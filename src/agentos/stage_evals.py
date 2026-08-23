"""Stage Evaluation Framework (Phase 1+2). See ADR-0006 and SPEC §9.

R5 corrective round:
- llm_judge definitions are ALWAYS advisory (required=True refused at define);
- a judge run must carry model_id AND prompt_version AND rubric_version
  matching the definition, else inadmissible;
- eval runs bind goal_id + case_id + artifact_chain_hash + corpus_version;
- stage_gate is fail-closed: empty required set => fail; runs are matched to
  the same goal_id; cross-goal reuse impossible; unknown definition => error.
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
        if kind not in ("deterministic", "llm_judge"):
            raise StageEvalError(f"unknown kind {kind}")
        if kind == "llm_judge":
            # ADR-0006: a model judge can never be a blocking criterion.
            if required:
                raise StageEvalError(
                    "llm_judge cannot be required (advisory-only by policy)")
            if not (prompt_version and rubric_version):
                raise StageEvalError(
                    "llm_judge definitions need prompt_version and rubric_version")
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
                 goal_id: str, seed: int | None = None,
                 env: dict | None = None, judge: dict | None = None,
                 artifact_chain_hash: str | None = None,
                 corpus_version: str | None = None) -> dict:
        """Run one definition against one case. The run is durably bound to
        the goal, the case id and the artifact-chain hash so gates can never
        reuse another goal's results."""
        d = self.latest(def_id)
        if not d:
            raise StageEvalError(f"unknown eval definition {def_id}")
        if not goal_id:
            raise StageEvalError("eval_run requires goal_id")
        case_id = case.get("id")
        if not case_id:
            raise StageEvalError("eval_run requires a case with an id")
        chain = artifact_chain_hash or "no-artifact-chain"
        corpus = corpus_version or d["corpus_version"]
        if d["kind"] == "llm_judge":
            missing = [k for k in ("model_id", "prompt_version",
                                   "rubric_version")
                       if not (judge or {}).get(k)]
            if missing:
                raise StageEvalError(
                    f"llm_judge run inadmissible, missing provenance: {missing}")
            if (judge["prompt_version"] != d["prompt_version"]
                    or judge["rubric_version"] != d["rubric_version"]):
                raise StageEvalError(
                    "judge prompt/rubric version does not match definition"
                    f" {def_id}@{d['version']}")
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
                 json.dumps({"env": env or {}, "case_id": case_id,
                             "artifact_chain_hash": chain,
                             "corpus_version": corpus}, sort_keys=True),
                 seed, json.dumps(metrics), outcome,
                 sha256_text(json.dumps(detail, sort_keys=True)),
                 round((time.perf_counter() - t0) * 1000), failure_class,
                 json.dumps(judge) if judge else None))
        return {"eval_run_id": run_id, "outcome": outcome, "ok": ok,
                "detail": detail, "case_id": case_id,
                "definition": f"{def_id}@{d['version']}"}

    # -- stage gates ----------------------------------------------------------
    def stage_gate(self, stage: str, required_eval_ids: list[str],
                   goal_id: str, artifact_chain_hash: str | None = None,
                   corpus_version: str | None = None) -> dict:
        """Decide a stage gate from persisted eval_run outcomes.

        Fail-closed rules (R5): empty required list => FAIL; every required
        definition needs >=1 run for THIS goal (cross-goal reuse impossible);
        a definition with zero runs for this goal fails the gate."""
        if not required_eval_ids:
            return self._record_gate(stage, [], "fail", goal_id,
                                     ["no required evals configured — "
                                      "fail-closed"])
        reasons: list[str] = []
        decision = "pass"
        for def_id in required_eval_ids:
            d = self.latest(def_id)
            if not d:
                raise StageEvalError(f"unknown eval definition {def_id}")
            if d["stage"] != stage:
                decision = "fail"
                reasons.append(f"{def_id}: belongs to stage {d['stage']},"
                               f" not {stage}")
                continue
            env_like = f'"goal_id": "{goal_id}"'
            rows = self.db.conn.execute(
                "SELECT outcome FROM eval_run"
                " WHERE definition_id=? AND definition_version=?"
                " AND goal_id=? ORDER BY created_at DESC",
                (def_id, d["version"], goal_id)).fetchall()
            _ = env_like  # documentation only
            if not rows:
                decision = "fail"
                reasons.append(f"{def_id}: no eval runs recorded for this goal")
                continue
            bad = [r["outcome"] for r in rows if r["outcome"] != "pass"]
            if bad and d["required"]:
                decision = "fail"
                reasons.append(
                    f"{def_id}@{d['version']}: {len(bad)}/{len(rows)} runs"
                    f" failed ({','.join(sorted(set(bad)))})")
            elif bad:
                reasons.append(
                    f"{def_id}@{d['version']}: advisory failures {len(bad)}")
        return self._record_gate(stage, required_eval_ids, decision,
                                 goal_id, reasons)

    def _record_gate(self, stage: str, required_eval_ids: list[str],
                     decision: str, goal_id: str, reasons: list[str]) -> dict:
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
