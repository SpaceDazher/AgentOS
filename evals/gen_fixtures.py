"""Generate the frozen stage-eval fixture corpora.

48 stage fixtures: 6 stages x 8 cases
  (2 valid/gold, 2 incomplete, 2 near-miss, 1 alternative-correct, 1 adversarial)
30 evaluator-quality fixtures: 10 gold + 10 near_miss + 10 alternative_correct

Usage:
    python -m evals.gen_fixtures           # writes evals/fixtures/...
    python -m evals.gen_fixtures --check   # verify corpus hashes only
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures"

STAGE_PLAN = [("gold", True, 0), ("gold", True, 1),
              ("incomplete", False, 0), ("incomplete", False, 1),
              ("near_miss", False, 0), ("near_miss", False, 1),
              ("alternative_correct", False, 0),
              ("adversarial", False, 0)]


# per-stage payload builders --------------------------------------------------
def _concept(good: bool, variant: int, set_class: str) -> dict:
    if good:
        return {"goal_statement": "Build a tiny greeting library",
                "concept_text": " ".join(["word"] * 20),
                "acceptance_criteria": [{"kind": "tests_present"}],
                "scope": "one module", "constraints": ["stdlib"],
                "stop_conditions": ["gate pass"],
                "requirements": ["module must expose greet"]}
    if set_class == "incomplete":
        base = {"goal_statement": "", "concept_text": "short",
                "acceptance_criteria": [], "scope": None,
                "constraints": None, "stop_conditions": None}
        if variant == 0:
            return base
        return {**base, "goal_statement": "x",
                "concept_text": " ".join(["w"] * 30)}
    if set_class == "near_miss":
        p = {"goal_statement": "G", "concept_text": " ".join(["w"] * 25),
             "acceptance_criteria": [{"kind": "tests_present"}],
             "scope": "m", "constraints": ["c"], "stop_conditions": None,
             "requirements": ["r1"]}
        if variant == 0:
            return p
        return {**p, "scope": None}
    if set_class == "alternative_correct":
        return {"goal_statement": "Greeting lib with CLI too",
                "concept_text": " ".join(["word"] * 40),
                "acceptance_criteria": [{"kind": "command_exit_0"},
                                        {"kind": "metric_threshold"}],
                "scope": "module + cli", "constraints": ["no network"],
                "stop_conditions": ["budget"], "requirements":
                    ["greet", "cli"]}
    return {"goal_statement": "G", "concept_text": " ".join(["w"] * 15),
            "acceptance_criteria": [{"kind": "self_report"}],
            "scope": "everything", "constraints": [], "stop_conditions": [],
            "explicit_contradiction": True,
            "requirements": ["must not use network",
                             "must use network for speed"]}


def _spec(good: bool, variant: int, set_class: str) -> dict:
    reqs = [{"id": "R1"}, {"id": "R2"}]
    crits = [{"id": "C1", "requirement_id": "R1", "kind": "tests_present"},
             {"id": "C2", "requirement_id": "R2", "kind": "invariant"}]
    if good:
        return {"requirements": reqs, "acceptance_criteria": crits,
                "test_kinds": ["positive", "negative", "edge"]}
    if set_class == "incomplete":
        if variant == 0:
            return {"requirements": reqs, "acceptance_criteria": [crits[0]],
                    "test_kinds": ["positive"]}
        return {"requirements": reqs, "acceptance_criteria": crits,
                "test_kinds": ["positive", "negative"]}
    if set_class == "near_miss":
        c = [dict(x) for x in crits]
        c[1]["kind"] = "manual_review"
        return {"requirements": reqs, "acceptance_criteria": c,
                "test_kinds": ["positive", "negative", "edge"]}
    if set_class == "alternative_correct":
        alt = [{"id": "C1", "requirement_id": "R1", "kind": "command_exit_0"},
               {"id": "C2", "requirement_id": "R2", "kind": "metric_threshold"},
               {"id": "C3", "requirement_id": "R2", "kind": "tests_present"}]
        return {"requirements": reqs, "acceptance_criteria": alt,
                "test_kinds": ["positive", "negative", "edge", "property"]}
    return {"requirements": reqs, "acceptance_criteria": [
        {"id": "C1", "requirement_id": "R1", "kind": "self_report"},
        {"id": "C2", "requirement_id": "R2", "kind": "agent_claim"}],
        "test_kinds": ["positive"]}


def _plan(good: bool, variant: int, set_class: str) -> dict:
    tasks = [{"key": "t1", "depends_on": [], "covers": ["R1"],
              "verification": "unit", "rollback": "drop"},
             {"key": "t2", "depends_on": ["t1"], "covers": ["R2"],
              "verification": "gate", "rollback": "supersede"}]
    if good:
        return {"tasks": tasks, "requirement_ids": ["R1", "R2"]}
    if set_class == "incomplete":
        if variant == 0:
            t = [dict(t) for t in tasks]
            t[0]["covers"] = []
            return {"tasks": t, "requirement_ids": ["R1", "R2"]}
        t = [{k: v for k, v in task.items() if k != "rollback"}
             for task in tasks]
        return {"tasks": t, "requirement_ids": ["R1", "R2"]}
    if set_class == "near_miss":
        t = [dict(t) for t in tasks]
        t.append({"key": "t3", "depends_on": ["nope"], "covers": ["R1"],
                  "verification": "v", "rollback": "r"})
        return {"tasks": t, "requirement_ids": ["R1", "R2"]}
    if set_class == "alternative_correct":
        lin = [{"key": "a", "depends_on": [], "covers": ["R1", "R2"],
                "verification": "gate", "rollback": "reset"}]
        return {"tasks": lin, "requirement_ids": ["R1", "R2"]}
    cyc = [{"key": "a", "depends_on": ["b"], "covers": ["R1"],
            "verification": "v", "rollback": "r", "out_of_scope": True},
           {"key": "b", "depends_on": ["a"], "covers": ["R2"],
            "verification": "v", "rollback": "r"}]
    return {"tasks": cyc, "requirement_ids": ["R1", "R2"]}


def _exec(good: bool, variant: int, set_class: str) -> dict:
    acts = [{"id": "A1", "effect": True, "gateway_recorded": True,
             "effect_class": "write_local"},
            {"id": "A2", "effect": False, "gateway_recorded": True}]
    runs = [{"id": "R1", "worker_failed": False, "status": "COMPLETED",
             "terminal_reason": "success", "confirmed_by_gate": True}]
    cps = [{"id": "CP1", "sha256": "abc", "verified": True}]
    if good:
        return {"activities": acts, "runs": runs, "checkpoints": cps}
    if set_class == "incomplete":
        if variant == 0:
            a = [dict(a) for a in acts]
            a[0]["gateway_recorded"] = False
            return {"activities": a, "runs": runs, "checkpoints": cps}
        return {"activities": acts, "runs": runs, "checkpoints": []}
    if set_class == "near_miss":
        r = [dict(r) for r in runs]
        r.append({"id": "R2", "worker_failed": True, "status": "COMPLETED",
                  "terminal_reason": "success", "confirmed_by_gate": False})
        return {"activities": acts, "runs": r, "checkpoints": cps}
    if set_class == "alternative_correct":
        r2 = [{"id": "R1", "worker_failed": True, "status": "FAILED",
               "terminal_reason": "worker: retry scheduled",
               "confirmed_by_gate": False},
              {"id": "R2", "worker_failed": False, "status": "COMPLETED",
               "terminal_reason": "success", "confirmed_by_gate": True}]
        return {"activities": acts, "runs": r2, "checkpoints": cps}
    bad_runs = [{"id": "R1", "worker_failed": False, "status": "COMPLETED",
                 "terminal_reason": "success", "confirmed_by_gate": False}]
    return {"activities": acts, "runs": bad_runs, "checkpoints": cps}


def _verif(good: bool, variant: int, set_class: str) -> dict:
    audit = {"chain_verified": True, "anchor_matches": True}
    holdout = {"separate_corpus": True, "hash_recorded": True,
               "agent_access": "none"}
    arts = [{"id": "V1", "conforms_to_spec": True}]
    if good:
        return {"artifacts": arts, "audit": audit, "holdout": holdout}
    if set_class == "incomplete":
        if variant == 0:
            return {"artifacts": arts,
                    "audit": {"chain_verified": False, "anchor_matches": True},
                    "holdout": holdout}
        return {"artifacts": arts, "audit": audit,
                "holdout": {"separate_corpus": False,
                            "hash_recorded": False, "agent_access": "agent"}}
    if set_class == "near_miss":
        a = arts + [{"id": "V2", "conforms_to_spec": True, "known_gap": True,
                     "accepted": True}]
        return {"artifacts": a, "audit": audit, "holdout": holdout}
    if set_class == "alternative_correct":
        # alternative route: one artifact intentionally rejected (correctly
        # handled) — conformity is judged over ACCEPTED artifacts only
        a = arts + [{"id": "V2", "conforms_to_spec": False,
                     "accepted": False}]
        return {"artifacts": a, "audit": audit, "holdout": holdout}
    return {"artifacts": arts,
            "audit": {"chain_verified": True, "anchor_matches": False},
            "holdout": holdout}


def _post(good: bool, variant: int, set_class: str) -> dict:
    judged = [{"episode": "e1", "predicted": "pass", "actual": "pass"},
              {"episode": "e2", "predicted": "pass", "actual": "pass"},
              {"episode": "e3", "predicted": "fail", "actual": "fail"}]
    failures = [{"id": "f1", "cause_class": "capability"}]
    hist = [{"cause_class": "capability"}, {"cause_class": "provider"}]
    if good:
        return {"judged_outcomes": judged, "failures": failures,
                "failure_history": hist,
                "next_hypotheses": [{"measurable_prediction": "+2% pass^1"}],
                "recurring_pattern_flagged": False}
    if set_class == "incomplete":
        if variant == 0:
            f = failures + [{"id": "f2"}]
            return {"judged_outcomes": judged, "failures": f,
                    "failure_history": hist, "next_hypotheses": []}
        h = [{"measurable_prediction": None},
             {"measurable_prediction": "x"}, {"measurable_prediction": "y"}]
        return {"judged_outcomes": judged, "failures": failures,
                "failure_history": hist, "next_hypotheses": h}
    if set_class == "near_miss":
        j = judged + [{"episode": "e4", "predicted": "pass", "actual": "fail"},
                      {"episode": "e5", "predicted": "pass",
                       "actual": "fail"}]
        return {"judged_outcomes": j, "failures": failures,
                "failure_history": hist,
                "next_hypotheses": [{"measurable_prediction": "x"}]}
    if set_class == "alternative_correct":
        return {"judged_outcomes": judged,
                "failures": failures + [{"id": "f2",
                                         "cause_class": "provider"}],
                "failure_history": hist,
                "next_hypotheses": [{"measurable_prediction": "-5% latency"}],
                "recurring_pattern_flagged": True}
    return {"judged_outcomes": judged,
            "failures": [{"id": "f1", "cause_class": "capability"}],
            "failure_history": [{"cause_class": "capability"}] * 3,
            "next_hypotheses": [{"measurable_prediction": "x"}],
            "recurring_pattern_flagged": False}


BUILDERS = {
    "concept": _concept, "specification": _spec, "plan": _plan,
    "execution": _exec, "verification": _verif, "post_episode": _post,
}

# which checks apply to which stage (metric suffixes)
STAGE_CHECKS = {
    "concept": ["clarity", "measurability", "scope_constraints",
                "contradictions"],
    "specification": ["traceability", "case_coverage",
                      "criteria_checkable", "gaming_resistance"],
    "plan": ["dag_validity", "requirement_coverage",
             "rollback_verification", "scope_discipline"],
    "execution": ["gateway_adherence", "worker_failure_semantics",
                  "checkpoint_integrity", "no_unconfirmed_terminal"],
    "verification": ["artifact_conformity", "audit_integrity",
                     "false_accept_probe", "holdout_independence"],
    "post_episode": ["calibration", "root_cause_taxonomy",
                     "next_hypothesis_single", "recurring_patterns"],
}


def expected_pass(set_class: str, good: bool) -> bool:
    """gold and alternative_correct expect pass; others expect fail."""
    return good or set_class == "alternative_correct"


def build_corpus() -> list[tuple[dict, dict]]:
    cases: list[tuple[dict, dict]] = []
    for stage, builder in BUILDERS.items():
        for set_class, good, variant in STAGE_PLAN:
            payload = builder(good, variant, set_class)
            ok = expected_pass(set_class, good)
            cid = f"{stage}-{set_class}-{variant}"
            rec = {
                "id": cid, "corpus_version": "stage-v1", "stage": stage,
                "label": f"{stage} {set_class} #{variant}",
                "set_class": set_class,
                "input_ref": f"evals/fixtures/stage/{stage}/{cid}.json",
                "expected_outcome": "pass" if ok else "fail",
                "provenance": {"generator": "evals.gen_fixtures v1"},
                "_checks": STAGE_CHECKS[stage], "_expect_all_pass": ok,
            }
            cases.append((rec, {"payload": payload}))
    # evaluator-quality corpus (verification-shaped)
    # evaluator-quality corpus (verification-shaped): 10 DISTINCT templates
    # per class, not one repeated template (R5-P2)
    def _eq_doc(i: int, sc: str, good: bool) -> dict:
        """Ten distinct artifact shapes; near-miss variants each carry a
        different realistic gap."""
        main = {"id": cid + "-main", "conforms_to_spec": True}
        gaps = [
            {"id": cid + "-gap", "conforms_to_spec": False,
             "accepted": True},                                   # wrong impl accepted
            {"id": cid + "-gap", "conforms_to_spec": True,
             "known_gap": "no edge-case tests", "accepted": True},  # thin tests
            {"id": cid + "-gap", "conforms_to_spec": True,
             "known_gap": "tests never executed", "accepted": True},
            {"id": cid + "-gap", "conforms_to_spec": True,
             "known_gap": "accepts invalid input", "accepted": True},
            {"id": cid + "-gap", "conforms_to_spec": True,
             "known_gap": "wrong return type", "accepted": True},
            {"id": cid + "-gap", "conforms_to_spec": True,
             "known_gap": "swallowed exception", "accepted": True},
            {"id": cid + "-gap", "conforms_to_spec": True,
             "known_gap": "off-by-one on empty input", "accepted": True},
            {"id": cid + "-gap", "conforms_to_spec": True,
             "known_gap": "ignores unicode", "accepted": True},
            {"id": cid + "-gap", "conforms_to_spec": True,
             "known_gap": "no rollback path", "accepted": True},
            {"id": cid + "-gap", "conforms_to_spec": True,
             "known_gap": "checkpoint hash absent", "accepted": True},
        ]
        arts = [dict(main)]
        if not good:
            arts.append(gaps[i % len(gaps)])
        # alternative-correct adds a properly REJECTED nonconforming artifact
        if good and sc == "alternative_correct":
            arts.append({"id": cid + "-rejected",
                         "conforms_to_spec": False, "accepted": False})
        return {"payload": {
            "artifacts": arts,
            "audit": {"chain_verified": i % 2 == 0 or good,
                      "anchor_matches": True}}}

    eq_specs = ([("eq-gold-%d" % i, "gold", True) for i in range(10)] +
                [("eq-near-miss-%d" % i, "near_miss", False)
                 for i in range(10)] +
                [("eq-alt-%d" % i, "alternative_correct", True)
                 for i in range(10)])
    for cid, sc, good in eq_specs:
        doc = _eq_doc(int(cid.rsplit("-", 1)[1]), sc, good)
        rec = {
            "id": cid, "corpus_version": "eq-v1", "stage": "verification",
            "label": f"evaluator quality {sc}", "set_class": sc,
            "input_ref": f"evals/fixtures/eq/{cid}.json",
            "expected_outcome": "pass" if good else "fail",
            "provenance": {"generator": "evals.gen_fixtures v1"},
            "_checks": ["artifact_conformity", "false_accept_probe"],
            "_expect_all_pass": good,
        }
        cases.append((rec, doc))
    return cases


def write_all() -> dict:
    pairs = build_corpus()
    man_cases = {}
    for rec, doc in pairs:
        p = ROOT / rec["input_ref"]
        p.parent.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(doc, indent=2, sort_keys=True)
        # write bytes (LF) so the recorded hash is platform-independent
        data = blob.encode("utf-8")
        p.write_bytes(data)
        man_cases[rec["id"]] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "stage": rec["stage"], "set_class": rec["set_class"],
            "expected_outcome": rec["expected_outcome"],
            "input_ref": rec["input_ref"],
        }
    manifest = {"schema": "agentos.eval-corpus/v1",
                "corpus_versions": {"stage": "stage-v1", "eq": "eq-v1"},
                "cases": man_cases}
    (ROOT / "evals" / "corpus_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    n_stage = sum(1 for r, _ in pairs if r["corpus_version"] == "stage-v1")
    n_eq = len(pairs) - n_stage
    return {"written": len(pairs), "stage_cases": n_stage, "eq_cases": n_eq}


def main() -> int:
    if "--check" in sys.argv:
        man = json.loads((ROOT / "evals" / "corpus_manifest.json")
                         .read_text(encoding="utf-8"))
        bad = []
        for cid, info in man["cases"].items():
            p = ROOT / info["input_ref"]
            if not p.exists():
                bad.append([cid, "missing"])
                continue
            if hashlib.sha256(p.read_bytes()).hexdigest() != info["sha256"]:
                bad.append([cid, "hash mismatch"])
        print(json.dumps({"checked": len(man["cases"]), "violations": bad}))
        return 1 if bad else 0
    print(json.dumps(write_all()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
