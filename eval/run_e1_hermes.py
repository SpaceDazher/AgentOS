"""E1 end-to-end pilot: real episodes through HermesAgentWorker.

Pilot scope (deliberately small): 2 tasks x 2 repeats. Each episode spawns a
real `hermes chat -q` session that must DECLARE its work products via the
structured effects channel; the harness replays them through the gateway and
the evaluator checks observable behavior (real subprocess execution).

Run:  python -m eval.run_e1_hermes --db .agentos-e1-hermes
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

try:
    from e2_tasks import E2_TASKS  # noqa: E402  (N=20 expanded frame)
except ImportError:
    E2_TASKS = None

from agentos.db import open_db  # noqa: E402
from agentos.engine import Engine  # noqa: E402
from agentos.gates import Evaluator, Gates  # noqa: E402
from agentos.gateway import ToolContract, ToolGateway  # noqa: E402
from agentos.hermes_worker import HermesAgentWorker  # noqa: E402
from agentos.journal import Journal  # noqa: E402


def run_episode(root: Path, task: dict, repeat: int,
                timeout_s: int) -> dict:
    t0 = time.perf_counter()
    ep_root = root / f"{task['key']}-r{repeat}"
    db = open_db(ep_root / "agentos.db")
    eng = Engine(db, ep_root)
    j = Journal(db)
    gw = ToolGateway(db, j)
    ev = Evaluator(db, ep_root)

    gw.register(ToolContract(
        name="fs.write.handler", version="1.0.0",
        input_schema={"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "content": {"type": "string"}},
                      "required": ["path", "content"]},
        required_capability="fs.write_local", effect_class="write_local",
        idempotency="keyed",
        handler=_make_gateway_write(ep_root)))

    goal_id = eng.create_goal(task["concept"], actor="e1-hermes")
    eng.refine_spec(goal_id, task["spec"], criteria=task["criteria"])
    eng.activate_goal(goal_id)
    eng.plan_tasks(goal_id, task["plan"])
    eng.schedule_ready_tasks(goal_id)

    task_id = db.conn.execute(
        "SELECT id FROM task WHERE goal_id=?", (goal_id,)).fetchone()[0]
    run_id, ctx = eng.open_run(task_id)

    worker = HermesAgentWorker(timeout_s=timeout_s)
    step = 0
    worker_ok = False
    note = ""
    while step < 3:
        from agentos.workers import StepRequest
        req = StepRequest(task_id=task_id, run_id=run_id, goal_id=goal_id,
                          title=task["plan"][0]["title"],
                          definition_of_done=task["spec"],
                          inputs={},
                          workspace_path=ctx.workspace_path,
                          step=step, checkpoint=None,
                          context_packet_text="")
        res = worker.step(req)
        note = res.note
        if not res.ok:
            break
        worker_ok = True
        # replay declared effects through the gateway (trusted path)
        for rel, content in res.outputs.get("files", {}).items():
            gw.invoke(ctx, gw.resolve("fs.write.handler"),
                      {"path": str(Path(ctx.workspace_path) / rel),
                       "content": content},
                      idempotency_key=f"{run_id}:effect:{rel}")
            step += 1
        if res.outputs.get("files"):
            break
        step += 1

    eng.complete_live_run(ctx)   # artifacts re-derived from gateway effects

    eval_results = {}
    for c in task["criteria"]:
        try:
            r = ev.run(goal_id, c["criterion_id"])
            eval_results[c["criterion_id"]] = r["result"]
        except Exception as e:  # noqa: BLE001
            eval_results[c["criterion_id"]] = f"error:{e}"

    episode_ok = False
    gate_result, reasons = "n/a", []
    try:
        eng.submit_to_gate(goal_id)
        gate = Gates(db, j).evaluate_release(goal_id)
        gate_result, reasons = gate["result"], gate["reasons"]
        episode_ok = gate_result == "pass"
    except RuntimeError as e:
        gate_result, reasons = "submit-refused", [str(e)]

    # Recording contract (protocol §Recording contract): build the evidence
    # pack for every episode and record path + sha256. E2 post-run audit found
    # this was missing (0 packs across 100 episode dirs); patched.
    pack_path = None
    pack_sha256 = None
    try:
        from agentos.evidence_pack import build as _build_pack
        built = _build_pack(db, ep_root, goal_id)
        pack_path = built["path"]
        pack_sha256 = built["sha256"]
    except Exception as e:  # noqa: BLE001 — pack failure must not mask episode
        pack_path = f"<pack-build-failed: {e}>"

    return {
        "task": task["key"], "repeat": repeat, "worker": "hermes",
        "episode_success": episode_ok,
        "gate_result": gate_result, "gate_reasons": reasons,
        "evaluation_results": eval_results,
        "worker_ok": worker_ok, "worker_note": note[:200],
        "duration_ms": round((time.perf_counter() - t0) * 1000),
        "goal_id": goal_id,
        "evidence_pack_path": pack_path,
        "evidence_pack_sha256": pack_sha256,
        "env": {
            "python": sys.version.split()[0],
            "hermes_bin": worker.bin,
            "platform": sys.platform,
        },
    }


def _make_gateway_write(root: Path):
    """Gateway-side write handler with workspace confinement."""
    root_resolved = Path(root).resolve()

    def write(path: str, content: str) -> dict:
        p = Path(path).resolve()
        if not p.is_relative_to(root_resolved):
            raise ValueError(f"path escapes episode root: {path}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"written": str(p), "bytes": len(content)}

    return write


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="run_e1_hermes")
    ap.add_argument("--tasks", nargs="*", default=None,
                    help="task keys from the frame (default: all in frame)")
    ap.add_argument("--frame", choices=["e1", "e2"], default="e2",
                    help="task frame: e1 (5 tasks) or e2 (20 tasks)")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=300,
                    help="per-step hermes timeout, seconds")
    ap.add_argument("--db", default=".agentos-e1-hermes")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    root = Path(args.db).resolve()
    root.mkdir(parents=True, exist_ok=True)
    frame = E1_TASKS if args.frame == "e1" else (E2_TASKS or E1_TASKS)
    if args.tasks:
        wanted = set(args.tasks)
        tasks = [t for t in frame if t["key"] in wanted]
        missing = wanted - {t["key"] for t in tasks}
        if missing:
            raise SystemExit(f"unknown task keys: {sorted(missing)}")
    else:
        tasks = list(frame)
    results = []
    for task in tasks:
        for repeat in range(1, args.repeats + 1):
            print(f"=== {task['key']} r{repeat} — spawning hermes session…",
                  flush=True)
            rec = run_episode(root, task, repeat, args.timeout)
            results.append(rec)
            flag = "PASS" if rec["episode_success"] else "FAIL"
            print(f"[{flag}] {task['key']} r{repeat} "
                  f"gate={rec['gate_result']} ({rec['duration_ms']}ms) "
                  f"note={rec['worker_note'][:80]}", flush=True)

    successes = sum(1 for r in results if r["episode_success"])
    summary = {
        "episodes_total": len(results),
        "pass_1": round(successes / max(len(results), 1), 3),
        "by_task": {t["key"]: {
            "successes": sum(1 for r in results
                             if r["task"] == t["key"] and r["episode_success"]),
            "episodes": args.repeats} for t in tasks},
    }
    out_path = Path(args.out or (root / "results.json"))
    out_path.write_text(json.dumps(
        {"schema": "agentos.e1-results/v0", "mode": "end-to-end-hermes-pilot",
         "summary": summary, "episodes": results}, indent=2),
        encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"results: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
