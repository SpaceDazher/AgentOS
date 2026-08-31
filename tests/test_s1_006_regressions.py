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
import importlib.util
import json
import subprocess
import sys
import tempfile
import random
import shutil
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parent.parent
S1006 = ROOT / "research" / "tickets" / "stage-1" / "S1-006"
sys.path.insert(0, str(S1006))


def _load_ticket_module(name: str):
    """Load an S1-006 research module under a UNIQUE sys.modules name.
    Other ticket suites (S1-005) import generic module names such as
    'evaluator' or 'make_bundle'; a plain import here would receive their
    cached module inside one discovery process (and vice versa), so each
    ticket suite must namespace its own modules."""
    unique = f"s1_006_{name}"
    if unique in sys.modules:
        return sys.modules[unique]
    spec = importlib.util.spec_from_file_location(
        unique, S1006 / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    spec.loader.exec_module(module)
    return module


ev = _load_ticket_module("evaluator")
rn = _load_ticket_module("runner")
mb = _load_ticket_module("make_bundle")
dg = _load_ticket_module("dependency_gate")
# make_bundle.build_bundle does 'from bundle_content import build' at call
# time; pre-register S1-006's copy so the name resolves deterministically.
_load_ticket_module("bundle_content")
sys.modules.setdefault("bundle_content", sys.modules["s1_006_bundle_content"])


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
        manifest_data=manifest, expected_commit=expected_commit,
        probes_sha=_sha(S1006 / "results" / "probes.json"))


# --------------------------------------------------------------------------
# Positive flow (production CLI path)

class PositiveFlowTests(TestCase):
    """Full evaluation through the production CLI path."""

    def test_full_pipeline_accepts_and_recommends(self):
        """Production CLI path; the evaluation is written to a temporary
        --out so the published nonce-bound sensitivity result is never
        clobbered by a nonce-less test invocation."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "evaluation.json"
            proc = subprocess.run(
                [sys.executable, str(S1006 / "evaluator.py"),
                 "--runs-manifest",
                 str(S1006 / "results" / "run-a" / "run-manifest.json"),
                 "--runs-manifest-sha", _sha(
                     S1006 / "results" / "run-a" / "run-manifest.json"),
                 "--probes-sha", _sha(S1006 / "results" / "probes.json"),
                 "--out", str(out)],
                capture_output=True, text=True, timeout=600,
                cwd=str(ROOT))
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

    def test_published_sensitivity_stays_nonce_bound(self):
        recorded = ev.load(S1006 / "results" / "sensitivity-analysis.json")
        nonce = recorded.get("run_nonce")
        self.assertTrue(nonce and nonce.startswith("s1-006-"),
                        "published evaluation lost its producer nonce")

    def test_both_backends_fully_scored(self):
        recorded = ev.load(S1006 / "results" / "sensitivity-analysis.json")
        for backend in ("in_process", "durable_engine"):
            self.assertIn(backend, recorded["scores_normalized"])
            self.assertEqual(len(recorded["scores_normalized"][backend]), 11)

    def test_rerun_matches_main_verdict(self):
        main = ev.load(S1006 / "results" / "sensitivity-analysis.json")
        cmp = ev.load(S1006 / "results" / "rerun-comparison.json")
        self.assertTrue(cmp["verdict_equal"])
        self.assertLessEqual(max(cmp["score_deltas"].values()),
                             cmp["score_absolute_tolerance"])
        self.assertTrue(all(
            delta <= cmp["metric_relative_tolerance"]
            for metric in cmp["metric_relative_deltas"].values()
            for delta in metric.values()))
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
        self.assertIn("raw-derived", str(ctx.exception))

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

    def test_porcelain_parser_only_ignores_generated_outputs(self):
        """Executed research scripts/tests are inputs and must be clean;
        only explicitly generated evidence outputs may be ignored."""
        lines = [" M research/tickets/stage-1/S1-006/evaluator.py",
                 " M tests/test_s1_006_regressions.py",
                 " M src/agentos/engine.py",
                 "?? research/tickets/stage-1/S1-006/results/new.json"]
        dirty = rn.research_surface_dirty_lines(lines)
        self.assertEqual(dirty, lines[:3])
        self.assertEqual(
            rn.research_surface_dirty_lines(
                [" M research/tickets/stage-1/S1-006/results/x.json",
                 " M research/tickets/stage-1/S1-006/bundle.json"]),
            [])


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
        self.assertIn("raw-derived", str(ctx.exception))


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
        contract = ev.load(S1006 / "backend-contract.json")
        rubric = ev.load(S1006 / "rubric.json")
        scores, unknown, _, _ = ev.score_dims(comparison, contract)
        result = ev.sensitivity(scores, rubric["weights"], unknown)
        # The winner is computed only from present cells. The missing cell
        # remains explicit for both candidates and cannot become a score.
        self.assertEqual(result["base_winner"], "in_process")
        self.assertIn("crash_recovery_time", unknown["in_process"])
        self.assertIn("crash_recovery_time", unknown["durable_engine"])


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
        self.assertNotEqual(run_a["provenance"]["executor_id"],
                            run_b["provenance"]["executor_id"])

    def test_fresh_subprocess_reproduces_main_matrix(self):
        """A separate runner process with the same frozen inputs
        reproduces run-a's frozen content: identical contract/workload/
        rubric bindings, metrics, safety counters and raw observations.
        Git provenance fields (commit/tree_sha/dirty) legitimately track
        the executing tree, so they are compared for internal
        consistency only, not against run-a's recorded commit."""
        run_a = ev.load(S1006 / "results" / "run-a" / "run-manifest.json")
        run_b = ev.load(S1006 / "results" / "run-b" / "run-manifest.json")
        frozen_keys = ("schema", "run_id", "backend", "load", "seed",
                       "scenario", "mutations", "contract_sha256",
                       "workload_sha256", "rubric_sha256", "metrics",
                       "resumes", "redeliveries",
                       "reconciled_unknown_outcomes", "safety_counters",
                       "reconciliations", "outbox", "checkpoint_registry",
                       "effect_attempt_counts", "delivery_attempt_counts",
                       "receipt_counts", "blind_retry_records",
                       "stale_completion_attempts", "scenario_events",
                       "raw_observations", "terminal_reason")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "run-x"
            proc = subprocess.run(
                [sys.executable, str(S1006 / "runner.py"),
                 "--mode", "main", "--out", str(out)],
                capture_output=True, text=True, timeout=900, cwd=str(ROOT))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            fresh = ev.load(out / "run-manifest.json")
            fresh_files = {e["run_id"]: ev.load(out / e["file"])
                           for e in fresh["runs"]}
        # 1) the independent rerun matches run-a semantically; executor and
        #    environment identity intentionally differ.
        for entry_a in run_a["runs"]:
            entry_b = next(e for e in run_b["runs"]
                           if e["run_id"] == entry_a["run_id"])
            data_a = ev.load(S1006 / "results" / "run-a" / entry_a["file"])
            data_b = ev.load(S1006 / "results" / "run-b" / entry_b["file"])
            for key in frozen_keys:
                self.assertEqual(data_a[key], data_b[key],
                                 f"{entry_a['run_id']}.{key}")
        # 2) a fresh subprocess reproduces the frozen content of every
        #    run despite executing on the current HEAD
        for entry in fresh["runs"]:
            entry_a = next(e for e in run_a["runs"]
                           if e["run_id"] == entry["run_id"])
            fresh_run = fresh_files[entry["run_id"]]
            recorded_run = ev.load(S1006 / "results" / "run-a"
                                   / entry_a["file"])
            for key in frozen_keys:
                self.assertEqual(
                    fresh_run[key], recorded_run[key],
                    f"{entry['run_id']}.{key} diverged")
            # provenance is internally consistent with the executing tree
            self.assertEqual(fresh_run["commit"], fresh["provenance"]["commit"])
            self.assertEqual(fresh_run["tree_sha"],
                             fresh["provenance"]["tree_sha"])
            self.assertEqual(fresh_run["dirty"],
                             fresh["provenance"]["dirty"])


# --------------------------------------------------------------------------
# Corrective review R2: raw authority, real scenarios, provenance, deps

class RawRunAuthorityR2Tests(TestCase):
    def test_run_manifest_cannot_escape_its_evidence_directory(self):
        with self.assertRaises(ev.EvalError):
            ev.run_file_path(S1006 / "results" / "run-a", "../secrets.json")

    def test_raw_safety_violation_cannot_be_hidden_by_comparison(self):
        """The evaluator must derive counters from hash-verified raw runs,
        not trust the separately produced backend-comparison summary."""
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run-b"
            shutil.copytree(S1006 / "results" / "run-b", run_dir)
            manifest_path = run_dir / "run-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            entry = manifest["runs"][0]
            raw_path = run_dir / entry["file"]
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            raw["safety_counters"]["duplicate_effect_count"] = 99
            raw_path.write_text(
                json.dumps(raw, indent=1, sort_keys=True) + "\n",
                encoding="utf-8")
            entry["sha256"] = _sha(raw_path)
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
            with self.assertRaises(ev.EvalError) as ctx:
                ev.evaluate(
                    S1006, S1006 / "results",
                    runs_manifest_path=manifest_path,
                    runs_manifest_sha=_sha(manifest_path),
                    expected_commit=manifest["provenance"]["commit"],
                    probes_sha=_sha(S1006 / "results" / "probes.json"))
        self.assertIn("SAFETY VIOLATION", str(ctx.exception))

    def test_comparison_summary_must_equal_raw_derived_comparison(self):
        comparison, probes, manifest, sha = _load_fresh()
        comparison = copy.deepcopy(comparison)
        comparison["runs"][0]["metrics"]["latency_us"]["p95"] = 10**12
        with self.assertRaises(ev.EvalError) as ctx:
            _evaluate(comparison=comparison, probes=probes,
                      manifest=manifest, manifest_sha=sha)
        self.assertIn("raw-derived", str(ctx.exception))

    def test_throughput_summary_is_derived_from_raw_completion_times(self):
        run = rn.simulate("in_process", "low", 101)
        run["metrics"]["throughput_tasks_per_second"] += 1
        with self.assertRaises(ev.EvalError) as ctx:
            ev.validate_raw_run(run)
        self.assertIn("throughput", str(ctx.exception))

    def test_production_evaluator_requires_probe_digest_binding(self):
        manifest_path = S1006 / "results" / "run-a" / "run-manifest.json"
        with self.assertRaises(ev.EvalError) as ctx:
            ev.evaluate(
                S1006, S1006 / "results",
                runs_manifest_path=manifest_path,
                runs_manifest_sha=_sha(manifest_path),
                expected_commit=ev.load(manifest_path)["provenance"]["commit"])
        self.assertIn("probe", str(ctx.exception).lower())


class RunnerSemanticsR2Tests(TestCase):
    def test_every_dag_instance_is_dependency_valid(self):
        roots = {task for task, deps in rn.DAG.items() if not deps}
        sequence = rn.task_sequence(40, random.Random(101))
        for offset in range(0, len(sequence), len(rn.DAG)):
            chunk = sequence[offset:offset + len(rn.DAG)]
            if chunk:
                self.assertIn(chunk[0], roots)
            seen = set()
            for task in chunk:
                self.assertTrue(set(rn.DAG[task]).issubset(seen),
                                f"{task} ran before its deps in {chunk}")
                seen.add(task)

    def test_arrivals_are_open_loop_not_ready_time_equals_dispatch_time(self):
        low = rn.simulate("in_process", "low", 101)
        high = rn.simulate("in_process", "high", 101)
        self.assertGreater(low["raw_observations"][1]["arrival_us"], 0)
        self.assertGreater(high["raw_observations"][1]["arrival_us"], 0)
        self.assertGreater(
            low["raw_observations"][1]["arrival_us"],
            high["raw_observations"][1]["arrival_us"])
        self.assertIn("waiting_us", high["raw_observations"][1])

    def test_high_load_creates_observable_queue_pressure(self):
        high = rn.simulate("in_process", "high", 101)
        self.assertGreater(high["metrics"]["max_queue_depth"], 1)
        self.assertTrue(any(item["waiting_us"] > 0
                            for item in high["raw_observations"]))
        ev.validate_raw_run(high)

    def test_rounded_open_loop_timing_remains_verifiable(self):
        run = rn.simulate("durable_engine", "nominal", 202, "S1")
        ev.validate_raw_run(run)

    def test_s1_observes_commit_crash_and_replayed_delivery(self):
        run = rn.simulate("in_process", "low", 101, "S1")
        event_types = [event["event"] for event in run["scenario_events"]]
        self.assertIn("transition_outbox_committed", event_types)
        self.assertIn("coordinator_crashed", event_types)
        self.assertIn("outbox_delivery_replayed", event_types)
        self.assertTrue(run["outbox"])
        self.assertTrue(all(item["delivered"] for item in run["outbox"].values()))

    def test_s3_resume_records_new_run_provenance(self):
        run = rn.simulate("durable_engine", "nominal", 303, "S3")
        self.assertTrue(run["resumes"])
        resume = run["resumes"][0]
        self.assertNotEqual(resume["previous_run_id"], resume["new_run_id"])
        self.assertEqual(resume["resumed_from_run_id"],
                         resume["previous_run_id"])
        self.assertEqual(resume["reexecuted_steps"], [])

    def test_s4_records_real_stale_fence_rejection(self):
        run = rn.simulate("durable_engine", "low", 202, "S4")
        stale = run["stale_completion_attempts"]
        self.assertTrue(stale)
        self.assertTrue(all(item["rejected"] for item in stale))
        self.assertTrue(all(item["presented_fence"] < item["current_fence"]
                            for item in stale))

    def test_every_s2_run_injects_and_reconciles_an_unknown_outcome(self):
        for backend in rn.BACKENDS:
            for load in rn.LOADS:
                for seed in rn.SEEDS:
                    run = rn.simulate(backend, load, seed, "S2")
                    self.assertGreater(
                        run["reconciled_unknown_outcomes"], 0,
                        f"missing S2 injection for {backend}/{load}/{seed}")
                    ev.validate_raw_run(run)

    def test_probe_a_derives_duplicates_from_actual_ledgers(self):
        probe = next(p for p in rn.build_probes()
                     if p["probe"] == "A_unsafe_resume")
        self.assertTrue(any(v == 2 for v in
                            probe["effect_attempt_counts"].values()))
        self.assertTrue(any(v == 2 for v in
                            probe["receipt_counts"].values()))
        derived = rn.derive_safety_counters(probe)
        self.assertEqual(derived, probe["safety_counters"])


class ProvenanceR2Tests(TestCase):
    def test_script_hashes_are_mandatory(self):
        comparison, probes, manifest, sha = _load_fresh()
        manifest = copy.deepcopy(manifest)
        manifest["provenance"].pop("script_hashes", None)
        with self.assertRaises(ev.EvalError) as ctx:
            _evaluate(comparison=comparison, probes=probes,
                      manifest=manifest, manifest_sha=sha)
        self.assertIn("script", str(ctx.exception).lower())

    def test_executed_script_hash_must_match_commit_tree(self):
        comparison, probes, manifest, sha = _load_fresh()
        manifest = copy.deepcopy(manifest)
        manifest["provenance"]["script_hashes"]["runner.py"] = "0" * 64
        with self.assertRaises(ev.EvalError) as ctx:
            _evaluate(comparison=comparison, probes=probes,
                      manifest=manifest, manifest_sha=sha)
        self.assertIn("runner.py", str(ctx.exception))

    def test_commit_blob_hashes_are_mandatory(self):
        comparison, probes, manifest, sha = _load_fresh()
        manifest = copy.deepcopy(manifest)
        manifest["provenance"].pop("script_blob_hashes", None)
        with self.assertRaises(ev.EvalError) as ctx:
            _evaluate(comparison=comparison, probes=probes,
                      manifest=manifest, manifest_sha=sha)
        self.assertIn("blob", str(ctx.exception).lower())


class SensitivityR2Tests(TestCase):
    def test_run_count_matches_every_weight_dimension_plus_random_vectors(self):
        rubric = ev.load(S1006 / "rubric.json")
        scores = {
            "a": {name: 4 for name in rubric["weights"]},
            "b": {name: 1 for name in rubric["weights"]},
        }
        result = ev.sensitivity(scores, rubric["weights"], {"a": [], "b": []})
        expected_perturbations = 2 * len(rubric["weights"])
        self.assertEqual(result["perturbation_runs"], expected_perturbations)
        self.assertEqual(result["random_runs"], ev.SENSITIVITY_RANDOM_RUNS)
        self.assertEqual(result["runs"],
                         expected_perturbations + ev.SENSITIVITY_RANDOM_RUNS)


class ScoringAuthorityR2Tests(TestCase):
    def test_qualitative_score_comes_from_explicit_evidence_cell(self):
        raw_runs = {}
        entries = []
        for spec in rn.run_matrix("main"):
            run = rn.simulate(spec["backend"], spec["load"], spec["seed"],
                              spec["scenario"])
            raw_runs[run["run_id"]] = run
            entries.append({"run_id": run["run_id"]})
        comparison = ev.comparison_from_raw({
            "contract_sha256": raw_runs[next(iter(raw_runs))]
                ["contract_sha256"],
            "workload_sha256": raw_runs[next(iter(raw_runs))]
                ["workload_sha256"],
            "rubric_sha256": raw_runs[next(iter(raw_runs))]["rubric_sha256"],
            "runs": entries,
        }, raw_runs)
        contract = ev.load(S1006 / "backend-contract.json")
        changed = copy.deepcopy(contract)
        changed["candidates"]["in_process"]["task_queue"] = "arbitrary text"
        baseline, _, _, _ = ev.score_dims(comparison, contract)
        text_changed, _, _, _ = ev.score_dims(comparison, changed)
        self.assertEqual(baseline["in_process"]["task_run_durability"],
                         text_changed["in_process"]["task_run_durability"])
        changed["qualitative_dimensions"]["task_run_durability"] \
            ["in_process"]["score"] = 1
        evidence_changed, _, _, _ = ev.score_dims(comparison, changed)
        self.assertEqual(
            evidence_changed["in_process"]["task_run_durability"], 1)


class DependencyGateR2Tests(TestCase):
    def _binding(self):
        rec = ev.load(ROOT / "research/tickets/stage-1/S1-002"
                      / "evaluation-record.json")
        pack = ev.load(ROOT / rec["evidence_pack"]["path"])
        db_eval = {
            "id": rec["evaluation_id"], "result": rec["result"],
            "artifact_chain_hash": rec["artifact_chain_hash"],
            "campaign_id": rec["campaign_id"], "goal_id": rec["goal_id"],
        }
        return rec, pack, db_eval

    def test_latest_evaluation_valid_is_required(self):
        rec, pack, db_eval = self._binding()
        rec = copy.deepcopy(rec)
        rec["evidence_pack"]["latest_evaluation_valid"] = False
        problems = dg.validate_dependency_binding(
            rec, pack, db_eval, rec["research_revision"])
        self.assertTrue(any("latest_evaluation_valid" in p for p in problems))

    def test_current_dependency_binding_is_complete(self):
        rec, pack, db_eval = self._binding()
        problems = dg.validate_dependency_binding(
            rec, pack, db_eval, rec["research_revision"])
        self.assertEqual(problems, [])

    def test_pack_chain_campaign_and_evaluation_are_bound(self):
        rec, pack, db_eval = self._binding()
        pack = copy.deepcopy(pack)
        pack["research"]["current_chain_hash"] = "0" * 64
        problems = dg.validate_dependency_binding(
            rec, pack, db_eval, rec["research_revision"])
        self.assertTrue(any("current chain" in p for p in problems))


if __name__ == "__main__":  # pragma: no cover
    from unittest import main
    main()
