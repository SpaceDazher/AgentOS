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


class TestAsciiTransport(unittest.TestCase):
    """The dsh boot pipeline corrupts non-ASCII argv (measured: cp1251
    mojibake), so the wire prompt must be ASCII; violations fail loudly."""

    def test_template_is_ascii_single_line(self):
        from agentos.dsh_worker import PROMPT_TEMPLATE_ASCII
        PROMPT_TEMPLATE_ASCII.encode("ascii")
        self.assertNotIn("\n", PROMPT_TEMPLATE_ASCII)

    def test_non_ascii_title_fails_loudly(self):
        from agentos.workers import StepRequest
        w = DshAgentWorker.__new__(DshAgentWorker)
        w.bin = "dsh.cmd"
        w.profile = "headless"
        w.timeout_s = 1
        res = w.step(StepRequest(
            task_id="t", run_id="r", goal_id="g", title="реализуй задачу",
            definition_of_done="d", inputs={}, workspace_path=".",
            step=0, checkpoint=None, context_packet_text=""))
        self.assertFalse(res.ok)
        self.assertIn("ASCII", res.note)

    def test_ascii_prompt_passes_guard(self):
        from agentos.workers import StepRequest
        w = DshAgentWorker.__new__(DshAgentWorker)
        w.bin = "definitely-not-a-real-binary-xyz"
        w.profile = "headless"
        w.timeout_s = 1
        res = w.step(StepRequest(
            task_id="t", run_id="r", goal_id="g", title="add task",
            definition_of_done="d", inputs={}, workspace_path=".",
            step=0, checkpoint=None, context_packet_text=""))
        # guard passed -> launch attempted -> typed launch failure
        self.assertFalse(res.ok)
        self.assertEqual(res.fail_class, "worker_unavailable")


if __name__ == "__main__":
    unittest.main()
