"""S1-013 operator-authorized solo closure contract."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TICKET = ROOT / "research" / "tickets" / "stage-1" / "S1-013"


def load_module(name: str):
    path = TICKET / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"s1013_solo_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load(name: str):
    return json.loads((TICKET / name).read_text(encoding="utf-8"))


class TestOperatorDecision(unittest.TestCase):
    def test_exact_answers_and_scope_change_are_verified(self):
        verifier = load_module("solo_closure")
        decision = load("operator-decision.json")
        result = verifier.verify_operator_decision(TICKET, decision)
        self.assertEqual(result["operator_id"], "OP-OWNER-01")
        self.assertEqual(result["selected_answers"], {
            "1": "A", "2": "A", "3": "B", "4": "A",
            "5": "A", "6": "A", "7": "C", "8": "B",
            "9": "A", "10": "A", "11": "C", "12": "A",
        })
        self.assertEqual(result["scope"], "solo_expert_review")
        self.assertEqual(result["full_human_pilot"], "cancelled_by_operator")
        self.assertEqual(result["target_status"], "PASS_WITH_LIMITS")

    def test_approved_artifact_hashes_match_disk(self):
        decision = load("operator-decision.json")
        for rel, expected in decision["approved_artifact_hashes"].items():
            actual = hashlib.sha256((TICKET / rel).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, rel)

    def test_decision_tampering_fails_closed(self):
        verifier = load_module("solo_closure")
        original = load("operator-decision.json")
        mutations = []
        for key, value in (("11", "A"), ("12", "B"), ("7", "A")):
            item = copy.deepcopy(original)
            item["selected_answers"][key] = value
            mutations.append(item)
        item = copy.deepcopy(original)
        item["approved_artifact_hashes"]["rubric.json"] = "0" * 64
        mutations.append(item)
        for mutated in mutations:
            with self.subTest(mutated=mutated["selected_answers"]):
                with self.assertRaises(ValueError):
                    verifier.verify_operator_decision(TICKET, mutated)


class TestSoloReviewEvidence(unittest.TestCase):
    def test_review_covers_both_roles_without_human_claims(self):
        verifier = load_module("solo_closure")
        review = verifier.verify_solo_review(TICKET, load("results/solo-review.json"))
        self.assertEqual(review["reviewed_roles"], ["owner", "reviewer"])
        self.assertEqual(review["mode"], "accelerated")
        self.assertEqual(review["operator_id"], "OP-OWNER-01")
        self.assertEqual(review["human_n"], 0)
        self.assertFalse(review["independent_grading_performed"])
        self.assertFalse(review["raw_retained"])
        self.assertEqual(review["result"], "PASS_WITH_LIMITS")
        self.assertEqual(review["human_effectiveness"], "NOT_MEASURED")

    def test_review_has_real_browser_importer_and_evaluator_evidence(self):
        review = load("results/solo-review.json")
        self.assertEqual(len(review["executions"]), 2)
        for execution in review["executions"]:
            self.assertTrue(execution["browser_version"])
            self.assertEqual(execution["import_status"], "ok")
            self.assertTrue(execution["evaluator_completed"])
            self.assertEqual(execution["approval_prompts"], 36)
            self.assertEqual(execution["stop_confirmed"], 1)
            self.assertRegex(execution["transient_envelope_sha256"], r"^[0-9a-f]{64}$")
        self.assertFalse((TICKET / "results" / "solo-raw").exists())

    def test_mutated_review_is_rejected(self):
        verifier = load_module("solo_closure")
        review = load("results/solo-review.json")
        for key, value in (("human_n", 1), ("raw_retained", True),
                           ("result", "PASS")):
            mutated = copy.deepcopy(review)
            mutated[key] = value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    verifier.verify_solo_review(TICKET, mutated)


class TestClosedCandidate(unittest.TestCase):
    def test_candidate_is_closed_with_explicit_limits(self):
        candidate = load("candidate-record.json")
        self.assertEqual(candidate["status"], "CLOSED_WITH_LIMITS")
        self.assertEqual(candidate["result"], "PASS_WITH_LIMITS")
        self.assertEqual(candidate["human_phase"], "CANCELLED_BY_OPERATOR")
        self.assertFalse(candidate["phase_b_required"])
        self.assertEqual(candidate["human_n"], 0)
        self.assertEqual(candidate["human_effectiveness"], "NOT_MEASURED")
        self.assertEqual(candidate["closure_basis"], "solo_expert_review")

    def test_bundle_and_ticket_docs_do_not_claim_a_human_pilot(self):
        bundle = load("bundle.json")
        serialized = json.dumps(bundle, ensure_ascii=False).lower()
        self.assertEqual(bundle["audit"]["verdict"], "pass_with_limits")
        self.assertIn("solo", serialized)
        self.assertIn("no human", serialized)
        docs = (ROOT / "docs" / "RESEARCH_STAGE_1_TICKETS.md").read_text(
            encoding="utf-8")
        start = docs.index("### S1-013")
        end = docs.index("### S1-014", start)
        section = docs[start:end]
        self.assertIn("**Status:** `PASS_WITH_LIMITS`", section)
        self.assertIn("solo expert", section.lower())
        self.assertIn("15-20-person pilot", section)
        self.assertIn("cancelled, not completed", section)

    def test_canonical_record_and_packs_are_content_addressed(self):
        record = load("evaluation-record.json")
        self.assertEqual(record["schema"], "agentos.ticket-evaluation-record/v2")
        self.assertEqual(record["ticket_id"], "S1-013")
        self.assertEqual(record["result"], "pass_with_limits")
        self.assertEqual(record["research_revision"], 1)
        for key in ("evidence_pack", "ticket_pack"):
            entry = record[key]
            path = ROOT / entry["path"]
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(actual, entry["sha256"])
            self.assertIn(actual, path.name)
        self.assertEqual({item["ticket_id"] for item in
                          record["canonical_dependencies"]},
                         {"S1-011", "S1-012"})

    def test_canonical_output_does_not_invalidate_frozen_inputs(self):
        publisher = load_module("make_bundle")
        problems, _ = publisher.verify_frozen_manifest(TICKET)
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
