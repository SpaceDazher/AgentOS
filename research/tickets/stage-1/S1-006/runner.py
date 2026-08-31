"""AgentOS S1-006 — deterministic execution-backend benchmark/simulator.

Discrete-event simulation over the frozen backend contract and workload
manifest. Both candidate backends implement identical AgentOS semantics
(one state owner, atomic transition+audit/outbox, gateway-only effects,
reconciliation for unknown outcomes, lease/fencing, checkpoint-hash
resume, deduplicated at-least-once delivery); they differ only in the
measured/modelled cost parameters and crash blast radius recorded in
backend-contract.json.

Modes:
  main    --out results/run-a   full frozen run matrix (90 runs)
  rerun   --out results/run-b   identical matrix in a separate process
  probes  --out results/probes.json  adversarial candidates through the
          same simulation code paths, evaluated by evaluator.py

Determinism: random.Random(seed) per run; no wall clock in the model; no
dict-order dependence. Every run records contract/workload/rubric sha256,
commit, tree, dirty flag and the environment manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import subprocess
import sys
from pathlib import Path

TICKET = Path(__file__).resolve().parent
ROOT = TICKET.parents[3]

SCHEMA = "agentos.s1-006.run/v1"
SAFETY_COUNTERS = (
    "duplicate_effect_count", "duplicate_receipt_count", "blind_retry_count",
    "stale_owner_completion_count", "checkpoint_hash_bypass_count",
    "lost_committed_event_count", "allow_after_revocation_count",
)
EVIDENCE_SCRIPTS = (
    "runner.py", "evaluator.py", "make_bundle.py", "dependency_gate.py",
    "bundle_content.py",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(args: list) -> str | None:
    try:
        out = subprocess.run(["git", *args], capture_output=True,
                             text=True, timeout=30, cwd=str(ROOT))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"git {' '.join(args)} failed: {exc}") from exc
    if out.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({out.returncode}): "
            f"{out.stderr.strip()}")
    value = out.stdout.strip()
    if not value:
        raise RuntimeError(f"git {' '.join(args)} returned empty output")
    return value


def _git_lines(args: list) -> list:
    """Raw git stdout lines (no global strip: porcelain status columns
    are positional and the leading space of ' M path' matters)."""
    try:
        out = subprocess.run(["git", *args], capture_output=True,
                             text=True, timeout=30, cwd=str(ROOT))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"git {' '.join(args)} failed: {exc}") from exc
    if out.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({out.returncode}): "
            f"{out.stderr.strip()}")
    return out.stdout.splitlines()


def _git_bytes(args: list) -> bytes:
    try:
        out = subprocess.run(["git", *args], capture_output=True,
                             timeout=30, cwd=str(ROOT))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"git {' '.join(args)} failed: {exc}") from exc
    if out.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({out.returncode}): "
            f"{out.stderr.decode(errors='replace').strip()}")
    return out.stdout


def research_surface_dirty_lines(porcelain_lines: list) -> list:
    """Return dirty input lines, ignoring only generated S1-006 outputs.

    Executed scripts, tests and contracts are evidence inputs and therefore
    must be committed.  The runner may replace tracked result files while it
    executes; that one explicit output subtree is not an input-dirty signal.
    """
    dirty = []
    for ln in porcelain_lines:
        if not ln.strip():
            continue
        path = ln[3:].strip().strip('"')
        if path.startswith("research/tickets/stage-1/S1-006/results/") or \
                path == "research/tickets/stage-1/S1-006/bundle.json":
            continue
        dirty.append(ln)
    return dirty


_PROV_CACHE: dict | None = None


def provenance() -> dict:
    global _PROV_CACHE
    if _PROV_CACHE is not None:
        return _PROV_CACHE
    scripts = {}
    script_blobs = {}
    commit = _git(["rev-parse", "HEAD"])
    for name in EVIDENCE_SCRIPTS:
        path = TICKET / name
        if path.is_file():
            scripts[name] = _sha(path.read_bytes())
            rel = path.relative_to(ROOT).as_posix()
            script_blobs[name] = _sha(
                _git_bytes(["show", f"{commit}:{rel}"]))
    # Only generated result files are excluded. Executed scripts, tests,
    # contracts and research inputs must all be committed and clean.
    dirty_lines = research_surface_dirty_lines(
        _git_lines(["status", "--porcelain"]))
    result = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "commit": commit,
        "tree_sha": _git(["rev-parse", "HEAD^{tree}"]),
        "dirty": bool(dirty_lines),
        "dirty_lines": dirty_lines,
        "script_hashes": scripts,
        "script_blob_hashes": script_blobs,
        "executor_id": os.environ.get("AGENTOS_EXECUTOR_ID", "direct-test"),
    }
    result["environment_hash"] = _sha(json.dumps(
        {k: result[k] for k in ("python", "platform", "commit", "tree_sha",
                                "script_hashes", "script_blob_hashes",
                                "executor_id")},
        sort_keys=True, separators=(",", ":")).encode())
    _PROV_CACHE = result
    return result


def percentile(sorted_values: list, pct: float):
    if not sorted_values:
        return None
    idx = min(len(sorted_values) - 1,
              max(0, round(len(sorted_values) * pct / 100) - 1))
    return sorted_values[idx]


def content_hash(run_id: str, task: str, step: int) -> str:
    """Verified content hash of a checkpoint (DB-bound by run/task/step)."""
    return _sha(f"{run_id}:{task}:{step}".encode())


class CheckpointStore:
    """DB-bound checkpoint registry: a run resumes only from a registered
    checkpoint whose presented content hash matches the registered one.
    Unregistered or corrupted checkpoints are rejected fail-closed."""

    def __init__(self):
        self._registered = {}

    def put(self, run_id: str, task: str, step: int, content: str) -> None:
        self._registered[(run_id, task, step)] = content

    def resume(self, run_id: str, task: str, step: int,
               presented: str) -> tuple[bool, str]:
        registered = self._registered.get((run_id, task, step))
        if registered is None:
            return False, "unregistered-checkpoint"
        if registered != presented:
            return False, "corrupt-checkpoint"
        return True, "verified"


def deliver_effect(decision_id: str, receipts: dict) -> bool:
    """Gateway delivery with local idempotency: at-least-once redelivery
    never creates a second local effect receipt. Returns True only on the
    first delivery of a decision."""
    if decision_id in receipts:
        return False
    receipts[decision_id] = 1
    return True


def retry_after_unknown(decision_id: str, reconciliations: dict,
                        counters: dict, *, allow_retry: bool) -> str:
    """SAF: an unknown external outcome is retried only after a recorded
    reconciliation resolution; a retry without that evidence is blind and
    is counted as a safety violation."""
    if allow_retry and decision_id in reconciliations:
        return "retry-after-reconciliation"
    counters["blind_retry_count"] += 1
    return "blind-retry"


# --------------------------------------------------------------------------
# DAG (frozen shape; identical for both backends)

DAG = {
    "t0": [], "t1": [], "t2": [], "t3": [],
    "t4": ["t0", "t1"], "t5": ["t1", "t2"], "t6": ["t2", "t3"],
    "t7": ["t0", "t3"],
    "t8": ["t4", "t5"], "t9": ["t5", "t6"], "t10": ["t6", "t7"],
    "t11": ["t4", "t7"],
}
LAYER_ORDER = ["t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
               "t8", "t9", "t10", "t11"]

LOADS = {"low": 40, "nominal": 120, "high": 360}
SEEDS = [101, 202, 303]
BACKENDS = ["in_process", "durable_engine"]
SCENARIOS = ["S1", "S2", "S3", "S4"]


def task_sequence(arrivals: int, rng: random.Random) -> list:
    """Dependency-ready execution sequence: tasks are drawn from ready
    layers; within a layer the seeded rng picks, mirroring a dependency-
    ready scheduler without changing DAG semantics."""
    seq = []
    while len(seq) < arrivals:
        done = set()
        while len(done) < len(DAG) and len(seq) < arrivals:
            ready = [t for t in LAYER_ORDER
                     if t not in done and all(d in done for d in DAG[t])]
            if not ready:
                raise RuntimeError("frozen DAG has no dependency-ready task")
            task = rng.choice(ready)
            seq.append(task)
            done.add(task)
    return seq


# --------------------------------------------------------------------------

def simulate(backend: str, load: str, seed: int, scenario: str | None = None,
             mutations: tuple = ()) -> dict:
    contract = json.loads((TICKET / "backend-contract.json").read_text(
        encoding="utf-8"))
    manifest = json.loads((TICKET / "workload-manifest.json").read_text(
        encoding="utf-8"))
    params = contract["candidates"][backend]["measured_parameters"]
    arrivals = manifest["load_levels"][load]["arrivals"]
    arrival_interval_us = manifest["load_levels"][load]["arrival_interval_us"]

    rng = random.Random(seed)
    sequence = task_sequence(arrivals, rng)

    dispatch_us = params["dispatch_us"]
    write_us = params["state_write_us"]
    lease_timeout_us = params.get("lease_timeout_ms", 0) * 1000
    recovery_us = params.get("crash_recovery_ms", 0) * 1000

    now = 0.0
    decisions = []       # one decision per gateway effect
    raw_latency = []
    queue_depths = []
    observations = []
    recovery_times = []
    receipts = {}        # decision_id -> local effect receipt count
    effect_attempts = {} # decision_id -> actual external effect executions
    delivery_attempts = {}  # decision_id -> gateway delivery attempts
    outbox = {}          # decision_id -> committed/delivered state
    reconciliations = {}  # decision_id -> resolution evidence
    blind_retries = []
    resumes = []         # S3 checkpoint-resume decisions
    stale_completion_attempts = []
    scenario_events = []
    redeliveries = 0     # S4 at-least-once redelivery attempts
    run_key = f"{backend}-{load}-{seed}" + (f"-{scenario}" if scenario else "")
    checkpoint_store = CheckpointStore()
    checkpoint_registry = {}
    current_fence = 1

    outcome_roll = {"ack": 0.9, "nack": 0.05, "unknown_reconciled": 0.05}

    def outcome_for(task, tick):
        decision_id = f"{task}#{tick}"
        roll = rng.random()
        if scenario == "S2" and tick == arrivals // 3:
            # S2 is a fault scenario, not a probabilistic hope: every seed
            # contains at least one started effect with an unknown outcome.
            outcome = "unknown_reconciled"
        else:
            outcome = ("ack" if roll < outcome_roll["ack"]
                       else "nack" if roll < outcome_roll["ack"]
                       + outcome_roll["nack"]
                       else "unknown_reconciled")
        decisions.append(decision_id)
        return decision_id, outcome

    def gateway_deliver(decision_id: str, *, replayed: bool = False) -> bool:
        """Execute the external effect only when the receipt ledger has no
        entry.  A redelivery is observed but absorbed before the effect."""
        delivery_attempts[decision_id] = delivery_attempts.get(decision_id, 0) + 1
        if decision_id in receipts:
            scenario_events.append({
                "event": "redelivery_deduplicated", "decision_id": decision_id})
            return False
        effect_attempts[decision_id] = effect_attempts.get(decision_id, 0) + 1
        receipts[decision_id] = receipts.get(decision_id, 0) + 1
        outbox[decision_id]["delivered"] = True
        scenario_events.append({
            "event": "outbox_delivery_replayed" if replayed
            else "effect_delivered",
            "decision_id": decision_id,
        })
        return True

    def unsafe_deliver(decision_id: str) -> None:
        """Mutation path: bypass gateway dedup and really execute/receipt a
        second effect.  Counters are derived later from these ledgers."""
        delivery_attempts[decision_id] = delivery_attempts.get(decision_id, 0) + 1
        effect_attempts[decision_id] = effect_attempts.get(decision_id, 0) + 1
        receipts[decision_id] = receipts.get(decision_id, 0) + 1
        outbox[decision_id]["delivered"] = True
        scenario_events.append({
            "event": "unsafe_duplicate_effect_executed",
            "decision_id": decision_id,
        })

    crash_after = None
    if scenario in ("S1", "S3"):
        crash_after = rng.randrange(max(2, arrivals // 3), arrivals)
    lease_fired = False

    for i, task in enumerate(sequence):
        arrival_us = i * arrival_interval_us
        dispatch_start = max(now, arrival_us)
        waiting_us = dispatch_start - arrival_us
        arrived_by_dispatch = min(
            arrivals, int(math.floor(dispatch_start / arrival_interval_us)) + 1)
        depth = max(1, arrived_by_dispatch - i)
        now = dispatch_start + dispatch_us
        queue_depths.append(depth)
        scheduling_latency_us = now - arrival_us
        raw_latency.append(scheduling_latency_us)

        decision_id, outcome = outcome_for(task, i)
        # The transition and outbox entry commit atomically before delivery.
        now += write_us
        outbox[decision_id] = {
            "committed": True, "delivered": False, "task": task,
            "commit_index": i,
        }
        scenario_events.append({
            "event": "transition_outbox_committed",
            "decision_id": decision_id,
        })

        if scenario == "S1" and crash_after is not None and i == crash_after:
            scenario_events.append({
                "event": "coordinator_crashed", "decision_id": decision_id})
            now += recovery_us
            recovery_times.append({"scenario": "S1", "us": recovery_us})
            if "drop_outbox" not in mutations:
                gateway_deliver(decision_id, replayed=True)
        else:
            gateway_deliver(decision_id)

        if outcome == "unknown_reconciled":
            reconciliations[decision_id] = "resolved-by-evidence"
            scenario_events.append({
                "event": "unknown_outcome_reconciled",
                "decision_id": decision_id,
            })
            if "blind_retry" in mutations:
                local = {c: 0 for c in SAFETY_COUNTERS}
                retry_after_unknown(decision_id, {}, local, allow_retry=True)
                if local["blind_retry_count"]:
                    blind_retries.append({
                        "decision_id": decision_id,
                        "reconciliation_evidence": None,
                    })

        # checkpoint is persisted and registered before any S3 crash.
        checkpoint_hash = content_hash(run_key, task, i)
        now += write_us
        checkpoint_store.put(run_key, task, i, checkpoint_hash)
        checkpoint_registry[f"{run_key}:{task}:{i}"] = checkpoint_hash

        if scenario == "S3" and crash_after is not None and i == crash_after:
            previous_run_id = run_key
            new_run_id = f"{run_key}-resume-1"
            scenario_events.append({
                "event": "run_crashed_after_checkpoint",
                "run_id": previous_run_id,
            })
            if "checkpoint_bypass" in mutations:
                accepted, reason = True, "bypassed-verification"
            else:
                accepted, reason = checkpoint_store.resume(
                    run_key, task, i, checkpoint_hash)
            resumes.append({
                "task": task, "step": i, "accepted": accepted,
                "reason": reason, "previous_run_id": previous_run_id,
                "new_run_id": new_run_id,
                "resumed_from_run_id": previous_run_id,
                "checkpoint_sha256": checkpoint_hash,
                "reexecuted_steps": [],
            })
            scenario_events.append({
                "event": "run_resumed_from_verified_checkpoint",
                "previous_run_id": previous_run_id,
                "new_run_id": new_run_id,
                "accepted": accepted,
            })
            if "unsafe_resume" in mutations:
                unsafe_deliver(decision_id)
            now += recovery_us
            recovery_times.append({"scenario": "S3", "us": recovery_us})

        if scenario == "S4" and not lease_fired and i >= arrivals // 3:
            lease_fired = True
            redeliveries += 1
            gateway_deliver(decision_id)
            presented_fence = current_fence
            current_fence += 1
            rejected = "no_fencing" not in mutations
            stale_completion_attempts.append({
                "decision_id": decision_id,
                "presented_fence": presented_fence,
                "current_fence": current_fence,
                "rejected": rejected,
            })
            scenario_events.append({
                "event": "stale_completion_rejected" if rejected
                else "stale_completion_accepted",
                "decision_id": decision_id,
            })
            now += lease_timeout_us
            recovery_times.append({"scenario": "S4", "us": lease_timeout_us})

        if scenario == "S2" and outcome == "unknown_reconciled":
            local = {c: 0 for c in SAFETY_COUNTERS}
            retry_after_unknown(decision_id, reconciliations, local,
                                allow_retry=True)
            now += write_us

        observations.append({
            "i": i, "task": task, "dag_instance": i // len(DAG),
            "decision_id": decision_id,
            "arrival_us": round(arrival_us, 2),
            "dispatch_start_us": round(dispatch_start, 2),
            "waiting_us": round(waiting_us, 2),
            "dispatch_us": round(dispatch_us, 2),
            "queue_depth": depth,
            "latency_us": round(scheduling_latency_us, 2),
            "completion_us": round(now, 2),
            "outcome": outcome,
        })

    span = max(now, 1e-9)
    ordered = sorted(raw_latency)
    prov = provenance()
    run = {
        "schema": SCHEMA,
        "run_id": f"{backend}-{load}-{seed}"
                  + (f"-{scenario}" if scenario else ""),
        "backend": backend, "load": load, "seed": seed,
        "scenario": scenario or "throughput",
        "mutations": list(mutations),
        "commit": prov["commit"],
        "tree_sha": prov["tree_sha"],
        "dirty": prov["dirty"],
        "contract_sha256": _sha((TICKET / "backend-contract.json")
                                .read_bytes()),
        "workload_sha256": _sha((TICKET / "workload-manifest.json")
                                .read_bytes()),
        "rubric_sha256": _sha((TICKET / "rubric.json").read_bytes()),
        "metrics": {
            "tasks": len(sequence),
            "latency_us": {
                "p50": round(percentile(ordered, 50), 2),
                "p95": round(percentile(ordered, 95), 2),
                "p99": round(percentile(ordered, 99), 2),
            },
            "throughput_tasks_per_second": round(len(sequence) / span * 1e6, 1),
            "max_queue_depth": max(queue_depths) if queue_depths else 0,
            "recovery_times": recovery_times,
        },
        "resumes": resumes,
        "redeliveries": redeliveries,
        "reconciled_unknown_outcomes": len(reconciliations),
        "reconciliations": reconciliations,
        "outbox": outbox,
        "checkpoint_registry": checkpoint_registry,
        "effect_attempt_counts": effect_attempts,
        "delivery_attempt_counts": delivery_attempts,
        "receipt_counts": receipts,
        "blind_retry_records": blind_retries,
        "stale_completion_attempts": stale_completion_attempts,
        "scenario_events": scenario_events,
        "raw_observations": observations,
        "terminal_reason": "completed",
    }
    run["safety_counters"] = derive_safety_counters(run)
    return run


def derive_safety_counters(run: dict) -> dict:
    """Derive safety counters from observable ledgers/traces.

    The producer cannot make an unsafe trace pass by merely writing zeros in
    ``safety_counters``; the evaluator recomputes this function independently.
    """
    effects = run.get("effect_attempt_counts", {})
    receipts = run.get("receipt_counts", {})
    outbox = run.get("outbox", {})
    resumes_ = run.get("resumes", [])
    stale = run.get("stale_completion_attempts", [])
    return {
        "duplicate_effect_count": sum(max(0, int(v) - 1)
                                      for v in effects.values()),
        "duplicate_receipt_count": sum(max(0, int(v) - 1)
                                       for v in receipts.values()),
        "blind_retry_count": len(run.get("blind_retry_records", [])),
        "stale_owner_completion_count": sum(
            1 for item in stale if not item.get("rejected")),
        "checkpoint_hash_bypass_count": sum(
            1 for item in resumes_
            if item.get("accepted") and item.get("reason") != "verified"),
        "lost_committed_event_count": sum(
            1 for item in outbox.values()
            if item.get("committed") and not item.get("delivered")),
        "allow_after_revocation_count": len(
            run.get("allow_after_revocation_records", [])),
    }


# --------------------------------------------------------------------------
# probe construction: deliberately unsafe configurations executed through
# the SAME simulation code paths (review requirement: real code paths)

PROBES = (
    {"probe": "A_unsafe_resume", "backend": "durable_engine",
     "load": "nominal", "seed": 303, "scenario": "S3",
     "mutations": ("unsafe_resume",),
     "expect": "FAIL", "reason": "duplicate external effect on resume"},
    {"probe": "B_incomparable", "backend": "durable_engine",
     "load": "nominal", "seed": 303, "scenario": None,
     "mutations": (), "expect": "INCOMPARABLE",
     "reason": "workload hash diverges from the frozen manifest"},
    {"probe": "C_blind_retry", "backend": "in_process",
     "load": "nominal", "seed": 303, "scenario": "S2",
     "mutations": ("blind_retry",),
     "expect": "FAIL", "reason": "retry without reconciliation evidence"},
)


def build_probes() -> list:
    out = []
    for probe in PROBES:
        run = simulate(probe["backend"], probe["load"], probe["seed"],
                       probe["scenario"], probe["mutations"])
        run["probe"] = probe["probe"]
        run["expect"] = probe["expect"]
        run["probe_reason"] = probe["reason"]
        if probe["probe"] == "B_incomparable":
            # the incomparable candidate is scored against a DIFFERENT
            # workload hash: the evaluator must refuse to compare
            run["workload_sha256"] = _sha(b"divergent-workload")
        out.append(run)
    return out


# --------------------------------------------------------------------------
# run matrix

def run_matrix(mode: str) -> list:
    runs = []
    for backend in BACKENDS:
        for load in LOADS:
            for seed in SEEDS:
                runs.append(dict(backend=backend, load=load, seed=seed,
                                 scenario=None))
    for backend in BACKENDS:
        for scenario in SCENARIOS:
            for load in LOADS:
                for seed in SEEDS:
                    runs.append(dict(backend=backend, load=load, seed=seed,
                                     scenario=scenario))
    return runs


def execute_matrix(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "agentos.s1-006.run-manifest/v1",
        "mode": out_dir.name,
        "contract_sha256": _sha((TICKET / "backend-contract.json")
                                .read_bytes()),
        "workload_sha256": _sha((TICKET / "workload-manifest.json")
                                .read_bytes()),
        "rubric_sha256": _sha((TICKET / "rubric.json").read_bytes()),
        "provenance": provenance(),
        "runs": [],
    }
    for spec in run_matrix("main"):
        run = simulate(spec["backend"], spec["load"], spec["seed"],
                       spec["scenario"])
        name = f"{run['run_id']}.json"
        (out_dir / name).write_text(
            json.dumps(run, indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
        manifest["runs"].append({
            "run_id": run["run_id"], "file": name,
            "sha256": _sha((out_dir / name).read_bytes()),
            "safety_counters": run["safety_counters"],
            "terminal_reason": run["terminal_reason"],
        })
    (out_dir / "run-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    comparison = build_comparison(out_dir)
    (out_dir / "comparison.json").write_text(
        json.dumps(comparison, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def build_comparison(run_a: Path) -> dict:
    """Aggregate the frozen matrix into the backend comparison."""
    manifest = json.loads((run_a / "run-manifest.json").read_text(
        encoding="utf-8"))
    by_id = {r["run_id"]: r for r in manifest["runs"]}
    comparison = {
        "schema": "agentos.s1-006.backend-comparison/v1",
        "contract_sha256": manifest["contract_sha256"],
        "workload_sha256": manifest["workload_sha256"],
        "rubric_sha256": manifest["rubric_sha256"],
        "runs": [],
    }
    for spec in run_matrix("main"):
        run_id = (f"{spec['backend']}-{spec['load']}-{spec['seed']}"
                  + (f"-{spec['scenario']}" if spec["scenario"] else ""))
        entry = by_id[run_id]
        data = json.loads((run_a / entry["file"]).read_text(encoding="utf-8"))
        comparison["runs"].append({
            "run_id": run_id,
            "backend": data["backend"], "load": data["load"],
            "seed": data["seed"], "scenario": data["scenario"],
            "commit": data["commit"], "tree_sha": data["tree_sha"],
            "metrics": data["metrics"],
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


def build_crash_replay(run_a: Path) -> dict:
    manifest = json.loads((run_a / "run-manifest.json").read_text(
        encoding="utf-8"))
    by_id = {r["run_id"]: r for r in manifest["runs"]}
    scenarios = []
    for backend in BACKENDS:
        for scenario in SCENARIOS:
            for load in LOADS:
                for seed in SEEDS:
                    run_id = f"{backend}-{load}-{seed}-{scenario}"
                    entry = by_id[run_id]
                    data = json.loads(
                        (run_a / entry["file"]).read_text(encoding="utf-8"))
                    scenarios.append({
                        "run_id": run_id, "backend": backend,
                        "scenario": scenario, "load": load, "seed": seed,
                        "recovery_times": data["metrics"]["recovery_times"],
                        "resumes": data["resumes"],
                        "redeliveries": data["redeliveries"],
                        "reconciled_unknown_outcomes":
                            data["reconciled_unknown_outcomes"],
                        "safety_counters": data["safety_counters"],
                        "terminal_reason": data["terminal_reason"],
                    })
    return {"schema": "agentos.s1-006.crash-replay/v1", "scenarios": scenarios}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("main", "rerun", "probes"),
                    default="main")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    out = Path(args.out)
    if args.mode == "probes":
        probes = build_probes()
        out.mkdir(parents=True, exist_ok=True)
        (out / "probes.json").write_text(
            json.dumps({"schema": "agentos.s1-006.probes/v1",
                        "probes": probes}, indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"probes written: {out / 'probes.json'}")
        return 0
    manifest = execute_matrix(out)
    if args.mode == "main":
        (out.parent / "backend-comparison.json").write_text(
            (out / "comparison.json").read_text(encoding="utf-8"),
            encoding="utf-8")
        (out.parent / "crash-replay-results.json").write_text(
            json.dumps(build_crash_replay(out), indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
    print(json.dumps({"mode": args.mode, "out": str(out),
                      "runs": len(manifest["runs"]),
                      "provenance": manifest["provenance"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
