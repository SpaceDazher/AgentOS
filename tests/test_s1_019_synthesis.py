"""Focused checks for the bounded S1-019 technical synthesis."""
import importlib.util
import hashlib
import json
from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parents[1]
TICKET = REPO / "research/tickets/stage-1/S1-019"


def module(name):
    path = TICKET / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"s1019_{name}", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


evaluator = module("evaluator")
comparator = module("comparator")
sensitivity = module("sensitivity")


class SynthesisInputTests(unittest.TestCase):
    def load(self, rel):
        return json.loads((TICKET / rel).read_text("utf-8"))

    def test_source_freeze_has_all_ten_aliases_and_valid_hashes(self):
        sources = self.load("source-registry.json")["sources"]
        self.assertEqual([item["alias"] for item in sources],
                         [f"SRC-{n:02d}" for n in range(10)])
        for source in sources:
            path = REPO / source["canonical_path"]
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                             source["sha256"])

    def test_corpus_is_exact_and_oracle_is_separate(self):
        cases_doc = self.load("cases.json")
        cases = cases_doc["cases"]
        oracle_doc = self.load("oracle.json")
        self.assertEqual(len(cases), 72)
        self.assertEqual(len({item["case_id"] for item in cases}), 72)
        self.assertEqual({item["class"] for item in cases},
                         {"happy", "near_miss", "adversarial"})
        self.assertTrue(all("decision" not in item for item in cases))
        manifest = self.load("corpus-manifest.json")
        self.assertEqual(evaluator.sha(evaluator.canonical(cases_doc)),
                         manifest["cases_sha256"])
        self.assertEqual(evaluator.sha(evaluator.canonical(oracle_doc)),
                         manifest["oracle_sha256"])

    def test_each_ep_and_clock_rule_has_positive_and_negative_coverage(self):
        cases = self.load("cases.json")["cases"]
        eps = {"EP-01", "EP-02", "EP-03", "EP-04", "EP-05", "EP-08"}
        for ep in eps:
            self.assertGreaterEqual(sum(item["ep_id"] == ep for item in cases), 8)
        for rule in ("S1-005", "S1-007", "S1-008", "S1-016", "S1-017", "S1-018"):
            controls = {item["wall_clock_control"] for item in cases
                        if item["wall_clock_rule"] == rule}
            self.assertEqual(controls, {True, False})

    def test_decision_rows_are_bounded_and_evidence_backed(self):
        rows = self.load("decision-matrix.json")["rows"]
        self.assertEqual(len(rows), 6)
        for row in rows:
            self.assertEqual(row["disposition"], "ADOPT_WITH_LIMITS")
            self.assertTrue(row["direct_evidence_refs"])
            self.assertTrue(row["audit_evidence_refs"])
            self.assertFalse(row["production_authority"])
            self.assertFalse(row["goal_acceptance_authority"])

    def test_reverse_traceability_covers_all_18_tickets(self):
        rows = self.load("reverse-traceability.json")["rows"]
        self.assertEqual({item["ticket_id"] for item in rows},
                         {f"S1-{n:03d}" for n in range(1, 19)})
        self.assertTrue(all(item["ep_decisions"] for item in rows))

    def test_contract_has_exact_syn_counter_set(self):
        counters = self.load("synthesis-contract.json")["hard_invariants"]
        self.assertEqual(set(counters), {f"SYN{n}" for n in range(1, 19)})

    def test_main_evaluator_rejects_adversarial_case_safely(self):
        case = next(item for item in self.load("cases.json")["cases"]
                    if item["class"] == "adversarial")
        result = evaluator.evaluate_case(case)
        self.assertEqual(result["decision"], "DEFER")
        self.assertTrue(result["probe_detected"])
        self.assertEqual(result["authority_mutations"], [])

    def test_comparator_recomputes_violation_instead_of_trusting_counter(self):
        observation = {
            "class": "adversarial", "decision": "ADOPT_WITH_LIMITS",
            "ep_id": "EP-01", "production_authority": False,
            "goal_acceptance_authority": False, "authority_mutations": [],
        }
        counters = comparator.recompute_counters([observation])
        self.assertEqual(counters["SYN4"], 1)

    def test_sensitivity_is_timing_free_and_large_enough(self):
        first = sensitivity.run()
        second = sensitivity.run()
        self.assertEqual(first, second)
        self.assertEqual(first["joint_seeded_trials"], 256)
        self.assertGreaterEqual(first["total_trials"], 264)
        self.assertEqual(first["wall_clock_inputs"], [])
        self.assertEqual(first["winner_flips"], 0)

    def test_operator_answers_are_not_fabricated(self):
        self.assertTrue((TICKET / "operator-questionnaire.md").is_file())
        self.assertFalse((TICKET / "operator-decision.json").exists())

    def test_unsafe_evidence_path_is_rejected(self):
        for path in ("../x", "/x", "C:/x", "x\\y"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                evaluator.safe_repo_path(path)


if __name__ == "__main__":
    unittest.main()
