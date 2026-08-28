"""Phase 3 tests: deterministic wiki projection, idempotent rebuild,
link/frontmatter/orphan validation."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentos.db import open_db  # noqa: E402
from agentos.stage_evals import StageEvals  # noqa: E402
from agentos.wiki import WikiBuilder  # noqa: E402


def _seed(root: Path):
    db = open_db(root / "agentos.db")
    j = None
    se = StageEvals(db, root)
    goal_id = db.conn.execute(
        "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
        ("goal_WIKI1", "wiki probe", "ACTIVE")).rowcount and \
        "goal_WIKI1" or "goal_WIKI1"
    db.conn.execute(
        "INSERT INTO task(id, goal_id, title, status, definition_of_done)"
        " VALUES (?,?,?,?,?)",
        ("task_WIKI1", goal_id, "impl", "DONE", "DoD"))
    db.conn.execute(
        "INSERT INTO run(id, goal_id, task_id, worker_type, status,"
        " terminal_reason, lease_owner, lease_expires_at, workspace_path)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        ("run_WIKI1", goal_id, "task_WIKI1", "fake", "COMPLETED",
         "success", "w", "2099-01-01T00:00:00Z", str(root / "ws")))
    se.define(stage="concept", kind="deterministic", metric="clarity",
              threshold=0.8)
    return db, goal_id


class TestWiki(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = Path(tempfile.mkdtemp())
        self.db, self.goal_id = _seed(self.root)
        self.wb = WikiBuilder(self.db, self.root)

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass

    def _tree_hash(self) -> dict:
        return {str(p.relative_to(self.wb.wiki)): p.read_bytes()
                for p in sorted(self.wb.wiki.rglob("*.md"))}

    def test_build_creates_notes_and_is_idempotent(self):
        r1 = self.wb.build()
        t1 = self._tree_hash()
        r2 = self.wb.build()
        t2 = self._tree_hash()
        self.assertGreater(r1["notes_written"], 0)
        self.assertEqual(t1, t2, "rebuild must be byte-identical")

    def test_check_clean_after_build(self):
        self.wb.build()
        res = self.wb.check()
        self.assertTrue(res["ok"],
                        f"issues after clean build: {res['issues']}")
        self.assertGreater(res["files"], 0)

    def test_check_fails_closed_when_generated_projection_is_empty(self):
        (self.wb.wiki / "_generated").mkdir(parents=True)
        res = self.wb.check()
        self.assertFalse(res["ok"])
        self.assertIn(
            "missing_generated_projection",
            {issue["kind"] for issue in res["issues"]})

    def test_check_detects_broken_link(self):
        self.wb.build()
        p = self.wb.wiki / "_generated" / "Home.md"
        p.write_text(p.read_text(encoding="utf-8") +
                     "\n[[no-such-note]]\n", encoding="utf-8")
        res = self.wb.check()
        self.assertFalse(res["ok"])
        kinds = {i["kind"] for i in res["issues"]}
        self.assertIn("broken_link", kinds)

    def test_check_detects_duplicate_ids_and_orphans(self):
        self.wb.build()
        (self.wb.wiki / "50-Episodes").mkdir(exist_ok=True)
        dup = self.wb.wiki / "50-Episodes" / "dup.md"
        home = self.wb.wiki / "_generated" / "Home.md"
        dup.write_text(home.read_text(encoding="utf-8"), encoding="utf-8")
        res = self.wb.check()
        kinds = [i["kind"] for i in res["issues"]]
        self.assertIn("duplicate_id", kinds)

    def test_check_detects_missing_frontmatter(self):
        self.wb.build()
        bad = self.wb.wiki / "_generated" / "nofm.md"
        bad.write_text("# no frontmatter\n", encoding="utf-8")
        res = self.wb.check()
        kinds = {i["kind"] for i in res["issues"]}
        self.assertIn("invalid_frontmatter", kinds)


if __name__ == "__main__":
    unittest.main()
