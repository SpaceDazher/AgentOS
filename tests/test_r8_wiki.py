"""R8 wiki regressions: spaced-name secret redaction + leak detection,
same-volume staging (build works regardless of vault drive)."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentos.db import open_db  # noqa: E402
from agentos.wiki import WikiBuilder, leak_scan  # noqa: E402


def _seed(db, goal_id="goal_W1"):
    db.conn.execute(
        "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
        (goal_id, "probe", "ACTIVE"))
    db.conn.execute(
        "INSERT INTO task(id, goal_id, title, status, definition_of_done)"
        " VALUES (?,?,?,?,?)",
        ("task_W1", goal_id, "impl leaky api key = TOPSECRET", "DONE",
         "DoD"))
    db.conn.execute(
        "INSERT INTO run(id, goal_id, task_id, worker_type, status,"
        " terminal_reason, lease_owner, lease_expires_at, workspace_path)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        ("run_W1", goal_id, "task_W1", "fake", "COMPLETED", "success",
         "probe", "2099-01-01T00:00:00Z", str(Path(tempfile.mkdtemp()))))


class TestSpacedSecretRedaction(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.db = open_db(self.root / "t.db")
        _seed(self.db)
        self.wb = WikiBuilder(self.db, self.root)

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass

    def test_spaced_name_redacted_and_check_clean(self):
        self.wb.build()
        leaks = [p for p in self.wb.wiki.rglob("*.md")
                 if "TOPSECRET" in p.read_text(encoding="utf-8")]
        self.assertEqual(leaks, [], f"secret leaked into {leaks}")
        res = self.wb.check()
        self.assertTrue(res["ok"], res["issues"])

    def test_check_detects_manual_leak(self):
        self.wb.build()
        target = self.wb.wiki / "_generated" / "Home.md"
        target.write_text(
            target.read_text(encoding="utf-8") + "\napi key = leak2\n",
            encoding="utf-8")
        res = self.wb.check()
        self.assertFalse(res["ok"])
        self.assertTrue(any(i["kind"] == "secret_leak" for i in
                            res["issues"]), res["issues"])

    def test_leak_scan_patterns(self):
        self.assertEqual(leak_scan("api key = TOPSECRET"),
                         ["api key = TOPSECRET"])
        self.assertEqual(leak_scan("api_key=abc"), ["api_key=abc"])
        self.assertEqual(leak_scan("password: p@ss"), ["password: p@ss"])
        self.assertEqual(leak_scan("x = [REDACTED]"), [])
        self.assertEqual(leak_scan("plain line"), [])


class TestSameVolumeStaging(unittest.TestCase):
    def test_build_works_with_vault_on_other_drive(self):
        """Vault on D: while system temp is on C: — staging is created beside
        the vault so the atomic rename never crosses volumes."""
        vault_root = ROOT / ".tmp-wiki-voltest"
        shutil.rmtree(vault_root, ignore_errors=True)
        try:
            db = open_db(vault_root / "t.db")
            _seed(db, "goal_VOL")
            wb = WikiBuilder(db, vault_root)
            r1 = wb.build()
            h1 = {p.name: p.read_bytes() for p in sorted(
                (wb.wiki / "_generated").glob("*.md"))}
            r2 = wb.build()
            h2 = {p.name: p.read_bytes() for p in sorted(
                (wb.wiki / "_generated").glob("*.md"))}
            self.assertEqual(h1, h2, "rebuild changed files")
            self.assertGreater(len(h1), 0)
            db.conn.close()
        finally:
            shutil.rmtree(vault_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
