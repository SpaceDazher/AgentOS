"""R4 regressions: pass^5 strictness, failure attribution, run terminal state
on worker failure, repo-relative path recording."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aggregate_e1 import aggregate, wilson_ci  # noqa: E402


def _ep(task: str, repeat: int, ok: bool, **kw) -> dict:
    d = {"task": task, "repeat": repeat, "episode_success": ok,
         "duration_ms": 100, "tool_calls": 1,
         "evaluation_results": {},
         # worker_ok=True means the worker step succeeded; a failed episode
         # with worker_ok=True is an evaluator/gate rejection.
         "worker_ok": kw.get("worker_ok", ok),
         "worker_note": kw.get("note", ""),
         "worker_fail_class": kw.get("fail_class"),
         "run_status": "COMPLETED" if ok else kw.get("run_status", "COMPLETED")}
    d.update(kw)
    return d


class TestPassKStrict(unittest.TestCase):
    def test_task_with_4_of_5_does_not_count(self):
        """R4-P1: greet-basic 4/5 must NOT count toward pass^5."""
        eps = []
        for r in range(1, 6):
            eps.append(_ep("greet", r, r != 4))       # fails repeat 4
        for r in range(1, 6):
            eps.append(_ep("clamp", r, True))          # 5/5
        agg = aggregate(eps, 5)
        self.assertEqual(agg["pass_5"]["tasks_passing"], 1)
        self.assertEqual(agg["pass_5"]["rate"], 0.5)   # 1 of 2 tasks
        self.assertEqual(agg["pass_5"]["passing_tasks"], ["clamp"])
        lo, hi = wilson_ci(1, 2)
        self.assertEqual(agg["pass_5"]["wilson95"], [lo, hi])

    def test_all_pass_counts_all(self):
        eps = [_ep(f"t{t}", r, True) for t in range(3) for r in range(1, 6)]
        agg = aggregate(eps, 5)
        self.assertEqual(agg["pass_5"]["rate"], 1.0)
        self.assertEqual(len(agg["pass_5"]["passing_tasks"]), 3)


class TestFailureAttribution(unittest.TestCase):
    def test_provider_vs_evaluator_reject_split(self):
        eps = [
            _ep("a", 1, False, note="no AGENTOS_RESULT line",
                fail_class="worker", worker_ok=False, run_status="FAILED"),
            _ep("b", 1, False, note="hermes timeout",
                fail_class="deadline", worker_ok=False, run_status="FAILED"),
            _ep("c", 1, False, note="tests missing",
                fail_class=None, worker_ok=True, run_status="COMPLETED"),
            _ep("d", 1, True),
        ]
        agg = aggregate(eps, 1)
        self.assertEqual(agg["failure_attribution"]["provider_no_result"], 2)
        self.assertEqual(agg["failure_attribution"]["evaluator_reject"], 1)


class TestRunTerminalStateOnWorkerFailure(unittest.TestCase):
    """The runner must mark the run FAILED (not COMPLETED) when the worker
    step returns not-ok — packs then document the real cause."""

    def test_engine_fail_run_sets_failed_terminal_reason(self):
        from agentos.db import open_db
        from agentos.engine import Engine
        import tempfile
        root = Path(tempfile.mkdtemp())
        db = open_db(root / "t.db")
        eng = Engine(db, root)
        goal_id = eng.create_goal("probe")
        eng.refine_spec(goal_id, "spec", criteria=[
            {"criterion_id": "has_code", "kind": "tests_present"}])
        eng.activate_goal(goal_id)
        eng.plan_tasks(goal_id, [{"key": "impl", "title": "T",
                                  "definition_of_done": "D"}])
        eng.schedule_ready_tasks(goal_id)
        task_id = db.conn.execute(
            "SELECT id FROM task WHERE goal_id=?", (goal_id,)).fetchone()[0]
        run_id, ctx = eng.open_run(task_id)
        eng.fail_run(run_id, goal_id, "worker", "no AGENTOS_RESULT line")
        row = db.conn.execute(
            "SELECT status, terminal_reason FROM run WHERE id=?",
            (run_id,)).fetchone()
        self.assertEqual(row["status"], "FAILED")
        self.assertIn("no AGENTOS_RESULT", row["terminal_reason"])


if __name__ == "__main__":
    unittest.main()
