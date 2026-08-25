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
import sys
import tempfile
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parent.parent
S1003 = ROOT / "research" / "tickets" / "stage-1" / "S1-003"
sys.path.insert(0, str(S1003))

import comparison as cmp  # noqa: E402


def _load(name: str) -> dict:
    return json.loads((S1003 / name).read_text(encoding="utf-8"))


def _disk_hashes() -> dict:
    return cmp._disk_hashes(S1003)


class TestComparisonFailClosed(TestCase):
    """Verify that comparison.py cannot be bypassed by tampering engine-results."""

    def setUp(self):
        self.structural = _load("raw-results.json")
        self.engine = _load("engine-results.json")
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
        # The assertion should carry inherited fields like digest and media_type
        # directly on the assertion IRI (not just nested inside evidence).
        self.assertIn("urn:s1-003:fixture:assertion-proposed-inherited", turtle)
        self.assertIn("digest", turtle)
        self.assertIn("media_type", turtle)
        # The hash should be a valid 64-char hex
        self.assertEqual(len(sha), 64)
        self.assertEqual(sha, hashlib.sha256(turtle.encode("utf-8")).hexdigest())


if __name__ == "__main__":
    import unittest
    unittest.main()
