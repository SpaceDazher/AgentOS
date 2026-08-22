"""Deterministic evaluators + gates. See spec/SPEC.md §8.

Evaluator produces Evaluation rows; the Gate is the ONLY actor allowed to move
Goal → ACCEPTED/REJECTED, via Machines.accept_by_gate_record (GateAuthority +
in-transaction passing-gate-row check).

Evaluation freshness binding: every evaluation stores the criterion_version and
the artifact_chain_hash of the CURRENT artifact set it inspected. The gate only
accepts evaluations whose (criterion_version, artifact_chain_hash) match the
goal's current criterion versions and current artifact chain — stale evaluations
are ignored, so changing a criterion invalidates prior passes.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .ids import canonical_json, new_id, sha256_text
from .journal import Journal

METHOD_VERSION = "eval-v2"


class Evaluator:
    def __init__(self, db, root_dir: str | Path):
        self.db = db
        self.root = Path(root_dir)

    # -- artifact chain fingerprint ---------------------------------------------
    def artifact_chain_hash(self, goal_id: str) -> str:
        """Stable hash over the CURRENT artifact versions (kind, version, sha256)."""
        rows = self.db.conn.execute(
            "SELECT kind, version, content_sha256 FROM artifact_version"
            " WHERE goal_id=? AND status='CURRENT' ORDER BY kind, version",
            (goal_id,)).fetchall()
        return sha256_text(canonical_json([dict(r) for r in rows]))

    # -- built-in deterministic checks ------------------------------------------------
    def _check_tests_present(self, goal_id: str, params: dict) -> tuple[bool, dict]:
        """The CURRENT code artifact must be a real, non-empty Python module set:
        every .py file parses, contains ≥1 def/class, and a test file exists
        with at least one test function."""
        row = self.db.conn.execute(
            "SELECT storage_path, content_sha256 FROM artifact_version"
            " WHERE goal_id=? AND kind='code' AND status='CURRENT'"
            " ORDER BY version DESC LIMIT 1", (goal_id,)).fetchone()
        if not row:
            return False, {"reason": "no CURRENT code artifact"}
        try:
            blob = json.loads(Path(row["storage_path"]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return False, {"reason": f"unreadable code artifact: {e}"}
        files = blob.get("files", {}) if isinstance(blob, dict) else {}
        if not files:
            return False, {"reason": "code artifact contains no files"}
        parsed = 0
        test_funcs = 0
        for fname, content in files.items():
            if not fname.endswith(".py") or not isinstance(content, str) or not content.strip():
                return False, {"reason": f"empty/non-python file: {fname}"}
            try:
                tree = ast_parse(content)
            except SyntaxError as e:
                return False, {"reason": f"syntax error in {fname}: {e}"}
            defs = [n for n in ast_walk(tree)
                    if isinstance(n, (ast_FunctionDef, ast_AsyncFunctionDef, ast_ClassDef))]
            if not defs:
                return False, {"reason": f"no definitions in {fname}"}
            parsed += 1
            # test file = filename contains 'test' OR any function named test_*
            for n in ast_walk(tree):
                if isinstance(n, ast_FunctionDef) and n.name.startswith("test"):
                    test_funcs += 1
        if test_funcs < 1:
            return False, {"reason": "no test_* functions in any test file"}
        return True, {"files": parsed, "test_functions": test_funcs}

    def _check_command_exit_0(self, goal_id: str, params: dict) -> tuple[bool, dict]:
        """Really execute the CURRENT code artifact's entry module in an isolated
        subprocess (no network, tmp cwd, hard timeout). Pass = exit 0.
        params: {"entry": "greet.py", "call": "greet", "arg": "world",
                 "expect_stdout_contains": "hello, world"} (all optional except entry)."""
        row = self.db.conn.execute(
            "SELECT storage_path FROM artifact_version WHERE goal_id=?"
            " AND kind='code' AND status='CURRENT' ORDER BY version DESC LIMIT 1",
            (goal_id,)).fetchone()
        if not row:
            return False, {"reason": "no CURRENT code artifact"}
        try:
            blob = json.loads(Path(row["storage_path"]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return False, {"reason": f"unreadable code artifact: {e}"}
        files = blob.get("files", {}) if isinstance(blob, dict) else {}
        entry = params.get("entry", "")
        if entry not in files:
            return False, {"reason": f"entry '{entry}' not in artifact"}
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            for fname, content in files.items():
                p = (tdp / fname)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            driver = tdp / "__eval_driver__.py"
            if params.get("call"):
                driver.write_text(
                    f"import {Path(entry).stem} as m\n"
                    f"_r = m.{params['call']}({params['arg']!r})\n"
                    f"print(_r)\n", encoding="utf-8")
            else:
                driver.write_text(f"import {Path(entry).stem}\n", encoding="utf-8")
            try:
                proc = subprocess.run(
                    [sys.executable, str(driver)], cwd=str(tdp),
                    capture_output=True, text=True, timeout=15,
                    env={"PYTHONPATH": str(tdp), "PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
            except subprocess.TimeoutExpired:
                return False, {"reason": "evaluator subprocess timeout"}
            if proc.returncode != 0:
                return False, {"reason": "non-zero exit", "stderr": proc.stderr[-300:]}
            out = (proc.stdout or "").strip()
            want = params.get("expect_stdout_contains")
            if want is not None and want not in out:
                return False, {"reason": "stdout mismatch", "stdout": out[:200]}
            return True, {"stdout": out[:200]}

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

    CHECKS = {
        "tests_present": _check_tests_present,
        "invariant": _check_invariant,
        "command_exit_0": _check_command_exit_0,
    }

    def run(self, goal_id: str, criterion_id: str) -> dict:
        crit = self.db.conn.execute(
            "SELECT * FROM acceptance_criteria WHERE goal_id=? AND criterion_id=?"
            " ORDER BY criterion_version DESC LIMIT 1", (goal_id, criterion_id)
        ).fetchone()
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
            " criterion_version, method, method_version, config_json, result,"
            " detail_json, artifact_chain_hash)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (eid, goal_id, subject["id"] if subject else None, criterion_id,
             crit["criterion_version"], crit["kind"], METHOD_VERSION,
             canonical_json(json.loads(crit["params_json"])),
             "pass" if ok else "fail", canonical_json(detail),
             self.artifact_chain_hash(goal_id)))
        Journal(self.db).append_event(goal_id, "evaluator", "evaluation.recorded",
                                      {"evaluation_id": eid, "criterion": criterion_id,
                                       "criterion_version": crit["criterion_version"],
                                       "result": "pass" if ok else "fail"})
        return {"evaluation_id": eid, "result": "pass" if ok else "fail", "detail": detail}


# lazy ast helpers (import cost only when used)
def ast_parse(code: str):
    import ast
    return ast.parse(code)


def ast_walk(tree):
    import ast
    return ast.walk(tree)


from ast import (  # noqa: E402
    FunctionDef as ast_FunctionDef,
    AsyncFunctionDef as ast_AsyncFunctionDef,
    ClassDef as ast_ClassDef,
)


GATE_PREDICATE = "release_predicate_v2"


class Gates:
    def __init__(self, db, journal: Journal):
        self.db = db
        self.j = journal
        from .machines import Machines, gate_authority
        self.m = Machines(db, journal)
        self.m.set_gate_authority(gate_authority())

    def evaluate_release(self, goal_id: str) -> dict:
        reasons: list[str] = []
        g = self.db.conn.execute(
            "SELECT * FROM goal WHERE id=?", (goal_id,)).fetchone()

        tasks = self.db.conn.execute(
            "SELECT COUNT(*) n, SUM(status='DONE') done FROM task WHERE goal_id=?",
            (goal_id,)).fetchone()
        if not tasks["n"] or tasks["done"] != tasks["n"]:
            reasons.append("not all tasks DONE")

        # Freshness binding: each CURRENT criterion version must have a passing
        # evaluation recorded for exactly that version AND the current artifact chain.
        chain_hash = _artifact_chain_hash(self.db, goal_id)
        crits = self.db.conn.execute(
            "SELECT criterion_id, MAX(criterion_version) v FROM acceptance_criteria"
            " WHERE goal_id=? GROUP BY criterion_id", (goal_id,)).fetchall()
        for c in crits:
            passed = self.db.conn.execute(
                "SELECT COUNT(*) FROM evaluation WHERE goal_id=? AND criterion_id=?"
                " AND criterion_version=? AND artifact_chain_hash=? AND result='pass'",
                (goal_id, c["criterion_id"], c["v"], chain_hash)).fetchone()[0]
            if not passed:
                reasons.append(
                    f"criterion {c['criterion_id']} (v{c['v']}) has no passing "
                    f"evaluation against the current artifact chain")

        unknown = self.db.conn.execute(
            "SELECT COUNT(*) FROM activity a JOIN run r ON r.id=a.run_id"
            " WHERE r.goal_id=? AND a.status IN ('UNKNOWN_OUTCOME','RECONCILED_FAILED')",
            (goal_id,)
        ).fetchone()[0]
        if unknown:
            reasons.append(f"{unknown} unresolved/reconciled-failed activities")

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
            (gid, goal_id, GATE_PREDICATE, "v2", fingerprint, result,
             "; ".join(reasons) or "all predicates satisfied"))
        self.j.append_event(goal_id, "gate", f"gate.{result}", {"gate_id": gid})

        if result == "pass":
            self.m.accept_by_gate_record(goal_id, "ACCEPTED", auth=self.m._gate_auth,
                                         gate_id=gid, reasons=[])
        else:
            self.m.accept_by_gate_record(goal_id, "REJECTED",
                                         auth=self.m._gate_auth, gate_id=gid,
                                         reasons=reasons)
        return {"gate_id": gid, "result": result, "reasons": reasons}


def _artifact_chain_hash(db, goal_id: str) -> str:
    rows = db.conn.execute(
        "SELECT kind, version, content_sha256 FROM artifact_version"
        " WHERE goal_id=? AND status='CURRENT' ORDER BY kind, version",
        (goal_id,)).fetchall()
    return sha256_text(canonical_json([dict(r) for r in rows]))
