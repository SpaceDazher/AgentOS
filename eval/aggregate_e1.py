"""Aggregate E1 results into the protocol's estimands (pass^k with Wilson CIs).

Usage: python -m eval.aggregate_e1 <results.json> [k]
"""
from __future__ import annotations

import json
import math
import sys


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, center - half), 3), round(min(1.0, center + half), 3))


def aggregate(episodes: list[dict], repeats: int | None = None,
              k: int | None = None) -> dict:
    """Pure aggregation over episode records (unit-testable, R4)."""
    tasks = sorted({e["task"] for e in episodes})
    by_task = {t: [e for e in episodes if e["task"] == t] for t in tasks}

    # pass^1
    s1 = sum(1 for e in episodes if e["episode_success"])
    lo, hi = wilson_ci(s1, len(episodes))
    pass1 = {
        "successes": s1, "n": len(episodes),
        "rate": round(s1 / max(len(episodes), 1), 3),
        "wilson95": [lo, hi],
    }

    out: dict = {"schema": "agentos.e1-aggregate/v0", "pass_1": pass1}

    # pass^k per protocol (all first-k repeats must pass, per task).
    # R4: a task counts ONLY if every repeat passed (strict AND) — verified
    # by the regression test against a hand-computed example.
    max_avail = min(len(by_task[t]) for t in tasks)
    k_eff = k or max_avail
    task_all_pass = []
    passing_task_names = []
    for t in tasks:
        eps = sorted(by_task[t], key=lambda e: e["repeat"])[:k_eff]
        ok = bool(eps) and all(e["episode_success"] for e in eps)
        task_all_pass.append(ok)
        if ok:
            passing_task_names.append(t)
    sk = sum(task_all_pass)
    klo, khi = wilson_ci(sk, len(tasks))
    out[f"pass_{k_eff}"] = {
        "definition": f"all first-{k_eff} repeats pass, per task",
        "tasks_passing": sk, "n_tasks": len(tasks),
        "passing_tasks": passing_task_names,
        "rate": round(sk / max(len(tasks), 1), 3),
        "wilson95": [klo, khi],
        "note": ("task-clustered; CI over tasks is coarse at n=5 — "
                 "protocol calls for N=20 before external claims"),
    }

    # R4: worker failure attribution (provider vs evaluator-rejected omissions)
    fail_modes = {"provider_no_result": 0, "evaluator_reject": 0,
                  "other_worker": 0}
    for e in episodes:
        if e["episode_success"]:
            continue
        fc = e.get("worker_fail_class")
        note = e.get("worker_note") or ""
        if not e.get("worker_ok") and (
                fc in ("deadline", "worker_unavailable")
                or "no AGENTOS_RESULT" in note
                or "timeout" in note.lower()):
            fail_modes["provider_no_result"] += 1
        elif e.get("worker_ok"):
            fail_modes["evaluator_reject"] += 1
        else:
            fail_modes["other_worker"] += 1
    out["failure_attribution"] = fail_modes

    # cost / latency
    durs_ok = [e["duration_ms"] for e in episodes if e["episode_success"]]
    durs_all = [e["duration_ms"] for e in episodes]
    tools = [e.get("tool_calls", 1) for e in episodes]
    out["cost_latency"] = {
        "duration_ms_mean_all": round(sum(durs_all) / max(len(durs_all), 1)),
        "duration_ms_mean_conditional_success":
            round(sum(durs_ok) / max(len(durs_ok), 1)) if durs_ok else None,
        "tool_calls_mean": round(sum(tools) / max(len(tools), 1), 2),
    }

    # evaluator agreement summary
    fails = {}
    for e in episodes:
        for crit, res in e.get("evaluation_results", {}).items():
            if res != "pass":
                fails.setdefault(crit, 0)
                fails[crit] += 1
    out["evaluation_failures_by_criterion"] = fails

    # per-task breakdown
    out["per_task"] = {t: {
        "episodes": len(eps),
        "successes": sum(1 for e in eps if e["episode_success"]),
        "mean_duration_ms": round(sum(e["duration_ms"] for e in eps)
                                  / max(len(eps), 1)),
    } for t, eps in by_task.items()}

    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: aggregate_e1 <results.json> [k]")
        return 2
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    k = int(sys.argv[2]) if len(sys.argv) > 2 else None
    out = aggregate(data["episodes"], k=k)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
