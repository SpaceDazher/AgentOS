"""Regression tests for S1-006 (QA2 execution backend research).

Positive flow: the frozen contract/workload/rubric produce a complete
90-run matrix, the evaluator derives PASS_WITH_LIMITS with in_process as
winner, probes A/B/C are detected through the real evaluator rules, and
the independent rerun (separate subprocess, separate output directory)
reproduces the safety verdict.

Negative mutations (fail-closed):
- run matrix divergence (missing/extra/duplicate runs);
- contract/workload/rubric hash divergence (INCOMPARABLE);
- mixed/fabricated commit and tree SHA provenance, dirty tree;
- runs-manifest digest mismatch, missing/corrupt run files;
- non-zero runner subprocess exit;
- safety counter key-set mismatch, non-zero counters, empty raw
  observations (never compensable by weighted scores);
- probes A/B/C undetected through the evaluator's real rules;
- unknown/NO_DATA dimensions excluded from scoring and never picking a
  winner.

Runner semantics (real code paths):
- corrupted/unregistered checkpoints never resume;
- duplicate delivery never creates a second local effect receipt;
- unknown outcomes are never retried without reconciliation evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parent.parent
S1006 = ROOT / "research" / "tickets" / "stage-1" / "S1-006"
sys.path.insert(0, str(S1006))

import evaluator as ev  # noqa: E402
import runner as rn  # noqa: E402
import make_bundle as mb  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_fresh():
    comparison = ev.load(S1006 / "results" / "backend-comparison.json")
    probes = ev.load(S1006 / "results" / "probes.json")
    manifest = ev.load(S1006 / "results" / "run-a" / "run-manifest.json")
    manifest_sha = _sha(S1006 / "results" / "run-a" / "run-manifest.json")
    return comparison, probes, manifest, manifest_sha


def _evaluate(comparison=None, probes=None, manifest=None, manifest_sha=None,
              expected_commit=None):
    return ev.evaluate(
        S1006, S1006 / "results",
        runs_manifest_path=S1006 / "results" / "run-a" / "run-manifest.json",
        runs_manifest_sha=manifest_sha or _sha(
            S1006 / "results" / "run-a" / "run-manifest.json"),
        comparison_data=comparison, probes_data=probes,
        manifest_data=manifest, expected_commit=expected_commit)


# --------------------------------------------------------------------------
# Positive flow (production CLI path)

class PositiveFlowTests(TestCase):
    """Full evaluation through the production CLI path."""

    def test_full_pipeline_accepts_and_recommends(self):
        proc = subprocess.run(
            [sys.executable, str(S1006 / "evaluator.py"),
             "--runs-manifest",
             str(S1006 / "results" / "run-a" / "run-manifest.json"),
             "--runs-manifest-sha", _sha(
                 S1006 / "results" / "run-a" / "run-manifest.json")],
            capture_output=True, text=True, timeout=600,
            cwd=str(ROOT), env={"SYSTEMROOT": "x"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["verdict"], "PASS_WITH_LIMITS")
        self.assertEqual(result["winner"], "in_process")
        self.assertTrue(result["sensitivity"]["stable"])
        self.assertEqual(result["sensitivity"]["flips"], 0)
        self.assertEqual(result["probe_rejections"]["A_unsafe_resume"],
                         "FAIL")
        self.assertEqual(result["probe_rejections"]["B_incomparable"],
                         "INCOMPARABLE/NO_DATA")
        self.assertEqual(result["probe_rejections"]["C_blind_retry"], "FAIL")

    def test_both_backends_fully_scored(self):
        recorded = ev.load(S1006 / "results" / "sensitivity-analysis.json")
        for backend in ("in_process", "durable_engine"):
            self.assertIn(backend, recorded["scores_normalized"])
            self.assertEqual(len(recorded["scores_normalized"][backend]), 11)

    def test_rerun_matches_main_verdict(self):
        main = ev.load(S1006 / "results" / "sensitivity-analysis.json")
        cmp = ev.load(S1006 / "results" / "rerun-comparison.json")
        self.assertTrue(cmp["verdict_equal"])
        self.assertLessEqual(max(cmp["score_deltas"].values()), 2.0)
        self.assertEqual(main["verdict"], "PASS_WITH_LIMITS")


# --------------------------------------------------------------------------
# Frozen run matrix integrity

class MatrixIntegrityTests(TestCase):
    def _evaluate_matrix(self, manifest, comparison):
        workload = ev.load(S1006 / "workload-manifest.json")
        return ev.validate_run_matrix(manifest, workload, comparison,
                                      S1006 / "results" / "run-a")

    def test_complete_matrix_accepted(self):
        comparison, _, manifest, _ = _load_fresh()
        expected, _ = self._evaluate_matrix(manifest, comparison)
        self.assertEqual(len(expected), 90)
        self.assertEqual(len(comparison["runs"]), 90)

    def test_missing_run_rejected(self):
        comparison, _, manifest, _ = _load_fresh()
        manifest["runs"] = manifest["runs"][:-1]
        with self.assertRaises(ev.EvalError) as ctx:
            self._evaluate_matrix(manifest, comparison)
        self.assertIn("divergence", str(ctx.exception))

    def test_extra_run_rejected(self):
        comparison, _, manifest, _ = _load_fresh()
        manifest["runs"].append(dict(manifest["runs"][0]))
        manifest["runs"][-1]["run_id"] += "-extra"
        with self.assertRaises(ev.EvalError):
            self._evaluate_matrix(manifest, comparison)

    def test_duplicate_run_rejected(self):
        comparison, _, manifest, _ = _load_fresh()
        manifest["runs"].append(dict(manifest["runs"][0]))
        with self.assertRaises(ev.EvalError):
            self._evaluate_matrix(manifest, comparison)

    def test_contract_hash_divergence_rejected(self):
        comparison, _, manifest, _ = _load_fresh()
        manifest["contract_sha256"] = "0" * 64
        with self.assertRaises(ev.EvalError):
            self._evaluate_matrix(manifest, comparison)

    def test_workload_hash_divergence_rejected(self):
        comparison, _, manifest, _ = _load_fresh()
        manifest["workload_sha256"] = "0" * 64
        with self.assertRaises(ev.EvalError):
            self._evaluate_matrix(manifest, comparison)

    def test_rubric_hash_divergence_rejected(self):
        comparison, _, manifest, _ = _load_fresh()
        manifest["rubric_sha256"] = "0" * 64
        with self.assertRaises(ev.EvalError):
            self._evaluate_matrix(manifest, comparison)


# --------------------------------------------------------------------------
# Commit/tree provenance binding (mixed revisions are INCOMPARABLE)

class ProvenanceMixingTests(TestCase):
    def test_mixed_commit_hashes_rejected(self):
        comparison, probes, manifest, sha = _load_fresh()
        comparison = copy.deepcopy(comparison)
        comparison["runs"][7]["commit"] = "1" * 40
        with self.assertRaises(ev.EvalError) as ctx:
            _evaluate(comparison=comparison, probes=probes,
                      manifest=manifest, manifest_sha=sha)
        self.assertIn("commit/tree", str(ctx.exception))

    def test_fabricated_tree_sha_rejected(self):
        comparison, probes, manifest, sha = _load_fresh()
        manifest = copy.deepcopy(manifest)
        manifest["provenance"]["tree_sha"] = "f" * 64
        with self.assertRaises(ev.EvalError) as ctx:
            _evaluate(comparison=comparison, probes=probes,
                      manifest=manifest, manifest_sha=sha)
        self.assertIn("tree", str(ctx.exception).lower())

    def test_dirty_tree_rejected(self):
        comparison, probes, manifest, sha = _load_fresh()
        manifest = copy.deepcopy(manifest)
        manifest["provenance"]["dirty"] = True
        with self.assertRaises(ev.EvalError) as ctx:
            _evaluate(comparison=comparison, probes=probes,
                      manifest=manifest, manifest_sha=sha)
        self.assertIn("dirty", str(ctx.exception).lower())

    def test_expected_commit_mismatch_rejected(self):
        with self.assertRaises(ev.EvalError) as ctx:
            _evaluate(expected_commit="0" * 40)
        self.assertIn("commit", str(ctx.exception).lower())

    def test_expected_commit_match_accepted(self):
        _, _, manifest, _ = _load_fresh()
        result = _evaluate(expected_commit=manifest["provenance"]["commit"])
        self.assertEqual(result["verdict"], "PASS_WITH_LIMITS")


# --------------------------------------------------------------------------
# Runs-manifest binding and executor discipline

class ProvenanceTests(TestCase):
    """Runs-manifest binding: digest mismatch, missing files and corrupt
    run files are rejected fail-closed; a non-zero runner subprocess exit
    stops the pipeline."""

    def _write_manifest(self, tmp: Path, run_files: dict, *,
                        tamper_digest: bool = False,
                        drop_file: str | None = None,
                        corrupt_file: str | None = None) -> Path:
        runs = []
        for name, content in run_files.items():
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if tamper_digest:
                digest = "0" * 64
            write = content if corrupt_file != name else "{ broken"
            (tmp / name).write_text(write, encoding="utf-8")
            runs.append({"run_id": name.replace(".json", ""),
                         "file": name, "sha256": digest})
        if drop_file:
            (tmp / drop_file).unlink()
        manifest = {"schema": "agentos.s1-006.run-manifest/v1",
                    "runs": runs}
        mpath = tmp / "run-manifest.json"
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        return mpath

    def test_valid_manifest_passes(self):
        with tempfile.TemporaryDirectory() as td:
            mpath = self._write_manifest(
                Path(td), {"a.json": json.dumps({"run_id": "a"})})
            result = ev.validate_runs_manifest(mpath)
            self.assertEqual(len(result["runs"]), 1)

    def test_manifest_digest_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            mpath = self._write_manifest(
                Path(td), {"a.json": json.dumps({"run_id": "a"})},
                tamper_digest=True)
            with self.assertRaises(ev.EvalError) as ctx:
                ev.validate_runs_manifest(mpath, "f" * 64)
            self.assertIn("digest mismatch", str(ctx.exception))

    def test_missing_run_file_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            mpath = self._write_manifest(
                Path(td), {"a.json": json.dumps({"run_id": "a"})},
                drop_file="a.json")
            with self.assertRaises(ev.EvalError) as ctx:
                ev.validate_runs_manifest(mpath)
            self.assertIn("run file missing", str(ctx.exception))

    def test_corrupt_run_file_digest_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            mpath = self._write_manifest(
                Path(td), {"a.json": json.dumps({"run_id": "a"})},
                corrupt_file="a.json")
            with self.assertRaises(ev.EvalError) as ctx:
                ev.validate_runs_manifest(mpath)
            self.assertIn("digest mismatch", str(ctx.exception))

    def test_nonzero_runner_exit_rejected(self):
        with self.assertRaises(SystemExit):
            mb.sh([sys.executable, "-c", "import sys; sys.exit(3)"])

    def test_timeout_runner_rejected(self):
        with self.assertRaises(SystemExit):
            mb.sh([sys.executable, "-c", "import time; time.sleep(30)"],
                  timeout=1)


# --------------------------------------------------------------------------
# Safety counters and observation completeness

class SafetyCounterTests(TestCase):
    def test_counter_keyset_mismatch_rejected(self):
        bad = dict.fromkeys(ev.SAFETY_COUNTERS[:-1], 0)
        with self.assertRaises(ev.EvalError):
            ev.validate_run_entry({"run_id": "x", "safety_counters": bad,
                                   "raw_observation_count": 5,
                                   "terminal_reason": "completed"})

    def test_empty_raw_observations_rejected(self):
        counters = dict.fromkeys(ev.SAFETY_COUNTERS, 0)
        with self.assertRaises(ev.EvalError) as ctx:
            ev.validate_run_entry({"run_id": "x", "safety_counters": counters,
                                   "raw_observation_count": 0,
                                   "terminal_reason": "completed"})
        self.assertIn("raw observations", str(ctx.exception))

    def test_abnormal_terminal_reason_rejected(self):
        counters = dict.fromkeys(ev.SAFETY_COUNTERS, 0)
        with self.assertRaises(ev.EvalError):
            ev.validate_run_entry({"run_id": "x", "safety_counters": counters,
                                   "raw_observation_count": 5,
                                   "terminal_reason": "censored"})

    def test_hard_safety_failure_not_compensable_by_weights(self):
        """Any non-zero safety counter fails the candidate regardless of
        how favourable the weighted score would be."""
        comparison, probes, manifest, sha = _load_fresh()
        comparison = copy.deepcopy(comparison)
        victim = next(r for r in comparison["runs"]
                      if r["backend"] == "in_process")
        victim["safety_counters"]["duplicate_effect_count"] = 1
        with self.assertRaises(ev.EvalError) as ctx:
            _evaluate(comparison=comparison, probes=probes,
                      manifest=manifest, manifest_sha=sha)
        self.assertIn("SAFETY VIOLATION", str(ctx.exception))


# --------------------------------------------------------------------------
# Adversarial probes through the real evaluator rules

class ProbeTests(TestCase):
    def _without(self, pid):
        comparison, probes, manifest, sha = _load_fresh()
        probes = copy.deepcopy(probes)
        probes["probes"] = [p for p in probes["probes"] if p["probe"] != pid]
        return comparison, probes, manifest, sha

    def test_undetected_probe_a_rejected(self):
        comparison, probes, manifest, sha = _load_fresh()
        probes = copy.deepcopy(probes)
        for p in probes["probes"]:
            if p["probe"] == "A_unsafe_resume":
                p["safety_counters"]["duplicate_effect_count"] = 0
                p["safety_counters"]["duplicate_receipt_count"] = 0
        with self.assertRaises(ev.EvalError) as ctx:
            _evaluate(comparison=comparison, probes=probes,
                      manifest=manifest, manifest_sha=sha)
        self.assertIn("A_unsafe_resume", str(ctx.exception))

    def test_undetected_probe_b_rejected(self):
        comparison, probes, manifest, sha = _load_fresh()
        probes = copy.deepcopy(probes)
        for p in probes["probes"]:
            if p["probe"] == "B_incomparable":
                frozen = ev.load(S1006 / "workload-manifest.json")
                p["workload_sha256"] = _sha(S1006 / "workload-manifest.json")
                self.assertNotEqual(p["workload_sha256"], "divergent")
                del frozen
        with self.assertRaises(ev.EvalError) as ctx:
            _evaluate(comparison=comparison, probes=probes,
                      manifest=manifest, manifest_sha=sha)
        self.assertIn("B_incomparable", str(ctx.exception))

    def test_undetected_probe_c_rejected(self):
        comparison, probes, manifest, sha = _load_fresh()
        probes = copy.deepcopy(probes)
        for p in probes["probes"]:
            if p["probe"] == "C_blind_retry":
                p["safety_counters"]["blind_retry_count"] = 0
        with self.assertRaises(ev.EvalError) as ctx:
            _evaluate(comparison=comparison, probes=probes,
                      manifest=manifest, manifest_sha=sha)
        self.assertIn("C_blind_retry", str(ctx.exception))

    def test_missing_probe_rejected(self):
        comparison, probes, manifest, sha = self._without("C_blind_retry")
        with self.assertRaises(ev.EvalError) as ctx:
            _evaluate(comparison=comparison, probes=probes,
                      manifest=manifest, manifest_sha=sha)
        self.assertIn("probes missing", str(ctx.exception))


# --------------------------------------------------------------------------
# unknown/NO_DATA never picks a winner

class UnknownPolicyTests(TestCase):
    def _comparison_with_unknown_recovery(self):
        comparison, _, _, _ = _load_fresh()
        comparison = copy.deepcopy(comparison)
        for run in comparison["runs"]:
            if run["backend"] == "durable_engine" and \
                    run["scenario"] in ("S1", "S2", "S3", "S4"):
                run["metrics"]["recovery_times"] = []
        return comparison

    def test_unknown_dimension_excluded_and_recorded(self):
        comparison = self._comparison_with_unknown_recovery()
        contract = ev.load(S1006 / "backend-contract.json")
        scores, unknown, _, _ = ev.score_dims(comparison, contract)
        # a dimension unobservable for ANY compared candidate is unknown
        # for BOTH: no side can gain an advantage from missing data
        self.assertIn("crash_recovery_time", unknown["durable_engine"])
        self.assertIn("crash_recovery_time", unknown["in_process"])
        self.assertNotIn("crash_recovery_time", scores["durable_engine"])
        self.assertNotIn("crash_recovery_time", scores["in_process"])

    def test_unknown_cells_cannot_pick_winner(self):
        comparison = self._comparison_with_unknown_recovery()
        result = _evaluate(comparison=comparison)
        # the winner must still be decided by scored dimensions only, and
        # unknown cells on the winner are recorded as limits
        self.assertEqual(result["winner"], "in_process")
        self.assertTrue(any("unknown cells" in r for r in result["reasons"]))
        self.assertEqual(result["verdict"], "PASS_WITH_LIMITS")


# --------------------------------------------------------------------------
# Runner semantics: checkpoint resume, dedup delivery, reconciliation

class CheckpointResumeTests(TestCase):
    def test_verified_checkpoint_resumes(self):
        store = rn.CheckpointStore()
        store.put("run-1", "t4", 3, rn.content_hash("run-1", "t4", 3))
        accepted, reason = store.resume("run-1", "t4", 3,
                                        rn.content_hash("run-1", "t4", 3))
        self.assertTrue(accepted)
        self.assertEqual(reason, "verified")

    def test_unregistered_checkpoint_never_resumes(self):
        store = rn.CheckpointStore()
        accepted, reason = store.resume("run-1", "t4", 3, "a" * 64)
        self.assertFalse(accepted)
        self.assertEqual(reason, "unregistered-checkpoint")

    def test_corrupted_checkpoint_never_resumes(self):
        store = rn.CheckpointStore()
        store.put("run-1", "t4", 3, rn.content_hash("run-1", "t4", 3))
        accepted, reason = store.resume("run-1", "t4", 3, "b" * 64)
        self.assertFalse(accepted)
        self.assertEqual(reason, "corrupt-checkpoint")

    def test_s3_scenario_resumes_through_verified_checkpoints(self):
        run = rn.simulate("durable_engine", "nominal", 303, "S3")
        self.assertEqual(run["safety_counters"]["checkpoint_hash_bypass_count"],
                         0)
        self.assertTrue(run["resumes"])
        self.assertTrue(all(r["accepted"] for r in run["resumes"]))


class DeliveryDedupTests(TestCase):
    def test_duplicate_delivery_never_creates_second_receipt(self):
        receipts: dict = {}
        counters = dict.fromkeys(rn.SAFETY_COUNTERS, 0)
        self.assertTrue(rn.deliver_effect("d#1", receipts))
        self.assertFalse(rn.deliver_effect("d#1", receipts))
        self.assertFalse(rn.deliver_effect("d#1", receipts))
        self.assertEqual(receipts["d#1"], 1)
        self.assertEqual(counters["duplicate_receipt_count"], 0)

    def test_s4_redelivery_is_absorbed_by_dedup(self):
        run = rn.simulate("in_process", "low", 202, "S4")
        self.assertGreaterEqual(run["redeliveries"], 1)
        self.assertEqual(run["safety_counters"]["duplicate_receipt_count"], 0)
        self.assertEqual(run["safety_counters"]["duplicate_effect_count"], 0)

    def test_probe_a_produces_real_duplicate(self):
        probes = rn.build_probes()
        probe_a = next(p for p in probes if p["probe"] == "A_unsafe_resume")
        self.assertEqual(probe_a["safety_counters"]["duplicate_effect_count"],
                         1)
        self.assertEqual(probe_a["safety_counters"]["duplicate_receipt_count"],
                         1)


class ReconciliationTests(TestCase):
    def test_unknown_outcome_without_evidence_is_blind_retry(self):
        counters = dict.fromkeys(rn.SAFETY_COUNTERS, 0)
        action = rn.retry_after_unknown("d#1", {}, counters, allow_retry=True)
        self.assertEqual(action, "blind-retry")
        self.assertEqual(counters["blind_retry_count"], 1)

    def test_unknown_outcome_with_recorded_reconciliation_retries(self):
        counters = dict.fromkeys(rn.SAFETY_COUNTERS, 0)
        reconciliations = {"d#1": "resolved-by-evidence"}
        action = rn.retry_after_unknown("d#1", reconciliations, counters,
                                        allow_retry=True)
        self.assertEqual(action, "retry-after-reconciliation")
        self.assertEqual(counters["blind_retry_count"], 0)

    def test_s2_scenario_reconciles_without_blind_retry(self):
        run = rn.simulate("durable_engine", "nominal", 101, "S2")
        self.assertEqual(run["safety_counters"]["blind_retry_count"], 0)
        # unknown outcomes in the frozen outcome model are reconciled
        self.assertGreater(run["reconciled_unknown_outcomes"], 0)

    def test_probe_c_produces_real_blind_retry(self):
        probes = rn.build_probes()
        probe_c = next(p for p in probes if p["probe"] == "C_blind_retry")
        self.assertGreaterEqual(
            probe_c["safety_counters"]["blind_retry_count"], 1)


# --------------------------------------------------------------------------
# Independent rerun: separate process, separate output manifest

class IndependentRerunTests(TestCase):
    def test_rerun_manifest_is_separate_and_frozen_equal(self):
        run_a = ev.load(S1006 / "results" / "run-a" / "run-manifest.json")
        run_b = ev.load(S1006 / "results" / "run-b" / "run-manifest.json")
        self.assertNotEqual(S1006 / "results" / "run-a",
                            S1006 / "results" / "run-b")
        for field in ("contract_sha256", "workload_sha256", "rubric_sha256"):
            self.assertEqual(run_a[field], run_b[field])
        self.assertEqual(len(run_b["runs"]), 90)

    def test_fresh_subprocess_reproduces_main_matrix(self):
        """A separate runner process with the same frozen inputs
        reproduces run-a byte-for-byte (independent rerun discipline)."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "run-x"
            proc = subprocess.run(
                [sys.executable, str(S1006 / "runner.py"),
                 "--mode", "main", "--out", str(out)],
                capture_output=True, text=True, timeout=900, cwd=str(ROOT))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            fresh = ev.load(out / "run-manifest.json")
            main = ev.load(S1006 / "results" / "run-a" / "run-manifest.json")
            fresh_runs = {r["run_id"]: r["sha256"] for r in fresh["runs"]}
            main_runs = {r["run_id"]: r["sha256"] for r in main["runs"]}
            self.assertEqual(fresh_runs, main_runs)


if __name__ == "__main__":  # pragma: no cover
    from unittest import main
    main()
