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
import subprocess
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
            trace = load_json(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"corrupt raw trace {f.name}: {e}") from e
        if not isinstance(trace, dict):
            raise ValueError(f"raw trace {f.name} must be an object")
        traces.append(trace)
    return traces


def raw_trace_digest(raw_dir: str | Path) -> dict[str, Any]:
    """Recompute the content digest for every raw trace on disk.

    The digest is over stable relative paths, byte lengths, raw bytes, and
    parsed canonical JSON hashes. A producer manifest is never accepted as a
    substitute for this evidence digest.
    """
    root = Path(raw_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"raw traces dir not found: {root}")
    members: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid raw trace {path}") from exc
        canonical = canonical_json(parsed).encode("utf-8")
        members.append({
            "path": path.relative_to(root).as_posix(),
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "canonical_sha256": hashlib.sha256(canonical).hexdigest(),
        })
    payload = {
        "algorithm": "sha256(path,size,bytes,canonical-json)",
        "members": members,
    }
    return {
        "algorithm": payload["algorithm"],
        "member_count": len(members),
        "members": members,
        "sha256": sha256_text(canonical_json(payload)),
    }


def derive_hard_counters(traces: list[dict[str, Any]]) -> dict[str, int]:
    """Derive all hard counters from trace fields, rejecting malformed data."""
    counters = {key: 0 for key in HARD_COUNTERS}
    for trace in traces:
        if not isinstance(trace, dict):
            raise ValueError("raw trace must be an object")
        for key in HARD_COUNTERS:
            value = trace.get(key)
            if value is None:
                # missing_timestamp is derived from authoritative timestamps;
                # every other hard counter is an explicit trace field.
                if key == "missing_timestamp":
                    value = int(trace.get("t_deny_monotonic_ns") is None)
                else:
                    raise ValueError(
                        f"trace {trace.get('trial_id')}: missing hard counter {key}")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"trace {trace.get('trial_id')}: invalid {key}={value!r}")
            counters[key] += value
    return counters


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value.lower())


def _valid_git_oid(value: Any) -> bool:
    return isinstance(value, str) and len(value) in {40, 64} and all(
        c in "0123456789abcdef" for c in value.lower())


def _git_blob_sha(git_commit: str, relative_path: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", f"{git_commit}:{relative_path}"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=10,
        )
        value = proc.stdout.strip()
        return value if proc.returncode == 0 and value else "MISSING"
    except Exception:
        return "MISSING"


def _git_tree_sha(git_commit: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", f"{git_commit}^{{tree}}"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=10,
        )
        value = proc.stdout.strip()
        return value if proc.returncode == 0 and value else "MISSING"
    except Exception:
        return "MISSING"


def _validate_process_evidence(manifest: dict[str, Any]) -> list[str]:
    """Return process-provenance failures for one manifest."""
    failures: list[str] = []
    evidence = manifest.get("process_evidence")
    if not isinstance(evidence, dict):
        return ["missing process_evidence"]
    for key in ("pid", "parent_pid"):
        value = evidence.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            failures.append(f"invalid process evidence {key}")
    argv = evidence.get("argv")
    if not isinstance(argv, list) or not argv or not all(
            isinstance(item, str) and item for item in argv):
        failures.append("missing/invalid process argv")
    for key in ("cwd", "output_dir", "executable", "python_version",
                "python_implementation", "git_commit", "started_at_utc"):
        if not isinstance(evidence.get(key), str) or not evidence[key]:
            failures.append(f"missing process evidence {key}")
    invocation_digest = evidence.get("invocation_digest")
    if not _valid_digest(invocation_digest):
        failures.append("missing/invalid invocation_digest")
    else:
        body = {k: v for k, v in evidence.items() if k != "invocation_digest"}
        if sha256_text(canonical_json(body)) != invocation_digest:
            failures.append("invocation_digest mismatch")
    descriptor = evidence.get("launch_descriptor")
    if (not isinstance(descriptor, dict) or descriptor.get("argv") != argv or
            descriptor.get("cwd") != evidence.get("cwd") or
            descriptor.get("executable") != evidence.get("executable") or
            descriptor.get("output_dir") != evidence.get("output_dir")):
        failures.append("missing/invalid launch_descriptor")
    return failures


def verify_hash_binding(trace: dict[str, Any]) -> bool:
    """Verify raw_trace_sha256 matches the trace content."""
    if not isinstance(trace, dict):
        return False
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
        self.run_summaries: dict[str, dict[str, Any]] = {}
        self.raw_archive_bindings: dict[str, dict[str, Any]] = {}

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
    if not isinstance(manifest, dict):
        result.fail("manifest must be an object")
        result.finalize()
        return result

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

    # A run is bound to the exact committed source blobs used to execute it.
    git_commit = manifest.get("git_commit")
    if not isinstance(git_commit, str) or not git_commit:
        result.fail("missing git_commit binding")
    else:
        declared_tree = manifest.get("git_tree_sha256")
        actual_tree = _git_tree_sha(git_commit)
        if not _valid_git_oid(declared_tree) or declared_tree != actual_tree:
            result.fail("git tree binding mismatch")
        else:
            result.ok("git tree binding verified")
        bindings = manifest.get("source_bindings")
        if not isinstance(bindings, dict) or not bindings:
            result.fail("missing source_bindings")
        else:
            for relative_path, declared_sha in sorted(bindings.items()):
                if not isinstance(relative_path, str) or not _valid_git_oid(declared_sha):
                    result.fail(f"invalid source binding: {relative_path}")
                    continue
                actual_sha = _git_blob_sha(git_commit, relative_path)
                if actual_sha != declared_sha:
                    result.fail(f"source binding mismatch: {relative_path}")
            if not result.failures or not any(
                    "source binding mismatch" in failure for failure in result.failures):
                result.ok(f"verified {len(bindings)} committed source bindings")

    process_failures = _validate_process_evidence(manifest)
    for failure in process_failures:
        result.fail(failure)
    if not process_failures:
        result.ok("process/launch provenance verified")

    # --- Check dirty flag ---
    if manifest.get("dirty", True) is not False:
        result.fail(f"dirty working tree: {manifest.get('dirty')}")
    else:
        result.ok("dirty=false in manifest")

    # --- Check executor identity ---
    exec_id = manifest.get("executor_id", "")
    if not isinstance(exec_id, str) or not exec_id or not exec_id.startswith("executor-"):
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
        if not isinstance(scenario, str):
            result.fail(f"trace {t.get('trial_id')}: scenario must be a string")
            scenario = ""
        if "PROBE-" in scenario:
            probe_traces.append(t)
            continue
        if scenario.startswith("fault-"):
            fault_traces.append(t)
            continue
        mandatory_traces.append(t)

    result.ok(f"loaded {len(all_traces)} raw traces "
              f"({len(mandatory_traces)} mandatory, {len(fault_traces)} fault, {len(probe_traces)} probe)")

    declared_count = manifest.get("raw_trace_count")
    if declared_count != len(all_traces):
        result.fail(f"raw trace count mismatch: manifest={declared_count} disk={len(all_traces)}")
    try:
        binding = raw_trace_digest(raw_dir)
    except (FileNotFoundError, ValueError) as exc:
        result.fail(f"cannot compute raw trace digest: {exc}")
        binding = None
    declared_binding = manifest.get("raw_trace_binding")
    if binding is not None:
        if not isinstance(declared_binding, dict) or declared_binding.get("sha256") != binding["sha256"]:
            result.fail("raw trace content digest mismatch")
        elif declared_binding.get("member_count") != binding["member_count"]:
            result.fail("raw trace member count binding mismatch")
        else:
            result.ok("raw trace content digest verified")

    # Trial identifiers are part of the immutable archive namespace.
    trial_ids = [t.get("trial_id") for t in all_traces]
    if any(not isinstance(tid, str) or not tid for tid in trial_ids):
        result.fail("raw trace has missing trial_id")
    if len(set(trial_ids)) != len(trial_ids):
        result.fail("duplicate trial_id in raw traces")

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
    try:
        recomputed = derive_hard_counters(mandatory_traces + fault_traces)
    except ValueError as exc:
        result.fail(str(exc))
        recomputed = {k: 0 for k in HARD_COUNTERS}

    # Verify counters match manifest
    manifest_counters = manifest.get("hard_counters", {})
    if not isinstance(manifest_counters, dict):
        result.fail("manifest hard_counters must be an object")
        manifest_counters = {}
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

    # --- Check mandatory trial count (360 matrix + 24 fault trials) ---
    # Fault injections are mandatory safety evidence too.  The matrix itself
    # remains 360 cells, but the authoritative mandatory population is
    # 360 matrix observations + 24 fault observations = 384.
    mandatory_count = len(mandatory_traces) + len(fault_traces)
    if mandatory_count != 384:
        result.fail(f"mandatory trial count: {mandatory_count} != 384")
    else:
        result.ok(f"mandatory trials = {mandatory_count} (360 matrix + 24 faults)")

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
        if not isinstance(manifest_stats, dict):
            result.fail("manifest latency_ms must be an object")
            manifest_stats = {}
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
    result.raw_archive_bindings = {
        "path": str(Path(raw_dir).resolve()),
        "sha256": binding["sha256"] if binding is not None else "",
        "member_count": binding["member_count"] if binding is not None else 0,
    }
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
    result.run_summaries["a"] = {
        "verdict": eval_a.verdict,
        "failures": eval_a.failures,
        "warnings": eval_a.warnings,
        "hard_counters": eval_a.counters,
    }
    result.raw_archive_bindings["a"] = eval_a.raw_archive_bindings
    if eval_a.verdict != "PASS":
        result.fail(f"main run (A) verdict: {eval_a.verdict}")
        result.failures.extend([f"A: {f}" for f in eval_a.failures])
    else:
        result.ok("main run (A) PASS")

    if manifest_b is not None and raw_dir_b is not None:
        # Evaluate B
        eval_b = evaluate_run(manifest_b, raw_dir_b)
        result.run_summaries["b"] = {
            "verdict": eval_b.verdict,
            "failures": eval_b.failures,
            "warnings": eval_b.warnings,
            "hard_counters": eval_b.counters,
        }
        result.raw_archive_bindings["b"] = eval_b.raw_archive_bindings
        if eval_b.verdict != "PASS":
            result.fail(f"rerun (B) verdict: {eval_b.verdict}")
            result.failures.extend([f"B: {f}" for f in eval_b.failures])
        else:
            result.ok("rerun (B) PASS")

        # Check executor identity and process independence. Distinct random
        # strings alone are not provenance: both manifests must carry valid,
        # independently observed process evidence.
        exec_a = manifest_a.get("executor_id", "")
        exec_b = manifest_b.get("executor_id", "")
        if exec_a and exec_b and exec_a != exec_b:
            result.ok(f"executor IDs differ: A={exec_a}, B={exec_b}")
        else:
            result.fail("executor IDs must differ between main and rerun")

        proc_a = manifest_a.get("process_evidence", {})
        proc_b = manifest_b.get("process_evidence", {})
        if (isinstance(proc_a, dict) and isinstance(proc_b, dict) and
                proc_a.get("pid") != proc_b.get("pid")):
            result.ok(f"process IDs differ: A={proc_a.get('pid')}, B={proc_b.get('pid')}")
        else:
            result.fail("process evidence must identify different PIDs")
        if (isinstance(proc_a, dict) and isinstance(proc_b, dict) and
                proc_a.get("invocation_digest") != proc_b.get("invocation_digest")):
            result.ok("invocation digests differ between A and B")
        else:
            result.fail("invocation digests must differ between A and B")

        # Check output root independence
        raw_a = manifest_a.get("raw_trace_dir", "")
        raw_b = manifest_b.get("raw_trace_dir", "")
        if raw_a and raw_b and raw_a != raw_b:
            result.ok(f"output roots differ: A={raw_a}, B={raw_b}")
        else:
            result.fail("output roots must differ between main and rerun")

        commit_a = manifest_a.get("git_commit")
        commit_b = manifest_b.get("git_commit")
        if commit_a and commit_a == commit_b:
            result.ok(f"git commits match: {commit_a}")
        else:
            result.fail("main and rerun must use the same git commit")
        tree_a = manifest_a.get("git_tree_sha256")
        tree_b = manifest_b.get("git_tree_sha256")
        if tree_a and tree_a == tree_b:
            result.ok("git tree bindings match")
        else:
            result.fail("main and rerun must use the same git tree")
        sources_a = manifest_a.get("source_bindings")
        sources_b = manifest_b.get("source_bindings")
        if isinstance(sources_a, dict) and sources_a == sources_b:
            result.ok("source blob bindings match")
        else:
            result.fail("main and rerun source blob bindings differ or are missing")

        # Compare hard counters and evidence population. The raw digests may
        # differ because each process has fresh UUID/timestamps, but both must
        # independently cover the same contract population.
        max_a = eval_a.counters
        max_b = eval_b.counters
        if max_a == max_b:
            result.ok("hard counters match between A and B")
        else:
            result.fail(f"hard counters mismatch: A={max_a}, B={max_b}")
        if (eval_a.raw_archive_bindings.get("member_count") ==
                eval_b.raw_archive_bindings.get("member_count") == 402):
            result.ok("raw trace populations match: 402 members each")
        else:
            result.fail("raw trace populations must contain 402 members each")

        # Compare verdicts
        if eval_a.verdict == eval_b.verdict:
            result.ok(f"verdicts match: {eval_a.verdict}")
        else:
            result.fail(f"verdict mismatch: A={eval_a.verdict}, B={eval_b.verdict}")
    else:
        result.fail("rerun (B) manifest and raw directory are required")

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
        "raw_archive_a": result.raw_archive_bindings.get("a", {}),
        "raw_archive_b": result.raw_archive_bindings.get("b", {}),
        "run_a": result.run_summaries.get("a", {}),
        "run_b": result.run_summaries.get("b", {}),
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    out_path = Path(args.output)
    out_path.write_bytes(
        (json.dumps(output, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )

    # Persist the comparison as a separate, hash-addressable input consumed by
    # make_bundle. It is derived from this invocation, never copied from an
    # earlier summary.
    if args.manifest_b and args.raw_dir_b:
        comparison_output = {
            "schema": "agentos.s1-008.comparison/v1",
            "verdict": result.verdict,
            "failures": result.failures,
            "warnings": result.warnings,
            "run_a_verdict": result.run_summaries.get("a", {}).get("verdict"),
            "run_b_verdict": result.run_summaries.get("b", {}).get("verdict"),
            "run_a_label": manifest.get("run_label", "run-a"),
            "run_b_label": load_json(args.manifest_b).get("run_label", "run-b"),
            "comparison": {
                "executor_ids_differ": manifest.get("executor_id") != load_json(args.manifest_b).get("executor_id"),
                "output_roots_differ": manifest.get("raw_trace_dir") != load_json(args.manifest_b).get("raw_trace_dir"),
                "process_ids_differ": manifest.get("process_evidence", {}).get("pid") != load_json(args.manifest_b).get("process_evidence", {}).get("pid"),
                "hard_counters_match": result.counters == result.run_summaries.get("b", {}).get("hard_counters"),
                "verdicts_match": result.run_summaries.get("a", {}).get("verdict") == result.run_summaries.get("b", {}).get("verdict"),
            },
            "raw_archive_a": result.raw_archive_bindings.get("a", {}),
            "raw_archive_b": result.raw_archive_bindings.get("b", {}),
            "hard_counters": result.counters,
        }
        (out_path.parent / "comparison.json").write_bytes(
            (json.dumps(comparison_output, indent=2, sort_keys=True) + "\n")
            .encode("utf-8")
        )

    print(json.dumps(output, indent=2, sort_keys=True))
    if result.verdict in {"FAIL", "BLOCKED"}:
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
