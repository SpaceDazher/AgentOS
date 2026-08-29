"""Unit tests for sloqual foundations: stats, contract freeze/verify,
durable revocation ledger semantics, environment manifest capture."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agentos.db import open_db  # noqa: E402
from agentos.gateway import CapabilityDenied, ToolContract, ToolGateway  # noqa: E402
from agentos.journal import Journal  # noqa: E402
from agentos.sloqual import contract as sq_contract  # noqa: E402
from agentos.sloqual import environment as sq_environment  # noqa: E402
from agentos.sloqual import postprocess as sq_postprocess  # noqa: E402
from agentos.sloqual import revocation as sq_revocation  # noqa: E402
from agentos.sloqual.openloop import OpenLoopRunner, build_schedule  # noqa: E402
from agentos.sloqual.stats import (  # noqa: E402
    MetricRecord, bootstrap_ci, percentile_nearest_rank, proportion_record,
    sufficient_power, wilson_interval)


class StatsTest(unittest.TestCase):
    def test_percentile_nearest_rank_matches_benchmark_convention(self):
        values = [float(i) for i in range(1, 101)]  # 1..100
        self.assertEqual(percentile_nearest_rank(values, 0.50), 50.0)
        self.assertEqual(percentile_nearest_rank(values, 0.95), 95.0)
        self.assertEqual(percentile_nearest_rank(values, 0.99), 99.0)
        self.assertEqual(percentile_nearest_rank([], 0.95), 0.0)

    def test_bootstrap_ci_is_deterministic_and_contains_median(self):
        values = [10.0 + (i % 7) for i in range(500)]
        lo1, hi1 = bootstrap_ci(values, quantile=0.5, b=200, seed_parts=("a",))
        lo2, hi2 = bootstrap_ci(values, quantile=0.5, b=200, seed_parts=("a",))
        self.assertEqual((lo1, hi1), (lo2, hi2))
        self.assertLessEqual(lo1, 13.0)
        self.assertGreaterEqual(hi1, 13.0)

    def test_wilson_interval_bounds(self):
        lo, hi = wilson_interval(0, 100)
        self.assertEqual(lo, 0.0)
        self.assertLess(hi, 0.06)
        lo, hi = wilson_interval(97, 100)
        self.assertGreater(lo, 0.9)
        self.assertLessEqual(hi, 1.0)

    def test_proportion_record_shape_and_metric_guard(self):
        record = proportion_record("availability", 999, 1000)
        self.assertEqual(record["count"], 1000)
        self.assertEqual(record["ci_method"], "wilson_score_level0.95")
        metric = MetricRecord("lat_ms", "ms", [1.0, 2.0, 3.0])
        shaped = metric.to_dict(include_raw=False)
        for key in ("count", "p50", "p95", "p99", "max", "ci95_low",
                    "ci95_high", "ci_method"):
            self.assertIn(key, shaped)
        with self.assertRaises(ValueError):
            MetricRecord("bad", "fraction", [0.5], kind="proportion").to_dict()

    def test_sufficient_power(self):
        self.assertTrue(sufficient_power({"count": 1000}, 1000))
        self.assertFalse(sufficient_power({"count": 999}, 1000))
        self.assertFalse(sufficient_power({}, 1))


def _minimal_contract() -> dict:
    return {
        "schema": "agentos.slo-contract/v1",
        "slo_id": "TEST-SLO",
        "version": "1.0.0",
        "extends": [],
        "mandatory_scenarios": ["warm_steady_state"],
        "sli_definitions": [{"id": "latency_end_to_end_ms"}],
        "invariants": [{"id": "false_acceptance_count", "threshold": 0}],
        "slos": [{"sli": "latency_end_to_end_ms.p95", "threshold": "<=20 ms"}],
        "sampling": {"min_seeds_per_scenario": 5},
        "confidence_intervals": {"level": 0.95},
        "verdict_rules": {"PASS": "all pass"},
        "change_policy": "new version on any change",
    }


class ContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "slo-contract.json"
        self.path.write_text(json.dumps(_minimal_contract()), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_freeze_and_verify_roundtrip(self):
        stamped_hash = sq_contract.freeze_contract(self.path, timestamp="2026-08-24T00:00:00Z")
        contract, verify_hash = sq_contract.verify_frozen(self.path)
        self.assertEqual(stamped_hash, verify_hash)
        self.assertEqual(contract["frozen_at"], "2026-08-24T00:00:00Z")
        self.assertNotIn("frozen_at_placeholder", contract)

    def test_tampering_breaks_verification(self):
        sq_contract.freeze_contract(self.path, timestamp="2026-08-24T00:00:00Z")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["slos"][0]["threshold"] = "<=999 ms"
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(sq_contract.ContractViolation):
            sq_contract.verify_frozen(self.path)

    def test_missing_required_keys_rejected(self):
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            sq_contract.load_contract(bad)

    def test_double_freeze_rejected(self):
        sq_contract.freeze_contract(self.path, timestamp="2026-08-24T00:00:00Z")
        with self.assertRaises(ValueError):
            sq_contract.freeze_contract(self.path, timestamp="2026-08-24T00:00:01Z")


class RevocationLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "revocation-test.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_grant_deny_revoke_no_resurrection_across_connections(self):
        db = open_db(self.db_path)
        conn = db.conn
        grant_id = sq_revocation.grant(conn, subject="run-A", capability="resource.read")
        self.assertTrue(sq_revocation.is_granted(conn, "run-A", "resource.read"))
        info = sq_revocation.revoke_durable(conn, grant_id, actor="tester")
        self.assertFalse(sq_revocation.is_granted(conn, "run-A", "resource.read"))
        self.assertGreater(info["commit_perf_ns"], 0)
        conn.close()
        # fresh connection == process restart view of durable state
        db2 = open_db(self.db_path)
        self.assertTrue(sq_revocation.resurrection_check(db2.conn, grant_id))
        self.assertEqual(sq_revocation.durable_capabilities(db2.conn, "run-A"), set())
        db2.conn.close()

    def test_grant_rows_immutable_except_revoke(self):
        db = open_db(self.db_path)
        grant_id = sq_revocation.grant(db.conn, subject="run-B", capability="cap.x")
        with self.assertRaises(sqlite3.Error):
            db.conn.execute(
                "UPDATE sloqual_capability_grant SET capability='cap.y' WHERE grant_id=?",
                (grant_id,))
        db.conn.close()

    def test_gateway_enforcement_observes_durable_revocation(self):
        from agentos.engine import Engine

        db = open_db(self.db_path)
        journal = Journal(db)
        gateway = ToolGateway(db, journal)

        def handler(**kwargs):
            return {"ok": True}

        gateway.register(ToolContract(
            name="qual.read", version="1.0.0",
            input_schema={"type": "object"}, output_schema={"type": "object"},
            required_capability="resource.read", effect_class="read",
            idempotency="none", handler=handler))
        engine = Engine(db, Path(self.tmp.name))
        goal_id = engine.create_goal("revocation gate test", constraints={})
        engine.refine_spec(goal_id, "spec", criteria=[
            {"criterion_id": "c1", "kind": "tests_present"}])
        engine.activate_goal(goal_id)
        engine.plan_tasks(goal_id, [
            {"key": "k1", "title": "T", "definition_of_done": "d"}])
        engine.schedule_ready_tasks(goal_id)
        task_id = db.conn.execute(
            "SELECT id FROM task WHERE goal_id=? AND status='READY'",
            (goal_id,)).fetchone()[0]
        _, base_ctx = engine.open_run(task_id, lease_minutes=5)
        ctx = sq_revocation.LedgerRunContext(
            db.conn, run_id=base_ctx.run_id, goal_id=goal_id, task_id=task_id,
            lease_owner=base_ctx.lease_owner,
            workspace_path=base_ctx.workspace_path,
            subject=base_ctx.run_id)
        resolved = gateway.resolve("qual.read", "1.0.0")
        grant_id = sq_revocation.grant(
            db.conn, subject=base_ctx.run_id, capability="resource.read")
        result = gateway.invoke(ctx, resolved, {})
        self.assertTrue(result["ok"])
        sq_revocation.revoke_durable(db.conn, grant_id, actor="tester")
        with self.assertRaises(CapabilityDenied):
            gateway.invoke(ctx, resolved, {})
        db.conn.close()


class EnvironmentManifestTest(unittest.TestCase):
    def test_capture_shape_and_input_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_file = root / "input.txt"
            input_file.write_text("payload", encoding="utf-8")
            manifest = sq_environment.capture(
                repo_root=root, work_root=root, db_path=None,
                topology={"scheduler_processes": 1},
                input_files=[input_file],
                capacity_mapping={"throughput_ratio": 0.4})
            import hashlib
            expected = hashlib.sha256(input_file.read_bytes()).hexdigest()
            self.assertEqual(manifest["input_file_hashes"]["input.txt"], expected)
            for key in ("schema", "runner_version", "cpu", "ram_total_bytes",
                        "disk", "sqlite", "time_sync", "production_like_proof"):
                self.assertIn(key, manifest)
            self.assertEqual(manifest["process_topology"]["scheduler_processes"], 1)

    def test_secret_marker_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                sq_environment.capture(
                    repo_root=root, work_root=root, db_path=None,
                    capacity_mapping={"api_key_marker": "accidental"})

    def test_manifest_hash_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = sq_environment.capture(repo_root=root, work_root=root, db_path=None)
            h1 = sq_environment.manifest_hash(manifest)
            h2 = sq_environment.manifest_hash(manifest)
            self.assertEqual(h1, h2)


class OpenLoopBatchTest(unittest.TestCase):
    def test_scheduled_requests_are_dispatched_in_bounded_batches(self):
        schedule = build_schedule(
            count=100, rate_events_per_second=10_000, seed=19,
            fixed_rate=True)
        batch_sizes = []

        def dispatch_batch(indexes):
            batch_sizes.append(len(indexes))
            return [("SUCCEEDED", {"index": i}) for i in indexes]

        result = OpenLoopRunner(max_inflight=128).run_batched(
            schedule, dispatch_batch_fn=dispatch_batch,
            max_batch_size=16, batch_window_s=0.001)

        self.assertEqual(len(result.observations), 100)
        self.assertEqual(result.not_started, 0)
        self.assertTrue(batch_sizes)
        self.assertLessEqual(max(batch_sizes), 16)
        self.assertEqual(sum(batch_sizes), 100)
        self.assertTrue(all(o.outcome == "SUCCEEDED"
                            for o in result.observations))
        self.assertTrue(all(
            o.dispatch_abs_ns >= result.schedule_origin_ns
            + o.scheduled_offset_ns
            for o in result.observations))


class PostprocessTest(unittest.TestCase):
    @staticmethod
    def _seed_ticket(root: Path) -> Path:
        ticket = root / "ticket"
        for run_id in ("run-a", "run-b"):
            scenario = ticket / "raw" / run_id / "scenario"
            scenario.mkdir(parents=True)
            (scenario / "seed-11.json").write_text(
                json.dumps({"run_id": run_id}), encoding="utf-8")
            (scenario / "events.jsonl").write_text(
                json.dumps({"run_id": run_id}) + "\n", encoding="utf-8")
            (scenario / "pressure.bin").write_bytes(b"reproducible load scratch")
            (scenario / "scratch.db-wal").write_bytes(b"sqlite scratch")
        stale = ticket / "traces" / "old-run"
        stale.mkdir(parents=True)
        (stale / "stale.jsonl").write_text("{}\n", encoding="utf-8")
        return ticket

    def test_manifest_is_scoped_to_selected_run_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            ticket = self._seed_ticket(Path(tmp))
            self.assertEqual(sq_postprocess.main([
                "--ticket", str(ticket), "--run-ids", "run-a", "run-b"]), 0)
            manifest = json.loads(
                (ticket / "artifact-manifest.json").read_text(encoding="utf-8"))
            paths = [entry["path"] for entry in manifest["artifacts"]]
            self.assertFalse(any("old-run" in path for path in paths))
            self.assertFalse(any(path.endswith((".bin", ".db-wal"))
                                 for path in paths))
            self.assertTrue(all(
                path.startswith(("raw/run-a/", "raw/run-b/",
                                 "traces/run-a/", "traces/run-b/"))
                for path in paths))

    def test_identical_rebuild_does_not_delete_live_trace_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            ticket = self._seed_ticket(Path(tmp))
            args = ["--ticket", str(ticket), "--run-ids", "run-a", "run-b"]
            self.assertEqual(sq_postprocess.main(args), 0)
            with mock.patch.object(
                    sq_postprocess.shutil, "rmtree",
                    side_effect=PermissionError("live trace is locked")):
                self.assertEqual(sq_postprocess.main(args), 0)

    def test_same_stat_trace_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ticket = self._seed_ticket(Path(tmp))
            args = ["--ticket", str(ticket), "--run-ids", "run-a", "run-b"]
            self.assertEqual(sq_postprocess.main(args), 0)
            source = ticket / "raw" / "run-a" / "scenario" / "events.jsonl"
            trace = ticket / "traces" / "run-a" / "scenario" / "events.jsonl"
            trace.write_bytes(b"x" * source.stat().st_size)
            source_stat = source.stat()
            os.utime(trace, ns=(source_stat.st_atime_ns,
                                source_stat.st_mtime_ns))
            with self.assertRaisesRegex(RuntimeError, "trace copy differs"):
                sq_postprocess.main(args)


if __name__ == "__main__":
    unittest.main()
