"""Publication refuses fabricated/stale canonical bindings."""
import importlib.util
import unittest
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "research/tickets/stage-1/S1-011/finalize_record.py"


class CanonicalPublication(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("s1011_finalize", P)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_valid_binding(self):
        self.mod.verify_binding(
            {"goal_id": "g", "campaign_id": "c"},
            {"id": "e", "goal_id": "g", "result": "pass_with_limits", "artifact_chain_hash": "a" * 64},
            {"goal": {"id": "g"}, "research": {"campaign": {"id": "c"},
             "chain_fresh": True, "latest_evaluation_valid": True,
             "current_chain_hash": "a" * 64, "latest_chain_hash": "a" * 64,
             "evaluations": [{"id": "e", "artifact_chain_hash": "a" * 64,
                               "result": "pass_with_limits"}]}})

    def test_missing_pack_binding_refused(self):
        with self.assertRaises(ValueError):
            self.mod.verify_binding({"goal_id": "g", "campaign_id": "c"},
                                    {"result": "pass_with_limits"}, {})

    def test_failed_evaluation_refused(self):
        with self.assertRaises(ValueError):
            self.mod.verify_binding({}, {"result": "fail"}, {})
