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
import re
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
    kinds = {r.get("kind") for r in records if isinstance(r, dict)}
    if kinds == {"proportion"}:
        successes = sum(int(r.get("successes") or 0) for r in records
                        if isinstance(r, dict))
        count = sum(int(r.get("count") or 0) for r in records
                    if isinstance(r, dict))
        if count > 0:
            from .stats import wilson_interval
            lo, hi = wilson_interval(successes, count)
            out.update({"successes": successes, "count": count,
                        "value": successes / count,
                        "ci95_low": lo, "ci95_high": hi,
                        "ci_method": "wilson_score_pooled_level0.95"})
    return out


def _phase_matches(name: str, qualifier: str | None) -> bool:
    if not qualifier:
        return True
    q = qualifier.strip()
    if q.startswith("phase_"):
        return name == q[len("phase_"):]
    ln, lq = name.lower(), q.lower()
    return name == q or lq == ln or lq in ln or ln in lq


def _make_resolver(observed_by_scenario: dict):
    """Scope/metric resolver shared by SLO evaluation and the
    contract-driven rerun comparison matrix."""
    INJECTED_SCENARIOS = {
        "queue_backpressure", "provider_full_outage", "provider_degraded",
        "sqlite_lock_contention", "disk_slow_saturation", "network_faults"}

    def _resolve_scenarios(scope: str) -> list[str]:
        # comma clauses ("revocation_under_load, all trials") are qualifiers;
        # the scenario selection lives before the first comma
        text = (scope or "").split(",")[0].strip()
        if text.lower().startswith("all"):
            return [k for k in observed_by_scenario
                    if k not in INJECTED_SCENARIOS]
        chosen: list[str] = []
        for part in text.split("|"):
            base = part.split("@")[0].strip()
            if not base:
                continue
            if base.endswith("*"):
                prefix = base[:-1]
                chosen += [k for k in observed_by_scenario
                           if k.startswith(prefix)]
            elif base in observed_by_scenario:
                chosen.append(base)
        seen: set[str] = set()
        return [k for k in chosen if not (k in seen or seen.add(k))]

    def find_metric(sli_path: str, scope: str):
        scenario_keys = _resolve_scenarios(scope)
        root = sli_path
        stat_hint = None
        if "." in sli_path:
            head, tail = sli_path.rsplit(".", 1)
            if tail in ("p50", "p95", "p99", "max", "mean", "median", "value"):
                root, stat_hint = head, tail
        nodes = []
        for key in scenario_keys:
            metrics = observed_by_scenario.get(key, {}).get("metrics", {})
            node = metrics.get(root)
            if isinstance(node, list):
                nodes.extend(n for n in node if isinstance(n, dict))
            elif isinstance(node, dict):
                nodes.append(node)
            else:
                qualifier = None
                if "@" in scope:
                    qualifier = scope.split("@", 1)[1]
                phases = metrics.get("phases")
                if isinstance(phases, list):
                    named = {}
                    for i, p in enumerate(phases):
                        if not isinstance(p, dict):
                            continue
                        key = next(iter(p), f"phase_{i}")
                        named[key if len(p) == 1 else f"phase_{i}"] = p
                    phases = named
                if isinstance(phases, dict):
                    # phase buckets map phase-name -> {metric_root: record};
                    # a scope qualifier selects named phases ONLY - silently
                    # aggregating across phases can hide SLO violations
                    for phase_name, phase in phases.items():
                        if not isinstance(phase, dict):
                            continue
                        if not _phase_matches(phase_name, qualifier):
                            continue
                        candidates = [phase]
                        for sub in phase.values():
                            if isinstance(sub, dict):
                                candidates.append(sub)
                        for cand in candidates:
                            if root in cand:
                                inner = cand[root]
                                if isinstance(inner, list):
                                    nodes.extend(n for n in inner
                                                 if isinstance(n, dict))
                                elif isinstance(inner, dict):
                                    nodes.append(inner)
        if not nodes:
            return None  # no arbitrary cross-scope pickup: absent means NO_DATA
        merged = _reduce_merged(nodes)
        if stat_hint and merged.get(stat_hint) is not None:
            merged["_stat_hint"] = stat_hint
        return merged
    return {"resolve": _resolve_scenarios, "find": find_metric}


def _evaluate_slos(contract: dict, observed_by_scenario: dict) -> tuple[list[dict], list[str], list[str]]:
    """Returns (slo_table, cannot_pass_reasons, hard_failures)."""
    table: list[dict] = []
    cannot_pass: list[str] = []
    failures: list[str] = []
    find_metric = _make_resolver(observed_by_scenario)["find"]

    def threshold_parts(threshold: str):
        match = re.search(r"(<=|>=)\s*([0-9]+(?:\.[0-9]+)?)", threshold)
        if not match:
            return None, None
        return match.group(1), float(match.group(2))

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
        verdict_text = str(slo.get("statistic_for_verdict", "")).lower()
        if "max" in verdict_text:
            statistic = "max"
        elif metric.get("_stat_hint"):
            statistic = metric["_stat_hint"]
        else:
            statistic = ("value" if slo["sli"].endswith("fraction")
                         or slo["sli"].endswith("seconds") else "p95")
        if metric.get(statistic) is None:
            for fallback in ("value", "median", "p50", "max"):
                if metric.get(fallback) is not None:
                    statistic = fallback
                    break
        value = metric.get(statistic)
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
        if verdict == "FAIL":
            # an OBSERVED threshold violation can never be argued down to a
            # limit: it is a hard failure under the frozen contract
            failures.append(
                f"slo-threshold-violation:{slo['sli']}@{scope}:"
                f"{value}!{op}{bound}")
        elif verdict in ("CI_CROSSES_THRESHOLD", "UNKNOWN"):
            cannot_pass.append(f"{slo['sli']}@{scope}:{verdict}")
        entry.update({"observed": value,
                      "ci": [metric.get("ci95_low"), metric.get("ci95_high")],
                      "statistic": statistic, "verdict": verdict})
        table.append(entry)
    return table, cannot_pass, failures


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

    main_known_commit: str | None = None  # resolved after loading seeds
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
            required_ratios = {
                k: v for k, v in (mapping.items() if isinstance(mapping, dict)
                                  else [])
                if "_ratio" in k and isinstance(v, (int, float))}
            server_class = mapping.get("server_class_storage") if isinstance(
                mapping, dict) else None
            ratios_ok = bool(required_ratios) and all(
                v >= 1.0 for v in required_ratios.values()) and (
                server_class is not False)
            production_like_flags.append(ratios_ok)
            if not ratios_ok:
                limits.append(
                    f"production-like-profile-not-proven:{run_id}:"
                    f"{json.dumps(required_ratios, sort_keys=True)}")
            if manifest.get("runner_version") != RUNNER_VERSION:
                failures.append(f"incompatible-runner-version:{run_id}")
        else:
            production_like_flags.append(False)
            limits.append(f"production-like-profile-absent:{run_id}")
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

    # resolve the series commit from the FIRST run's first stamped seed,
    # then hold every seed of every run to that same frozen commit
    main_known_commit = None
    first_run_seeds = next(iter(runs.values()), {})
    for seeds in first_run_seeds.values():
        for payload in seeds.values():
            sha = payload.get("commit_sha")
            if sha:
                main_known_commit = str(sha)
                break
        if main_known_commit:
            break

    # every seed must carry the SAME frozen code commit as its run manifest
    for run_id, scenario_map in runs.items():
        manifest_path = work_root / run_id / "environment-manifest.json"
        manifest_commit = None
        if manifest_path.exists():
            try:
                raw = json.loads(manifest_path.read_text(
                    encoding="utf-8")).get("git_commit_sha")
                if isinstance(raw, dict):
                    raw = raw.get("value")
                manifest_commit = str(raw) if raw and raw != "unavailable" \
                    else None
            except (OSError, ValueError):
                manifest_commit = None
        seen_commits: set[str] = set()
        for scenario_id, seeds in scenario_map.items():
            for seed, payload in seeds.items():
                sha = payload.get("commit_sha")
                if not sha:
                    failures.append(
                        f"commit-sha-unrecorded:{run_id}:{scenario_id}:{seed}")
                else:
                    seen_commits.add(str(sha))
        for foreign in sorted(seen_commits - {main_known_commit}):
            failures.append(
                f"commit-sha-mismatch:{run_id}:{foreign}")
        if (manifest_commit and seen_commits
                and manifest_commit not in seen_commits):
            failures.append(
                f"commit-sha-mismatch-vs-manifest:{run_id}:{manifest_commit}")

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
        limits.append(
            "production-like-proof-missing-or-insufficient:verdict-capped-at-PWL")

    # --- aggregate observed metrics per run ---------------------------------
    observed_by_scenario: dict[str, dict] = {}
    revocation_total_trials = 0
    revocation_max_ms = 0.0
    revocation_violations = 0
    invariant_totals: dict[str, int] = {}
    scale_gaps: list[str] = []

    # observed metrics for SLO evaluation come from the FIRST (main) run;
    # the rerun is checked separately for consistency below.
    main_run = run_ids[0] if run_ids else ""
    for scenario_id, seeds in runs.get(main_run, {}).items():
        merged_metrics: dict = {}
        for seed, payload in sorted(seeds.items()):
            for key, value in payload.get("result", {}).get(
                    "metrics", {}).items():
                merged_metrics.setdefault(key, []).append(value)
        observed_by_scenario[scenario_id] = {"metrics": merged_metrics}

    mandatory_invariants = [i["id"] for i in contract.get("invariants", [])]

    def _check_seed_invariants(run_id: str, scenario_id: str, seed: int,
                               payload: dict) -> None:
        """Every contract-mandatory counter must be present, numeric,
        non-negative and exactly zero — in EVERY run, not just the first."""
        inv = payload.get("result", {}).get("invariants") or {}
        for key in mandatory_invariants:
            value = inv.get(key)
            label = f"{run_id}:{scenario_id}:{seed}:{key}"
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                failures.append(f"invariant-missing-or-negative:{label}={value!r}")
                invariant_totals[label] = -1
            elif value < 0:
                failures.append(f"invariant-missing-or-negative:{label}={value}")
                invariant_totals[label] = int(value)
            elif value > 0:
                failures.append(
                    f"invariant-violation:{label}={int(value)}")
                invariant_totals[label] = int(value)
            else:
                invariant_totals.setdefault(label, 0)

    for run_id in run_ids:
        for scenario_id, seeds in runs.get(run_id, {}).items():
            for seed, payload in sorted(seeds.items()):
                result = payload.get("result", {})
                if scenario_id != "revocation_under_load":
                    _check_seed_invariants(run_id, scenario_id, seed, payload)
                    if result.get("completed_at_required_scale") is False:
                        scale_gaps.append(
                            f"{run_id}:{scenario_id}:below-required-scale")
                    profile = result.get("db_profile") or {}
                    if profile and not profile.get("reached_target", True):
                        scale_gaps.append(
                            f"{run_id}:{scenario_id}:db-growth-below-target")
                    if result.get("metrics", {}).get("_power_insufficient"):
                        limits.append(
                            f"insufficient-statistical-power:{run_id}:{scenario_id}:{seed}")
                else:
                    _check_seed_invariants(run_id, scenario_id, seed, payload)
                    m = result.get("metrics", {})
                    revocation_total_trials += int(m.get("trials_total", 0))
                    lat = m.get("revocation_enforcement_latency_ms", {})
                    revocation_max_ms = max(revocation_max_ms,
                                            float(lat.get("max") or 0.0))
                    revocation_violations += int(
                        m.get("allow_after_commit_violations", 0))
                    if not m.get("gate_all_trials_le_5000ms", False):
                        failures.append(
                            f"revocation-gate-not-passed:{run_id}:{seed}")
                    for check in m.get("resurrection_checks", []):
                        if not check.get("still_denies_after_restart"):
                            failures.append(
                                f"capability-resurrection-after-restart:{run_id}:{seed}")
    per_run_trials: dict[str, int] = {}
    for run_id, scenario_map in runs.items():
        total = 0
        for seed, payload in scenario_map.get("revocation_under_load",
                                              {}).items():
            total += int(payload.get("result", {}).get("metrics", {}).get(
                "trials_total", 0))
        per_run_trials[run_id] = total
        if total < MIN_REVOCATION_TRIALS:
            failures.append(
                f"revocation-trials-below-minimum:{run_id}:"
                f"{total}<{MIN_REVOCATION_TRIALS}")

    from .harness import _SECRET_MARKERS
    for run_id in run_ids:
        run_dir = work_root / run_id
        for artifact in run_dir.rglob("*"):
            if not artifact.is_file():
                continue
            if artifact.suffix.lower() in (".db", ".wal", ".shm"):
                continue
            try:
                text = artifact.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            low = text.lower()
            hits = [m for m in _SECRET_MARKERS if m.lower() in low]
            if hits:
                failures.append(
                    f"secrets-in-artifacts:{run_id}:{artifact.name}:{hits[0]}")

    if revocation_total_trials < MIN_REVOCATION_TRIALS:
        limits.append(
            f"revocation-trials-below-minimum-total:{revocation_total_trials}")
    if revocation_max_ms > REVOCATION_LIMIT_MS:
        failures.append(
            f"revocation-latency-over-limit:{revocation_max_ms}ms>{REVOCATION_LIMIT_MS}ms")
    if revocation_violations > 0:
        failures.append(f"post-revoke-forbidden-side-effects:{revocation_violations}")
    for gap in scale_gaps:
        limits.append(gap)

    slo_table, cannot_pass, slo_failures = _evaluate_slos(
        contract, observed_by_scenario)
    failures.extend(slo_failures)
    if any(row["requires_owner_confirmation"] for row in slo_table):
        limits.append("owner-confirmation-pending:thresholds-marked-in-contract")

    def _eval_for_bucket(sli, scope, bucket):
        return _make_resolver(bucket)["find"](sli, scope)

    rerun_summary = _compare_runs(runs, contract, _eval_for_bucket)
    for missing in rerun_summary.get("missing_comparable", []):
        limits.append(f"rerun-missing-comparable:{missing}")
    for comp in rerun_summary.get("comparisons", []):
        if not isinstance(comp, dict):
            continue
        for label, cell in comp.items():
            if isinstance(cell, dict) and cell.get("flagged"):
                limits.append(
                    f"rerun-divergence-unexplained:{comp.get('scenario')}:"
                    f"{label}:rel={cell.get('relative_diff')}")

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


def _seed_metric(payload: dict, path: tuple[str, ...]) -> float | None:
    node = payload.get("result", {}).get("metrics", {})
    for part in path:
        if isinstance(node, dict):
            node = node.get(part)
        else:
            break
    if isinstance(node, bool):
        return None
    if isinstance(node, (int, float)):
        return float(node)
    if isinstance(node, dict):
        for key in (path[-1], "value"):
            value = node.get(key) if isinstance(node, dict) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return None


def _p95_of_seed_metrics(payloads: list[dict], metric_path: tuple[str, ...]) -> float | None:
    values = [v for v in (_seed_metric(p, metric_path) for p in payloads)
              if v is not None]
    return statistics.median(values) if values else None


def _compare_runs(runs: dict[str, dict[str, dict[int, dict]]],
                  contract: dict | None = None,
                  evaluate=None) -> dict:
    run_ids = list(runs.keys())
    if len(run_ids) < 2:
        return {"status": "rerun-missing"}
    first, second = run_ids[0], run_ids[1]
    comparisons = []
    if contract and evaluate is not None:
        missing_comparable = []
        for slo in contract.get("slos", []):
            sli, scope = slo["sli"], slo.get("scope", "")
            values = []
            for rid in (first, second):
                observed: dict = {}
                for scenario_id, seeds in runs.get(rid, {}).items():
                    merged = {}
                    for seed, payload in sorted(seeds.items()):
                        for key, value in payload.get("result", {}).get(
                                "metrics", {}).items():
                            merged.setdefault(key, []).append(value)
                    observed[scenario_id] = {"metrics": merged}
                metric = evaluate(sli, scope, observed)
                if metric:
                    verdict_text = str(
                        slo.get("statistic_for_verdict", "")).lower()
                    if "max" in verdict_text:
                        stat = "max"
                    elif metric.get("_stat_hint"):
                        stat = metric["_stat_hint"]
                    elif metric.get("value") is not None:
                        stat = "value"
                    else:
                        stat = "p95"
                    if metric.get(stat) is None:
                        for fallback in ("value", "median", "p50", "max"):
                            if metric.get(fallback) is not None:
                                stat = fallback
                                break
                    values.append((rid, metric.get(stat)))
            if any(v is None for _, v in values) or len(values) < 2:
                missing_comparable.append(f"{sli}@{scope}")
                comparisons.append({"sli": sli, "scope": scope,
                                    "status": "missing-comparable"})
                continue
            va, vb = values[0][1], values[1][1]
            rc = (contract or {}).get("rerun_consistency", {})
            proportion_sli = sli.startswith(("availability_fraction",
                                             "error_rate_fraction"))
            if proportion_sli:
                diff = abs(va - vb)
                tol = rc.get("proportion_absolute_tolerance", 0.01)
                comparisons.append({"sli": sli, "scope": scope,
                                    "first": round(va, 6),
                                    "rerun": round(vb, 6),
                                    "absolute_diff": round(diff, 6),
                                    "tolerance": tol,
                                    "flagged": diff > tol})
            else:
                rel = abs(va - vb) / max(abs(vb), 1e-9)
                tol = (rc.get("latency_relative_tolerance", 0.35)
                       if "latency" in sli or "_ms" in sli
                       else rc.get("default_relative_tolerance", 0.35))
                comparisons.append({"sli": sli, "scope": scope,
                                    "first": round(va, 6),
                                    "rerun": round(vb, 6),
                                    "relative_diff": round(rel, 6),
                                    "tolerance": tol,
                                    "flagged": rel > tol})
        return {"status": "compared", "basis": "contract-slo-matrix",
                "comparisons": comparisons,
                "missing_comparable": missing_comparable,
                "gross_divergences": sum(
                    1 for c in comparisons if c.get("flagged"))}
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
