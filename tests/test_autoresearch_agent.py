"""Agent-driven autoresearch campaign regressions (ROADMAP item 0).

The candidate generator is a host-owned apply_host callable that spawns a
worker and replays its DECLARED effects into the isolated worktree. These
tests pin the three canonical outcomes of the ADR-0008 loop with a
deterministic FakeWorker (no LLM, no network):
  KEEP        — improvement above noise floor AND holdout pass
  DISCARD     — no improvement above noise floor
  QUARANTINED — dev-perfect candidate caught by the mandatory holdout,
                or an out-of-scope file write
"""
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "eval"))

from eval.run_autoresearch import (  # noqa: E402
    build_manifest, dev_eval_fn, generate_candidate, holdout_fn,
    make_apply_host)
from agentos.autoresearch import Autoresearch  # noqa: E402
from agentos.db import open_db  # noqa: E402
from agentos.engine import Engine  # noqa: E402
from agentos.workers import FakeWorker  # noqa: E402


class AgentCampaignTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = Path(tempfile.mkdtemp(prefix="agentos-campaign-"))
        self.db = open_db(self.root / "agentos.db")
        self.eng = Engine(self.db, self.root)
        self.goal = self.eng.create_goal("campaign goal", actor="t")
        self.ar = Autoresearch(self.db, self.root, stage_evals=None,
                               repo_source=_REPO)

    def _run(self, worker, hypothesis="h"):
        manifest, eval_hashes, corpus_hash = build_manifest(budget=1)
        self.assertTrue(self.ar.verify_frozen(manifest, eval_hashes,
                                              corpus_hash))
        return self.ar.run_campaign(
            manifest,
            scenarios=[{"hypothesis": hypothesis,
                        "candidate_ref": "fake",
                        "apply_host": make_apply_host(worker, 1, hypothesis),
                        "noise_floor": 0.02}],
            dev_eval_fn=dev_eval_fn,
            holdout_fn=holdout_fn,
            goal_id=self.goal)

    def test_good_candidate_is_kept_with_holdout_pass(self):
        worker = FakeWorker([{"ok": True, "outputs": {"files": {
            "candidate/add.py": "def add(a, b):\n    return a + b\n"}}}])
        results = self._run(worker)
        self.assertEqual(results[0]["status"], "KEEP", results)

    def test_broken_candidate_is_discarded(self):
        worker = FakeWorker([{"ok": True, "outputs": {"files": {
            "candidate/add.py": "def add(a, b):\n    return a - b\n"}}}])
        results = self._run(worker)
        self.assertEqual(results[0]["status"], "DISCARD", results)

    def test_dev_perfect_candidate_quarantined_by_holdout(self):
        worker = FakeWorker([{"ok": True, "outputs": {"files": {
            "candidate/add.py":
                "def add(a, b):\n"
                "    if a == b:\n"
                "        return a + b + 1\n"
                "    return a + b\n"}}}])
        results = self._run(worker)
        self.assertEqual(results[0]["status"], "QUARANTINED", results)
        self.assertIn("holdout", results[0]["rationale"].lower())

    def test_out_of_scope_write_quarantines(self):
        def rogue(wt):
            (wt / "spec" / "evil.md").write_text("outside scope",
                                                 encoding="utf-8")
            return {"files": ["spec/evil.md"]}

        manifest, _, _ = build_manifest(budget=1)
        results = self.ar.run_campaign(
            manifest,
            scenarios=[{"hypothesis": "scope probe", "candidate_ref": "rogue",
                        "apply_host": rogue}],
            dev_eval_fn=dev_eval_fn, holdout_fn=holdout_fn,
            goal_id=self.goal)
        self.assertEqual(results[0]["status"], "QUARANTINED", results)
        self.assertEqual(results[-1].get("reason"), "security_violation")

    def test_worker_failure_becomes_crash(self):
        worker = FakeWorker([{"ok": False, "fail_class": "worker"}])
        results = self._run(worker)
        self.assertEqual(results[0]["status"], "CRASH", results)

    def test_generate_candidate_writes_declared_files(self):
        import tempfile
        wt = Path(tempfile.mkdtemp(prefix="agentos-cand-"))
        worker = FakeWorker([{"ok": True, "outputs": {"files": {
            "candidate/add.py": "def add(a, b):\n    return a + b\n"}}}])
        info = generate_candidate(wt, worker, "hyp", "dod", 1)
        self.assertEqual(info["files"], ["candidate/add.py"])
        self.assertTrue((wt / "candidate" / "add.py").exists())


if __name__ == "__main__":
    unittest.main()
