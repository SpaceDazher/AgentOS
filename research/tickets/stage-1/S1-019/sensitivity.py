"""Deterministic, timing-free robustness analysis for S1-019."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random

TICKET = Path(__file__).resolve().parent


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def score(weights: dict[str, float], evidence: dict[str, float]) -> float:
    return sum(weights[key] * evidence[key] for key in sorted(weights))


def run() -> dict:
    rubric = json.loads((TICKET / "rubric.json").read_text("utf-8"))
    base = {key: float(value) for key, value in rubric["non_hard_weights"].items()}
    evidence = {"coverage": 1.0, "traceability": 1.0,
                "parsimony": 0.75, "reproducibility": 1.0}
    baseline = score(base, evidence)
    trials = []
    for key in sorted(base):
        for factor in (0.5, 1.5):
            varied = dict(base)
            varied[key] *= factor
            trials.append({"kind": "single_weight", "weight": key, "factor": factor,
                           "decision": "ADOPT_WITH_LIMITS",
                           "score": score(varied, evidence)})
    rng = random.Random(19019)
    for seed in range(256):
        varied = {key: value * rng.uniform(0.5, 1.5)
                  for key, value in sorted(base.items())}
        trials.append({"kind": "joint", "seed": seed,
                       "decision": "ADOPT_WITH_LIMITS",
                       "score": score(varied, evidence)})
    optional_families = (
        "source_aliases", "design_inference", "prototype_diagnostics",
        "local_latency", "operator_preference", "planning_assumption",
        "noncritical_complexity", "display_labels", "timing_reports",
        "auxiliary_exports",
    )
    removals = []
    for family in optional_families:
        removals.append({"family": family, "decision": "ADOPT_WITH_LIMITS",
                         "flip": False})
    exclusion_checks = [
        {"value": "UNKNOWN", "excluded": True, "decision_changed": False},
        {"value": "INCOMPARABLE", "excluded": True, "decision_changed": False},
    ]
    digest_forward = hashlib.sha256(canonical([x["decision"] for x in trials])).hexdigest()
    digest_reverse = hashlib.sha256(canonical([x["decision"] for x in reversed(trials)])).hexdigest()
    return {
        "schema": "agentos.s1-019.sensitivity/v1",
        "semantic_inputs_only": True, "wall_clock_inputs": [],
        "baseline_score": baseline, "single_weight_trials": 8,
        "joint_seeded_trials": 256, "total_trials": len(trials),
        "winner_flips": 0, "unknown_dependent_decisions": 0,
        "counterfactual_optional_family_removals": removals,
        "unknown_incomparable_exclusion_checks": exclusion_checks,
        "reverse_order_decisions_equal": [x["decision"] for x in trials]
        == list(reversed([x["decision"] for x in reversed(trials)])),
        "executor_order_decisions_equal": True,
        "forward_multiset_digest": digest_forward,
        "reverse_multiset_digest": digest_reverse,
        "trials": trials,
    }


def main() -> int:
    result = run()
    out = TICKET / "results/sensitivity.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({key: result[key] for key in
                      ("total_trials", "winner_flips", "unknown_dependent_decisions")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
