"""Fail-closed gate semantics of the SLOQUAL comparator (synthetic fixtures)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agentos.sloqual import compare as cmp_mod  # noqa: E402
from agentos.sloqual.contract import freeze_contract  # noqa: E402
from agentos.sloqual.environment import (  # noqa: E402
    RUNNER_VERSION, capture, manifest_hash, write_manifest)

SCENARIOS = cmp_mod.REQUIRED_SCENARIOS
SEEDS = cmp_mod.REGISTERED_SEEDS


def _latency_record(p95: float, ci_hi: float | None = None) -> dict:
    return {
        "name": "x", "unit": "ms", "kind": "latency", "count": 1200,
        "min": p95 / 4, "median": p95 / 2, "mean": p95 / 2, "p50": p95 / 2,
        "p95": p95, "p99": p95 * 1.2, "max": p95 * 1.5,
        "ci95_low": p95 * 0.8,
        "ci95_high": ci_hi if ci_hi is not None else p95 * 1.05,
        "ci_method": "bootstrap_percentile_B2000_level0.95",
        "raw": [p95] * 50,
    }


def _proportion(value: float) -> dict:
    return {"name": "x", "unit": "fraction", "kind": "proportion",
            "count": 1000, "successes": int(value * 1000), "value": value,
            "ci95_low": max(0.0, value - 0.01),
            "ci95_high": min(1.0, value + 0.01),
            "ci_method": "wilson_score_level0.95", "raw": [1000]}


def _value(v: float, unit: str = "units") -> dict:
    return {"name": "x", "unit": unit, "kind": "value", "count": 1, "value": v}


def _normal_metrics() -> dict:
    return {
        "latency_end_to_end_ms": _latency_record(12.0),
        "service_time_ms": _latency_record(6.0),
        "queue_wait_ms": _latency_record(3.0),
        "throughput_achieved_events_per_second": _value(35.5),
        "error_rate_fraction": _proportion(0.004),
        "availability_fraction": _proportion(0.9996),
        "db_transaction_latency_ms": _latency_record(1.5),
        "audit_journal_latency_ms": _latency_record(0.9),
        "counts": {"dispatched": 1020, "succeeded": 1015},
    }


def _revocation_metrics(*, max_ms: float = 40.0, trials: int = 21,
                        violations: int = 0, with_raw: bool = True) -> dict:
    return {
        "revocation_enforcement_latency_ms": {
            "name": "rev", "unit": "ms", "kind": "latency", "count": trials,
            "p50": max_ms / 2, "p95": max_ms * 0.9, "p99": max_ms,
            "max": max_ms, "mean": max_ms / 2, "min": 1.0,
            "ci95_low": 1.0, "ci95_high": max_ms,
            "ci_method": "bootstrap_percentile_B2000_level0.95",
            "raw": [max_ms] * trials if with_raw else [],
        },
        "trials_total": trials,
        "censored_trials_over_6s": 0,
        "allow_after_commit_violations": violations,
        "resurrection_checks": [{"still_denies_after_restart": True}],
        "gate_all_trials_le_5000ms": violations == 0 and max_ms <= 5000.0,
    }


class FixtureBuilder:
    def __init__(self, root: Path):
        self.root = root
        self.ticket = root / "ticket"
        self.ticket.mkdir(parents=True)
        contract = self._contract_fixture()
        path = self.ticket / "slo-contract.json"
        path.write_text(json.dumps(contract), encoding="utf-8")
        self.contract_hash = freeze_contract(path)

    @staticmethod
    def _contract_fixture() -> dict:
        return {
            "schema": "agentos.slo-contract/v1", "slo_id": "T", "version": "1.0.0",
            "extends": [], "mandatory_scenarios": list(SCENARIOS),
            "sli_definitions": [],
            "invariants": [{"id": k, "threshold": 0} for k in (
                "false_acceptance_count", "lost_terminal_transitions_count",
                "audit_chain_violations_count",
                "capability_scope_violations_count",
                "stale_lease_executions_count",
                "side_effect_duplication_count",
                "confirmed_data_loss_count",
                "secrets_in_artifacts_count")],
            "sampling": {}, "confidence_intervals": {},
            "verdict_rules": {}, "change_policy": "x",
            "frozen_at_placeholder": "x",
            "slos": [
                {"sli": "latency_end_to_end_ms.p95",
                 "scope": "warm_steady_state@nominal", "threshold": "<=20.0 ms",
                 "requires_owner_confirmation": True},
                {"sli": "throughput_achieved_events_per_second",
                 "scope": "warm_steady_state@nominal", "threshold": ">=34.0 events/s",
                 "requires_owner_confirmation": False},
                {"sli": "availability_fraction", "scope": "all non-injected windows", "threshold": ">=0.999",
                 "requires_owner_confirmation": True},
                {"sli": "error_rate_fraction", "scope": "all non-injected windows", "threshold": "<=0.01",
                 "requires_owner_confirmation": True},
                {"sli": "latency_end_to_end_ms.p95", "scope": "burst@10x_peak",
                 "threshold": "<=200.0 ms", "requires_owner_confirmation": True},
                {"sli": "recovery_time_seconds",
                 "scope": "worker_restart|scheduler_restart|full_restart|net*_faults|provider_*",
                 "threshold": "<=30.0 s", "requires_owner_confirmation": True},
                {"sli": "db_transaction_latency_ms.p95",
                 "scope": "warm_steady_state@nominal", "threshold": "<=10.0 ms",
                 "requires_owner_confirmation": True},
                {"sli": "audit_journal_latency_ms.p95",
                 "scope": "warm_steady_state@nominal", "threshold": "<=10.0 ms",
                 "requires_owner_confirmation": True},
                {"sli": "startup_to_first_success_ms",
                 "scope": "provider_*", "threshold": "<=500.0 ms",
                 "requires_owner_confirmation": True},
                {"sli": "revocation_enforcement_latency_ms",
                 "scope": "revocation_under_load", "threshold": "<=5000.0 ms",
                 "statistic_for_verdict": "max",
                 "requires_owner_confirmation": False},
            ],
        }

    def add_run(self, run_id: str, *, revocation_max_ms: float = 40.0,
                revocation_trials: int = 105, revocation_violations: int = 0,
                drop_seed: int | None = None, corrupt_contract_hash: bool = False,
                strip_ci_from: str | None = None,
                empty_metrics_for: str | None = None,
                invariant_violation_in: str | None = None,
                high_latency_for: str | None = None,
                secret_marker_in: str | None = None,
                bad_commit_for: str | None = None,
                revocation_trials_default: int = 105,
                env_capacity_mapping: dict | None = None,
                wrong_env_hash_for: str | None = None):
        run_dir = self.root / "work" / run_id
        manifest = capture(repo_root=self.root, work_root=run_dir,
                           db_path=None,
                           capacity_mapping=(
                               env_capacity_mapping
                               if env_capacity_mapping is not None
                               else {"cpu_ratio": 1.2}))
        write_manifest(manifest, run_dir / "environment-manifest.json")
        env_hash = manifest_hash(manifest)
        for scenario in SCENARIOS:
            for seed in SEEDS:
                if seed == drop_seed:
                    continue
                metrics = _normal_metrics()
                trials_payload = None
                result_extra: dict = {
                    "invariants": {k: 0 for k in (
                        "false_acceptance_count",
                        "lost_terminal_transitions_count",
                        "audit_chain_violations_count",
                        "capability_scope_violations_count",
                        "stale_lease_executions_count",
                        "side_effect_duplication_count",
                        "confirmed_data_loss_count",
                        "secrets_in_artifacts_count")}}
                if scenario == "revocation_under_load":
                    metrics = _revocation_metrics(
                        max_ms=revocation_max_ms,
                        trials=revocation_trials,
                        violations=revocation_violations)
                    trials_payload = [
                        {"trial": i, "enforcement_latency_ms": revocation_max_ms}
                        for i in range(revocation_trials)]
                if scenario in ("cold_start",):
                    metrics["startup_to_first_success_ms"] = _value(210.0, "ms")
                if scenario in ("worker_restart", "scheduler_restart",
                                "full_restart"):
                    metrics["recovery_time_seconds"] = _value(2.5, "s")
                if scenario == "burst":
                    metrics = {"phases": {"burst": {
                        "latency_end_to_end_ms": _latency_record(90.0)}}}
                if high_latency_for == scenario:
                    metrics["latency_end_to_end_ms"] = _latency_record(25.0)
                if secret_marker_in == scenario:
                    metrics["_operator_note"] = {
                        "name": "note", "unit": "text", "kind": "value",
                        "count": 1, "value": "password=TOPSECRET"}
                if strip_ci_from and scenario == strip_ci_from:
                    metrics["queue_wait_ms"].pop("ci95_high")
                if empty_metrics_for and scenario == empty_metrics_for:
                    metrics = {}
                if invariant_violation_in and scenario == invariant_violation_in:
                    result_extra["invariants"]["lost_terminal_transitions_count"] = 2
                payload = {
                    "schema": "agentos.sloqual-result/v1",
                    "runner_version": RUNNER_VERSION,
                    "run_id": run_id, "scenario_id": scenario, "seed": seed,
                    "commit_sha": (
                        ("f" * 40) if bad_commit_for == scenario else ("a" * 40)),
                    "contract_sha256": (
                        "0" * 64 if corrupt_contract_hash else self.contract_hash),
                    "environment_hash": (
                        "bad" if wrong_env_hash_for == scenario else env_hash),
                    "result": {**{"metrics": metrics,
                                  "_power_insufficient": False},
                               **result_extra},
                }
                if trials_payload is not None:
                    payload["result"]["trials"] = trials_payload
                out = run_dir / scenario / f"seed-{seed}.json"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(payload), encoding="utf-8")


def run_compare(builder: FixtureBuilder, run_ids=("run-A", "run-B")) -> dict:
    return cmp_mod.compare(builder.ticket, list(run_ids),
                           work_root=builder.root / "work",
                           repo_src=builder.root)


class ComparatorGateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.builder = FixtureBuilder(Path(tmp.name))

    def test_empty_measurement_set_can_never_pass(self):
        result = cmp_mod.compare(self.builder.ticket, ["only"],
                                 work_root=self.builder.root / "nowhere",
                                 repo_src=self.builder.root)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("missing-independent-rerun", result["fail_conditions"])

    def test_full_happy_path_yields_pass_with_limits_not_fail(self):
        self.builder.add_run("run-A", revocation_trials=25)
        self.builder.add_run("run-B", revocation_trials=25)
        result = run_compare(self.builder)
        self.assertEqual(result["fail_conditions"], [])
        self.assertIn("owner-confirmation-pending:thresholds-marked-in-contract",
                      result["limits"])
        self.assertGreaterEqual(result["revocation"]["total_trials_main_run"], 100)

    def test_contract_modified_after_launch_rejected(self):
        self.builder.add_run("run-A", corrupt_contract_hash=True)
        self.builder.add_run("run-B")
        result = run_compare(self.builder)
        self.assertTrue(any(r.startswith("contract-modified-after-launch")
                            for r in result["fail_conditions"]))
        self.assertEqual(result["verdict"], "FAIL")

    def test_revocation_over_limit_fails(self):
        self.builder.add_run("run-A", revocation_max_ms=5200.0)
        self.builder.add_run("run-B")
        result = run_compare(self.builder)
        self.assertTrue(any(r.startswith("revocation-latency-over-limit")
                            for r in result["fail_conditions"]))
        self.assertEqual(result["verdict"], "FAIL")

    def test_post_revoke_side_effect_fails(self):
        self.builder.add_run("run-A", revocation_violations=1)
        self.builder.add_run("run-B")
        result = run_compare(self.builder)
        self.assertTrue(any(r.startswith("post-revoke-forbidden-side-effects")
                            for r in result["fail_conditions"]))
        self.assertEqual(result["verdict"], "FAIL")

    def test_missing_ci_is_rejected(self):
        self.builder.add_run("run-A", strip_ci_from="soak")
        self.builder.add_run("run-B")
        result = run_compare(self.builder)
        self.assertTrue(any(r.startswith("missing-CI:") for r in
                            result["fail_conditions"]))
        self.assertEqual(result["verdict"], "FAIL")

    def test_empty_result_is_rejected(self):
        self.builder.add_run("run-A", empty_metrics_for="db_growth")
        self.builder.add_run("run-B")
        result = run_compare(self.builder)
        self.assertTrue(any(r.startswith("empty-result:") for r in
                            result["fail_conditions"]))
        self.assertEqual(result["verdict"], "FAIL")

    def test_missing_seed_is_rejected(self):
        self.builder.add_run("run-A", drop_seed=33)
        self.builder.add_run("run-B")
        result = run_compare(self.builder)
        self.assertTrue(any(r.startswith("missing-seed:") for r in
                            result["fail_conditions"]))
        self.assertEqual(result["verdict"], "FAIL")

    def test_duplicate_run_ids_rejected(self):
        self.builder.add_run("run-A")
        result = run_compare(self.builder, run_ids=["run-A", "run-A"])
        self.assertIn("duplicated-run-id", result["fail_conditions"])
        self.assertEqual(result["verdict"], "FAIL")

    def test_insufficient_production_like_profile_blocks_full_pass(self):
        self.builder.add_run("run-A", env_capacity_mapping={
            "cpu_ratio": 1.2, "storage_projection_ratio": 0.02,
            "server_class_storage": False})
        self.builder.add_run("run-B", env_capacity_mapping={})
        result = run_compare(self.builder)
        self.assertTrue(any(r.startswith("production-like-profile-not-proven")
                            for r in result["limits"]))
        self.assertNotIn("missing-production-like-proof",
                         result["fail_conditions"])
        self.assertEqual(result["verdict"], "PASS_WITH_LIMITS")

    def test_environment_hash_mismatch_rejected(self):
        self.builder.add_run("run-A", wrong_env_hash_for="soak")
        self.builder.add_run("run-B")
        result = run_compare(self.builder)
        self.assertTrue(any(r.startswith("environment-hash-mismatch")
                            for r in result["fail_conditions"]))
        self.assertEqual(result["verdict"], "FAIL")

    def test_invariant_violation_forces_fail(self):
        self.builder.add_run("run-A", invariant_violation_in="full_restart")
        self.builder.add_run("run-B")
        result = run_compare(self.builder)
        self.assertTrue(any(r.startswith("invariant-violation:")
                            for r in result["fail_conditions"]))
        self.assertEqual(result["verdict"], "FAIL")

    def test_slo_table_resolves_real_measurements(self):
        self.builder.add_run("run-A")
        self.builder.add_run("run-B")
        result = run_compare(self.builder)
        table = result["slo_table"]
        self.assertTrue(table)
        probe_rows = [r for r in table
                      if r["scope"] == "provider_*"
                      and r["slo"] == "startup_to_first_success_ms"]
        for row in table:
            if row in probe_rows:
                self.assertEqual(row["verdict"], "NO_DATA",
                                 "cross-scope pickup must stay absent")
                continue
            self.assertNotIn(row["verdict"], ("UNKNOWN", "NO_DATA"),
                             f"unresolved SLO row: {row}")
        latency_rows = [r for r in table
                        if r["slo"] == "latency_end_to_end_ms.p95"
                        and r["scope"].startswith("warm")]
        self.assertTrue(latency_rows and latency_rows[0]["observed"] is not None)
        stray_no_data = [c for c in result["limits"]
                         if "no-data:" in c
                         and "startup_to_first_success_ms" not in c]
        self.assertEqual(stray_no_data, [])
        burst_rows = [r for r in table
                      if r["scope"].startswith("burst")]
        self.assertTrue(burst_rows and
                        burst_rows[0]["observed"] is not None,
                        "burst nested latency must resolve")

    def test_scope_without_metric_stays_no_data(self):
        # startup_to_first_success_ms exists ONLY in cold_start; a provider_*
        # scope must NOT pick it up from another scenario (no cross-pickup)
        self.builder.add_run("run-A")
        self.builder.add_run("run-B")
        result = run_compare(self.builder)
        row = [r for r in result["slo_table"]
               if r["slo"] == "startup_to_first_success_ms"][0]
        self.assertEqual(row["verdict"], "NO_DATA")

    def test_measured_slo_threshold_violation_is_hard_fail(self):
        self.builder.add_run("run-A", high_latency_for="warm_steady_state")
        self.builder.add_run("run-B")
        result = run_compare(self.builder)
        self.assertTrue(any(r.startswith("slo-threshold-violation:")
                            for r in result["fail_conditions"]))
        self.assertEqual(result["verdict"], "FAIL")

    def test_revocation_invariants_are_gated(self):
        self.builder.add_run("run-A",
                             invariant_violation_in="revocation_under_load")
        self.builder.add_run("run-B")
        result = run_compare(self.builder)
        self.assertTrue(any(r.startswith("invariant-violation:run-A:"
                                          "revocation_under_load:")
                            for r in result["fail_conditions"]))
        self.assertEqual(result["verdict"], "FAIL")

    def test_per_run_revocation_minimum_enforced(self):
        self.builder.add_run("run-A", revocation_trials=15)
        self.builder.add_run("run-B", revocation_trials=105)
        result = run_compare(self.builder)
        self.assertTrue(any(r.startswith(
            "revocation-trials-below-minimum:run-A:") for r in
            result["fail_conditions"]))
        self.assertEqual(result["verdict"], "FAIL")

    def test_commit_sha_binding_rejects_foreign_commit(self):
        self.builder.add_run("run-A", bad_commit_for="soak")
        self.builder.add_run("run-B")
        result = run_compare(self.builder)
        self.assertTrue(any(r.startswith("commit-sha-mismatch:")
                            for r in result["fail_conditions"]))
        self.assertEqual(result["verdict"], "FAIL")

    def test_secret_marker_in_results_is_a_failure(self):
        self.builder.add_run("run-A", secret_marker_in="soak")
        self.builder.add_run("run-B")
        result = run_compare(self.builder)
        self.assertTrue(any(r.startswith("secrets-in-artifacts:")
                            for r in result["fail_conditions"]))
        self.assertEqual(result["verdict"], "FAIL")

    def test_rerun_comparison_rows_carry_measurements(self):
        self.builder.add_run("run-A")
        self.builder.add_run("run-B")
        result = run_compare(self.builder)
        comp = result["rerun_comparison"]["comparisons"]
        self.assertEqual(result["rerun_comparison"]["basis"],
                         "contract-slo-matrix")
        warm = [x for x in comp if x.get("sli") == "latency_end_to_end_ms.p95"
                and str(x.get("scope", "")).startswith("warm")][0]
        self.assertGreater(warm["first"], 0.0)
        self.assertGreater(warm["rerun"], 0.0)
        self.assertIn("flagged", warm)



if __name__ == "__main__":
    unittest.main()
