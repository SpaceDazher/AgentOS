"""R5 regressions: fail-closed stage gates, goal binding, llm_judge advisory
enforcement + provenance, immutable decisions, real worktree autoresearch,
wiki stale-note removal + redaction + dangling refs, pack goal scoping."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agentos.db import open_db  # noqa: E402
from agentos.stage_evals import StageEvalError, StageEvals  # noqa: E402


class R5Case(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = Path(tempfile.mkdtemp())
        self.db = open_db(self.root / "t.db")
        self.se = StageEvals(self.db, self.root)
        for gid in ("goal_A", "goal_B"):
            self.db.conn.execute(
                "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
                (gid, "probe", "ACTIVE"))
        self.db.conn.commit() if hasattr(self.db.conn, "commit") else None

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass


class TestFailClosedGates(R5Case):
    def _defn(self):
        return self.se.define(stage="concept", kind="deterministic",
                              metric="clarity", threshold=0.8)

    def test_empty_required_set_fails_closed(self):
        gate = self.se.stage_gate("concept", [], goal_id="goal_A", artifact_chain_hash="chain-A")
        self.assertEqual(gate["decision"], "fail")

    def test_no_runs_for_goal_fails(self):
        did, _ = self._defn()
        gate = self.se.stage_gate("concept", [did], goal_id="goal_B", artifact_chain_hash="chain-A")
        self.assertEqual(gate["decision"], "fail")

    def test_cross_goal_reuse_impossible(self):
        """A passing run for goal_A must not satisfy goal_B's gate."""
        did, _ = self._defn()
        case = {"id": "c1"}
        self.se.run_case(did, case, lambda c: (True, {}), goal_id="goal_A", artifact_chain_hash="chain-A")
        ok_gate = self.se.stage_gate("concept", [did], goal_id="goal_A", artifact_chain_hash="chain-A")
        cross_gate = self.se.stage_gate("concept", [did], goal_id="goal_B", artifact_chain_hash="chain-A")
        self.assertEqual(ok_gate["decision"], "pass")
        self.assertEqual(cross_gate["decision"], "fail")


class TestLLMJudgeAdvisoryOnly(R5Case):
    def test_required_llm_judge_refused_at_define(self):
        with self.assertRaises(StageEvalError):
            self.se.define(stage="verification", kind="llm_judge",
                           metric="conformity", threshold=0.9,
                           required=True, prompt_version="p1",
                           rubric_version="r1")

    def test_judge_provenance_versions_must_match_definition(self):
        did, _ = self.se.define(stage="verification", kind="llm_judge",
                                metric="conformity", threshold=0.9,
                                required=False, prompt_version="p1",
                                rubric_version="r1")
        case = {"id": "c"}
        with self.assertRaises(StageEvalError):
            self.se.run_case(did, case, lambda c: (True, {}), goal_id="goal_A",
                             artifact_chain_hash="chain-A",
                             judge={"model_id": "m", "prompt_version": "pX",
                                    "rubric_version": "r1"})
        r = self.se.run_case(did, case, lambda c: (True, {}), goal_id="goal_A",
                             artifact_chain_hash="chain-A",
                             judge={"model_id": "m", "prompt_version": "p1",
                                    "rubric_version": "r1"})
        self.assertEqual(r["outcome"], "pass")


class TestImmutableDecisions(R5Case):
    def _defn(self):
        return self.se.define(stage="concept", kind="deterministic",
                              metric="clarity", threshold=0.8)

    def test_stage_gate_and_experiment_are_append_only(self):
        did, _ = self._defn()
        gate = self.se.stage_gate("concept", [did], goal_id="goal_A",
                                  artifact_chain_hash="chain-A")
        with self.assertRaises(Exception):
            self.db.conn.execute(
                "UPDATE stage_gate SET decision='pass' WHERE id=?",
                (gate["stage_gate_id"],))
        from agentos.autoresearch import Autoresearch, make_manifest
        ar = Autoresearch(self.db, self.root, self.se)
        cid = ar.create_campaign(
            make_manifest(baseline_ref="b", primary_metric="m",
                          mutable_scope=["src/x.py"],
                          frozen_eval_hashes={"e": "h"},
                          corpus_hash="c", budget=2),
            "probe", goal_id="goal_A")
        eid = ar.record_experiment(cid, "hyp", "base", "cand",
                                   ["src/x.py"], {}, "KEEP", "why",
                                   goal_id="goal_A")
        with self.assertRaises(Exception):
            self.db.conn.execute(
                "UPDATE experiment SET status='QUARANTINED' WHERE id=?",
                (eid,))

    def test_experiment_goal_must_match_campaign_owner(self):
        """R7: an experiment whose goal differs from the campaign owner is
        refused — cross-goal insertion is impossible."""
        from agentos.autoresearch import Autoresearch, AutoresearchError
        from agentos.autoresearch import (
            Autoresearch, AutoresearchError, make_manifest)
        ar = Autoresearch(self.db, self.root, self.se)
        cid = ar.create_campaign(
            make_manifest(baseline_ref="b", primary_metric="m",
                          mutable_scope=["src/x.py"],
                          frozen_eval_hashes={"e": "h"},
                          corpus_hash="c", budget=2),
            "probe", goal_id="goal_A")
        with self.assertRaises(AutoresearchError):
            ar.record_experiment(cid, "hyp", "base", "cand", ["src/x.py"],
                                 {}, "KEEP", "why", goal_id="goal_B")


class TestRealWorktreeCampaign(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.repo = Path(tempfile.mkdtemp())
        # fake repo layout the runner seeds worktrees from
        (self.repo / "src" / "agentos").mkdir(parents=True)
        (self.repo / "src" / "agentos" / "prompts.py").write_text(
            "PROMPT='v1'\n", encoding="utf-8")
        frozen = {"evals/frozen_evals.json":
                  _sha_bytes(b'{"frozen": true}')}
        (self.repo / "evals").mkdir()
        (self.repo / "evals" / "frozen_evals.json").write_bytes(
            b'{"frozen": true}')
        self.frozen = frozen
        self.root = Path(tempfile.mkdtemp())
        self.db = open_db(self.root / "t.db")
        self.db.conn.execute(
            "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
            ("goal_AR", "probe", "ACTIVE"))
        from agentos.stage_evals import StageEvals
        from agentos.autoresearch import Autoresearch
        self.ar = Autoresearch(self.db, self.root, None,
                               repo_source=self.repo)

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass

    def _manifest(self):
        from agentos.autoresearch import make_manifest
        return make_manifest(
            baseline_ref="base", primary_metric="pass^1",
            mutable_scope=["src/agentos/prompts.py"],
            frozen_eval_hashes={"eval.x": "h1"}, corpus_hash="chash",
            budget=5, frozen_files=self.frozen)

    def test_apply_is_invoked_and_in_scope_change_keeps(self):
        calls = []

        def apply(wt: Path):
            calls.append(str(wt))
            p = wt / "src" / "agentos" / "prompts.py"
            p.write_text("PROMPT='v2'\n", encoding="utf-8")

        results = self.ar.run_campaign(
            self._manifest(),
            [{"hypothesis": "better prompt", "candidate_ref": "c1",
              "apply": apply, "measurements": {}}],
            goal_id="goal_AR",
            dev_eval_fn=lambda wt, seed: 0.4 if wt else 0.5,
            holdout_fn=lambda wt, seed: {"passed": True}, drill_mode=True)
        self.assertTrue(calls, "apply(worktree) was never invoked")
        self.assertEqual(results[0]["status"], "KEEP")

    def test_in_process_apply_callback_is_rejected_outside_drill_mode(self):
        from agentos.autoresearch import AutoresearchError
        with self.assertRaises(AutoresearchError) as cm:
            self.ar.run_campaign(
                self._manifest(),
                [{"hypothesis": "host callback", "candidate_ref": "cb",
                  "apply": lambda worktree: None}],
                goal_id="goal_AR",
                dev_eval_fn=lambda wt, seed: 0.4,
                holdout_fn=lambda wt, seed: {"passed": True})
        self.assertIn("drill-only", str(cm.exception))

    def test_out_of_scope_change_quarantines_campaign(self):
        def apply(wt: Path):
            # candidate tries to modify a FROZEN eval file -> host catches it
            (wt / "evals" / "frozen_evals.json").write_bytes(b"tampered")
            p = wt / "src" / "agentos" / "prompts.py"
            p.write_text("PROMPT='v2'\n", encoding="utf-8")

        results = self.ar.run_campaign(
            self._manifest(),
            [{"hypothesis": "evil", "candidate_ref": "evil-1",
              "apply": apply},
             {"hypothesis": "innocent", "candidate_ref": "ok"}],
             dev_eval_fn=lambda wt, seed: 0.3 if wt else 0.5,
             holdout_fn=lambda wt, seed: {"passed": True},
             goal_id="goal_AR", drill_mode=True)
        self.assertEqual(results[0]["status"], "QUARANTINED")
        self.assertIn("FROZEN file modified",
                      results[0]["rationale"])
        # campaign halts; innocent experiment never ran
        self.assertEqual(results[-1]["reason"], "security_violation")

    def test_outside_scope_file_change_blocks_keep(self):
        def apply(wt: Path):
            (wt / "README.md").write_text("# sneaky\n", encoding="utf-8")

        results = self.ar.run_campaign(
            self._manifest(),
            [{"hypothesis": "scope creep", "candidate_ref": "sc",
             "apply": apply}],
             dev_eval_fn=lambda wt, seed: 0.3 if wt else 0.5,
             holdout_fn=lambda wt, seed: {"passed": True},
             goal_id="goal_AR", drill_mode=True)
        self.assertIn(results[0]["status"],
                      ("QUARANTINED", "DISCARD"))


def _sha_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    unittest.main()
