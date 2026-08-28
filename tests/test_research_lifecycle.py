"""Regression tests for research-series identity and wiki staging cleanup."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentos.db import _backfill_research_series, open_db  # noqa: E402
from agentos.engine import Engine  # noqa: E402
from agentos.machines import Machines  # noqa: E402
from agentos.research import (  # noqa: E402
    fixture_bundle,
    reconcile_research_duplicates,
    run_research_plan,
)
from agentos.wiki import WikiBuilder  # noqa: E402
import agentos.research as research_module  # noqa: E402
import agentos.wiki as wiki_module  # noqa: E402


class TestResearchSeriesLifecycle(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.db = open_db(self.root / "agentos.db")

    def tearDown(self):
        self.db.conn.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_exact_key_and_manifest_reuses_canonical_campaign(self):
        bundle = fixture_bundle("stable series")
        first = run_research_plan(
            self.db, self.root, "Stable series", bundle,
            research_key="S1-STABLE")
        before = {
            table: self.db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("goal", "research_campaign", "research_artifact",
                          "research_evaluation")
        }

        second = run_research_plan(
            self.db, self.root, "Stable series", bundle,
            research_key="S1-STABLE")

        self.assertEqual(second["goal_id"], first["goal_id"])
        self.assertEqual(second["campaign_id"], first["campaign_id"])
        self.assertTrue(second["reused"])
        self.assertEqual(second["research_key"], "S1-STABLE")
        self.assertEqual(second["revision"], 1)
        for table, count in before.items():
            self.assertEqual(
                self.db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                count, table)

    def test_manifest_change_creates_revision_and_journaled_supersession(self):
        first = run_research_plan(
            self.db, self.root, "Revision series", fixture_bundle("v1"),
            research_key="S1-REVISION")
        changed = fixture_bundle("v2")
        changed["claims"][0]["text"] = "The revised fixture has three sources."
        second = run_research_plan(
            self.db, self.root, "Revision series", changed,
            research_key="S1-REVISION")

        self.assertNotEqual(second["goal_id"], first["goal_id"])
        rows = self.db.conn.execute(
            "SELECT revision, campaign_id, supersedes_campaign_id"
            " FROM research_series WHERE research_key=? ORDER BY revision",
            ("S1-REVISION",)).fetchall()
        self.assertEqual([r[0] for r in rows], [1, 2])
        self.assertEqual(rows[1][1], second["campaign_id"])
        self.assertEqual(rows[1][2], first["campaign_id"])
        self.assertEqual(
            self.db.conn.execute("SELECT status FROM goal WHERE id=?",
                                 (first["goal_id"],)).fetchone()[0],
            "CANCELLED")
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM audit_event WHERE goal_id=?"
                " AND event_type='goal.cancelled'", (first["goal_id"],)
            ).fetchone()[0], 1)
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM relation_assertion"
                " WHERE src_type='research_campaign' AND src_id=?"
                " AND rel='SUPERSEDES' AND dst_id=?",
                (second["campaign_id"], first["campaign_id"]),
            ).fetchone()[0], 1)

    def test_reverting_manifest_creates_a_new_latest_revision(self):
        v1 = fixture_bundle("revert series")
        v2 = fixture_bundle("revert series")
        v2["claims"][0]["text"] = "The second revision changes the claim."
        first = run_research_plan(
            self.db, self.root, "Revert series", v1,
            research_key="S1-REVERT")
        second = run_research_plan(
            self.db, self.root, "Revert series", v2,
            research_key="S1-REVERT")
        third = run_research_plan(
            self.db, self.root, "Revert series", v1,
            research_key="S1-REVERT")

        rows = self.db.conn.execute(
            "SELECT revision, campaign_id, manifest_sha256"
            " FROM research_series WHERE research_key=? ORDER BY revision",
            ("S1-REVERT",)).fetchall()
        self.assertEqual([row[0] for row in rows], [1, 2, 3])
        self.assertEqual(rows[0][1], first["campaign_id"])
        self.assertEqual(rows[1][1], second["campaign_id"])
        self.assertEqual(rows[2][1], third["campaign_id"])
        self.assertEqual(rows[0][2], rows[2][2])
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM goal WHERE status='ACTIVE'"
                " AND id IN (?,?,?)",
                (first["goal_id"], second["goal_id"], third["goal_id"]),
            ).fetchone()[0], 1)
        self.assertEqual(
            self.db.conn.execute(
                "SELECT status FROM goal WHERE id=?", (third["goal_id"],)
            ).fetchone()[0], "ACTIVE")

    def test_failed_supersession_is_repaired_by_exact_retry(self):
        first = run_research_plan(
            self.db, self.root, "Retry retirement", fixture_bundle("v1"),
            research_key="S1-RETRY")
        changed = fixture_bundle("v2")
        changed["claims"][0]["text"] = "The retry revision is different."
        original = Machines.cancel_superseded_goal
        calls = {"count": 0}

        def fail_once(instance, goal_id, payload=None):
            if calls["count"] == 0:
                calls["count"] += 1
                raise RuntimeError("injected retirement failure")
            return original(instance, goal_id, payload)

        with mock.patch.object(Machines, "cancel_superseded_goal",
                               new=fail_once):
            failed = run_research_plan(
                self.db, self.root, "Retry retirement", changed,
                research_key="S1-RETRY")
            self.assertEqual(failed["status"], "fail")
            retried = run_research_plan(
                self.db, self.root, "Retry retirement", changed,
                research_key="S1-RETRY")

        # The failed first revision committed its canonical rows before the
        # injected retirement error, so no evaluation was appended.  Exact
        # retry repairs lineage and resumes that missing deterministic
        # evaluation without creating another Goal/campaign.
        self.assertEqual(retried["status"], "pass")
        self.assertTrue(retried["reused"])
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM research_evaluation WHERE campaign_id=?",
                (retried["campaign_id"],)).fetchone()[0], 1)
        self.assertEqual(
            self.db.conn.execute(
                "SELECT status FROM goal WHERE id=?", (first["goal_id"],)
            ).fetchone()[0], "CANCELLED")
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM goal g JOIN research_series rs"
                " ON rs.goal_id=g.id WHERE rs.research_key=?"
                " AND g.status='ACTIVE'", ("S1-RETRY",)
            ).fetchone()[0], 1)

    def test_persistence_failure_releases_lock_and_cancels_partial_goal(self):
        with mock.patch.object(Path, "write_bytes",
                               side_effect=OSError("injected artifact failure")):
            result = run_research_plan(
                self.db, self.root, "Failure hygiene", fixture_bundle("fault"),
                research_key="S1-FAILURE")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM research_series_lock"
                " WHERE research_key='S1-FAILURE'"
            ).fetchone()[0], 0)
        goals = self.db.conn.execute(
            "SELECT id, status FROM goal WHERE concept_text=?",
            ("Failure hygiene",)).fetchall()
        self.assertEqual(len(goals), 1)
        self.assertNotIn(goals[0]["status"],
                         {"DRAFT", "ACTIVE", "GATE_PENDING", "REJECTED", "ESCALATED"})
        self.assertFalse(
            (self.root / "goals" / goals[0]["id"] / "research").exists())

    def test_failure_cleanup_never_cancels_a_concurrent_unrelated_goal(self):
        original_create = Engine.create_goal
        unrelated: dict[str, str] = {}

        def create_with_concurrent_goal(instance, concept_text, *args, **kwargs):
            if concept_text == "Owned failed attempt":
                unrelated["id"] = original_create(
                    instance, "Concurrent unrelated goal", actor="requester")
            return original_create(instance, concept_text, *args, **kwargs)

        with mock.patch.object(Engine, "create_goal", new=create_with_concurrent_goal), \
                mock.patch.object(Engine, "refine_spec",
                                  side_effect=RuntimeError("injected pre-persist failure")):
            result = run_research_plan(
                self.db, self.root, "Owned failed attempt", fixture_bundle("fault"),
                research_key="S1-OWNED-FAILURE")

        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            self.db.conn.execute("SELECT status FROM goal WHERE id=?",
                                 (unrelated["id"],)).fetchone()[0], "DRAFT")
        owned = self.db.conn.execute(
            "SELECT status FROM goal WHERE concept_text='Owned failed attempt'"
        ).fetchone()
        self.assertIsNotNone(owned)
        self.assertEqual(owned["status"], "CANCELLED")

    def test_backfill_adopts_ticket_key_and_orders_revisions(self):
        campaigns = []
        for index, (stamp, digest) in enumerate((
                ("2026-01-01T00:00:00.000Z", "a" * 64),
                ("2026-01-01T00:00:01.000Z", "a" * 64),
                ("2026-01-01T00:00:02.000Z", "b" * 64))):
            goal_id = f"goal-TICKET-{index}"
            campaign_id = f"camp-TICKET-{index}"
            self.db.conn.execute(
                "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
                (goal_id, "ticket", "ACTIVE"))
            self.db.conn.execute(
                "INSERT INTO research_campaign(id, goal_id, topic,"
                " manifest_sha256, created_at) VALUES (?,?,?,?,?)",
                (campaign_id, goal_id, f"s1-003 benchmark pass {index}",
                 digest, stamp))
            campaigns.append(campaign_id)

        _backfill_research_series(self.db.conn)
        rows = self.db.conn.execute(
            "SELECT research_key, revision, campaign_id, supersedes_campaign_id"
            " FROM research_series WHERE campaign_id IN (?,?,?)"
            " ORDER BY revision", tuple(campaigns)).fetchall()
        self.assertEqual([row[0] for row in rows], ["S1-003"] * 3)
        self.assertEqual([row[1] for row in rows], [1, 2, 3])
        self.assertEqual([row[2] for row in rows], campaigns)
        self.assertEqual([row[3] for row in rows], [None, campaigns[0], campaigns[1]])

    def test_research_reconcile_cli_dry_run_apply_and_selector_guards(self):
        first = run_research_plan(
            self.db, self.root, "S1-003 lineage", fixture_bundle("v1"),
            research_key="S1-003")
        changed = fixture_bundle("v2")
        changed["claims"][0]["text"] = "CLI repair revision."
        def leave_old_active(instance, goal_id, payload=None):
            raise RuntimeError("injected CLI repair gap")

        with mock.patch.object(Machines, "cancel_superseded_goal",
                               new=leave_old_active):
            second = run_research_plan(
                self.db, self.root, "S1-003 lineage", changed,
                research_key="S1-003")
        self.assertEqual(second["status"], "fail")
        before = self.db.conn.execute(
            "SELECT status FROM goal WHERE id=?", (first["goal_id"],)
        ).fetchone()[0]

        from agentos.cli import main as cli_main

        def invoke(*args):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = cli_main(list(args))
            return code, json.loads(output.getvalue())

        code, preview = invoke(
            "research-reconcile", "--db", str(self.root),
            "--research-key", "S1-003")
        self.assertEqual(code, 0)
        self.assertEqual(preview["mode"], "dry-run")
        self.assertGreaterEqual(preview["candidates"], 1)
        self.assertEqual(
            self.db.conn.execute(
                "SELECT status FROM goal WHERE id=?", (first["goal_id"],)
            ).fetchone()[0], before)

        code, applied = invoke(
            "research-reconcile", "--db", str(self.root),
            "--research-key", "S1-003", "--apply")
        self.assertEqual(code, 0)
        self.assertEqual(applied["mode"], "apply")
        self.assertGreaterEqual(applied["cancelled"], 1)
        self.assertEqual(
            self.db.conn.execute(
                "SELECT status FROM goal WHERE id=?", (first["goal_id"],)
            ).fetchone()[0], "CANCELLED")

        code, missing = invoke(
            "research-reconcile", "--db", str(self.root), "--apply")
        self.assertNotEqual(code, 0)
        self.assertIn("selector", json.dumps(missing).lower())
        code, ambiguous = invoke(
            "research-reconcile", "--db", str(self.root),
            "--research-key", "S1-003", "--topic", "S1-003 lineage",
            "--apply")
        self.assertNotEqual(code, 0)
        self.assertIn("exactly one", json.dumps(ambiguous).lower())

    def test_reconcile_is_dry_run_by_default_and_cancels_only_old_active_duplicates(self):
        # Different keys model the historical pre-series duplicate shape.
        runs = [run_research_plan(
            self.db, self.root, "Historical duplicate", fixture_bundle("same"),
            research_key=f"legacy-{i}") for i in range(3)]
        preview = reconcile_research_duplicates(self.db, apply=False)
        self.assertEqual(preview["mode"], "dry-run")
        self.assertEqual(preview["cancelled"], 0)
        self.assertGreaterEqual(preview["candidates"], 2)
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM goal WHERE status='ACTIVE'"
                " AND id IN (?,?,?)", tuple(r["goal_id"] for r in runs)
            ).fetchone()[0], 3)

        applied = reconcile_research_duplicates(
            self.db, topic="Historical duplicate", apply=True)
        self.assertEqual(applied["mode"], "apply")
        self.assertEqual(applied["cancelled"], 2)
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM goal WHERE status='ACTIVE'"
                " AND id IN (?,?,?)", tuple(r["goal_id"] for r in runs)
            ).fetchone()[0], 1)

    def test_reconcile_apply_requires_an_explicit_selector(self):
        with self.assertRaises(ValueError):
            reconcile_research_duplicates(self.db, apply=True)

    def test_backfill_populates_every_unbound_legacy_campaign(self):
        digest = "a" * 64
        rows = []
        for index in range(2):
            goal_id = f"goal-BACKFILL-{index}"
            campaign_id = f"camp-BACKFILL-{index}"
            self.db.conn.execute(
                "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
                (goal_id, "backfill", "ACTIVE"))
            self.db.conn.execute(
                "INSERT INTO research_campaign(id, goal_id, topic,"
                " manifest_sha256) VALUES (?,?,?,?)",
                (campaign_id, goal_id, "legacy backfill", digest))
            rows.append(campaign_id)

        _backfill_research_series(self.db.conn)
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM research_series"
                " WHERE campaign_id IN (?,?)", tuple(rows)).fetchone()[0], 2)
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM research_campaign c"
                " LEFT JOIN research_series rs ON rs.campaign_id=c.id"
                " WHERE rs.campaign_id IS NULL").fetchone()[0], 0)

    def test_backfill_collision_is_explicit_and_leaves_no_gap(self):
        digest = "b" * 64
        self.db.conn.execute(
            "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
            ("goal-BACKFILL-COLLISION", "collision", "ACTIVE"))
        self.db.conn.execute(
            "INSERT INTO research_campaign(id, goal_id, topic, manifest_sha256)"
            " VALUES (?,?,?,?)",
            ("camp-BACKFILL-COLLISION", "goal-BACKFILL-COLLISION",
             "collision", digest))
        self.db.conn.execute(
            "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
            ("goal-BACKFILL-OTHER", "other", "ACTIVE"))
        self.db.conn.execute(
            "INSERT INTO research_campaign(id, goal_id, topic, manifest_sha256)"
            " VALUES (?,?,?,?)",
            ("camp-BACKFILL-OTHER", "goal-BACKFILL-OTHER", "other", "c" * 64))
        self.db.conn.execute(
            "INSERT INTO research_series(id, research_key, revision, campaign_id,"
            " goal_id, topic, manifest_sha256) VALUES (?,?,?,?,?,?,?)",
            ("series-existing", "legacy:camp-BACKFILL-COLLISION", 1,
             "camp-BACKFILL-OTHER", "goal-BACKFILL-OTHER", "other", "c" * 64))

        with self.assertRaises(sqlite3.IntegrityError):
            _backfill_research_series(self.db.conn)
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM research_campaign c"
                " LEFT JOIN research_series rs ON rs.campaign_id=c.id"
                " WHERE c.id='camp-BACKFILL-COLLISION'"
                " AND rs.campaign_id IS NULL").fetchone()[0], 1)

    def test_concurrent_exact_repeats_create_one_goal(self):
        db_path = self.root / "concurrent.db"
        # Migrations themselves are performed before workers race; this test
        # targets research-key reservation rather than startup migration.
        initialized = open_db(db_path)
        initialized.conn.close()
        barrier = threading.Barrier(2)
        results: list[dict] = []
        errors: list[BaseException] = []

        def worker() -> None:
            db = open_db(db_path)
            try:
                barrier.wait(timeout=10)
                results.append(run_research_plan(
                    db, self.root, "Concurrent", fixture_bundle("same"),
                    research_key="S1-CONCURRENT"))
            except BaseException as exc:  # report both worker failures
                errors.append(exc)
            finally:
                db.conn.close()

        # Concurrent projection swaps are a separate concern; this probe
        # isolates the canonical DB reservation and evaluation path.
        with mock.patch.object(
                research_module, "_attach_research_outputs",
                side_effect=lambda db, root, goal_id, result: result):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
        self.assertFalse(errors, errors)
        self.assertEqual(len(results), 2)
        observed = open_db(db_path)
        try:
            self.assertEqual(
                observed.conn.execute(
                    "SELECT COUNT(*) FROM goal WHERE concept_text='Concurrent'"
                ).fetchone()[0], 1)
            self.assertEqual(
                observed.conn.execute(
                    "SELECT COUNT(*) FROM research_series"
                    " WHERE research_key='S1-CONCURRENT'"
                ).fetchone()[0], 1)
        finally:
            observed.conn.close()
        self.assertEqual(sum(not result["reused"] for result in results), 1)


class TestWikiStagingLifecycle(unittest.TestCase):
    def test_stale_stage_is_one_actionable_issue_and_build_cleans_it(self):
        root = Path(tempfile.mkdtemp())
        db = open_db(root / "agentos.db")
        try:
            wb = WikiBuilder(db, root)
            wb.build()
            stale = wb.wiki / ".wiki-stage-crashed"
            stale.mkdir()
            (stale / "orphan.md").write_text("partial projection", encoding="utf-8")

            checked = wb.check()
            stage_issues = [i for i in checked["issues"]
                            if i["kind"] == "stale_staging_dir"]
            self.assertEqual(len(stage_issues), 1)
            self.assertEqual(stage_issues[0]["note"], ".wiki-stage-crashed")
            self.assertFalse(any(i["kind"] == "orphan_note"
                                 and "wiki-stage" in i["note"]
                                 for i in checked["issues"]))

            wb.build()
            self.assertFalse(stale.exists())
            self.assertTrue(wb.check()["ok"], wb.check())
        finally:
            db.conn.close()
            shutil.rmtree(root, ignore_errors=True)

    def test_concurrent_build_cannot_delete_active_staging(self):
        root = Path(tempfile.mkdtemp())
        db = open_db(root / "agentos.db")
        stage_ready = threading.Event()
        release_stage = threading.Event()
        created: list[Path] = []
        original_make_stage = WikiBuilder._make_staging_dir

        def paused_make_stage(instance):
            stage = original_make_stage(instance)
            created.append(stage)
            stage_ready.set()
            release_stage.wait(timeout=10)
            return stage

        worker_errors: list[BaseException] = []

        def run_first_build():
            worker_db = open_db(root / "agentos.db")
            try:
                WikiBuilder(worker_db, root).build()
            except BaseException as exc:
                worker_errors.append(exc)
            finally:
                worker_db.conn.close()

        try:
            with mock.patch.object(WikiBuilder, "_make_staging_dir",
                                   new=paused_make_stage):
                worker = threading.Thread(target=run_first_build)
                worker.start()
                self.assertTrue(stage_ready.wait(timeout=10))
                self.assertTrue(created[0].exists())
                second = WikiBuilder(db, root)
                with self.assertRaises(RuntimeError):
                    second.build()
                self.assertTrue(created[0].exists())
                release_stage.set()
                worker.join(timeout=30)
                self.assertFalse(worker.is_alive())
                self.assertEqual(worker_errors, [])
            self.assertFalse(created[0].exists())
        finally:
            release_stage.set()
            db.conn.close()
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
