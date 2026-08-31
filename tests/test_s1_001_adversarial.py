"""Executable adversarial regression tests for S1-001 source promotion.

Follows the S1-003 precedent: tests import the ticket-local probe helpers and
verify that the promotion criteria operate on the BUNDLE's data (sources,
provenance fields, claims), not on hard-coded logic:

  P1: a mirror URL with a different publisher label but the same
      canonical_source_id / independence_group must not count as an
      independent source (delta |G| = delta N = 0 across high-risk claims).
  P2a: a source marked ``u`` with a plausible title but no verifier
       provenance must remain unpromoted.
  P2b: a corrected DOI must preserve the original error note.
  P3: every promotion candidate carries canonical_source_id, publisher_id,
      independence_group and the v/c/u/x/x-excluded vocabulary is defined.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
S1001 = ROOT / "research" / "tickets" / "stage-1" / "S1-001"
sys.path.insert(0, str(S1001))

import promotion_probes as pp  # noqa: E402


def _bundle() -> dict:
    return json.loads((S1001 / "bundle.json").read_text(encoding="utf-8"))


class TestS1001PromotionProbes(unittest.TestCase):
    """The bundle data satisfies every mandatory adversarial probe."""

    def test_all_probes_pass_on_bundle_data(self):
        bundle = _bundle()
        result = pp.run_all(bundle)
        self.assertEqual(result["observed"], "pass", result["failures"])
        self.assertEqual(result["passed"], result["total_probes"])
        self.assertGreaterEqual(result["total_probes"], 2)

    def test_mirror_does_not_create_independence(self):
        """Different URL + publisher label, same canonical identity => no delta."""
        bundle = _bundle()
        effect = pp.mirror_effect(
            bundle, "F16",
            "https://cdn.example.org/mirror/doyle-tms", "some-other-publisher")
        self.assertTrue(effect["different_publisher_label"])
        self.assertTrue(effect["inherits_canonical_source_id"])
        self.assertTrue(effect["inherits_independence_group"])
        self.assertEqual(effect["delta_independence_groups"],
                         {c: 0 for c in pp.HIGH_RISK_CLAIMS})
        self.assertEqual(effect["delta_canonical_sources"],
                         {c: 0 for c in pp.HIGH_RISK_CLAIMS})
        self.assertFalse(effect["independence_violated"])

    def test_provenance_missing_keeps_u_unpromoted(self):
        """A plausible u title without verifier/method must stay unpromoted."""
        bundle = _bundle()
        result = pp.provenance_without_verifier(bundle, "F18")
        self.assertTrue(result["plausible_title"])
        self.assertFalse(result["has_verifier"])
        self.assertFalse(result["has_method"])
        self.assertEqual(result["decision"], "u")
        self.assertTrue(result["remains_unpromoted"])

    def test_corrected_doi_preserves_original_error(self):
        """F16's correction must retain the rejected near-miss DOI."""
        bundle = _bundle()
        result = pp.corrected_doi_preserves_error(bundle, "F16")
        self.assertTrue(result["error_preserved"])
        self.assertTrue(result["names_near_miss"])
        self.assertIn("90020-9", result["correction_note"])
        self.assertTrue(result["probe_passed"])

    def test_acceptance_fields_complete_on_all_candidates(self):
        bundle = _bundle()
        a = pp.acceptance_fields(bundle)
        self.assertEqual(a["candidate_count"], 12)
        self.assertEqual(a["missing_fields"], [])
        self.assertTrue(a["all_candidates_complete"])
        self.assertTrue(a["vocabulary_defined"])
        self.assertEqual(set(a["status_vocabulary"]), pp.STATUS_VOCAB)


class TestS1001ProbesFailClosed(unittest.TestCase):
    """Tampering with bundle data must make the probes fail (fail-closed)."""

    def test_duplicating_a_candidate_without_new_group_fails_independence(self):
        """If the queue really double-counted a mirror as a new candidate with
        the same canonical_source_id, the probe must surface it (Sybil)."""
        bundle = _bundle()
        original = next(s for s in bundle["sources"] if s["id"] == "F16")
        duplicate = copy.deepcopy(original)
        duplicate["id"] = "F16-DUP"
        duplicate["canonical_uri"] = "https://doi.org/10.1016/0004-3702(79)90008-0"
        bundle["sources"].append(duplicate)
        result = pp.run_all(bundle)
        self.assertNotEqual(result["observed"], "pass")
        # The duplicate canonical_source_id is caught by the no-double-count
        # rule (P3) — the same field that also backs the P1 mirror probe.
        self.assertTrue(any("P3" in f or "duplicate_canonical" in f
                            for f in result["failures"]))

    def test_stripping_provenance_fields_makes_acceptance_probe_fail(self):
        bundle = _bundle()
        f16 = next(s for s in bundle["sources"] if s["id"] == "F16")
        del f16["verifier_provenance"]["canonical_source_id"]
        result = pp.run_all(bundle)
        self.assertNotEqual(result["observed"], "pass")
        self.assertTrue(any("P3" in f for f in result["failures"]))

    def test_erasing_correction_note_makes_doi_probe_fail(self):
        bundle = _bundle()
        f16 = next(s for s in bundle["sources"] if s["id"] == "F16")
        f16["verifier_provenance"]["correction_note"] = ""
        result = pp.run_all(bundle)
        self.assertNotEqual(result["observed"], "pass")
        self.assertTrue(any("P2b" in f for f in result["failures"]))


if __name__ == "__main__":
    unittest.main()