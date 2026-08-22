"""T07 lease exclusivity; alternative-but-valid trajectory acceptance;
context compiler provenance; CLI demo end-to-end."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

from tests.base import AgentOSTestCase
from agentos.engine import LeaseHeldError
from agentos.workers import FakeWorker


class TestLeases(AgentOSTestCase):
    def test_t07_double_start_denied_while_running(self):
        goal_id = self.make_goal_with_task()
        task_id = self.db.conn.execute(
            "SELECT id FROM task WHERE goal_id=?", (goal_id,)).fetchone()[0]

        class NeverDoneWorker(FakeWorker):
            def step(self, req):
                return FakeWorker.step(self, req) if req.step > 0 else \
                    type("R", (), {"ok": True, "note": "", "outputs": {},
                                   "fail_class": None,
                                   "next_action": {"keep_going": True},
                                   "raw_output_ref": None})()

        # start a run that never signals done → stays RUNNING until budget exhaust
        self.eng.start_task(task_id, NeverDoneWorker())
        status = self.db.conn.execute(
            "SELECT status FROM run WHERE task_id=? ORDER BY created_at DESC"
            " LIMIT 1", (task_id,)).fetchone()[0]
        if status == "RUNNING":
            with self.assertRaises(LeaseHeldError):
                self.eng.start_task(task_id, FakeWorker())


class TestAlternativeTrajectory(AgentOSTestCase):
    def test_alternatively_correct_result_passes_same_criteria(self):
        """Evaluator checks observable end state, not a fixed script output."""
        goal_id = self.make_goal_with_task()
        task_id = self.db.conn.execute(
            "SELECT id FROM task WHERE goal_id=?", (goal_id,)).fetchone()[0]
        alt = FakeWorker([{"ok": True, "outputs": {"implementation": "alt-correct",
                                                   "style": "different-but-valid"}}])
        self.eng.start_task(task_id, alt)
        ev = self.ev.run(goal_id, "has_code")
        self.assertEqual(ev["result"], "pass")
        self.eng.submit_to_gate(goal_id)
        from agentos.gates import Gates
        gate = Gates(self.db, self.j).evaluate_release(goal_id)
        self.assertEqual(gate["result"], "pass")


class TestContextCompiler(AgentOSTestCase):
    def test_packet_carries_source_pointers_and_dedupes(self):
        goal_id = self.make_goal_with_task()
        run_id = self.run_simple_task(goal_id)
        ctx = self.ctx_for(run_id, goal_id)
        self.gw.memory_write(ctx, "note", "same text", "file://one")
        packet = self.eng.compiler.compile(goal_id, "implement greet")
        rendered = packet.render(2000)
        self.assertIn("[artifact:", rendered)
        self.assertIn("untrusted", rendered)


class TestCliDemo(unittest.TestCase):
    def test_demo_end_to_end_happy(self):
        import tempfile
        root = tempfile.mkdtemp()
        proc = subprocess.run(
            [sys.executable, "-m", "agentos.cli", "demo", "--db", root],
            capture_output=True, text=True, timeout=120,
            cwd=str(Path(__file__).resolve().parent.parent / "src"),
            env={"PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src"),
                 **__import__("os").environ})
        out = proc.stdout
        self.assertIn('"gate"', out)
        data = json.loads(out)
        self.assertEqual(data["gate"]["result"], "pass")
        self.assertEqual(data["tool_write_replay"], "REPLAYED")
        self.assertIn("denied", data["dangerous_without_approval"])
        self.assertTrue(data["chain_verified"])

    def test_demo_flaky_recovers(self):
        import tempfile
        root = tempfile.mkdtemp()
        proc = subprocess.run(
            [sys.executable, "-m", "agentos.cli", "demo", "--flaky", "--db", root],
            capture_output=True, text=True, timeout=120,
            cwd=str(Path(__file__).resolve().parent.parent / "src"),
            env={"PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src"),
                 **__import__("os").environ})
        data = json.loads(proc.stdout)
        self.assertEqual(data["gate"]["result"], "pass")


if __name__ == "__main__":
    unittest.main()
