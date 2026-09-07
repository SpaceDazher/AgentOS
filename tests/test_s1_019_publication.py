"""Independent checks for the canonical S1-019 publication."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import unittest


REPO = Path(__file__).resolve().parents[1]
TICKET = REPO / "research/tickets/stage-1/S1-019"


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class S1019PublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = json.loads((TICKET / "evaluation-record.json").read_text("utf-8"))

    def load_bound_file(self, binding):
        path = REPO / binding["path"]
        raw = path.read_bytes()
        self.assertEqual(digest(raw), binding["sha256"])
        self.assertEqual(path.stem.rsplit("-", 1)[-1], binding["sha256"])
        return json.loads(raw)

    def test_canonical_identity_and_limited_verdict(self):
        record = self.record
        self.assertEqual(record["schema"], "agentos.ticket-evaluation-record/v2")
        self.assertEqual(record["ticket_id"], "S1-019")
        self.assertEqual(record["research_revision"], 2)
        self.assertEqual(record["result"], "pass_with_limits")
        self.assertRegex(record["goal_id"], r"^goal_")
        self.assertRegex(record["campaign_id"], r"^rcamp_")
        self.assertRegex(record["evaluation_id"], r"^reval_")
        self.assertRegex(record["artifact_chain_hash"], r"^[0-9a-f]{64}$")
        self.assertFalse(record["production_authority"])
        self.assertFalse(record["goal_acceptance_authority"])

    def test_canonical_evidence_pack_is_fresh_and_self_hashed(self):
        pack = self.load_bound_file(self.record["evidence_pack"])
        payload = {key: value for key, value in pack.items() if key != "sha256"}
        self.assertEqual(pack["sha256"], digest(canonical(payload)))
        self.assertEqual(pack["goal"]["id"], self.record["goal_id"])
        research = pack["research"]
        self.assertEqual(research["campaign"]["id"], self.record["campaign_id"])
        self.assertTrue(research["chain_fresh"])
        self.assertTrue(research["latest_evaluation_valid"])
        self.assertEqual(research["current_chain_hash"],
                         self.record["artifact_chain_hash"])

    def test_ticket_pack_and_raw_archive_are_content_addressed(self):
        ticket = self.load_bound_file(self.record["ticket_pack"])
        raw = self.load_bound_file(self.record["raw_archive"])
        self.assertEqual(ticket["payload_sha256"], digest(canonical(ticket["payload"])))
        self.assertEqual(raw["payload_sha256"], digest(canonical(raw["payload"])))
        self.assertEqual(ticket["payload"]["ticket_id"], "S1-019")
        self.assertEqual(ticket["payload"]["series"]["goal_id"],
                         self.record["goal_id"])
        self.assertEqual(ticket["payload"]["evaluation"]["id"],
                         self.record["evaluation_id"])
        self.assertEqual(len(ticket["payload"]["canonical_dependencies"]), 18)
        self.assertEqual(len(raw["payload"]["run_a"]["observations"]), 72)
        self.assertEqual(len(raw["payload"]["run_b"]["observations"]), 72)

    def test_operator_decision_is_exact_bounded_and_non_authoritative(self):
        operator = json.loads((TICKET / "operator-decision.json").read_text("utf-8"))
        self.assertEqual(operator["answer_tokens"],
                         [f"{number}A" for number in range(1, 11)])
        self.assertEqual(operator["derived_status"], "PASS_WITH_LIMITS")
        self.assertTrue(operator["hard_gates_all_pass"])
        self.assertTrue(operator["operator_cannot_override_hard_gates"])
        self.assertFalse(operator["production_authority"])
        self.assertFalse(operator["goal_acceptance_authority"])
        self.assertEqual(digest((TICKET / "operator-decision.json").read_bytes()),
                         self.record["operator_decision_sha256"])

    def test_tracked_hashes_match_clean_git_archive(self):
        tracked = self.record["tracked_artifact_hashes"]
        required = {
            "tests/test_s1_019_publication.py",
            "research/tickets/stage-1/S1-019/S1-019_CLOSURE.md",
        }
        self.assertTrue(required.issubset(tracked))
        for rel, expected in tracked.items():
            raw = subprocess.run(
                ["git", "-C", str(REPO), "show", f"HEAD:{rel}"],
                capture_output=True, check=True).stdout
            self.assertEqual(digest(raw), expected, rel)
            self.assertEqual(raw, (REPO / rel).read_bytes(), rel)


if __name__ == "__main__":
    unittest.main()
