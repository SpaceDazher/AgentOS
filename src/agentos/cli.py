"""CLI: single-command demo of the full vertical scenario + utility verbs.

    python -m agentos.cli demo [--worker fake|hermes] [--flaky] [--db PATH]
    python -m agentos.cli evidence --goal GOAL_ID

stdout carries exactly one JSON document; any warnings/diagnostics emitted by
library code during execution are re-routed to stderr. Exit codes: 0 success,
1 demo/error failure (reported as {"error": ...} JSON, never a traceback),
2 usage error.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import time
from pathlib import Path

from .context_compiler import ContextCompiler  # noqa: F401 (side-effect free)
from .db import open_db
from .engine import Engine
from .evidence_pack import build as build_evidence
from .gates import Evaluator, Gates
from .gateway import ApprovalRequired, RunContext, ToolContract, ToolGateway
from .journal import Journal
from .workers import FakeWorker

DEMO_CONCEPT = """Build a tiny greeting library:
- module greet(name: str) -> str returning "hello, <name>"
- include unit tests
- all acceptance criteria must be machine-checkable"""

EVAL_CRITERIA = ("has_code", "no_bad_rows")


def default_contracts() -> list[ToolContract]:
    def fs_write(path: str, content: str) -> dict:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"written": str(p), "bytes": len(content)}

    return [
        ToolContract(
            name="fs.read", version="1.0.0",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}},
                          "required": ["path"]},
            required_capability="fs.read", effect_class="read", idempotency="natural",
        ),
        ToolContract(
            name="fs.write", version="1.0.0",
            input_schema={"type": "object",
                          "properties": {"path": {"type": "string"},
                                         "content": {"type": "string"}},
                          "required": ["path", "content"]},
            required_capability="fs.write_local", effect_class="write_local",
            idempotency="keyed",
        ),
        ToolContract(
            name="fs.write.handler", version="1.0.0",
            input_schema={"type": "object",
                          "properties": {"path": {"type": "string"},
                                         "content": {"type": "string"}},
                          "required": ["path", "content"]},
            required_capability="fs.write_local", effect_class="write_local",
            idempotency="keyed", handler=fs_write,
        ),
        ToolContract(
            name="deploy.prod", version="1.0.0",
            input_schema={"type": "object", "properties": {"target": {"type": "string"}},
                          "required": ["target"]},
            required_capability="cmd.local", effect_class="dangerous",
            idempotency="none",
        ),
    ]


def run_demo(worker_kind: str = "fake", flaky: bool = False,
             db_path: str | None = None) -> dict:
    t0 = time.perf_counter()
    root = Path(db_path or ".agentos-demo").resolve()
    root.mkdir(parents=True, exist_ok=True)
    db = open_db(root / "agentos.db")
    eng = Engine(db, root)
    j = Journal(db)
    gw = ToolGateway(db, j)
    ev = Evaluator(db, root)
    for c in default_contracts():
        gw.register(c)

    # 1. Concept → Goal
    goal_id = eng.create_goal(DEMO_CONCEPT, actor="requester")

    # 2. Specification + acceptance criteria → activate
    eng.refine_spec(goal_id,
                    "Spec: greet(name)->'hello, <name>'; tests included.",
                    criteria=[
                        {"criterion_id": "has_code", "kind": "tests_present"},
                        {"criterion_id": "no_bad_rows",
                         "kind": "invariant",
                         "params": {"sql": "SELECT id FROM task WHERE status='FAILED'",
                                    "expect_rows": 0}},
                    ])
    eng.activate_goal(goal_id)

    # 3. Task DAG
    eng.plan_tasks(goal_id, [
        {"key": "impl", "title": "Implement greet() with tests",
         "definition_of_done": "code artifact recorded; scripted worker success",
         "retry_budget": 2},
    ])

    # 4-7. Execute with gateway effects + checkpoints
    eng.schedule_ready_tasks(goal_id)
    if flaky:
        from .workers import FakeWorker as FW
        worker = FW([{"ok": False, "fail_class": "worker"},
                     {"ok": True}])  # fails once, succeeds on retry
    else:
        if worker_kind == "hermes":
            try:
                from .hermes_worker import HermesAgentWorker
                worker = HermesAgentWorker()
            except Exception as e:
                return {"error": f"hermes worker unavailable: {e}",
                        "hint": "install hermes CLI or use --worker fake"}
        else:
            worker = FakeWorker()
    task_id = db.conn.execute(
        "SELECT id FROM task WHERE goal_id=?", (goal_id,)).fetchone()[0]
    # run-to-completion loop: retries consume the worker script; bounded by
    # the task retry budget inside the engine.
    for _ in range(4):
        status = db.conn.execute("SELECT status FROM task WHERE id=?",
                                 (task_id,)).fetchone()[0]
        if status == "DONE":
            break
        if status == "READY":
            run_id = eng.start_task(task_id, worker)
        else:  # first entry: PENDING→READY may need a reschedule after failure
            eng.schedule_ready_tasks(goal_id)
            if db.conn.execute("SELECT status FROM task WHERE id=?",
                               (task_id,)).fetchone()[0] != "READY":
                break

    # tool calls through the gateway inside the run context
    ctx = RunContext(run_id=run_id, goal_id=goal_id, task_id=task_id,
                     lease_owner=run_id,
                     capabilities=eng._capabilities_for(goal_id),
                     workspace_path=str(root / "workspaces" / run_id))
    ws_file = str(Path(ctx.workspace_path) / "greet.py")
    r1 = gw.invoke(ctx, gw.resolve("fs.write.handler"),
                   {"path": ws_file, "content": "def greet(name):\n    return f'hello, {name}'\n"},
                   idempotency_key=f"{run_id}:write-greet")
    # replay with same key+args ⇒ REPLAYED, no second write
    r2 = gw.invoke(ctx, gw.resolve("fs.write.handler"),
                   {"path": ws_file, "content": "def greet(name):\n    return f'hello, {name}'\n"},
                   idempotency_key=f"{run_id}:write-greet")
    gw.memory_write(ctx, "note", "greet implemented per spec",
                    source_uri=ws_file)

    # dangerous op without approval must be denied
    try:
        gw.invoke(ctx, gw.resolve("deploy.prod"), {"target": "prod"})
        denied_note = "NOT DENIED (bug)"
    except ApprovalRequired:
        denied_note = "denied (approval required)"

    # 8. Evaluators over criteria (rows land in the evaluation table)
    for criterion in EVAL_CRITERIA:
        ev.run(goal_id, criterion)

    # 9. Gate
    eng.submit_to_gate(goal_id)
    gate = Gates(db, j).evaluate_release(goal_id)

    # 10. Evidence pack
    pack = build_evidence(db, root, goal_id)

    # Structured summary read back from the DB (the journal-of-record), so the
    # output reflects persisted end state rather than in-memory call results.
    tasks = [{"id": r["id"], "title": r["title"], "status": r["status"]}
             for r in db.conn.execute(
                 "SELECT id, title, status FROM task WHERE goal_id=? ORDER BY id",
                 (goal_id,))]
    runs = [{"id": r["id"], "status": r["status"],
             "terminal_reason": r["terminal_reason"]}
            for r in db.conn.execute(
                "SELECT id, status, terminal_reason FROM run WHERE goal_id=?"
                " ORDER BY created_at, id", (goal_id,))]
    evaluations = [{"criterion": r["criterion_id"], "result": r["result"]}
                   for r in db.conn.execute(
                       "SELECT criterion_id, result FROM evaluation WHERE goal_id=?"
                       " ORDER BY rowid", (goal_id,))]

    return {
        "goal_id": goal_id,
        "run_id": run_id,
        "tasks": tasks,
        "runs": runs,
        "tool_write_1": r1["status"],
        "tool_write_replay": r2["status"],
        "dangerous_without_approval": denied_note,
        "evaluations": evaluations,
        "gate": {"result": gate["result"], "reasons": gate["reasons"]},
        "evidence_pack": pack["path"],
        "sha256": pack["sha256"],
        "chain_verified": pack["pack"]["audit"]["chain_verified"],
        "duration_ms": round((time.perf_counter() - t0) * 1000),
    }


def _emit_json(obj) -> None:
    print(json.dumps(obj, indent=2))


def _call_quietly(fn, *args, **kwargs):
    """Invoke fn with stdout captured, re-emitting anything it printed onto
    stderr, so the CLI's stdout stays exactly one clean JSON document."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            value = fn(*args, **kwargs)
    except BaseException:
        noise = buf.getvalue()
        if noise:
            sys.stderr.write(noise)
            sys.stderr.flush()
        raise
    noise = buf.getvalue()
    if noise:
        sys.stderr.write(noise)
        sys.stderr.flush()
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agentos")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--worker", choices=["fake", "hermes"], default="fake")
    d.add_argument("--flaky", action="store_true",
                   help="scripted first-attempt failure to exercise retry path")
    d.add_argument("--db", default=None, help="root dir for db/workspaces/artifacts")
    e = sub.add_parser("evidence")
    e.add_argument("--goal", required=True)
    e.add_argument("--db", default=None)
    a = ap.parse_args(argv)

    if a.cmd == "demo":
        try:
            result = _call_quietly(run_demo, a.worker, a.flaky, a.db)
        except Exception as exc:  # CLI boundary: JSON error, never a traceback
            _emit_json({"error": f"{type(exc).__name__}: {exc}"})
            return 1
        _emit_json(result)
        if "error" in result:
            return 1
        return 0 if result.get("gate", {}).get("result") == "pass" else 1
    if a.cmd == "evidence":
        try:
            root = Path(a.db or ".agentos-demo").resolve()
            db = open_db(root / "agentos.db")
            pack = _call_quietly(build_evidence, db, root, a.goal)
        except Exception as exc:
            _emit_json({"error": f"{type(exc).__name__}: {exc}"})
            return 1
        _emit_json(pack["pack"])
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
