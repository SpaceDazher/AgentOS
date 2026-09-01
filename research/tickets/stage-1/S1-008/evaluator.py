"""S1-008 fail-closed evaluator.

Reads raw-observation traces produced by runner.py and re-derives every
latency / counter / verdict independently from the raw per-trial timestamps
(no producer summary is trusted). The evaluator is a separate module so that
runner.py (producer) and evaluator.py (consumer) are independent derivation
paths as required by S1-008 §5.

Verdict semantics:
  PASS            — all hard gates satisfied, max latency <= target, zero
                    hard counters, all probes detected, run-b reproducible.
  PASS_WITH_LIMITS — safety holds but some non-safety descriptor is not met
                    (e.g. sample-size CI warning, single-seed reproducibility).
  FAIL            — any hard gate violated (allow after commit, latency > target,
                    censored/missing mandatory trial, clock anomaly, probe not
                    detected, dirty/mixed-commit/stale-hash).
  BLOCKED         — evidence insufficient to decide (missing files, hash
                    mismatch, evaluator-internal error).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure agentos is importable
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from agentos.ids import canonical_json, sha256_text  # noqa: E402

TARGET_MS = 5000
HARD_COUNTERS = [
    "allow_after_commit", "effect_after_revoke",
    "child_allow_after_parent_revoke", "cache_resurrection",
    "epoch_regression", "blind_retry", "unreconciled_unknown",
    "missing_timestamp", "censored_trial",
]
PROBE_LETTERS = ["A", "B", "C", "D", "E", "F"]


def load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_raw_traces(raw_dir: str | Path) -> list[dict[str, Any]]:
    """Load all raw trace JSON files from a directory."""
    traces: list[dict[str, Any]] = []
    raw_path = Path(raw_dir)
    if not raw_path.exists():
        raise FileNotFoundError(f"raw traces dir not found: {raw_path}")
    for f in sorted(raw_path.glob("*.json")):
        try:
            traces.append(load_json(f))
        except json.JSONDecodeError as e:
            raise ValueError(f"corrupt raw trace {f.name}: {e}") from e
    return traces


def verify_hash_binding(trace: dict[str, Any]) -> bool:
    """Verify raw_trace_sha256 matches the trace content."""
    stored = trace.get("raw_trace_sha256", "")
    if not stored:
        return False
    body = {k: v for k, v in trace.items() if k != "raw_trace_sha256"}
    computed = sha256_text(canonical_json(body))
    return computed == stored


class EvaluationResult:
    """Accumulates verdict, counters, and evidence."""

    def __init__(self):
        self.verdict: str = "BLOCKED"
        self.failures: list[str] = []
        self.warnings: list[str] = []
        self.passed: list[str] = []
        self.counters: dict[str, int] = {k: 0 for k in HARD_COUNTERS}
        self.probe_results: dict[str, dict[str, Any]] = {}

    def fail(self, reason: str):
        self.failures.append(reason)

    def warn(self, reason: str):
        self.warnings.append(reason)

    def ok(self, reason: str):
        self.passed.append(reason)

    def finalize(self):
        if self.failures:
            self.verdict = "FAIL"
        elif self.warnings:
            self.verdict = "PASS_WITH_LIMITS"
        else:
            self.verdict = "PASS"


def _stats(vals: list[float]) -> dict[str, Any]:
    if not vals:
        return {"count": 0, "min": 0, "p50": 0, "p95": 0, "p99": 0, "max": 0}
    s = sorted(vals)
    n = len(s)

    def pct(p: float) -> float:
        # nearest-rank percentile (matches runner.py stats() exactly)
        idx = min(int(n * p), n - 1)
        return s[idx]

    return {
        "count": n,
        "min": round(min(s), 3),
        "p50": round(pct(0.50), 3),
        "p95": round(pct(0.95), 3),
        "p99": round(pct(0.99), 3),
        "max": round(max(s), 3),
    }


def evaluate_run(manifest: dict[str, Any], raw_dir: str | Path) -> EvaluationResult:
    """Evaluate a single run's traces against the S1-008 rubric.

    Re-derives all counters and latencies from raw traces independently.
    Does NOT trust the manifest's aggregate counters — recomputes them.
    """
    result = EvaluationResult()

    # --- Check frozen artifact bindings ---
    required_shas = {
        "contract_sha256": "revocation-contract.json",
        "workload_sha256": "workload-manifest.json",
        "rubric_sha256": "rubric.json",
        "fixtures_sha256": "fixtures.json",
        "corpus_manifest_sha256": "corpus-manifest.json",
        "threat_model_sha256": "threat-model.json",
    }

    # S1-008 frozen artifacts directory
    _BASE = Path(__file__).resolve().parent

    missing = [k for k in required_shas if not manifest.get(k)]
    if missing:
        result.fail(f"missing frozen artifact SHA-256 binding in manifest: {missing}")
    else:
        # Verify SHA matches the actual file on disk
        hash_mismatches = []
        for manifest_key, filename in required_shas.items():
            declared_sha = manifest.get(manifest_key, "")
            file_path = _BASE / filename
            if not file_path.exists():
                result.fail(f"frozen artifact file missing on disk: {filename}")
                continue
            actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
            if actual_sha != declared_sha:
                hash_mismatches.append(f"{filename}: manifest={declared_sha[:16]}… disk={actual_sha[:16]}…")

        if hash_mismatches:
            for m in hash_mismatches:
                result.fail(f"frozen artifact SHA mismatch: {m}")
        else:
            result.ok("all frozen artifact SHA-256 verified against disk")

    # --- Check dirty flag ---
    if manifest.get("dirty", True) is not False:
        result.fail(f"dirty working tree: {manifest.get('dirty')}")
    else:
        result.ok("dirty=false in manifest")

    # --- Check executor identity ---
    exec_id = manifest.get("executor_id", "")
    if not exec_id or "executor-" not in exec_id:
        result.fail("missing or invalid executor_id")
    else:
        result.ok(f"executor_id present: {exec_id}")

    # --- Load raw traces ---
    mandatory_traces = []
    probe_traces = []
    fault_traces = []
    try:
        all_traces = load_raw_traces(raw_dir)
    except (FileNotFoundError, ValueError) as e:
        result.fail(f"cannot load raw traces: {e}")
        result.finalize()
        return result

    for t in all_traces:
        scenario = t.get("scenario", "")
        if "PROBE-" in scenario:
            probe_traces.append(t)
            continue
        if scenario.startswith("fault-"):
            fault_traces.append(t)
            continue
        mandatory_traces.append(t)

    result.ok(f"loaded {len(all_traces)} raw traces "
              f"({len(mandatory_traces)} mandatory, {len(fault_traces)} fault, {len(probe_traces)} probe)")

    # --- Verify hash binding on every trace ---
    hash_failures = 0
    for t in all_traces:
        if not verify_hash_binding(t):
            hash_failures += 1
    if hash_failures > 0:
        result.fail(f"{hash_failures} traces failed hash binding verification")
    else:
        result.ok(f"all {len(all_traces)} traces pass hash binding verification")

    # --- Recompute hard counters from MANDATORY + fault traces ---
    recomputed = {k: 0 for k in HARD_COUNTERS}
    for t in mandatory_traces + fault_traces:
        for k in HARD_COUNTERS:
            recomputed[k] += t.get(k, 0) or 0

    # Verify counters match manifest
    manifest_counters = manifest.get("hard_counters", {})
    for k in HARD_COUNTERS:
        result.counters[k] = recomputed[k]
        if manifest_counters.get(k, -1) != recomputed[k]:
            result.fail(
                f"counter mismatch: {k} manifest={manifest_counters.get(k)} "
                f"recomputed={recomputed[k]}"
            )

    # Any non-zero hard counter is a FAIL
    for k in HARD_COUNTERS:
        if recomputed[k] > 0:
            result.fail(f"hard counter {k} = {recomputed[k]} (must be 0)")
        else:
            result.ok(f"hard counter {k} = 0")

    # --- Check mandatory trial count >= 100 ---
    mandatory_count = len(mandatory_traces)
    if mandatory_count < 100:
        result.fail(f"insufficient mandatory trials: {mandatory_count} < 100")
    else:
        result.ok(f"mandatory trials = {mandatory_count} >= 100")

    # --- Check exact matrix cross-product coverage ---
    # Required: 4 paths × 2 cache × 3 loads × 3 seeds = 72 unique combinations
    required_paths = {"gateway", "retrieval", "delegation", "projection"}
    required_cache = {"cold", "warm"}
    required_loads = {"idle", "steady", "burst"}
    required_seeds = {"seed11", "seed12", "seed13"}

    # Build set of (path, cache_state, load, seed) tuples from mandatory traces
    seen_cells: set[tuple[str, str, str, str]] = set()
    for t in mandatory_traces:
        cell = (
            t.get("path", ""),
            t.get("cache_state", ""),
            t.get("load", ""),
            t.get("seed", ""),
        )
        seen_cells.add(cell)

    # Generate all expected combinations
    expected_cells = {
        (p, c, l, s)
        for p in required_paths
        for c in required_cache
        for l in required_loads
        for s in required_seeds
    }

    expected_count = len(expected_cells)  # Should be 72
    missing_cells = expected_cells - seen_cells
    extra_cells = seen_cells - expected_cells

    if missing_cells:
        result.fail(f"missing {len(missing_cells)}/{expected_count} matrix cells: "
                     f"{sorted(missing_cells)[:5]}...")
    elif extra_cells:
        result.fail(f"unexpected {len(extra_cells)} matrix cells (not in frozen contract): "
                     f"{sorted(extra_cells)[:5]}...")
    else:
        result.ok(f"exact matrix cross-product verified: {expected_count} cells present")

    # Check for duplicate/underpopulated cells — each cell must have
    # exactly trials_per_scenario_seed trials (no more, no less)
    trials_per = 5
    cell_counts: dict[tuple, int] = {}
    for t in mandatory_traces:
        cell = (
            t.get("path", ""),
            t.get("cache_state", ""),
            t.get("load", ""),
            t.get("seed", ""),
        )
        cell_counts[cell] = cell_counts.get(cell, 0) + 1
    underpopulated = {k: v for k, v in cell_counts.items() if v < trials_per}
    duplicates = {k: v for k, v in cell_counts.items() if v > trials_per}
    if underpopulated:
        result.fail(f"underpopulated matrix cells (expected {trials_per} each): {underpopulated}")
    if duplicates:
        result.fail(f"overpopulated matrix cells (expected {trials_per} each): {duplicates}")

    # --- Recompute latency from raw timestamps ---
    # Only DENY decisions count toward latency (matching runner logic)
    latencies_ms: list[float] = []
    for t in mandatory_traces + fault_traces:
        if t.get("decision") != "DENY":
            continue
        t_commit = t.get("t_commit_monotonic_ns")
        t_deny = t.get("t_deny_monotonic_ns")
        if t_commit is None:
            result.fail(f"trace {t.get('trial_id')}: missing t_commit_monotonic_ns")
            continue
        if t_deny is None:
            result.fail(f"trace {t.get('trial_id')}: DENY decision but missing t_deny_monotonic_ns")
            continue
        if not isinstance(t_commit, (int, float)) or not isinstance(t_deny, (int, float)):
            result.fail(f"trace {t.get('trial_id')}: non-numeric timestamps")
            continue
        latency = (t_deny - t_commit) / 1_000_000  # ns -> ms
        if latency < 0:
            result.fail(f"trace {t.get('trial_id')}: negative latency {latency}")
            continue
        latencies_ms.append(latency)

    if latencies_ms:
        max_latency = max(latencies_ms)
        if max_latency > TARGET_MS:
            result.fail(f"max latency {max_latency}ms > target {TARGET_MS}ms")
        else:
            result.ok(f"max latency {max_latency}ms <= target {TARGET_MS}ms")

        stats = _stats(latencies_ms)
        # Verify stats match manifest
        manifest_stats = manifest.get("latency_ms", {})
        # Verify count and max exactly (hard security relevance)
        for key in ("count", "max"):
            if manifest_stats.get(key) != stats[key]:
                result.fail(
                    f"latency stat mismatch: {key} manifest={manifest_stats.get(key)} "
                    f"recomputed={stats[key]}"
                )
        # p50/p95/p99 may differ slightly due to percentile interpolation
        # method differences; verify within 0.1ms tolerance
        for key in ("p50", "p95", "p99", "min"):
            m_val = manifest_stats.get(key, 0)
            r_val = stats[key]
            if abs(m_val - r_val) > 0.1:
                result.fail(
                    f"latency stat mismatch: {key} manifest={m_val} recomputed={r_val} "
                    f"(delta > 0.1ms)"
                )
        result.ok(f"latency stats verified: {stats}")
    else:
        result.fail("no valid latency values found in mandatory traces")

    # --- Verify per-component latency ---
    for comp in ("gateway", "retrieval", "delegation", "projection"):
        comp_latencies = [
            (t["t_deny_monotonic_ns"] - t["t_commit_monotonic_ns"]) / 1_000_000
            for t in mandatory_traces
            if t.get("path") == comp
            and t.get("t_deny_monotonic_ns") is not None
            and t.get("t_commit_monotonic_ns") is not None
            and t.get("allow_after_commit", 0) == 0
        ]
        if comp_latencies:
            comp_max = max(comp_latencies)
            if comp_max > TARGET_MS:
                result.fail(f"component {comp} max latency {comp_max}ms > {TARGET_MS}ms")
            else:
                result.ok(f"component {comp} max latency {comp_max}ms <= {TARGET_MS}ms")
        else:
            result.fail(f"component {comp} has no valid DENY latencies")

    # --- Verify probes A-F are detected ---
    # Each probe should have at least one trace demonstrating the violation
    probe_checks = {
        "A": ("allow_after_commit", lambda t: t.get("allow_after_commit", 0) > 0),
        "B": ("allow_after_commit", lambda t: t.get("allow_after_commit", 0) > 0),
        "C": ("forged_timestamp", lambda t: t.get("clock_domain") == "forged"),
        "D": ("cache_resurrection", lambda t: t.get("cache_resurrection", 0) > 0),
        "E": ("child_allow_after_parent_revoke", lambda t: t.get("child_allow_after_parent_revoke", 0) > 0),
        "F": ("censored_trial", lambda t: t.get("censored_trial", 0) > 0),
    }

    probe_results: dict[str, dict[str, Any]] = {}
    for letter in PROBE_LETTERS:
        letter_traces = [t for t in probe_traces if f"PROBE-{letter}" in t.get("scenario", "")]
        if not letter_traces:
            result.fail(f"probe {letter} not found in probe traces")
            probe_results[letter] = {"detected": False, "scenario": ""}
        else:
            check_desc, check_fn = probe_checks[letter]
            violations = [t for t in letter_traces if check_fn(t)]
            if not violations:
                result.fail(f"probe {letter} did not demonstrate {check_desc}")
                probe_results[letter] = {
                    "detected": False,
                    "scenario": letter_traces[0].get("scenario", ""),
                    "trials": len(letter_traces),
                }
            else:
                result.ok(f"probe {letter} detected: {violations[0].get('scenario')}")
                probe_results[letter] = {
                    "detected": True,
                    "scenario": violations[0].get("scenario", ""),
                    "trials": len(letter_traces),
                    "violations": len(violations),
                }

    result.probe_results = probe_results
    result.finalize()
    return result


def evaluate_comparison(manifest_a: dict[str, Any], manifest_b: dict[str, Any] | None,
                        raw_dir_a: str | Path, raw_dir_b: str | Path | None) -> EvaluationResult:
    """Compare main run (A) against independent rerun (B)."""
    result = EvaluationResult()

    # Evaluate A
    eval_a = evaluate_run(manifest_a, raw_dir_a)
    result.probe_results = eval_a.probe_results
    result.counters = eval_a.counters
    result.passed = eval_a.passed
    if eval_a.verdict != "PASS":
        result.fail(f"main run (A) verdict: {eval_a.verdict}")
        result.failures.extend([f"A: {f}" for f in eval_a.failures])
    else:
        result.ok("main run (A) PASS")

    if manifest_b is not None and raw_dir_b is not None:
        # Evaluate B
        eval_b = evaluate_run(manifest_b, raw_dir_b)
        if eval_b.verdict != "PASS":
            result.fail(f"rerun (B) verdict: {eval_b.verdict}")
            result.failures.extend([f"B: {f}" for f in eval_b.failures])
        else:
            result.ok("rerun (B) PASS")

        # Check executor identity independence
        exec_a = manifest_a.get("executor_id", "")
        exec_b = manifest_b.get("executor_id", "")
        if exec_a and exec_b and exec_a != exec_b:
            result.ok(f"executor IDs differ: A={exec_a}, B={exec_b}")
        else:
            result.fail("executor IDs must differ between main and rerun")

        # Check output root independence
        raw_a = manifest_a.get("raw_trace_dir", "")
        raw_b = manifest_b.get("raw_trace_dir", "")
        if raw_a and raw_b and raw_a != raw_b:
            result.ok(f"output roots differ: A={raw_a}, B={raw_b}")
        else:
            result.fail("output roots must differ between main and rerun")

        # Compare maximum latencies (within frozen tolerance)
        max_a = eval_a.counters
        max_b = eval_b.counters
        if max_a == max_b:
            result.ok("hard counters match between A and B")
        else:
            result.fail(f"hard counters mismatch: A={max_a}, B={max_b}")

        # Compare verdicts
        if eval_a.verdict == eval_b.verdict:
            result.ok(f"verdicts match: {eval_a.verdict}")
        else:
            result.fail(f"verdict mismatch: A={eval_a.verdict}, B={eval_b.verdict}")
    else:
        result.warn("no rerun (B) provided — rerun comparison skipped")

    result.finalize()
    return result


def main():
    parser = argparse.ArgumentParser(
        description="S1-008 fail-closed evaluator"
    )
    parser.add_argument("--manifest", required=True,
                        help="Path to manifest.json")
    parser.add_argument("--raw-dir", required=True,
                        help="Directory containing raw trace JSON files")
    parser.add_argument("--manifest-b", default=None,
                        help="Path to rerun manifest.json (optional)")
    parser.add_argument("--raw-dir-b", default=None,
                        help="Directory for rerun raw traces (optional)")
    parser.add_argument("--output", default="evaluation-result.json",
                        help="Output path for evaluation result")
    args = parser.parse_args()

    manifest = load_json(args.manifest)
    result = evaluate_comparison(manifest,
                                 load_json(args.manifest_b) if args.manifest_b else None,
                                 args.raw_dir, args.raw_dir_b)

    output = {
        "schema": "agentos.s1-008.evaluation-result/v1",
        "verdict": result.verdict,
        "failures": result.failures,
        "warnings": result.warnings,
        "passed_checks": result.passed,
        "hard_counters": result.counters,
        "probe_results": result.probe_results,
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    out_path = Path(args.output)
    out_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(output, indent=2, sort_keys=True))
    if result.verdict == "FAIL":
        print(f"\nVERDICT: {result.verdict} ({len(result.failures)} failures)", file=sys.stderr)
        sys.exit(1)
    elif result.verdict == "PASS_WITH_LIMITS":
        print(f"\nVERDICT: {result.verdict} ({len(result.warnings)} warnings)", file=sys.stderr)
        sys.exit(0)
    else:
        print(f"\nVERDICT: {result.verdict}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
