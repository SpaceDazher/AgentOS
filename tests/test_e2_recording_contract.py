"""E2 recording-contract regression (ROADMAP item 4 / protocol §Recording).

Drills `run_episode` with a deterministic FakeWorker (no LLM, no network) and
asserts that EVERY episode — success and failure alike — records:
  - evidence pack path + sha256 (pack built, file exists, digest matches);
  - env identity block (python/platform/harness_version);
  - true run terminal state + reason;
  - worker fail class on failure.
This pins the E2-v2 recording contract so future runner edits cannot silently
drop it.
"""
import json
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "eval"))

from e1_tasks import E1_TASKS  # noqa: E402
from run_e1_hermes import run_episode  # noqa: E402

from agentos.workers import FakeWorker  # noqa: E402

GREET = next(t for t in E1_TASKS if t["key"] == "greet-basic")

GREET_SRC = (
    "def greet(name):\n"
    "    return f'hello, {name}'\n"
)

TEST_SRC = (
    "from greet import greet\n"
    "\n\n"
    "def test_greet():\n"
    "    assert greet('world') == 'hello, world'\n"
)


class TestRecordingContract(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = Path(tempfile.mkdtemp(prefix="agentos-e2-contract-"))

    def _pack_file(self, rec: dict) -> Path:
        p = Path(rec["evidence_pack_path"])
        return p if p.is_absolute() else (Path.cwd() / p)

    def test_success_episode_records_pack_env_state(self):
        fw = FakeWorker([{"ok": True,
                          "outputs": {"files": {"greet.py": GREET_SRC,
                                                "test_greet.py": TEST_SRC}}}])
        rec = run_episode(self.root, GREET, 1, timeout_s=1, worker=fw)
        self.assertEqual(rec["worker"], "fake")
        self.assertTrue(rec["episode_success"], rec)
        self.assertEqual(rec["gate_result"], "pass")
        self.assertEqual(rec["run_status"], "COMPLETED")
        # pack recorded + real + digest matches
        self.assertTrue(rec["evidence_pack_path"], rec)
        self.assertTrue(rec["evidence_pack_sha256"], rec)
        pack_file = self._pack_file(rec)
        self.assertTrue(pack_file.exists(), pack_file)
        # the recorded sha256 is the canonical-pack digest: file bytes embed
        # {"sha256": ...} + pack; verifier recomputes by popping the field
        raw = json.loads(pack_file.read_text(encoding="utf-8"))
        embedded = raw.pop("sha256")
        from agentos.ids import canonical_json, sha256_text
        self.assertEqual(rec["evidence_pack_sha256"], embedded)
        self.assertEqual(rec["evidence_pack_sha256"],
                         sha256_text(canonical_json(raw)))
        self.assertEqual(raw["goal"]["id"], rec["goal_id"])
        # env identity present
        env = rec["env"]
        for k in ("python", "platform", "harness_version"):
            self.assertTrue(env.get(k), (k, env))
        self.assertIsNone(env["hermes_bin_name"])

    def test_failed_episode_records_pack_failclass_terminal(self):
        fw = FakeWorker([{"ok": False, "fail_class": "worker"}])
        rec = run_episode(self.root, GREET, 1, timeout_s=1, worker=fw)
        self.assertFalse(rec["episode_success"])
        self.assertEqual(rec["worker_fail_class"], "worker")
        self.assertEqual(rec["run_status"], "FAILED")
        self.assertTrue(rec["run_terminal_reason"], rec)
        # the pack is STILL built and digest-recorded on failure
        self.assertTrue(rec["evidence_pack_path"], rec)
        self.assertTrue(rec["evidence_pack_sha256"], rec)
        self.assertTrue(self._pack_file(rec).exists())
        self.assertEqual(rec["gate_result"], "submit-refused")


if __name__ == "__main__":
    unittest.main()
