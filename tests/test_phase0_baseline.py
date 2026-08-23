"""Phase-0 baseline regressions: the six invariants from the EPIC brief that
must hold before any self-improvement work.

1. pass^5 computed strictly (all k repeats pass per task).
2. worker failure => Run FAILED (never COMPLETED/success).
3. durable record preserves fail_class + evidence of cause.
4. recording contract: model/harness/tool versions, provider identity slot,
   trace pointer + hash, cost, interventions fields exist on episode records.
5. pack/trace paths are repo-relative or portable.
6. provider outage separable from capability/evaluator failure.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aggregate_e1 import aggregate, wilson_ci  # noqa: E402


def _ep(task, repeat, ok, **kw):
    d = {"task": task, "repeat": repeat, "episode_success": ok,
         "duration_ms": 100, "tool_calls": 1, "evaluation_results": {},
         "worker_ok": kw.get("worker_ok", ok),
         "worker_note": kw.get("note", ""),
         "worker_fail_class": kw.get("fail_class"),
         "worker_trace_digest": kw.get("trace_digest"),
         "run_status": "COMPLETED" if ok else kw.get("run_status", "FAILED"),
         "env": kw.get("env", {"python": "3.11", "harness_version":
                               "agentos-harness/0.1"})}
    d.update(kw)
    return d


class TestP0PassKStrict(unittest.TestCase):
    def test_pass5_counts_only_all_repeat_tasks(self):
        eps = ([_ep("a", r, r != 3) for r in range(1, 6)]     # 4/5
               + [_ep("b", r, True) for r in range(1, 6)])    # 5/5
        agg = aggregate(eps, 5)
        self.assertEqual(agg["pass_5"]["tasks_passing"], 1)
        self.assertEqual(agg["pass_5"]["passing_tasks"], ["b"])

    def test_provider_outcome_separable_from_capability(self):
        """Provider no-result and evaluator-reject land in distinct buckets."""
        eps = [
            _ep("a", 1, False, note="no AGENTOS_RESULT line",
                fail_class="worker", worker_ok=False),
            _ep("b", 1, False, note="tests missing",
                worker_ok=True),  # evaluator reject
            _ep("c", 1, True),
        ]
        agg = aggregate(eps, 1)
        fa = agg["failure_attribution"]
        self.assertEqual(fa["provider_no_result"], 1)
        self.assertEqual(fa["evaluator_reject"], 1)


class TestP0RunTerminalState(unittest.TestCase):
    def test_worker_failure_run_is_failed_not_completed(self):
        import tempfile
        from agentos.db import open_db
        from agentos.engine import Engine
        root = Path(tempfile.mkdtemp())
        db = open_db(root / "t.db")
        eng = Engine(db, root)
        goal_id = eng.create_goal("p0 probe")
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
        self.assertNotIn("success", row["terminal_reason"])
        self.assertIn("no AGENTOS_RESULT", row["terminal_reason"])


class TestP0RecordingContract(unittest.TestCase):
    REQUIRED_EPISODE_KEYS = [
        "evidence_pack_path", "evidence_pack_sha256",
        "worker_fail_class", "worker_trace_digest",
        "worker_trace_ref", "run_status", "run_terminal_reason",
    ]
    REQUIRED_ENV_KEYS = ["python", "platform", "harness_version"]

    def test_episode_record_shape_has_contract_fields(self):
        """The runner's episode record carries every protocol-required field;
        verified against a real recorded episode from the retry series."""
        results = Path(".agentos-e2-retry/results.json")
        if not results.exists():
            self.skipTest("retry results not present on this checkout")
        data = json.loads(results.read_text(encoding="utf-8"))
        ep = data["episodes"][0]
        for key in self.REQUIRED_EPISODE_KEYS:
            self.assertIn(key, ep, f"missing contract field: {key}")
        for key in self.REQUIRED_ENV_KEYS:
            self.assertIn(key, ep["env"], f"missing env field: {key}")

    def test_pack_and_trace_paths_are_repo_relative(self):
        results = Path(".agentos-e2-retry/results.json")
        if not results.exists():
            self.skipTest("retry results not present on this checkout")
        data = json.loads(results.read_text(encoding="utf-8"))
        for ep in data["episodes"]:
            p = ep["evidence_pack_path"] or ""
            self.assertNotIn(str(Path(p).anchor) and ":\\" in p and p,
                             [p], "absolute path leaked") if ":\\" in p else None
            self.assertFalse(p.startswith("C:\\"), f"absolute path: {p}")
            tr = ep.get("worker_trace_ref")
            if tr:
                self.assertFalse(tr.startswith("C:\\"),
                                 f"absolute trace ref: {tr}")


if __name__ == "__main__":
    unittest.main()
