"""Off-host anchor export/verify regressions (ROADMAP near-circle item 3)."""
import json
import unittest
from pathlib import Path

from agentos.anchor import AnchorExportError, export_anchor, load_bundle, verify_bundle
from agentos.journal import Journal

from tests.base import AgentOSTestCase


class AnchorBundleTest(AgentOSTestCase):
    """Shared: build a multi-event history through legitimate transitions."""

    def _produce_events(self, goals: int = 2) -> None:
        for _ in range(goals):
            self.make_goal_with_task()

    def _out(self) -> Path:
        return self.root / "offhost" / "anchor.json"


class TestAnchorExport(AnchorBundleTest):
    def test_export_writes_bundle_and_verify_ok(self):
        self._produce_events()
        bundle = export_anchor(self.db, self._out(), now_iso="2026-01-02T03:04:05Z")
        self.assertEqual(bundle["schema"], "agentos.anchor-export/v1")
        self.assertEqual(bundle["exported_at"], "2026-01-02T03:04:05Z")
        loaded = load_bundle(self._out())
        self.assertEqual(loaded["state"], bundle["state"])
        report = verify_bundle(self._out(), self.db)
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["struct_ok"])
        self.assertTrue(report["hist_ok"])
        self.assertTrue(report["chain_ok"])
        self.assertEqual(report["db_ahead_by"], 0)

    def test_bundle_contains_only_public_digests(self):
        self._produce_events()
        export_anchor(self.db, self._out())
        text = self._out().read_text(encoding="utf-8")
        # no goal ids, concept texts or payloads leak into the off-host file
        for goal_id_row in self.db.conn.execute("SELECT id FROM goal"):
            self.assertNotIn(goal_id_row["id"], text)
        self.assertNotIn("demo concept", text)

    def test_verify_still_binds_after_db_advances(self):
        """A DB that legitimately moved ahead must NOT invalidate an old
        export — historical binding is per-seq."""
        self._produce_events()
        old = self.root / "anchor-old.json"
        export_anchor(self.db, old)
        self._produce_events()   # advance the chain
        report = verify_bundle(old, self.db)
        self.assertTrue(report["ok"], report)
        self.assertGreater(report["db_ahead_by"], 0)

    def test_tamper_detected_by_hist_or_chain(self):
        self._produce_events()
        export_anchor(self.db, self._out())
        target = self.db.conn.execute(
            "SELECT MIN(seq) AS s FROM audit_event").fetchone()["s"]
        self.db.conn.execute(
            "UPDATE audit_event SET payload_json='{\"evil\":true}' WHERE seq=?",
            (target,))
        report = verify_bundle(self._out(), self.db)
        self.assertFalse(report["ok"], report)

    def test_export_refuses_to_run_on_broken_chain(self):
        self._produce_events()
        self.db.conn.execute(
            "UPDATE audit_event SET payload_json='{\"evil\":true}'"
            " WHERE seq=(SELECT MAX(seq) FROM audit_event)")
        ok, bad = Journal(self.db).full_chain_check()
        self.assertFalse(ok)
        refuse = self.root / "must-not-exist.json"
        with self.assertRaises(AnchorExportError):
            export_anchor(self.db, refuse)
        self.assertFalse(refuse.exists())

    def test_state_sha256_is_deterministic_regardless_of_time(self):
        self._produce_events()
        b1 = export_anchor(self.db, self.root / "a1.json",
                           now_iso="2026-01-01T00:00:00Z")
        b2 = export_anchor(self.db, self.root / "a2.json",
                           now_iso="2026-06-06T06:06:06Z")
        self.assertEqual(b1["state_sha256"], b2["state_sha256"])
        self.assertNotEqual(b1["exported_at"], b2["exported_at"])

    def test_bundle_tampering_breaks_struct_check(self):
        self._produce_events()
        out = self.root / "b.json"
        export_anchor(self.db, out)
        data = json.loads(out.read_text(encoding="utf-8"))
        data["state"]["last_seq"] += 100
        out.write_text(json.dumps(data), encoding="utf-8")
        report = verify_bundle(out, self.db)
        self.assertFalse(report["ok"])
        self.assertFalse(report["struct_ok"])

    def test_head_matches_mirror_file(self):
        self._produce_events()
        bundle = export_anchor(self.db, self._out())
        mirror = self.db.path.parent / "audit_anchor.head"
        if mirror.exists():   # written transactionally by journal.py
            seq_s, digest = mirror.read_text(encoding="utf-8").split()
            self.assertEqual(int(seq_s), bundle["state"]["last_seq"])
            self.assertEqual(digest, bundle["state"]["head_digest"])


class TestAnchorExportRefusals(AgentOSTestCase):
    def test_empty_journal_refused(self):
        with self.assertRaises(AnchorExportError):
            export_anchor(self.db, self.root / "empty.json")


if __name__ == "__main__":
    unittest.main()
