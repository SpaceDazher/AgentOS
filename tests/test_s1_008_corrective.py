"""Corrective-round regression tests for the S1-008 evidence pipeline.

The tests in this module deliberately use temporary inputs for integrity
checks.  They must not rely on the checked-in historical evidence output or
on the repository's current git status.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
S1_DIR = REPO_ROOT / "research" / "tickets" / "stage-1" / "S1-008"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_module("s1_008_runner_corrective", S1_DIR / "runner.py")
make_bundle = _load_module("s1_008_make_bundle_corrective", S1_DIR / "make_bundle.py")
finalizer = _load_module("s1_008_finalizer_corrective", S1_DIR / "finalize_record.py")


class TestDirtyStatusParser(unittest.TestCase):
    def test_parser_preserves_both_porcelain_status_columns(self):
        self.assertTrue(runner._status_line_is_dirty(" M research/tickets/stage-1/S1-008/runner.py"))
        self.assertTrue(runner._status_line_is_dirty("M  research/tickets/stage-1/S1-008/runner.py"))
        self.assertTrue(runner._status_line_is_dirty(" D research/tickets/stage-1/S1-008/runner.py"))
        self.assertTrue(runner._status_line_is_dirty("R  research/tickets/stage-1/S1-008/old.py -> research/tickets/stage-1/S1-008/new.py"))
        self.assertTrue(runner._status_line_is_dirty("?? research/tickets/stage-1/S1-008/new-input.json"))

    def test_only_scoped_generated_outputs_are_ignored(self):
        self.assertFalse(runner._status_line_is_dirty("?? results/run-a-clean/raw-traces/trial.json"))
        self.assertFalse(runner._status_line_is_dirty(" M results/evidence/evidence-pack-old.json"))
        self.assertTrue(runner._status_line_is_dirty("?? results/unexpected-input.json"))


class TestRawTraceDigest(unittest.TestCase):
    def test_digest_changes_when_a_trace_changes_and_contains_members(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw-traces"
            raw.mkdir()
            (raw / "a.json").write_text('{"trial_id":"a","value":1}\n', encoding="utf-8")
            (raw / "b.json").write_text('{"trial_id":"b","value":2}\n', encoding="utf-8")
            first = make_bundle.raw_trace_digest(raw)
            self.assertEqual(first["member_count"], 2)
            self.assertEqual(len(first["members"]), 2)
            self.assertNotEqual(first["sha256"], "")
            (raw / "b.json").write_text('{"trial_id":"b","value":3}\n', encoding="utf-8")
            second = make_bundle.raw_trace_digest(raw)
            self.assertNotEqual(first["sha256"], second["sha256"])


class TestVerifyDbOwnership(unittest.TestCase):
    def _db(self, td: str):
        path = Path(td) / "agentos.db"
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE goal (id TEXT PRIMARY KEY);
            CREATE TABLE research_campaign (id TEXT PRIMARY KEY, goal_id TEXT NOT NULL);
            CREATE TABLE research_evaluation (
                id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, goal_id TEXT NOT NULL,
                result TEXT NOT NULL, artifact_chain_hash TEXT NOT NULL
            );
            CREATE TABLE research_series (
                id TEXT PRIMARY KEY, research_key TEXT NOT NULL, revision INTEGER NOT NULL,
                campaign_id TEXT NOT NULL, goal_id TEXT NOT NULL
            );
            """
        )
        conn.execute("INSERT INTO goal VALUES (?)", ("goal-1",))
        conn.execute("INSERT INTO research_campaign VALUES (?, ?)", ("camp-1", "goal-1"))
        conn.execute(
            "INSERT INTO research_evaluation VALUES (?, ?, ?, ?, ?)",
            ("eval-1", "camp-1", "goal-1", "pass_with_limits", "chain-1"),
        )
        conn.execute(
            "INSERT INTO research_series VALUES (?, ?, ?, ?, ?)",
            ("series-1", "S1-008", 14, "camp-1", "goal-1"),
        )
        conn.commit()
        conn.close()
        return path

    def test_exact_owner_result_and_chain_are_required(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            verified = finalizer.verify_db(
                "goal-1", "camp-1", "eval-1", "PASS_WITH_LIMITS", "chain-1", db
            )
            self.assertTrue(verified["fully_verified"])
            self.assertEqual(verified["research_revision"], 14)
            self.assertTrue(verified["series_campaign_match"])
            self.assertTrue(verified["series_goal_match"])
            for kwargs in (
                {"campaign_id": "camp-wrong"},
                {"bundle_chain": "chain-wrong"},
                {"eval_result": "FAIL"},
                {"goal_id": "goal-wrong"},
            ):
                args = {
                    "goal_id": "goal-1",
                    "campaign_id": "camp-1",
                    "evaluation_id": "eval-1",
                    "eval_result": "PASS_WITH_LIMITS",
                    "bundle_chain": "chain-1",
                    "db_path": db,
                }
                args.update(kwargs)
                self.assertFalse(finalizer.verify_db(**args)["fully_verified"], kwargs)

    def test_missing_or_cross_owned_series_is_not_verified(self):
        for mutation in ("delete", "cross_goal", "cross_campaign", "stale_revision"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                db = self._db(td)
                conn = sqlite3.connect(db)
                if mutation == "delete":
                    conn.execute("DELETE FROM research_series")
                elif mutation == "cross_goal":
                    conn.execute("UPDATE research_series SET goal_id='goal-other'")
                elif mutation == "cross_campaign":
                    conn.execute("UPDATE research_series SET campaign_id='camp-other'")
                else:
                    conn.execute("INSERT INTO research_series VALUES (?, ?, ?, ?, ?)",
                                 ("series-latest", "S1-008", 14, "camp-latest", "goal-latest"))
                    conn.execute("INSERT INTO research_series VALUES (?, ?, ?, ?, ?)",
                                 ("series-old", "S1-008", 13, "camp-old", "goal-old"))
                    conn.execute("UPDATE research_series SET revision=13 WHERE id='series-1'")
                conn.commit()
                conn.close()
                verified = finalizer.verify_db(
                    "goal-1", "camp-1", "eval-1", "PASS_WITH_LIMITS", "chain-1", db
                )
                self.assertFalse(verified["fully_verified"])


class TestPortableFinalizerPaths(unittest.TestCase):
    def test_repo_relative_paths_resolve_under_trusted_root(self):
        resolved = finalizer._resolve_repo_path("results/evidence/example.json")
        self.assertEqual(resolved, finalizer._REPO_ROOT / "results/evidence/example.json")

    def test_traversal_and_outside_absolute_paths_are_rejected(self):
        for value in ("../outside.json", "results/../outside.json",
                      Path(tempfile.gettempdir()) / "outside.json"):
            with self.subTest(value=str(value)):
                with self.assertRaises(finalizer.FinalizationError):
                    finalizer._resolve_repo_path(value)


class TestFailClosedFinalizer(unittest.TestCase):
    def test_fail_and_blocked_inputs_cannot_derive_positive_outcome(self):
        for evaluation, comparison in (
            ({"verdict": "FAIL"}, {"verdict": "PASS"}),
            ({"verdict": "PASS"}, {"verdict": "BLOCKED"}),
            ({}, {"verdict": "PASS"}),
            ({"verdict": "UNKNOWN"}, {"verdict": "PASS"}),
        ):
            with self.assertRaises(finalizer.FinalizationError):
                finalizer.derive_outcome({"evaluation": evaluation, "comparison": comparison})


if __name__ == "__main__":
    unittest.main()
