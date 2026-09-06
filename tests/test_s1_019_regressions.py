"""Availability checks, not a complete evidence-validation suite."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'research/tickets/stage-1/S1-019/dependency_gate.py'
spec = importlib.util.spec_from_file_location('s1019_dependency_availability', SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class DependencyAvailabilityTests(unittest.TestCase):
    def test_strict_json(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'[]', b'\xff'):
            with self.subTest(raw=raw), self.assertRaises(gate.StrictJsonError):
                gate.load_strict_json(raw)

    def test_unsafe_paths(self):
        for path in ('../record', 'x/../record', '/record', 'C:/record',
                     'x\\record', 'x//record', 'x/./record'):
            with self.subTest(path=path), self.assertRaises(gate.PathSafetyError):
                gate.validate_repo_relative_path(path)

    def test_mutable_ref_rejected(self):
        with self.assertRaises(gate.GateInputError):
            gate.resolve_pinned_commit(REPO, 'HEAD')

    def test_symlink_rejected(self):
        entry = b'120000 blob ' + b'a' * 40 + b'\trecord.json\x00'
        with patch.object(gate, '_git', return_value=entry):
            with self.assertRaises(gate.GateInputError):
                gate.read_regular_blob(REPO, gate.PINNED_COMMIT, 'record.json')

    def test_candidate_never_substitutes_for_missing_record(self):
        def blob(repo, commit, path):
            return None if path.endswith('evaluation-record.json') else b'{}'
        with patch.object(gate, 'resolve_pinned_commit', return_value=gate.PINNED_COMMIT), \
                patch.object(gate, 'read_regular_blob', side_effect=blob):
            report = gate.run_gate(REPO, gate.PINNED_COMMIT)
        self.assertEqual(report['status'], 'BLOCKED_DEPENDENCY')
        self.assertEqual(len(report['dependencies']), 18)
        self.assertIn('not a substitute', report['dependencies'][0]['problems'][0])

    def test_presence_does_not_authorize_synthesis(self):
        with patch.object(gate, 'resolve_pinned_commit', return_value=gate.PINNED_COMMIT), \
                patch.object(gate, 'read_regular_blob', return_value=b'{}'):
            report = gate.run_gate(REPO, gate.PINNED_COMMIT)
        self.assertEqual(report['status'], 'CANONICAL_VERIFICATION_REQUIRED')
        self.assertFalse(report['synthesis_authorized'])

    def test_pinned_main_lacks_s1014_record(self):
        report = gate.run_gate(REPO, gate.PINNED_COMMIT)
        row = next(r for r in report['dependencies'] if r['ticket'] == 'S1-014')
        self.assertEqual(row['status'], 'BLOCKED_DEPENDENCY')
        self.assertIn('candidate-record.json', row['problems'][0])
        self.assertFalse(report['synthesis_authorized'])


if __name__ == '__main__':
    unittest.main()
