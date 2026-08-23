"""R8: migration 0008->HEAD preserves campaigns; DB trigger refuses
cross-goal experiment inserts."""
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
MIGR = ROOT / "src" / "agentos" / "migrations"


class TestUpgradePreservesCampaigns(unittest.TestCase):
    def _apply(self, db_path, files):
        conn = sqlite3.connect(db_path)
        for f in files:
            conn.executescript((MIGR / f).read_text(encoding="utf-8"))
        conn.commit()
        return conn

    def test_upgrade_keeps_campaigns_and_enforces_owner_trigger(self):
        tmp = Path(tempfile.mkdtemp())
        dbp = tmp / "u.db"
        # --- build a 0008-state DB manually (schema as of 0008) ---
        conn = self._apply(dbp, ["0001_core.sql", "0002_criteria.sql",
                                 "0003_review_fixes.sql",
                                 "0004_activity_outcomes.sql",
                                 "0005_chain_anchor.sql",
                                 "0006_fence_sink.sql"])
        conn.executescript(Path(MIGR / "0007_stage_evals.sql").read_text(
            encoding="utf-8"))
        conn.executescript(Path(MIGR / "0008_review_r5.sql").read_text(
            encoding="utf-8"))
        conn.execute("INSERT INTO goal(id, concept_text, status) VALUES"
                     " ('goal_OLD','probe','ACTIVE')")
        # 0008-era campaign: NO goal_id column
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(campaign)").fetchall()]
        self.assertNotIn("goal_id", cols)
        conn.execute(
            "INSERT INTO campaign(id, name, manifest_json, manifest_sha256,"
            " baseline_ref, primary_metric, budget, created_at)"
            " VALUES ('camp_OLD','n','{}','h','b','m',3,'t')")
        conn.commit()
        n_exp_before = 2
        conn.close()

        # --- upgrade to HEAD ---
        conn = sqlite3.connect(dbp)
        for f in ["0009_review_r6.sql", "0010_review_r7.sql"]:
            conn.executescript((MIGR / f).read_text(encoding="utf-8"))
        conn.commit()
        campaigns_after = conn.execute(
            "SELECT COUNT(*) FROM campaign").fetchone()[0]
        owner = conn.execute(
            "SELECT goal_id FROM campaign WHERE id='camp_OLD'"
        ).fetchone()[0]
        goal_exists = conn.execute(
            "SELECT COUNT(*) FROM goal WHERE id=?", (owner,)).fetchone()[0]
        # DB-enforced scoping: cross-goal insert must be refused by trigger
        try:
            conn.execute(
                "INSERT INTO experiment(id, campaign_id, hypothesis,"
                " baseline_ref, candidate_ref, status, goal_id)"
                " VALUES ('exp_x','camp_OLD','h','b','c','KEEP',"
                "'goal_SOMEONE_ELSE')")
            cross_goal_inserted = True
        except sqlite3.IntegrityError as e:
            cross_goal_inserted = False
            msg = str(e)
        conn.close()
        self.assertEqual(campaigns_after, 1,
                         "campaign history lost during upgrade")
        self.assertEqual(owner, "goal_MIGRATED")
        self.assertEqual(goal_exists, 1)
        self.assertFalse(cross_goal_inserted,
                         "raw SQL inserted a cross-goal experiment")
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
