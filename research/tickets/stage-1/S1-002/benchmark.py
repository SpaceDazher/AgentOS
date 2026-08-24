"""Reproducible local control-plane benchmark for Stage 1 ticket S1-002.

This measures the real AgentOS read-only ToolGateway path, including contract
resolution, schema validation, capability enforcement, activity persistence,
and the hash-chained audit event.  It is a single-process SQLite/WAL benchmark,
not a production SLO or a distributed-worker capacity test.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import random
import sqlite3
import statistics
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentos.db import open_db
from agentos.engine import Engine
from agentos.gateway import CapabilityDenied, ToolContract, ToolGateway
from agentos.journal import Journal


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "min": 0.0,
            "mean": 0.0,
            "stddev": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
        }
    return {
        "min": round(min(values), 6),
        "mean": round(statistics.fmean(values), 6),
        "stddev": round(statistics.pstdev(values), 6),
        "p50": round(percentile(values, 0.50), 6),
        "p95": round(percentile(values, 0.95), 6),
        "p99": round(percentile(values, 0.99), 6),
        "max": round(max(values), 6),
    }


def file_set_bytes(db_path: Path) -> dict[str, int]:
    paths = {
        "database": db_path,
        "wal": Path(str(db_path) + "-wal"),
        "shm": Path(str(db_path) + "-shm"),
    }
    sizes = {name: path.stat().st_size if path.exists() else 0 for name, path in paths.items()}
    sizes["total"] = sum(sizes.values())
    return sizes


def setup_runtime(root: Path) -> dict[str, Any]:
    started = time.perf_counter_ns()
    db_path = root / "benchmark.db"
    db = open_db(db_path)
    engine = Engine(db, root)
    journal = Journal(db)
    gateway = ToolGateway(db, journal)
    goal_id = engine.create_goal(
        "S1-002 deterministic gateway benchmark",
        constraints={"benchmark": "s1-002", "network": "disabled"},
    )
    engine.refine_spec(
        goal_id,
        "Measure the local read-only authorization and audit path.",
        criteria=[{"criterion_id": "benchmark_recorded", "kind": "tests_present"}],
    )
    engine.activate_goal(goal_id)
    engine.plan_tasks(
        goal_id,
        [
            {
                "key": "benchmark",
                "title": "Run deterministic authorization workload",
                "definition_of_done": "Raw timed observations are persisted.",
            }
        ],
    )
    engine.schedule_ready_tasks(goal_id)
    task_id = db.conn.execute(
        "SELECT id FROM task WHERE goal_id=? AND status='READY'", (goal_id,)
    ).fetchone()[0]
    _, base_ctx = engine.open_run(task_id, lease_minutes=30)

    def authorize(resource: str, action: str, request_id: str) -> dict[str, Any]:
        return {"allowed": True, "resource": resource, "action": action, "request_id": request_id}

    contract = ToolContract(
        name="benchmark.authorize",
        version="1.0.0",
        input_schema={
            "type": "object",
            "properties": {
                "resource": {"type": "string"},
                "action": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": ["resource", "action", "request_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        required_capability="resource.read",
        effect_class="read",
        idempotency="none",
        handler=authorize,
    )
    gateway.register(contract)
    allowed_ctx = replace(base_ctx, capabilities={"resource.read"})
    denied_ctx = replace(base_ctx, capabilities=set())
    setup_ms = (time.perf_counter_ns() - started) / 1_000_000
    return {
        "db": db,
        "db_path": db_path,
        "gateway": gateway,
        "contract": contract,
        "allowed_ctx": allowed_ctx,
        "denied_ctx": denied_ctx,
        "setup_ms": setup_ms,
    }


def invoke_one(runtime: dict[str, Any], *, allowed: bool, request_id: str) -> str:
    ctx = runtime["allowed_ctx"] if allowed else runtime["denied_ctx"]
    try:
        result = runtime["gateway"].invoke(
            ctx,
            runtime["contract"],
            {"resource": "workspace/demo", "action": "read", "request_id": request_id},
        )
        return result["status"].lower()
    except CapabilityDenied:
        return "denied"


def close_runtime(runtime: dict[str, Any]) -> None:
    db = runtime["db"]
    try:
        db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        db.conn.close()


def run_trial(
    *, rate: int, duration: float, mode: str, trial: int, seed: int, warmup: int
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        runtime = setup_runtime(Path(tmp))
        rng = random.Random(seed + rate * 10_000 + trial * 100 + (1 if mode == "warm" else 0))
        warmup_started = time.perf_counter_ns()
        if mode == "warm":
            for index in range(warmup):
                invoke_one(
                    runtime,
                    allowed=rng.random() >= 0.10,
                    request_id=f"warmup-{rate}-{trial}-{index}",
                )
        warmup_ms = (time.perf_counter_ns() - warmup_started) / 1_000_000

        event_count = max(1, round(rate * duration))
        interval_ns = 1_000_000_000 / rate
        started_at = utc_now()
        schedule_start = time.perf_counter_ns()
        cpu_start = time.process_time_ns()
        raw_events: list[dict[str, Any]] = []
        service_total_ns = 0
        completed_last_ns = schedule_start
        for index in range(event_count):
            target_ns = schedule_start + round((index + 1) * interval_ns)
            remaining_ns = target_ns - time.perf_counter_ns()
            if remaining_ns > 0:
                time.sleep(remaining_ns / 1_000_000_000)
            service_start_ns = time.perf_counter_ns()
            due_index = math.floor(max(0, service_start_ns - schedule_start) / interval_ns)
            queue_depth = max(0, due_index - (index + 1))
            allowed = rng.random() >= 0.10
            decision = invoke_one(
                runtime,
                allowed=allowed,
                request_id=f"measure-{mode}-{rate}-{trial}-{index}",
            )
            completed_ns = time.perf_counter_ns()
            completed_last_ns = completed_ns
            service_ns = completed_ns - service_start_ns
            service_total_ns += service_ns
            raw_events.append(
                {
                    "index": index,
                    "arrival_offset_ms": round((target_ns - schedule_start) / 1_000_000, 6),
                    "allowed_path": allowed,
                    "decision": decision,
                    "service_ms": round(service_ns / 1_000_000, 6),
                    "queue_wait_ms": round(max(0, service_start_ns - target_ns) / 1_000_000, 6),
                    "end_to_end_ms": round(max(0, completed_ns - target_ns) / 1_000_000, 6),
                    "queue_depth_at_start": queue_depth,
                }
            )
        cpu_ns = time.process_time_ns() - cpu_start
        ended_at = utc_now()
        observed_wall_ns = max(1, completed_last_ns - schedule_start)
        service_ms = [event["service_ms"] for event in raw_events]
        e2e_ms = [event["end_to_end_ms"] for event in raw_events]
        queue_wait_ms = [event["queue_wait_ms"] for event in raw_events]
        result = {
            "rate_target_events_per_second": rate,
            "duration_target_seconds": duration,
            "mode": mode,
            "trial": trial,
            "seed": seed,
            "started_at": started_at,
            "ended_at": ended_at,
            "setup_ms": round(runtime["setup_ms"], 6),
            "warmup_events": warmup if mode == "warm" else 0,
            "warmup_ms": round(warmup_ms, 6),
            "events_completed": event_count,
            "allowed_events": sum(1 for event in raw_events if event["decision"] == "succeeded"),
            "denied_events": sum(1 for event in raw_events if event["decision"] == "denied"),
            "observed_wall_seconds": round(observed_wall_ns / 1_000_000_000, 6),
            "achieved_events_per_second": round(event_count * 1_000_000_000 / observed_wall_ns, 6),
            "single_worker_busy_ratio": round(service_total_ns / observed_wall_ns, 6),
            "process_cpu_ratio": round(cpu_ns / observed_wall_ns, 6),
            "queue_depth_max": max(event["queue_depth_at_start"] for event in raw_events),
            "service_latency_ms": summarize(service_ms),
            "queue_wait_ms": summarize(queue_wait_ms),
            "end_to_end_latency_ms": summarize(e2e_ms),
            "raw_events": raw_events,
        }
        close_runtime(runtime)
        return result


def aggregate_trials(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for trial in trials:
        groups.setdefault((trial["mode"], trial["rate_target_events_per_second"]), []).append(trial)
    output = []
    for (mode, rate), members in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1])):
        raw_events = [event for member in members for event in member["raw_events"]]
        service = [event["service_ms"] for event in raw_events]
        e2e = [event["end_to_end_ms"] for event in raw_events]
        waits = [event["queue_wait_ms"] for event in raw_events]
        output.append(
            {
                "mode": mode,
                "rate_target_events_per_second": rate,
                "trial_count": len(members),
                "events_completed": len(raw_events),
                "achieved_events_per_second": summarize(
                    [member["achieved_events_per_second"] for member in members]
                ),
                "single_worker_busy_ratio": summarize(
                    [member["single_worker_busy_ratio"] for member in members]
                ),
                "process_cpu_ratio": summarize([member["process_cpu_ratio"] for member in members]),
                "queue_depth_max": max(member["queue_depth_max"] for member in members),
                "service_latency_ms": summarize(service),
                "queue_wait_ms": summarize(waits),
                "end_to_end_latency_ms": summarize(e2e),
                "local_20ms_target_observed": percentile(e2e, 0.95) <= 20.0,
            }
        )
    return output


def run_storage_probe(*, events: int, seed: int, warmup: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        runtime = setup_runtime(Path(tmp))
        rng = random.Random(seed + 9_000_000)
        for index in range(warmup):
            invoke_one(runtime, allowed=True, request_id=f"storage-warmup-{index}")
        runtime["db"].conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before_sizes = file_set_bytes(runtime["db_path"])
        before_activity = runtime["db"].conn.execute("SELECT count(*) FROM activity").fetchone()[0]
        before_audit = runtime["db"].conn.execute("SELECT count(*) FROM audit_event").fetchone()[0]
        started_at = utc_now()
        started_ns = time.perf_counter_ns()
        for index in range(events):
            invoke_one(
                runtime,
                allowed=rng.random() >= 0.10,
                request_id=f"storage-{index}",
            )
        elapsed_ns = time.perf_counter_ns() - started_ns
        ended_at = utc_now()
        runtime["db"].conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        after_sizes = file_set_bytes(runtime["db_path"])
        after_activity = runtime["db"].conn.execute("SELECT count(*) FROM activity").fetchone()[0]
        after_audit = runtime["db"].conn.execute("SELECT count(*) FROM audit_event").fetchone()[0]
        added_activity = after_activity - before_activity
        added_audit = after_audit - before_audit
        added_rows = added_activity + added_audit
        delta_bytes = after_sizes["total"] - before_sizes["total"]
        bytes_per_gateway_event = delta_bytes / events
        bytes_per_persisted_row = delta_bytes / added_rows
        output = {
            "started_at": started_at,
            "ended_at": ended_at,
            "warmup_events": warmup,
            "measured_gateway_events": events,
            "elapsed_seconds": round(elapsed_ns / 1_000_000_000, 6),
            "activity_rows_added": added_activity,
            "audit_rows_added": added_audit,
            "persisted_rows_added": added_rows,
            "before_bytes": before_sizes,
            "after_bytes": after_sizes,
            "delta_bytes": delta_bytes,
            "bytes_per_gateway_event": round(bytes_per_gateway_event, 6),
            "bytes_per_persisted_row": round(bytes_per_persisted_row, 6),
            "projection_36_5m_rows_bytes": round(bytes_per_persisted_row * 36_500_000),
            "projection_36_5m_rows_gib": round(
                bytes_per_persisted_row * 36_500_000 / (1024 ** 3), 6
            ),
            "raw_1kib_per_row_projection_gib": round(36_500_000 * 1024 / (1024 ** 3), 6),
            "scope_limit": "Local SQLite/WAL row growth for this payload and schema; excludes indexes added later, backups, replicas, object artifacts, and filesystem allocation effects.",
        }
        close_runtime(runtime)
        return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--rates", nargs="+", type=int, default=[10, 34, 100])
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--storage-events", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260824)
    args = parser.parse_args()
    if sorted(set(args.rates)) != sorted(args.rates) or any(rate <= 0 for rate in args.rates):
        raise SystemExit("rates must be unique positive integers")
    if not {34, 100}.issubset(set(args.rates)) or len(args.rates) < 3:
        raise SystemExit("S1-002 requires at least three rates including 34 and 100")
    if args.duration <= 0 or args.trials < 1 or args.warmup < 0 or args.storage_events < 1:
        raise SystemExit("duration/trials/storage-events must be positive; warmup cannot be negative")

    run_started_at = utc_now()
    trials: list[dict[str, Any]] = []
    for mode in ("cold", "warm"):
        for rate in args.rates:
            for trial in range(1, args.trials + 1):
                trials.append(
                    run_trial(
                        rate=rate,
                        duration=args.duration,
                        mode=mode,
                        trial=trial,
                        seed=args.seed,
                        warmup=args.warmup,
                    )
                )
    aggregates = aggregate_trials(trials)
    storage = run_storage_probe(events=args.storage_events, seed=args.seed, warmup=args.warmup)
    result = {
        "schema": "agentos.s1-002-benchmark/v1",
        "run_started_at": run_started_at,
        "run_ended_at": utc_now(),
        "configuration": {
            "rates_events_per_second": args.rates,
            "duration_seconds_per_trial": args.duration,
            "trials_per_rate_and_mode": args.trials,
            "modes": ["cold", "warm"],
            "warmup_events": args.warmup,
            "allowed_denied_mix": "seeded 90% allow / 10% deny",
            "storage_probe_events": args.storage_events,
            "seed": args.seed,
            "worker_count": 1,
            "arrival_model": "deterministic fixed-rate schedule",
            "network": "disabled",
        },
        "environment": {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "sqlite": sqlite3.sqlite_version,
            "platform": platform.platform(),
            "processor": platform.processor(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "perf_counter": vars(time.get_clock_info("perf_counter")),
            "sqlite_journal_mode": "WAL",
            "agentos_commit": os.environ.get("AGENTOS_COMMIT", "not-supplied"),
        },
        "workload_scope": "Real local ToolGateway read path: registry resolve, JSON-schema subset validation, capability decision, handler, activity row, and hash-chained audit event.",
        "non_scope": [
            "external network or model latency",
            "multiple processes or hosts",
            "distributed worker pool and M/M/c validation",
            "production traffic, durability, failover, or SLO commitment",
        ],
        "trials": trials,
        "aggregates": aggregates,
        "storage_probe": storage,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "run_started_at": result["run_started_at"],
                "run_ended_at": result["run_ended_at"],
                "aggregate_scenarios": len(aggregates),
                "measured_events": sum(item["events_completed"] for item in trials),
                "storage_probe_events": args.storage_events,
                "aggregates": aggregates,
                "storage_probe": storage,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
