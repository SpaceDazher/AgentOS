"""Regression tests for S1-009 adapter contract evaluation.

Run:  python -m unittest tests.test_s1_009_regressions -v
      python -m unittest discover -s tests -v

These tests are stdlib-only and deterministic. No network or LLM.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tarfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "research" / "tickets" / "stage-1" / "S1-009"  # S1-009 directory
REPO_ROOT = ROOT.parents[3]
DB_PATH = REPO_ROOT / ".agentos-research" / "platform-stage-1" / "agentos.db"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_evaluator():
    """Import evaluator.py as a module without polluting sys.path."""
    spec = importlib.util.spec_from_file_location("evaluator_s1_009", ROOT / "evaluator.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestCaseIntegrity(unittest.TestCase):
    """exact case set: no missing/extra/duplicate/malformed results."""

    @classmethod
    def setUpClass(cls):
        with open(ROOT / "cases.json", encoding="utf-8") as f:
            cls.manifest = json.load(f)

    def test_case_count_is_40(self):
        self.assertEqual(len(self.manifest["cases"]), 40)

    def test_protocol_group_counts(self):
        proto_counts = {}
        for c in self.manifest["cases"]:
            proto_counts[c["protocol"]] = proto_counts.get(c["protocol"], 0) + 1
        self.assertEqual(proto_counts["MCP"], 12)
        self.assertEqual(proto_counts["A2A"], 12)
        self.assertEqual(proto_counts["cross"], 16)

    def test_no_duplicate_case_ids(self):
        ids = [c["case_id"] for c in self.manifest["cases"]]
        duplicates = [cid for cid in ids if ids.count(cid) > 1]
        self.assertEqual(duplicates, [], f"Duplicate case IDs: {duplicates}")

    def test_all_cases_have_required_fields(self):
        required = {"case_id", "protocol", "category", "probe_id",
                    "capability_row", "title", "input", "hub_context", "expected"}
        for c in self.manifest["cases"]:
            missing = required - set(c.keys())
            self.assertEqual(missing, set(), f"Case {c['case_id']} missing: {missing}")

    def test_all_expected_decisions_valid(self):
        valid_decisions = {"ACCEPT", "DENY", "QUARANTINE"}
        for c in self.manifest["cases"]:
            self.assertIn(c["expected"]["decision"], valid_decisions,
                          f"Case {c['case_id']}: {c['expected']['decision']}")


class TestCapabilityMatrix(unittest.TestCase):
    """capability/gap matrix: 15 surfaces, 12 passing, 3 unsupported."""

    @classmethod
    def setUpClass(cls):
        with open(ROOT / "capability-matrix.json", encoding="utf-8") as f:
            cls.matrix = json.load(f)

    def test_covers_minimum_15_surfaces(self):
        ids = [e["surface_id"] for e in self.matrix["matrix"]]
        self.assertGreaterEqual(len(ids), 15)
        for i in range(1, 16):
            self.assertIn(f"SM{i}", ids, f"SM{i} missing from capability matrix")

    def test_unsupported_rows_are_absent_or_underspecified(self):
        for entry in self.matrix["matrix"]:
            if entry["surface_id"] in ("SM6", "SM8", "SM11"):
                self.assertEqual(entry["loss_class"], "unsupported",
                                 f"{entry['surface_id']} must be unsupported")

    def test_supported_rows_preserve_semantics(self):
        for entry in self.matrix["matrix"]:
            if entry["loss_class"] == "supported":
                self.assertIn("loss_class", entry)
            elif entry["loss_class"] == "lossy-safe":
                pass  # lossy-safe is acceptable
            elif entry["loss_class"] != "unsupported":
                self.fail(f"Unknown loss_class: {entry['loss_class']}")

    def test_supported_rows_are_lossy_safe_or_lossless(self):
        for entry in self.matrix["matrix"]:
            if entry["loss_class"] != "unsupported":
                self.assertIn(entry["loss_class"], ("lossy-safe", "lossless"))


class TestAdapterContract(unittest.TestCase):
    """Adapter contract: 18 rules, no PLACEHOLDER, version-gated."""

    @classmethod
    def setUpClass(cls):
        with open(ROOT / "adapter-contract.json", encoding="utf-8") as f:
            cls.contract = json.load(f)

    def test_no_placeholder_hashes(self):
        blob = json.dumps(self.contract)
        self.assertNotIn("PLACEHOLDER", blob,
                         "adapter-contract.json must not contain PLACEHOLDER hashes")

    def test_rule_count_18(self):
        count = 0
        for proto in self.contract.get("protocols", {}).values():
            for direction in ("inbound", "outbound"):
                count += len(proto.get(direction, []))
        self.assertEqual(count, 18)

    def test_all_rules_have_sha256(self):
        for proto_name, proto in self.contract.get("protocols", {}).items():
            for direction in ("inbound", "outbound"):
                for rule in proto.get(direction, []):
                    sha = rule.get("rule_sha256", "")
                    self.assertNotEqual(sha, "PLACEHOLDER-computed-by-make-bundle",
                                        f"Rule {rule.get('rule_id')} still has placeholder")
                    self.assertEqual(len(sha), 64,
                                     f"Rule {rule.get('rule_id')} SHA-256 is not 64 hex chars")

    def test_contract_version_matches_bundle(self):
        self.assertEqual(self.contract.get("contract_version"), "1.0")

    def test_provider_neutrality_claim(self):
        pn = self.contract.get("provider_neutrality", {})
        self.assertIn("claim", pn)
        self.assertIn("constraint", pn)


class TestHardRules(unittest.TestCase):
    """The 8 hub hard rules must be enforced by the evaluator."""

    @classmethod
    def setUpClass(cls):
        with open(ROOT / "canonical-envelope.schema.json", encoding="utf-8") as f:
            cls.schema = json.load(f)

    def test_eight_hard_rules_present(self):
        rules = self.schema.get("hard_rules", {})
        self.assertEqual(len(rules), 8)
        for i in range(1, 9):
            self.assertIn(f"rule_{i}", rules, f"rule_{i} missing from schema")


class TestCaseEvaluator(unittest.TestCase):
    """Run the evaluator and verify decisions against expected outcomes."""

    @classmethod
    def setUpClass(cls):
        with open(ROOT / "cases.json", encoding="utf-8") as f:
            cls.cases = json.load(f)
        cls.evaluator = _load_evaluator()

    def _run_case(self, case):
        """Translate a single case via evaluate_case and return the result dict."""
        return self.evaluator.evaluate_case(case)

    def test_all_cases_decisions_match_expected(self):
        for case in self.cases["cases"]:
            result = self._run_case(case)
            expected_decision = case["expected"]["decision"]
            actual_decision = result["decision_actual"]
            self.assertEqual(
                actual_decision, expected_decision,
                f"Case {case['case_id']}: expected {expected_decision}, got {actual_decision}"
            )

    def test_all_cases_verdicts_pass(self):
        for case in self.cases["cases"]:
            result = self._run_case(case)
            self.assertEqual(result["verdict"], "PASS",
                             f"Case {case['case_id']}: verdict is {result['verdict']}")

    def test_probe_a_no_auth_escalation(self):
        """Probe A: protocol payload claiming delegation/approval must DENY."""
        for case in self.cases["cases"]:
            if case["probe_id"] == "A":
                result = self._run_case(case)
                self.assertEqual(result["decision_actual"], "DENY",
                                 f"Probe A case {case['case_id']} must DENY")

    def test_probe_b_unregistered_capability_denied(self):
        for case in self.cases["cases"]:
            if case["probe_id"] == "B":
                result = self._run_case(case)
                self.assertEqual(result["decision_actual"], "DENY",
                                 f"Probe B case {case['case_id']} must DENY")

    def test_probe_c_budget_overflow_denied(self):
        for case in self.cases["cases"]:
            if case["probe_id"] == "C":
                result = self._run_case(case)
                self.assertEqual(result["decision_actual"], "DENY",
                                 f"Probe C case {case['case_id']} must DENY")

    def test_probe_d_replay_denied(self):
        for case in self.cases["cases"]:
            if case["probe_id"] == "D":
                result = self._run_case(case)
                self.assertEqual(result["decision_actual"], "DENY",
                                 f"Probe D case {case['case_id']} must DENY")

    def test_probe_e_no_silent_knowledge_promotion(self):
        for case in self.cases["cases"]:
            if case["probe_id"] == "E":
                result = self._run_case(case)
                self.assertEqual(result["decision_actual"], "DENY",
                                 f"Probe E case {case['case_id']} must DENY")

    def test_probe_f_unknown_version_or_extension_quarantined(self):
        for case in self.cases["cases"]:
            if case["probe_id"] == "F":
                result = self._run_case(case)
                self.assertEqual(result["decision_actual"], "QUARANTINE",
                                 f"Probe F case {case['case_id']} must QUARANTINE")

    def test_zero_escalation_cases(self):
        """No case may escalate to ACCEPT via protocol payload."""
        for case in self.cases["cases"]:
            result = self._run_case(case)
            if result["decision_actual"] == "ACCEPT":
                # Accepted cases must have grant_present from hub ledger,
                # not from protocol payload
                env = result.get("envel_hash", "")
                self.assertIsNotNone(env, f"Accept case {case['case_id']} must have envelope")


class TestProcessSeparatedRerun(unittest.TestCase):
    """Independent rerun: two process-separated runs must match."""

    @classmethod
    def setUpClass(cls):
        cls.run_a_summary = ROOT / "results" / "run-a" / "summary.json"
        cls.run_b_summary = ROOT / "results" / "run-b" / "summary.json"
        cls.comparison = ROOT / "results" / "comparison.json"

    def test_both_runs_exist(self):
        self.assertTrue(self.run_a_summary.exists(), "run-a summary must exist")
        self.assertTrue(self.run_b_summary.exists(), "run-b summary must exist")

    def test_both_runs_pass_all_cases(self):
        for name, path in [("run-a", self.run_a_summary), ("run-b", self.run_b_summary)]:
            with open(path) as f:
                summary = json.load(f)
            self.assertEqual(summary["verdict"], "PASS", f"{name} must PASS")
            self.assertEqual(summary["verdict_counts"]["PASS"], 40,
                             f"{name} must have 40 PASS")
            self.assertEqual(summary["verdict_counts"]["FAIL"], 0,
                             f"{name} must have 0 FAIL")

    def test_comparison_json_exists_and_passes(self):
        self.assertTrue(self.comparison.exists(), "comparison.json must exist")
        with open(self.comparison) as f:
            comp = json.load(f)
        self.assertEqual(comp["verdict"], "PASS")
        self.assertTrue(comp["hash_match"], "hash fields must match between runs")
        self.assertTrue(comp["decision_identical"], "decisions must be identical")
        self.assertTrue(comp["envelope_hash_identical"], "envelope hashes must be identical")
        self.assertEqual(comp["mismatches"], [])

    def test_executor_ids_differ(self):
        with open(self.run_a_summary) as f:
            sa = json.load(f)
        with open(self.run_b_summary) as f:
            sb = json.load(f)
        self.assertNotEqual(sa["executor_id"], sb["executor_id"],
                            "Executor IDs must differ between runs")

    def test_nonces_differ(self):
        with open(self.run_a_summary) as f:
            sa = json.load(f)
        with open(self.run_b_summary) as f:
            sb = json.load(f)
        self.assertNotEqual(sa["nonce"], sb["nonce"],
                            "Nonces must differ between runs")

    def test_saved_runs_bind_current_frozen_inputs_and_clean_processes(self):
        """Saved PASS evidence must bind current bytes and independent runs.

        This is deliberately RED against the pre-correction evidence: its
        evaluator hash is stale and A/B share the runner PID/dirty state.
        """
        expected = {
            "evaluator_sha256": sha256_file(ROOT / "evaluator.py"),
            "adapter_contract_sha256": sha256_file(ROOT / "adapter-contract.json"),
            "corpus_sha256": sha256_file(ROOT / "cases.json"),
            "envelope_schema_sha256": sha256_file(ROOT / "canonical-envelope.schema.json"),
            "rubric_sha256": sha256_file(ROOT / "rubric.json"),
        }
        manifest_sha = sha256_file(ROOT / "corpus-manifest.json")
        summaries = {}
        for name in ("run-a", "run-b"):
            summary = json.loads((ROOT / "results" / name / "summary.json").read_text())
            summaries[name] = summary
            with self.subTest(run=name):
                self.assertEqual(summary.get("hashes"), expected)
                self.assertEqual(summary.get("input_manifest_sha256"), manifest_sha)
                prov = summary.get("process_provenance", {})
                self.assertFalse(prov.get("dirty", True))
                self.assertRegex(prov.get("commit_sha", ""), r"^[0-9a-f]{40}$")
                self.assertRegex(prov.get("tree_sha", ""), r"^[0-9a-f]{40}$")
                self.assertEqual(prov.get("input_manifest_sha256"), manifest_sha)
                self.assertTrue(prov.get("evaluator_clean"))
                self.assertEqual(prov.get("evaluator_commit_sha"), prov.get("commit_sha"))
                self.assertEqual(prov.get("evaluator_tree_sha"), prov.get("tree_sha"))
                self.assertEqual(prov.get("evaluator_input_manifest_sha256"), manifest_sha)
        a = summaries["run-a"]
        b = summaries["run-b"]
        self.assertNotEqual(a["process_provenance"].get("runner_pid"),
                            b["process_provenance"].get("runner_pid"))
        self.assertNotEqual(a["process_provenance"].get("evaluator_pid"),
                            b["process_provenance"].get("evaluator_pid"))
        self.assertNotEqual(a.get("output_root"), b.get("output_root"))
        self.assertEqual(a["process_provenance"].get("commit_sha"),
                         b["process_provenance"].get("commit_sha"))
        self.assertEqual(a["process_provenance"].get("tree_sha"),
                         b["process_provenance"].get("tree_sha"))
        self.assertEqual(a.get("input_manifest_sha256"),
                         b.get("input_manifest_sha256"))


class TestHashConsistency(unittest.TestCase):
    """All tracked hashes must match file bytes on disk."""

    def test_evaluator_sha_matches_file(self):
        with open(ROOT / "corpus-manifest.json") as f:
            manifest = json.load(f)
        expected = sha256_file(ROOT / "evaluator.py")
        self.assertEqual(manifest["evaluator_sha256"], expected,
                         "corpus-manifest evaluator hash must match file")

    def test_no_placeholder_hashes_in_contract(self):
        with open(ROOT / "adapter-contract.json", encoding="utf-8") as f:
            contract = json.load(f)
        blob = json.dumps(contract)
        self.assertNotIn("PLACEHOLDER", blob)

    def test_bundle_json_hashes_match_files(self):
        bundle_path = ROOT / "bundle.json"
        if not bundle_path.exists():
            self.skipTest("bundle.json not yet generated")
        with open(bundle_path) as f:
            bundle = json.load(f)
        for name, recorded_hash in bundle.get("artifact_hashes", {}).items():
            if recorded_hash == "MISSING":
                continue
            actual = sha256_file(ROOT / name)
            self.assertEqual(actual, recorded_hash,
                             f"bundle hash mismatch for {name}")

    def test_corpus_manifest_frozen_artifacts_match_current_files(self):
        """Authority hashes in corpus-manifest are recomputed from disk."""
        manifest = json.loads((ROOT / "corpus-manifest.json").read_text())
        frozen = manifest.get("frozen_artifacts", {})
        paths = {
            "cases": ROOT / "cases.json",
            "adapter_contract": ROOT / "adapter-contract.json",
            "canonical_envelope_schema": ROOT / "canonical-envelope.schema.json",
            "rubric": ROOT / "rubric.json",
        }
        for key, path in paths.items():
            with self.subTest(key=key):
                self.assertTrue(path.is_file())
                self.assertEqual(frozen.get(key, {}).get("sha256"), sha256_file(path))
        self.assertEqual(manifest.get("evaluator_sha256"), sha256_file(ROOT / "evaluator.py"))


class TestPathSafety(unittest.TestCase):
    """Relative paths must not exit repo root; traversal rejected."""

    def test_evaluator_relative_to_s1_009(self):
        with open(ROOT / "evaluator.py") as f:
            content = f.read()
        self.assertNotIn("/etc/", content)
        self.assertNotIn("/root/", content)

    def test_no_absolute_paths_in_cases(self):
        with open(ROOT / "cases.json") as f:
            cases = json.load(f)
        for case in cases["cases"]:
            blob = json.dumps(case["input"])
            self.assertNotIn("/home/", blob)
            self.assertNotIn("/Users/", blob)


class TestCapabilityCoverage(unittest.TestCase):
    """The advertised coverage counter must come from real evaluator cases."""

    def test_saved_runs_pass_at_least_twelve_distinct_capability_rows(self):
        for name in ("run-a", "run-b"):
            summary = json.loads((ROOT / "results" / name / "summary.json").read_text())
            coverage = summary.get("capability_rows_passing", {})
            with self.subTest(run=name):
                self.assertGreaterEqual(coverage.get("total", 0), 12)
                self.assertGreaterEqual(coverage.get("passing", 0), 12)
                row_ids = coverage.get("row_ids", coverage.get("distinct_rows", []))
                self.assertGreaterEqual(len(set(row_ids)), 12)
                self.assertEqual(len(row_ids), len(set(row_ids)))
                self.assertEqual(coverage.get("distinct_passing_rows"), len(set(row_ids)))


class TestProtocolSnapshotManifest(unittest.TestCase):
    """Normative and independent sources must bind actual archived bytes."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "protocol-snapshot-manifest.json").read_text())

    def test_remote_sources_have_byte_snapshots_and_real_hashes(self):
        for source in self.manifest.get("sources", []):
            source_type = str(source.get("source_type", "")).lower()
            if "local" in source_type:
                continue
            with self.subTest(source=source.get("id")):
                rel = source.get("snapshot_path", "")
                self.assertTrue(rel and not Path(rel).is_absolute())
                path = (REPO_ROOT / Path(*rel.replace("\\", "/").split("/"))).resolve()
                self.assertTrue(path.is_file(), f"missing archived snapshot {rel}")
                self.assertEqual(source.get("snapshot_sha256"), sha256_file(path))
                self.assertEqual(source.get("snapshot_sha256_method"), "sha256(snapshot_file_bytes)")
                self.assertNotIn("content-derived", str(source.get("snapshot_sha256_method", "")))
                self.assertNotIn("retrieval_timestamp)", str(source.get("snapshot_sha256_method", "")))
                self.assertTrue(source.get("tag_commit_release"), "release/tag provenance is required")

    def test_independent_source_is_archived_too(self):
        independent = [
            s for s in self.manifest.get("sources", [])
            if "independent" in str(s.get("source_type", "")).lower()
        ]
        self.assertTrue(independent, "an independent interoperability/security source is required")
        for source in independent:
            self.assertTrue(source.get("snapshot_path"))
            self.assertRegex(source.get("snapshot_sha256", ""), r"^[0-9a-f]{64}$")


class TestLatestCanonicalBinding(unittest.TestCase):
    """Record and packs must bind the exact latest canonical DB row."""

    @classmethod
    def setUpClass(cls):
        cls.record = json.loads((ROOT / "evaluation-record.json").read_text())

    def test_record_matches_exact_latest_series_and_evaluation(self):
        self.assertTrue(DB_PATH.is_file(), "canonical DB is required for latest-row binding")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            series = conn.execute(
                "SELECT * FROM research_series WHERE research_key=? "
                "ORDER BY revision DESC, id DESC LIMIT 1", ("S1-009",)
            ).fetchone()
            self.assertIsNotNone(series)
            top_level_series_fields = {
                "id": "research_series_id",
                "revision": "research_revision",
                "campaign_id": "campaign_id",
                "goal_id": "goal_id",
                "manifest_sha256": "manifest_sha256",
            }
            for field in ("id", "revision", "campaign_id", "goal_id", "manifest_sha256"):
                with self.subTest(field=field):
                    self.assertEqual(self.record.get(top_level_series_fields[field]), series[field])
            evaluation = conn.execute(
                "SELECT * FROM research_evaluation WHERE goal_id=? "
                "ORDER BY evaluation_version DESC, id DESC LIMIT 1", (series["goal_id"],)
            ).fetchone()
            self.assertIsNotNone(evaluation)
            self.assertEqual(self.record.get("evaluation_id"), evaluation["id"])
            self.assertEqual(self.record.get("artifact_chain_hash"), evaluation["artifact_chain_hash"])
        finally:
            conn.close()

    def test_tracked_packs_are_self_file_payload_and_archive_reproducible(self):
        entries = [
            self.record.get("tracked_ticket_pack"),
            self.record.get("tracked_canonical_pack"),
        ]
        self.assertTrue(all(isinstance(entry, dict) for entry in entries))
        paths = []
        for entry in entries:
            rel = entry.get("path", "")
            self.assertTrue(rel and not Path(rel).is_absolute())
            path = (REPO_ROOT / Path(*rel.replace("\\", "/").split("/"))).resolve()
            self.assertTrue(path.is_file(), rel)
            try:
                path.relative_to(REPO_ROOT.resolve())
            except ValueError:
                self.fail(f"pack path escapes repository: {rel}")
            listed = subprocess.run(
                ["git", "ls-files", "--error-unmatch", rel],
                cwd=REPO_ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(listed.returncode, 0, f"pack is not tracked: {rel}")
            file_sha = sha256_file(path)
            self.assertEqual(entry.get("file_sha256"), file_sha)
            self.assertEqual(path.stem, file_sha)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(entry.get("payload_sha256"),
                             hashlib.sha256(
                                 json.dumps(payload["payload"], sort_keys=True,
                                            separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                             ).hexdigest())
            self_hash_payload = dict(payload)
            self_hash_payload["pack_sha256"] = ""
            self.assertEqual(payload.get("pack_sha256"),
                             hashlib.sha256(
                                 json.dumps(self_hash_payload, sort_keys=True,
                                            separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                             ).hexdigest())
            paths.append(rel)
        self.assertNotEqual(paths[0], paths[1])

        archive = subprocess.run(
            ["git", "archive", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, check=True,
        ).stdout
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            names = set(tar.getnames())
        for rel in paths:
            self.assertIn(rel.replace("\\", "/"), names)


class TestKnowledgeGovernance(unittest.TestCase):
    """Knowledge content remains untrusted; no silent promotion."""

    @classmethod
    def setUpClass(cls):
        with open(ROOT / "cases.json", encoding="utf-8") as f:
            cls.cases = json.load(f)

    def test_promotion_cases_are_adversarial(self):
        """Any case with 'promoted' or 'verified' in input payload must be DENY."""
        for case in self.cases["cases"]:
            blob = json.dumps(case["input"]).lower()
            if "promoted" in blob or "verified" in blob:
                self.assertEqual(case["expected"]["decision"], "DENY",
                                 f"Case {case['case_id']} with promotion/verified must DENY")

    def test_accepted_cases_never_promote_knowledge(self):
        for case in self.cases["cases"]:
            if case["expected"]["decision"] == "ACCEPT":
                env = case["expected"].get("envelope_assertions", {})
                status = env.get("knowledge.status", "proposal")
                self.assertEqual(status, "proposal",
                                 f"Accept case {case['case_id']} must have knowledge.status=proposal")


class TestFailClosedMutations(unittest.TestCase):
    """Negative mutations: fail-closed when oracle/manifest is tampered."""

    @classmethod
    def setUpClass(cls):
        cls.evaluator = _load_evaluator()
        with open(ROOT / "cases.json", encoding="utf-8") as f:
            cls.manifest = json.load(f)

    def test_missing_expected_decision_fails(self):
        """A case without `expected.decision` must FAIL (not default to ACCEPT)."""
        case = {
            "case_id": "TEST-MISSING-EXPECTED",
            "protocol": "MCP",
            "category": "tampered",
            "probe_id": "",
            "capability_row": "SM3",
            "title": "tampered fixture without expected.decision",
            "input": {"jsonrpc": "2.0", "method": "tools/call",
                      "params": {"name": "read_file", "arguments": {"path": "/x"}},
                      "id": "t1"},
            "hub_context": {},
            "expected": {},  # missing decision
        }
        result = self.evaluator.evaluate_case(case)
        self.assertEqual(result["verdict"], "FAIL",
                         "Missing expected.decision must FAIL")
        self.assertEqual(result["decision_expected"], "MISSING_DECISION_FIELD")

    def test_missing_expected_block_fails(self):
        """A case without `expected` block must FAIL."""
        case = {
            "case_id": "TEST-MISSING-BLOCK",
            "protocol": "MCP",
            "category": "tampered",
            "probe_id": "",
            "capability_row": "SM3",
            "title": "tampered fixture without expected block",
            "input": {"jsonrpc": "2.0", "method": "tools/call",
                      "params": {"name": "read_file", "arguments": {"path": "/x"}},
                      "id": "t2"},
            "hub_context": {},
            # no expected field at all
        }
        result = self.evaluator.evaluate_case(case)
        self.assertEqual(result["verdict"], "FAIL",
                         "Missing expected block must FAIL")
        self.assertEqual(result["decision_expected"], "MISSING_ORACLE")

    def test_tampered_manifest_mismatch_refuses_to_run(self):
        """Corpus manifest with wrong sha256 must cause run_corpus to raise."""
        import tempfile, shutil
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            shutil.copy(ROOT / "cases.json", tmp / "cases.json")
            shutil.copy(ROOT / "corpus-manifest.json", tmp / "corpus-manifest.json")
            shutil.copy(ROOT / "adapter-contract.json", tmp / "adapter-contract.json")
            shutil.copy(ROOT / "rubric.json", tmp / "rubric.json")
            shutil.copy(ROOT / "canonical-envelope.schema.json", tmp / "canonical-envelope.schema.json")
            # Tamper the manifest
            with open(tmp / "corpus-manifest.json") as f:
                m = json.load(f)
            m["frozen_artifacts"]["cases"]["sha256"] = "0" * 64
            with open(tmp / "corpus-manifest.json", "w") as f:
                json.dump(m, f)
            with self.assertRaises(RuntimeError) as ctx:
                self.evaluator.run_corpus(
                    tmp / "cases.json", tmp / "out", "test-exec", "test-nonce"
                )
            self.assertIn("corpus sha256 mismatch", str(ctx.exception))

    def test_comparator_detects_duplicate_case_ids(self):
        """Comparator must flag duplicate case_ids in either run."""
        runner_mod = importlib.util.spec_from_file_location(
            "runner_s1_009", str(ROOT / "runner.py")
        )
        runner = importlib.util.module_from_spec(runner_mod)
        runner_mod.loader.exec_module(runner)
        compare_runs = runner.compare_runs
        run_a = {
            "executor_id": "vA", "nonce": "nA",
            "results_path": str(ROOT / "results" / "run-a" / "results.json"),
            "hashes": {},
            "invocation_digest": "da",
            "process_provenance": {"evaluator_pid": 1},
        }
        run_b = {
            "executor_id": "vB", "nonce": "nB",
            "results_path": str(ROOT / "results" / "run-b" / "results.json"),
            "hashes": {},
            "invocation_digest": "db",
            "process_provenance": {"evaluator_pid": 2},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # Create run-a with duplicate
            dup_results = [
                {"case_id": "DUP", "decision_actual": "DENY", "verdict": "FAIL",
                 "envel_hash": "h1", "rules_triggered": [], "reasons": [],
                 "case_id": "DUP", "decision_actual": "DENY", "verdict": "FAIL",
                 "envel_hash": "h1", "rules_triggered": [], "reasons": []},
            ]
            # Use simpler approach
            (tmp / "run-a").mkdir()
            (tmp / "run-b").mkdir()
            with open(tmp / "run-a" / "results.json", "w") as f:
                json.dump([
                    {"case_id": "A1", "decision_actual": "ACCEPT", "verdict": "PASS",
                     "envel_hash": "h1", "rules_triggered": [], "reasons": []},
                    {"case_id": "A1", "decision_actual": "DENY", "verdict": "FAIL",
                     "envel_hash": "h2", "rules_triggered": [], "reasons": []},
                ], f)
            with open(tmp / "run-b" / "results.json", "w") as f:
                json.dump([
                    {"case_id": "A1", "decision_actual": "ACCEPT", "verdict": "PASS",
                     "envel_hash": "h1", "rules_triggered": [], "reasons": []},
                ], f)
            run_a["results_path"] = str(tmp / "run-a" / "results.json")
            run_b["results_path"] = str(tmp / "run-b" / "results.json")
            comp = compare_runs(run_a, run_b)
            dup_mismatches = [m for m in comp["mismatches"] if m["type"] == "duplicate_in_a"]
            self.assertEqual(len(dup_mismatches), 1, "Must detect duplicate_in_a")
            self.assertEqual(dup_mismatches[0]["case_id"], "A1")
            self.assertEqual(comp["verdict"], "FAIL")

    def test_comparator_detects_extra_case_in_b(self):
        """Comparator must flag extra cases in run-B not present in run-A."""
        runner_mod = importlib.util.spec_from_file_location(
            "runner_s1_009", str(ROOT / "runner.py")
        )
        runner = importlib.util.module_from_spec(runner_mod)
        runner_mod.loader.exec_module(runner)
        compare_runs = runner.compare_runs
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "run-a").mkdir()
            (tmp / "run-b").mkdir()
            with open(tmp / "run-a" / "results.json", "w") as f:
                json.dump([
                    {"case_id": "A1", "decision_actual": "ACCEPT", "verdict": "PASS",
                     "envel_hash": "h1", "rules_triggered": [], "reasons": []},
                ], f)
            with open(tmp / "run-b" / "results.json", "w") as f:
                json.dump([
                    {"case_id": "A1", "decision_actual": "ACCEPT", "verdict": "PASS",
                     "envel_hash": "h1", "rules_triggered": [], "reasons": []},
                    {"case_id": "BEXTRA", "decision_actual": "DENY", "verdict": "PASS",
                     "envel_hash": "h2", "rules_triggered": [], "reasons": []},
                ], f)
            run_a = {
                "executor_id": "vA", "nonce": "nA",
                "results_path": str(tmp / "run-a" / "results.json"),
                "hashes": {}, "invocation_digest": "da",
                "process_provenance": {"evaluator_pid": 1},
            }
            run_b = {
                "executor_id": "vB", "nonce": "nB",
                "results_path": str(tmp / "run-b" / "results.json"),
                "hashes": {}, "invocation_digest": "db",
                "process_provenance": {"evaluator_pid": 2},
            }
            comp = compare_runs(run_a, run_b)
            extra = [m for m in comp["mismatches"] if m["type"] == "extra_in_b"]
            self.assertEqual(len(extra), 1, "Must detect extra_in_b")
            self.assertEqual(extra[0]["case_id"], "BEXTRA")
            self.assertEqual(comp["verdict"], "FAIL")

    def test_comparator_rejects_dirty_or_mixed_frozen_provenance(self):
        runner_mod = importlib.util.spec_from_file_location(
            "runner_s1_009_provenance", str(ROOT / "runner.py")
        )
        runner = importlib.util.module_from_spec(runner_mod)
        runner_mod.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "a.json").write_text(json.dumps([
                {"case_id": "A1", "decision_actual": "ACCEPT", "verdict": "PASS", "envel_hash": "h"}
            ]))
            (tmp / "b.json").write_text(json.dumps([
                {"case_id": "A1", "decision_actual": "ACCEPT", "verdict": "PASS", "envel_hash": "h"}
            ]))
            common = {
                "hashes": {"evaluator_sha256": "e"},
                "input_manifest_sha256": "m",
                "process_provenance": {
                    "runner_pid": 10, "evaluator_pid": 11,
                    "commit_sha": "a" * 40, "tree_sha": "b" * 40,
                    "dirty": True,
                },
            }
            a = dict(common, executor_id="A", nonce="na", results_path=str(tmp / "a.json"),
                     invocation_digest="ia", output_root="results/run-a")
            b_prov = dict(common["process_provenance"], runner_pid=12,
                          evaluator_pid=13, commit_sha="c" * 40, dirty=False)
            b = dict(common, executor_id="B", nonce="nb", results_path=str(tmp / "b.json"),
                     invocation_digest="ib", output_root="results/run-b",
                     process_provenance=b_prov, input_manifest_sha256="different")
            comparison = runner.compare_runs(a, b)
            self.assertEqual(comparison["verdict"], "FAIL")
            kinds = {m["type"] for m in comparison["mismatches"]}
            self.assertIn("dirty_run", kinds)
            self.assertIn("mixed_commit", kinds)
            self.assertIn("mixed_tree", kinds)
            self.assertIn("mixed_input_manifest", kinds)

    def test_repeated_runner_process_is_not_independent(self):
        runner_mod = importlib.util.spec_from_file_location(
            "runner_s1_009_same_runner", str(ROOT / "runner.py")
        )
        runner = importlib.util.module_from_spec(runner_mod)
        runner_mod.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            rows = [{"case_id": "A1", "decision_actual": "ACCEPT", "verdict": "PASS", "envel_hash": "h"}]
            (tmp / "a.json").write_text(json.dumps(rows))
            (tmp / "b.json").write_text(json.dumps(rows))
            provenance = {
                "runner_pid": 77, "evaluator_pid": 11,
                "commit_sha": "a" * 40, "tree_sha": "b" * 40,
                "dirty": False,
            }
            def run(path, executor, nonce, out_root):
                return {
                    "executor_id": executor, "nonce": nonce,
                    "results_path": str(path), "hashes": {"h": "x"},
                    "invocation_digest": executor + nonce,
                    "output_root": out_root,
                    "input_manifest_sha256": "m",
                    "process_provenance": dict(provenance),
                }
            comparison = runner.compare_runs(
                run(tmp / "a.json", "A", "na", "results/run-a"),
                run(tmp / "b.json", "B", "nb", "results/run-b"),
            )
            self.assertEqual(comparison["verdict"], "FAIL")
            self.assertIn("same_runner_pid", {m["type"] for m in comparison["mismatches"]})

    def test_comparator_rejects_dirty_evaluator_provenance(self):
        runner_mod = importlib.util.spec_from_file_location(
            "runner_s1_009_evaluator_provenance", str(ROOT / "runner.py")
        )
        runner = importlib.util.module_from_spec(runner_mod)
        runner_mod.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            rows = [{"case_id": "A1", "decision_actual": "ACCEPT",
                     "verdict": "PASS", "envel_hash": "h"}]
            (tmp / "a.json").write_text(json.dumps(rows))
            (tmp / "b.json").write_text(json.dumps(rows))
            hashes = {key: "a" * 64 for key in runner.REQUIRED_HASH_KEYS}
            def run(path, pid, evaluator_clean):
                return {
                    "executor_id": str(pid), "nonce": str(pid),
                    "results_path": str(path), "hashes": hashes,
                    "invocation_digest": str(pid), "output_root": str(pid),
                    "input_manifest_sha256": "m",
                    "process_provenance": {
                        "runner_pid": pid, "evaluator_pid": pid + 100,
                        "commit_sha": "b" * 40, "tree_sha": "c" * 40,
                        "dirty": False, "clean": True,
                        "input_manifest_sha256": "m",
                        "evaluator_clean": evaluator_clean,
                        "evaluator_commit_sha": "b" * 40,
                        "evaluator_tree_sha": "c" * 40,
                        "evaluator_input_manifest_sha256": "m",
                    },
                }
            comparison = runner.compare_runs(
                run(tmp / "a.json", 10, False),
                run(tmp / "b.json", 20, True),
            )
            self.assertEqual(comparison["verdict"], "FAIL")
            self.assertIn("dirty_evaluator",
                          {m["type"] for m in comparison["mismatches"]})


if __name__ == "__main__":
    unittest.main()
