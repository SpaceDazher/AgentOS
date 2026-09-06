"""Regression gates for wall-clock contamination before S1-019 synthesis."""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "research" / "tickets" / "stage-1" / "S1-019"
    / "preflight_wall_clock.py"
)
SPEC = importlib.util.spec_from_file_location("s1019_preflight", MODULE_PATH)
preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preflight
SPEC.loader.exec_module(preflight)


class MemoryTree:
    def __init__(self, files: dict[str, object]):
        self.files = {
            path: value if isinstance(value, str) else json.dumps(value)
            for path, value in files.items()
        }

    def has(self, path: str) -> bool:
        return path in self.files

    def read_text(self, path: str) -> str:
        return self.files[path]

    def read_json(self, path: str) -> dict:
        return json.loads(self.read_text(path))

    def list_files(self, prefix: str) -> list[str]:
        return sorted(path for path in self.files if path.startswith(prefix))


class WallClockPreflightTests(unittest.TestCase):
    def test_clock_calls_are_found_by_ast_not_comments(self):
        source = """\nimport time\n# time.perf_counter_ns()\ndef run():\n    return time.perf_counter_ns()\n"""
        self.assertEqual(
            preflight.clock_calls(source),
            [{"line": 5, "call": "time.perf_counter_ns"}],
        )

    def test_clock_calls_follow_direct_import_aliases(self):
        source = """\nfrom time import perf_counter_ns as host_clock\ndef run():\n    return host_clock()\n"""
        self.assertEqual(
            preflight.clock_calls(source),
            [{"line": 4, "call": "time.perf_counter_ns"}],
        )

    def test_s1_005_counterfactual_preserves_winner_without_latency(self):
        matrix = {
            "matrix": [
                {"dimension": "safety", "cells": {
                    "monolith": {"score": 4}, "containers": {"score": 2}}},
                {"dimension": "latency_serialization", "cells": {
                    "monolith": {"score": 4}, "containers": {"score": 0}}},
            ]
        }
        rubric = {"weights": {"safety": 10, "latency_serialization": 1}}
        result = {"winner": "monolith"}
        check = preflight.check_s1_005(matrix, rubric, result)
        self.assertTrue(check["passed"])
        self.assertEqual(check["counterfactual_winner"], "monolith")

    def test_s1_005_fails_when_latency_is_decisive(self):
        matrix = {
            "matrix": [
                {"dimension": "safety", "cells": {
                    "monolith": {"score": 2}, "containers": {"score": 4}}},
                {"dimension": "latency_serialization", "cells": {
                    "monolith": {"score": 4}, "containers": {"score": 0}}},
            ]
        }
        rubric = {"weights": {"safety": 1, "latency_serialization": 10}}
        result = {"winner": "monolith"}
        check = preflight.check_s1_005(matrix, rubric, result)
        self.assertFalse(check["passed"])
        self.assertEqual(check["counterfactual_winner"], "containers")

    def test_s1_007_requires_neutral_timing_and_equal_d1(self):
        timing = {"variants": {
            "per_scope": {"verdict": "WITHIN_TOLERANCE"},
            "shared_rls": {"verdict": "WITHIN_TOLERANCE"},
        }}
        decision = {"winner": "per_scope", "scores_per_dimension": {
            "D1": {"per_scope": 4.0, "shared_rls": 4.0}}}
        self.assertTrue(preflight.check_s1_007(timing, decision)["passed"])
        timing["variants"]["shared_rls"]["verdict"] = "SIGNAL_ABOVE_TOLERANCE"
        self.assertFalse(preflight.check_s1_007(timing, decision)["passed"])

    def test_s1_016_is_admissible_only_as_inconclusive(self):
        record = {"result": "pass_with_limits", "limitations": [
            "sensitivity parsimony consumes wall-clock latencies"]}
        candidate = {"design_decision": "INCONCLUSIVE", "sensitivity_flips": 1}
        sensitivity = {"flips": 1, "stable": False}
        self.assertTrue(
            preflight.check_s1_016(record, candidate, sensitivity)["passed"])
        candidate["design_decision"] = "FLAT_RUNTIME_PROV_EXPORT"
        self.assertFalse(
            preflight.check_s1_016(record, candidate, sensitivity)["passed"])

    def test_missing_dependencies_block_synthesis(self):
        tree = MemoryTree({
            "research/tickets/stage-1/S1-004/runner.py": "print('ok')\n"
        })
        report = preflight.audit(tree)
        self.assertEqual(report["status"], "BLOCKED_DEPENDENCY")
        self.assertIn("S1-017", report["missing_tickets"])
        self.assertIn("S1-018", report["missing_tickets"])

    def test_unregistered_clock_source_fails_closed(self):
        files = {}
        for number in range(4, 19):
            ticket = f"S1-{number:03d}"
            files[f"research/tickets/stage-1/{ticket}/runner.py"] = "pass\n"
        files["research/tickets/stage-1/S1-009/evaluator.py"] = (
            "import time\nscore = time.perf_counter_ns()\n"
        )
        report = preflight.audit(MemoryTree(files), semantic_checks=False)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(
            item["ticket"] == "S1-009" for item in report["violations"]
        ))

    def test_synthesis_import_policy_is_fail_closed(self):
        policy = preflight.synthesis_import_policy()
        self.assertEqual(policy["S1-008"]["wall_clock"], "native_slo_only")
        self.assertEqual(policy["S1-016"]["architecture_decision"], "deny")
        self.assertEqual(policy["S1-017"]["wall_clock"], "deny")
        self.assertEqual(policy["S1-018"]["wall_clock"], "deny")

    def test_latency_free_scoring_source_is_required(self):
        prefix = "research/tickets/stage-1/S1-017"
        good = MemoryTree({
            f"{prefix}/sensitivity.py": (
                "DIMS = ('utility', 'bytes_parsimony')\n"
                "def measured_scores(run, ticket):\n    return {'utility': 1}\n"
            ),
            f"{prefix}/make_bundle.py": (
                "def _semantic_metrics(metrics):\n"
                "    return {k: v for k, v in metrics.items() "
                "if k not in ('latencies', 'executor')}\n"
            ),
        })
        self.assertTrue(preflight.check_latency_excluded(good, "S1-017")["passed"])
        good.files[f"{prefix}/sensitivity.py"] = (
            "import time\nDIMS = ('utility', 'latency')\n"
            "def measured_scores(run, ticket):\n"
            "    return {'utility': time.perf_counter_ns()}\n"
        )
        self.assertFalse(preflight.check_latency_excluded(good, "S1-017")["passed"])


if __name__ == "__main__":
    unittest.main()
