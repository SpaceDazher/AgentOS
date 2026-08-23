"""Machine-readable evidence pack generator. See spec/SPEC.md §8."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .ids import canonical_json, new_id, sha256_text


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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

    # Phase 5 + R7: stage evals are goal-scoped; experiments come ONLY via
    # campaigns owned by this goal; wiki refs carry hashes and only include
    # notes whose frontmatter goal matches.
    stage_eval_runs = rows(
        "SELECT er.id, er.definition_id, er.definition_version, er.outcome,"
        " er.failure_class, er.judge_json, ed.stage, ed.kind, ed.metric,"
        " ed.required, ed.independence_class"
        " FROM eval_run er LEFT JOIN eval_definition ed"
        " ON ed.id=er.definition_id AND ed.version=er.definition_version"
        " WHERE er.goal_id=?", (goal_id,))
    stage_gates = rows(
        "SELECT id, stage, decision, rationale, authority FROM stage_gate"
        " WHERE goal_id=?", (goal_id,))
    experiments = rows(
        "SELECT DISTINCT e.id, e.campaign_id, e.hypothesis, e.baseline_ref,"
        " e.candidate_ref, e.status, e.decision_rationale,"
        " e.frozen_hashes_json FROM experiment e JOIN campaign c"
        " ON c.id = e.campaign_id WHERE c.goal_id=?", (goal_id,))
    wiki_refs = {}
    wiki_dir = Path(root_dir) / "wiki" / "_generated"
    if wiki_dir.exists():
        for p in sorted(wiki_dir.glob("*.md")):
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            m = re.search(r"^goal_id:\s*(\S+)\s*$", text, re.MULTILINE)
            note_goal = m.group(1) if m else None
            if note_goal and note_goal != goal_id:
                continue   # another goal's note never enters this pack
            wiki_refs[p.stem] = {
                "path": f"wiki/_generated/{p.name}",
                "sha256": _sha_bytes(p.read_bytes()),
            }

    pack = {
        "schema": "agentos.evidence-pack/v2",
        "goal": goal[0],
        "acceptance_criteria": criteria,
        "tasks": tasks,
        "runs": runs,
        "evaluations": evals,
        "gates": gates_,
        "artifact_versions": artifacts,
        "tool_activities": activities,
        "approvals": approvals,
        "stage_evals": {
            "runs": stage_eval_runs,
            "gates": stage_gates,
        },
        "experiments": [dict(e, frozen_hashes=json.loads(
            e.pop("frozen_hashes_json") or "{}")) for e in experiments],
        "wiki_refs": wiki_refs,
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
