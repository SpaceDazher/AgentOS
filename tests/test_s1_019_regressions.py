"""Regression tests for the S1-019 immutable dependency gate."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "research/tickets/stage-1/S1-019/dependency_gate.py"
spec = importlib.util.spec_from_file_location("s1019_dependency_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class DependencyGateTests(unittest.TestCase):
    def test_strict_json(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'[]', b'\xff'):
            with self.subTest(raw=raw), self.assertRaises(gate.StrictJsonError):
                gate.load_strict_json(raw)

    def test_unsafe_paths(self):
        for path in ("../record", "x/../record", "/record", "C:/record",
                     "x\\record", "x//record", "x/./record"):
            with self.subTest(path=path), self.assertRaises(gate.PathSafetyError):
                gate.validate_repo_relative_path(path)

    def test_mutable_ref_rejected(self):
        with self.assertRaises(gate.GateInputError):
            gate.resolve_pinned_commit(REPO, "HEAD")

    def test_symlink_rejected(self):
        entry = b"120000 blob " + b"a" * 40 + b"\trecord.json\x00"
        with patch.object(gate, "_git", return_value=entry):
            with self.assertRaises(gate.GateInputError):
                gate.read_regular_blob(REPO, gate.PINNED_COMMIT, "record.json")

    def test_legacy_payload_tampering_is_rejected(self):
        record = {
            "ticket_id": "S1-001", "result": "pass_with_limits",
            "research_revision": 1, "goal_id": "g", "campaign_id": "c",
            "evaluation_id": "e", "artifact_chain_hash": "a" * 64,
            "limitations": ["limit"],
            "evidence_pack": {"path": "research/tickets/stage-1/S1-001/p.json",
                              "sha256": "b" * 64, "payload_sha256": "c" * 64},
        }
        with patch.object(gate, "read_regular_blob", return_value=b'{"schema":"x"}'):
            result = gate._verify_legacy(REPO, gate.PINNED_COMMIT, "S1-001", record)
        self.assertEqual(result["status"], "NOT_PROVEN")
        self.assertTrue(any("sha" in issue for issue in result["problems"]))

    def test_actual_origin_main_proves_all_dependencies(self):
        report = gate.run_gate(REPO, gate.PINNED_COMMIT)
        self.assertEqual(len(report["dependencies"]), 18)
        failures = {row["ticket"]: row["problems"] for row in report["dependencies"]
                    if row["status"] != "PROVEN"}
        self.assertEqual(failures, {})
        self.assertTrue(report["dependencies_proven"])
        self.assertTrue(report["synthesis_authorized"])
        self.assertEqual(report["status"], "PASS_WITH_LIMITS")


if __name__ == "__main__":
    unittest.main()
