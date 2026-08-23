"""Deterministic stage checks (Phase 2) — one check function per required
stage eval. Each: case -> (bool, detail). All pure functions over the case
payload; no LLM, no network, fully deterministic.

Cases are fixture dicts loaded from evals/fixtures/<corpus>/...; input_ref
points at a JSON file with {"payload": {...}, "expect": {...}}.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path


def _load(case: dict) -> dict:
    ref = case.get("input_ref", "")
    p = Path(ref)
    if not p.exists():
        # fixtures dir relative to repo root
        alt = Path(__file__).resolve().parent.parent.parent / ref
        p = alt if alt.exists() else p
    return json.loads(p.read_text(encoding="utf-8"))


# -- Concept stage ------------------------------------------------------------
def concept_clarity(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    text = data["concept_text"]
    words = len(text.split())
    ok = bool(data.get("goal_statement")) and 5 <= words <= 200
    return ok, {"words": words, "has_goal": bool(data.get("goal_statement"))}


def concept_measurability(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    crits = data.get("acceptance_criteria") or []
    measurable = [c for c in crits
                  if c.get("kind") in ("tests_present", "command_exit_0",
                                       "invariant", "metric_threshold")]
    ok = bool(crits) and len(measurable) == len(crits)
    return ok, {"criteria": len(crits), "measurable": len(measurable)}


def concept_scope_constraints(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    ok = bool(data.get("scope")) and bool(data.get("constraints")) \
        and bool(data.get("stop_conditions"))
    return ok, {"scope": bool(data.get("scope")),
                "constraints": bool(data.get("constraints")),
                "stop_conditions": bool(data.get("stop_conditions"))}


def concept_contradictions(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    reqs = data.get("requirements") or []
    lowered = [r.lower() for r in reqs]
    conflicts = []
    for i, a in enumerate(lowered):
        for b in lowered[i + 1:]:
            if ("must not" in a and "must " in b and
                    a.split("must not")[0].strip() ==
                    b.split("must")[1].strip()[:len(a.split("must not")[0].strip())]
                    and a != b):
                conflicts.append((a, b))
    ok = len(reqs) > 0 and not data.get("explicit_contradiction", False)
    return ok, {"requirements": len(reqs), "conflicts_marked":
                data.get("explicit_contradiction", False)}


# -- Specification stage --------------------------------------------------------
def spec_traceability(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    reqs = {r["id"] for r in (data.get("requirements") or [])}
    crits = data.get("acceptance_criteria") or []
    covered = {c.get("requirement_id") for c in crits}
    uncovered = reqs - covered
    return not uncovered, {"uncovered_requirements": sorted(uncovered)}


def spec_case_coverage(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    kinds = set(data.get("test_kinds") or [])
    need = {"positive", "negative", "edge"}
    missing = need - kinds
    return not missing, {"missing": sorted(missing),
                         "present": sorted(kinds & need)}


def spec_criteria_checkable(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    bad = [c["id"] for c in (data.get("acceptance_criteria") or [])
           if c.get("kind") not in ("tests_present", "command_exit_0",
                                    "invariant", "metric_threshold")]
    return not bad, {"non_machine_checkable": bad}


def spec_gaming_resistance(case: dict) -> tuple[bool, dict]:
    """Detect criteria that literally restate 'the agent says it is done'."""
    data = _load(case)["payload"]
    suspicious = [c["id"] for c in (data.get("acceptance_criteria") or [])
                  if any(w in c.get("kind", "").lower()
                         for w in ("self_report", "agent_claim", "verbal"))]
    return not suspicious, {"gaming_prone": suspicious}


# -- Plan stage -------------------------------------------------------------
def plan_dag_validity(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    tasks = data.get("tasks") or []
    ids = {t["key"] for t in tasks}
    problems = []
    deps = {}
    for t in tasks:
        for d in t.get("depends_on", []):
            if d not in ids:
                problems.append(f"{t['key']}: unknown dep {d}")
            else:
                deps.setdefault(t["key"], set()).add(d)
    # cycle detection (DFS)
    state = {}

    def visit(node):
        if state.get(node) == 1:
            problems.append(f"cycle at {node}")
            return
        if state.get(node) == 2:
            return
        state[node] = 1
        for d in deps.get(node, ()):
            visit(d)
        state[node] = 2

    for t in tasks:
        visit(t["key"])
    return not problems, {"problems": problems[:5]}


def plan_requirement_coverage(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    reqs = {r for r in (data.get("requirement_ids") or [])}
    covered = set()
    for t in (data.get("tasks") or []):
        covered |= set(t.get("covers") or [])
    missing = reqs - covered
    return not missing, {"missing": sorted(missing)}


def plan_rollback_and_verification(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    tasks = data.get("tasks") or []
    no_verify = [t["key"] for t in tasks
                 if not (t.get("verification") and t.get("rollback"))]
    return not no_verify, {"tasks_without_verify_or_rollback": no_verify}


def plan_scope_discipline(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    out_of_scope = [t["key"] for t in (data.get("tasks") or [])
                    if t.get("out_of_scope")]
    return not out_of_scope, {"out_of_scope_tasks": out_of_scope}


# -- Execution stage ---------------------------------------------------------
def execution_gateway_adherence(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    acts = data.get("activities") or []
    bypass = [a["id"] for a in acts
              if a.get("effect") and not a.get("gateway_recorded")]
    unclassified = [a["id"] for a in acts
                    if a.get("effect") and a.get("gateway_recorded")
                    and not a.get("effect_class")]
    ok = not bypass and not unclassified
    return ok, {"bypassed_gateway": bypass, "unclassified": unclassified}


def execution_worker_failure_semantics(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    runs = data.get("runs") or []
    wrong = [r["id"] for r in runs
             if r.get("worker_failed")
             and (r.get("status") != "FAILED"
                  or r.get("terminal_reason", "").startswith("success"))]
    return not wrong, {"misrecorded_failures": wrong}


def execution_checkpoint_integrity(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    cps = data.get("checkpoints") or []
    runs = data.get("runs") or []
    bad = [c["id"] for c in cps
           if not c.get("sha256") or c.get("verified") is False]
    # a multi-step run without ANY recorded checkpoint has no integrity
    # evidence at all (fail-closed)
    if runs and len(runs) > 0 and len(cps) == 0:
        bad.append("<none-recorded>")
    return not bad, {"bad_checkpoints": bad}


def execution_no_unconfirmed_terminal(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    runs = data.get("runs") or []
    bad = [r["id"] for r in runs
           if r.get("status") == "COMPLETED" and not r.get("confirmed_by_gate")]
    return not bad, {"unconfirmed_completions": bad}


# -- Verification stage -------------------------------------------------------
def verification_artifact_conformity(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    arts = data.get("artifacts") or []
    # conformity is judged over artifacts the pipeline ACCEPTED; a rejected
    # nonconforming artifact is correct behaviour, not a violation.
    accepted_nonconf = [a["id"] for a in arts
                        if a.get("accepted", True)
                        and not a.get("conforms_to_spec")]
    return not accepted_nonconf, {"nonconforming_accepted": accepted_nonconf,
                                  "checked": len(arts)}


def verification_audit_integrity(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    audit = data.get("audit") or {}
    ok = audit.get("chain_verified") is True and audit.get(
        "anchor_matches") is True
    return ok, {"chain_verified": audit.get("chain_verified"),
                "anchor_matches": audit.get("anchor_matches")}


def verification_false_accept_probe(case: dict) -> tuple[bool, dict]:
    """A near-miss artifact must be REJECTED — evaluator FNR probe."""
    data = _load(case)["payload"]
    accepted_despite_gap = [
        a["id"] for a in (data.get("artifacts") or [])
        if a.get("known_gap") and a.get("accepted")]
    return not accepted_despite_gap, {"false_accepts": accepted_despite_gap}


def verification_holdout_independence(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    holdout = data.get("holdout") or {}
    ok = (holdout.get("separate_corpus") is True
          and holdout.get("hash_recorded") is True
          and holdout.get("agent_access") == "none")
    return ok, {"holdout": holdout}


# -- Post-episode stage -----------------------------------------------------
def post_calibration(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    judged = data.get("judged_outcomes") or []
    mismatches = [j["episode"] for j in judged
                  if j.get("predicted") != j.get("actual")]
    rate_ok = len(mismatches) <= max(1, len(judged) // 3)
    return rate_ok, {"mismatches": mismatches, "judged": len(judged)}


def post_root_cause_taxonomy(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    causes = data.get("failures") or []
    unclassified = [f["id"] for f in causes if not f.get("cause_class")]
    known = {"provider", "capability", "evaluator", "policy",
             "specification", "infrastructure"}
    unknown = [f["id"] for f in causes
               if f.get("cause_class") not in known]
    return not unclassified and not unknown, {
        "unclassified": unclassified, "unknown_classes": unknown}


def post_next_hypothesis_single(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    hyps = data.get("next_hypotheses") or []
    testable = [h for h in hyps if h.get("measurable_prediction")]
    return len(testable) == 1, {"hypotheses": len(hyps),
                                "testable": len(testable)}


def post_recurring_patterns(case: dict) -> tuple[bool, dict]:
    data = _load(case)["payload"]
    hist = data.get("failure_history") or []
    cur = data.get("failures") or []
    classes_now = {f.get("cause_class") for f in cur}
    repeat = [c for c in classes_now
              if sum(1 for h in hist if h.get("cause_class") == c) >= 2]
    # recurring patterns MUST be flagged
    flagged = bool(data.get("recurring_pattern_flagged")) or not repeat
    return flagged, {"recurring": sorted(repeat),
                     "flagged": data.get("recurring_pattern_flagged", False)}


# registry used by fixtures/tests: metric name -> fn
CHECKS = {
    "concept.clarity": concept_clarity,
    "concept.measurability": concept_measurability,
    "concept.scope_constraints": concept_scope_constraints,
    "concept.contradictions": concept_contradictions,
    "specification.traceability": spec_traceability,
    "specification.case_coverage": spec_case_coverage,
    "specification.criteria_checkable": spec_criteria_checkable,
    "specification.gaming_resistance": spec_gaming_resistance,
    "plan.dag_validity": plan_dag_validity,
    "plan.requirement_coverage": plan_requirement_coverage,
    "plan.rollback_verification": plan_rollback_and_verification,
    "plan.scope_discipline": plan_scope_discipline,
    "execution.gateway_adherence": execution_gateway_adherence,
    "execution.worker_failure_semantics": execution_worker_failure_semantics,
    "execution.checkpoint_integrity": execution_checkpoint_integrity,
    "execution.no_unconfirmed_terminal": execution_no_unconfirmed_terminal,
    "verification.artifact_conformity": verification_artifact_conformity,
    "verification.audit_integrity": verification_audit_integrity,
    "verification.false_accept_probe": verification_false_accept_probe,
    "verification.holdout_independence": verification_holdout_independence,
    "post_episode.calibration": post_calibration,
    "post_episode.root_cause_taxonomy": post_root_cause_taxonomy,
    "post_episode.next_hypothesis_single": post_next_hypothesis_single,
    "post_episode.recurring_patterns": post_recurring_patterns,
}
