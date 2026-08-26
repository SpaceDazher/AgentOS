"""Tests for the DshAgentWorker adapter (no `dsh` binary required).

Covers what CAN be tested offline: shared effects-channel parsing with path
confinement, availability resolution, and unavailable-construction typing.
"""
import unittest

from agentos.dsh_worker import DshAgentWorker, resolve_dsh_bin
from agentos.hermes_worker import WorkerUnavailable


class TestParseEffectsShared(unittest.TestCase):
    """The parser is inherited verbatim from HermesAgentWorker and must keep
    its workspace-confinement guarantees."""

    def setUp(self):
        self.ws = __import__("tempfile").mkdtemp(prefix="agentos-dsh-ws-")
        self.parse = staticmethod(DshAgentWorker.parse_effects).__func__

    def test_valid_block_parsed(self):
        text = ("AGENTOS_EFFECTS_BEGIN greet.py\n"
                "def greet():\n    return 'hi'\n"
                "AGENTOS_EFFECTS_END greet.py\n"
                "AGENTOS_RESULT {\"ok\": true}")
        declared = self.parse(text, self.ws)
        self.assertEqual(declared,
                         {"greet.py": "def greet():\n    return 'hi'"})

    def test_traversal_path_rejected(self):
        text = ("AGENTOS_EFFECTS_BEGIN ../evil.py\n"
                "x = 1\n"
                "AGENTOS_EFFECTS_END ../evil.py\n")
        self.assertEqual(self.parse(text, self.ws), {})

    def test_absolute_and_drive_paths_rejected(self):
        for bad in ("/abs/evil.py", "C:/abs/evil.py", "D:\\evil.py"):
            text = (f"AGENTOS_EFFECTS_BEGIN {bad}\n"
                    "x = 1\n"
                    f"AGENTOS_EFFECTS_END {bad}\n")
            self.assertEqual(self.parse(text, self.ws), {}, bad)

    def test_unclosed_block_ignored(self):
        text = ("AGENTOS_EFFECTS_BEGIN ok.py\n"
                "x = 1\n")
        self.assertEqual(self.parse(text, self.ws), {})


class TestAvailability(unittest.TestCase):
    def test_resolve_returns_none_or_str(self):
        resolved = resolve_dsh_bin()
        self.assertTrue(resolved is None or isinstance(resolved, str))

    def test_missing_bin_raises_typed_error(self):
        if resolve_dsh_bin():
            self.skipTest("dsh present on PATH; typed-error path not exerciseable")
        with self.assertRaises(WorkerUnavailable):
            DshAgentWorker()


if __name__ == "__main__":
    unittest.main()
