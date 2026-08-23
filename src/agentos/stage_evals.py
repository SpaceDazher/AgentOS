"""Stage Evaluation Framework (Phase 1+2). See ADR-0006 and SPEC §9.

Versioned eval definitions (append-only), eval cases, eval runs and stage
gates. Deterministic checks are blocking; llm_judge checks are advisory-only
(a judge result can never satisfy a required criterion alone). Every judge
record must carry model id + prompt version + rubric version or it is
inadmissible.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .gateway import GatewayError
from .ids import new_id, sha256_text

STAGES = ("concept", "specification", "plan", "execution",
          "verification", "post_episode")


class StageEvalError(GatewayError):
    pass


class StageEvals:
    """Registry + runner for stage evaluations over a DB."""

    def __init__(self, db, root_dir: str | Path):
        self.db = db
        self.root = Path(root_dir)

    # -- definitions ---------------------------------------------------------
    def define(self, *, stage: str, kind: str, metric: str, threshold: float,
               direction: str = "minimize", corpus_version: str = "c1",
               timeout_s: float = 30, required: bool = True,
               independence_class: str = "normal",
               prompt_version: str | None = None,
               rubric_version: str | None = None,
               def_id: str | None = None) -> tuple[str, int]:
        if stage not in STAGES:
            raise StageEvalError(f"unknown stage {stage}")
        if kind == "llm_judge" and not (prompt_version and rubric_version):
            raise StageEvalError(
                "llm_judge definitions need prompt_version and rubric_version")
        if kind not in ("deterministic", "llm_judge"):
            raise StageEvalError(f"unknown kind {kind}")
        def_id = def_id or f"eval.{stage}.{metric}"
        row = self.db.conn.execute(
            "SELECT MAX(version) AS v FROM eval_definition WHERE id=?",
            (def_id,)).fetchone()
        version = (row["v"] or 0) + 1
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO eval_definition(id, version, stage, kind, metric,"
                " direction, threshold, timeout_s, corpus_version,"
                " independence_class, required, prompt_version, rubric_version)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (def_id, version, stage, kind, metric, direction, threshold,
                 timeout_s, corpus_version, independence_class,
                 1 if required else 0, prompt_version, rubric_version))
        return def_id, version

    def latest(self, def_id: str) -> dict | None:
        row = self.db.conn.execute(
            "SELECT * FROM eval_definition WHERE id=?"
            " ORDER BY version DESC LIMIT 1", (def_id,)).fetchone()
        return dict(row) if row else None

    # -- cases ---------------------------------------------------------------
    def add_case(self, *, case_id: str, corpus_version: str, stage: str,
                 label: str, set_class: str, input_ref: str,
                 expected_outcome: str, provenance: dict | None = None) -> str:
        if set_class not in ("gold", "near_miss", "alternative_correct",
                             "adversarial", "incomplete"):
            raise StageEvalError(f"unknown set_class {set_class}")
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO eval_case(id, corpus_version, stage, label,"
                " set_class, input_ref, expected_outcome, provenance_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (case_id, corpus_version, stage, label, set_class, input_ref,
                 expected_outcome, json.dumps(provenance or {})))
        return case_id

    def cases(self, corpus_version: str, set_class: str | None = None) -> list[dict]:
        if set_class:
            rows = self.db.conn.execute(
                "SELECT * FROM eval_case WHERE corpus_version=? AND set_class=?",
                (corpus_version, set_class)).fetchall()
        else:
            rows = self.db.conn.execute(
                "SELECT * FROM eval_case WHERE corpus_version=?",
                (corpus_version,)).fetchall()
        return [dict(r) for r in rows]

    # -- running -------------------------------------------------------------
    def run_case(self, def_id: str, case: dict, check_fn, *,
                 goal_id: str | None = None, seed: int | None = None,
                 env: dict | None = None, judge: dict | None = None) -> dict:
        """Run one definition against one case with the given deterministic
        check function: check_fn(case) -> (bool, detail)."""
        d = self.latest(def_id)
        if not d:
            raise StageEvalError(f"unknown eval definition {def_id}")
        if d["kind"] == "llm_judge":
            if not judge or not judge.get("model_id"):
                raise StageEvalError(
                    "llm_judge run without model_id is inadmissible")
        t0 = time.perf_counter()
        try:
            ok, detail = check_fn(case)
            outcome = "pass" if ok else "fail"
            failure_class = None
        except Exception as e:  # noqa: BLE001
            ok, detail, outcome, failure_class = False, {
                "error": str(e)[:200]}, "error", "evaluator"
        metrics = {"value": 0.0 if ok else 1.0, "passed": bool(ok)}
        run_id = new_id("evalrun")
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO eval_run(id, goal_id, definition_id,"
                " definition_version, env_json, seed, metrics_json, outcome,"
                " logs_sha256, duration_ms, failure_class, judge_json)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, goal_id, def_id, d["version"],
                 json.dumps(env or {}), seed, json.dumps(metrics), outcome,
                 sha256_text(json.dumps(detail, sort_keys=True)),
                 round((time.perf_counter() - t0) * 1000), failure_class,
                 json.dumps(judge) if judge else None))
        return {"eval_run_id": run_id, "outcome": outcome, "ok": ok,
                "detail": detail, "case_id": case["id"],
                "definition": f"{def_id}@{d['version']}"}

    # -- stage gates ----------------------------------------------------------
    def stage_gate(self, stage: str, required_eval_ids: list[str],
                   goal_id: str | None = None) -> dict:
        """Decide a stage gate from persisted eval_run outcomes.

        Advisory (required=0) failures add rationale but never fail the gate.
        A required definition with no runs fails the gate (no silent skip)."""
        reasons: list[str] = []
        decision = "pass"
        for def_id in required_eval_ids:
            d = self.latest(def_id)
            if not d:
                raise StageEvalError(f"unknown eval definition {def_id}")
            runs = self.db.conn.execute(
                "SELECT outcome, failure_class FROM eval_run"
                " WHERE definition_id=? AND definition_version=?"
                " ORDER BY created_at DESC", (def_id, d["version"])).fetchall()
            if not runs:
                if d["required"]:
                    decision = "fail"
                    reasons.append(f"{def_id}: no eval runs recorded")
                else:
                    reasons.append(f"{def_id}: advisory, no runs")
                continue
            bad = [r["outcome"] for r in runs if r["outcome"] != "pass"]
            if bad and d["required"]:
                decision = "fail"
                reasons.append(
                    f"{def_id}@{d['version']}: {len(bad)}/{len(runs)} runs"
                    f" failed ({','.join(sorted(set(bad)))})")
            elif bad:
                reasons.append(
                    f"{def_id}@{d['version']}: advisory failures {len(bad)}")
        gate_id = new_id("stagegate")
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO stage_gate(id, stage, required_eval_ids_json,"
                " decision, rationale, authority, goal_id) VALUES (?,?,?,?,?,?,?)",
                (gate_id, stage, json.dumps(required_eval_ids), decision,
                 "; ".join(reasons) or "all required evals passed",
                 "GateAuthority", goal_id))
        return {"stage_gate_id": gate_id, "stage": stage,
                "decision": decision, "reasons": reasons}
