"""The 17 mandatory qualification scenarios (scenario-manifest.json v1.0.0).

Each scenario runs against the REAL AgentOS engine/gateway/journal. Long-run
scenarios accept duration overrides so the registered full-scale requirement
(6 h sustained / 24 h soak) stays distinct from pilot-scale executions; the
comparator treats anything below required scale as PASS_WITH_LIMITS evidence,
never PASS.
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from agentos.gateway import CapabilityDenied, StaleOwnerError

from . import harness as H
from .harness import READ_CAPABILITY, WRITE_CAPABILITY
from .openloop import OpenLoopRunner, build_schedule
from .provider import ProviderClient, ProviderServer
from .revocation import grant, revoke_durable
from .stats import MetricRecord, proportion_record

SRC_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ScenarioConfig:
    work_root: Path            # scratch dir for this RUN (per run_id)
    seeds: list[int]
    overrides: dict[str, float] = field(default_factory=dict)
    repo_src: Path = SRC_ROOT  # for subprocess PYTHONPATH

    def override(self, scenario_id: str, key: str, default: float) -> float:
        return float(self.overrides.get(f"{scenario_id}.{key}", default))

    def scenario_dir(self, scenario_id: str, seed: int) -> Path:
        path = self.work_root / scenario_id / f"seed-{seed}"
        path.mkdir(parents=True, exist_ok=True)
        return path


def _spawn(module: str, args: list[str], cfg: ScenarioConfig,
           stderr_path: Path | None = None) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(cfg.repo_src)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    err = (open(stderr_path, "ab") if stderr_path is not None
           else subprocess.DEVNULL)
    try:
        return subprocess.Popen(
            [sys.executable, "-m", f"agentos.sloqual.{module}", *args],
            env=env, stdout=subprocess.DEVNULL, stderr=err)
    finally:
        if stderr_path is not None:
            err.close()


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _authorize_dispatch(handle, ctx, resolved, index: int):
    """One gateway authorize invocation -> (outcome, detail). Serialized by
    the runtime invoke lock (single-process SQLite model)."""
    try:
        with handle.invoke_lock:
            result = handle.gateway.invoke(
                ctx, resolved,
                {"resource": "workspace/demo", "action": "read"})
        status = str(result.get("status", "ERROR"))
        return ("SUCCEEDED" if result.get("ok") else status), {
            "activity_id": result.get("activity_id")}
    except CapabilityDenied:
        return "DENIED", {}
    except StaleOwnerError:
        return "STALE_OWNER_DENIED", {}
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            return "SQLITE_BUSY", {"error": str(exc)[:120]}
        return "ERROR", {"error": str(exc)[:120]}
    except Exception as exc:  # noqa: BLE001 - scenario boundary
        return "ERROR", {"error": str(exc)[:120]}


UNEXPECTED_FAILURE_OUTCOMES = {"FAILED", "SQLITE_BUSY", "STALE_OWNER_DENIED", "ERROR"}


def summarize_open_loop(result, *, seed: int, tag: str,
                        denied_pool_indexes: set[int] | None = None,
                        window_slice: tuple[int, int] | None = None,
                        min_observations: int = 1000) -> dict:
    rows = result.raw_rows()
    if window_slice:
        rows = rows[window_slice[0]:window_slice[1]]
    completed = [r for r in rows if r["completion_offset_ms"] is not None]
    succeeded = [r for r in rows if r["outcome"] == "SUCCEEDED"]
    denied = [r for r in rows if r["outcome"] == "DENIED"]
    pool = denied_pool_indexes or set()
    unexpected_denied = [r for r in denied if r["index"] not in pool]
    failed = [r for r in rows if r["outcome"] in UNEXPECTED_FAILURE_OUTCOMES]
    e2e_values = [r["end_to_end_ms"] for r in completed]
    queue_values = [r["queue_wait_ms"] for r in rows]
    service_values = [r["service_ms"] for r in completed]
    window_start_ns = result.schedule_origin_ns
    scheduled_first = rows[0]["scheduled_offset_ms"] if rows else 0.0
    last_completion_ms = max((r["completion_offset_ms"] for r in completed),
                             default=0.0)
    observed_wall_s = max(1e-9, (last_completion_ms - scheduled_first) / 1000.0)
    dispatched = len(rows)
    metrics = {
        "latency_end_to_end_ms": MetricRecord(
            f"{tag}.end_to_end_ms", "ms", e2e_values,
            seed_parts=(seed, tag)).to_dict(),
        "service_time_ms": MetricRecord(
            f"{tag}.service_ms", "ms", service_values,
            seed_parts=(seed, tag)).to_dict(),
        "queue_wait_ms": MetricRecord(
            f"{tag}.queue_wait_ms", "ms", queue_values,
            seed_parts=(seed, tag)).to_dict(),
        "throughput_achieved_events_per_second": {
            "name": f"{tag}.throughput_eps", "unit": "events/s",
            "kind": "value", "count": 1,
            "value": round(len(completed) / observed_wall_s, 6)},
        "throughput_realization_fraction": proportion_record(
            f"{tag}.throughput_realization", len(completed),
            max(1, dispatched)),
        "error_rate_fraction": proportion_record(
            f"{tag}.error_rate", len(failed) + len(unexpected_denied),
            # contract v1.0.2: expected denials are excluded from BOTH sides
            max(1, dispatched - (len(denied) - len(unexpected_denied)))),
        "availability_fraction": proportion_record(
            f"{tag}.availability", len(succeeded),
            max(1, dispatched - (len(denied) - len(unexpected_denied)))),
        "counts": {
            "dispatched": dispatched,
            "completed": len(completed),
            "succeeded": len(succeeded),
            "expected_denied": len(denied) - len(unexpected_denied),
            "unexpected_denied": len(unexpected_denied),
            "failed": len(failed),
            "not_started_dropped": sum(
                1 for r in rows if r["outcome"] == "NOT_STARTED"),
            "observed_window_seconds": round(observed_wall_s, 6),
            "drain_seconds": result.drain_s,
        },
    }
    metrics["_power_insufficient"] = len(e2e_values) < min_observations
    return metrics


def _db_latency_metrics(handle, tag: str, seed: int) -> dict:
    prof = handle.profiling
    return {
        "db_transaction_latency_ms": MetricRecord(
            f"{tag}.db_tx_ms", "ms", prof.db_write_samples_ms,
            seed_parts=(seed, tag)).to_dict(),
        "audit_journal_latency_ms": MetricRecord(
            f"{tag}.audit_ms", "ms", prof.audit_samples_ms,
            seed_parts=(seed, tag)).to_dict(),
    }


def _split_allow_deny(count: int, seed: int, fraction_denied: float = 0.10):
    rng = random.Random(seed * 7919 + 13)
    return {i for i in range(count) if rng.random() < fraction_denied}


# ---------------------------------------------------------------- scenarios

def scenario_cold_start(cfg: ScenarioConfig, seed: int) -> dict:
    work = cfg.scenario_dir("cold_start", seed)
    started = time.perf_counter_ns()
    handle = H.build_runtime(work)
    ctx = H.ledger_subject_context(handle, subject=f"cold-{seed}")
    grant(handle.db.conn, subject=f"cold-{seed}", capability=READ_CAPABILITY)
    resolved = handle.gateway.resolve("qual.authorize", "1.0.0")
    first = _authorize_dispatch(handle, ctx, resolved, 0)
    first_success_ms = (time.perf_counter_ns() - started) / 1e6
    schedule = build_schedule(count=300, rate_events_per_second=20,
                              seed=seed, fixed_rate=True)
    result = OpenLoopRunner(max_inflight=64).run(
        schedule, dispatch_fn=lambda i: _authorize_dispatch(
            handle, ctx, resolved, i))
    invariants = H.sweep_invariants(handle.db.conn, paths=[handle.root])
    handle.close()
    return {
        "seed": seed,
        "metrics": {
            "startup_to_first_success_ms": {"value": round(first_success_ms, 6),
                                            "unit": "ms", "count": 1, "kind": "value"},
            "first_request_outcome": first[0],
            **summarize_open_loop(result, seed=seed, tag="cold_start",
                                  min_observations=100),
        },
        "invariants": invariants,
    }


def _steady_like_run(cfg: ScenarioConfig, scenario_id: str, seed: int, *,
                     rate: float, duration_s: float, warmup_events: int,
                     provider: bool = False) -> tuple[dict, list[dict]]:
    server = None
    client = None
    if provider:
        server = ProviderServer(seed=seed).start()
        client = ProviderClient(server.port)
    handle = H.build_runtime(cfg.scenario_dir(scenario_id, seed),
                             provider_client=client)
    subject = f"{scenario_id}-{seed}"
    ctx = H.ledger_subject_context(handle, subject=subject)
    grant(handle.db.conn, subject=subject, capability=READ_CAPABILITY)
    if client is not None:
        grant(handle.db.conn, subject=subject, capability=READ_CAPABILITY)
    resolved_a = handle.gateway.resolve("qual.authorize", "1.0.0")
    resolved_p = (handle.gateway.resolve("qual.provider_call", "1.0.0")
                  if client else None)
    for i in range(warmup_events):        # discarded warm-up (contract §warmup)
        _authorize_dispatch(handle, ctx, resolved_a, i)
    count = max(1, int(rate * duration_s))
    schedule = build_schedule(count=count, rate_events_per_second=rate, seed=seed)
    denied_pool = _split_allow_deny(count, seed)
    denied_ctx = H.ledger_subject_context(handle, subject=f"{subject}-denied")

    def dispatch(i: int):
        use_ctx = denied_ctx if i in denied_pool else ctx
        if resolved_p is not None and i % 2 == 1:
            return _authorize_dispatch(handle, use_ctx, resolved_p, i)
        return _authorize_dispatch(handle, use_ctx, resolved_a, i)

    result = OpenLoopRunner(max_inflight=512).run(
        schedule, dispatch_fn=dispatch)
    metrics = summarize_open_loop(
        result, seed=seed, tag=scenario_id,
        denied_pool_indexes=denied_pool)
    metrics.update(_db_latency_metrics(handle, scenario_id, seed))
    invariants = H.sweep_invariants(handle.db.conn, paths=[handle.root])
    raw_rows = result.raw_rows()
    if client is not None:
        client.close()
    handle.close()
    if server is not None:
        server.stop()
    return ({**{"seed": seed}, "metrics": metrics, "invariants": invariants},
            raw_rows)


def scenario_warm_steady_state(cfg: ScenarioConfig, seed: int) -> dict:
    summary, _rows = _steady_like_run(
        cfg, "warm_steady_state", seed,
        rate=34.0,
        duration_s=cfg.override("warm_steady_state", "duration_s", 30.0),
        warmup_events=100)
    return summary


def scenario_sustained_load(cfg: ScenarioConfig, seed: int) -> dict:
    required_s = 21600.0
    duration_s = cfg.override("sustained_load", "duration_s",
                              cfg.override("sustained_load", "pilot_duration_s", 900.0))
    summary, _rows = _steady_like_run(
        cfg, "sustained_load", seed, rate=34.0, duration_s=duration_s,
        warmup_events=int(60 * 34))     # 60 s warm-up window excluded
    summary["completed_at_required_scale"] = duration_s >= required_s
    summary["required_scale_note"] = (
        f"ran {duration_s:.0f}s of required {required_s:.0f}s continuous load")
    return summary


def scenario_soak(cfg: ScenarioConfig, seed: int) -> dict:
    required_s = 86400.0
    duration_s = cfg.override("soak", "duration_s",
                              cfg.override("soak", "pilot_duration_s", 1200.0))
    interval_s = cfg.override("soak", "sample_interval_s", 60.0)
    samples: list[dict] = []
    stop = threading.Event()

    def sampler():
        while not stop.wait(interval_s):
            samples.append({
                "wall_ns": time.time_ns(),
                "rss_bytes": _process_rss_bytes(),
                "db_bytes": _dir_size_bytes(cfg.scenario_dir("soak", seed)),
            })

    thread = threading.Thread(target=sampler, daemon=True)
    thread.start()
    summary, _rows = _steady_like_run(
        cfg, "soak", seed, rate=10.0, duration_s=duration_s, warmup_events=100)
    stop.set()
    thread.join(timeout=5)
    summary["resource_samples"] = samples
    summary["completed_at_required_scale"] = duration_s >= required_s
    summary["required_scale_note"] = (
        f"ran {duration_s:.0f}s of required {required_s:.0f}s soak")
    return summary


def _process_rss_bytes() -> int:
    try:
        if sys.platform == "win32":
            import ctypes

            class _PMC(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                            *(("PeakWorkingSetSize" if False else f"_f{i}", ctypes.c_size_t)
                              for i in range(0))]  # placeholder never used

            # WorkingSet via GetProcessMemoryInfo
            class _IO(ctypes.Structure):
                _fields_ = [(n, ctypes.c_ulonglong) for n in (
                    "a", "b", "c", "d", "e", "f", "g", "h")]

            class _MEMPS(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_ulong),
                            ("PageFaultCount", ctypes.c_ulong),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]

            memps = _MEMPS()
            memps.cb = ctypes.sizeof(_MEMPS)
            ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(),
                ctypes.byref(memps), memps.cb)
            return int(memps.WorkingSetSize)
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except Exception:  # noqa: BLE001
        pass
    return 0


def _dir_size_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def scenario_burst(cfg: ScenarioConfig, seed: int) -> dict:
    base = 34.0
    burst_rate = base * cfg.override("burst", "burst_multiplier", 10)
    burst_s = cfg.override("burst", "burst_duration_s", 30.0)
    phase_s = cfg.override("burst", "phase_duration_s", 30.0)
    handle = H.build_runtime(cfg.scenario_dir("burst", seed))
    subject = f"burst-{seed}"
    ctx = H.ledger_subject_context(handle, subject=subject)
    grant(handle.db.conn, subject=subject, capability=READ_CAPABILITY)
    resolved = handle.gateway.resolve("qual.authorize", "1.0.0")
    for i in range(100):
        _authorize_dispatch(handle, ctx, resolved, i)
    phase_metrics: dict = {}
    all_rows: list[dict] = []
    for phase_index, (phase_name, rate, dur) in enumerate((
            ("nominal_pre", base, phase_s),
            ("burst", burst_rate, burst_s),
            ("cooldown", base, phase_s))):
        count = max(1, int(rate * dur))
        schedule = build_schedule(count=count, rate_events_per_second=rate,
                                  seed=seed + phase_index * 101)
        denied_pool = _split_allow_deny(count, seed)
        result = OpenLoopRunner(max_inflight=2048).run(
            schedule, dispatch_fn=lambda i: _authorize_dispatch(
                handle, ctx, resolved, i))
        summary = summarize_open_loop(result, seed=seed,
                                      tag=f"burst.{phase_name}",
                                      denied_pool_indexes=denied_pool)
        phase_metrics[phase_name] = summary
        all_rows.extend(result.raw_rows())
    invariants = H.sweep_invariants(handle.db.conn, paths=[handle.root])
    handle.close()
    return {"seed": seed, "metrics": {"phases": phase_metrics},
            "invariants": invariants}


def scenario_queue_backpressure(cfg: ScenarioConfig, seed: int) -> dict:
    duration_s = cfg.override("queue_backpressure", "duration_s", 30.0)
    rate = cfg.override("queue_backpressure", "saturating_rate_events_per_second", 400)
    handle = H.build_runtime(cfg.scenario_dir("queue_backpressure", seed))
    subject = f"backpressure-{seed}"
    ctx = H.ledger_subject_context(handle, subject=subject)
    grant(handle.db.conn, subject=subject, capability=READ_CAPABILITY)
    resolved = handle.gateway.resolve("qual.authorize", "1.0.0")
    count = int(rate * duration_s)
    schedule = build_schedule(count=count, rate_events_per_second=rate, seed=seed)
    inflight = {"now": 0, "max": 0}
    lock = threading.Lock()

    def dispatch(i: int):
        with lock:
            inflight["now"] += 1
            inflight["max"] = max(inflight["max"], inflight["now"])
        try:
            return _authorize_dispatch(handle, ctx, resolved, i)
        finally:
            with lock:
                inflight["now"] -= 1

    result = OpenLoopRunner(max_inflight=256, not_started_grace_s=0.05).run(
        schedule, dispatch_fn=dispatch)
    summary = summarize_open_loop(result, seed=seed, tag="queue_backpressure")
    summary["queue_depth_max_observed"] = {
        "value": inflight["max"], "unit": "requests", "count": 1, "kind": "value"}
    invariants = H.sweep_invariants(handle.db.conn, paths=[handle.root])
    handle.close()
    return {"seed": seed, "metrics": summary, "invariants": invariants}


def _provider_scenario_run(cfg: ScenarioConfig, scenario_id: str, seed: int, *,
                           duration_s: float, rate: float, fault_plan: list[dict]):
    """fault_plan: [{at_s, knobs{...}} ...] applied by timer threads."""
    server = ProviderServer(seed=seed).start()
    client = ProviderClient(server.port)
    handle = H.build_runtime(cfg.scenario_dir(scenario_id, seed),
                             provider_client=client)
    subject = f"{scenario_id}-{seed}"
    ctx = H.ledger_subject_context(handle, subject=subject)
    grant(handle.db.conn, subject=subject, capability=READ_CAPABILITY)
    resolved = handle.gateway.resolve("qual.provider_call", "1.0.0")
    timers = []
    origin_holder = {"ns": None}
    recovery_marks: list[dict] = []

    def apply(knobs: dict, label: str, kind: str):
        server.set_fault(**knobs)
        if kind == "restore":
            recovery_marks.append({"label": label, "restored_ns":
                                   time.perf_counter_ns()})

    for entry in fault_plan:
        timer = threading.Timer(
            entry["at_s"], apply,
            args=(entry["knobs"], entry.get("label", ""), entry.get("kind", "fault")))
        timer.daemon = True
        timer.start()
        timers.append(timer)

    count = int(rate * duration_s)
    schedule = build_schedule(count=count, rate_events_per_second=rate, seed=seed)

    def dispatch(i: int):
        if origin_holder["ns"] is None:
            origin_holder["ns"] = time.perf_counter_ns()
        try:
            with handle.invoke_lock:
                result = handle.gateway.invoke(
                    ctx, resolved, {"request_id": f"{scenario_id}-{seed}-{i}"})
            return (str(result.get("status")), {})
        except CapabilityDenied:
            return "DENIED", {}
        except Exception as exc:  # noqa: BLE001
            return "ERROR", {"error": str(exc)[:120]}

    result = OpenLoopRunner(max_inflight=512).run(schedule, dispatch_fn=dispatch)
    for timer in timers:
        timer.cancel()
    rows = result.raw_rows()
    origin = origin_holder["ns"] or result.schedule_origin_ns
    failed_outcomes = {"FAILED", "ERROR"}
    provider_failed = [r for r in rows if r["outcome"] in failed_outcomes]
    recovery_metrics = []
    for mark in recovery_marks:
        first_ok = next((r for r in rows
                         if r["outcome"] == "SUCCEEDED"
                         and r["completion_offset_ms"] is not None
                         and origin + int(r["completion_offset_ms"] * 1e6) > mark["restored_ns"]),
                        None)
        if first_ok is not None:
            first_ok_abs = origin + int(first_ok["completion_offset_ms"] * 1e6)
            recovery_metrics.append({
                "label": mark["label"],
                "recovery_time_seconds": round((first_ok_abs - mark["restored_ns"]) / 1e9, 6)})
    invariants = H.sweep_invariants(handle.db.conn, paths=[handle.root])
    client.close()
    handle.close()
    server.stop()
    metrics = {
        "external_provider_failure_rate_fraction": proportion_record(
            f"{scenario_id}.provider_failure", len(provider_failed), max(1, len(rows))),
        "recovery": recovery_metrics,
        "counts": {"dispatched": len(rows), "failed": len(provider_failed),
                   "succeeded": sum(1 for r in rows if r["outcome"] == "SUCCEEDED")},
    }
    return {"seed": seed, "metrics": metrics, "invariants": invariants}


def scenario_provider_full_outage(cfg: ScenarioConfig, seed: int) -> dict:
    duration_s = cfg.override("provider_full_outage", "duration_s", 60.0)
    window = cfg.override("provider_full_outage", "outage_start_s", 15.0)
    window_end = cfg.override("provider_full_outage", "outage_end_s", 35.0)
    return _provider_scenario_run(
        cfg, "provider_full_outage", seed, duration_s=duration_s, rate=20.0,
        fault_plan=[
            {"at_s": window, "knobs": {"mode": "full_outage"}, "label": "full_outage"},
            {"at_s": window_end, "knobs": {"mode": "ok"}, "label": "restored",
             "kind": "restore"},
        ])


def scenario_provider_degraded(cfg: ScenarioConfig, seed: int) -> dict:
    duration_s = cfg.override("provider_degraded", "duration_s", 45.0)
    return _provider_scenario_run(
        cfg, "provider_degraded", seed, duration_s=duration_s, rate=20.0,
        fault_plan=[
            {"at_s": 0, "knobs": {"mode": "mixed", "mix_probabilities": {
                "timeout": 0.2, "empty_response": 0.2, "rate_limited": 0.2},
                "timeout_ms": 800}},
        ])


def _extra_task_run(handle, key: str):
    handle.engine.plan_tasks(handle.goal_id, [{
        "key": key, "title": key, "definition_of_done": "worker seat"}])
    handle.engine.schedule_ready_tasks(handle.goal_id)
    row = handle.db.conn.execute(
        "SELECT id FROM task WHERE goal_id=? AND title=? AND status='READY'",
        (handle.goal_id, key)).fetchone()
    task_id = row[0]
    run_id, ctx = handle.engine.open_run(task_id, lease_minutes=60)
    return task_id, run_id, ctx


def scenario_worker_restart(cfg: ScenarioConfig, seed: int) -> dict:
    sdir = cfg.scenario_dir("worker_restart", seed)
    handle = H.build_runtime(sdir)
    task_b, run_b, ctx_b = _extra_task_run(handle, f"worker-seat-{seed}")
    grant(handle.db.conn, subject="worker-restart-seat",
          capability=READ_CAPABILITY)
    pre_log = sdir / "worker-pre.jsonl"
    post_log = sdir / "worker-post.jsonl"
    common = ["--db", str(handle.db_path), "--run-id", run_b,
              "--goal-id", handle.goal_id, "--task-id", task_b,
              "--lease-owner", ctx_b.lease_owner,
              "--workspace", str(sdir), "--subject", "worker-restart-seat"]
    proc = _spawn("worker_loop", [*common, "--duration-s", "3600",
                                  "--poll-ms", "20", "--out", str(pre_log)],
                  cfg, stderr_path=sdir / "worker-pre.stderr.log")
    time.sleep(20)
    kill_wall = time.time_ns()
    kill_perf = time.perf_counter_ns()
    proc.terminate()
    proc.wait(timeout=15)
    proc2 = _spawn("worker_loop", [*common, "--duration-s", "25",
                                   "--poll-ms", "20", "--out", str(post_log)],
                   cfg, stderr_path=sdir / "worker-post.stderr.log")
    proc2.wait(timeout=60)
    pre_rows = [r for r in _read_jsonl(pre_log) if r["outcome"] == "SUCCEEDED"]
    post_rows = [r for r in _read_jsonl(post_log) if r["outcome"] == "SUCCEEDED"]
    if not pre_rows or not post_rows:
        # fail-closed: an unmeasured restart is a scenario FAILURE, never a
        # silent empty record (SLOQUAL-001 review finding).
        handle.close()
        raise RuntimeError(
            f"worker_restart produced no successful operations "
            f"(pre={len(pre_rows)}, post={len(post_rows)}); "
            "worker subprocess did not execute the workload")
    recovery_s = (post_rows[0]["t_ns"] - kill_perf) / 1e9
    # stale-lease subcheck: an expired lease must deny mutating ops
    stale_violation = 0
    handle.engine.plan_tasks(handle.goal_id, [{
        "key": f"stale-short-{seed}", "title": f"stale-short-{seed}",
        "definition_of_done": "short lease probe"}])
    handle.engine.schedule_ready_tasks(handle.goal_id)
    row = handle.db.conn.execute(
        "SELECT id FROM task WHERE goal_id=? AND title=?",
        (handle.goal_id, f"stale-short-{seed}")).fetchone()
    _, short_ctx = handle.engine.open_run(row[0], lease_minutes=0.01)
    grant(handle.db.conn, subject="stale-probe", capability=WRITE_CAPABILITY)
    time.sleep(1.5)   # 0.01-minute lease has certainly expired
    resolved_w = handle.gateway.resolve("qual.worklog_append", "1.0.0")
    short_probe = H.ledger_subject_context(
        handle, subject="stale-probe", run_id=short_ctx.run_id,
        lease_owner=short_ctx.lease_owner)
    try:
        handle.gateway.invoke(short_probe, resolved_w,
                              {"line_id": f"stale-{seed}"})
        stale_violation += 1  # executed under expired lease!
    except StaleOwnerError:
        pass
    invariants = H.sweep_invariants(handle.db.conn, paths=[handle.root])
    invariants["stale_lease_executions_count"] = max(
        int(invariants.get("stale_lease_executions_count", 0)),
        stale_violation)
    handle.close()
    rec_raw = ([recovery_s] if recovery_s is not None else []) + [
        (r["t_ns"] - kill_perf) / 1e9 for r in post_rows[:20]]
    rec_record = MetricRecord(
        "recovery_time_seconds", "s", rec_raw,
        seed_parts=(seed, "worker_restart")).to_dict(include_raw=True)
    return {"seed": seed,
            "metrics": {"recovery_time_seconds": rec_record,
                "pre_successes": len(pre_rows), "post_successes": len(post_rows),
                "kill_wall_ns": kill_wall},
            "invariants": invariants}


def scenario_scheduler_restart(cfg: ScenarioConfig, seed: int) -> dict:
    sdir = cfg.scenario_dir("scheduler_restart", seed)
    handle = H.build_runtime(sdir)
    sched_log = sdir / "scheduler.jsonl"
    common = ["--db", str(handle.db_path), "--root", str(sdir),
              "--goal-id", handle.goal_id, "--duration-s", "3600",
              "--interval-ms", "150", "--out", str(sched_log)]
    proc = _spawn("scheduler_loop", common, cfg)
    time.sleep(12)
    killed_at = time.perf_counter_ns()
    proc.terminate()
    proc.wait(timeout=15)
    time.sleep(1.0)
    restarted_at = time.perf_counter_ns()
    respawn_args = ["--db", common[1], "--root", common[3],
                    "--goal-id", handle.goal_id, "--duration-s", "25",
                    "--interval-ms", "150", "--out", common[-1]]
    proc2 = _spawn("scheduler_loop", respawn_args, cfg)
    proc2.wait(timeout=60)
    events = _read_jsonl(sched_log)
    ok_events = [e for e in events if e["outcome"] == "OK"]
    first_after = next((e for e in ok_events if e["t_ns"] > killed_at), None)
    recovery_s = ((first_after["t_ns"] - restarted_at) / 1e9
                  if first_after else None)
    invariants = H.sweep_invariants(handle.db.conn, paths=[handle.root])
    handle.close()
    rec_raw = ([recovery_s] if recovery_s is not None else [])
    return {"seed": seed, "metrics": {
        "recovery_time_seconds": MetricRecord(
            "recovery_time_seconds", "s", rec_raw,
            seed_parts=(seed, "scheduler_restart")).to_dict(include_raw=True),
        "scheduler_ticks_total": len(events),
        "ticks_before_kill": sum(1 for e in ok_events if e["t_ns"] <= killed_at)},
        "invariants": invariants}


def scenario_full_restart(cfg: ScenarioConfig, seed: int) -> dict:
    sdir = cfg.scenario_dir("full_restart", seed)
    handle = H.build_runtime(sdir)
    subject = f"full-restart-{seed}"
    ctx = H.ledger_subject_context(handle, subject=subject)
    grant(handle.db.conn, subject=subject, capability=READ_CAPABILITY)
    resolved = handle.gateway.resolve("qual.authorize", "1.0.0")
    for i in range(50):
        _authorize_dispatch(handle, ctx, resolved, i)
    seq_before = handle.db.conn.execute(
        "SELECT seq FROM audit_event ORDER BY seq DESC LIMIT 1").fetchone()[0]
    anchor_before = handle.db.conn.execute(
        "SELECT head_digest FROM audit_anchor WHERE id=1").fetchone()[0]
    handle.close()
    reopened_at = time.perf_counter_ns()
    handle2 = H.build_runtime(sdir)
    ctx2 = H.ledger_subject_context(handle2, subject=subject)
    grant(handle2.db.conn, subject=subject, capability=READ_CAPABILITY)
    resolved2 = handle2.gateway.resolve("qual.authorize", "1.0.0")
    first = _authorize_dispatch(handle2, ctx2, resolved2, 999)
    recovery_s = (time.perf_counter_ns() - reopened_at) / 1e9
    seq_after = handle2.db.conn.execute(
        "SELECT seq FROM audit_event ORDER BY seq DESC LIMIT 1").fetchone()[0]
    anchor_after = handle2.db.conn.execute(
        "SELECT head_digest FROM audit_anchor WHERE id=1").fetchone()[0]
    # Data-loss detection: audit sequence must never regress, the reopened
    # chain must verify end-to-end, and the first request must succeed.
    # (Anchor equality across the restart boundary is NOT required: any
    # event appended between the two reads legitimately advances it.)
    ok_chain, _bad = H.journal_chain_ok(handle2.db.conn)
    data_loss = 0 if (seq_after >= seq_before and ok_chain
                      and first[0] == "SUCCEEDED") else 1
    invariants = H.sweep_invariants(handle2.db.conn, paths=[handle2.root])
    invariants["confirmed_data_loss_count"] = data_loss
    handle2.close()
    return {"seed": seed, "metrics": {
        "recovery_time_seconds": MetricRecord(
            "recovery_time_seconds", "s", [recovery_s],
            seed_parts=(seed, "full_restart")).to_dict(include_raw=True),
        "first_request_after_restart": first[0],
        "audit_seq_before": seq_before, "audit_seq_after": seq_after},
        "invariants": invariants}


def scenario_sqlite_lock_contention(cfg: ScenarioConfig, seed: int) -> dict:
    sdir = cfg.scenario_dir("sqlite_lock_contention", seed)
    handle = H.build_runtime(sdir)
    subject = f"contention-{seed}"
    ctx = H.ledger_subject_context(handle, subject=subject)
    grant(handle.db.conn, subject=subject, capability=READ_CAPABILITY)
    resolved = handle.gateway.resolve("qual.authorize", "1.0.0")
    contenders = [_spawn("contention_loop", [
        "--db", str(handle.db_path), "--hold-ms", "40", "--sleep-ms", "20",
        "--duration-s", "45"], cfg) for _ in range(2)]
    time.sleep(1.0)
    count = int(20 * 30)
    schedule = build_schedule(count=count, rate_events_per_second=20, seed=seed)
    result = OpenLoopRunner(max_inflight=256).run(
        schedule, dispatch_fn=lambda i: _authorize_dispatch(
            handle, ctx, resolved, i))
    for proc in contenders:
        proc.wait(timeout=60)
    summary = summarize_open_loop(result, seed=seed, tag="lock_contention")
    busy = summary["counts"].get("failed", 0)
    summary["sqlite_busy_count"] = {
        "value": busy, "unit": "requests", "count": 1, "kind": "value"}
    summary.update(_db_latency_metrics(handle, "lock_contention", seed))
    invariants = H.sweep_invariants(handle.db.conn, paths=[handle.root])
    handle.close()
    return {"seed": seed, "metrics": summary, "invariants": invariants}


def scenario_disk_slow_saturation(cfg: ScenarioConfig, seed: int) -> dict:
    sdir = cfg.scenario_dir("disk_slow_saturation", seed)
    handle = H.build_runtime(sdir)
    subject = f"disk-{seed}"
    ctx = H.ledger_subject_context(handle, subject=subject)
    grant(handle.db.conn, subject=subject, capability=READ_CAPABILITY)
    resolved = handle.gateway.resolve("qual.authorize", "1.0.0")
    stop = threading.Event()
    chunk = os.urandom(8 * 1024 * 1024)

    def pressure(writer_id: int):
        index = 0
        while not stop.is_set():
            path = sdir / f"pressure-{writer_id}-{index % 8}.bin"
            with open(path, "wb") as fh:
                fh.write(chunk)
                fh.flush()
                os.fsync(fh.fileno())
            index += 1

    writers = [threading.Thread(target=pressure, args=(i,), daemon=True)
               for i in range(4)]
    for w in writers:
        w.start()
    time.sleep(0.5)
    count = int(20 * 30)
    schedule = build_schedule(count=count, rate_events_per_second=20, seed=seed)
    result = OpenLoopRunner(max_inflight=256).run(
        schedule, dispatch_fn=lambda i: _authorize_dispatch(
            handle, ctx, resolved, i))
    stop.set()
    for w in writers:
        w.join(timeout=10)
    metrics = summarize_open_loop(result, seed=seed, tag="disk_saturation")
    method_limitation = ("user-space IO pressure (parallel fsynced "
                         "writes); true block-device throttling unavailable")
    metrics.update(_db_latency_metrics(handle, "disk_saturation", seed))
    invariants = H.sweep_invariants(handle.db.conn, paths=[handle.root])
    handle.close()
    return {"seed": seed, "metrics": metrics,
            "method_limitation": method_limitation, "invariants": invariants}


def scenario_db_growth(cfg: ScenarioConfig, seed: int) -> dict:
    sdir = cfg.scenario_dir("db_growth", seed)
    handle = H.build_runtime(sdir)
    conn = handle.db.conn
    target_rows = int(cfg.override("db_growth", "target_rows", 2000000))
    budget_s = cfg.override("db_growth", "insert_budget_s", 180.0)
    batch = int(cfg.override("db_growth", "bulk_insert_batch", 5000))
    conn.execute("CREATE TABLE IF NOT EXISTS sloqual_bulk("
                 "id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
    payload = json.dumps({"note": "x" * 900})[:1024]
    inserted = 0
    deadline = time.time() + budget_s
    while inserted < target_rows and time.time() < deadline:
        n = min(batch, target_rows - inserted)
        conn.executemany(
            "INSERT INTO sloqual_bulk(payload) VALUES (?)",
            [(payload,) for _ in range(n)])
        inserted += n
    db_bytes = handle.db_path.stat().st_size
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    subject = f"growth-{seed}"
    ctx = H.ledger_subject_context(handle, subject=subject)
    grant(conn, subject=subject, capability=READ_CAPABILITY)
    resolved = handle.gateway.resolve("qual.authorize", "1.0.0")
    count = int(34 * 30)
    schedule = build_schedule(count=count, rate_events_per_second=34, seed=seed)
    result = OpenLoopRunner(max_inflight=512).run(
        schedule, dispatch_fn=lambda i: _authorize_dispatch(
            handle, ctx, resolved, i))
    metrics = summarize_open_loop(result, seed=seed, tag="db_growth")
    db_profile = {"rows_inserted": inserted,
                  "target_rows": target_rows,
                  "db_bytes": db_bytes, "page_count": page_count,
                  "reached_target": inserted >= target_rows}
    metrics.update(_db_latency_metrics(handle, "db_growth", seed))
    invariants = H.sweep_invariants(conn)
    handle.close()
    return {"seed": seed, "metrics": metrics,
            "db_profile": db_profile, "invariants": invariants}


def scenario_network_faults(cfg: ScenarioConfig, seed: int) -> dict:
    duration_s = cfg.override("network_faults", "duration_s", 110.0)
    scale = duration_s / 110.0
    base_plan = [
        {"at_s": 0, "knobs": {"mode": "ok"}},
        {"at_s": 5, "knobs": {"mode": "latency", "latency_ms": 250},
         "label": "latency_250ms"},
        {"at_s": 35, "knobs": {"mode": "ok"}, "label": "latency_restored",
         "kind": "restore"},
        {"at_s": 40, "knobs": {"loss_fraction": 0.3}, "label": "packet_loss_30"},
        {"at_s": 70, "knobs": {"loss_fraction": 0.0}, "label": "loss_restored",
         "kind": "restore"},
        {"at_s": 75, "knobs": {"mode": "disconnect"}, "label": "disconnect"},
        {"at_s": 95, "knobs": {"mode": "ok", "loss_fraction": 0.0},
         "label": "disconnect_restored", "kind": "restore"},
    ]
    plan = [dict(entry, at_s=round(entry["at_s"] * scale, 3))
            for entry in base_plan]
    return _provider_scenario_run(
        cfg, "network_faults", seed, duration_s=duration_s, rate=20.0,
        fault_plan=plan)


# --- S1-008 security gate ----------------------------------------------------

REVOCATION_LEVELS = {
    "idle": 0,
    "nominal@34eps": 1,
    "burst@340eps": 3,
}


def scenario_revocation_under_load(cfg: ScenarioConfig, seed: int) -> dict:
    """S1-008 security gate: >=100 trials across seeds x load levels.

    Per trial: durable GRANT -> all instances confirm allow -> durable REVOKE
    (single SQLite tx) -> every instance must observe DENY within 5 s; any
    successful operation after the durable commit is a capability violation.
    """
    sdir = cfg.scenario_dir("revocation_under_load", seed)
    trials_per_level = int(cfg.override(
        "revocation_under_load", "trials_per_seed_level", 7))
    handle = H.build_runtime(sdir)
    conn = handle.db.conn
    subject = f"revocable-principal-{seed}"
    instance_files: list[Path] = []
    instance_procs: list[subprocess.Popen | None] = []
    instance_args: list[list[str]] = []
    common = ["--db", str(handle.db_path), "--goal-id", handle.goal_id,
              "--workspace", str(sdir), "--duration-s", "3600",
              "--poll-ms", "25", "--subject", subject]
    for idx in range(3):
        task_id, run_id, rctx = _extra_task_run(handle, f"rev-seat-{seed}-{idx}")
        out = sdir / f"instance-{idx}.jsonl"
        instance_files.append(out)
        args = [*common, "--run-id", run_id, "--task-id", task_id,
                "--lease-owner", rctx.lease_owner, "--out", str(out)]
        instance_args.append(args)
        instance_procs.append(_spawn("worker_loop", args, cfg))

    def snapshot(path: Path) -> list[dict]:
        try:
            return _read_jsonl(path)
        except OSError:
            return []

    def spawn_background() -> subprocess.Popen:
        idx = random.Random(seed).randrange(4)
        task_id, run_id, bctx = _extra_task_run(handle, f"bg-load-{seed}-{idx}-{time.time_ns()}")
        grant(handle.db.conn, subject=run_id, capability=READ_CAPABILITY)
        return _spawn("worker_loop", [
            "--db", str(handle.db_path), "--run-id", run_id,
            "--goal-id", handle.goal_id, "--task-id", task_id,
            "--lease-owner", bctx.lease_owner, "--workspace", str(sdir),
            "--duration-s", "3600", "--poll-ms", "15",
            "--subject", run_id,
            "--out", str(sdir / f"bg-{idx}.jsonl")], cfg)

    trials: list[dict] = []
    resurrection_checks: list[dict] = []
    trial_no = 0
    for level_name, loader_count in REVOCATION_LEVELS.items():
        bg = [spawn_background() for _ in range(loader_count)]
        for t in range(trials_per_level):
            trial_no += 1
            gid = grant(conn, subject=subject, capability=READ_CAPABILITY,
                        actor="revocation-gate")
            deadline = time.perf_counter() + 5.0
            confirmed = False
            while time.perf_counter() < deadline:
                snaps = [snapshot(p)[-3:] for p in instance_files]
                if snaps and all(snap and any(r["outcome"] == "SUCCEEDED"
                                              for r in snap) for snap in snaps):
                    confirmed = True
                    break
                time.sleep(0.02)
            info = revoke_durable(conn, gid, actor="revocation-gate")
            commit_ns = info["commit_perf_ns"]
            deadline = time.perf_counter() + 6.0
            first_denies: list[float | None] = [None] * len(instance_files)
            violations_after_commit = 0
            while time.perf_counter() < deadline:
                for idx, path in enumerate(instance_files):
                    if first_denies[idx] is not None:
                        continue
                    for row in snapshot(path):
                        if row["t_ns"] <= commit_ns:
                            continue
                        if row["outcome"] == "DENIED":
                            first_denies[idx] = row["t_ns"]
                            break
                        if row["outcome"] == "SUCCEEDED":
                            violations_after_commit += 1
                if all(d is not None for d in first_denies):
                    break
                time.sleep(0.005)
            observed_max = max((d - commit_ns for d in first_denies
                                if d is not None), default=None)
            trials.append({
                "trial": trial_no, "level": level_name, "seed": seed,
                "commit_perf_ns": commit_ns,
                "grant_confirmed_before_revoke": confirmed,
                "first_deny_offsets_ms": [
                    round((d - commit_ns) / 1e6, 3) if d is not None else None
                    for d in first_denies],
                "enforcement_latency_ms": (
                    round(observed_max / 1e6, 3)
                    if observed_max is not None else None),
                "all_instances_denied": all(d is not None for d in first_denies),
                "allow_after_commit_violations": violations_after_commit,
            })
            if t == trials_per_level // 2:
                # restart an instance WHILE revoked; capability must NOT return
                idx = 1
                if instance_procs[idx] is not None:
                    instance_procs[idx].terminate()   # type: ignore[union-attr]
                    instance_procs[idx].wait(timeout=15)   # type: ignore[union-attr]
                task_id, run_id, rctx = _extra_task_run(
                    handle, f"rev-seat-{seed}-{idx}-b")
                args = [*common, "--run-id", run_id, "--task-id", task_id,
                        "--lease-owner", rctx.lease_owner,
                        "--out", str(instance_files[idx])]
                instance_args[idx] = args
                instance_procs[idx] = _spawn("worker_loop", args, cfg)
                time.sleep(1.0)
                recent = snapshot(instance_files[idx])[-5:]
                resurrection_checks.append({
                    "while_revoked": True, "instance": idx,
                    "observed_outcomes_after_restart": [
                        r["outcome"] for r in recent],
                    "still_denies_after_restart": bool(recent) and any(
                        r["outcome"] == "DENIED" for r in recent),
                })
        for proc in bg:
            proc.terminate()
            proc.wait(timeout=15)
    for idx, proc in enumerate(instance_procs):
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
    latencies = [t["enforcement_latency_ms"] for t in trials
                 if t["enforcement_latency_ms"] is not None]
    censored = sum(1 for t in trials if t["enforcement_latency_ms"] is None)
    violations = sum(t["allow_after_commit_violations"] for t in trials)
    unconfirmed = sum(1 for t in trials
                      if not t["grant_confirmed_before_revoke"])
    metrics = {
        "revocation_enforcement_latency_ms": MetricRecord(
            "revocation.enforcement_ms", "ms", latencies,
            seed_parts=(seed, "revocation")).to_dict(include_raw=True),
        "trials_total": len(trials),
        "censored_trials_over_6s": censored,
        "allow_after_commit_violations": violations,
        "grants_unconfirmed_before_revoke": unconfirmed,
        "resurrection_checks": resurrection_checks,
        "gate_all_trials_le_5000ms": bool(latencies)
        and max(latencies) <= 5000.0 and censored == 0 and violations == 0,
    }
    invariants = H.sweep_invariants(conn, paths=[handle.root])
    invariants["capability_scope_violations_count"] = max(
        int(invariants.get("capability_scope_violations_count", 0)),
        violations)
    handle.close()
    return {"seed": seed, "metrics": metrics, "invariants": invariants,
            "trials": trials}


def scenario_recovery_after_failures(cfg: ScenarioConfig, seed: int) -> dict:
    """Composite verification over every fault-scenario DB produced this run."""
    root = cfg.work_root
    checked: list[dict] = []
    totals = {key: 0 for key in (
        "audit_chain_violations_count", "lost_terminal_transitions_count",
        "false_acceptance_count", "capability_scope_violations_count",
        "stale_lease_executions_count", "side_effect_duplication_count",
        "confirmed_data_loss_count", "secrets_in_artifacts_count")}
    for db_path in sorted(root.glob("*/*/qual.db")):
        scenario = db_path.parent.parent.name
        if scenario == "recovery_after_failures":
            continue
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        t0 = time.perf_counter_ns()
        findings = H.sweep_invariants(conn, paths=[db_path.parent])
        if findings.get("audit_chain_violations_count", 0):
            # A concurrent writer can make a mid-append snapshot look broken;
            # re-verify after quiescence before accepting the finding.
            time.sleep(0.5)
            findings = H.sweep_invariants(conn, paths=[db_path.parent])
        verify_s = (time.perf_counter_ns() - t0) / 1e9
        conn.close()
        checked.append({"scenario": scenario, "db": str(db_path),
                        "findings": findings, "verify_seconds": verify_s})
        for key in totals:
            value = findings.get(key, 0)
            if isinstance(value, int) and value > 0:
                totals[key] += value
    verify_raw = [c.get("verify_seconds") for c in checked
                  if c.get("verify_seconds") is not None]
    return {"seed": seed, "metrics": {
        "databases_verified": len(checked),
        "db_verification_seconds": MetricRecord(
            "db_verification_seconds", "s", verify_raw,
            seed_parts=(seed, "recovery_after_failures")
        ).to_dict(include_raw=True),
        "violation_totals": totals},
        "databases_checked": checked,
        "invariants": {**totals,
                       "unresolved_unknown_outcomes_count": sum(
                           c["findings"].get("unresolved_unknown_outcomes_count", 0)
                           for c in checked)}}


SCENARIO_REGISTRY = {
    "cold_start": scenario_cold_start,
    "warm_steady_state": scenario_warm_steady_state,
    "sustained_load": scenario_sustained_load,
    "soak": scenario_soak,
    "burst": scenario_burst,
    "queue_backpressure": scenario_queue_backpressure,
    "provider_full_outage": scenario_provider_full_outage,
    "provider_degraded": scenario_provider_degraded,
    "worker_restart": scenario_worker_restart,
    "scheduler_restart": scenario_scheduler_restart,
    "full_restart": scenario_full_restart,
    "sqlite_lock_contention": scenario_sqlite_lock_contention,
    "disk_slow_saturation": scenario_disk_slow_saturation,
    "db_growth": scenario_db_growth,
    "network_faults": scenario_network_faults,
    "revocation_under_load": scenario_revocation_under_load,
    "recovery_after_failures": scenario_recovery_after_failures,
}
