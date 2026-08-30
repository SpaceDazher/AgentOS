"""Fail-closed regressions for the S1-004 corrective review."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
TICKET = ROOT / "research" / "tickets" / "stage-1" / "S1-004"
SIM_DIR = TICKET / "simulator"
sys.path.insert(0, str(SIM_DIR))

import invariant_simulator as isim  # noqa: E402
import run_acceptance  # noqa: E402
import run_formal  # noqa: E402


def _alloy_body(commands: dict[str, str]) -> str:
    messages = {
        "SAT": "Instance found. Predicate is consistent.",
        "UNSAT": "No instance found. Predicate may be inconsistent.",
    }
    return "\n".join(
        f'Executing "{command}"\n{messages[verdict]}'
        for command, verdict in commands.items()
    )


def _tlc_console(*, temporal: bool = True) -> str:
    lines = [
        "903731 states generated, 271168 distinct states found, "
        "0 states left on queue.",
    ]
    if temporal:
        lines.append("Finished checking temporal properties in 11s")
    lines.append("Model checking completed. No error has been found.")
    return "\n".join(lines)


class FormalFailClosedTests(TestCase):
    def test_alloy_requires_zero_exit_and_exact_command_matrix(self):
        expected = run_formal.EXPECTED_ALLOY_COMMANDS
        result = run_formal.validate_alloy_execution(0, _alloy_body(expected))
        self.assertEqual(len(result["commands"]), 12)
        self.assertEqual(result["verdict"], "PASS")

        with self.assertRaises(ValueError):
            run_formal.validate_alloy_execution(7, _alloy_body(expected))
        with self.assertRaises(ValueError):
            run_formal.validate_alloy_execution(
                0, _alloy_body(dict(list(expected.items())[:-1])))
        first = next(iter(expected.items()))
        with self.assertRaises(ValueError):
            run_formal.validate_alloy_execution(
                0, _alloy_body(expected) + "\n" + _alloy_body(dict([first])))

    def test_tlc_requires_temporal_marker_and_complete_config(self):
        cfg = (TICKET / "tla" / "agentos_transitions_v1.cfg").read_text(
            encoding="utf-8")
        result = run_formal.validate_tlc_execution(0, _tlc_console(), cfg)
        self.assertTrue(result["temporal_properties_checked"])
        self.assertGreater(result["states_generated"], 0)

        with self.assertRaises(ValueError):
            run_formal.validate_tlc_execution(
                0, _tlc_console(temporal=False), cfg)
        with self.assertRaises(ValueError):
            run_formal.validate_tlc_execution(
                0, _tlc_console(), cfg.replace("PROPERTY LiveDelivery", ""))
        with self.assertRaises(ValueError):
            run_formal.validate_tlc_execution(
                0, _tlc_console(), cfg.replace("INVARIANT TypeOk", ""))
        with self.assertRaises(ValueError):
            run_formal.validate_tlc_execution(
                0, _tlc_console(), cfg.replace("Alloc = 3", "Alloc = 30"))


class AcceptanceFailClosedTests(TestCase):
    def test_acceptance_requires_three_distinct_seeds(self):
        with self.assertRaises(ValueError):
            run_acceptance.validate_acceptance_request(
                [11], run_acceptance.ACCEPTANCE_OPS)
        with self.assertRaises(ValueError):
            run_acceptance.validate_acceptance_request(
                [11, 11, 22], run_acceptance.ACCEPTANCE_OPS)
        run_acceptance.validate_acceptance_request(
            [11, 22, 33], run_acceptance.ACCEPTANCE_OPS)

    def test_rerun_is_a_fresh_subprocess_with_validated_result(self):
        _, expected = isim.simulate(71, 50)
        rerun = run_acceptance.rerun_seed(
            71, 50, expected["trace_digest"])
        self.assertEqual(rerun["executor"]["mode"], "subprocess")
        self.assertTrue(rerun["digest_match"])
        self.assertEqual(rerun["invariant_counters"], expected["invariant_counters"])

    def test_rerun_nonzero_exit_fails_closed(self):
        completed = subprocess.CompletedProcess(
            args=["simulator"], returncode=3, stdout="{}", stderr="boom")
        with patch.object(run_acceptance.subprocess, "run", return_value=completed):
            with self.assertRaises(RuntimeError):
                run_acceptance.rerun_seed(71, 50, "abc")

    def test_boolean_counter_and_incomplete_operation_counts_fail_closed(self):
        _, valid = isim.simulate(71, 50)
        boolean_counter = json.loads(json.dumps(valid))
        boolean_counter["invariant_counters"]["INV1"] = False
        with self.assertRaises(RuntimeError):
            run_acceptance.validate_simulation_result(boolean_counter, 71, 50)

        incomplete_counts = json.loads(json.dumps(valid))
        incomplete_counts["op_counts"] = {"allow": 1}
        with self.assertRaises(RuntimeError):
            run_acceptance.validate_simulation_result(incomplete_counts, 71, 50)

    def test_unknown_invariant_counter_fails_closed(self):
        _, result = isim.simulate(73, 50)
        result["invariant_counters"]["UNKNOWN_INVARIANT"] = 1
        with self.assertRaisesRegex(RuntimeError, "unexpected"):
            run_acceptance.validate_simulation_result(result, 73, 50)

    def test_skip_rerun_bypass_is_not_available(self):
        source = (SIM_DIR / "run_acceptance.py").read_text(encoding="utf-8")
        self.assertNotIn("--skip-rerun", source)


class SimulatorCorrectnessTests(TestCase):
    def test_inv6_aggregates_all_child_reservations(self):
        sim = isim.Simulator(1)
        parent, child_a, child_b = 0, 8, 16
        sim.g_reserved[parent] = 2
        sim.g_reserved[child_a] = 2
        sim.g_reserved[child_b] = 2
        with self.assertRaises(isim.Violation) as ctx:
            sim.audit()
        self.assertEqual(ctx.exception.invariant, "INV6")

    def test_probe_b_exercises_real_operations(self):
        probe = isim.probe_reserve_revoke_retry()
        self.assertTrue(probe["passed"], probe)
        counts = probe["checks"]["actual_operation_counts"]
        for operation in (
                "reserve_child", "allow", "publish", "delivery_timeout",
                "reconcile", "retry"):
            self.assertGreater(counts.get(operation, 0), 0, operation)


class EvidenceSnapshotTests(TestCase):
    def test_evaluation_record_binds_tracked_content_addressed_pack(self):
        record = json.loads((TICKET / "evaluation-record.json").read_text(
            encoding="utf-8"))
        raw_path = record["evidence_pack"]["path"].replace("\\", "/")
        self.assertTrue(raw_path.startswith(
            "research/tickets/stage-1/S1-004/results/evidence/"), raw_path)
        self.assertNotIn(".agentos-research", raw_path)
        pack = ROOT / Path(raw_path)
        self.assertTrue(pack.is_file(), pack)
        digest = hashlib.sha256(pack.read_bytes()).hexdigest()
        self.assertEqual(digest, record["evidence_pack"]["sha256"])
        self.assertIn(digest, pack.name)
