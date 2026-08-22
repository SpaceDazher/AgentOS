"""Adversarial invariants regression net.

Covers the five invariants that must hold no matter what else changes:
  I1 audit atomicity — a guarded transition commits exactly one audit event;
     a rejected transition (expect_from CAS mismatch) commits none;
  I2 hash-chain integrity — full_chain_check() passes over a mixed event
     history and detects a direct payload tamper via SQL;
  I3 memory scoping — cross-goal memory_read raises MemoryScopeViolation
     while same-goal reads still work (independent of tests/test_security.py);
  I4 idempotency conflict — the same idempotency key with different args is
     denied and leaves a DENIED activity row behind;
  I5 one-time approvals — an approval nonce is consumed on first use; replay
     raises ApprovalInvalid and the row stays CONSUMED.

Each test gets its own throwaway sqlite DB in a per-test tmpdir (tests/base),
so tampering done here never outlives the test run.
"""
from tests.base import AgentOSTestCase

from agentos.gateway import (
    ApprovalInvalid,
    ApprovalRequired,
    IdempotencyConflict,
    MemoryScopeViolation,
    ToolContract,
)
from agentos.ids import canonical_json
from agentos.journal import TransitionError


def _audit_count(db) -> int:
    return db.conn.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0]


class TestAuditAtomicity(AgentOSTestCase):
    def test_valid_transition_audits_once_invalid_audits_never(self):
        goal_id = self.eng.create_goal("invariants atomicity concept")
        n0 = _audit_count(self.db)

        # Valid CAS transition: exactly ONE audit event.
        res = self.j.transition(
            table="goal", obj_id=goal_id, field="status",
            expect_from="DRAFT", to="ACTIVE", actor="test-harness",
            goal_id=goal_id)
        self.assertTrue(res["ok"])
        self.assertFalse(res["duplicate"])
        self.assertEqual(_audit_count(self.db), n0 + 1)
        status = self.db.conn.execute(
            "SELECT status FROM goal WHERE id=?", (goal_id,)).fetchone()[0]
        self.assertEqual(status, "ACTIVE")

        # Deliberately invalid: expect_from no longer matches (goal is ACTIVE).
        # The whole tx must roll back — no partial write, no audit event.
        with self.assertRaises(TransitionError):
            self.j.transition(
                table="goal", obj_id=goal_id, field="status",
                expect_from="DRAFT", to="CANCELLED", actor="test-harness",
                goal_id=goal_id)
        self.assertEqual(_audit_count(self.db), n0 + 1)
        # ...and the object really was left untouched.
        status = self.db.conn.execute(
            "SELECT status FROM goal WHERE id=?", (goal_id,)).fetchone()[0]
        self.assertEqual(status, "ACTIVE")
        ok, bad = self.j.full_chain_check()
        self.assertTrue(ok)
        self.assertIsNone(bad)


class TestHashChainTamperDetection(AgentOSTestCase):
    def _build_mixed_history(self) -> str:
        """create_goal + ~10 mixed events: plain appends + guarded transitions."""
        goal_id = self.make_goal_with_task()
        for i in range(6):
            self.j.append_event(goal_id, "test-harness", f"probe.append.{i}",
                                {"i": i, "note": f"mixed-history-{i}"})
        task_id = self.db.conn.execute(
            "SELECT id FROM task WHERE goal_id=?", (goal_id,)).fetchone()[0]
        self.j.transition(table="task", obj_id=task_id, expect_from="READY",
                          to="RUNNING", actor="test-harness", goal_id=goal_id)
        self.j.transition(table="task", obj_id=task_id, expect_from="RUNNING",
                          to="DONE", actor="test-harness", goal_id=goal_id,
                          extra_sets={"definition_of_done": "done when scripted success"})
        return goal_id

    def test_chain_verifies_then_sql_tamper_detected(self):
        self._build_mixed_history()
        n = _audit_count(self.db)
        self.assertGreaterEqual(n, 10)

        ok, bad = self.j.full_chain_check()
        self.assertTrue(ok)
        self.assertIsNone(bad)

        # Adversary edits history directly in SQL (row 3 of >= 10, so it has a
        # successor whose prev-pointer can no longer match the recomputed digest).
        seq3 = self.db.conn.execute(
            "SELECT seq FROM audit_event ORDER BY seq LIMIT 1 OFFSET 2"
        ).fetchone()[0]
        cur = self.db.conn.execute(
            "UPDATE audit_event SET payload_json='{\"tampered\":true}' WHERE seq=?",
            (seq3,))
        self.assertEqual(cur.rowcount, 1)

        ok, bad = self.j.full_chain_check()
        self.assertFalse(ok)
        self.assertIsNotNone(bad)
        # The break must surface at or after the tampered row.
        self.assertGreaterEqual(bad, seq3)
        # DB is per-test tmpdir (tests/base tearDown deletes it): tampering
        # cannot leak into any other test.


class TestMemoryScopingNegative(AgentOSTestCase):
    def test_cross_goal_memory_read_denied_owner_still_reads(self):
        g1 = self.make_goal_with_task()
        r1 = self.run_simple_task(g1)
        ctx1 = self.ctx_for(r1, g1)
        mid = self.gw.memory_write(ctx1, "note", "secret of goal1", "file://a")

        g2 = self.make_goal_with_task()
        r2 = self.run_simple_task(g2)
        ctx2 = self.ctx_for(r2, g2)
        with self.assertRaises(MemoryScopeViolation):
            self.gw.memory_read(ctx2, mid)

        # positive control: the owning scope still gets its own memory back
        got = self.gw.memory_read(ctx1, mid)
        self.assertEqual(got["content"], "secret of goal1")


class TestIdempotencyConflict(AgentOSTestCase):
    def test_same_key_different_args_denied_and_recorded(self):
        goal_id = self.make_goal_with_task()
        run_id = self.run_simple_task(goal_id)
        ctx = self.ctx_for(run_id, goal_id)
        self.gw.register(self.write_contract())
        c = self.gw.resolve("fs.write.handler")

        path = str(self.root / "out.txt")
        r1 = self.gw.invoke(ctx, c, {"path": path, "content": "v1"},
                            idempotency_key="intent-42")
        self.assertTrue(r1["ok"])

        # Same key, DIFFERENT args => detectable conflict, hard stop...
        with self.assertRaises(IdempotencyConflict):
            self.gw.invoke(ctx, c, {"path": path, "content": "v2-EVIL"},
                           idempotency_key="intent-42")

        # ...and the denial is recorded as a DENIED activity row carrying the
        # would-be (attacker) arguments.
        denied = self.db.conn.execute(
            "SELECT * FROM activity WHERE op_name='fs.write.handler'"
            " AND status='DENIED'").fetchall()
        self.assertEqual(len(denied), 1)
        self.assertEqual(denied[0]["args_canonical_json"],
                         canonical_json({"path": path, "content": "v2-EVIL"}))

        # The conflicting call must NOT have executed: exactly one success.
        succeeded = self.db.conn.execute(
            "SELECT COUNT(*) FROM activity WHERE op_name='fs.write.handler'"
            " AND status='SUCCEEDED'").fetchone()[0]
        self.assertEqual(succeeded, 1)


class TestApprovalOneTimeUse(AgentOSTestCase):
    def _dangerous_tool(self) -> ToolContract:
        return ToolContract(
            name="deploy.prod", version="1.0.0",
            input_schema={"type": "object",
                          "properties": {"target": {"type": "string"}},
                          "required": ["target"]},
            required_capability="cmd.local", effect_class="dangerous",
            idempotency="none")

    def test_nonce_is_single_use(self):
        goal_id = self.make_goal_with_task()   # normal tier => cmd.local granted
        run_id = self.run_simple_task(goal_id)
        ctx = self.ctx_for(run_id, goal_id)
        self.gw.register(self._dangerous_tool())
        c = self.gw.resolve("deploy.prod")

        # Without a nonce the dangerous tool is not even reachable.
        with self.assertRaises(ApprovalRequired):
            self.gw.invoke(ctx, c, {"target": "prod"})

        aid = self.gw.grant_approval(
            goal_id=goal_id, actor="requester", operation="invoke_tool",
            tool_name="deploy.prod", tool_version="1.0.0",
            args={"target": "prod"}, target="prod")
        nonce = self.db.conn.execute(
            "SELECT nonce FROM approval WHERE id=?", (aid,)).fetchone()[0]

        r1 = self.gw.invoke(ctx, c, {"target": "prod"}, approval_nonce=nonce)
        self.assertTrue(r1["ok"])
        self.assertEqual(
            self.db.conn.execute("SELECT status FROM approval WHERE id=?",
                                 (aid,)).fetchone()[0], "CONSUMED")

        # Second use of the SAME nonce: replay denied, approval stays consumed.
        with self.assertRaises(ApprovalInvalid):
            self.gw.invoke(ctx, c, {"target": "prod"}, approval_nonce=nonce)
        self.assertEqual(
            self.db.conn.execute("SELECT status FROM approval WHERE id=?",
                                 (aid,)).fetchone()[0], "CONSUMED")


if __name__ == "__main__":
    import unittest
    unittest.main()
