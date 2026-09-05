"""S1-014 independent evaluator.

Recomputes everything from validated raw observations, the frozen corpus and
the frozen oracle.  It never trusts a producer summary, a displayed variant
label, a saved verdict or cached metrics.  Synthetic/operator observations can
never produce a human N, a winner or a superiority claim.

usage: python evaluator.py <observations_dir> <out_dir> [--executor X --nonce N]
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as c  # noqa: E402

HUMAN_ROLES = ()  # no role in this ticket produces human participant data


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    s = sorted(values)
    return s[len(s) // 2]


def _cell() -> dict:
    return {"n_assigned": 0, "n_presented": 0, "n_submitted": 0, "n_timeout": 0, "n_missing": 0,
            "n_withdrawn": 0, "correct": 0, "incorrect": 0, "unscored_missing": 0,
            "provenance_recall_exact": 0, "provenance_recall_partial": 0, "provenance_recall_none": 0,
            "challenge_seen": 0, "challenge_not_seen": 0, "challenge_missing": 0,
            "overload": {k: 0 for k in c.OVERLOAD_CHOICES}, "times_ms": [], "censored_times_ms": [],
            "disclosure_actions": [], "keyboard_steps": [], "pointer_trials": 0}


def evaluate(observations_dir: Path, ticket: Path = c.TICKET,
             executor: str = "EXEC-EVAL", nonce: str = "0") -> dict:
    disputes = c.load_json(ticket / "task-manifest.json")["disputes"]
    oracle = c.load_json(ticket / "oracle" / "oracle.json")["oracle"]
    frozen = c.load_json(ticket / "prototype" / "browser-contract.json")
    by_id = {d["dispute_id"]: d for d in disputes}
    raw = c.load_json(observations_dir / "observations.json")
    if raw.get("schema") != c.OBSERVATIONS_SCHEMA:
        raise c.ContractError("observations schema mismatch")
    observations = raw["observations"]
    if c.digest(observations) != raw.get("observations_sha256"):
        raise c.ContractError("observations digest mismatch")

    # --- fresh parity / accessibility gates from the frozen contract ----------
    parity = [c.parity_report(d) for d in disputes]
    if frozen["contract_sha256"] != c.browser_contract(disputes)["contract_sha256"]:
        raise c.ContractError("browser contract is not derived from the frozen corpus")
    if any(did in c.canonical(frozen).decode() for did in ()):  # placeholder guard, no-op
        pass
    if "correct_answer" in c.canonical(frozen).decode():
        raise c.ContractError("oracle leaked into browser contract")

    cells: dict[tuple[str, str], dict] = defaultdict(_cell)
    strata: dict[tuple[str, str], dict] = defaultdict(_cell)
    sessions: list[dict] = []
    deviations: list[str] = []
    a11y_failures: list[str] = []
    for obs in observations:
        if obs["contract_sha256"] != frozen["contract_sha256"]:
            raise c.ContractError("observation bound to a different contract")
        if obs["human"] is not False and obs["role"] in HUMAN_ROLES:
            deviations.append(f"{obs['session_id']}: human role encountered; not permitted")
        # trust only the frozen assignment table for the variant label
        assignment = next(a for a in frozen["assignments"]
                          if a["assignment_sha256"] == obs["assignment_sha256"])
        table = {t["position"]: t for t in assignment["trials"]}
        summary = {"session_id": obs["session_id"], "role": obs["role"], "seed": obs["seed"],
                   "executor": obs["executor"], "lifecycle": obs["lifecycle"],
                   "accessibility_mode": obs["accessibility_mode"], "trials": len(obs["trials"])}
        for t in obs["trials"]:
            spec = table[t["position"]]
            variant, did = spec["variant"], spec["dispute_id"]
            if (variant, did) != (t["variant"], t["dispute_id"]):
                deviations.append(f"{obs['session_id']}: displayed label drift at {t['position']}")
            cell = cells[(variant, did)]
            scell = strata[(variant, by_id[did]["complexity_stratum"])]
            for target in (cell, scell):
                target["n_assigned"] += 1
                if t["presented_t_ms"] is not None:
                    target["n_presented"] += 1
                target[f"n_{t['outcome']}"] += 1
                if t["outcome"] in ("submitted", "timeout"):
                    dt = t["submitted_t_ms"] - t["presented_t_ms"]
                    (target["times_ms"] if t["outcome"] == "submitted" else target["censored_times_ms"]).append(dt)
                    target["disclosure_actions"].append(t["disclosure_actions"])
                    target["keyboard_steps"].append(t["keyboard_steps"])
                if t["pointer_used"]:
                    target["pointer_trials"] += 1
                orc = oracle[did]
                if t["answer"] == "__MISSING__":
                    target["unscored_missing"] += 1
                elif t["answer"] == orc["correct_answer"]:
                    target["correct"] += 1
                else:
                    target["incorrect"] += 1
                needed = set(orc["provenance_recall_set"])
                got = set(t["provenance_recall"])
                if got and got == needed:
                    target["provenance_recall_exact"] += 1
                elif got & needed:
                    target["provenance_recall_partial"] += 1
                else:
                    target["provenance_recall_none"] += 1
                key = {"challenge_seen": "challenge_seen", "challenge_not_seen": "challenge_not_seen"}.get(
                    t["challenge_choice"], "challenge_missing")
                target[key] += 1
                target["overload"][t["overload"]] += 1
            if obs["accessibility_mode"] != "pointer" and t["pointer_used"]:
                a11y_failures.append(f"{obs['session_id']}: pointer used in {obs['accessibility_mode']}")
            if obs["accessibility_mode"] == "keyboard_only" and t["outcome"] == "submitted" and t["keyboard_steps"] == 0:
                a11y_failures.append(f"{obs['session_id']}: submitted with zero keyboard steps in keyboard_only")
        sessions.append(summary)

    def finalize(store: dict[tuple[str, str], dict], label: str) -> dict:
        out: dict[str, Any] = {}
        for (variant, key), cell in sorted(store.items()):
            n = cell["n_assigned"]
            entry = dict(cell)
            entry["accuracy_rate_over_assigned"] = (cell["correct"] / n) if n else None
            entry["time_median_ms_submitted_only"] = _median(cell["times_ms"])
            entry["time_median_ms_including_censored"] = _median(cell["times_ms"] + cell["censored_times_ms"])
            entry["disclosure_actions_median"] = _median(cell["disclosure_actions"])
            entry["keyboard_steps_median"] = _median(cell["keyboard_steps"])
            entry["denominator_note"] = "rates use n_assigned; missing/timeout/withdrawn trials are never dropped"
            out.setdefault(variant, {})[key] = entry
        return out

    metrics = {
        "schema": "agentos.s1-014.metrics/v1", "ticket": c.TICKET_ID,
        "executor": executor, "nonce": nonce, "pid": os.getpid(),
        "contract_sha256": frozen["contract_sha256"],
        "observations_sha256": raw["observations_sha256"],
        "human_study_n": 0, "operator_review_n": sum(1 for s in sessions if s["role"] == "operator_design_reviewer"),
        "synthetic_session_n": sum(1 for s in sessions if s["role"] == "synthetic_technical_replay"),
        "comparative_human_effectiveness": "NOT_MEASURED",
        "winner": None, "comparative_claim_status": "FORBIDDEN_NO_HUMAN_STUDY",
        "variants": list(c.VARIANTS), "tasks": [d["dispute_id"] for d in disputes],
        "by_variant_task": finalize(cells, "task"),
        "by_variant_stratum": finalize(strata, "stratum"),
        "sessions": sessions, "protocol_deviations": deviations,
        "gates": {
            "content_parity": all(p["equivalent"] for p in parity),
            "disclosure_symmetry": all(not any("asymmetry" in x for x in p["problems"]) for p in parity),
            "provenance_visible_level0": all(c.information_set(c.render_card(d))["provenance_level0"] and
                                             c.information_set(c.render_graph(d))["provenance_level0"] for d in disputes),
            "challenge_visible_level0": all(c.information_set(c.render_card(d))["challenge_visible_level0"] and
                                            c.information_set(c.render_graph(d))["challenge_visible_level0"] for d in disputes),
            "independence_visible_level0": all(c.information_set(c.render_graph(d))["independence_level0"] for d in disputes),
            "graph_linear_equivalent": all(bool(c.render_graph(d)["level0"]["linear_equivalent"]) for d in disputes),
            "accessibility_failures": a11y_failures,
            "accessibility": not a11y_failures,
            "oracle_absent_from_browser": True,
        },
        "parity": parity,
    }
    metrics["hard_gates_green"] = all(v is True for k, v in metrics["gates"].items()
                                      if k not in ("accessibility_failures",))
    # digest over the replay-invariant part (executor/nonce/pid excluded)
    invariant = {k: v for k, v in metrics.items() if k not in ("executor", "nonce", "pid")}
    metrics["metrics_sha256"] = c.digest(invariant)
    return metrics


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("observations_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--executor", default="EXEC-EVAL")
    ap.add_argument("--nonce", default="0")
    args = ap.parse_args()
    result = evaluate(Path(args.observations_dir), executor=args.executor, nonce=args.nonce)
    c.dump(Path(args.out_dir) / "metrics.json", result)
    print(result["metrics_sha256"])
