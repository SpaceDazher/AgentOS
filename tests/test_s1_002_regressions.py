"""Deterministic regression tests for S1-002 benchmark reproducibility.

Follows the S1-003 precedent: the tests import the ticket-local probe/bench
helpers directly (stdlib-only) and verify that the declared claims are
reproducible from the committed raw evidence.  Wall-clock latency is a live
measurement and is intentionally NOT byte-asserted; the deterministic
structural envelope and the bundle<->evidence hash consistency ARE asserted.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
S1002 = ROOT / "research" / "tickets" / "stage-1" / "S1-002"
sys.path.insert(0, str(S1002))

import bench_probe as bp  # noqa: E402


def _read(name: str) -> bytes:
    return (S1002 / name).read_bytes()


def _load_bundle() -> dict:
    return json.loads(_read("bundle.json"))


class TestS1002BenchProbe(unittest.TestCase):
    """The reproducibility probe passes on the committed evidence."""

    def test_bench_probe_passes(self):
        bundle = _load_bundle()
        raw = json.loads(_read("raw-results.json"))
        failures = bp.probe(bundle, raw, _read("raw-results.json"))
        self.assertEqual(failures, [], failures)

    def test_on_disk_raw_sha_matches_bundle_claim(self):
        """The committed raw-results.json digest equals the configured one and
        every artifact that names it agrees — closes the stale-hash review gap."""
        on_disk = hashlib.sha256(_read("raw-results.json")).hexdigest()
        self.assertEqual(on_disk, bp.CONFIG_SHA256)
        for kind in ("research_plan", "source_registry", "independent_audit", "progress"):
            content = _load_bundle()["artifacts"][kind]["content"]
            self.assertIn(on_disk, content, f"{kind} must carry the true raw SHA-256")

    def test_structurally_correct_envelope(self):
        raw = json.loads(_read("raw-results.json"))
        cfg = raw["configuration"]
        self.assertEqual(cfg["seed"], bp.EXPECTED_SEED)
        self.assertEqual(list(cfg["rates_events_per_second"]), bp.EXPECTED_RATES)
        self.assertEqual(
            sum(t["events_completed"] for t in raw["trials"]),
            bp.EXPECTED_EVENTS)
        self.assertEqual(len(raw["aggregates"]), bp.EXPECTED_AGGREGATES)
        self.assertEqual(
            raw["storage_probe"]["bytes_per_persisted_row"],
            bp.EXPECTED_STORAGE_BYTES_PER_ROW)

    def test_rng_seed_is_deterministic_and_90_10(self):
        """The seeded 90/10 allow/deny mix is reproducible for a fixed seed."""
        def first_sequence():
            rng = random.Random(bp.EXPECTED_SEED + 34 * 10_000 + 1 * 100)
            return [rng.random() >= 0.10 for _ in range(200)]
        a = first_sequence()
        b = first_sequence()
        self.assertEqual(a, b)
        self.assertTrue(150 < sum(a) <= 200)  # ~90% allow

    def test_seeded_rng_differs_across_rates(self):
        rng1 = random.Random(bp.EXPECTED_SEED + 10 * 10_000 + 1 * 100)
        rng2 = random.Random(bp.EXPECTED_SEED + 100 * 10_000 + 1 * 100)
        self.assertNotEqual(
            [rng1.random() for _ in range(50)],
            [rng2.random() for _ in range(50)])


class TestS1002BenchHelpers(unittest.TestCase):
    """Deterministic pure helpers used by the benchmark."""

    def test_percentile_and_summarize_are_deterministic(self):
        from benchmark import percentile, summarize
        values = [1.0, 2.0, 3.0, 4.0, 100.0]
        self.assertEqual(percentile(values, 0.95), 100.0)
        s1 = summarize(values)
        s2 = summarize(values)
        self.assertEqual(s1, s2)
        self.assertEqual(s1["p50"], 3.0)
        self.assertEqual(s1["min"], 1.0)
        self.assertEqual(s1["max"], 100.0)


if __name__ == "__main__":
    unittest.main()
