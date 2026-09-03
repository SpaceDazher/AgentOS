"""Independent negative probes for the S1-005 REVIEW_R2 findings.

F1: experiments must be re-executed as a fresh subprocess by the bundle
    builder; a saved/fabricated boundary-experiments.json must never be
    published without fresh verification, and the fresh output must be
    bound to the environment manifest, the commit SHA and the output file
    SHA-256.
F2: evidence refs must resolve to hash-bound repository paths or registry
    source ids; free-form authority is removed; claim classification rules
    are enforced by the evaluator (a `measurement` cell needs a measurement
    artifact, a `fact` cell needs an implementation/source artifact).
F3: failure-scenario branches are strictly validated by the PRODUCTION
    evaluator.validate_scenarios (not a test-local copy): wrong types,
    empty strings/lists/dicts and partially empty branches are rejected.
F4: the sensitivity result must store the full weight vector, the total
    and the digest for every S2 run, and the digest must verify on read.
F5: IPC child processes must not leak pipe handles (no ResourceWarning)
    and must be terminated/killed on timeout.
F6: the bundle builder must fail on evaluator subprocess failures
    (non-zero exit, malformed JSON, stale/missing output, schema
    mismatch) and must actually re-execute experiments.
"""
from __future__ import annotations

import copy
import gc
import hashlib
import json
import subprocess
import sys
import warnings
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parent.parent
S1005 = ROOT / "research" / "tickets" / "stage-1" / "S1-005"
sys.path.insert(0, str(S1005))

import evaluator as ev  # noqa: E402
import experiments as exp  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _restore_production_sensitivity(saved: str) -> None:
    """Best-effort regeneration of the tracked sensitivity file with a
    guaranteed restore (isolation fix): re-run the production evaluator
    so a working environment still verifies byte-identical regeneration;
    if regeneration fails for any reason, write back `saved` so the
    tracked evidence file is never left deleted, and never mask the
    test's own outcome (no re-raise)."""
    import os as _os
    try:
        saved_doc = json.loads(saved)
        env = dict(_os.environ)
        if saved_doc.get("run_nonce"):
            env["AGENTOS_RUN_NONCE"] = saved_doc["run_nonce"]
        else:
            env.pop("AGENTOS_RUN_NONCE", None)
        subprocess.run(
            [sys.executable, str(S1005 / "evaluator.py"),
             "--ticket", str(S1005), "--out", str(S1005 / "results")],
            check=True, capture_output=True, timeout=600, env=env)
    except Exception:
        (S1005 / "results" / "sensitivity-analysis.json").write_text(
            saved, encoding="utf-8")


def _fresh():
    rubric = ev.load_json(S1005 / "rubric.json")
    matrix = ev.load_json(S1005 / "results" / "qa1-decision-matrix.json")
    scenarios = ev.load_json(S1005 / "results" / "failure-scenarios.json")
    sha = _sha(S1005 / "rubric.json")
    return rubric, matrix, scenarios, sha


# --------------------------------------------------------------------------
# F2 - evidence ref authority and claim classification
# --------------------------------------------------------------------------

class F2EvidenceAuthorityTests(TestCase):
    def _cell(self, matrix, dim_name, cid):
        return next(d for d in matrix["matrix"]
                    if d["dimension"] == dim_name)["cells"][cid]

    def test_freeform_evidence_ref_rejected(self):
        rubric, matrix, scenarios, sha = _fresh()
        cell = self._cell(matrix, "policy_boundary", "monolith")
        cell["evidence_refs"] = ["trust me, containers are bad"]
        with self.assertRaises(ev.EvalError):
            ev.validate_matrix(matrix, rubric, sha, S1005)

    def test_source_id_refs_resolve_via_registry(self):
        """Registry-backed source ids (ADR-0002, SRC-03 ...) remain valid
        and each binds to an existing, digest-matched file."""
        rubric, matrix, scenarios, sha = _fresh()
        result = ev.validate_matrix(matrix, rubric, sha, S1005)
        self.assertTrue(result[0])

    def test_measurement_cell_requires_measurement_artifact(self):
        rubric, matrix, scenarios, sha = _fresh()
        cell = self._cell(matrix, "latency_serialization", "monolith")
        self.assertEqual(cell["claim_type"], "measurement")
        # strip the measurement artifact -> classification must fail
        cell["evidence_refs"] = ["adr/ADR-0002-monolith-journal.md"]
        with self.assertRaises(ev.EvalError):
            ev.validate_matrix(matrix, rubric, sha, S1005)

    def test_fact_cell_requires_implementation_or_source_artifact(self):
        rubric, matrix, scenarios, sha = _fresh()
        cell = self._cell(matrix, "policy_boundary", "monolith")
        self.assertEqual(cell["claim_type"], "fact")
        cell["evidence_refs"] = ["results/ENVIRONMENT.md"]
        with self.assertRaises(ev.EvalError):
            ev.validate_matrix(matrix, rubric, sha, S1005)

    def test_unknown_with_numeric_score_still_rejected(self):
        rubric, matrix, scenarios, sha = _fresh()
        cell = self._cell(matrix, "restart_recovery_reconciliation",
                          "containers")
        cell["score"] = 3
        with self.assertRaises(ev.EvalError):
            ev.validate_matrix(matrix, rubric, sha, S1005)


# --------------------------------------------------------------------------
# F3 - production scenario schema strictness
# --------------------------------------------------------------------------

class F3ScenarioStrictnessTests(TestCase):
    def _validated(self, mutate):
        rubric, matrix, scenarios, sha = _fresh()
        scenarios = copy.deepcopy(scenarios)
        mutate(scenarios)
        ev.validate_scenarios(scenarios)

    def test_recorded_scenarios_pass_production_validator(self):
        self._validated(lambda s: None)

    def test_empty_string_branch_rejected(self):
        def mutate(s):
            s["scenarios"][0]["authoritative_state_owner"]["monolith"] = ""
        with self.assertRaises(ev.EvalError):
            self._validated(mutate)

    def test_wrong_type_branch_rejected(self):
        def mutate(s):
            s["scenarios"][0]["allowed_transitions"]["monolith"] = \
                {"step": "restart"}
        with self.assertRaises(ev.EvalError):
            self._validated(mutate)

    def test_partially_empty_transitions_rejected(self):
        def mutate(s):
            s["scenarios"][0]["allowed_transitions"]["containers"] = [
                "restart state container", ""]
        with self.assertRaises(ev.EvalError):
            self._validated(mutate)

    def test_empty_dict_branch_rejected(self):
        def mutate(s):
            s["scenarios"][0]["invariant_impact"] = {}
        with self.assertRaises(ev.EvalError):
            self._validated(mutate)

    def test_empty_stop_condition_rejected(self):
        def mutate(s):
            s["scenarios"][1]["stop_condition"] = "   "
        with self.assertRaises(ev.EvalError):
            self._validated(mutate)


# --------------------------------------------------------------------------
# F4 - weight vectors are persisted and digest-verified
# --------------------------------------------------------------------------

class F4WeightVectorPersistenceTests(TestCase):
    def test_s2_runs_store_full_vectors_and_verify(self):
        recorded = ev.load_json(
            S1005 / "results" / "sensitivity-analysis.json")
        runs = recorded["sensitivity"].get("s2_runs")
        self.assertIsInstance(runs, list)
        self.assertEqual(len(runs), recorded["sensitivity"]["random_runs"])
        total = recorded["sensitivity"]["total_weight"]
        for run in runs:
            self.assertIn("run", run)
            self.assertIn("weights", run)
            self.assertIn("total", run)
            self.assertIn("weights_sha256", run)
            self.assertEqual(run["total"], total)
            self.assertEqual(sum(run["weights"].values()), total)
            digest = hashlib.sha256(json.dumps(
                run["weights"], sort_keys=True).encode()).hexdigest()
            self.assertEqual(digest, run["weights_sha256"])

    def test_weight_vectors_reproduce_winner(self):
        """A sampled subset of persisted vectors must reproduce the
        recorded winner when re-scored."""
        recorded = ev.load_json(
            S1005 / "results" / "sensitivity-analysis.json")
        rubric, matrix, scenarios, sha = _fresh()
        weights = ev.validate_rubric(rubric, S1005 / "rubric.json")
        scoring, _, _ = ev.validate_matrix(matrix, rubric, sha, S1005)
        for run in recorded["sensitivity"]["s2_runs"][:20]:
            scores, _ = ev.weighted_scores(matrix, run["weights"], scoring)
            winner, tie = ev.winner_of(scores)
            self.assertFalse(tie)
            self.assertEqual(winner, run["winner"])


# --------------------------------------------------------------------------
# F5 - subprocess resources are closed (no ResourceWarning)
# --------------------------------------------------------------------------

class F5PipeHandleTests(TestCase):
    def _no_resource_warning(self, mode):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                exp.measure_pipe_child(rounds=8, mode=mode)
            except (ValueError, RuntimeError):
                pass
            gc.collect()
        resource_warnings = [w for w in caught
                             if issubclass(w.category, ResourceWarning)]
        self.assertEqual(resource_warnings, [])

    def test_ok_child_no_resource_warning(self):
        self._no_resource_warning("ok")

    def test_corrupt_child_no_resource_warning(self):
        self._no_resource_warning("corrupt")

    def test_crash_child_no_resource_warning(self):
        self._no_resource_warning("crash")


# --------------------------------------------------------------------------
# F1/F6 - bundle builder behavior (fresh subprocesses, fail-closed)
# --------------------------------------------------------------------------

class F1F6BundleBuilderBehaviorTests(TestCase):
    def test_run_experiments_overwrites_fabricated_file(self):
        """A fabricated boundary-experiments.json must be replaced by a
        fresh subprocess run (finding 1: no publishing of saved results).
        Runs in a TemporaryDirectory: unit tests must never modify tracked
        evidence (review R3, finding 1)."""
        import tempfile
        out = Path(tempfile.mkdtemp()) / "boundary-experiments.json"
        fabricated = {
            "schema": "agentos.s1-005.boundary-experiments/v1",
            "experiments": {
                "small_512b": {"rounds": 10, "in_process_us": 0.1,
                               "pipe_process_us": 0.2, "tcp_localhost_us": 0.3},
                "large_16kb": {"rounds": 10, "in_process_us": 1.0,
                               "pipe_process_us": 2.0, "tcp_localhost_us": 3.0},
                "sqlite_multi_writer": {
                    "single_writer": {"writers": 1, "transactions": 2,
                                      "seconds": 0.1, "txns_per_second": 99},
                    "two_writers": {"writers": 2, "transactions": 2,
                                    "seconds": 0.2, "txns_per_second": 98},
                    "committed_rows_complete": True,
                    "serialized_writes": True},
            },
        }
        out.write_text(json.dumps(fabricated, indent=2), encoding="utf-8")
        import make_bundle
        fresh = make_bundle.run_experiments(out_path=out)
        on_disk = json.loads(out.read_text(encoding="utf-8"))
        self.assertNotEqual(on_disk["experiments"]["small_512b"]["rounds"],
                            fabricated["experiments"]["small_512b"]["rounds"])
        self.assertTrue(
            on_disk["experiments"]["small_512b"]["response_semantics_validated"])
        self.assertEqual(fresh["experiments"]["small_512b"]["rounds"],
                         on_disk["experiments"]["small_512b"]["rounds"])
        self.assertIn("commit", fresh)
        self.assertIn("environment", fresh)

    def _run_fake_evaluator(self, body: str) -> dict:
        """Run the production run_evaluator with a controlled fake
        executable (dependency injection). Fresh-write semantics are
        mandatory: the saved sensitivity output is deleted first, and the
        production evaluator regenerates it afterwards with the ORIGINAL
        run nonce so the file is byte-identical to its prior state."""
        import make_bundle
        orig_nonce = make_bundle._LAST_RUN_NONCE
        saved = (S1005 / "results" / "sensitivity-analysis.json").read_text(
            encoding="utf-8")
        make_bundle._LAST_RUN_NONCE = "review-r2-test-nonce"

        def command_factory():
            nonce = make_bundle._LAST_RUN_NONCE
            body_n = (body
                      .replace("%NONCE%", nonce)
                      .replace("%SENS%", str(
                          S1005 / "results" / "sensitivity-analysis.json")))
            return [sys.executable, "-c", body_n]
        try:
            return make_bundle.run_evaluator(
                command_factory=command_factory,
                experiments_path=S1005 / "results" / "boundary-experiments.json",
                experiments_sha="0" * 64,
                expected_commit="0" * 40,
                run_nonce="review-r2-test-nonce")
        finally:
            _restore_production_sensitivity(saved)
            make_bundle._LAST_RUN_NONCE = orig_nonce
            assert (S1005 / "results" / "sensitivity-analysis.json").read_text(
                encoding="utf-8") == saved

    def test_run_evaluator_rejects_nonzero_exit(self):
        with self.assertRaises(SystemExit):
            self._run_fake_evaluator(
                "import sys; sys.stderr.write('boom'); sys.exit(2)")

    def test_run_evaluator_rejects_malformed_output(self):
        with self.assertRaises(SystemExit):
            self._run_fake_evaluator(
                "import pathlib, sys; p = pathlib.Path(r'%SENS%'); "
                "p.write_text('not json at all', encoding='utf-8')")

    def test_run_evaluator_rejects_nonce_mismatch(self):
        with self.assertRaises(SystemExit):
            self._run_fake_evaluator(
                "import json, pathlib, sys; p = pathlib.Path(r'%SENS%'); "
                "p.write_text(json.dumps({"
                "'schema': 'agentos.s1-005.evaluation/v1',"
                "'verdict': 'PASS_WITH_LIMITS',"
                "'run_nonce': 'WRONG'}), encoding='utf-8')")

    def test_run_evaluator_accepts_fresh_correct_output(self):
        result = self._run_fake_evaluator(
            "import json, os, pathlib, sys;"
            "nonce = os.environ.get('AGENTOS_RUN_NONCE');"
            "p = pathlib.Path(r'%SENS%');"
            "p.write_text(json.dumps({"
            "'schema': 'agentos.s1-005.evaluation/v1',"
            "'verdict': 'PASS_WITH_LIMITS',"
            "'run_nonce': nonce,"
            "'sensitivity': {'stable': True, 's2_all_sums_valid': True}}),"
            "encoding='utf-8')")
        self.assertEqual(result.get("run_nonce"), "review-r2-test-nonce")

    def test_stale_saved_sensitivity_cannot_produce_verdict(self):
        """An impostor that writes NOTHING must fail: the saved verdict
        cannot be published (fresh-write semantics are mandatory, review
        R3 finding 2)."""
        import make_bundle
        orig_nonce = make_bundle._LAST_RUN_NONCE
        saved = (S1005 / "results" / "sensitivity-analysis.json").read_text(
            encoding="utf-8")
        make_bundle._LAST_RUN_NONCE = "review-r2-stale-nonce"

        def command_factory():
            return [sys.executable, "-c", "pass"]
        try:
            with self.assertRaises(SystemExit):
                make_bundle.run_evaluator(
                    command_factory=command_factory,
                    experiments_path=S1005 / "results" / "boundary-experiments.json",
                    experiments_sha="0" * 64,
                    expected_commit="0" * 40,
                    run_nonce="review-r2-stale-nonce")
        finally:
            _restore_production_sensitivity(saved)
            make_bundle._LAST_RUN_NONCE = orig_nonce
        # the impostor run failed closed (SystemExit above); the production
        # restore reproduces the deterministic saved verdict exactly
        self.assertEqual(
            (S1005 / "results" / "sensitivity-analysis.json").read_text(
                encoding="utf-8"),
            saved)

    def test_make_bundle_verifies_commit_and_digest_binding(self):
        recorded = ev.load_json(S1005 / "results" / "boundary-experiments.json")
        self.assertIn("commit", recorded)
        self.assertIn("environment", recorded)
        self.assertIn("output_sha256", recorded)
        # output_sha256 covers the canonical payload without the self-hash
        payload = {k: v for k, v in recorded.items() if k != "output_sha256"}
        canonical = json.dumps(payload, sort_keys=True,
                               separators=(",", ":"),
                               ensure_ascii=False).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(),
                         recorded["output_sha256"])


def make_bundle_module():
    import importlib
    if "make_bundle" not in sys.modules:
        sys.modules["make_bundle"] = importlib.import_module("make_bundle")
    return sys.modules["make_bundle"]


# keep the module importable for the tests above
import make_bundle  # noqa: E402
