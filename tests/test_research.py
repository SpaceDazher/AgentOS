"""Offline adversarial checks for the bounded research planner."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentos.db import open_db  # noqa: E402
from agentos.evidence_pack import build as build_evidence  # noqa: E402
from agentos.research import (  # noqa: E402
    evaluate_research,
    fixture_bundle,
    research_chain_hash,
    run_research_plan,
)
import agentos.research as research_module  # noqa: E402
from agentos.wiki import WikiBuilder  # noqa: E402


class TestResearchPlanner(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.db = open_db(self.root / "agentos.db")

    def tearDown(self):
        self.db.conn.close()

    def test_offline_fixture_passes_and_persists_dag(self):
        result = run_research_plan(
            self.db, self.root, "Offline fixture topic", fixture_bundle())
        self.assertEqual(result["status"], "pass", result)
        self.assertEqual(
            [r[0] for r in self.db.conn.execute(
                "SELECT title FROM task WHERE goal_id=? ORDER BY rowid",
                (result["goal_id"],))],
            ["research_plan", "source_registry", "feature_catalog",
             "architecture_models", "mental_model", "ontology",
             "mathematical_model", "synthesis_and_gaps", "independent_audit",
             "platform_plan", "progress"],
        )
        for row in self.db.conn.execute(
                "SELECT storage_path, content_sha256 FROM research_artifact"
                " WHERE goal_id=?", (result["goal_id"],)):
            p = Path(row[0])
            self.assertTrue(str(p).startswith(
                str(self.root / "goals" / result["goal_id"] / "research")))
            self.assertEqual(
                __import__("hashlib").sha256(p.read_bytes()).hexdigest(),
                row[1],
            )
        self.assertEqual(result["evidence_pack"]["schema"],
                         "agentos.evidence-pack/v3")
        evidence_path = Path(result["evidence_pack"]["path"])
        self.assertTrue(evidence_path.is_file())
        file_sha = __import__("hashlib").sha256(
            evidence_path.read_bytes()).hexdigest()
        self.assertEqual(result["evidence_pack"]["sha256"], file_sha)
        self.assertEqual(result["evidence_pack"]["file_sha256"], file_sha)
        self.assertNotEqual(
            result["evidence_pack"]["payload_sha256"], file_sha)
        self.assertTrue(result["wiki"]["check"]["ok"], result["wiki"])

    def test_invalid_uri_and_sha_fail_closed(self):
        bundle = fixture_bundle()
        bundle["sources"][0]["canonical_uri"] = "not a uri"
        bundle["sources"][0]["content_sha256"] = "bad"
        result = run_research_plan(self.db, self.root, "bad", bundle)
        self.assertEqual(result["status"], "fail")
        self.assertTrue(any("URI" in x or "SHA" in x
                            for x in result["next_actions"]))

    def test_raw_cross_goal_links_are_rejected(self):
        first = run_research_plan(
            self.db, self.root, "One", fixture_bundle())
        second = run_research_plan(
            self.db, self.root, "Two", fixture_bundle())
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.conn.execute(
                "INSERT INTO research_claim_source(claim_id, source_id, goal_id)"
                " VALUES (?,?,?)", (
                    first["claims"][0]["id"], second["sources"][0]["id"],
                    first["goal_id"],
                ))

    def test_artifacts_and_evaluations_are_append_only(self):
        result = run_research_plan(
            self.db, self.root, "Immutable", fixture_bundle())
        aid = result["artifacts"][0]["id"]
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.conn.execute(
                "UPDATE research_artifact SET producer='changed' WHERE id=?",
                (aid,))
        eid = result["evaluation"]["id"]
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.conn.execute(
                "DELETE FROM research_evaluation WHERE id=?", (eid,))

    def test_adversarial_evaluation_requirements_fail_closed(self):
        cases = []
        bundle = fixture_bundle()
        bundle["sources"][0]["canonical_uri"] = bundle["sources"][1]["canonical_uri"]
        cases.append((bundle, "duplicate canonical source"))
        bundle = fixture_bundle()
        bundle["sources"][0]["verification_method"] = ""
        cases.append((bundle, "provenance"))
        bundle = fixture_bundle()
        bundle["claims"][0]["source_ids"] = []
        cases.append((bundle, "verified same-goal source"))
        bundle = fixture_bundle()
        bundle["sources"][0]["verification_status"] = "unverified"
        cases.append((bundle, "verified source ratio"))
        bundle = fixture_bundle()
        bundle["audit"]["producer"] = bundle["audit"]["auditor"]
        cases.append((bundle, "auditor"))
        bundle = fixture_bundle()
        bundle["audit"]["verdict"] = "pass_with_limits"
        cases.append((bundle, "limitations"))
        bundle = fixture_bundle()
        bundle["artifacts"]["platform_plan"]["content"] = "# Scope\nonly"
        cases.append((bundle, "platform_plan"))
        for candidate, expected in cases:
            result = run_research_plan(self.db, self.root, expected, candidate)
            self.assertEqual(result["status"], "fail", (expected, result))
            self.assertTrue(any(expected.lower() in str(item).lower()
                                or "source" in str(item).lower()
                                for item in result["next_actions"]),
                            (expected, result))

    def test_evidence_and_wiki_are_goal_scoped_and_redacted(self):
        first_bundle = fixture_bundle()
        first_bundle["sources"][0]["title"] = "api key = TOPSECRET"
        first = run_research_plan(self.db, self.root, "first", first_bundle)
        second = run_research_plan(self.db, self.root, "second", fixture_bundle())
        first_pack = build_evidence(self.db, self.root, first["goal_id"])["pack"]
        self.assertEqual(first_pack["schema"], "agentos.evidence-pack/v3")
        self.assertEqual({s["id"] for s in first_pack["research"]["sources"]},
                         {s["id"] for s in first["sources"]})
        self.assertNotIn(second["goal_id"], json.dumps(first_pack))
        wiki = WikiBuilder(self.db, self.root)
        wiki.build()
        self.assertTrue(wiki.check()["ok"])
        source_notes = list((self.root / "wiki" / "_generated").glob(
            "research-source-*.md"))
        self.assertTrue(source_notes)
        self.assertTrue(all("TOPSECRET" not in p.read_text(encoding="utf-8")
                            for p in source_notes))

    def test_latest_schema_upgrade_preserves_existing_goal(self):
        migration_dir = ROOT / "src" / "agentos" / "migrations"
        db_path = self.root / "upgrade.db"
        conn = sqlite3.connect(db_path)
        migration_names = [p.name for p in sorted(migration_dir.glob("*.sql"))
                           if p.name != "0013_research_platform_plan.sql"]
        for name in migration_names:
            conn.executescript((migration_dir / name).read_text(encoding="utf-8"))
        conn.execute(
            "CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, "
            "applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        conn.executemany("INSERT INTO schema_migrations(name) VALUES (?)",
                         [(name,) for name in migration_names])
        conn.execute("INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
                     ("goal_UPGRADE", "preserve", "ACTIVE"))
        conn.commit()
        conn.close()
        upgraded = open_db(db_path)
        self.assertEqual(upgraded.conn.execute(
            "SELECT concept_text FROM goal WHERE id='goal_UPGRADE'"
        ).fetchone()[0], "preserve")
        self.assertEqual(upgraded.conn.execute(
            "SELECT COUNT(*) FROM research_campaign"
        ).fetchone()[0], 0)
        upgraded.conn.close()

    def test_bundle_thresholds_cannot_reward_hack_authority(self):
        bundle = fixture_bundle()
        bundle["config"] = {"min_source_count": 1,
                             "min_verified_ratio": 0.0,
                             "required_artifacts": []}
        bundle["sources"] = bundle["sources"][:1]
        for claim in bundle["claims"]:
            claim["source_ids"] = ["fixture-source-1"] if claim["claim_class"] == "fact" else []
        result = run_research_plan(self.db, self.root, "authority", bundle)
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(any("minimum" in action.lower()
                            or "required_artifacts" in action.lower()
                            for action in result["next_actions"]))

    def test_trusted_config_can_only_tighten_numeric_thresholds(self):
        result = run_research_plan(
            self.db, self.root, "tighten", fixture_bundle(),
            {"min_source_count": 4})
        self.assertEqual(result["status"], "fail", result)
        self.assertIn("minimum 4", " ".join(result["evaluation"]["reasons"]))

    def test_claims_and_substantive_artifact_traceability_are_required(self):
        bundle = fixture_bundle()
        bundle["claims"] = []
        for artifact in bundle["artifacts"].values():
            artifact["claim_refs"] = []
        result = run_research_plan(self.db, self.root, "traceability", bundle)
        self.assertEqual(result["status"], "fail", result)
        reasons = " ".join(result["evaluation"]["reasons"])
        self.assertIn("claim", reasons.lower())

    def test_factual_claim_cannot_mix_unverified_support(self):
        bundle = fixture_bundle()
        bundle["claims"][0]["source_ids"] = ["fixture-source-1", "fixture-source-2"]
        bundle["sources"][1]["verification_status"] = "unverified"
        result = run_research_plan(self.db, self.root, "exclusive facts", bundle)
        self.assertEqual(result["status"], "fail", result)
        self.assertIn("unverified", " ".join(result["evaluation"]["reasons"]).lower())

    def test_manifest_is_host_asserted_not_user_authority(self):
        bundle = fixture_bundle()
        bundle["manifest_sha256"] = "0" * 64
        result = run_research_plan(self.db, self.root, "manifest", bundle)
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(any("manifest" in action.lower()
                            for action in result["next_actions"]))

    def test_audit_identities_bind_to_artifact_producers(self):
        bundle = fixture_bundle()
        bundle["audit"] = {"producer": "alice", "auditor": "bob",
                           "verdict": "pass", "limitations": []}
        result = run_research_plan(self.db, self.root, "audit binding", bundle)
        self.assertEqual(result["status"], "fail", result)
        self.assertIn("producer", " ".join(result["evaluation"]["reasons"]).lower())

    def test_pass_with_limits_remains_distinct_success_result(self):
        bundle = fixture_bundle()
        bundle["audit"]["verdict"] = "pass_with_limits"
        bundle["audit"]["limitations"] = ["offline fixture only"]
        result = run_research_plan(self.db, self.root, "limited", bundle)
        self.assertEqual(result["status"], "pass_with_limits", result)
        self.assertEqual(result["evaluation"]["result"], "pass_with_limits")

    def test_artifact_file_state_changes_chain_and_stales_evidence(self):
        result = run_research_plan(self.db, self.root, "tamper", fixture_bundle())
        before = research_chain_hash(self.db, result["goal_id"])
        artifact_path = Path(result["artifacts"][0]["storage_path"])
        artifact_path.write_text("tampered", encoding="utf-8")
        after = research_chain_hash(self.db, result["goal_id"])
        self.assertNotEqual(before, after)
        before_eval = build_evidence(self.db, self.root, result["goal_id"])["pack"]
        self.assertFalse(before_eval["research"]["chain_fresh"])
        self.assertFalse(before_eval["research"]["latest_evaluation_valid"])
        evaluation = evaluate_research(self.db, result["goal_id"])
        self.assertEqual(evaluation["result"], "fail")
        pack = build_evidence(self.db, self.root, result["goal_id"])["pack"]
        self.assertTrue(pack["research"]["chain_fresh"])
        self.assertFalse(pack["research"]["latest_evaluation_valid"])

    def test_reevaluation_preserves_untampered_pass(self):
        result = run_research_plan(self.db, self.root, "reeval pass", fixture_bundle())
        evaluation = evaluate_research(self.db, result["goal_id"])
        self.assertEqual(evaluation["result"], "pass", evaluation)

    def test_reevaluation_preserves_untampered_limited_pass(self):
        bundle = fixture_bundle()
        bundle["audit"]["verdict"] = "pass_with_limits"
        bundle["audit"]["limitations"] = ["offline fixture only"]
        result = run_research_plan(self.db, self.root, "reeval limited", bundle)
        evaluation = evaluate_research(self.db, result["goal_id"])
        self.assertEqual(evaluation["result"], "pass_with_limits", evaluation)

    def test_non_utf8_platform_plan_fails_re_evaluation(self):
        result = run_research_plan(self.db, self.root, "bad platform bytes", fixture_bundle())
        plan = next(a for a in result["artifacts"] if a["kind"] == "platform_plan")
        Path(plan["storage_path"]).write_bytes(b"\xff\xfe")
        evaluation = evaluate_research(self.db, result["goal_id"])
        self.assertEqual(evaluation["result"], "fail", evaluation)
        self.assertTrue(any("platform_plan" in reason
                            for reason in evaluation["reasons"]))

    def test_fact_support_requires_support_relation(self):
        for relation in ("context", "contradicts"):
            result = run_research_plan(
                self.db, self.root, f"relation {relation}", fixture_bundle())
            source = self.db.conn.execute(
                "SELECT id FROM research_source WHERE goal_id=? ORDER BY id LIMIT 1",
                (result["goal_id"],)).fetchone()[0]
            campaign = self.db.conn.execute(
                "SELECT id FROM research_campaign WHERE goal_id=?",
                (result["goal_id"],)).fetchone()[0]
            claim_id = f"raw-{relation}"
            self.db.conn.execute(
                "INSERT INTO research_claim(id,campaign_id,goal_id,text,claim_class)"
                " VALUES (?,?,?,?,?)",
                (claim_id, campaign, result["goal_id"],
                 f"raw {relation} claim", "fact"),
            )
            self.db.conn.execute(
                "INSERT INTO research_claim_source(claim_id,source_id,goal_id,relation)"
                " VALUES (?,?,?,?)",
                (claim_id, source, result["goal_id"], relation),
            )
            evaluation = evaluate_research(self.db, result["goal_id"])
            self.assertEqual(evaluation["result"], "fail", evaluation)
            self.assertTrue(any("supports relation" in reason
                                for reason in evaluation["reasons"]))

    def test_external_input_limits_fail_closed_for_mapping_and_file(self):
        bundle = fixture_bundle()
        with mock.patch.object(research_module, "MAX_SOURCES", 2):
            bundle["sources"] = bundle["sources"][:2] + [{}]
            result = run_research_plan(self.db, self.root, "too many sources", bundle)
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(any("source limit" in action.lower()
                            for action in result["next_actions"]))

        bundle = fixture_bundle()
        with mock.patch.object(research_module, "MAX_BODY_BYTES", 8):
            bundle["sources"][0]["content"] = "123456789"
            result = run_research_plan(self.db, self.root, "large source", bundle)
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(any("body" in action.lower()
                            for action in result["next_actions"]))

        bundle = fixture_bundle()
        with mock.patch.object(research_module, "MAX_BUNDLE_FILE_BYTES", 8):
            path = self.root / "oversized-bundle.json"
            path.write_bytes(b"123456789")
            result = run_research_plan(self.db, self.root, "large file", path)
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(any("bundle file" in action.lower()
                            for action in result["next_actions"]))

        with mock.patch.object(research_module, "MAX_BUNDLE_FILE_BYTES", 8):
            result = run_research_plan(
                self.db, self.root, "large mapping", fixture_bundle())
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(any("mapping" in action.lower()
                            for action in result["next_actions"]))

        bundle = fixture_bundle()
        with mock.patch.object(research_module, "MAX_CLAIMS", 2):
            result = run_research_plan(self.db, self.root, "too many claims", bundle)
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(any("claim limit" in action.lower()
                            for action in result["next_actions"]))

        bundle = fixture_bundle()
        with mock.patch.object(research_module, "MAX_BODY_BYTES", 8):
            bundle["artifacts"]["platform_plan"]["content"] = "123456789"
            result = run_research_plan(self.db, self.root, "large artifact", bundle)
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(any("artifact platform_plan body" in action.lower()
                            for action in result["next_actions"]))

    def test_external_input_text_and_uri_limits_fail_closed(self):
        bundle = fixture_bundle()
        with mock.patch.object(research_module, "MAX_URI_CHARS", 8):
            bundle["sources"][0]["canonical_uri"] = "https://x.test"
            result = run_research_plan(self.db, self.root, "long uri", bundle)
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(any("URI" in action for action in result["next_actions"]))

        bundle = fixture_bundle()
        with mock.patch.object(research_module, "MAX_CLAIM_TEXT_CHARS", 8):
            bundle["claims"][0]["text"] = "123456789"
            result = run_research_plan(self.db, self.root, "long claim", bundle)
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(any("claim" in action.lower()
                            for action in result["next_actions"]))

        bundle = fixture_bundle()
        with mock.patch.object(research_module, "MAX_SOURCE_TITLE_CHARS", 8):
            bundle["sources"][0]["title"] = "123456789"
            result = run_research_plan(self.db, self.root, "long title", bundle)
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(any("title" in action.lower()
                            for action in result["next_actions"]))

        bundle = fixture_bundle()
        with mock.patch.object(research_module, "MAX_SOURCE_TYPE_CHARS", 2):
            bundle["sources"][0]["source_type"] = "abc"
            result = run_research_plan(self.db, self.root, "long source type", bundle)
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(any("source type" in action.lower()
                            for action in result["next_actions"]))

    def test_raw_sql_case_variant_uri_is_unique_within_goal(self):
        result = run_research_plan(self.db, self.root, "uri case", fixture_bundle())
        source = self.db.conn.execute(
            "SELECT * FROM research_source WHERE goal_id=? ORDER BY id LIMIT 1",
            (result["goal_id"],)).fetchone()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.conn.execute(
                "INSERT INTO research_source(id,campaign_id,goal_id,canonical_uri,"
                "title,source_type,content_sha256,verification_status,verifier,"
                "verification_method) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("rsrc_CASE", source["campaign_id"], result["goal_id"],
                 "https://" + source["canonical_uri"].split("://", 1)[1].upper(),
                 "case", "fixture",
                 source["content_sha256"], "verified", "v", "m"),
            )

    def test_raw_cross_goal_artifact_claim_link_is_rejected(self):
        first = run_research_plan(self.db, self.root, "artifact one", fixture_bundle())
        second = run_research_plan(self.db, self.root, "artifact two", fixture_bundle())
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.conn.execute(
                "INSERT INTO research_artifact_claim(artifact_id,claim_id,goal_id)"
                " VALUES (?,?,?)", (first["artifacts"][0]["id"],
                                     second["claims"][0]["id"], first["goal_id"]))

    def test_sources_claims_and_links_are_append_only(self):
        result = run_research_plan(self.db, self.root, "append only", fixture_bundle())
        source_id = result["sources"][0]["id"]
        claim_id = result["claims"][0]["id"]
        link = self.db.conn.execute(
            "SELECT claim_id,source_id,goal_id FROM research_claim_source"
            " WHERE goal_id=? LIMIT 1", (result["goal_id"],)).fetchone()
        for sql, args in (
            ("UPDATE research_source SET title='x' WHERE id=?", (source_id,)),
            ("DELETE FROM research_claim WHERE id=?", (claim_id,)),
            ("DELETE FROM research_claim_source WHERE claim_id=? AND source_id=?",
             (link["claim_id"], link["source_id"])),
        ):
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.conn.execute(sql, args)

    def test_unsupported_bundle_type_returns_structured_failure(self):
        result = run_research_plan(self.db, self.root, "bad type", 123)
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(result["next_actions"])

    def test_wiki_research_object_ownership_is_checked(self):
        first = run_research_plan(self.db, self.root, "owner one", fixture_bundle())
        second = run_research_plan(self.db, self.root, "owner two", fixture_bundle())
        wiki = WikiBuilder(self.db, self.root)
        wiki.build()
        note = self.root / "wiki" / "_generated" / (
            f"research-source-{first['sources'][0]['id']}.md")
        text = note.read_text(encoding="utf-8")
        note.write_text(text.replace(f'goal_id: "{first["goal_id"]}"',
                                     f'goal_id: "{second["goal_id"]}"'),
                        encoding="utf-8")
        checked = wiki.check()
        self.assertFalse(checked["ok"])
        self.assertTrue(any(i["kind"] == "ownership_mismatch"
                            for i in checked["issues"]))

    def test_platform_sections_need_substantive_content(self):
        bundle = fixture_bundle()
        bundle["artifacts"]["platform_plan"]["content"] = "\n".join(
            f"# {section}\nx" for section in (
                "Scope", "Architecture", "Workstreams", "Milestones",
                "Verification", "Risks", "Open decisions"))
        result = run_research_plan(self.db, self.root, "thin plan", bundle)
        self.assertEqual(result["status"], "fail", result)
        self.assertIn("substantive", " ".join(result["evaluation"]["reasons"]).lower())


if __name__ == "__main__":
    unittest.main()
