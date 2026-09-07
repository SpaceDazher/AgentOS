"""Regression tests for the S1-020 independent closure audit."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TICKET = ROOT / "research" / "tickets" / "stage-1" / "S1-020"
BASE_COMMIT = "78a4218606212c4f65642fe8dbf9c6a808209cfb"


def load_module(name: str):
    path = TICKET / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"s1020_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class S1020ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = load_module("dependency_gate")
        cls.evaluator = load_module("evaluator")
        cls.comparator = load_module("comparator")

    def test_01_strict_json_rejects_duplicate_and_nonfinite(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.assertRaises(self.gate.StrictJsonError):
                self.gate.load_strict_json(raw)

    def test_02_paths_fail_closed(self):
        for path in ("../escape", "/absolute", "C:/escape", "a\\b", ".git/config"):
            with self.assertRaises(self.gate.PathSafetyError):
                self.gate.validate_repo_relative_path(path)

    def test_03_contract_accounts_for_exact_ticket_sets(self):
        contract = json.loads((TICKET / "closure-contract.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["active_ticket_ids"], [f"S1-{n:03d}" for n in range(1, 21)])
        self.assertEqual(contract["parked_ids"], [f"PARK-{n:02d}" for n in range(1, 5)])
        self.assertFalse(contract["research_pass_is_goal_accepted"])
        self.assertFalse(contract["reopen_parked_items"])

    def test_04_pinned_dependency_and_probe_gate(self):
        report = self.gate.run_gate(ROOT, BASE_COMMIT)
        self.assertEqual(report["status"], "PASS_WITH_LIMITS")
        self.assertTrue(report["dependencies_proven"])
        self.assertTrue(report["all_prior_probes_pass"])
        self.assertEqual(len(report["dependencies"]), 19)
        self.assertEqual(len(report["probe_results"]), 19)
        self.assertTrue(all(row["status"] == "PROVEN" for row in report["dependencies"]))
        self.assertTrue(all(row["passed"] for row in report["probe_results"]))

    def test_05_mutable_ref_is_rejected(self):
        with self.assertRaises(self.gate.GateInputError):
            self.gate.resolve_pinned_commit(ROOT, "HEAD")

    def test_06_common_gate_stale_chain_blocks(self):
        state = self.evaluator.baseline_state()
        state["chain_fresh"] = False
        decision = self.evaluator.closure_decision(state)
        self.assertEqual(decision["status"], "BLOCKED")
        self.assertIn("chain_fresh", decision["failed_gates"])

    def test_07_latest_evaluation_false_blocks(self):
        state = self.evaluator.baseline_state()
        state["latest_evaluation_valid"] = False
        self.assertEqual(self.evaluator.closure_decision(state)["status"], "BLOCKED")

    def test_08_equal_auditor_blocks(self):
        state = self.evaluator.baseline_state()
        state["auditor_id"] = state["producer_id"]
        self.assertEqual(self.evaluator.closure_decision(state)["status"], "BLOCKED")

    def test_09_missing_ticket_probe_blocks(self):
        state = self.evaluator.baseline_state()
        state["prior_probe_pass"]["S1-019"] = False
        self.assertEqual(self.evaluator.closure_decision(state)["status"], "BLOCKED")

    def test_10_missing_dependency_blocks(self):
        state = self.evaluator.baseline_state()
        state["dependency_status"].pop("S1-009")
        self.assertEqual(self.evaluator.closure_decision(state)["status"], "BLOCKED")

    def test_11_parked_items_cannot_be_reopened(self):
        state = self.evaluator.baseline_state()
        state["parked_status"]["PARK-03"] = "READY"
        self.assertEqual(self.evaluator.closure_decision(state)["status"], "BLOCKED")

    def test_12_production_and_acceptance_authority_denied(self):
        state = self.evaluator.baseline_state()
        state["production_authority"] = True
        state["goal_acceptance_authority"] = True
        decision = self.evaluator.closure_decision(state)
        self.assertEqual(decision["status"], "BLOCKED")
        self.assertIn("production_authority", decision["failed_gates"])
        self.assertIn("goal_acceptance_authority", decision["failed_gates"])

    def test_13_wall_clock_is_not_a_decision_input(self):
        state = self.evaluator.baseline_state()
        state["generated_at"] = "2099-01-01T00:00:00Z"
        first = self.evaluator.closure_decision(state)
        state["generated_at"] = "2000-01-01T00:00:00Z"
        second = self.evaluator.closure_decision(state)
        self.assertEqual(first, second)

    def test_14_coverage_has_every_open_item_and_ticket(self):
        matrix = json.loads((TICKET / "coverage-matrix.json").read_text(encoding="utf-8"))
        self.assertEqual({r["ticket_id"] for r in matrix["ticket_rows"]},
                         {f"S1-{n:03d}" for n in range(1, 21)})
        self.assertEqual({r["parked_id"] for r in matrix["parked_rows"]},
                         {f"PARK-{n:02d}" for n in range(1, 5)})
        self.assertTrue(matrix["open_item_rows"])
        self.assertTrue(all(row["ticket_mappings"] for row in matrix["open_item_rows"]))

    def test_15_corpus_is_balanced_and_oracle_separate(self):
        cases = json.loads((TICKET / "cases.json").read_text(encoding="utf-8"))["cases"]
        oracle = json.loads((TICKET / "oracle.json").read_text(encoding="utf-8"))["expected"]
        counts = {kind: sum(c["class"] == kind for c in cases)
                  for kind in ("gold", "near_miss", "adversarial")}
        self.assertEqual(counts, {"gold": 20, "near_miss": 20, "adversarial": 20})
        self.assertEqual(set(oracle), {c["case_id"] for c in cases})
        self.assertTrue(all("expected" not in case for case in cases))

    def test_16_evaluator_matches_host_owned_oracle(self):
        run = self.evaluator.evaluate("test-auditor", "nonce-a", BASE_COMMIT)
        self.assertEqual(run["verdict"], "PASS_WITH_LIMITS")
        self.assertEqual(run["matched"], 60)
        self.assertEqual(run["mismatches"], [])
        self.assertTrue(all(value == 0 for value in run["hard_counters"].values()))

    def test_17_comparator_recomputes_and_rejects_tamper(self):
        run_a = self.evaluator.evaluate("auditor-A", "nonce-a", BASE_COMMIT)
        run_b = self.evaluator.evaluate("auditor-B", "nonce-b", BASE_COMMIT)
        good = self.comparator.compare(run_a, run_b)
        self.assertEqual(good["verdict"], "PASS_WITH_LIMITS")
        poisoned = copy.deepcopy(run_b)
        poisoned["observations"][0]["observed_status"] = "BLOCKED"
        bad = self.comparator.compare(run_a, poisoned)
        self.assertEqual(bad["verdict"], "FAIL")

    def test_18_tracked_runner_outputs_are_bound_to_clean_commit(self):
        comparison = json.loads((TICKET / "results" / "comparison.json").read_text(encoding="utf-8"))
        self.assertEqual(comparison["verdict"], "PASS_WITH_LIMITS")
        self.assertTrue(comparison["process_separation_verified"])
        self.assertEqual(comparison["verified_commit"], BASE_COMMIT)

    def test_19_s1_006_and_s1_007_probe_verdicts_fail_closed(self):
        for ticket in ("S1-006", "S1-007"):
            doc = json.loads((ROOT / "research" / "tickets" / "stage-1" / ticket /
                              "results" / "sensitivity-analysis.json").read_text(encoding="utf-8"))
            self.assertTrue(self.gate.probe_pass(ticket, doc))
            tampered = copy.deepcopy(doc)
            key = next(iter(tampered["probe_rejections"]))
            if ticket == "S1-006":
                tampered["probe_rejections"][key] = "PASS"
            else:
                tampered["probe_rejections"][key]["detected"] = "PASS"
            self.assertFalse(self.gate.probe_pass(ticket, tampered))

    def test_20_canonical_record_binds_wiki_and_content_addresses(self):
        record = json.loads((TICKET / "evaluation-record.json").read_text(encoding="utf-8"))
        self.assertEqual(record["result"], "pass_with_limits")
        self.assertTrue(record["wiki_check_ok"])
        self.assertTrue(record["wiki_check"]["ok"])
        self.assertEqual(record["wiki_check"]["issues"], [])
        for key in ("evidence_pack", "ticket_pack", "raw_archive"):
            binding = record[key]
            raw = (ROOT / binding["path"]).read_bytes()
            self.assertEqual(__import__("hashlib").sha256(raw).hexdigest(), binding["sha256"])
            self.assertIn(binding["sha256"], Path(binding["path"]).name)


if __name__ == "__main__":
    unittest.main()
