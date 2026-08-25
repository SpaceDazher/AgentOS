"""Adversarial regression tests for S1-003 fail-closed logic.

These tests import comparison.py and validate_pyshacl helpers directly
(no rdflib/pySHACL needed) and verify that every fail-open bypass identified
during review is blocked:

1. Tampering expected_conforms / normalized_violations in engine-results.json
   must NOT bypass comparison (expectations come from structural oracle only).
2. Tampering shapes/fixtures/RDF hashes must be caught (all recomputed from disk).
3. Per-run provenance mismatches (runtime, hashes, digest) must be caught.
4. Unclassified violations in engine results must cause FAIL (not be silently
   allowed — only the versioned allowlist entries are permitted).
5. Empty engine-results with pyshacl_executed=true must still FAIL (count check
   and key-set completeness).
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
S1003 = ROOT / "research" / "tickets" / "stage-1" / "S1-003"
sys.path.insert(0, str(S1003))

import comparison as cmp  # noqa: E402


def _load(name: str) -> dict:
    return json.loads((S1003 / name).read_text(encoding="utf-8"))


def _disk_hashes() -> dict:
    return cmp._disk_hashes(S1003)


def _prepare_v2_engine(engine: dict, structural: dict) -> dict:
    """Upgrade the checked-in pre-replay fixture in memory for unit tests.

    ``engine-results.json`` is intentionally not edited by this regression
    suite; the parent replay will regenerate it from validate_pyshacl.py.  The
    comparator tests still need a complete v2-shaped artifact, so this helper
    adds only deterministic schema fields in memory.
    """
    engine["schema"] = cmp.ENGINE_SCHEMA
    disk = cmp._disk_hashes(S1003)
    engine["inputs"].update({
        "fixtures_sha256": disk["fixtures_json"],
        "shapes_open_sha256": disk["shapes_open"],
        "shapes_promoted_only_sha256": disk["shapes_promoted_only"],
        "rdf_input_sha256": disk["fixtures_ttl"],
        "validate_structural_sha256": disk["validate_structural"],
        "fixtures_to_rdf_sha256": disk["fixtures_to_rdf"],
        "validate_pyshacl_sha256": disk["validate_pyshacl"],
    })
    structural_by_key = {
        (item["fixture_id"], item["profile"]): item
        for item in structural["results"]
    }
    for run in engine["results"]:
        key = (run["fixture_id"], run["profile"])
        oracle = structural_by_key[key]
        tuples = cmp._expected_semantic_tuples(oracle, *key)
        run["semantic_tuples"] = tuples
        run["semantic_digest"] = cmp._semantic_digest_from_tuples(tuples)
        run["validate_structural_sha256"] = disk["validate_structural"]
        run["fixtures_to_rdf_sha256"] = disk["fixtures_to_rdf"]
        run["validate_pyshacl_sha256"] = disk["validate_pyshacl"]
    engine["summary"] = {
        "total_runs": len(engine["results"]),
        "matched_runs": len(engine["results"]),
        "mismatch_count": 0,
        "verdict": "pass",
    }
    return engine


class TestComparisonFailClosed(TestCase):
    """Verify that comparison.py cannot be bypassed by tampering engine-results."""

    def setUp(self):
        self.structural = _load("raw-results.json")
        self.engine = _prepare_v2_engine(_load("engine-results.json"), self.structural)
        self.disk = _disk_hashes()

    def test_baseline_passes(self):
        """The real (un-tampered) engine-results must produce PASS."""
        report = cmp.compare(self.engine, self.structural, self.disk)
        self.assertEqual(report["verdict"], "pass", report["mismatches"])
        self.assertEqual(report["matched"], 26)
        self.assertEqual(report["fail_closed"], True)

    # ------------------------------------------------------------------ #
    # P1: expected values from engine must NOT be trusted
    # ------------------------------------------------------------------ #
    def test_tampering_expected_conforms_is_caught(self):
        """Changing expected_conforms in a negative run to true must FAIL."""
        tampered = copy.deepcopy(self.engine)
        # Pick a fixture that should FAIL conformance
        neg = next(r for r in tampered["results"]
                   if not r["expected_conforms"] and r["profile"] == "open")
        neg["expected_conforms"] = True
        neg["observed_conforms"] = True
        # Also empty out the violations so the reason check is moot
        neg["normalized_violations"] = []
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail",
                         f"expected FAIL when engine expected_conforms is tampered: {report['mismatches']}")
        self.assertTrue(any("conforms" in m for m in report["mismatches"]))

    def test_tampering_normalized_violations_is_caught(self):
        """Removing all violations from a negative run must FAIL (primary reason missing)."""
        tampered = copy.deepcopy(self.engine)
        neg = next(r for r in tampered["results"]
                   if not r["expected_conforms"] and r["profile"] == "open")
        neg["normalized_violations"] = []
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail",
                         f"expected FAIL when violations are emptied: {report['mismatches']}")
        self.assertTrue(any("primary_reason" in m or "violations" in m.lower()
                            for m in report["mismatches"]))

    def test_expected_primary_reason_from_engine_is_ignored(self):
        """Even if engine's expected_primary_reason matches, structural oracle
        must be the source of truth.  Corrupt the engine's normalized_violations
        (removing the actual reason) while keeping expected_primary_reason
        unchanged — the comparator must still catch it via the structural oracle."""
        tampered = copy.deepcopy(self.engine)
        neg = next(r for r in tampered["results"]
                   if not r["expected_conforms"] and r["profile"] == "open")
        original = neg["expected_primary_reason"]
        # The original primary reason should be a real reason string
        self.assertIsNotNone(original)
        # Corrupt the engine's observed violations: remove the structural
        # oracle's expected reason.  If the comparator trusted the engine's
        # expected_primary_reason field, this would still pass.
        original_violations = list(neg["normalized_violations"])
        neg["normalized_violations"] = [
            v for v in original_violations if v != original
        ]
        # Also corrupt expected_primary_reason to prove it's ignored
        neg["expected_primary_reason"] = "completely_bogus_reason"
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail",
                         f"expected FAIL when engine normalized_violations "
                         f"are corrupted: {report['mismatches']}")

    # ------------------------------------------------------------------ #
    # P1: shape/RDF hash tampering must be caught
    # ------------------------------------------------------------------ #
    def test_tampering_shapes_sha_is_caught(self):
        tampered = copy.deepcopy(self.engine)
        for r in tampered["results"]:
            r["shapes_sha256"] = "0" * 64
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("shapes_sha256" in m for m in report["mismatches"]))

    def test_tampering_fixtures_sha_is_caught(self):
        tampered = copy.deepcopy(self.engine)
        for r in tampered["results"]:
            r["fixtures_sha256"] = "0" * 64
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("fixtures_sha256" in m for m in report["mismatches"]))

    def test_tampering_rdf_input_sha_is_caught(self):
        """rdf_input_sha256 is in inputs and per-run.  The comparator must
        verify per-run presence.  Empty rdf_input_sha256 must FAIL."""
        tampered = copy.deepcopy(self.engine)
        for r in tampered["results"]:
            r["rdf_input_sha256"] = ""
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("rdf_input_sha256" in m for m in report["mismatches"]))

    def test_top_level_provenance_hashes_are_content_bound(self):
        """Every declared top-level deterministic-input hash must match disk."""
        for field in ("rdf_input_sha256", "validate_structural_sha256",
                      "fixtures_to_rdf_sha256", "validate_pyshacl_sha256"):
            tampered = copy.deepcopy(self.engine)
            tampered["inputs"][field] = "2" * 64
            report = cmp.compare(tampered, self.structural, self.disk)
            self.assertEqual(report["verdict"], "fail", (field, report))
            self.assertTrue(any(field in m for m in report["mismatches"]),
                            (field, report["mismatches"]))

    def test_per_run_generator_hashes_are_content_bound(self):
        """Per-run provenance cannot be replaced by another valid digest."""
        for field in ("validate_structural_sha256", "fixtures_to_rdf_sha256",
                      "validate_pyshacl_sha256"):
            tampered = copy.deepcopy(self.engine)
            tampered["results"][0][field] = "deadbeef" * 8
            report = cmp.compare(tampered, self.structural, self.disk)
            self.assertEqual(report["verdict"], "fail", (field, report))
            self.assertTrue(any(field in m for m in report["mismatches"]),
                            (field, report["mismatches"]))

    def test_tampering_semantic_digest_is_caught(self):
        """A run with an empty semantic_digest must FAIL."""
        tampered = copy.deepcopy(self.engine)
        # Corrupt one run's digest
        tampered["results"][0]["semantic_digest"] = ""
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("semantic_digest" in m for m in report["mismatches"]))

    # ------------------------------------------------------------------ #
    # P1: count, key-set, duplicates, pyshacl_executed
    # ------------------------------------------------------------------ #
    def test_empty_engine_results_is_caught(self):
        """Empty results with pyshacl_executed=true must FAIL (not pass)."""
        tampered = copy.deepcopy(self.engine)
        tampered["results"] = []
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(report["fail_closed"])

    def test_pyshacl_not_executed_is_caught(self):
        tampered = copy.deepcopy(self.engine)
        tampered["pyshacl_executed"] = False
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("pyshacl_executed" in m for m in report["mismatches"]))

    def test_duplicate_keys_are_caught(self):
        tampered = copy.deepcopy(self.engine)
        # Duplicate the first result
        tampered["results"].append(copy.deepcopy(tampered["results"][0]))
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("duplicate" in m for m in report["mismatches"]))

    def test_extra_engine_run_is_caught(self):
        tampered = copy.deepcopy(self.engine)
        extra = copy.deepcopy(tampered["results"][0])
        extra["fixture_id"] = "fake-fixture"
        extra["profile"] = "open"
        tampered["results"].append(extra)
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("extra" in m for m in report["mismatches"]))

    def test_missing_engine_run_is_caught(self):
        tampered = copy.deepcopy(self.engine)
        tampered["results"].pop(0)  # Remove one run
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("missing" in m for m in report["mismatches"]))

    def test_runtime_mismatch_is_caught(self):
        tampered = copy.deepcopy(self.engine)
        for r in tampered["results"]:
            r["runtime"]["rdflib"] = "0.0.0"
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("runtime" in m for m in report["mismatches"]))

    # ------------------------------------------------------------------ #
    # P2: unclassified violations must cause FAIL
    # ------------------------------------------------------------------ #
    def test_unclassified_violation_is_caught(self):
        """Injecting an unknown reason into a valid run must FAIL."""
        tampered = copy.deepcopy(self.engine)
        # Find a run that currently passes (conforms=True, no violations)
        good_run = next(r for r in tampered["results"] if r["observed_conforms"])
        good_run["normalized_violations"].append("totally_unknown_reason_xyz")
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(
            any("unclassified" in m or "unknown violation" in m
                for m in report["mismatches"]),
            f"expected unclassified/unknown violation in mismatches: {report['mismatches']}")

    # ------------------------------------------------------------------ #
    # R8 regression: strict type checks, content-aware hashes, engine
    # summary validation — all bypass paths from REVISE verdict
    # ------------------------------------------------------------------ #
    def test_string_false_pyshacl_executed_is_caught(self):
        """pyshacl_executed='false' (string) must FAIL — strict boolean."""
        tampered = copy.deepcopy(self.engine)
        tampered["pyshacl_executed"] = "false"  # not boolean True
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("pyshacl_executed" in m for m in report["mismatches"]))

    def test_string_false_observed_conforms_is_caught(self):
        """observed_conforms='false' (string) must FAIL — strict boolean."""
        tampered = copy.deepcopy(self.engine)
        good = next(r for r in tampered["results"] if r["observed_conforms"] is True)
        good["observed_conforms"] = "false"
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("not a JSON boolean" in m for m in report["mismatches"]))

    def test_fake_nonempty_hash_is_caught(self):
        """rdf_input_sha256='000...000' (non-empty but fake) must FAIL."""
        tampered = copy.deepcopy(self.engine)
        for r in tampered["results"]:
            r["rdf_input_sha256"] = "0" * 64
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("rdf_input_sha256" in m for m in report["mismatches"]))

    def test_nonempty_fake_semantic_digest_is_caught(self):
        """semantic_digest='111...111' (non-empty but fake) must FAIL."""
        tampered = copy.deepcopy(self.engine)
        for r in tampered["results"]:
            r["semantic_digest"] = "1" * 64
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("semantic_digest" in m for m in report["mismatches"]))

    def test_arbitrary_valid_semantic_digest_is_caught(self):
        """Any digest not derived from canonical tuples must FAIL."""
        for fake in ("2" * 64, "deadbeef" * 8):
            tampered = copy.deepcopy(self.engine)
            tampered["results"][0]["semantic_digest"] = fake
            report = cmp.compare(tampered, self.structural, self.disk)
            self.assertEqual(report["verdict"], "fail", (fake, report))
            self.assertTrue(any("semantic_digest" in m
                                for m in report["mismatches"]),
                            (fake, report["mismatches"]))

    def test_tampered_semantic_tuples_are_caught(self):
        """Replacing canonical evidence tuples must FAIL even with a valid digest."""
        tampered = copy.deepcopy(self.engine)
        tampered["results"][0]["semantic_tuples"] = ["[\"s1-003-semantic/v1\",\"wrong\"]"]
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("semantic_tuples" in m
                            for m in report["mismatches"]))

    def test_normalized_violations_must_be_sorted_unique_strings(self):
        """A JSON object is not a valid normalized-violations list."""
        tampered = copy.deepcopy(self.engine)
        good_run = next(r for r in tampered["results"] if r["observed_conforms"])
        good_run["normalized_violations"] = {"not_promoted_status": True}
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("normalized_violations" in m
                            for m in report["mismatches"]))

    def test_per_run_matched_must_be_strict_and_consistent(self):
        """A forged false or string matched field must FAIL."""
        for value in (False, "false"):
            tampered = copy.deepcopy(self.engine)
            tampered["results"][0]["matched"] = value
            report = cmp.compare(tampered, self.structural, self.disk)
            self.assertEqual(report["verdict"], "fail", (value, report))
            self.assertTrue(any("matched" in m for m in report["mismatches"]),
                            (value, report["mismatches"]))

    def test_unclassified_violations_field_is_checked(self):
        """Non-empty unclassified_violations must FAIL (not just normalized)."""
        tampered = copy.deepcopy(self.engine)
        good_run = next(r for r in tampered["results"] if r["observed_conforms"])
        good_run["unclassified_violations"] = [{"totally": "unexpected"}]
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("unclassified_violations" in m for m in report["mismatches"]))

    def test_engine_verdict_fail_is_caught(self):
        """Engine self-reported verdict='fail' must cause FAIL."""
        tampered = copy.deepcopy(self.engine)
        tampered["verdict"] = "fail"
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("engine.verdict" in m for m in report["mismatches"]))

    def test_engine_mismatches_populated_is_caught(self):
        """Non-empty engine.mismatches must cause FAIL."""
        tampered = copy.deepcopy(self.engine)
        tampered["mismatches"] = ["forged: engine claims a problem"]
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("engine.mismatches" in m for m in report["mismatches"]))

    def test_engine_summary_and_coverage_are_consistent(self):
        """Forged summary/coverage counts cannot accompany a PASS."""
        for field, value in (("matched_runs", 25), ("mismatch_count", 1)):
            tampered = copy.deepcopy(self.engine)
            tampered["summary"][field] = value
            report = cmp.compare(tampered, self.structural, self.disk)
            self.assertEqual(report["verdict"], "fail", (field, report))
        tampered = copy.deepcopy(self.engine)
        tampered["coverage"]["matched_run_count"] = 25
        report = cmp.compare(tampered, self.structural, self.disk)
        self.assertEqual(report["verdict"], "fail", report)

    # ------------------------------------------------------------------ #
    # sha-check mode
    # ------------------------------------------------------------------ #
    def test_sha_check_catches_tampered_shapes_on_disk(self):
        """If the shapes file on disk changes, --sha-check must FAIL."""
        import tempfile, shutil
        tmpdir = Path(tempfile.mkdtemp())
        try:
            # Copy the S1-003 dir to temp
            dst = tmpdir / "s1003"
            shutil.copytree(S1003, dst, ignore=_ignore_venv)
            # Tamper shapes file
            shapes_file = dst / "shapes-v3.ttl"
            original = shapes_file.read_text(encoding="utf-8")
            shapes_file.write_text(original + "\n# TAMPERED\n", encoding="utf-8")
            # Recompute disk hashes
            disk = cmp._disk_hashes(dst)
            # Run comparison with tampered disk hashes
            report = cmp.compare(self.engine, self.structural, disk)
            self.assertEqual(report["verdict"], "fail")
            self.assertTrue(any("shapes_sha256" in m for m in report["mismatches"]))
        finally:
            shutil.rmtree(tmpdir)

    def test_sha_check_mode_aborts_on_disk_mismatch(self):
        """When --sha-check detects disk mismatch, verdict must be fail."""
        # Simulate: engine reports wrong hash for shapes
        tampered_engine = copy.deepcopy(self.engine)
        tampered_engine["inputs"]["shapes_open_sha256"] = "0" * 64
        # compare() itself doesn't do sha_check — that's in main()
        # But we can test the logic by passing wrong disk hashes
        wrong_disk = copy.deepcopy(self.disk)
        wrong_disk["shapes_open"] = "0" * 64
        report = cmp.compare(tampered_engine, self.structural, wrong_disk)
        self.assertEqual(report["verdict"], "fail")


def _ignore_venv(directory, contents):
    """Ignore venv dirs when copying."""
    ignored = ["/".join([directory, c]) for c in contents
               if c.startswith(".venv")]
    return set(ignored)


class TestValidatePyshaclFailClosed(TestCase):
    """Verify validate_pyshacl.py fail-closed behavior for unknown violations."""

    def setUp(self):
        sys.path.insert(0, str(S1003))
        import validate_pyshacl as vp
        self.vp = vp

    def test_known_reasons_are_classified(self):
        """All reasons in _KNOWN_REASONS should not be 'unclassified'."""
        # Create a fake result dict
        result = {
            "constraint_component": "http://www.w3.org/ns/shacl#MinCountConstraintComponent",
            "result_path": "https://example.org/agent-hub#supportedBy",
            "result_message": "insufficient_evidence_count",
            "focus_node": "urn:test:fixture",
            "source_shape": "https://example.org/agent-hub#KnowledgeAssertionShape",
        }
        reason = self.vp._classify_violation(
            result["source_shape"],
            result["constraint_component"],
            result["result_path"],
            result["result_message"],
            result["focus_node"],
            {},
        )
        self.assertEqual(reason, "insufficient_evidence_count")
        self.assertNotEqual(reason, "unclassified")

    def test_unknown_message_is_unclassified_not_discarded(self):
        """A message not in _KNOWN_REASONS and not matching any fallback
        must be classified as 'unclassified' (not silently dropped)."""
        result = {
            "constraint_component": "http://www.w3.org/ns/shacl#MinCountConstraintComponent",
            "result_path": "https://example.org/agent-hub#someUnknownProperty",
            "result_message": "some_bogus_reason_xyz",
            "focus_node": "urn:test:fixture",
            "source_shape": "https://example.org/agent-hub#SomeShape",
        }
        reason = self.vp._classify_violation(
            result["source_shape"],
            result["constraint_component"],
            result["result_path"],
            result["result_message"],
            result["focus_node"],
            {},
        )
        self.assertEqual(reason, "unclassified")

    def test_unclassified_allowlist_filters_benigns(self):
        """OrConstraintComponent with 'Node ' prefix message is allowed."""
        from validate_pyshacl import _filter_unclassified, UNCLASSIFIED_ALLOWLIST
        # Verify the allowlist contains the OrConstraintComponent entry
        self.assertTrue(any(cc == "OrConstraintComponent" for cc, _, _ in UNCLASSIFIED_ALLOWLIST))

        # An entry matching the allowlist should be filtered out (allowed)
        allowed = [{
            "constraint_component": "http://www.w3.org/ns/shacl#OrConstraintComponent",
            "result_path": "",
            "result_message": "Node <urn:test> must conform to one or more shapes",
            "focus_node": "urn:test",
            "source_shape": "https://example.org/agent-hub#KnowledgeAssertionShape",
        }]
        unexpected = _filter_unclassified(allowed)
        self.assertEqual(len(unexpected), 0, f"Expected 0 unexpected, got {unexpected}")

    def test_unclassified_non_allowlisted_is_caught(self):
        """An unclassified violation NOT in the allowlist must be unexpected."""
        from validate_pyshacl import _filter_unclassified
        not_allowed = [{
            "constraint_component": "http://www.w3.org/ns/shacl#MinCountConstraintComponent",
            "result_path": "https://example.org/agent-hub#bogus",
            "result_message": "unknown_violation_xyz",
            "focus_node": "urn:test",
            "source_shape": "https://example.org/agent-hub#SomeShape",
        }]
        unexpected = _filter_unclassified(not_allowed)
        self.assertEqual(len(unexpected), 1)
        self.assertEqual(unexpected[0]["result_message"], "unknown_violation_xyz")


class TestFixturesToRdf(TestCase):
    """Verify inherited_content_object_properties are emitted at assertion root."""

    def setUp(self):
        sys.path.insert(0, str(S1003))
        from fixtures_to_rdf import build_graph
        self.build_graph = build_graph
        doc = json.loads((S1003 / "fixtures.json").read_text(encoding="utf-8"))
        self.doc = doc

    def test_inherited_props_on_assertion_root(self):
        """The assertion-proposed-inherited fixture must have inherited
        data_object_properties (digest, media_type) present in the
        generated Turtle at the assertion root level, not only inside
        supportedBy evidence loops."""
        turtle, sha = self.build_graph(self.doc)
        fixture_id = "assertion-proposed-inherited"
        self.assertIn(fixture_id, turtle)
        self.assertIn("urn:s1-003:fixture:assertion-proposed-inherited", turtle)
        self.assertIn("digest", turtle)
        self.assertIn("media_type", turtle)
        self.assertEqual(len(sha), 64)
        self.assertEqual(sha, hashlib.sha256(turtle.encode("utf-8")).hexdigest())


class TestResearchLocalProvenance(TestCase):
    """Verified local sources must bind to a safe, repo-relative file hash."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        sys.path.insert(0, str(ROOT / "src"))
        from agentos.db import open_db
        from agentos.research import fixture_bundle, run_research_plan
        self.db = open_db(self.root / "agentos.db")
        self.fixture_bundle = fixture_bundle
        self.run_research_plan = run_research_plan

    def tearDown(self):
        self.db.conn.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def _local_bundle(self, path: str, file_sha256: str) -> dict:
        bundle = self.fixture_bundle("local provenance")
        bundle["sources"][0]["verifier_provenance"] = {
            "method": "local-file-sha256",
            "path": path,
            "file_sha256": file_sha256,
        }
        return bundle

    def test_valid_repo_relative_local_hash_passes(self):
        target = self.root / "verified.md"
        target.write_text("verified local source\n", encoding="utf-8")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        result = self.run_research_plan(
            self.db, self.root, "valid local provenance",
            self._local_bundle("verified.md", digest),
        )
        self.assertEqual(result["status"], "pass", result)

    def test_local_provenance_hashing_streams_file_bytes(self):
        """A large verified source must not be loaded by Path.read_bytes()."""
        target = self.root / "verified.md"
        target.write_text("streamed verified source\n", encoding="utf-8")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        original_read_bytes = Path.read_bytes

        def refuse_whole_target(path_obj):
            if path_obj == target:
                raise AssertionError("verified source was read into memory at once")
            return original_read_bytes(path_obj)

        with patch.object(Path, "read_bytes", new=refuse_whole_target):
            result = self.run_research_plan(
                self.db, self.root, "stream local provenance",
                self._local_bundle("verified.md", digest),
            )
        self.assertEqual(result["status"], "pass", result)

    def test_explicit_workspace_root_is_used_when_db_root_differs(self):
        """Local provenance resolves against the trusted workspace, not DB storage."""
        from agentos.db import open_db

        db_root = self.root / "db-root"
        workspace = self.root / "workspace"
        target = workspace / "research" / "source.md"
        target.parent.mkdir(parents=True)
        target.write_text("repo-relative verified source\n", encoding="utf-8")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        db = open_db(db_root / "agentos.db")
        try:
            result = self.run_research_plan(
                db, db_root, "separate workspace provenance",
                self._local_bundle("research/source.md", digest),
                workspace_root=workspace,
            )
        finally:
            db.conn.close()
        self.assertEqual(result["status"], "pass", result)

    def test_stale_local_hash_research_plan_is_rejected(self):
        target = self.root / "verified.md"
        target.write_text("verified local source\n", encoding="utf-8")
        result = self.run_research_plan(
            self.db, self.root, "stale local provenance",
            self._local_bundle("verified.md", "0" * 64),
        )
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(any("file_sha256" in item
                            for item in result["next_actions"]), result)

    def test_absolute_and_traversal_local_paths_are_rejected(self):
        target = self.root / "verified.md"
        target.write_text("verified local source\n", encoding="utf-8")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        for path in (str(target), "../verified.md"):
            result = self.run_research_plan(
                self.db, self.root, f"unsafe local path {path}",
                self._local_bundle(path, digest),
            )
            self.assertEqual(result["status"], "fail", (path, result))
            self.assertTrue(any("path" in item.lower()
                                for item in result["next_actions"]),
                            (path, result["next_actions"]))

    def test_malformed_local_hash_is_rejected(self):
        target = self.root / "verified.md"
        target.write_text("verified local source\n", encoding="utf-8")
        for digest in ("A" * 64, "deadbeef", "g" * 64):
            result = self.run_research_plan(
                self.db, self.root, f"malformed local hash {digest[:8]}",
                self._local_bundle("verified.md", digest),
            )
            self.assertEqual(result["status"], "fail", (digest, result))
            self.assertTrue(any("file_sha256" in item
                                for item in result["next_actions"]),
                            (digest, result["next_actions"]))


if __name__ == "__main__":
    import unittest
    unittest.main()
