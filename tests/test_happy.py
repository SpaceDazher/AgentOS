"""T01 happy path + T14 audit atomicity + T15 old artifact version preserved."""
from tests.base import AgentOSTestCase
from agentos.gates import Gates
from agentos.evidence_pack import build as build_evidence
from agentos.workers import FakeWorker
from pathlib import Path
from unittest.mock import patch


class TestHappyPath(AgentOSTestCase):
    def test_t01_full_vertical_accepts(self):
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        # real artifact through the gateway (F-P0-3 evaluator checks content)
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
        res = self.gw.invoke(ctx, self.gw.resolve("fs.write.handler"),
                             {"path": str(Path(ctx.workspace_path) / "greet.py"),
                              "content": src}, idempotency_key="hp1")
        self.assertEqual(res["status"], "SUCCEEDED")
        self.eng.complete_live_run(ctx, outputs={"files": {"greet.py": src}})
        ev = self.ev.run(goal_id, "has_code")
        self.assertEqual(ev["result"], "pass")
        self.eng.submit_to_gate(goal_id)
        gate = Gates(self.db, self.j).evaluate_release(goal_id)
        self.assertEqual(gate["result"], "pass")
        status = self.db.conn.execute(
            "SELECT status FROM goal WHERE id=?", (goal_id,)).fetchone()[0]
        self.assertEqual(status, "ACCEPTED")
        pack = build_evidence(self.db, self.root, goal_id)
        self.assertTrue(pack["pack"]["audit"]["chain_verified"])
        self.assertTrue(pack["pack"]["accepted"])

    def test_t14_transition_and_audit_atomic(self):
        goal_id = self.make_goal_with_task()
        n_before = self.db.conn.execute(
            "SELECT COUNT(*) FROM audit_event").fetchone()[0]
        # a successful transition adds exactly one event
        from agentos.engine import LeaseHeldError
        self.run_simple_task(goal_id)
        rows = self.db.conn.execute(
            "SELECT event_type FROM audit_event ORDER BY seq DESC LIMIT 1"
        ).fetchall()
        # force a failed transition: no event must appear
        from agentos.journal import TransitionError
        goal_status = self.db.conn.execute(
            "SELECT status FROM goal WHERE id=?", (goal_id,)).fetchone()[0]
        with self.assertRaises(TransitionError):
            self.j.transition(table="goal", obj_id=goal_id, expect_from="NOPE",
                              to="ACCEPTED", actor="gate", goal_id=goal_id)
        n_after_fail = self.db.conn.execute(
            "SELECT COUNT(*) FROM audit_event").fetchone()[0]
        self.assertEqual(n_after_fail, n_before + 4)  # only successful run events
        ok, bad = self.j.full_chain_check()
        self.assertTrue(ok)

    def test_t15_failed_edit_preserves_old_artifact(self):
        goal_id = self.make_goal_with_task()
        self.run_simple_task(goal_id)
        v1 = self.db.conn.execute(
            "SELECT id, content_sha256 FROM artifact_version WHERE goal_id=?"
            " AND kind='code' ORDER BY version", (goal_id,)).fetchall()
        # a second completed run supersedes rather than overwrites
        task_id = self.db.conn.execute(
            "SELECT id FROM task WHERE goal_id=?", (goal_id,)).fetchone()[0]
        self.db.conn.execute(
            "UPDATE task SET status='READY' WHERE id=?", (task_id,))
        final = self.eng.drive_task(task_id, FakeWorker())
        self.assertEqual(final, "DONE")  # second run completes and supersedes
        versions = self.db.conn.execute(
            "SELECT version, status, content_sha256 FROM artifact_version"
            " WHERE goal_id=? AND kind='code' ORDER BY version", (goal_id,)).fetchall()
        self.assertGreaterEqual(len(versions), 2)
        self.assertEqual(versions[0]["status"], "SUPERSEDED")
        self.assertEqual(versions[0]["content_sha256"], v1[0]["content_sha256"])
        rel = self.db.conn.execute(
            "SELECT COUNT(*) FROM relation_assertion WHERE rel='SUPERSEDES'"
        ).fetchone()[0]
        self.assertGreaterEqual(rel, 1)

    def test_run_and_task_completion_roll_back_together(self):
        """A crash between completion steps must not persist a split state."""
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        artifacts_before = self.db.conn.execute(
            "SELECT COUNT(*) FROM artifact_version WHERE goal_id=?",
            (goal_id,)).fetchone()[0]

        with patch.object(self.eng, "_store_artifact",
                          side_effect=RuntimeError("simulated crash")):
            with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                self.eng.complete_live_run(ctx, outputs={"tick": 1})

        run_status = self.db.conn.execute(
            "SELECT status FROM run WHERE id=?", (run_id,)).fetchone()[0]
        task_status = self.db.conn.execute(
            "SELECT status FROM task WHERE id=?", (ctx.task_id,)).fetchone()[0]
        artifacts_after = self.db.conn.execute(
            "SELECT COUNT(*) FROM artifact_version WHERE goal_id=?",
            (goal_id,)).fetchone()[0]
        self.assertEqual((run_status, task_status), ("RUNNING", "RUNNING"))
        self.assertEqual(artifacts_after, artifacts_before)
        self.assertEqual(self.db.conn.execute(
            "SELECT COUNT(*) FROM audit_event WHERE goal_id=?"
            " AND event_type IN ('run.completed','task.done')",
            (goal_id,)).fetchone()[0], 0)
        self.assertEqual(self.j.full_chain_check(), (True, None))
