"""Subprocess scheduler loop: performs REAL Engine transitions continuously
so scheduler restart scenarios can measure recovery against durable state."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--goal-id", required=True)
    parser.add_argument("--duration-s", type=float, default=60.0)
    parser.add_argument("--interval-ms", type=float, default=200.0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from agentos.db import open_db  # noqa: E402
    from agentos.engine import Engine  # noqa: E402

    db = open_db(args.db)
    engine = Engine(db, args.root)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    counter = 0
    deadline = time.perf_counter() + args.duration_s
    with open(out_path, "a", encoding="utf-8") as handle:
        while time.perf_counter() < deadline:
            started = time.perf_counter_ns()
            status = "OK"
            detail = {}
            try:
                engine.plan_tasks(args.goal_id, [{
                    "key": f"sched-{counter}",
                    "title": f"scheduler tick {counter}",
                    "definition_of_done": "tick recorded",
                }])
                ready = engine.schedule_ready_tasks(args.goal_id)
                detail["scheduled"] = len(ready)
                if ready:
                    task_id = ready[0]
                    run_id, ctx = engine.open_run(task_id, lease_minutes=5)
                    engine.complete_live_run(
                        ctx, outputs={"tick": counter})
                    detail["completed_task"] = task_id
            except Exception as exc:  # noqa: BLE001 - scenario boundary
                status = "ERROR"
                detail["error"] = str(exc)[:200]
            handle.write(json.dumps({
                "t_ns": started, "wall_ns": time.time_ns(),
                "outcome": status, "counter": counter,
                "detail": detail}) + "\n")
            handle.flush()
            counter += 1
            time.sleep(args.interval_ms / 1000.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
