"""R9 stabilization contracts.

These tests exercise the upgrade path through the real Database migration
runner, rather than applying individual scripts with executescript().
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentos.db import _apply_migration, open_db  # noqa: E402
from agentos.evidence_pack import build as build_pack  # noqa: E402
from agentos.gates import Gates, _artifact_chain_hash  # noqa: E402
from agentos.journal import Journal  # noqa: E402
from agentos.stage_evals import StageEvals  # noqa: E402
from agentos.wiki import WikiBuilder  # noqa: E402
from tests.test_r8_regressions import R8Case  # noqa: E402

MIGR = ROOT / "src" / "agentos" / "migrations"
BASE_MIGRATIONS = [
    "0001_core.sql", "0002_criteria.sql", "0003_review_fixes.sql",
    "0004_activity_outcomes.sql", "0005_chain_anchor.sql",
    "0006_fence_sink.sql", "0007_stage_evals.sql", "0008_review_r5.sql",
]
STAGES = ("concept", "specification", "plan", "execution",
          "verification", "post_episode")


def _legacy_db(include_campaign: bool = True) -> tuple[Path, Path]:
    root = Path(tempfile.mkdtemp())
    dbp = root / "legacy.db"
    conn = sqlite3.connect(dbp)
    for name in BASE_MIGRATIONS:
        conn.executescript((MIGR / name).read_text(encoding="utf-8"))
    conn.execute(
        "CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT"
        " NOT NULL DEFAULT (datetime('now')))"
    )
    conn.executemany(
        "INSERT INTO schema_migrations(name) VALUES (?)",
        [(name,) for name in BASE_MIGRATIONS],
    )
    conn.execute(
        "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
        ("goal_OWNER", "owner", "ACTIVE"),
    )
    if include_campaign:
        conn.execute(
            "INSERT INTO campaign(id, name, manifest_json, manifest_sha256,"
            " baseline_ref, primary_metric, budget, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            ("camp_OLD", "old", "{\"v\":1}", "hash", "base", "metric", 3, "t"),
        )
    # Fully valid 0008 experiment row; the owner is evidence for recovery.
    conn.execute(
        "INSERT INTO experiment(id, campaign_id, hypothesis, baseline_ref,"
        " candidate_ref, mutable_scope_json, budget_json, seeds_json,"
        " primary_metric, status, measurements_json, frozen_hashes_json,"
        " goal_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("exp_OLD", "camp_OLD", "h", "base", "cand", "[]", "{}", "[]",
         "metric", "KEEP", "{}", "{}", "goal_OWNER"),
    )
    conn.commit()
    conn.close()
    return root, dbp


def _valid_experiment(conn, exp_id: str, campaign_id: str, goal_id: str | None):
    return conn.execute(
        "INSERT INTO experiment(id, campaign_id, hypothesis, baseline_ref,"
        " candidate_ref, mutable_scope_json, budget_json, seeds_json,"
        " primary_metric, status, measurements_json, frozen_hashes_json,"
        " goal_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (exp_id, campaign_id, "h", "base", "cand", "[]", "{}", "[]",
         "metric", "KEEP", "{}", "{}", goal_id),
    )


class TestR9Migrations(unittest.TestCase):
    def test_failed_migration_rolls_back_body_and_marker(self):
        conn = sqlite3.connect(":memory:", isolation_level=None)
        conn.execute(
            "CREATE TABLE schema_migrations (name TEXT PRIMARY KEY,"
            " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        with self.assertRaises(sqlite3.OperationalError):
            _apply_migration(
                conn,
                "broken.sql",
                "CREATE TABLE partial_write(id INTEGER);"
                " INSERT INTO table_that_does_not_exist VALUES (1);",
            )
        self.assertIsNone(conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name='partial_write'").fetchone())
        self.assertIsNone(conn.execute(
            "SELECT name FROM schema_migrations WHERE name='broken.sql'"
        ).fetchone())
        conn.close()

    def test_0008_upgrade_preserves_campaign_and_experiment(self):
        root, dbp = _legacy_db()
        try:
            db = open_db(dbp)
            campaign = db.conn.execute(
                "SELECT id, goal_id, name FROM campaign WHERE id='camp_OLD'"
            ).fetchone()
            exp = db.conn.execute(
                "SELECT id, goal_id FROM experiment WHERE id='exp_OLD'"
            ).fetchone()
            self.assertEqual(dict(campaign), {
                "id": "camp_OLD", "goal_id": "goal_OWNER", "name": "old"})
            self.assertEqual(dict(exp), {"id": "exp_OLD", "goal_id": "goal_OWNER"})
            self.assertIn("0011_review_r9.sql", {
                r[0] for r in db.conn.execute("SELECT name FROM schema_migrations")})
            self.assertEqual(
                db.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(
                db.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            with self.assertRaises(sqlite3.IntegrityError):
                db.conn.execute(
                    "UPDATE campaign_legacy_r9 SET name='tampered'"
                    " WHERE id='camp_OLD'")
            db.conn.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_missing_campaign_is_reconstructed_from_experiment_evidence(self):
        root, dbp = _legacy_db()
        try:
            conn = sqlite3.connect(dbp)
            conn.executescript((MIGR / "0009_review_r6.sql").read_text(encoding="utf-8"))
            conn.executescript((MIGR / "0010_review_r7.sql").read_text(encoding="utf-8"))
            # Simulate a database after the old destructive 0009: campaign
            # rows are gone but append-only experiment evidence remains.
            conn.execute("DROP TRIGGER IF EXISTS experiment_goal_owner")
            conn.execute("DROP TRIGGER IF EXISTS campaign_no_update")
            conn.execute("DROP TRIGGER IF EXISTS campaign_no_delete")
            conn.execute("DROP TABLE campaign")
            conn.execute(
                "CREATE TABLE campaign (id TEXT PRIMARY KEY, goal_id TEXT NOT NULL"
                " REFERENCES goal(id), name TEXT NOT NULL, manifest_json TEXT NOT NULL,"
                " manifest_sha256 TEXT NOT NULL, baseline_ref TEXT NOT NULL,"
                " primary_metric TEXT NOT NULL, budget INTEGER NOT NULL,"
                " created_at TEXT NOT NULL)"
            )
            conn.execute("INSERT INTO schema_migrations(name) VALUES ('0009_review_r6.sql')")
            conn.execute("INSERT INTO schema_migrations(name) VALUES ('0010_review_r7.sql')")
            conn.commit()
            conn.close()

            db = open_db(dbp)
            row = db.conn.execute(
                "SELECT id, goal_id, baseline_ref FROM campaign WHERE id='camp_OLD'"
            ).fetchone()
            self.assertEqual(row[0], "camp_OLD")
            self.assertEqual(row[1], "goal_OWNER")
            self.assertEqual(row[2], "base")
            self.assertEqual(
                db.conn.execute("SELECT COUNT(*) FROM experiment WHERE id='exp_OLD'").fetchone()[0],
                1,
            )
            db.conn.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_owner_trigger_rejects_null_unknown_and_mismatch(self):
        root, dbp = _legacy_db()
        try:
            db = open_db(dbp)
            db.conn.execute(
                "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
                ("goal_OTHER", "other", "ACTIVE"),
            )
            for exp_id, campaign_id, goal_id, expected in (
                ("exp_null", "camp_OLD", None, "owner"),
                ("exp_unknown", "camp_MISSING", "goal_OWNER", "owner"),
                ("exp_mismatch", "camp_OLD", "goal_OTHER", "owner"),
            ):
                with self.assertRaises(sqlite3.IntegrityError) as cm:
                    _valid_experiment(db.conn, exp_id, campaign_id, goal_id)
                self.assertIn(expected, str(cm.exception).lower())
            db.conn.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_interrupted_0010_rebuild_is_recovered_before_retry(self):
        root, dbp = _legacy_db()
        try:
            conn = sqlite3.connect(dbp)
            conn.executescript(
                (MIGR / "0009_review_r6.sql").read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations(name) VALUES"
                " ('0009_review_r6.sql')")
            conn.executescript("""
                CREATE TABLE stage_gate_new (
                  id TEXT PRIMARY KEY,
                  stage TEXT NOT NULL,
                  required_eval_ids_json TEXT NOT NULL,
                  decision TEXT NOT NULL,
                  rationale TEXT NOT NULL,
                  authority TEXT NOT NULL DEFAULT 'GateAuthority',
                  goal_id TEXT,
                  artifact_chain_hash TEXT NOT NULL DEFAULT '',
                  corpus_version TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL
                );
                INSERT INTO stage_gate_new(
                  id, stage, required_eval_ids_json, decision, rationale,
                  authority, goal_id, artifact_chain_hash, corpus_version,
                  created_at)
                VALUES ('gate_PARTIAL', 'concept', '[]', 'fail', 'partial',
                        'GateAuthority', 'goal_OWNER', 'chain', 'c1', 't');
                DROP TABLE stage_gate;
            """)
            conn.commit()
            conn.close()

            db = open_db(dbp)
            gate = db.conn.execute(
                "SELECT id, artifact_chain_hash, corpus_version"
                " FROM stage_gate WHERE id='gate_PARTIAL'").fetchone()
            self.assertEqual(gate[0], "gate_PARTIAL")
            # A decision recovered from an interrupted historical rebuild is
            # evidence, but loses authority and therefore fails closed.
            self.assertEqual((gate[1], gate[2]), ("", ""))
            self.assertIn("0010_review_r7.sql", {
                r[0] for r in db.conn.execute(
                    "SELECT name FROM schema_migrations")})
            db.conn.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_0010_campaign_owner_without_experiments_is_preserved(self):
        root, dbp = _legacy_db()
        try:
            conn = sqlite3.connect(dbp)
            for name in ("0009_review_r6.sql", "0010_review_r7.sql"):
                conn.executescript((MIGR / name).read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations(name) VALUES (?)", (name,))
            conn.execute(
                "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
                ("goal_CURRENT", "current", "ACTIVE"))
            conn.execute(
                "INSERT INTO campaign(id, goal_id, name, manifest_json,"
                " manifest_sha256, baseline_ref, primary_metric, budget,"
                " created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                ("camp_CURRENT", "goal_CURRENT", "current", "{}", "hash",
                 "base", "metric", 1, "t"))
            conn.commit()
            conn.close()

            db = open_db(dbp)
            owner = db.conn.execute(
                "SELECT goal_id FROM campaign WHERE id='camp_CURRENT'"
            ).fetchone()[0]
            self.assertEqual(owner, "goal_CURRENT")
            db.conn.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestR9GateAuthority(R8Case):
    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_gate_persists_pinned_definition_version(self):
        did, version = self.se.define(stage="concept", kind="deterministic",
                                      metric="clarity", threshold=1.0)
        self.se.run_case(did, {"id": "case"}, lambda c: (True, {}),
                         goal_id=self.goal_id, artifact_chain_hash=self.chain,
                         corpus_version="c1")
        self.se.stage_gate("concept", [did], goal_id=self.goal_id,
                           artifact_chain_hash=self.chain, corpus_version="c1")
        raw = self.db.conn.execute(
            "SELECT required_eval_ids_json FROM stage_gate"
        ).fetchone()[0]
        self.assertEqual(json.loads(raw), [f"{did}@{version}"])

    def test_malformed_or_bare_required_refs_fail_release_authority(self):
        concept_id = None
        for stage in STAGES:
            did, _ = self.se.define(
                stage=stage, kind="deterministic",
                metric=f"authority_{stage}", threshold=1.0)
            self.se.run_case(
                did, {"id": f"case-{stage}"}, lambda c: (True, {}),
                goal_id=self.goal_id, artifact_chain_hash=self.chain,
                corpus_version="c1")
            self.se.stage_gate(
                stage, [did], goal_id=self.goal_id,
                artifact_chain_hash=self.chain, corpus_version="c1")
            if stage == "concept":
                concept_id = did
        self.db.conn.execute(
            "INSERT INTO stage_gate(id, stage, required_eval_ids_json, decision,"
            " rationale, goal_id, artifact_chain_hash, corpus_version, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            ("bad-gate", "concept", json.dumps([concept_id]), "pass", "bad",
             self.goal_id, self.chain, "c1", "9999-01-01T00:00:00Z"),
        )
        self.eng.submit_to_gate(self.goal_id)
        result = Gates(self.db, self.j).evaluate_release(self.goal_id)
        self.assertEqual(result["result"], "fail")
        self.assertTrue(any(
            "not a pinned id@version" in reason
            for reason in result["reasons"]), result["reasons"])

    def test_new_definition_version_invalidates_old_gate_authority(self):
        concept_id = None
        for stage in STAGES:
            did, _ = self.se.define(
                stage=stage, kind="deterministic",
                metric=f"version_{stage}", threshold=1.0)
            self.se.run_case(
                did, {"id": f"case-{stage}"}, lambda c: (True, {}),
                goal_id=self.goal_id, artifact_chain_hash=self.chain,
                corpus_version="c1")
            self.se.stage_gate(
                stage, [did], goal_id=self.goal_id,
                artifact_chain_hash=self.chain, corpus_version="c1")
            if stage == "concept":
                concept_id = did
        self.se.define(
            stage="concept", kind="deterministic", metric="version_concept",
            threshold=1.0, def_id=concept_id)
        self.eng.submit_to_gate(self.goal_id)
        result = Gates(self.db, self.j).evaluate_release(self.goal_id)
        self.assertEqual(result["result"], "fail")
        self.assertTrue(any("is stale; latest is" in reason
                            for reason in result["reasons"]), result["reasons"])


class TestR9WikiScoping(unittest.TestCase):
    def test_legacy_baseline_projects_through_campaign_owner(self):
        root, dbp = _legacy_db()
        try:
            db = open_db(dbp)
            # Historic baseline has no goal_id but campaign has an owner.
            db.conn.execute("DROP TRIGGER IF EXISTS experiment_goal_owner")
            _valid_experiment(db.conn, "exp_NULL", "camp_OLD", None)
            wb = WikiBuilder(db, root)
            wb.build()
            note = root / "wiki" / "_generated" / "experiment-exp_NULL.md"
            self.assertIn("goal_id: \"goal_OWNER\"", note.read_text(encoding="utf-8"))
            self.assertTrue(wb.check()["ok"], wb.check()["issues"])
            db.conn.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_frontmatter_newline_is_not_a_new_field(self):
        root = Path(tempfile.mkdtemp())
        try:
            db = open_db(root / "db.sqlite")
            db.conn.execute(
                "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
                ("goal_SAFE", "safe", "ACTIVE"),
            )
            injected_title = "safe\ngoal_id: goal_OTHER"
            db.conn.execute(
                "INSERT INTO task(id, goal_id, title, status, definition_of_done)"
                " VALUES (?,?,?,?,?)",
                ("task_SAFE", "goal_SAFE", injected_title, "READY", "done"),
            )
            wb = WikiBuilder(db, root)
            wb.build()
            text = (root / "wiki" / "_generated" / "task-task_SAFE.md").read_text(
                encoding="utf-8")
            from agentos.wiki import parse_frontmatter
            fm = parse_frontmatter(text)
            self.assertEqual(fm["goal_id"], "goal_SAFE")
            self.assertEqual(fm["title"], injected_title)
            self.assertTrue(wb.check()["ok"], wb.check()["issues"])
            db.conn.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_evidence_pack_excludes_other_goal_wiki_notes(self):
        root = Path(tempfile.mkdtemp())
        try:
            db = open_db(root / "db.sqlite")
            db.conn.executemany(
                "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
                (("goal_ONE", "one", "ACTIVE"),
                 ("goal_TWO", "two", "ACTIVE")),
            )
            WikiBuilder(db, root).build()
            foreign_note = (root / "wiki" / "_generated" /
                            "goal-goal_TWO.md")
            foreign_note.write_text(
                foreign_note.read_text(encoding="utf-8").replace(
                    "\n---\n", '\ngoal_id: "goal_ONE"\n---\n', 1),
                encoding="utf-8")
            pack = build_pack(db, root, "goal_ONE")["pack"]
            refs = pack["wiki_refs"]
            self.assertNotIn("Home", refs)
            self.assertIn("goal-goal_ONE", refs)
            self.assertNotIn("goal-goal_TWO", refs)
            db.conn.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_projection_does_not_truncate_older_canonical_goals(self):
        root = Path(tempfile.mkdtemp())
        try:
            db = open_db(root / "db.sqlite")
            db.conn.executemany(
                "INSERT INTO goal(id, concept_text, status, created_at)"
                " VALUES (?,?,?,?)",
                [(f"goal_CAP{i:02d}", "cap", "ACTIVE",
                  f"2020-01-{(i % 28) + 1:02d}T{i:02d}:00:00Z")
                 for i in range(55)],
            )
            wb = WikiBuilder(db, root)
            wb.build()
            notes = list((wb.wiki / "_generated").glob("goal-goal_CAP*.md"))
            self.assertEqual(len(notes), 55)
            self.assertTrue(
                (wb.wiki / "_generated" / "goal-goal_CAP00.md").exists())
            db.conn.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_failed_projection_swap_restores_exact_previous_tree(self):
        root = Path(tempfile.mkdtemp())
        try:
            db = open_db(root / "db.sqlite")
            db.conn.execute(
                "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
                ("goal_SWAP", "swap", "ACTIVE"))
            wb = WikiBuilder(db, root)
            wb.build()
            stale = wb.wiki / "_generated" / "stale.md"
            stale.write_text("old projection evidence", encoding="utf-8")

            def snapshot():
                return {p.name: p.read_bytes() for p in sorted(
                    (wb.wiki / "_generated").glob("*")) if p.is_file()}

            before = snapshot()
            original_rename = Path.rename

            def fail_new_projection(path_obj, target):
                if (path_obj.name == "_generated"
                        and path_obj.parent.name.startswith(".wiki-stage-")):
                    raise OSError("injected swap failure")
                return original_rename(path_obj, target)

            with patch.object(Path, "rename", new=fail_new_projection):
                with self.assertRaises(OSError):
                    wb.build()
            self.assertEqual(snapshot(), before)
            db.conn.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
