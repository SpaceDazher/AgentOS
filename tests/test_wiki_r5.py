"""R5 wiki regressions: stale generated notes removed, secrets redacted and
detected, dangling canonical refs reported."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentos.db import open_db  # noqa: E402
from agentos.wiki import WikiBuilder  # noqa: E402


class WikiR5(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = Path(tempfile.mkdtemp())
        self.db = open_db(self.root / "agentos.db")
        self.db.conn.execute(
            "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
            ("goal_R5", "probe", "ACTIVE"))
        self.db.conn.execute(
            "INSERT INTO campaign(id, goal_id, name, manifest_json,"
            " manifest_sha256, baseline_ref, primary_metric, budget)"
            " VALUES (?,?,?,?,?,?,?,?)",
            ("camp", "goal_R5", "wiki", "{}", "hash", "b", "m", 1))
        self.wb = WikiBuilder(self.db, self.root)

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass

    def test_stale_generated_note_removed_on_rebuild(self):
        self.wb.build()
        stale = self.wb.wiki / "_generated" / "goal-GONE.md"
        stale.write_text("---\nid: GONE\ntype: goal\ntitle: x\nstatus: old\n"
                         "created_at: ''\nupdated_at: ''\n---\n# gone\n",
                         encoding="utf-8")
        self.assertTrue(stale.exists())
        self.wb.build()
        self.assertFalse(stale.exists(),
                         "stale generated note survived rebuild")

    def test_secrets_redacted_and_leak_detected(self):
        # canonical record carries a secret in untrusted text
        self.db.conn.execute(
            "INSERT INTO experiment(id, campaign_id, hypothesis, baseline_ref,"
            " candidate_ref, mutable_scope_json, seeds_json, primary_metric,"
            " status, measurements_json, decision_rationale,"
            " frozen_hashes_json, goal_id)"
            " VALUES ('exp_R5','camp','use api_key=TOPSECRET-12345','b','c',"
            "'{}','[]','m','KEEP','{}','why','{}','goal_R5')")
        self.wb.build()
        note = (self.wb.wiki / "_generated" / "experiment-exp_R5.md"
                ).read_text(encoding="utf-8")
        self.assertNotIn("TOPSECRET", note, "secret leaked into vault")
        res = self.wb.check()
        kinds = {i["kind"] for i in res["issues"]}
        self.assertNotIn("secret_leak", kinds,
                         "redaction failed; checker caught a leak")

    def test_unredacted_secret_is_flagged(self):
        self.wb.build()
        p = self.wb.wiki / "_generated" / "Home.md"
        p.write_text(p.read_text(encoding="utf-8") +
                     "\napi_key = SUPERSECRETVALUE123\n", encoding="utf-8")
        res = self.wb.check()
        kinds = {i["kind"] for i in res["issues"]}
        self.assertIn("secret_leak", kinds)

    def test_dangling_canonical_ref_reported(self):
        self.wb.build()
        p = self.wb.wiki / "_generated" / "goal-goal_R5.md"
        text = p.read_text(encoding="utf-8").replace(
            'goal_id: "goal_R5"', 'goal_id: "goal_MISSING"', 1)
        p.write_text(text, encoding="utf-8")
        res = self.wb.check()
        kinds = {i["kind"] for i in res["issues"]}
        self.assertIn("dangling_ref", kinds)

    def test_duplicate_frontmatter_key_is_invalid(self):
        self.wb.build()
        p = self.wb.wiki / "_generated" / "goal-goal_R5.md"
        text = p.read_text(encoding="utf-8").replace(
            "---\n", '---\ngoal_id: "goal_MISSING"\n', 1)
        p.write_text(text, encoding="utf-8")
        kinds = {i["kind"] for i in self.wb.check()["issues"]}
        self.assertIn("invalid_frontmatter", kinds)


if __name__ == "__main__":
    unittest.main()
