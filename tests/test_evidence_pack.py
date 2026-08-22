"""Evidence pack: acceptance flag flips at the gate; audit chain; schema keys;
on-disk sha256 integrity."""
import json
import unittest
from pathlib import Path

from tests.base import AgentOSTestCase
from agentos.evidence_pack import build as build_evidence
from agentos.gates import Gates
from agentos.ids import canonical_json, sha256_text

REQUIRED_KEYS = [
    "schema", "goal", "tasks", "runs", "evaluations", "gates",
    "artifact_versions", "tool_activities", "approvals", "acceptance_criteria",
]


class TestEvidencePack(AgentOSTestCase):
    def _happy_to_gate_pending(self) -> str:
        """Full happy flow up to (but not including) gate release."""
        goal_id = self.make_goal_with_task()
        self.run_simple_task(goal_id)
        ev = self.ev.run(goal_id, "has_code")
        self.assertEqual(ev["result"], "pass")
        self.eng.submit_to_gate(goal_id)
        return goal_id

    def test_accepted_false_before_gate_true_after(self):
        goal_id = self._happy_to_gate_pending()
        before = build_evidence(self.db, self.root, goal_id)["pack"]
        self.assertFalse(before["accepted"])

        gate = Gates(self.db, self.j).evaluate_release(goal_id)
        self.assertEqual(gate["result"], "pass")

        after = build_evidence(self.db, self.root, goal_id)["pack"]
        self.assertTrue(after["accepted"])

    def test_audit_chain_verified_and_event_count_positive(self):
        goal_id = self._happy_to_gate_pending()
        Gates(self.db, self.j).evaluate_release(goal_id)
        audit = build_evidence(self.db, self.root, goal_id)["pack"]["audit"]
        self.assertTrue(audit["chain_verified"])
        self.assertGreater(audit["event_count"], 0)

    def test_pack_contains_required_sections(self):
        goal_id = self._happy_to_gate_pending()
        Gates(self.db, self.j).evaluate_release(goal_id)
        pack = build_evidence(self.db, self.root, goal_id)["pack"]
        for key in REQUIRED_KEYS:
            self.assertIn(key, pack)
        self.assertEqual(pack["schema"], "agentos.evidence-pack/v1")
        self.assertTrue(pack["acceptance_criteria"])

    def test_file_on_disk_and_sha256_matches_content(self):
        goal_id = self._happy_to_gate_pending()
        Gates(self.db, self.j).evaluate_release(goal_id)
        res = build_evidence(self.db, self.root, goal_id)

        path = Path(res["path"])
        self.assertTrue(path.exists())

        loaded = json.loads(path.read_text(encoding="utf-8"))
        stored = loaded.pop("sha256")
        recomputed = sha256_text(canonical_json(loaded))
        self.assertEqual(stored, recomputed)
        self.assertEqual(res["sha256"], stored)


if __name__ == "__main__":
    unittest.main()
