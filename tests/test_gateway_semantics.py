"""T05 idempotent replay + same-key-different-intent conflict; T06 unknown outcome
reconciliation; T08 stale owner/fencing."""
from tests.base import AgentOSTestCase
from agentos.gateway import (
    GatewayError, IdempotencyConflict, StaleOwnerError,
)


class TestIdempotency(AgentOSTestCase):
    def setUp(self):
        super().setUp()
        self.goal_id = self.make_goal_with_task()
        self.run_id = self.run_simple_task(self.goal_id)
        self.ctx = self.ctx_for(self.run_id, self.goal_id)
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


class TestReconciliation(AgentOSTestCase):
    def test_t06_unknown_outcome_requires_reconciliation(self):
        goal_id = self.make_goal_with_task()
        run_id = self.run_simple_task(goal_id)
        ctx = self.ctx_for(run_id, goal_id)
        self.gw.register(self.write_contract())
        c = self.gw.resolve("fs.write.handler")
        res = self.gw.invoke(ctx, c, {"path": str(self.root / "x.txt"),
                                      "content": "hi"}, idempotency_key="u1")
        self.gw.mark_unknown_outcome(res["activity_id"])
        unresolved = self.gw.unresolved_unknown_outcomes(goal_id)
        self.assertEqual(len(unresolved), 1)
        # gate must refuse while unresolved
        from agentos.gates import Gates
        self.ev.run(goal_id, "has_code")
        self.eng.submit_to_gate(goal_id)
        gate = Gates(self.db, self.j).evaluate_release(goal_id)
        self.assertEqual(gate["result"], "fail")
        self.assertTrue(any("UNKNOWN_OUTCOME" in r for r in gate["reasons"]))
        # reconcile (separate authorized op) then proceed
        self.gw.reconcile(res["activity_id"], True, "observed://file/x.txt")
        self.assertEqual(self.gw.unresolved_unknown_outcomes(goal_id), [])


class TestFencing(AgentOSTestCase):
    def test_t08_stale_owner_denied(self):
        goal_id = self.make_goal_with_task()
        run_id = self.run_simple_task(goal_id)
        ctx = self.ctx_for(run_id, goal_id)
        self.gw.register(self.write_contract())
        c = self.gw.resolve("fs.write.handler")
        # lease owner rewritten (reassignment) — old ctx must be fenced out
        self.db.conn.execute("UPDATE run SET lease_owner='run_NEW' WHERE id=?",
                             (run_id,))
        with self.assertRaises(StaleOwnerError):
            self.gw.invoke(ctx, c, {"path": str(self.root / "y.txt"),
                                    "content": "x"}, idempotency_key="f1")
