"""Machine-readable evidence pack generator. See spec/SPEC.md §8."""
from __future__ import annotations

import json
from pathlib import Path

from .ids import canonical_json, new_id, sha256_text


def build(db, root_dir: str | Path, goal_id: str) -> dict:
    c = db.conn

    def rows(sql: str, args: tuple = ()) -> list[dict]:
        return [dict(r) for r in c.execute(sql, args)]

    goal = rows("SELECT * FROM goal WHERE id=?", (goal_id,))
    if not goal:
        raise RuntimeError("no such goal")

    events = rows("SELECT seq, ts, goal_id, actor, event_type, payload_json,"
                  " prev_event_sha256 FROM audit_event ORDER BY seq")
    # F10: verify the GLOBAL chain first (prev pointers span all goals), then
    # project this goal's events. Also fail loudly on inconsistent ACCEPTED.
    from .journal import Journal as _J
    chain_ok, bad_seq = _J(db).full_chain_check()
    events = [ev for ev in events if ev["goal_id"] == goal_id]
    if not chain_ok:
        raise RuntimeError(
            f"audit hash chain broken at seq {bad_seq}; refusing to emit an "
            f"evidence pack (tamper suspected)")
    accepted = goal[0]["status"] == "ACCEPTED"
    if accepted:
        ok_gate = c.execute(
            "SELECT COUNT(*) FROM gate WHERE goal_id=? AND result='pass'",
            (goal_id,)).fetchone()[0]
        acc_ev = c.execute(
            "SELECT COUNT(*) FROM audit_event WHERE goal_id=? AND"
            " event_type='goal.accepted'", (goal_id,)).fetchone()[0]
        if not ok_gate or not acc_ev:
            raise RuntimeError(
                "inconsistent ACCEPTED: goal is ACCEPTED without a passing gate"
                " record and/or goal.accepted audit event")

    tasks = rows("SELECT id, title, status, attempts FROM task WHERE goal_id=?", (goal_id,))
    runs = rows("SELECT id, task_id, worker_type, status, terminal_reason,"
                " resumed_from_run_id FROM run WHERE goal_id=?", (goal_id,))
    evals = rows("SELECT id, criterion_id, method, method_version, result, detail_json"
                 " FROM evaluation WHERE goal_id=?", (goal_id,))
    gates_ = rows("SELECT id, predicate_name, predicate_version, result, rationale"
                  " FROM gate WHERE goal_id=?", (goal_id,))
    artifacts = rows("SELECT id, kind, version, content_sha256, status,"
                     " superseded_by_id FROM artifact_version WHERE goal_id=?", (goal_id,))
    activities = rows(
        "SELECT a.id, a.op_name, a.tool_identity, a.effect_class, a.status,"
        " a.result_digest FROM activity a JOIN run r ON r.id=a.run_id"
        " WHERE r.goal_id=?", (goal_id,))
    approvals = rows("SELECT id, operation, tool_identity, actor, status, nonce"
                     " FROM approval WHERE goal_id=?", (goal_id,))
    criteria = rows("SELECT criterion_id, kind FROM acceptance_criteria WHERE goal_id=?",
                    (goal_id,))

    pack = {
        "schema": "agentos.evidence-pack/v1",
        "goal": goal[0],
        "acceptance_criteria": criteria,
        "tasks": tasks,
        "runs": runs,
        "evaluations": evals,
        "gates": gates_,
        "artifact_versions": artifacts,
        "tool_activities": activities,
        "approvals": approvals,
        "audit": {
            "event_count": len(events),
            "chain_verified": chain_ok,
            "first_seq": events[0]["seq"] if events else None,
            "last_seq": events[-1]["seq"] if events else None,
        },
        "accepted": goal[0]["status"] == "ACCEPTED",
    }
    digest = sha256_text(canonical_json(pack))
    out_dir = Path(root_dir) / "goals" / goal_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "evidence-pack.json"
    out_path.write_text(canonical_json({"sha256": digest, **pack}), encoding="utf-8")
    return {"pack": pack, "path": str(out_path), "sha256": digest}
