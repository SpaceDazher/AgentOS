"""anchor-mirror regressions: idempotent off-host mirroring (ROADMAP item 3)."""
import hashlib
import json
import unittest
from pathlib import Path

from agentos.anchor import AnchorExportError, mirror_anchor
from agentos.journal import Journal

from tests.base import AgentOSTestCase


class AnchorMirrorTest(AgentOSTestCase):
    def setUp(self):
        super().setUp()
        self.dest = self.root / "offhost-mirror"

    def _produce_events(self, goals: int = 2) -> None:
        for _ in range(goals):
            self.make_goal_with_task()

    def test_first_run_creates_bundle_latest_history(self):
        self._produce_events()
        res = mirror_anchor(self.db, self.dest, now_iso="2026-01-01T00:00:00Z")
        self.assertTrue(res["changed"])
        bundle = self.dest / res["anchor_file"]
        self.assertTrue(bundle.exists())
        self.assertEqual(
            res["bundle_sha256"],
            hashlib.sha256(bundle.read_bytes()).hexdigest())
        latest = json.loads((self.dest / "latest.json").read_text("utf-8"))
        self.assertEqual(latest["anchor_file"], res["anchor_file"])
        self.assertEqual(latest["bundle_sha256"], res["bundle_sha256"])
        history = (self.dest / "history.ndjson").read_text("utf-8").splitlines()
        self.assertEqual(len(history), 1)
        rec = json.loads(history[0])
        self.assertEqual(rec["last_seq"], res["last_seq"])

    def test_second_run_unchanged_no_new_history(self):
        self._produce_events()
        mirror_anchor(self.db, self.dest, now_iso="2026-01-01T00:00:00Z")
        res2 = mirror_anchor(self.db, self.dest, now_iso="2026-01-02T00:00:00Z")
        self.assertFalse(res2["changed"])
        history = (self.dest / "history.ndjson").read_text("utf-8").splitlines()
        self.assertEqual(len(history), 1)
        # the immutable entry was NOT replaced despite a later export time
        bundle = self.dest / res2["anchor_file"]
        self.assertEqual(
            res2["bundle_sha256"],
            hashlib.sha256(bundle.read_bytes()).hexdigest())

    def test_new_state_appends_history_and_updates_latest(self):
        self._produce_events()
        r1 = mirror_anchor(self.db, self.dest, now_iso="2026-01-01T00:00:00Z")
        self._produce_events()
        r2 = mirror_anchor(self.db, self.dest, now_iso="2026-01-02T00:00:00Z")
        self.assertTrue(r2["changed"])
        self.assertNotEqual(r1["anchor_file"], r2["anchor_file"])
        self.assertGreater(r2["last_seq"], r1["last_seq"])
        latest = json.loads((self.dest / "latest.json").read_text("utf-8"))
        self.assertEqual(latest["anchor_file"], r2["anchor_file"])
        history = (self.dest / "history.ndjson").read_text("utf-8").splitlines()
        self.assertEqual(len(history), 2)

    def test_broken_chain_refuses_and_touches_nothing(self):
        self._produce_events()
        self.db.conn.execute(
            "UPDATE audit_event SET payload_json='{\"evil\":true}'"
            " WHERE seq=(SELECT MAX(seq) FROM audit_event)")
        ok, bad = Journal(self.db).full_chain_check()
        self.assertFalse(ok)
        with self.assertRaises(AnchorExportError):
            mirror_anchor(self.db, self.dest)
        self.assertFalse(self.dest.exists() and
                         any(self.dest.iterdir()))

    def test_conflicting_same_name_entry_refused(self):
        self._produce_events()
        mirror_anchor(self.db, self.dest, now_iso="2026-01-01T00:00:00Z")
        target = self.dest / "anchors"
        name = sorted(p.name for p in target.glob("*.json"))[0]
        (target / name).write_text("{\"tampered\": true}", encoding="utf-8")
        with self.assertRaises(AnchorExportError):
            mirror_anchor(self.db, self.dest, now_iso="2026-01-03T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
