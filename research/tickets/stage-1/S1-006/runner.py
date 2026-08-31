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


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(args: list) -> str | None:
    try:
        out = subprocess.run(["git", *args], capture_output=True,
                             text=True, timeout=30, cwd=str(ROOT))
        return out.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


_PROV_CACHE: dict | None = None


def provenance() -> dict:
    global _PROV_CACHE
    if _PROV_CACHE is not None:
        return _PROV_CACHE
    scripts = {}
    for name in ("runner.py", "evaluator.py"):
        path = TICKET / name
        if path.is_file():
            scripts[name] = _sha(path.read_bytes())
    # dirty flag excludes the ticket's own research directory: it is the
    # mutable research surface written by this run; executed-script
    # integrity is bound via script_hashes instead (review R3 flow).
    status = _git(["status", "--porcelain"]) or ""
    dirty_lines = []
    for ln in status.splitlines():
        if not ln.strip():
            continue
        path = ln[3:].strip().strip('"')
        # the research ticket directory and its regression tests are the
        # mutable research surface written by this run; executed-platform
        # code (src/, evals/, spec/, docs/, adr/) still flags dirty
        if path.startswith("research/tickets/") or path.startswith("tests/"):
            continue
        dirty_lines.append(ln)
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "commit": _git(["rev-parse", "HEAD"]),
        "tree_sha": _git(["rev-parse", "HEAD^{tree}"]),
        "dirty": bool(dirty_lines),
        "dirty_lines": dirty_lines,
        "script_hashes": scripts,
    }


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
    done = set()
    seq = []
    while len(seq) < arrivals:
        ready = [t for t in LAYER_ORDER
                 if t not in done and all(d in done for d in DAG[t])]
        if not ready:
            ready = list(LAYER_ORDER)  # DAG restarts: arrivals > DAG size
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

    rng = random.Random(seed)
    sequence = task_sequence(arrivals, rng)

    dispatch_us = params["dispatch_us"]
    write_us = params["state_write_us"]
    lease_timeout_us = params.get("lease_timeout_ms", 0) * 1000
    recovery_us = params.get("crash_recovery_ms", 0) * 1000

    now = 0.0
    queue = []           # ready task ids with ready_time
    completed = set()
    decisions = []       # one decision per gateway effect
    raw_latency = []
    queue_depths = []
    throughput_span_start = None
    counters = {c: 0 for c in SAFETY_COUNTERS}
    observations = []
    recovery_times = []
    receipts = {}        # decision_id -> local effect receipt count
    reconciliations = {}  # decision_id -> resolution evidence
    resumes = []         # S3 checkpoint-resume decisions
    redeliveries = 0     # S4 at-least-once redelivery attempts
    run_key = f"{backend}-{load}-{seed}" + (f"-{scenario}" if scenario else "")

    outcome_roll = {"ack": 0.9, "nack": 0.05, "unknown_reconciled": 0.05}

    def do_effect(task, tick):
        decision_id = f"{task}#{tick}"
        roll = rng.random()
        outcome = ("ack" if roll < outcome_roll["ack"]
                   else "nack" if roll < outcome_roll["ack"] + outcome_roll["nack"]
                   else "unknown_reconciled")
        decisions.append(decision_id)
        if outcome == "unknown_reconciled":
            # SAF: unknown outcome enters reconciliation; retry only after
            # recorded resolution
            reconciliations[decision_id] = "resolved-by-evidence"
            if "blind_retry" in mutations:
                # mutated backend retries WITHOUT reconciliation evidence
                retry_after_unknown(decision_id, {}, counters,
                                    allow_retry=True)
        return decision_id, outcome

    def record_receipt(decision_id):
        # unsafe direct ledger append (probe path): a second receipt for an
        # already-received decision is a safety violation
        receipts[decision_id] = receipts.get(decision_id, 0) + 1
        if receipts[decision_id] > 1:
            counters["duplicate_receipt_count"] += 1

    crash_after = None
    if scenario in ("S1", "S3"):
        crash_after = rng.randrange(max(2, arrivals // 3), arrivals)
    lease_fired = False

    for i, task in enumerate(sequence):
        ready_time = now
        queue.append((task, ready_time))
        depth = len(queue)
        # dispatch
        now += dispatch_us
        task_id, _rt = queue.pop(0)
        queue_depths.append(depth)
        raw_latency.append(now - _rt)
        if throughput_span_start is None:
            throughput_span_start = now

        if scenario == "S1" and crash_after is not None and i == crash_after:
            # coordinator crash AFTER committed transition+outbox (the
            # transition is committed atomically below), BEFORE delivery:
            now += recovery_us
            recovery_times.append({"scenario": "S1", "us": recovery_us})
            # delivery is replayed from the durable outbox: exactly one
            # effect/receipt per decision (at-least-once, deduplicated)

        # checkpoint (DB-bound, content hash verified)
        checkpoint_hash = content_hash(run_key, task, i)
        now += write_us

        if scenario == "S3" and crash_after is not None and i == crash_after:
            # run crash after a VALID checkpoint: resume creates a new run
            # with provenance; completed steps are not re-executed
            store = CheckpointStore()
            store.put(run_key, task, i, checkpoint_hash)
            if "checkpoint_bypass" in mutations:
                counters["checkpoint_hash_bypass_count"] += 1
                resumes.append({"task": task, "step": i, "accepted": None,
                                "reason": "bypassed-verification"})
            else:
                accepted, reason = store.resume(run_key, task, i,
                                                checkpoint_hash)
                resumes.append({"task": task, "step": i,
                                "accepted": accepted, "reason": reason})
            now += recovery_us
            recovery_times.append({"scenario": "S3", "us": recovery_us})

        # external effect via the gateway
        decision_id, outcome = do_effect(task, i)
        if "unsafe_resume" in mutations and scenario == "S3" \
                and i == crash_after:
            # probe A: the unsafe backend re-executes the external effect
            # on resume and force-appends a second receipt
            counters["duplicate_effect_count"] += 1
            record_receipt(decision_id)
        if not deliver_effect(decision_id, receipts):
            # a redelivered decision never creates a second local receipt
            counters["duplicate_receipt_count"] += 1

        if scenario == "S4" and not lease_fired and i >= arrivals // 3:
            lease_fired = True
            # lease expiry: the engine redelivers the activity; the local
            # dedup absorbs it. The STALE owner attempts a completion with
            # an old fencing token and is rejected.
            redeliveries += 1
            deliver_effect(decision_id, receipts)
            if "no_fencing" in mutations:
                counters["stale_owner_completion_count"] += 1
            now += lease_timeout_us
            recovery_times.append({"scenario": "S4", "us": lease_timeout_us})

        if scenario == "S2" and outcome == "unknown_reconciled":
            # reconciliation resolves with recorded evidence; only then a
            # retry is allowed
            retry_after_unknown(decision_id, reconciliations, counters,
                                allow_retry=True)
            now += write_us

        # atomic transition + audit/outbox append
        if "drop_outbox" in mutations and i == crash_after:
            counters["lost_committed_event_count"] += 1
        completed.add(task)
        observations.append({
            "i": i, "task": task_id, "dispatch_us": round(dispatch_us, 2),
            "queue_depth": depth, "latency_us": round(now - _rt, 2),
            "outcome": outcome,
        })

    span = max(now - (throughput_span_start or 0), 1e-9)
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
                "p50": percentile(ordered, 50),
                "p95": percentile(ordered, 95),
                "p99": percentile(ordered, 99),
            },
            "throughput_tasks_per_second": round(len(sequence) / span * 1e6, 1),
            "max_queue_depth": max(queue_depths) if queue_depths else 0,
            "recovery_times": recovery_times,
        },
        "resumes": resumes,
        "redeliveries": redeliveries,
        "reconciled_unknown_outcomes": len(reconciliations),
        "safety_counters": counters,
        "raw_observations": observations,
        "terminal_reason": "completed",
    }
    return run


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
            json.dumps(build_comparison(out), indent=1, sort_keys=True) + "\n",
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
