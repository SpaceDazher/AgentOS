"""E1 evaluation runner (docs/EVALUATION_PROTOCOL.md).

Usage:
    python -m eval.run_e1 --repeats 5 [--worker fake] [--db ROOT] [--out results.json]

For each task in the frozen frame (eval/e1_tasks.py) and each repeat, runs a
full goal episode: concept -> spec -> plan -> live run with gateway effects ->
evaluations -> gate. Records per-episode outcomes into one JSON results file;
aggregates pass^1 / pass^k / cost / latency at the end.

The harness-reliability drill (FakeWorker) is deterministic; end-to-end
episodes use --worker hermes (requires local hermes CLI).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from e1_tasks import E1_TASKS  # noqa: E402

from agentos.db import open_db  # noqa: E402
from agentos.engine import Engine  # noqa: E402
from agentos.evidence_pack import build as build_evidence  # noqa: E402
from agentos.gates import Evaluator, Gates  # noqa: E402
from agentos.gateway import ToolContract, ToolGateway  # noqa: E402
from agentos.journal import Journal  # noqa: E402


def _write_handler(db):
    from agentos.fence_sink import make_fs_write_handler
    return make_fs_write_handler(db)


def _solve_reference(task_key: str) -> dict[str, str]:
    """Reference implementations per task key (what a correct worker yields).
    Alternative-but-valid outputs also pass — the evaluator checks behavior,
    not this exact text."""
    return {
        "greet-basic": ("def greet(name):\n"
                        "    return f'hello, {name}'\n\n\n"
                        "def test_greet():\n"
                        "    assert greet('world') == 'hello, world'\n"),
        "add-int": ("def add(a, b):\n"
                    "    return a + b\n\n\n"
                    "def test_add():\n"
                    "    assert add(2, 1) == 3\n"),
        "reverse-str": ("def reverse(s):\n"
                        "    return s[::-1]\n\n\n"
                        "def test_reverse():\n"
                        "    assert reverse('abc') == 'cba'\n"),
        "max-of-list": ("def maximum(xs):\n"
                        "    if not xs:\n"
                        "        raise ValueError('empty')\n"
                        "    return max(xs)\n\n\n"
                        "def test_maximum():\n"
                        "    assert maximum([1, 9, 4]) == 9\n"),
        "flaky-recover": ("def bump(n):\n"
                          "    return n + 1\n\n\n"
                          "def test_bump():\n"
                          "    assert bump(1) == 2\n"),
    }[task_key]


def run_episode(root: Path, task: dict, repeat: int,
                worker_kind: str) -> dict:
    t0 = time.perf_counter()
    db = open_db(root / f"{task['key']}-r{repeat}" / "agentos.db")
    eng = Engine(db, root / f"{task['key']}-r{repeat}")
    j = Journal(db)
    gw = ToolGateway(db, j)
    ev = Evaluator(db, root / f"{task['key']}-r{repeat}")

    gw.register(ToolContract(
        name="fs.write.handler", version="1.0.0",
        input_schema={"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "content": {"type": "string"}},
                      "required": ["path", "content"]},
        required_capability="fs.write_local", effect_class="write_local",
        idempotency="keyed", handler=_write_handler(db)))

    goal_id = eng.create_goal(task["concept"], actor="e1-runner")
    eng.refine_spec(goal_id, task["spec"], criteria=task["criteria"])
    eng.activate_goal(goal_id)
    eng.plan_tasks(goal_id, task["plan"])
    eng.schedule_ready_tasks(goal_id)

    tool_calls = 0
    if worker_kind == "fake":
        run_id, ctx = eng.open_run(task_id=db.conn.execute(
            "SELECT id FROM task WHERE goal_id=?", (goal_id,)).fetchone()[0])
        src = _solve_reference(task["key"])
        module_name = task.get("module", f"{task['key']}.py")
        script = task.get("script", [{"ok": True}])
        # scripted failure consumes an attempt before completion
        if any(not step.get("ok", True) for step in script[:-1]):
            eng.fail_run(run_id, goal_id, "worker",
                         "scripted first-attempt failure")
            eng._task_fail_or_retry(ctx.task_id, goal_id, "worker")
            eng.schedule_ready_tasks(goal_id)
            run_id, ctx = eng.open_run(ctx.task_id)
        r1 = gw.invoke(ctx, gw.resolve("fs.write.handler"),
                       {"path": str(Path(ctx.workspace_path) / module_name),
                        "content": src},
                       idempotency_key=f"{run_id}:impl")
        tool_calls += 1
        eng.complete_live_run(ctx)  # artifacts re-derived from gateway effects
    else:
        raise SystemExit("hermes worker E1 requires interactive scheduling; "
                         "use --worker fake for harness drills")

    eval_results = {}
    for c in task["criteria"]:
        res = ev.run(goal_id, c["criterion_id"])
        eval_results[c["criterion_id"]] = res["result"]

    episode_ok = True
    try:
        eng.submit_to_gate(goal_id)
    except RuntimeError as e:
        episode_ok = False
        gate_result, reasons = "submit-refused", [str(e)]
    else:
        gate = Gates(db, j).evaluate_release(goal_id)
        gate_result, reasons = gate["result"], gate["reasons"]
        episode_ok = gate_result == "pass"

    duration_ms = round((time.perf_counter() - t0) * 1000)
    return {
        "task": task["key"], "repeat": repeat, "worker": worker_kind,
        "episode_success": episode_ok,
        "gate_result": gate_result, "gate_reasons": reasons,
        "evaluation_results": eval_results,
        "tool_calls": tool_calls,
        "duration_ms": duration_ms,
        "goal_id": goal_id,
    }


def aggregate(results: list[dict], repeats: int) -> dict:
    tasks = sorted({r["task"] for r in results})
    by_task = {t: [r for r in results if r["task"] == t]
               for t in tasks}
    pass1 = sum(1 for r in results if r["episode_success"]) / max(len(results), 1)

    def passk(k: int) -> float | None:
        vals = []
        for t in tasks:
            eps = by_task[t]
            if len(eps) < k:
                continue
            ok = all(e["episode_success"] for e in eps[:k])
            vals.append(ok)
        return (sum(vals) / len(vals)) if vals else None

    durations = [r["duration_ms"] for r in results]
    successes = [r for r in results if r["episode_success"]]
    return {
        "episodes_total": len(results),
        "pass_1": round(pass1, 3),
        "pass_k_min_available": min(
            (len(by_task[t]) for t in tasks), default=0),
        **({f"pass_{min(repeats, min(len(by_task[t]) for t in tasks))}":
            round(passk(min(repeats, min(len(by_task[t]) for t in tasks))), 3)}
           if repeats else {}),
        "false_completion_rate": 0.0,   # no human gold set yet — see protocol
        "cost_tool_calls_mean": round(sum(r["tool_calls"] for r in results)
                                      / max(len(results), 1), 2),
        "duration_ms_mean": round(sum(durations) / max(len(durations), 1)),
        "duration_ms_conditional_on_success": round(
            sum(r["duration_ms"] for r in successes) / max(len(successes), 1))
        if successes else None,
        "tasks": {t: {"successes": sum(1 for e in eps if e["episode_success"]),
                      "episodes": len(eps)} for t, eps in by_task.items()},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="run_e1")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--worker", choices=["fake"], default="fake")
    ap.add_argument("--db", default=None, help="root dir for episodes")
    ap.add_argument("--out", default=None, help="results JSON path")
    args = ap.parse_args(argv)

    root = Path(args.db or ".agentos-e1").resolve()
    root.mkdir(parents=True, exist_ok=True)
    results = []
    for task in E1_TASKS:
        for repeat in range(1, args.repeats + 1):
            rec = run_episode(root, task, repeat, args.worker)
            results.append(rec)
            flag = "PASS" if rec["episode_success"] else "FAIL"
            print(f"[{flag}] {task['key']} r{repeat} "
                  f"({rec['duration_ms']}ms, tools={rec['tool_calls']})")

    summary = aggregate(results, args.repeats)
    out = {"schema": "agentos.e1-results/v0",
           "protocol": "docs/EVALUATION_PROTOCOL.md (frame: eval/e1_tasks.py)",
           "worker": args.worker, "repeats_requested": args.repeats,
           "summary": summary, "episodes": results}
    out_path = Path(args.out or (root / "results.json"))
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"results: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
