"""Phase 4 tests: campaign manifest immutability, frozen-hash verification,
decision matrix (KEEP/DISCARD/RETEST/CRASH/QUARANTINED), budget + stop rules,
deterministic fake campaign without LLM/network."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentos.autoresearch import (  # noqa: E402
    Autoresearch, AutoresearchError, CampaignManifest)
from agentos.db import open_db  # noqa: E402
from agentos.stage_evals import StageEvals  # noqa: E402


class ARCase(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = Path(tempfile.mkdtemp())
        self.db = open_db(self.root / "t.db")
        self.se = StageEvals(self.db, self.root)
        self.ar = Autoresearch(self.db, self.root, self.se)
        self.manifest = CampaignManifest(
            baseline_ref="commit-base", primary_metric="pass^1",
            mutable_scope=["src/agentos/prompts.py"],
            frozen_eval_hashes={"eval.x": "h1"},
            corpus_hash="chash", budget=5)

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass


class TestManifest(ARCase):
    def test_manifest_requires_frozen_hashes(self):
        with self.assertRaises(AutoresearchError):
            CampaignManifest(baseline_ref="b", primary_metric="m",
                             mutable_scope=[], frozen_eval_hashes={},
                             corpus_hash="")

    def test_manifest_hash_changes_when_frozen_changes(self):
        m2 = CampaignManifest(baseline_ref="b", primary_metric="pass^1",
                              mutable_scope=["src/x.py"],
                              frozen_eval_hashes={"eval.x": "OTHER"},
                              corpus_hash="chash", budget=5)
        self.assertNotEqual(self.manifest.manifest_hash, m2.manifest_hash)


class TestDecide(unittest.TestCase):
    def test_keep_on_improvement_above_noise(self):
        s, why = Autoresearch.decide(0.5, 0.4, noise_floor=0.05)
        self.assertEqual(s, "KEEP")

    def test_discard_below_noise_and_complexity_penalty_breaks_tie(self):
        s1, _ = Autoresearch.decide(0.5, 0.47, noise_floor=0.05)
        self.assertEqual(s1, "DISCARD")
        # statistically equal candidate WITH complexity cost -> DISCARD
        # (penalty pushes it to clearly-worse territory)
        s2, _ = Autoresearch.decide(0.5, 0.48, noise_floor=0.05,
                                    complexity_penalty=0.05)
        self.assertEqual(s2, "DISCARD")

    def test_retest_inside_ambiguity_band(self):
        s, _ = Autoresearch.decide(0.5, 0.485, noise_floor=0.06)
        self.assertEqual(s, "RETEST")

    def test_crash_and_quarantine_precedence(self):
        s1, _ = Autoresearch.decide(0.5, 0.3, noise_floor=0.05,
                                    infrastructure_failure=True)
        self.assertEqual(s1, "CRASH")
        s2, _ = Autoresearch.decide(0.5, 0.3, noise_floor=0.05,
                                    security_violation=True)
        self.assertEqual(s2, "QUARANTINED")
        s3, _ = Autoresearch.decide(0.5, 0.3, noise_floor=0.05,
                                    frozen_ok=False)
        self.assertEqual(s3, "QUARANTINED")
        s4, _ = Autoresearch.decide(0.5, 0.3, noise_floor=0.05,
                                    hard_constraints_ok=False)
        self.assertEqual(s4, "QUARANTINED")


class TestFakeCampaign(ARCase):
    def test_full_matrix_keep_discard_crash_quarantine(self):
        scenarios = [
            {"hypothesis": "tighten prompt", "candidate_ref": "c1",
             "measurements": {"dev": 0.35}},                    # KEEP
            {"hypothesis": "reorder steps", "candidate_ref": "c2",
             "measurements": {"dev": 0.52}},                    # DISCARD
            {"hypothesis": "ambiguous tweak", "candidate_ref": "c3",
             "measurements": {"dev": 0.485}, "noise_floor": 0.06},  # RETEST

            {"hypothesis": "network blip", "candidate_ref": "c4",
             "measurements": {"dev": 0.9},
             "infrastructure_failure": True},                   # CRASH
            {"hypothesis": "touch frozen evals", "candidate_ref": "c5",
             "measurements": {"dev": 0.1}, "mutates_frozen": True},
                                                                # QUARANTINED
        ]
        results = self.ar.run_fake_campaign(
            self.manifest, scenarios,
            dev_eval_fn=lambda wt, seed: 0.5)
        statuses = [r["status"] for r in results]
        # QUARANTINED halts the campaign -> trailing CAMPAIGN_STOPPED marker
        self.assertEqual(statuses, ["KEEP", "DISCARD", "RETEST", "CRASH",
                                    "QUARANTINED", "CAMPAIGN_STOPPED"])
        # every decision is durable with rationale
        rows = self.db.conn.execute(
            "SELECT status, decision_rationale FROM experiment"
            " WHERE status IN ('KEEP','DISCARD','RETEST','CRASH',"
            "'QUARANTINED')").fetchall()
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(r["decision_rationale"] for r in rows))

    def test_campaign_stops_after_three_crashes(self):
        crash = {"hypothesis": "infra down", "candidate_ref": "cx",
                 "measurements": {"dev": 0.9},
                 "infrastructure_failure": True}
        results = self.ar.run_fake_campaign(
            self.manifest, [dict(crash) for _ in range(5)],
            dev_eval_fn=lambda wt, seed: 0.5)
        stops = [r for r in results if r["status"] == "CAMPAIGN_STOPPED"]
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]["reason"], "infra_failures_3")
        # only three CRASH experiments were recorded before the stop
        crashes = [r for r in results if r["status"] == "CRASH"]
        self.assertEqual(len(crashes), 3)

    def test_budget_stops_campaign(self):
        good = {"hypothesis": "h", "candidate_ref": "c",
                "measurements": {"dev": 0.3}}
        tight = CampaignManifest(
            baseline_ref="base", primary_metric="pass^1",
            mutable_scope=["src/agentos/prompts.py"],
            frozen_eval_hashes={"eval.x": "h1"}, corpus_hash="chash",
            budget=2)
        results = self.ar.run_fake_campaign(
            tight, [dict(good) for _ in range(5)],
            dev_eval_fn=lambda wt, seed: 0.5)
        self.assertEqual(results[-1]["status"], "CAMPAIGN_STOPPED")
        self.assertEqual(results[-1]["reason"], "budget_exhausted")
        keeps = [r for r in results if r["status"] == "KEEP"]
        self.assertEqual(len(keeps), 2)

    def test_frozen_hash_change_stops_with_quarantine(self):
        """A candidate that mutates frozen evals is QUARANTINED and the
        campaign halts — the candidate can never grade its own exam."""
        bad = {"hypothesis": "lower my own threshold", "candidate_ref": "evil",
               "measurements": {"dev": 0.01}, "mutates_frozen": True}
        after = {"hypothesis": "innocent", "candidate_ref": "ok",
                 "measurements": {"dev": 0.3}}
        results = self.ar.run_fake_campaign(
            self.manifest, [bad, after],
            dev_eval_fn=lambda wt, seed: 0.5)
        self.assertEqual(results[0]["status"], "QUARANTINED")
        # campaign halts immediately after quarantine
        self.assertEqual(results[-1]["reason"], "security_violation")
        quarantined = [r for r in results if r["status"] == "QUARANTINED"]
        self.assertEqual(len(quarantined), 1)
        # the innocent follow-up experiment never ran
        self.assertTrue(all(r.get("hypothesis") != "innocent"
                            for r in results if "hypothesis" in r))


if __name__ == "__main__":
    unittest.main()
