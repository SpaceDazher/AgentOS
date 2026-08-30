"""Independent negative probes for the S1-005 REVIEW_R1 findings.

Each test class maps to one review finding and is written RED-first:
it encodes the DESIRED fail-closed behavior, not the current one.

F1: hard-constraint violations must reject any candidate (not only probe A).
F2: the bundle must derive its verdict from the evaluator subprocess, not
    hardcode it.
F3: evidence packs must be published inside the repository (tracked,
    content-addressed) with file sha AND normalized payload sha, and the
    record must carry the exact research revision.
F4: the decision matrix must reject duplicate dimensions, incomplete cells
    (evidence_refs/confidence/statement), non-existent evidence paths and
    unknown cells carrying numeric scores.
F5: failure scenarios need a strict schema: unique ids, non-empty required
    fields, both topology branches, and INV/SAF/LIVE references.
F6: sensitivity random weight vectors must sum exactly to the rubric total,
    ties must be indeterminate, and the winner must not depend on candidate
    insertion order.
F7: IPC experiments must validate response semantics and child exit codes,
    and must fail on crashed children or corrupt responses.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parent.parent
S1005 = ROOT / "research" / "tickets" / "stage-1" / "S1-005"
sys.path.insert(0, str(S1005))

import evaluator as ev  # noqa: E402
import experiments as exp  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fresh():
    rubric = ev.load_json(S1005 / "rubric.json")
    matrix = ev.load_json(S1005 / "results" / "qa1-decision-matrix.json")
    scenarios = ev.load_json(S1005 / "results" / "failure-scenarios.json")
    sha = _sha(S1005 / "rubric.json")
    return rubric, copy.deepcopy(matrix), copy.deepcopy(scenarios), sha


def _full(rubric, matrix, scenarios, sha):
    """Run validation + scoring; returns the full evaluation dict."""
    weights = ev.validate_rubric(rubric, S1005 / "rubric.json")
    real, rejections, rejected_real = ev.validate_matrix(
        matrix, rubric, sha, S1005)
    if len(scenarios.get("scenarios", [])) < ev.MIN_FAILURE_SCENARIOS:
        raise ev.EvalError("too few failure scenarios")
    scores, meta = ev.weighted_scores(matrix, weights, real)
    sens = ev.sensitivity(matrix, weights, real)
    return {
        "real": real,
        "rejections": rejections,
        "scores": scores,
        "meta": meta,
        "sensitivity": sens,
        "winner": sens["base_winner"],
    }


# --------------------------------------------------------------------------
# F1 - hard constraints reject ANY candidate
# --------------------------------------------------------------------------

class F1HardConstraintTests(TestCase):
    VIOLATION = "single_canonical_state_writer"

    def _with_violation(self, cid):
        rubric, matrix, scenarios, sha = _fresh()
        for dim in matrix["matrix"]:
            if dim["dimension"] == "policy_boundary":
                cell = dim["cells"][cid]
                cell["hard_constraint_violations"] = [self.VIOLATION]
                break
        return _full(rubric, matrix, scenarios, sha)

    def test_monolith_with_violation_is_rejected_and_not_winner(self):
        result = self._with_violation("monolith")
        self.assertNotIn("monolith", result["real"],
                         "violating real candidate must be rejected")
        self.assertNotEqual(result["winner"], "monolith")
        self.assertEqual(result["winner"], "containers")

    def test_containers_with_violation_is_rejected_and_not_winner(self):
        result = self._with_violation("containers")
        self.assertNotIn("containers", result["real"])
        self.assertNotEqual(result["winner"], "containers")

    def test_all_real_candidates_rejected_fails_closed(self):
        rubric, matrix, scenarios, sha = _fresh()
        for dim in matrix["matrix"]:
            if dim["dimension"] == "policy_boundary":
                for cid in ("monolith", "containers"):
                    dim["cells"][cid]["hard_constraint_violations"] = [
                        self.VIOLATION]
        with self.assertRaises(ev.EvalError):
            _full(rubric, matrix, scenarios, sha)

    def test_unknown_violation_id_rejected(self):
        rubric, matrix, scenarios, sha = _fresh()
        for dim in matrix["matrix"]:
            if dim["dimension"] == "policy_boundary":
                dim["cells"]["monolith"]["hard_constraint_violations"] = [
                    "made_up_constraint"]
        with self.assertRaises(ev.EvalError):
            _full(rubric, matrix, scenarios, sha)


# --------------------------------------------------------------------------
# F4 - decision matrix structural integrity
# --------------------------------------------------------------------------

class F4MatrixIntegrityTests(TestCase):
    def test_duplicate_dimension_row_rejected(self):
        rubric, matrix, scenarios, sha = _fresh()
        matrix["matrix"].append(copy.deepcopy(matrix["matrix"][0]))
        with self.assertRaises(ev.EvalError):
            _full(rubric, matrix, scenarios, sha)

    def test_cell_without_evidence_refs_rejected(self):
        rubric, matrix, scenarios, sha = _fresh()
        matrix["matrix"][0]["cells"]["monolith"]["evidence_refs"] = []
        with self.assertRaises(ev.EvalError):
            _full(rubric, matrix, scenarios, sha)

    def test_cell_without_confidence_rejected(self):
        rubric, matrix, scenarios, sha = _fresh()
        matrix["matrix"][0]["cells"]["monolith"].pop("confidence", None)
        with self.assertRaises(ev.EvalError):
            _full(rubric, matrix, scenarios, sha)

    def test_cell_without_statement_rejected(self):
        rubric, matrix, scenarios, sha = _fresh()
        matrix["matrix"][0]["cells"]["monolith"]["statement"] = ""
        with self.assertRaises(ev.EvalError):
            _full(rubric, matrix, scenarios, sha)

    def test_nonexistent_evidence_path_rejected(self):
        rubric, matrix, scenarios, sha = _fresh()
        cell = matrix["matrix"][0]["cells"]["monolith"]
        cell["evidence_refs"] = ["src/agentos/does_not_exist.py"]
        with self.assertRaises(ev.EvalError):
            _full(rubric, matrix, scenarios, sha)

    def test_unknown_with_numeric_score_rejected(self):
        rubric, matrix, scenarios, sha = _fresh()
        for dim in matrix["matrix"]:
            cell = dim["cells"]["containers"]
            if cell["claim_type"] == "unknown":
                cell["score"] = 2
        with self.assertRaises(ev.EvalError):
            _full(rubric, matrix, scenarios, sha)


# --------------------------------------------------------------------------
# F5 - failure scenario schema strictness
# --------------------------------------------------------------------------

def _validate_scenarios(scenarios):
    ids = set()
    for sc in scenarios.get("scenarios", []):
        sid = sc.get("id")
        if not sid or sid in ids:
            raise ev.EvalError(f"scenario id missing or duplicated: {sid!r}")
        ids.add(sid)
        for field in ("title", "fault_injection", "initial_state",
                      "authoritative_state_owner", "allowed_transitions",
                      "recovery_path", "observable_artifacts",
                      "stop_condition", "invariant_impact"):
            value = sc.get(field)
            if value is None or value == "" or value == [] or value == {}:
                raise ev.EvalError(f"scenario {sid}: field {field} is empty")
        for topology in ("monolith", "containers"):
            if topology not in sc["authoritative_state_owner"]:
                raise ev.EvalError(
                    f"scenario {sid}: missing state owner for {topology}")
            if topology not in sc["allowed_transitions"]:
                raise ev.EvalError(
                    f"scenario {sid}: missing transitions for {topology}")
            if topology not in sc["recovery_path"]:
                raise ev.EvalError(
                    f"scenario {sid}: missing recovery for {topology}")
            if topology not in sc["invariant_impact"]:
                raise ev.EvalError(
                    f"scenario {sid}: missing invariant impact for {topology}")
            impact = json.dumps(sc["invariant_impact"][topology])
            import re
            if not re.search(r"\b(INV[1-6]|SAF\d|LIVE\d)", impact):
                raise ev.EvalError(
                    f"scenario {sid}: invariant impact for {topology} does "
                    "not reference INV/SAF/LIVE")
        if not sc["observable_artifacts"]:
            raise ev.EvalError(f"scenario {sid}: no observable artifacts")


class F5ScenarioSchemaTests(TestCase):
    def _validated(self, mutate):
        rubric, matrix, scenarios, sha = _fresh()
        scenarios = copy.deepcopy(scenarios)
        mutate(scenarios)
        _validate_scenarios(scenarios)

    def test_recorded_scenarios_pass_strict_schema(self):
        self._validated(lambda s: None)

    def test_empty_fault_injection_rejected(self):
        def mutate(s):
            s["scenarios"][0]["fault_injection"] = ""
        with self.assertRaises(ev.EvalError):
            self._validated(mutate)

    def test_duplicate_scenario_ids_rejected(self):
        def mutate(s):
            s["scenarios"][1]["id"] = s["scenarios"][0]["id"]
        with self.assertRaises(ev.EvalError):
            self._validated(mutate)

    def test_missing_topology_branch_rejected(self):
        def mutate(s):
            del s["scenarios"][0]["allowed_transitions"]["containers"]
        with self.assertRaises(ev.EvalError):
            self._validated(mutate)

    def test_invariant_impact_without_refs_rejected(self):
        def mutate(s):
            s["scenarios"][0]["invariant_impact"]["monolith"] = \
                "все хорошо, ничего не нарушено"
        with self.assertRaises(ev.EvalError):
            self._validated(mutate)

    def test_empty_artifacts_rejected(self):
        def mutate(s):
            s["scenarios"][0]["observable_artifacts"] = []
        with self.assertRaises(ev.EvalError):
            self._validated(mutate)


# --------------------------------------------------------------------------
# F6 - sensitivity weight composition and tie semantics
# --------------------------------------------------------------------------

class F6SensitivityTests(TestCase):
    def test_random_compositions_sum_exactly(self):
        rng = ev.random.Random(42)
        total = 0
        for _ in range(200):
            parts = ev.random_composition(100, 8, rng)
            self.assertEqual(sum(parts), 100)
            self.assertTrue(all(p >= 1 for p in parts))
            total += 1
        self.assertEqual(total, 200)

    def test_s2_vectors_sum_to_total(self):
        rubric = ev.load_json(S1005 / "rubric.json")
        matrix = ev.load_json(S1005 / "results" / "qa1-decision-matrix.json")
        weights = ev.validate_rubric(rubric, S1005 / "rubric.json")
        real, _, _ = ev.validate_matrix(matrix, rubric, _sha(S1005 / "rubric.json"), S1005)
        sens = ev.sensitivity(matrix, weights, real)
        self.assertTrue(sens.get("s2_all_sums_valid"),
                        "every S2 weight vector must sum to the rubric total")

    def test_winner_independent_of_insertion_order(self):
        rubric = ev.load_json(S1005 / "rubric.json")
        matrix = ev.load_json(S1005 / "results" / "qa1-decision-matrix.json")
        weights = ev.validate_rubric(rubric, S1005 / "rubric.json")
        real, _, _ = ev.validate_matrix(matrix, rubric, _sha(S1005 / "rubric.json"), S1005)
        forward = ev.weighted_scores(matrix, weights, list(real))
        backward = ev.weighted_scores(matrix, weights, list(reversed(real)))
        self.assertEqual(
            forward[0]["monolith"], backward[0]["monolith"])
        self.assertEqual(
            forward[0]["containers"], backward[0]["containers"])

    def test_tie_is_indeterminate_not_insertion_order(self):
        winner, tie = ev.winner_of({"a": 3.0, "b": 3.0})
        self.assertTrue(tie)
        self.assertIsNone(winner)
        winner, tie = ev.winner_of({"a": 3.1, "b": 3.0})
        self.assertFalse(tie)
        self.assertEqual(winner, "a")


# --------------------------------------------------------------------------
# F7 - IPC experiment response semantics
# --------------------------------------------------------------------------

class F7ExperimentSemanticsTests(TestCase):
    def test_valid_response_accepted(self):
        exp._require_valid_response({"allow": True, "reason": "policy.match"})

    def test_wrong_semantics_rejected(self):
        with self.assertRaises(ValueError):
            exp._require_valid_response({"allow": False,
                                         "reason": "policy.deny"})
        with self.assertRaises(ValueError):
            exp._require_valid_response({"ok": True})

    def test_corrupt_child_detected(self):
        with self.assertRaises(ValueError):
            exp.measure_pipe_child(rounds=5, mode="corrupt")

    def test_crashed_child_detected(self):
        with self.assertRaises((RuntimeError, ValueError)):
            exp.measure_pipe_child(rounds=5, mode="crash")

    def test_healthy_child_validates_semantics(self):
        stats = exp.measure_pipe_child(rounds=25, mode="ok")
        self.assertEqual(stats["validated"], 25)
        self.assertEqual(stats["child_exit_code"], 0)


# --------------------------------------------------------------------------
# F2/F3 - bundle derives verdict from evaluator; evidence pack published
# --------------------------------------------------------------------------

class F2F3BundleAndPackTests(TestCase):
    def test_bundle_verdict_matches_evaluator_output(self):
        recorded = ev.load_json(S1005 / "results" / "sensitivity-analysis.json")
        bundle = ev.load_json(S1005 / "bundle.json")
        self.assertEqual(bundle["audit"]["verdict"], recorded["verdict"].lower())
        eval_claim = next(c for c in bundle["claims"]
                          if c["id"] == "c3-evaluation")
        self.assertIn(str(recorded["winner"]), eval_claim["text"])
        self.assertIn(str(recorded["scores_normalized"]["monolith"]),
                      eval_claim["text"])

    def test_bundle_ran_evaluator_subprocess(self):
        source = (S1005 / "make_bundle.py").read_text(encoding="utf-8")
        self.assertIn("evaluator.py", source)
        self.assertIn("subprocess", source)
        self.assertIn("returncode", source)

    def test_experiments_validated_before_bundle(self):
        """Behavioral: the bundle builder's experiment validator must
        reject a fabricated minimal result (review R2 F6; review R3 F5
        supersede the source-text check with a behavioral one)."""
        import make_bundle
        fabricated = {
            "schema": "agentos.s1-005.boundary-experiments/v1",
            "commit": "0" * 40, "tree_sha": "0" * 40, "dirty": False,
            "environment": {"python": "3.12"},
            "script_hashes": {},
            "output_sha256": "0" * 64,
            "experiments": {
                "small_512b": {"rounds": 10, "in_process_us": 0.1,
                               "pipe_process_us": 0.2,
                               "tcp_localhost_us": 0.3,
                               "response_semantics_validated": True,
                               "validated_counts": {"a": 10}},
                "large_16kb": {"rounds": 10, "in_process_us": 1.0,
                               "pipe_process_us": 2.0,
                               "tcp_localhost_us": 3.0,
                               "response_semantics_validated": True,
                               "validated_counts": {"a": 10}},
                "sqlite_multi_writer": {
                    "single_writer": {"writers": 1, "transactions": 2,
                                      "seconds": 0.1, "txns_per_second": 99},
                    "two_writers": {"writers": 2, "transactions": 2,
                                    "seconds": 0.2, "txns_per_second": 98,
                                    "writer_results": [{"busy": 0}, {"busy": 0}]},
                    "committed_rows_complete": True,
                    "serialized_writes": True},
            },
        }
        with self.assertRaises(SystemExit):
            make_bundle.validate_experiments_data(fabricated)

    def test_evidence_pack_tracked_and_bound(self):
        record = ev.load_json(S1005 / "evaluation-record.json")
        self.assertIn("research_revision", record)
        pack_ref = record["evidence_pack"]
        self.assertIn("payload_sha256", pack_ref)
        tracked = ROOT / record["evidence_pack"]["path"]
        self.assertTrue(tracked.is_file(),
                        "tracked evidence pack must be committed")
        self.assertEqual(_sha(tracked), pack_ref["sha256"])
        pack = json.loads(tracked.read_text(encoding="utf-8"))
        # the normalized payload hash excludes the self-hash field
        payload = {k: v for k, v in pack.items() if k != "sha256"}
        canonical = json.dumps(payload, sort_keys=True,
                               separators=(",", ":")).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(),
                         pack_ref["payload_sha256"])
        self.assertEqual(pack_ref["payload_sha256"], pack["sha256"])
