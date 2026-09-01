"""TDD regression tests for S1-008 revocation latency validation.

Tests follow fail-closed principles. Tests are written first (RED) then
verified against the implementation (GREEN).
"""
import json
import os
import sys
import unittest
import tempfile
from pathlib import Path

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

S1_008_DIR = Path(__file__).resolve().parents[1] / "research/tickets/stage-1/S1-008"
RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"


class TestS1008DependencyGate(unittest.TestCase):
    """Test: dependency gate accepts S1-002/S1-004 and rejects stale/tampered."""

    def test_dependency_gate_json_exists(self):
        """dependency-gate.json must exist and be valid."""
        gate_path = S1_008_DIR / "dependency-gate.json"
        self.assertTrue(gate_path.exists(), "dependency-gate.json must exist")
        data = json.loads(gate_path.read_text())
        self.assertTrue(data.get("overall_ok", False), "dependency gate must pass")

    def test_dependency_gate_has_s1_002_s1_004(self):
        """Gate must include both S1-002 and S1-004 dependencies."""
        gate_path = S1_008_DIR / "dependency-gate.json"
        data = json.loads(gate_path.read_text())
        deps = data.get("dependencies", {})
        self.assertIn("S1-002", deps)
        self.assertIn("S1-004", deps)


class TestS1008FrozenArtifacts(unittest.TestCase):
    """Test: frozen artifacts exist and are content-addressed."""

    def test_all_frozen_artifacts_exist(self):
        """All required frozen artifacts must exist."""
        artifacts = [
            "revocation-contract.json",
            "workload-manifest.json",
            "threat-model.json",
            "rubric.json",
            "fixtures.json",
            "corpus-manifest.json",
        ]
        for artifact in artifacts:
            path = S1_008_DIR / artifact
            self.assertTrue(path.exists(), f"{artifact} must exist")
            json.loads(path.read_text())  # Must be valid JSON

    def test_contract_has_hard_bound(self):
        """revocation-contract.json must contain 5000ms hard bound."""
        contract = json.loads((S1_008_DIR / "revocation-contract.json").read_text())
        self.assertEqual(contract.get("hard_target_ms"), 5000)

    def test_contract_has_time_semantics(self):
        """Contract must define all required time markers."""
        contract = json.loads((S1_008_DIR / "revocation-contract.json").read_text())
        for marker in ["t_request", "t_commit", "t_observe", "t_decision", "t_deny", "t_effect"]:
            self.assertIn(marker, contract.get("time_semantics", {}))

    def test_rubric_has_hard_gates(self):
        """rubric.json must contain hard gates."""
        rubric = json.loads((S1_008_DIR / "rubric.json").read_text())
        hard_gates = rubric.get("hard_gates", {})
        self.assertEqual(hard_gates.get("max_latency_ms"), 5000)
        self.assertEqual(hard_gates.get("max_allow_after_commit"), 0)


class TestS1008MeasurementMatrix(unittest.TestCase):
    """Test: measurement matrix has 72 observations and ≥100 trials per run."""

    def test_run_a_has_72_observations(self):
        """Run A must have 72 mandatory scenario-seed observations."""
        manifest = json.loads((RESULTS_DIR / "run-a/manifest.json").read_text())
        self.assertEqual(manifest["matrix"]["base_observations"], 72)

    def test_run_a_has_100_plus_trials(self):
        """Run A must have ≥100 revocation trials."""
        manifest = json.loads((RESULTS_DIR / "run-a/manifest.json").read_text())
        self.assertGreaterEqual(manifest["matrix"]["total_trials"], 100)

    def test_run_b_has_72_observations(self):
        """Run B must have 72 mandatory scenario-seed observations."""
        manifest = json.loads((RESULTS_DIR / "run-b/manifest.json").read_text())
        self.assertEqual(manifest["matrix"]["base_observations"], 72)

    def test_run_b_has_100_plus_trials(self):
        """Run B must have ≥100 revocation trials."""
        manifest = json.loads((RESULTS_DIR / "run-b/manifest.json").read_text())
        self.assertGreaterEqual(manifest["matrix"]["total_trials"], 100)

    def test_four_paths_represented(self):
        """All 4 enforcement paths must be present in the matrix."""
        manifest = json.loads((RESULTS_DIR / "run-a/manifest.json").read_text())
        # paths is stored as a count in the manifest
        self.assertEqual(manifest["matrix"]["paths"], 4)


class TestS1008HardCounters(unittest.TestCase):
    """Test: all hard counters must be zero."""

    def test_run_a_all_hard_counters_zero(self):
        """Run A must have zero hard counters."""
        manifest = json.loads((RESULTS_DIR / "run-a/manifest.json").read_text())
        counters = manifest["hard_counters"]
        for name, value in counters.items():
            self.assertEqual(value, 0, f"Run A hard counter {name} = {value} (expected 0)")

    def test_run_b_all_hard_counters_zero(self):
        """Run B must have zero hard counters."""
        manifest = json.loads((RESULTS_DIR / "run-b/manifest.json").read_text())
        counters = manifest["hard_counters"]
        for name, value in counters.items():
            self.assertEqual(value, 0, f"Run B hard counter {name} = {value} (expected 0)")


class TestS1008LatencyBounds(unittest.TestCase):
    """Test: maximum latency ≤5000ms for each mandatory scenario."""

    def test_run_a_max_latency_within_bound(self):
        """Run A max latency must be ≤5000ms."""
        manifest = json.loads((RESULTS_DIR / "run-a/manifest.json").read_text())
        max_latency = manifest["latency_ms"]["max"]
        self.assertLessEqual(max_latency, 5000, f"Run A max latency {max_latency}ms > 5000ms")

    def test_run_b_max_latency_within_bound(self):
        """Run B max latency must be ≤5000ms."""
        manifest = json.loads((RESULTS_DIR / "run-b/manifest.json").read_text())
        max_latency = manifest["latency_ms"]["max"]
        self.assertLessEqual(max_latency, 5000, f"Run B max latency {max_latency}ms > 5000ms")

    def test_latency_stats_have_required_percentiles(self):
        """Latency stats must include max, p50, p95, p99."""
        manifest = json.loads((RESULTS_DIR / "run-a/manifest.json").read_text())
        stats = manifest["latency_ms"]
        for key in ["max", "p50", "p95", "p99"]:
            self.assertIn(key, stats, f"latency_ms missing {key}")


class TestS1008AdversarialProbes(unittest.TestCase):
    """Test: adversarial probes A-F are detected."""

    def test_all_probes_detected(self):
        """All probes A-F must be detected with violations."""
        eval_result = json.loads((RESULTS_DIR / "evaluation-result.json").read_text())
        probe_results = eval_result.get("probe_results", {})
        for letter in ["A", "B", "C", "D", "E", "F"]:
            self.assertIn(letter, probe_results, f"Probe {letter} not found in probe_results")
            self.assertTrue(probe_results[letter].get("detected", False),
                           f"Probe {letter} not detected")


class TestS1008HashBinding(unittest.TestCase):
    """Test: raw trace hash binding is verified."""

    def test_run_a_all_traces_hash_binding(self):
        """All run A traces must pass hash binding verification."""
        eval_result = json.loads((RESULTS_DIR / "evaluation-result.json").read_text())
        self.assertEqual(eval_result.get("hash_binding_failures", 0), 0,
                        "Run A has hash binding failures")

    def test_comparison_passes(self):
        """Comparison of A vs B must pass."""
        comparison = json.loads((RESULTS_DIR / "comparison.json").read_text())
        self.assertEqual(comparison["verdict"], "PASS",
                        f"Comparison verdict is {comparison['verdict']}, expected PASS")


class TestS1008ExecutorSeparation(unittest.TestCase):
    """Test: main and rerun have different executor IDs and output roots."""

    def test_different_executor_ids(self):
        """Run A and Run B must have different executor IDs."""
        manifest_a = json.loads((RESULTS_DIR / "run-a/manifest.json").read_text())
        manifest_b = json.loads((RESULTS_DIR / "run-b/manifest.json").read_text())
        self.assertNotEqual(manifest_a["executor_id"], manifest_b["executor_id"])

    def test_different_output_roots(self):
        """Run A and Run B must have different output directories."""
        manifest_a = json.loads((RESULTS_DIR / "run-a/manifest.json").read_text())
        manifest_b = json.loads((RESULTS_DIR / "run-b/manifest.json").read_text())
        # Use raw_trace_dir as the output root identifier
        self.assertNotEqual(manifest_a.get("raw_trace_dir", ""), manifest_b.get("raw_trace_dir", ""))


class TestS1008FinalVerdict(unittest.TestCase):
    """Test: final verdict and evaluation record."""

    def test_evaluation_record_exists(self):
        """evaluation-record.json must exist in S1-008."""
        path = S1_008_DIR / "evaluation-record.json"
        self.assertTrue(path.exists(), "evaluation-record.json must exist")
        data = json.loads(path.read_text())
        self.assertIn("verdict", data)

    def test_evaluation_record_verdict_pass(self):
        """Evaluation record must have PASS verdict."""
        path = S1_008_DIR / "evaluation-record.json"
        data = json.loads(path.read_text())
        self.assertEqual(data["verdict"], "PASS",
                        f"Verdict is {data['verdict']}, expected PASS")

    def test_bundle_exists(self):
        """bundle.json must exist in S1-008."""
        path = S1_008_DIR / "bundle.json"
        self.assertTrue(path.exists(), "bundle.json must exist")
        data = json.loads(path.read_text())
        self.assertIn("artifact_chain_hash", data)

    def test_evidence_pack_exists(self):
        """Evidence pack must exist in results/evidence/."""
        evidence_dir = RESULTS_DIR / "evidence"
        packs = list(evidence_dir.glob("evidence-pack-*.json"))
        self.assertTrue(len(packs) > 0, "No evidence pack found in results/evidence/")
        # Pack verdict matches run-a evaluation; comparison verdict is the combined verdict
        pack = json.loads(packs[0].read_text())
        self.assertIn(pack["verdict"], ["PASS", "PASS_WITH_LIMITS"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
