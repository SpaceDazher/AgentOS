"""Fail-closed comparator for qualification runs.

Rejection list (objective §9): missing/empty results, incomplete scenario
set, missing seed, duplicated run id, contract modified after launch,
environment hash mismatch, missing raw traces, missing production-like
proof, missing independent rerun, security/correctness violations,
revocation latency > 5 s, results without CIs, incompatible runner version.
An empty measurement set can NEVER yield PASS.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from .contract import compute_self_hash, load_contract, verify_frozen
from .environment import RUNNER_VERSION, manifest_hash

REQUIRED_SCENARIOS = (
    "cold_start", "warm_steady_state", "sustained_load", "soak", "burst",
    "queue_backpressure", "provider_full_outage", "provider_degraded",
    "worker_restart", "scheduler_restart", "full_restart",
    "sqlite_lock_contention", "disk_slow_saturation", "db_growth",
    "network_faults", "revocation_under_load", "recovery_after_failures")

REGISTERED_SEEDS = (11, 22, 33, 44, 55)
MIN_REVOCATION_TRIALS = 100
REVOCATION_LIMIT_MS = 5000.0


def _load_seed_files(run_dir: Path) -> dict[str, dict[int, dict]]:
    per_scenario: dict[str, dict[int, dict]] = {}
    if not run_dir.exists():
        return per_scenario
    for seed_file in sorted(run_dir.glob("*/seed-*.json")):
        scenario_id = seed_file.parent.name
        payload = json.loads(seed_file.read_text(encoding="utf-8"))
        per_scenario.setdefault(scenario_id, {})[payload["seed"]] = payload
    return per_scenario


def _check_metric_has_ci(name: str, metric: dict) -> str | None:
    kind = metric.get("kind")
    if kind == "value":
        return None if metric.get("value") is not None else f"no-value:{name}"
    if metric.get("ci95_low") is None or metric.get("ci95_high") is None:
        return f"missing-CI:{name}"
    return None


def _iter_metric_records(node, path=""):
    if isinstance(node, dict):
        if {"count", "kind"} <= set(node.keys()) and node.get("kind") in (
                "latency", "proportion", "value"):
            yield path, node
        else:
            for key, value in node.items():
                yield from _iter_metric_records(
                    value, f"{path}.{key}" if path else key)


def _reduce_merged(records):
    """Reduce a list of per-seed metric records into one envelope record."""
    if isinstance(records, dict):
        return records
    if not records or not isinstance(records, list):
        return records
    out: dict = {}
    for key in ("kind", "unit", "name", "ci_method"):
        if isinstance(records[0], dict) and records[0].get(key) is not None:
            out[key] = records[0][key]
    for key in ("p50", "p95", "p99", "median", "mean", "value", "max"):
        values = [r.get(key) for r in records
                  if isinstance(r, dict) and r.get(key) is not None]
        out[key] = statistics.median(values) if values else None
    lows = [r.get("ci95_low") for r in records
            if isinstance(r, dict) and r.get("ci95_low") is not None]
    highs = [r.get("ci95_high") for r in records
             if isinstance(r, dict) and r.get("ci95_high") is not None]
    out["ci95_low"] = min(lows) if lows else None
    out["ci95_high"] = max(highs) if highs else None
    return out


def _evaluate_slos(contract: dict, observed_by_scenario: dict) -> tuple[list[dict], list[str]]:
    """Returns (slo_table, cannot_pass_reasons)."""
    table: list[dict] = []
    cannot_pass: list[str] = []

    def find_metric(sli_path: str, scope: str):
        scenario = scope.split("@")[0].strip() if scope else ""
        bucket = observed_by_scenario.get(scenario)
        if bucket is None and scenario in ("", "all"):
            root_metric = sli_path.split(".")[0]
            for candidate in ("warm_steady_state",
                              *observed_by_scenario.keys()):
                cand_bucket = observed_by_scenario.get(candidate)
                if cand_bucket and root_metric in cand_bucket.get("metrics", {}):
                    bucket = cand_bucket
                    break
        if not bucket:
            return None
        node = bucket.get("metrics", bucket)
        for part in sli_path.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return _reduce_merged(node)

    def threshold_parts(threshold: str):
        text = threshold.replace("ms", "").replace("events/s", "").strip()
        for op in ("<=", ">="):
            if text.startswith(op):
                try:
                    return op, float(text[len(op):].strip())
                except ValueError:
                    continue
        return None, None

    for slo in contract["slos"]:
        scope = slo.get("scope", "")
        entry = {"slo": slo["sli"], "scope": scope,
                 "threshold": slo["threshold"],
                 "requires_owner_confirmation":
                     slo.get("requires_owner_confirmation", True)}
        metric = find_metric(slo["sli"], scope)
        if metric is None:
            entry.update({"observed": None, "ci": None, "verdict": "NO_DATA"})
            cannot_pass.append(f"no-data:{slo['sli']}@{scope}")
            table.append(entry)
            continue
        statistic = ("max" if "max" in str(slo.get("statistic_for_verdict", "")).lower()
                     else "p95")
        value = metric.get(statistic, metric.get("value"))
        ci_hi = metric.get("ci95_high")
        op, bound = threshold_parts(slo["threshold"])
        verdict = "UNKNOWN"
        if value is None or bound is None:
            verdict = "UNKNOWN"
        elif op == "<=":
            point_ok = value <= bound
            ci_ok = (ci_hi is not None and ci_hi <= bound)  # CI may not hide a violation
            verdict = "PASS_CANDIDATE" if (point_ok and ci_ok) else (
                "FAIL" if not point_ok else "CI_CROSSES_THRESHOLD")
        elif op == ">=":
            point_ok = value >= bound
            ci_lo = metric.get("ci95_low")
            ci_ok = (ci_lo is not None and ci_lo >= bound)
            verdict = "PASS_CANDIDATE" if (point_ok and ci_ok) else (
                "FAIL" if not point_ok else "CI_CROSSES_THRESHOLD")
        if verdict in ("FAIL", "CI_CROSSES_THRESHOLD", "UNKNOWN"):
            cannot_pass.append(f"{slo['sli']}@{slo.get('scope','')}:{verdict}")
        entry.update({"observed": value,
                      "ci": [metric.get("ci95_low"), metric.get("ci95_high")],
                      "statistic": statistic, "verdict": verdict})
        table.append(entry)
    return table, cannot_pass


def compare(ticket_dir: Path, run_ids: list[str], *, work_root: Path,
            repo_src: Path) -> dict:
    failures: list[str] = []
    limits: list[str] = []
    ticket_dir = Path(ticket_dir)

    # --- contract integrity -------------------------------------------------
    contract, contract_hash = verify_frozen(ticket_dir / "slo-contract.json")

    if len(run_ids) < 2:
        failures.append("missing-independent-rerun")
    if len(set(run_ids)) != len(run_ids):
        failures.append("duplicated-run-id")
    if set(REQUIRED_SCENARIOS) != set(contract["mandatory_scenarios"]):
        failures.append("scenario-set-mismatch-vs-contract")

    runs: dict[str, dict[str, dict[int, dict]]] = {}
    env_hashes: dict[str, str | None] = {}
    production_like_flags: list[bool] = []
    for run_id in run_ids:
        run_dir = work_root / run_id
        runs[run_id] = _load_seed_files(run_dir)
        manifest_path = run_dir / "environment-manifest.json"
        recorded_hash = None
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            recorded_hash = manifest_hash(manifest)
            mapping = manifest.get("production_like_proof", {}).get(
                "capacity_mapping", {})
            production_like_flags.append(bool(mapping))
            if manifest.get("runner_version") != RUNNER_VERSION:
                failures.append(f"incompatible-runner-version:{run_id}")
        else:
            production_like_flags.append(False)
        env_hashes[run_id] = recorded_hash

        scenario_map = runs[run_id]
        for scenario_id in REQUIRED_SCENARIOS:
            seeds = scenario_map.get(scenario_id, {})
            if not seeds:
                failures.append(f"missing-scenario:{run_id}:{scenario_id}")
                continue
            missing = [s for s in REGISTERED_SEEDS if s not in seeds]
            if missing:
                failures.append(f"missing-seed:{run_id}:{scenario_id}:{missing}")
            for seed, payload in seeds.items():
                if payload.get("contract_sha256") != contract_hash:
                    failures.append(
                        f"contract-modified-after-launch:{run_id}:{scenario_id}:{seed}")
                if payload.get("runner_version") != RUNNER_VERSION:
                    failures.append(
                        f"incompatible-runner-version:{run_id}:{scenario_id}:{seed}")
                result = payload.get("result", {})
                metrics = result.get("metrics", {})
                if not metrics:
                    failures.append(f"empty-result:{run_id}:{scenario_id}:{seed}")
                has_raw = bool(result.get("trials")) or any(
                    m.get("raw") or m.get("values")
                    for _, m in _iter_metric_records(metrics))
                if not has_raw:
                    failures.append(
                        f"missing-raw-traces:{run_id}:{scenario_id}:{seed}")
                for path, metric in _iter_metric_records(metrics):
                    issue = _check_metric_has_ci(path, metric)
                    if issue:
                        failures.append(
                            f"{issue}:{run_id}:{scenario_id}:{seed}")

    # environment hash must be consistent inside each run's seed files
    for run_id, scenario_map in runs.items():
        for scenario_id, seeds in scenario_map.items():
            for seed, payload in seeds.items():
                recorded = payload.get("environment_hash")
                if recorded and recorded != env_hashes[run_id]:
                    failures.append(
                        f"environment-hash-mismatch:{run_id}:{scenario_id}:{seed}")
                if not recorded:
                    limits.append(f"env-hash-unrecorded:{run_id}:{scenario_id}:{seed}")

    if not any(production_like_flags):
        failures.append("missing-production-like-proof")

    # --- aggregate observed metrics per run ---------------------------------
    observed_by_scenario: dict[str, dict] = {}
    revocation_total_trials = 0
    revocation_max_ms = 0.0
    revocation_violations = 0
    invariant_totals: dict[str, int] = {}
    scale_gaps: list[str] = []

    main_run = run_ids[0]
    for scenario_id, seeds in runs.get(main_run, {}).items():
        merged_metrics: dict = {}
        for seed, payload in sorted(seeds.items()):
            metrics = payload.get("result", {}).get("metrics", {})
            for key, value in metrics.items():
                merged_metrics.setdefault(key, []).append(value)
        observed_by_scenario[scenario_id] = {"metrics": merged_metrics}
        for seed, payload in seeds.items():
            result = payload.get("result", {})
            if scenario_id != "revocation_under_load":
                for name, count in (result.get("invariants") or {}).items():
                    if isinstance(count, int) and count > 0:
                        invariant_totals[f"{scenario_id}:{name}"] = \
                            invariant_totals.get(f"{scenario_id}:{name}", 0) + count
                if result.get("completed_at_required_scale") is False:
                    scale_gaps.append(f"{scenario_id}:below-required-scale")
                profile = result.get("db_profile") or {}
                if profile and not profile.get("reached_target", True):
                    scale_gaps.append(f"{scenario_id}:db-growth-below-target")
                if result.get("metrics", {}).get("_power_insufficient"):
                    limits.append(f"insufficient-statistical-power:{scenario_id}:{seed}")
            else:
                m = result.get("metrics", {})
                revocation_total_trials += int(m.get("trials_total", 0))
                lat = m.get("revocation_enforcement_latency_ms", {})
                revocation_max_ms = max(revocation_max_ms,
                                        float(lat.get("max") or 0.0))
                revocation_violations += int(
                    m.get("allow_after_commit_violations", 0))
                if not m.get("gate_all_trials_le_5000ms", False):
                    failures.append(f"revocation-gate-not-passed:{main_run}:{seed}")
                for check in m.get("resurrection_checks", []):
                    if not check.get("still_denies_after_restart"):
                        failures.append("capability-resurrection-after-restart")
    if revocation_total_trials < MIN_REVOCATION_TRIALS:
        limits.append(
            f"revocation-trials-below-minimum:{revocation_total_trials}<{MIN_REVOCATION_TRIALS}")
    if revocation_max_ms > REVOCATION_LIMIT_MS:
        failures.append(
            f"revocation-latency-over-limit:{revocation_max_ms}ms>{REVOCATION_LIMIT_MS}ms")
    if revocation_violations > 0:
        failures.append(f"post-revoke-forbidden-side-effects:{revocation_violations}")
    for name, count in invariant_totals.items():
        failures.append(f"invariant-violation:{name}={count}")
    for gap in scale_gaps:
        limits.append(gap)

    slo_table, cannot_pass = _evaluate_slos(contract, observed_by_scenario)
    if any(row["requires_owner_confirmation"] for row in slo_table):
        limits.append("owner-confirmation-pending:thresholds-marked-in-contract")

    rerun_summary = _compare_runs(runs)

    verdict = "PASS"
    if failures:
        verdict = "FAIL"
    elif cannot_pass or limits:
        verdict = "PASS_WITH_LIMITS"
    return {
        "schema": "agentos.sloqual-compare/v1",
        "verdict": verdict,
        "contract_sha256": contract_hash,
        "contract_self_hash_recomputed": compute_self_hash(contract),
        "run_ids": run_ids,
        "fail_conditions": sorted(set(failures)),
        "limits": sorted(set(limits + [
            f"slo-cannot-pass:{reason}" for reason in cannot_pass])),
        "slo_table": slo_table,
        "invariant_totals_main_run": invariant_totals,
        "revocation": {
            "total_trials_main_run": revocation_total_trials,
            "max_observed_ms": revocation_max_ms,
            "limit_ms": REVOCATION_LIMIT_MS,
            "violations": revocation_violations},
        "rerun_comparison": rerun_summary,
    }


def _p95_of_seed_metrics(payloads: list[dict], metric_path: tuple[str, ...]) -> float | None:
    values = []
    for payload in payloads:
        node = payload.get("result", {}).get("metrics", {})
        for part in metric_path:
            node = node.get(part, {}) if isinstance(node, dict) else {}
        if isinstance(node, dict) and node.get("p95") is not None:
            values.append(float(node["p95"]))
        elif isinstance(node, dict) and node.get("value") is not None:
            values.append(float(node["value"]))
    return statistics.median(values) if values else None


def _compare_runs(runs: dict[str, dict[str, dict[int, dict]]]) -> dict:
    run_ids = list(runs.keys())
    if len(run_ids) < 2:
        return {"status": "rerun-missing"}
    first, second = run_ids[0], run_ids[1]
    comparisons = []
    for scenario_id in REQUIRED_SCENARIOS:
        seeds_a = runs[first].get(scenario_id, {})
        seeds_b = runs[second].get(scenario_id, {})
        common = sorted(set(seeds_a) & set(seeds_b))
        if not common:
            comparisons.append({"scenario": scenario_id, "status": "no-common-seeds"})
            continue
        payloads_a = [seeds_a[s] for s in common]
        payloads_b = [seeds_b[s] for s in common]
        row: dict = {"scenario": scenario_id, "seeds_compared": common}
        for label, path in (("e2e_p95", ("latency_end_to_end_ms", "p95")),
                            ("throughput", ("throughput_achieved_events_per_second", "value")),
                            ("availability", ("availability_fraction", "value"))):
            va = _p95_of_seed_metrics(payloads_a, path)
            vb = _p95_of_seed_metrics(payloads_b, path)
            if va is not None and vb not in (None, 0.0):
                rel = abs(va - vb) / max(abs(vb), 1e-9)
                row[label] = {"first": round(va, 6), "rerun": round(vb, 6),
                              "relative_diff": round(rel, 6),
                              "flagged": rel > 0.5}
        comparisons.append(row)
    flagged = [c for c in comparisons if isinstance(c, dict) and any(
        isinstance(v, dict) and v.get("flagged")
        for v in c.values() if isinstance(v, dict))]
    return {"status": "compared", "comparisons": comparisons,
            "gross_divergences": len(flagged)}
