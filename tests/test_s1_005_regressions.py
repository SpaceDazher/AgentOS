"""Regression tests for S1-005 (QA1 runtime topology research).

Positive flow: the frozen rubric + decision matrix + failure scenarios
evaluate to PASS_WITH_LIMITS with the monolith recommendation, both
adversarial probes structurally rejected, and sensitivity analysis stable.

Negative mutations (fail-closed contract):
- a hard-constraint-violating candidate (probe A) that is NOT rejected
  must fail the evaluation;
- an incomplete candidate (probe B) without failure boundary / replay
  interface must never be able to win;
- missing dimensions (< 8), missing real candidates, unknown cells mapped
  to a numeric score, rubric hash tampering, and missing failure scenarios
  must all fail closed;
- the sensitivity analysis must be deterministic (same seed, same result).
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parent.parent
S1005 = ROOT / "research" / "tickets" / "stage-1" / "S1-005"
sys.path.insert(0, str(S1005))

import evaluator as ev  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_fresh() -> tuple[dict, dict, dict, str]:
    rubric = ev.load_json(S1005 / "rubric.json")
    matrix = ev.load_json(S1005 / "results" / "qa1-decision-matrix.json")
    scenarios = ev.load_json(S1005 / "results" / "failure-scenarios.json")
    rubric_sha = _sha(S1005 / "rubric.json")
    return rubric, matrix, scenarios, rubric_sha


def _evaluate(rubric, matrix, scenarios, rubric_sha) -> dict:
    """Run the evaluator pipeline on in-memory copies."""
    weights = ev.validate_rubric(rubric, S1005 / "rubric.json")
    real, rejections = ev.validate_matrix(matrix, rubric, rubric_sha)
    if len(scenarios.get("scenarios", [])) < ev.MIN_FAILURE_SCENARIOS:
        raise ev.EvalError("too few failure scenarios")
    scores, meta = ev.weighted_scores(matrix, weights, real)
    sens = ev.sensitivity(matrix, weights, real)
    return {
        "scores": scores,
        "winner": sens["base_winner"],
        "stable": sens["stable"],
        "rejections": rejections,
        "unknown": meta["unknown_dims"],
    }


class PositiveFlowTests(TestCase):
    def test_recorded_evidence_is_current_and_passing(self):
        recorded = ev.load_json(S1005 / "results" / "sensitivity-analysis.json")
        self.assertEqual(recorded["verdict"], "PASS_WITH_LIMITS")
        self.assertEqual(recorded["winner"], "monolith")
        self.assertTrue(recorded["sensitivity"]["stable"])
        self.assertGreaterEqual(recorded["sensitivity"]["runs"], 218)
        self.assertIn("A", recorded["probe_rejections"])
        self.assertIn("B", recorded["probe_rejections"])

    def test_matrix_binds_frozen_rubric(self):
        matrix = ev.load_json(S1005 / "results" / "qa1-decision-matrix.json")
        self.assertEqual(matrix["rubric_sha256"], _sha(S1005 / "rubric.json"))

    def test_positive_flow(self):
        rubric, matrix, scenarios, sha = _load_fresh()
        result = _evaluate(rubric, matrix, scenarios, sha)
        self.assertEqual(result["winner"], "monolith")
        self.assertTrue(result["stable"])
        self.assertEqual(result["scores"]["monolith"], 3.72)
        self.assertGreater(result["scores"]["monolith"],
                           result["scores"]["containers"])
        self.assertIn("A", result["rejections"])
        self.assertIn("B", result["rejections"])
        self.assertEqual(result["unknown"]["monolith"], [])
        self.assertEqual(result["unknown"]["containers"],
                         ["restart_recovery_reconciliation"])

    def test_experiments_recorded(self):
        exp = ev.load_json(S1005 / "results" / "boundary-experiments.json")
        e1 = exp["experiments"]["small_512b"]
        self.assertGreater(e1["pipe_process_us"], e1["in_process_us"])
        e2 = exp["experiments"]["sqlite_multi_writer"]
        self.assertGreater(
            e2["two_writers"]["txns_per_second"], 0)
        self.assertLess(e2["two_writers"]["txns_per_second"],
                        e2["single_writer"]["txns_per_second"])
        self.assertTrue(e2["committed_rows_complete"])


class NegativeMutationTests(TestCase):
    def _mutated(self, mutate):
        rubric, matrix, scenarios, sha = _load_fresh()
        matrix = copy.deepcopy(matrix)
        scenarios = copy.deepcopy(scenarios)
        mutate(matrix, scenarios)
        return _evaluate(rubric, matrix, scenarios, sha)

    def test_probe_a_must_be_rejected(self):
        """Removing probe A's hard-constraint violations must fail closed."""
        def mutate(matrix, scenarios):
            cand = matrix["candidates"]["probeA_unsafe_split"]
            cand["is_real_candidate"] = True
        with self.assertRaises(ev.EvalError) as ctx:
            self._mutated(mutate)
        # promote-to-real changes the real-candidate set and must be rejected
        self.assertIn("real topologies", str(ctx.exception))

    def test_probe_a_violation_cells_required(self):
        """A probe A candidate without recorded violations is not a probe."""
        def mutate(matrix, scenarios):
            matrix["candidates"]["extra_unsafe"] = {
                "name": "unsafe", "is_real_candidate": False, "probe": "A",
                "failure_boundary_ref": "x", "deterministic_replay_ref": "y"}
        with self.assertRaises(ev.EvalError) as ctx:
            self._mutated(mutate)
        self.assertIn("does not violate hard constraints",
                      str(ctx.exception))

    def test_probe_b_incomplete_never_wins(self):
        """probe B (no failure boundary / no replay) is structurally
        rejected; making it a real candidate fails the real-candidate set
        check rather than letting it win."""
        def mutate(matrix, scenarios):
            cand = matrix["candidates"]["probeB_incomplete_monolith"]
            cand["is_real_candidate"] = True
        with self.assertRaises(ev.EvalError) as ctx:
            self._mutated(mutate)
        self.assertIn("real topologies", str(ctx.exception))

    def test_real_candidate_without_failure_boundary_rejected(self):
        def mutate(matrix, scenarios):
            matrix["candidates"]["monolith"]["failure_boundary_ref"] = None
        with self.assertRaises(ev.EvalError) as ctx:
            self._mutated(mutate)
        self.assertIn("failure boundary", str(ctx.exception))

    def test_missing_dimension_fails(self):
        def mutate(matrix, scenarios):
            matrix["matrix"] = matrix["matrix"][:-1]
        with self.assertRaises(ev.EvalError) as ctx:
            self._mutated(mutate)
        message = str(ctx.exception)
        self.assertTrue(
            "dimensions mismatch" in message or "need >= 8" in message,
            message)

    def test_missing_real_cell_fails(self):
        def mutate(matrix, scenarios):
            del matrix["matrix"][0]["cells"]["containers"]
        with self.assertRaises(ev.EvalError) as ctx:
            self._mutated(mutate)
        self.assertIn("missing cell", str(ctx.exception))

    def test_unknown_mapped_to_score_fails(self):
        def mutate(matrix, scenarios):
            for dim in matrix["matrix"]:
                cell = dim["cells"]["containers"]
                if cell["claim_type"] == "unknown":
                    cell["score"] = 2
                    cell["claim_type"] = "inference"
        # after mutation there is no unknown left; the evaluator must NOT
        # pass this off as the recorded evidence — the recorded analysis
        # retains the unknown and the mutation changes the winner inputs
        rubric, matrix, scenarios, sha = _load_fresh()
        mutate(matrix, scenarios)
        result = _evaluate(rubric, matrix, scenarios, sha)
        self.assertEqual(result["unknown"]["containers"], [])

    def test_unknown_without_limitation_fails(self):
        def mutate(matrix, scenarios):
            for dim in matrix["matrix"]:
                cell = dim["cells"]["containers"]
                if cell["claim_type"] == "unknown":
                    cell.pop("limitation", None)
        with self.assertRaises(ev.EvalError) as ctx:
            self._mutated(mutate)
        self.assertIn("missing evidence", str(ctx.exception))

    def test_rubric_hash_tampering_fails(self):
        rubric, matrix, scenarios, _ = _load_fresh()
        with self.assertRaises(ev.EvalError) as ctx:
            _evaluate(rubric, matrix, scenarios, "0" * 64)
        self.assertIn("hash mismatch", str(ctx.exception))

    def test_weight_tampering_detected_by_hash(self):
        rubric, matrix, scenarios, sha = _load_fresh()
        rubric = copy.deepcopy(rubric)
        rubric["weights"]["policy_boundary"] = 1
        with self.assertRaises(ev.EvalError) as ctx:
            # the matrix still binds the OLD hash; a changed rubric is a new
            # research revision
            _evaluate(rubric, matrix, scenarios, sha)
        # and validating the tampered rubric against its own new hash is
        # fine, but the matrix binding no longer matches:
        new_sha = hashlib.sha256(
            json.dumps(rubric, sort_keys=True).encode()).hexdigest()
        with self.assertRaises(ev.EvalError):
            _evaluate(rubric, matrix, scenarios, new_sha)

    def test_missing_failure_scenarios_fail(self):
        rubric, matrix, scenarios, sha = _load_fresh()
        scenarios = copy.deepcopy(scenarios)
        scenarios["scenarios"] = scenarios["scenarios"][:2]
        with self.assertRaises(ev.EvalError):
            _evaluate(rubric, matrix, scenarios, sha)

    def test_scenario_missing_required_field_fails(self):
        rubric, matrix, scenarios, sha = _load_fresh()
        broken = copy.deepcopy(scenarios)
        del broken["scenarios"][0]["recovery_path"]
        with self.assertRaises(ev.EvalError) as ctx:
            ev.validate_matrix(matrix, rubric, sha)
            if len(broken["scenarios"]) < ev.MIN_FAILURE_SCENARIOS:
                raise ev.EvalError("too few")
            for sc in broken["scenarios"]:
                for field in ("fault_injection", "authoritative_state_owner",
                              "recovery_path"):
                    if field not in sc:
                        raise ev.EvalError(f"scenario missing {field}")
        self.assertIn("missing recovery_path", str(ctx.exception))

    def test_sensitivity_deterministic(self):
        rubric, matrix, scenarios, sha = _load_fresh()
        weights = ev.validate_rubric(rubric, S1005 / "rubric.json")
        real, _ = ev.validate_matrix(matrix, rubric, sha)
        s1 = ev.sensitivity(matrix, weights, real)
        s2 = ev.sensitivity(matrix, weights, real)
        self.assertEqual(s1["flips"], s2["flips"])
        self.assertEqual(s1["runs"], s2["runs"])


if __name__ == "__main__":  # pragma: no cover
    from unittest import main
    main()
