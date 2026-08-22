"""T05 idempotent replay + same-key-different-intent conflict; T06 unknown outcome
reconciliation; T08 stale owner/fencing.

Review-fix note: gateway mutating ops now require the persisted run to be
RUNNING with an unexpired lease (F7), so these tests use open_live_run() — a
long-lived interactive worker session — instead of invoking after completion.
"""
from tests.base import AgentOSTestCase
from pathlib import Path
from agentos.gateway import (
    GatewayError, IdempotencyConflict, StaleOwnerError,
)


class TestIdempotency(AgentOSTestCase):
    def setUp(self):
        super().setUp()
        self.goal_id = self.make_goal_with_task()
        self.run_id, self.ctx = self.open_live_run(self.goal_id)
        self.gw.register(self.write_contract())

    def _args(self, content="a"):
        return {"path": str(self.root / "ws-out" / "f.txt"), "content": content}

    def test_t05a_same_key_same_args_replays(self):
        c = self.gw.resolve("fs.write.handler")
        r1 = self.gw.invoke(self.ctx, c, self._args("a"), idempotency_key="k1")
        r2 = self.gw.invoke(self.ctx, c, self._args("a"), idempotency_key="k1")
        self.assertEqual(r1["status"], "SUCCEEDED")
        self.assertEqual(r2["status"], "REPLAYED")
        self.assertEqual(r1["digest"], r2["digest"])

    def test_t05b_same_key_different_args_conflicts(self):
        c = self.gw.resolve("fs.write.handler")
        self.gw.invoke(self.ctx, c, self._args("a"), idempotency_key="k2")
        with self.assertRaises(IdempotencyConflict):
            self.gw.invoke(self.ctx, c, self._args("DIFFERENT"), idempotency_key="k2")

    def test_t05c_incomplete_intent_never_reexecutes(self):
        """F5: an intent recorded without an outcome must not re-run the handler;
        it returns UNKNOWN_OUTCOME and demands reconciliation."""
        c = self.gw.resolve("fs.write.handler")
        calls = {"n": 0}

        def counting_handler(path, content):
            calls["n"] += 1
            if calls["n"] == 1:
                # simulate crash AFTER effect, BEFORE outcome recorded
                raise RuntimeError("simulated crash mid-effect")
            return {"written": path}

        contract = self.write_contract(handler=counting_handler)
        self.db.conn.execute("DELETE FROM tool_contract WHERE name='fs.write.handler'")
        self.gw.register(contract)
        c2 = self.gw.resolve("fs.write.handler")
        r1 = self.gw.invoke(self.ctx, c2, self._args("crashy"), idempotency_key="kc")
        self.assertEqual(r1["status"], "FAILED")  # handler raised -> known failure
        # simulate the crash window: intent exists, no digest
        self.db.conn.execute(
            "UPDATE idempotency_key SET outcome_digest=NULL WHERE key_hash=?",
            (__import__("agentos.ids", fromlist=["sha256_text"])
             .sha256_text("kc|" + c2.identity),))
        calls["n"] = 1  # next successful call would be execution #2 if retried
        r2 = self.gw.invoke(self.ctx, c2, self._args("crashy"), idempotency_key="kc")
        self.assertEqual(r2["status"], "UNKNOWN_OUTCOME")
        self.assertTrue(r2.get("reconciliation_required"))
        self.assertEqual(calls["n"], 1)  # handler NOT re-executed


class TestReconciliation(AgentOSTestCase):
    def setUp(self):
        super().setUp()
        self.goal_id = self.make_goal_with_task()
        self.run_id, ctx = self.open_live_run(self.goal_id)
        self.ctx = ctx
        self.gw.register(self.write_contract())

    def test_t06_unknown_outcome_requires_reconciliation(self):
        c = self.gw.resolve("fs.write.handler")
        res = self.gw.invoke(self.ctx, c, {"path": str(self.root / "x.txt"),
                                           "content": "hi"}, idempotency_key="u1")
        self.gw.mark_unknown_outcome(res["activity_id"])
        unresolved = self.gw.unresolved_unknown_outcomes(self.goal_id)
        self.assertEqual(len(unresolved), 1)
        # F8: failed observation yields RECONCILED_FAILED and stays blocking
        rec = self.gw.reconcile(res["activity_id"], False, "observed://file/x.txt")
        self.assertFalse(rec["ok"])
        self.assertEqual(rec["status"], "RECONCILED_FAILED")
        # finish the run so the goal can legally reach the gate; the gate must
        # STILL fail because of the reconciled-failed activity
        self.eng.complete_live_run(self.ctx, outputs={"done": True})
        self.ev.run(self.goal_id, "has_code")
        self.eng.submit_to_gate(self.goal_id)
        from agentos.gates import Gates
        gate2 = Gates(self.db, self.j).evaluate_release(self.goal_id)
        self.assertEqual(gate2["result"], "fail")
        self.assertTrue(any("reconciled-failed" in r for r in gate2["reasons"]))

    def test_t06b_successful_reconciliation_unblocks_gate(self):
        from agentos.gates import Gates
        c = self.gw.resolve("fs.write.handler")
        res = self.gw.invoke(self.ctx, c, {"path": str(self.root / "x2.txt"),
                                           "content": "hi"},
                             idempotency_key="u2")
        self.gw.mark_unknown_outcome(res["activity_id"])
        rec = self.gw.reconcile(res["activity_id"], True, "observed://file/x2.txt")
        self.assertTrue(rec["ok"])
        self.assertEqual(rec["status"], "RECONCILED_SUCCEEDED")
        self.assertEqual(self.gw.unresolved_unknown_outcomes(self.goal_id), [])
        # real artifact content so tests_present passes (F-P0-3)
        src = ("def greet(name):\n"
               "    return f'hello, {name}'\n\n\n"
               "def test_greet():\n"
               "    assert greet('world') == 'hello, world'\n")

        def _write(path, content):
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"written": str(p)}

        self.gw.register(self.write_contract(handler=_write))
        w = self.gw.invoke(self.ctx, self.gw.resolve("fs.write.handler"),
                           {"path": str(Path(self.ctx.workspace_path) / "greet.py"),
                            "content": src}, idempotency_key="u2b")
        self.assertEqual(w["status"], "SUCCEEDED")
        self.eng.complete_live_run(self.ctx, outputs={"files": {"greet.py": src}})
        self.ev.run(self.goal_id, "has_code")
        self.eng.submit_to_gate(self.goal_id)
        gate = Gates(self.db, self.j).evaluate_release(self.goal_id)
        self.assertEqual(gate["result"], "pass")


class TestFencing(AgentOSTestCase):
    def test_t08_stale_owner_denied(self):
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract())
        c = self.gw.resolve("fs.write.handler")
        # lease owner rewritten (reassignment) — old ctx must be fenced out
        self.db.conn.execute("UPDATE run SET lease_owner='run_NEW' WHERE id=?",
                             (run_id,))
        with self.assertRaises(StaleOwnerError):
            self.gw.invoke(ctx, c, {"path": str(self.root / "y.txt"),
                                    "content": "x"}, idempotency_key="f1")

    def test_t08b_expired_lease_denied_and_completed_run_denied(self):
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id, lease_minutes=30)
        self.gw.register(self.write_contract())
        c = self.gw.resolve("fs.write.handler")
        # expire the lease in place: still RUNNING but stale
        self.db.conn.execute(
            "UPDATE run SET lease_expires_at='2000-01-01T00:00:00Z' WHERE id=?",
            (run_id,))
        with self.assertRaises(StaleOwnerError):
            self.gw.invoke(ctx, c, {"path": str(self.root / "e.txt"),
                                    "content": "x"}, idempotency_key="f2")
        # restore validity, complete the run, then writes must STILL be denied
        self.db.conn.execute(
            "UPDATE run SET lease_expires_at='2099-01-01T00:00:00Z' WHERE id=?",
            (run_id,))
        self.eng.complete_live_run(ctx)
        with self.assertRaises(StaleOwnerError):
            self.gw.invoke(ctx, c, {"path": str(self.root / "z.txt"),
                                    "content": "x"}, idempotency_key="f3")

    def test_t08c_fence_tokens_monotonic_persisted(self):
        goal_id = self.make_goal_with_task()
        _, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract())
        c = self.gw.resolve("fs.write.handler")
        r1 = self.gw.invoke(ctx, c, {"path": str(self.root / "fa.txt"),
                                     "content": "1"})
        r2 = self.gw.invoke(ctx, c, {"path": str(self.root / "fb.txt"),
                                     "content": "2"})
        f1 = self.db.conn.execute(
            "SELECT detail_json FROM activity WHERE id=?",
            (r1["activity_id"],)).fetchone()[0]
        f2 = self.db.conn.execute(
            "SELECT detail_json FROM activity WHERE id=?",
            (r2["activity_id"],)).fetchone()[0]
        import json as _json
        v1 = _json.loads(f1)["fence"]
        v2 = _json.loads(f2)["fence"]
        self.assertEqual(v2, v1 + 1)
        row = self.db.conn.execute(
            "SELECT value FROM fence_counter WHERE id=1").fetchone()[0]
        self.assertGreaterEqual(row, v2)
