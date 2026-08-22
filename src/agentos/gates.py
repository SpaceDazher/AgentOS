"""Deterministic evaluators + gates. See spec/SPEC.md §8.

Evaluator produces Evaluation rows; the Gate is the ONLY actor allowed to move
Goal → ACCEPTED/REJECTED.
"""
from __future__ import annotations

import json
from pathlib import Path

from .ids import canonical_json, new_id
from .journal import Journal

METHOD_VERSION = "eval-v1"


class Evaluator:
    def __init__(self, db, root_dir: str | Path):
        self.db = db
        self.root = Path(root_dir)

    # -- built-in deterministic checks ------------------------------------------------
    def _check_tests_present(self, goal_id: str, params: dict) -> tuple[bool, dict]:
        row = self.db.conn.execute(
            "SELECT COUNT(*) FROM artifact_version WHERE goal_id=? AND kind='code'",
            (goal_id,)).fetchone()[0]
        return row > 0, {"code_artifacts": row}

    def _check_invariant(self, goal_id: str, params: dict) -> tuple[bool, dict]:
        """params: {"sql": "...", "expect_rows": "0"} — run a read-only invariant SQL."""
        sql = params.get("sql", "")
        if not sql.lower().lstrip("( ").startswith("select"):
            return False, {"error": "invariant must be a SELECT"}
        try:
            n = len(self.db.conn.execute(sql).fetchall())
        except Exception as e:
            return False, {"error": str(e)[:200]}
        expect = int(params.get("expect_rows", 0))
        return n == expect, {"rows": n, "expected": expect}

    def _check_command_exit_0(self, goal_id: str, params: dict) -> tuple[bool, dict]:
        """MVP: simulated command check against recorded outputs (no shell exec)."""
        marker = params.get("output_key", "")
        row = self.db.conn.execute(
            "SELECT content_sha256 FROM artifact_version WHERE goal_id=?"
            " AND kind='code' AND status='CURRENT' ORDER BY version DESC LIMIT 1",
            (goal_id,)).fetchone()
        ok = bool(row) and bool(marker)
        return ok, {"marker": marker, "artifact": bool(row)}

    CHECKS = {
        "tests_present": _check_tests_present,
        "invariant": _check_invariant,
        "command_exit_0": _check_command_exit_0,
    }

    def run(self, goal_id: str, criterion_id: str) -> dict:
        crit = self.db.conn.execute(
            "SELECT * FROM acceptance_criteria WHERE goal_id=? AND criterion_id=?",
            (goal_id, criterion_id)).fetchone()
        if not crit:
            raise RuntimeError(f"unknown criterion {criterion_id}")
        fn = self.CHECKS.get(crit["kind"])
        if not fn:
            raise RuntimeError(f"unknown check kind {crit['kind']}")
        ok, detail = fn(self, goal_id, json.loads(crit["params_json"]))
        subject = self.db.conn.execute(
            "SELECT id FROM artifact_version WHERE goal_id=? AND status='CURRENT'"
            " ORDER BY version DESC LIMIT 1", (goal_id,)).fetchone()
        eid = new_id("eval")
        self.db.conn.execute(
            "INSERT INTO evaluation(id, goal_id, subject_artifact_id, criterion_id,"
            " method, method_version, config_json, result, detail_json)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (eid, goal_id, subject["id"] if subject else None, criterion_id,
             crit["kind"], METHOD_VERSION, canonical_json(json.loads(crit["params_json"])),
             "pass" if ok else "fail", canonical_json(detail)))
        Journal(self.db).append_event(goal_id, "evaluator", "evaluation.recorded",
                                      {"evaluation_id": eid, "criterion": criterion_id,
                                       "result": "pass" if ok else "fail"})
        return {"evaluation_id": eid, "result": "pass" if ok else "fail", "detail": detail}


GATE_PREDICATE = "release_predicate_v1"


class Gates:
    def __init__(self, db, journal: Journal):
        self.db = db
        self.j = journal
        from .machines import Machines
        self.m = Machines(db, journal)

    def evaluate_release(self, goal_id: str, actor: str = "gate") -> dict:
        reasons: list[str] = []
        g = self.db.conn.execute(
            "SELECT * FROM goal WHERE id=?", (goal_id,)).fetchone()

        tasks = self.db.conn.execute(
            "SELECT COUNT(*) n, SUM(status='DONE') done FROM task WHERE goal_id=?",
            (goal_id,)).fetchone()
        if not tasks["n"] or tasks["done"] != tasks["n"]:
            reasons.append("not all tasks DONE")

        need = self.db.conn.execute(
            "SELECT criterion_id FROM acceptance_criteria WHERE goal_id=?",
            (goal_id,)).fetchall()
        for c in need:
            passed = self.db.conn.execute(
                "SELECT COUNT(*) FROM evaluation WHERE goal_id=? AND criterion_id=?"
                " AND result='pass'", (goal_id, c["criterion_id"])).fetchone()[0]
            if not passed:
                reasons.append(f"criterion {c['criterion_id']} has no passing evaluation")

        unknown = self.db.conn.execute(
            "SELECT COUNT(*) FROM activity a JOIN run r ON r.id=a.run_id"
            " WHERE r.goal_id=? AND a.status='UNKNOWN_OUTCOME'", (goal_id,)
        ).fetchone()[0]
        if unknown:
            reasons.append(f"{unknown} unresolved UNKNOWN_OUTCOME activities")

        chain_ok, bad_seq = self.j.full_chain_check()
        if not chain_ok:
            reasons.append(f"audit chain broken at seq {bad_seq}")

        if g["risk_tier"] == "sensitive":
            appr = self.db.conn.execute(
                "SELECT COUNT(*) FROM approval WHERE goal_id=? AND status='CONSUMED'"
                " AND operation='release'", (goal_id,)).fetchone()[0]
            if not appr:
                reasons.append("sensitive goal requires a consumed release approval")

        result = "pass" if not reasons else "fail"
        fingerprint = canonical_json({"goal": goal_id, "reasons": sorted(reasons)})
        gid = new_id("gate")
        self.db.conn.execute(
            "INSERT INTO gate(id, goal_id, predicate_name, predicate_version,"
            " input_fingerprint, result, rationale) VALUES (?,?,?,?,?,?,?)",
            (gid, goal_id, GATE_PREDICATE, "v1", fingerprint, result,
             "; ".join(reasons) or "all predicates satisfied"))
        self.j.append_event(goal_id, "gate", f"gate.{result}", {"gate_id": gid})

        if result == "pass":
            self.m.goal_transition(goal_id, "GATE_PENDING", "ACCEPTED", "gate")
        else:
            self.m.goal_transition(goal_id, "GATE_PENDING", "REJECTED", "gate",
                                   payload={"gaps": reasons})
        return {"gate_id": gid, "result": result, "reasons": reasons}
