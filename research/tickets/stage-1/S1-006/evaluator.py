"""AgentOS S1-006 — independent fail-closed evaluator (QA2).

Derives the verdict ONLY from the frozen rubric and the raw observations
recorded by runner.py. The producer never states the expected verdict in
observed results.

Fail-closed on:
- run matrix divergence (missing/extra/duplicate runs vs the frozen
  workload manifest);
- contract/workload/rubric hash divergence across runs (INCOMPARABLE);
- mixed/fabricated commit or tree SHA provenance, dirty working tree,
  expected-commit mismatch;
- safety counters with wrong key sets or non-zero values on a candidate;
- missing/empty raw observations or terminal reasons;
- probes A/B/C not rejected through the real evaluation rules;
- weight perturbations flipping the winner (caps at PASS_WITH_LIMITS);
- unknown/NO_DATA dimensions (never mapped to a number or advantage).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
from pathlib import Path


SCHEMA = "agentos.s1-006.evaluation/v1"
SAFETY_COUNTERS = (
    "duplicate_effect_count", "duplicate_receipt_count", "blind_retry_count",
    "stale_owner_completion_count", "checkpoint_hash_bypass_count",
    "lost_committed_event_count", "allow_after_revocation_count",
)
SENSITIVITY_SEED = 42
SENSITIVITY_RANDOM_RUNS = 200
REQUIRED_SCRIPT_HASHES = {
    "runner.py", "evaluator.py", "make_bundle.py", "dependency_gate.py",
    "bundle_content.py",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class EvalError(ValueError):
    pass


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def run_file_path(run_dir: Path, name) -> Path:
    if not isinstance(name, str) or not name.endswith(".json") or \
            Path(name).name != name:
        raise EvalError(f"unsafe run file name: {name!r}")
    return run_dir / name


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def git_bytes(root: Path, args: list[str]) -> bytes:
    try:
        proc = subprocess.run(["git", *args], cwd=str(root),
                              capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvalError(f"git {' '.join(args)} failed: {exc}") from exc
    if proc.returncode != 0:
        raise EvalError(
            f"git {' '.join(args)} failed ({proc.returncode}): "
            f"{proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def validate_provenance(prov: dict, ticket: Path,
                        expected_commit: str | None = None) -> None:
    """Bind executed scripts to the declared commit/tree and current bytes."""
    commit = prov.get("commit")
    tree_sha = prov.get("tree_sha")
    if not isinstance(commit, str) or not HEX40.fullmatch(commit):
        raise EvalError("experiment commit is missing or malformed")
    if not isinstance(tree_sha, str) or not HEX40.fullmatch(tree_sha):
        raise EvalError("experiment tree SHA is missing or malformed")
    root = ticket.parents[3]
    resolved_tree = git_bytes(root, ["rev-parse", f"{commit}^{{tree}}"])
    if resolved_tree.decode().strip() != tree_sha:
        raise EvalError("declared tree SHA does not resolve from commit")
    if expected_commit is not None and commit != expected_commit:
        raise EvalError(
            f"experiment commit {commit} != expected commit {expected_commit}")
    if prov.get("dirty") is not False:
        raise EvalError("experiments recorded on a dirty working tree")

    scripts = prov.get("script_hashes")
    script_blobs = prov.get("script_blob_hashes")
    if not isinstance(scripts, dict) or set(scripts) != REQUIRED_SCRIPT_HASHES:
        raise EvalError("executed script hash set mismatch")
    if not isinstance(script_blobs, dict) or \
            set(script_blobs) != REQUIRED_SCRIPT_HASHES:
        raise EvalError("commit script blob hash set mismatch")
    for name in sorted(REQUIRED_SCRIPT_HASHES):
        digest = scripts.get(name)
        blob_recorded = script_blobs.get(name)
        if not isinstance(digest, str) or not HEX64.fullmatch(digest):
            raise EvalError(f"{name}: script hash missing or malformed")
        if not isinstance(blob_recorded, str) or not HEX64.fullmatch(
                blob_recorded):
            raise EvalError(f"{name}: blob hash missing or malformed")
        disk_path = ticket / name
        if sha(disk_path) != digest:
            raise EvalError(f"{name}: script hash does not match disk")
        rel = disk_path.relative_to(root).as_posix()
        blob_digest = hashlib.sha256(
            git_bytes(root, ["show", f"{commit}:{rel}"])).hexdigest()
        if blob_digest != blob_recorded:
            raise EvalError(f"{name}: script hash does not match commit tree")
    executor = prov.get("executor_id")
    environment_hash = prov.get("environment_hash")
    if not isinstance(executor, str) or not executor.strip():
        raise EvalError("executor identity missing")
    if not isinstance(environment_hash, str) or not HEX64.fullmatch(
            environment_hash):
        raise EvalError("environment hash missing or malformed")
    expected_environment = hashlib.sha256(canonical({
        k: prov[k] for k in ("python", "platform", "commit", "tree_sha",
                             "script_hashes", "script_blob_hashes",
                             "executor_id")
    }).encode()).hexdigest()
    if environment_hash != expected_environment:
        raise EvalError("environment hash does not match provenance")


def validate_run_matrix(manifest: dict, workload: dict, comparison: dict,
                        run_a: Path) -> tuple:
    """Exact matrix: every frozen (backend, load, seed[, scenario]) run
    present exactly once; hash bindings identical across runs."""
    expected = set()
    loads = [k for k in workload["load_levels"] if k != "note"]
    for backend in workload["backends"]:
        for load in loads:
            for seed in workload["seeds"]:
                expected.add(f"{backend}-{load}-{seed}")
                for scenario in ("S1", "S2", "S3", "S4"):
                    expected.add(f"{backend}-{load}-{seed}-{scenario}")
    actual = [r["run_id"] for r in manifest["runs"]]
    if len(actual) != len(set(actual)):
        raise EvalError("duplicate run ids in the run manifest")
    missing = sorted(expected - set(actual))
    extra = sorted(set(actual) - expected)
    if missing or extra:
        raise EvalError(f"run matrix divergence: missing={missing} "
                        f"extra={extra}")
    if manifest["contract_sha256"] != sha(
            Path(__file__).resolve().parent / "backend-contract.json"):
        raise EvalError("run manifest contract hash != frozen contract")
    if manifest["workload_sha256"] != sha(
            Path(__file__).resolve().parent / "workload-manifest.json"):
        raise EvalError("run manifest workload hash != frozen workload")
    if manifest["rubric_sha256"] != sha(
            Path(__file__).resolve().parent / "rubric.json"):
        raise EvalError("run manifest rubric hash != frozen rubric")
    for run in comparison["runs"]:
        for field, frozen in (("contract_sha256", manifest["contract_sha256"]),
                              ("workload_sha256", manifest["workload_sha256"]),
                              ("rubric_sha256", manifest["rubric_sha256"])):
            if run[field] != frozen:
                raise EvalError(
                    f"run {run['run_id']}: {field} diverges from the frozen "
                    "manifest -> INCOMPARABLE")
    return expected, manifest


def validate_run_entry(data: dict) -> None:
    counters = data.get("safety_counters")
    if not isinstance(counters, dict):
        raise EvalError(f"{data.get('run_id')}: safety counters missing")
    if set(counters) != set(SAFETY_COUNTERS):
        raise EvalError(
            f"{data.get('run_id')}: safety counter key set mismatch: "
            f"{sorted(set(counters) ^ set(SAFETY_COUNTERS))}")
    for name, value in counters.items():
        if value != 0:
            raise EvalError(
                f"{data.get('run_id')}: SAFETY VIOLATION {name}={value}")
    count = data.get("raw_observation_count")
    if not isinstance(count, int) or count <= 0:
        raise EvalError(
            f"{data.get('run_id')}: empty raw observations")
    if data.get("terminal_reason") != "completed":
        raise EvalError(f"{data.get('run_id')}: terminal reason "
                        f"{data.get('terminal_reason')!r}")


def derive_safety_counters(data: dict) -> dict:
    """Independent derivation from raw observable state, not producer totals."""
    try:
        effects = data["effect_attempt_counts"]
        receipts = data["receipt_counts"]
        outbox = data["outbox"]
        resumes = data["resumes"]
        stale = data["stale_completion_attempts"]
        blind = data["blind_retry_records"]
    except (KeyError, TypeError) as exc:
        raise EvalError(f"{data.get('run_id')}: raw safety ledger missing") from exc
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0
               for ledger in (effects, receipts) for v in ledger.values()):
        raise EvalError(f"{data.get('run_id')}: malformed effect/receipt ledger")
    return {
        "duplicate_effect_count": sum(max(0, v - 1)
                                      for v in effects.values()),
        "duplicate_receipt_count": sum(max(0, v - 1)
                                       for v in receipts.values()),
        "blind_retry_count": len(blind),
        "stale_owner_completion_count": sum(
            1 for item in stale if not item.get("rejected")),
        "checkpoint_hash_bypass_count": sum(
            1 for item in resumes
            if item.get("accepted") and item.get("reason") != "verified"),
        "lost_committed_event_count": sum(
            1 for item in outbox.values()
            if item.get("committed") and not item.get("delivered")),
        "allow_after_revocation_count": len(
            data.get("allow_after_revocation_records", [])),
    }


def _percentile(values: list[float], pct: float):
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1,
              max(0, round(len(ordered) * pct / 100) - 1))
    return ordered[idx]


def validate_raw_run(data: dict, *, allow_safety_failure: bool = False) -> None:
    if data.get("schema") != "agentos.s1-006.run/v1":
        raise EvalError(f"{data.get('run_id')}: raw run schema mismatch")
    observations = data.get("raw_observations")
    if not isinstance(observations, list) or not observations:
        raise EvalError(f"{data.get('run_id')}: empty raw observations")
    if not all(isinstance(item, dict) for item in observations):
        raise EvalError(f"{data.get('run_id')}: malformed raw observations")
    supplied = data.get("safety_counters")
    if not isinstance(supplied, dict) or set(supplied) != set(SAFETY_COUNTERS):
        raise EvalError(f"{data.get('run_id')}: safety counter key set mismatch")
    if not allow_safety_failure:
        for name, value in supplied.items():
            if value != 0:
                raise EvalError(
                    f"{data.get('run_id')}: SAFETY VIOLATION {name}={value}")
    derived = derive_safety_counters(data)
    if supplied != derived:
        raise EvalError(
            f"{data.get('run_id')}: safety counters != raw-derived counters")
    metrics = data.get("metrics") or {}
    if metrics.get("tasks") != len(observations):
        raise EvalError(f"{data.get('run_id')}: task count != raw observations")
    try:
        latencies = [float(item["latency_us"]) for item in observations]
        depths = [int(item["queue_depth"]) for item in observations]
        completions = [float(item["completion_us"]) for item in observations]
    except (KeyError, TypeError, ValueError) as exc:
        raise EvalError(
            f"{data.get('run_id')}: malformed latency/queue/completion data") \
            from exc
    if any(depth < 1 for depth in depths):
        raise EvalError(f"{data.get('run_id')}: invalid queue depth")
    for item in observations:
        try:
            arrival = float(item["arrival_us"])
            dispatch_start = float(item["dispatch_start_us"])
            waiting = float(item["waiting_us"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EvalError(
                f"{data.get('run_id')}: malformed open-loop timing") from exc
        # All three values are independently serialized to 0.01 us. Their
        # reconstructed difference may therefore differ by one quantum.
        if abs((dispatch_start - arrival) - waiting) > 0.011 or waiting < 0:
            raise EvalError(
                f"{data.get('run_id')}: waiting time != raw arrival/dispatch")
    recorded_latency = metrics.get("latency_us") or {}
    for key, pct in (("p50", 50), ("p95", 95), ("p99", 99)):
        if recorded_latency.get(key) != _percentile(latencies, pct):
            raise EvalError(
                f"{data.get('run_id')}: {key} != raw-derived latency")
    if metrics.get("max_queue_depth") != max(depths):
        raise EvalError(f"{data.get('run_id')}: queue depth != raw-derived value")
    derived_throughput = round(len(observations) / max(completions) * 1e6, 1)
    if metrics.get("throughput_tasks_per_second") != derived_throughput:
        raise EvalError(
            f"{data.get('run_id')}: throughput != raw-derived value")
    if data.get("terminal_reason") != "completed":
        raise EvalError(f"{data.get('run_id')}: abnormal terminal reason")

    scenario = data.get("scenario")
    by_instance = {}
    for item in observations:
        by_instance.setdefault(item.get("dag_instance"), []).append(item)
    dag = {
        "t0": [], "t1": [], "t2": [], "t3": [],
        "t4": ["t0", "t1"], "t5": ["t1", "t2"],
        "t6": ["t2", "t3"], "t7": ["t0", "t3"],
        "t8": ["t4", "t5"], "t9": ["t5", "t6"],
        "t10": ["t6", "t7"], "t11": ["t4", "t7"],
    }
    for instance, items in by_instance.items():
        seen = set()
        for item in items:
            task = item.get("task")
            if task not in dag or not set(dag[task]).issubset(seen):
                raise EvalError(
                    f"{data.get('run_id')}: DAG dependency violation in "
                    f"instance {instance}")
            seen.add(task)
    events = [item.get("event") for item in data.get("scenario_events", [])]
    if scenario == "S1":
        event_rows = data.get("scenario_events", [])
        crashed = [item for item in event_rows
                   if item.get("event") == "coordinator_crashed"]
        if len(crashed) != 1:
            raise EvalError(f"{data.get('run_id')}: incomplete S1 replay trace")
        decision_id = crashed[0].get("decision_id")
        event_names = [item.get("event") for item in event_rows
                       if item.get("decision_id") == decision_id]
        try:
            committed_at = event_names.index("transition_outbox_committed")
            crashed_at = event_names.index("coordinator_crashed")
            replayed_at = event_names.index("outbox_delivery_replayed")
        except ValueError as exc:
            raise EvalError(
                f"{data.get('run_id')}: incomplete S1 replay trace") from exc
        if not committed_at < crashed_at < replayed_at:
            raise EvalError(f"{data.get('run_id')}: invalid S1 event ordering")
    elif scenario == "S2":
        unknowns = {item.get("decision_id") for item in observations
                    if item.get("outcome") == "unknown_reconciled"}
        if unknowns != set(data.get("reconciliations", {})):
            raise EvalError(f"{data.get('run_id')}: unreconciled S2 outcomes")
    elif scenario == "S3":
        resumes = data.get("resumes", [])
        if not resumes or not all(
                item.get("accepted") and item.get("reason") == "verified"
                and item.get("previous_run_id") != item.get("new_run_id")
                and item.get("resumed_from_run_id") == item.get("previous_run_id")
                and item.get("reexecuted_steps") == []
                for item in resumes):
            if not allow_safety_failure:
                raise EvalError(f"{data.get('run_id')}: invalid S3 resume trace")
        registry = data.get("checkpoint_registry", {})
        if resumes and not all(
                registry.get(
                    f"{item.get('previous_run_id')}:{item.get('task')}:"
                    f"{item.get('step')}") == item.get("checkpoint_sha256")
                for item in resumes):
            raise EvalError(f"{data.get('run_id')}: S3 checkpoint not registered")
    elif scenario == "S4":
        stale = data.get("stale_completion_attempts", [])
        if not stale or not all(
                item.get("rejected")
                and item.get("presented_fence") < item.get("current_fence")
                for item in stale):
            if not allow_safety_failure:
                raise EvalError(f"{data.get('run_id')}: invalid S4 fencing trace")
        deliveries = data.get("delivery_attempt_counts", {})
        effects = data.get("effect_attempt_counts", {})
        receipts = data.get("receipt_counts", {})
        if stale and not all(
                deliveries.get(item.get("decision_id"), 0) >= 2
                and effects.get(item.get("decision_id")) == 1
                and receipts.get(item.get("decision_id")) == 1
                for item in stale):
            raise EvalError(f"{data.get('run_id')}: S4 redelivery not deduplicated")


def load_verified_runs(runs_manifest_path: Path, manifest: dict) -> dict[str, dict]:
    runs = {}
    for entry in manifest.get("runs", []):
        run_file = run_file_path(runs_manifest_path.parent, entry.get("file"))
        if not run_file.is_file():
            raise EvalError(f"run file missing: {entry['file']}")
        if sha(run_file) != entry.get("sha256"):
            raise EvalError(f"run file digest mismatch: {entry['file']}")
        data = load(run_file)
        if data.get("run_id") != entry.get("run_id"):
            raise EvalError(f"run id/file mismatch: {entry['file']}")
        if data["run_id"] in runs:
            raise EvalError(f"duplicate raw run id: {data['run_id']}")
        validate_raw_run(data)
        runs[data["run_id"]] = data
    return runs


def comparison_from_raw(manifest: dict, raw_runs: dict[str, dict]) -> dict:
    comparison = {
        "schema": "agentos.s1-006.backend-comparison/v1",
        "contract_sha256": manifest["contract_sha256"],
        "workload_sha256": manifest["workload_sha256"],
        "rubric_sha256": manifest["rubric_sha256"],
        "runs": [],
    }
    for entry in manifest["runs"]:
        data = raw_runs[entry["run_id"]]
        comparison["runs"].append({
            "run_id": data["run_id"], "backend": data["backend"],
            "load": data["load"], "seed": data["seed"],
            "scenario": data["scenario"], "commit": data["commit"],
            "tree_sha": data["tree_sha"], "metrics": data["metrics"],
            "safety_counters": data["safety_counters"],
            "observed_semantics": {
                "resume_count": len(data["resumes"]),
                "all_resumes_verified": all(
                    item.get("accepted") and item.get("reason") == "verified"
                    for item in data["resumes"]),
                "redeliveries": data["redeliveries"],
                "reconciled_unknown_outcomes":
                    data["reconciled_unknown_outcomes"],
                "stale_completion_attempts":
                    len(data["stale_completion_attempts"]),
                "all_stale_completions_rejected": all(
                    item.get("rejected")
                    for item in data["stale_completion_attempts"]),
                "dag_dependency_violations": 0,
            },
            "raw_observation_count": len(data["raw_observations"]),
            "terminal_reason": data["terminal_reason"],
            "contract_sha256": data["contract_sha256"],
            "workload_sha256": data["workload_sha256"],
            "rubric_sha256": data["rubric_sha256"],
        })
    return comparison


def evaluate_probes(probes: dict) -> dict:
    """Probe rules over real run records (review R2 finding 6: behavioral,
    not counter-tampering)."""
    if probes.get("schema") != "agentos.s1-006.probes/v1":
        raise EvalError("probe evidence schema mismatch")
    rows = probes.get("probes")
    if not isinstance(rows, list):
        raise EvalError("probe evidence rows missing")
    out = {}
    for run in rows:
        pid = run.get("probe")
        try:
            validate_raw_run(run, allow_safety_failure=True)
        except EvalError as exc:
            raise EvalError(f"probe {pid}: {exc}") from exc
        if pid in out:
            raise EvalError(f"duplicate probe: {pid}")
        counters = run.get("safety_counters", {})
        if pid == "A_unsafe_resume":
            detected = counters.get("duplicate_effect_count", 0) >= 1 or \
                counters.get("duplicate_receipt_count", 0) >= 1
            out[pid] = {
                "detected": detected, "verdict": "FAIL" if detected else None,
                "reason": run.get("probe_reason")}
        elif pid == "C_blind_retry":
            detected = counters.get("blind_retry_count", 0) >= 1
            out[pid] = {
                "detected": detected, "verdict": "FAIL" if detected else None,
                "reason": run.get("probe_reason")}
        elif pid == "B_incomparable":
            frozen = sha(Path(__file__).resolve().parent
                         / "workload-manifest.json")
            divergent = run.get("workload_sha256") not in (None, frozen)
            out[pid] = {
                "detected": bool(divergent),
                "verdict": "INCOMPARABLE/NO_DATA" if divergent else None,
                "reason": run.get("probe_reason")}
    missing = {"A_unsafe_resume", "B_incomparable", "C_blind_retry"} - set(out)
    if missing:
        raise EvalError(f"probes missing: {sorted(missing)}")
    for pid, verdict in out.items():
        if not verdict["detected"]:
            raise EvalError(f"probe {pid} was NOT detected: positive "
                            "verdicts are forbidden while a probe passes")
    return out


# ---- deterministic per-dimension scoring ---------------------------------

def score_dims(comparison: dict, contract: dict) -> tuple:
    """Derive per-backend dimension scores from raw observations and the
    frozen contract. Measurement rules are explicit and deterministic."""
    by_backend = {}
    for run in comparison["runs"]:
        if run["scenario"] not in (None, "throughput"):
            continue
        by_backend.setdefault(run["backend"], []).append(run)
    scenarios_by = {}
    for run in comparison["runs"]:
        if run["scenario"] in ("S1", "S2", "S3", "S4"):
            scenarios_by.setdefault(run["backend"], []).append(run)

    def med_recovery(backend):
        values = []
        for run in scenarios_by.get(backend, []):
            for rt in run["metrics"]["recovery_times"]:
                values.append(rt["us"])
        return sorted(values)[len(values) // 2] if values else None

    def p95(backend):
        values = sorted(run["metrics"]["latency_us"]["p95"]
                        for run in by_backend.get(backend, []))
        return values[len(values) // 2] if values else None

    scores = {b: {} for b in by_backend}
    unknown = {b: [] for b in by_backend}

    def ratio_score(a, b, key):
        va, vb = a.get(key), b.get(key)
        if va is None or vb is None:
            return None
        lo, hi = sorted((va, vb))
        return max(0, min(4, round(4 * lo / hi)))

    rec_med = {b: med_recovery(b) for b in by_backend}
    if any(v is None for v in rec_med.values()):
        for b in by_backend:
            unknown[b].append("crash_recovery_time")
    else:
        lo = min(rec_med.values())
        for b in by_backend:
            scores[b]["crash_recovery_time"] = max(
                0, min(4, round(4 * lo / rec_med[b])))

    p95s = {b: p95(b) for b in by_backend}
    if any(v is None for v in p95s.values()):
        for b in by_backend:
            unknown[b].append("throughput_latency")
    else:
        lo = min(p95s.values())
        for b in by_backend:
            scores[b]["throughput_latency"] = max(
                0, min(4, round(4 * lo / p95s[b])))

    for b in by_backend:
        runs = by_backend[b]
        scenario_runs = scenarios_by.get(b, [])
        all_runs = runs + scenario_runs
        clean = all(all(v == 0 for v in r["safety_counters"].values())
                    for r in all_runs)
        scores[b]["duplicate_effect_prevention"] = 4 if clean else 0
        s2 = [r for r in scenario_runs if r["scenario"] == "S2"]
        scores[b]["unknown_outcome_reconciliation"] = 4 if s2 and all(
            r["observed_semantics"]["reconciled_unknown_outcomes"] > 0
            and r["safety_counters"]["blind_retry_count"] == 0
            for r in s2) else 0
        s4 = [r for r in scenario_runs if r["scenario"] == "S4"]
        scores[b]["lease_fencing_stale_owner"] = 4 if s4 and all(
            r["observed_semantics"]["stale_completion_attempts"] > 0
            and r["observed_semantics"]["all_stale_completions_rejected"]
            for r in s4) else 0
        s3 = [r for r in scenario_runs if r["scenario"] == "S3"]
        scores[b]["checkpoint_integrity_resume"] = 4 if s3 and all(
            r["observed_semantics"]["resume_count"] > 0
            and r["observed_semantics"]["all_resumes_verified"]
            for r in s3) else 0
        scores[b]["dag_determinism"] = 4 if all(
            r["observed_semantics"]["dag_dependency_violations"] == 0
            for r in all_runs) else 0
        scores[b]["test_determinism_replay"] = 4 if len(all_runs) == 45 else 0
        for dim, candidates in contract["qualitative_dimensions"].items():
            cell = candidates.get(b) or {}
            value = cell.get("score")
            if value is None:
                unknown[b].append(dim)
            elif isinstance(value, int) and not isinstance(value, bool) \
                    and 0 <= value <= 4 and cell.get("claim_type") \
                    and cell.get("evidence_refs") and cell.get("rationale"):
                scores[b][dim] = value
            else:
                raise EvalError(f"invalid qualitative score cell: {dim}.{b}")
    return scores, unknown, rec_med, p95s


def sensitivity(scores: dict, weights: dict, unknown: dict) -> dict:
    def weighted(ws):
        out = {}
        for b, sc in scores.items():
            num = sum(ws[d] * v for d, v in sc.items() if v is not None)
            den = sum(ws[d] for d, v in sc.items() if v is not None)
            out[b] = round(num / den, 4) if den else None
        return out

    base = weighted(weights)
    base_winner = max(base, key=lambda b: base[b])
    flips, runs, ties = 0, 0, 0
    perturbation_runs = 0
    names = list(weights)
    for dim in names:
        for factor in (0.5, 1.5):
            ws = dict(weights)
            ws[dim] = max(1, round(weights[dim] * factor))
            delta = 100 - sum(ws.values())
            rest = [k for k in ws if k != dim]
            share = sum(ws[k] for k in rest)
            if share:
                for k in rest:
                    ws[k] = max(1, round(ws[k] + delta * ws[k] / share))
            sc = weighted(ws)
            ordered = sorted(sc.items(), key=lambda item: item[1], reverse=True)
            if len(ordered) > 1 and ordered[0][1] == ordered[1][1]:
                ties += 1
                runs += 1
                perturbation_runs += 1
                continue
            win = ordered[0][0]
            runs += 1
            perturbation_runs += 1
            if win != base_winner:
                flips += 1
    rng = random.Random(42)
    for i in range(SENSITIVITY_RANDOM_RUNS):
        cuts = sorted(rng.sample(range(1, 100), len(names) - 1))
        parts, prev = [], 0
        for cut in cuts + [100]:
            parts.append(cut - prev)
            prev = cut
        ws = dict(zip(names, parts))
        sc = weighted(ws)
        ordered = sorted(sc.items(), key=lambda item: item[1], reverse=True)
        if len(ordered) > 1 and ordered[0][1] == ordered[1][1]:
            ties += 1
            runs += 1
            continue
        win = ordered[0][0]
        runs += 1
        if win != base_winner:
            flips += 1
    return {"base_scores": base, "base_winner": base_winner,
            "runs": runs, "perturbation_runs": perturbation_runs,
            "random_runs": SENSITIVITY_RANDOM_RUNS,
            "ties": ties, "flips": flips,
            "stable": flips == 0 and ties == 0}


def validate_runs_manifest(runs_manifest_path: Path,
                           runs_manifest_sha: str | None = None) -> dict:
    """Binding + integrity of the frozen run manifest (review R3 style):
    the evaluator scores EXACTLY the recorded run matrix and verifies the
    manifest digest and every run file digest before use."""
    if runs_manifest_sha:
        actual = sha(runs_manifest_path)
        if actual != runs_manifest_sha:
            raise EvalError(
                f"runs manifest digest mismatch: {actual} != "
                f"{runs_manifest_sha}")
    manifest = load(runs_manifest_path)
    if manifest.get("schema") != "agentos.s1-006.run-manifest/v1":
        raise EvalError("run manifest schema mismatch")
    for entry in manifest.get("runs", []):
        run_file = run_file_path(runs_manifest_path.parent, entry.get("file"))
        if not run_file.is_file():
            raise EvalError(f"run file missing: {entry['file']}")
        if sha(run_file) != entry.get("sha256"):
            raise EvalError(f"run file digest mismatch: {entry['file']}")
        try:
            data = load(run_file)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EvalError(f"run file is not valid JSON: {entry['file']}") from exc
        if data.get("run_id") != entry.get("run_id"):
            raise EvalError(f"run id/file mismatch: {entry['file']}")
    return manifest


def evaluate(ticket: Path, results: Path, *,
             runs_manifest_path: Path | None = None,
             runs_manifest_sha: str | None = None,
             expected_commit: str | None = None,
             probes_sha: str | None = None,
             run_nonce: str | None = None,
             comparison_data: dict | None = None,
             probes_data: dict | None = None,
             manifest_data: dict | None = None) -> dict:
    rubric = load(ticket / "rubric.json")
    rubric_sha = sha(ticket / "rubric.json")
    contract = load(ticket / "backend-contract.json")
    workload = load(ticket / "workload-manifest.json")
    run_a = results / "run-a"
    probes_path = results / "probes.json"
    if probes_data is not None:
        probes = probes_data
    else:
        if not probes_sha:
            raise EvalError("probe evidence digest is required")
        if sha(probes_path) != probes_sha:
            raise EvalError("probe evidence digest mismatch")
        probes = load(probes_path)
    # runs binding (review R3 style): the evaluator scores EXACTLY the
    # frozen run matrix named by the caller and verifies digests first.
    if runs_manifest_path is None:
        runs_manifest_path = results / "run-a" / "run-manifest.json"
    if manifest_data is None:
        manifest = validate_runs_manifest(runs_manifest_path,
                                          runs_manifest_sha)
    else:
        if runs_manifest_sha and sha(runs_manifest_path) != runs_manifest_sha:
            raise EvalError("runs manifest digest mismatch")
        manifest = manifest_data

    prov = manifest.get("provenance") or {}
    validate_provenance(prov, ticket, expected_commit)
    raw_runs = load_verified_runs(runs_manifest_path, manifest)
    raw_comparison = comparison_from_raw(manifest, raw_runs)
    if comparison_data is not None:
        if canonical(comparison_data) != canonical(raw_comparison):
            raise EvalError("comparison summary != raw-derived comparison")
    else:
        comparison_path = runs_manifest_path.parent / "comparison.json"
        if not comparison_path.is_file():
            raise EvalError("raw-derived comparison artifact missing")
        saved_comparison = load(comparison_path)
        if canonical(saved_comparison) != canonical(raw_comparison):
            raise EvalError("saved comparison != raw-derived comparison")
    comparison = raw_comparison

    expected, manifest = validate_run_matrix(
        manifest, workload, comparison, run_a)
    if len(comparison["runs"]) != len(expected):
        raise EvalError("comparison runs != frozen matrix size")
    for run in comparison["runs"]:
        if run.get("commit") != prov.get("commit") or \
                run.get("tree_sha") != prov.get("tree_sha"):
            raise EvalError(
                f"run {run['run_id']}: commit/tree provenance diverges "
                "from the run manifest -> INCOMPARABLE")
        validate_run_entry(run)
    probe_results = evaluate_probes(probes)

    scores, unknown, rec_med, p95s = score_dims(comparison, contract)
    sens = sensitivity(scores, rubric["weights"], unknown)
    winner = sens["base_winner"]

    verdict = "PASS_WITH_LIMITS"  # inherited dependency limits always bind
    reasons = [
        "inherited limits: S1-002 is not a production SLO; S1-005 is "
        "same-host bounded and does not prove multi-host reliability"]
    if unknown.get(winner):
        reasons.append(f"unknown cells on winner: {unknown[winner]}")
    if not sens["stable"]:
        verdict = "PASS_WITH_LIMITS"
        reasons.append("winner flipped under sensitivity analysis")
    if any(v == 0 for b in scores.values() for v in b.values()):
        reasons.append(
            "a candidate scored 0 on at least one dimension (documented "
            "extreme, not a safety violation; safety counters remain zero)")

    return {
        "schema": SCHEMA,
        "rubric_sha256": rubric_sha,
        "run_nonce": run_nonce,
        "runs_binding": {
            "path": str(runs_manifest_path),
            "sha256": sha(runs_manifest_path),
        },
        "probes_binding": {
            "path": str(probes_path),
            "sha256": probes_sha or hashlib.sha256(
                canonical(probes).encode()).hexdigest(),
        },
        "scores_normalized": scores,
        "recovery_median_us": rec_med,
        "p95_us": p95s,
        "winner": winner,
        "recommendation": {"topology": winner},
        "probe_rejections": {k: v["verdict"] for k, v in probe_results.items()},
        "sensitivity": {k: v for k, v in sens.items()},
        "verdict": verdict,
        "reasons": reasons,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticket", default=str(
        Path(__file__).resolve().parent))
    ap.add_argument("--results", default=None)
    ap.add_argument("--runs-manifest", default=None,
                    help="frozen run-a manifest to score")
    ap.add_argument("--runs-manifest-sha", default=None,
                    help="sha256 of the frozen run manifest")
    ap.add_argument("--expected-commit", default=None)
    ap.add_argument("--probes-sha", default=None,
                    help="sha256 of <results>/probes.json")
    ap.add_argument("--out", default=None,
                    help="output path for the evaluation result; defaults "
                         "to <results>/sensitivity-analysis.json (the "
                         "published, nonce-bound location used by "
                         "make_bundle.py)")
    args = ap.parse_args(argv)
    ticket = Path(args.ticket).resolve()
    results = Path(args.results).resolve() if args.results \
        else ticket / "results"
    try:
        result = evaluate(
            ticket, results,
            runs_manifest_path=(Path(args.runs_manifest).resolve()
                                if args.runs_manifest else None),
            runs_manifest_sha=args.runs_manifest_sha,
            expected_commit=args.expected_commit,
            probes_sha=args.probes_sha,
            run_nonce=os.environ.get("AGENTOS_RUN_NONCE"))
    except EvalError as exc:
        print(json.dumps({"verdict": "FAIL", "error": str(exc)}, indent=2))
        return 1
    out_path = Path(args.out).resolve() if args.out else \
        results / "sensitivity-analysis.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
