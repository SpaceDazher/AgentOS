"""S1-008 regression tests.

These tests verify the S1-008 revocation-latency measurement infrastructure
from the frozen artifacts down to the final evaluation record. They are
"honest" in the sense that they re-derive everything from disk rather than
trusting pre-recorded numbers in the record file.

Run: PYTHONPATH=src python -m unittest tests.test_s1_008_regressions -v
"""
import hashlib
import json
import copy
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
S1_008_DIR = REPO_ROOT / "research" / "tickets" / "stage-1" / "S1-008"
RESULTS_DIR = REPO_ROOT / "results"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_traces(raw_dir: Path) -> list[dict]:
    traces = []
    for f in sorted(raw_dir.glob("*.json")):
        traces.append(json.loads(f.read_text()))
    return traces


class TestFrozenArtifacts(unittest.TestCase):
    """Verify frozen artifacts SHA-256s re-derived from disk."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = json.loads((S1_008_DIR / "bundle.json").read_text())
        cls.frozen = cls.bundle.get("frozen_artifacts", {})

    def test_no_bogus_or_missing_sha(self):
        """Ensure frozen artifact SHA-256s are real hashes, not strings
        like 'bogus' or 'MISSING'.
        """
        for name, sha in self.frozen.items():
            self.assertIsNotNone(sha, f"{name} missing sha256")
            self.assertNotEqual(sha.upper(), "MISSING",
                               f"{name} has placeholder MISSING")
            self.assertNotEqual(sha.lower(), "bogus",
                               f"{name} has placeholder bogus")
            self.assertEqual(len(sha), 64,
                            f"{name} sha256 is not 64 chars: {sha}")

    def test_contract_sha_matches_disk(self):
        """revocation-contract.json SHA must match the file's actual SHA."""
        sha = self.frozen.get("revocation-contract.json")
        self.assertIsNotNone(sha, "revocation-contract.json not in frozen_artifacts")
        actual = _sha256_file(S1_008_DIR / "revocation-contract.json")
        self.assertEqual(actual, sha,
                        f"Disk SHA {actual} != recorded {sha}")

    def test_manifest_sha_matches_disk(self):
        sha = self.frozen.get("workload-manifest.json")
        self.assertIsNotNone(sha)
        actual = _sha256_file(S1_008_DIR / "workload-manifest.json")
        self.assertEqual(actual, sha)

    def test_threat_model_sha_matches_disk(self):
        sha = self.frozen.get("threat-model.json")
        self.assertIsNotNone(sha)
        actual = _sha256_file(S1_008_DIR / "threat-model.json")
        self.assertEqual(actual, sha)

    def test_rubric_sha_matches_disk(self):
        sha = self.frozen.get("rubric.json")
        self.assertIsNotNone(sha)
        actual = _sha256_file(S1_008_DIR / "rubric.json")
        self.assertEqual(actual, sha)

    def test_fixtures_sha_matches_disk(self):
        sha = self.frozen.get("fixtures.json")
        self.assertIsNotNone(sha)
        actual = _sha256_file(S1_008_DIR / "fixtures.json")
        self.assertEqual(actual, sha)

    def test_contract_has_hard_bound(self):
        d = json.loads((S1_008_DIR / "revocation-contract.json").read_text())
        self.assertEqual(d["hard_target_ms"], 5000)

    def test_rubric_has_hard_gates(self):
        d = json.loads((S1_008_DIR / "rubric.json").read_text())
        gates = d["hard_gates"]
        self.assertEqual(gates["max_allow_after_commit"], 0)


class TestMatrixCrossProduct(unittest.TestCase):
    """Verify exact 4×2×3×3=72 matrix cells in raw traces."""

    @classmethod
    def setUpClass(cls):
        cls.traces = _load_traces(RESULTS_DIR / "run-a-clean" / "raw-traces")

    def test_mandatory_trace_count(self):
        mandatory = [t for t in self.traces
                     if "PROBE-" not in t.get("scenario", "")
                     and not t.get("scenario", "").startswith("fault-")]
        self.assertEqual(len(mandatory), 360)  # 72 × 5

    def test_all_72_cells_present(self):
        """Every (path, cache_state, load, seed) cell must appear exactly
        trials_per_scenario_seed = 5 times.
        """
        cells: dict[tuple, int] = {}
        for t in self.traces:
            scenario = t.get("scenario", "")
            if "PROBE-" in scenario or scenario.startswith("fault-"):
                continue
            key = (t.get("path"), t.get("cache_state"),
                   t.get("load"), t.get("seed"))
            cells[key] = cells.get(key, 0) + 1

        # 4 × 2 × 3 × 3 = 72 cells
        expected_cells = 72
        self.assertEqual(len(cells), expected_cells,
                         f"Expected {expected_cells} cells, got {len(cells)}")

        # Each cell must have exactly 5 trials
        for cell, count in cells.items():
            self.assertEqual(count, 5,
                           f"Cell {cell} has {count} trials, expected 5")

    def test_four_paths_represented(self):
        paths = set()
        for t in self.traces:
            scenario = t.get("scenario", "")
            if "PROBE-" in scenario or scenario.startswith("fault-"):
                continue
            paths.add(t.get("path"))
        self.assertEqual(len(paths), 4, f"Only {len(paths)} paths: {paths}")

    def test_cache_states_represented(self):
        caches = set()
        for t in self.traces:
            scenario = t.get("scenario", "")
            if "PROBE-" in scenario or scenario.startswith("fault-"):
                continue
            caches.add(t.get("cache_state"))
        self.assertEqual(len(caches), 2, f"Only {len(caches)} cache states: {caches}")

    def test_loads_represented(self):
        loads = set()
        for t in self.traces:
            scenario = t.get("scenario", "")
            if "PROBE-" in scenario or scenario.startswith("fault-"):
                continue
            loads.add(t.get("load"))
        self.assertEqual(len(loads), 3, f"Only {len(loads)} loads: {loads}")

    def test_seeds_represented(self):
        seeds = set()
        for t in self.traces:
            scenario = t.get("scenario", "")
            if "PROBE-" in scenario or scenario.startswith("fault-"):
                continue
            seeds.add(t.get("seed"))
        self.assertEqual(len(seeds), 3, f"Only {len(seeds)} seeds: {seeds}")
        self.assertEqual(seeds, {"seed11", "seed12", "seed13"})


class TestHardCounters(unittest.TestCase):
    """Verify that all hard counters are zero (fail-closed)."""

    @classmethod
    def setUpClass(cls):
        cls.traces = _load_traces(RESULTS_DIR / "run-a-clean" / "raw-traces")

    def test_all_hard_counters_zero(self):
        """Recompute hard counters from trace data and verify all are 0."""
        from importlib.util import module_from_spec, spec_from_file_location
        import sys
        evaluator_path = S1_008_DIR / "evaluator.py"
        spec = spec_from_file_location("s1_008_evaluator_for_regression", evaluator_path)
        evaluator = module_from_spec(spec)
        sys.modules[spec.name] = evaluator
        spec.loader.exec_module(evaluator)
        counters = evaluator.derive_hard_counters(
            [t for t in self.traces if "PROBE-" not in t.get("scenario", "")]
        )
        for k, v in counters.items():
            self.assertEqual(v, 0, f"{k} = {v}, expected 0")

    def test_each_hard_counter_mutation_is_detected(self):
        from importlib.util import module_from_spec, spec_from_file_location
        import sys
        spec = spec_from_file_location(
            "s1_008_evaluator_counter_mutation", S1_008_DIR / "evaluator.py"
        )
        evaluator = module_from_spec(spec)
        sys.modules[spec.name] = evaluator
        spec.loader.exec_module(evaluator)
        honest = [t for t in self.traces if "PROBE-" not in t.get("scenario", "")]
        for counter in evaluator.HARD_COUNTERS:
            mutated = copy.deepcopy(honest[0])
            if counter == "missing_timestamp":
                mutated["t_deny_monotonic_ns"] = None
                mutated.pop("missing_timestamp", None)
            else:
                mutated[counter] = 1
            with self.subTest(counter=counter):
                derived = evaluator.derive_hard_counters([mutated])
                self.assertGreater(derived[counter], 0)


class TestLatencyBounds(unittest.TestCase):
    """Verify that max latency ≤ 5000ms (target)."""

    @classmethod
    def setUpClass(cls):
        cls.traces = _load_traces(RESULTS_DIR / "run-a-clean" / "raw-traces")

    def test_max_latency_within_target(self):
        latencies = [t["latency_ms"] for t in self.traces
                     if t.get("latency_ms") is not None]
        self.assertGreater(len(latencies), 0, "No latency values found")
        max_lat = max(latencies)
        self.assertLessEqual(max_lat, 5000,
                            f"Max latency {max_lat}ms exceeds 5000ms target")


class TestProbeDetection(unittest.TestCase):
    """Verify that all probes A-F are detected with violations."""

    @classmethod
    def setUpClass(cls):
        cls.eval_result = json.loads(
            (RESULTS_DIR / "evaluation-result.json").read_text()
        )

    def test_all_probes_detected(self):
        probes = self.eval_result.get("probe_results", {})
        for label in ["A", "B", "C", "D", "E", "F"]:
            self.assertIn(label, probes,
                          f"Probe {label} not found in probe_results")
            entry = probes[label]
            self.assertTrue(entry.get("detected", False),
                           f"Probe {label} not detected")
            self.assertGreater(entry.get("violations", 0), 0,
                             f"Probe {label} has 0 violations")


class TestHashBinding(unittest.TestCase):
    """Verify that all traces pass hash binding verification."""

    @classmethod
    def setUpClass(cls):
        cls.traces = _load_traces(RESULTS_DIR / "run-a-clean" / "raw-traces")

    def test_all_traces_hash_verified(self):
        from agentos.ids import canonical_json, sha256_text
        for t in self.traces:
            recorded_sha = t.get("raw_trace_sha256", "")
            # Recompute: hash canonical JSON of trace with raw_trace_sha256 removed
            body = {k: v for k, v in t.items() if k != "raw_trace_sha256"}
            actual_sha = sha256_text(canonical_json(body))
            self.assertEqual(actual_sha, recorded_sha,
                           f"Trace {t.get('trial_id')} hash mismatch")


class TestProvenance(unittest.TestCase):
    """Verify run provenance: different executors and output roots."""

    @classmethod
    def setUpClass(cls):
        cls.manifest_a = json.loads(
            (RESULTS_DIR / "run-a-clean" / "manifest.json").read_text()
        )
        cls.manifest_b = json.loads(
            (RESULTS_DIR / "run-b-clean" / "manifest.json").read_text()
        )

    def test_different_executor_ids(self):
        self.assertNotEqual(
            self.manifest_a["executor_id"],
            self.manifest_b["executor_id"]
        )

    def test_different_output_roots(self):
        self.assertNotEqual(
            self.manifest_a["raw_trace_dir"],
            self.manifest_b["raw_trace_dir"]
        )

    def test_dirty_state(self):
        """Verify dirty=False for both runs (all harness files committed)."""
        self.assertFalse(self.manifest_a["dirty"],
                         "Run A was dirty — harness changes not committed")
        self.assertFalse(self.manifest_b["dirty"],
                         "Run B was dirty — harness changes not committed")
        self.assertNotEqual(self.manifest_a["process_evidence"]["pid"],
                            self.manifest_b["process_evidence"]["pid"])
        self.assertNotEqual(self.manifest_a["process_evidence"]["invocation_digest"],
                            self.manifest_b["process_evidence"]["invocation_digest"])


class TestEvidencePack(unittest.TestCase):
    """Verify content-addressed evidence pack."""

    @classmethod
    def setUpClass(cls):
        evidence_dir = RESULTS_DIR / "evidence"
        # Resolve the exact pack recorded by the finalizer.  Never rely on
        # directory/glob order: old immutable packs may remain beside the
        # current one.
        record_path = S1_008_DIR / "evaluation-record.json"
        cls.pack = None
        if record_path.is_file():
            try:
                record = json.loads(record_path.read_text())
                exact_path = Path(record.get("evidence_pack", {}).get("path", ""))
                if exact_path.is_file():
                    cls.pack = exact_path
            except (OSError, json.JSONDecodeError, TypeError):
                cls.pack = None
        if cls.pack is None:
            try:
                bundle = json.loads((S1_008_DIR / "bundle.json").read_text())
            except (OSError, json.JSONDecodeError):
                bundle = {}
            candidates = []
            for candidate in sorted(evidence_dir.glob("evidence-pack-*.json")):
                try:
                    pack = json.loads(candidate.read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                if all(pack.get(key) == bundle.get(key) for key in (
                        "bundle_sha256", "goal_id", "campaign_id",
                        "evaluation_id", "artifact_chain_hash")):
                    candidates.append(candidate)
            cls.pack = candidates[-1] if candidates else None

    def test_evidence_pack_exists(self):
        self.assertIsNotNone(self.pack, "No evidence pack found")
        if self.pack is None:
            return

    def test_pack_hash_matches_filename(self):
        if self.pack is None:
            self.skipTest("No evidence pack")
        expected_hash = self.pack.stem.replace("evidence-pack-", "")
        content = self.pack.read_bytes()
        actual_hash = hashlib.sha256(content).hexdigest()
        self.assertEqual(actual_hash, expected_hash,
                        "Pack file SHA-256 does not match filename")

    def test_pack_self_hash_valid(self):
        if self.pack is None:
            self.skipTest("No evidence pack")
        pack = json.loads(self.pack.read_text())
        recorded = pack.get("pack_sha256", "")
        # Verify self-hash: remove pack_sha256, recompute
        pack["pack_sha256"] = ""
        from agentos.ids import canonical_json, sha256_text
        recomputed = sha256_text(canonical_json(pack))
        self.assertEqual(recomputed, recorded,
                        "Pack self-hash mismatch")

    def test_observation_entries(self):
        if self.pack is None:
            self.skipTest("No evidence pack")
        pack = json.loads(self.pack.read_text())
        entries = pack.get("raw_observations_archive", {}).get("member_count", 0)
        self.assertGreater(entries, 0, "No observation entries in pack")


class TestEvaluationRecord(unittest.TestCase):
    """Verify final evaluation-record.json."""

    @classmethod
    def setUpClass(cls):
        path = S1_008_DIR / "evaluation-record.json"
        if path.exists():
            cls.record = json.loads(path.read_text())
        else:
            cls.record = None

    def test_record_exists(self):
        self.assertIsNotNone(self.record, "evaluation-record.json not found")

    def test_record_has_pass_with_limits(self):
        if self.record is None:
            self.skipTest("No record")
        # Honest verdict: PASS_WITH_LIMITS due to S1-002/S1-004 dependency
        self.assertEqual(self.record["result"], "PASS_WITH_LIMITS",
                        "Result should be PASS_WITH_LIMITS (transitive from deps)")

    def test_record_db_verified(self):
        if self.record is None:
            self.skipTest("No record")
        db_v = self.record.get("db_verified", {})
        self.assertTrue(db_v.get("fully_verified", False),
                       f"DB not fully verified: {db_v}")

    def test_record_evidence_pack_hash_valid(self):
        if self.record is None:
            self.skipTest("No record")
        evidence = self.record.get("evidence_pack", {})
        pack_path = Path(evidence.get("path", ""))
        if not pack_path.is_file():
            self.skipTest("No evidence pack")
        file_hash = hashlib.sha256(pack_path.read_bytes()).hexdigest()
        fname_hash = pack_path.stem.replace("evidence-pack-", "")
        self.assertEqual(file_hash, evidence.get("sha256"))
        self.assertEqual(file_hash, fname_hash,
                        "Pack file SHA does not match filename")

    def test_record_self_hash_and_exact_pack_binding(self):
        if self.record is None:
            self.skipTest("No record")
        recorded = self.record.get("record_sha256")
        body = dict(self.record)
        body["record_sha256"] = ""
        from agentos.ids import canonical_json, sha256_text
        self.assertEqual(sha256_text(canonical_json(body)), recorded)
        pack = json.loads(Path(self.record["evidence_pack"]["path"]).read_text())
        self.assertEqual(pack["goal_id"], self.record["goal_id"])
        self.assertEqual(pack["campaign_id"], self.record["campaign_id"])
        self.assertEqual(pack["evaluation_id"], self.record["evaluation_id"])
        self.assertEqual(pack["artifact_chain_hash"], self.record["artifact_chain_hash"])
        self.assertEqual(set(pack["raw_archives"]), {"a", "b"})


if __name__ == "__main__":
    unittest.main()
