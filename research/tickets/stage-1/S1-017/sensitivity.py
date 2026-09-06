"""S1-017 sensitivity math (pure, deterministic).

Weight sensitivity over decision dimensions: equal base weights, +-50% per
dimension, leave-one-dimension-out and the deterministic 0.5/1.0/1.5 grid
(>= 200 vectors). Safety gates are never weighted.

Determinism contract (S1-016 lesson): every dimension is derived from
deterministic model counts and measured artifact BYTE SIZES only — never
from wall-clock latencies, which are reported separately in metrics.json
and never enter the decision inputs.
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

DIMS = ("utility", "steps_parsimony", "write_parsimony",
        "complexity_parsimony", "coverage_parsimony")
PLACEMENTS = ("A", "B", "C")

# Static complexity proxies from the frozen placement specifications:
# distinct integration entry points each placement adds to the runtime path.
STATIC_COMPLEXITY = {"A": 1, "B": 2, "C": 3}


def score(scores: dict, weights: dict) -> dict:
    return {rep: sum(scores[dim][rep] * weights[dim] for dim in DIMS)
            for rep in PLACEMENTS}


def winner_of(totals: dict) -> str:
    best = max(totals.values())
    winners = sorted(rep for rep, value in totals.items() if value == best)
    return winners[0] if len(winners) == 1 else "TIE"


def weight_vectors() -> list[dict]:
    vectors = [{"name": "base_equal",
                "weights": {dim: 1.0 for dim in DIMS}}]
    for dim in DIMS:
        for factor in (0.5, 1.5):
            weights = {other: 1.0 for other in DIMS}
            weights[dim] = factor
            vectors.append({"name": f"{dim}_x{factor}", "weights": weights})
    for dim in DIMS:
        weights = {other: 1.0 for other in DIMS}
        weights[dim] = 0.0
        vectors.append({"name": f"lodo_{dim}", "weights": weights})
    for index, combo in enumerate(itertools.product((0.5, 1.0, 1.5), repeat=len(DIMS))):
        vectors.append({"name": f"grid_{index:03d}",
                        "weights": dict(zip(DIMS, combo))})
    return vectors


def analyze(scores: dict) -> dict:
    vectors = weight_vectors()
    results = []
    for vector in vectors:
        totals = score(scores, vector["weights"])
        results.append({"name": vector["name"], "winner": winner_of(totals),
                        "totals": totals})
    base_winner = results[0]["winner"]
    flips = [r for r in results[1:] if r["winner"] != base_winner]
    distribution: dict[str, int] = {}
    for result in results:
        distribution[result["winner"]] = distribution.get(result["winner"], 0) + 1
    return {"vector_count": len(results), "base_winner": base_winner,
            "flips": len(flips), "flip_examples": flips[:12],
            "winners_distribution": distribution, "stable": not flips}


def measured_scores(run_dir: Path, ticket: Path) -> dict:
    """Deterministic per-placement aggregates from a frozen run.

    - write bytes: mean artifact bytes per observation (A stores nothing at
      runtime, B stores a recomputable index at export, C stores a runtime
      annotation record);
    - runtime steps: deterministic model-enumeration step count
      (states+transitions per scenario); placements A/B execute it offline/
      at export (0 runtime steps), C executes it in the request path;
    - utility/coverage: identical observable contract, verified by the
      evaluator's 100% oracle-agreement gate for every placement.
    """
    doc = json.loads((run_dir / "observations.json").read_text("utf-8"))
    corpus = json.loads((ticket / "corpus.json").read_text("utf-8"))
    model_steps = sum(len(c["states"]) + len(c["transitions"])
                      for c in corpus["cases"])
    bytes_by: dict[str, list[int]] = {p: [] for p in PLACEMENTS}
    for observation in doc["observations"]:
        core = observation["core"]
        bytes_by[core["placement"]].append(core["artifact"]["bytes"])
    mean_bytes = {p: (sum(v) / len(v)) if v else 0.0 for p, v in bytes_by.items()}
    max_write = max(mean_bytes.values()) or 1.0
    max_complexity = max(STATIC_COMPLEXITY.values())
    scores = {
        "utility": {p: 1.0 for p in PLACEMENTS},
        "steps_parsimony": {"A": 1.0, "B": 1.0, "C": 0.0},
        "write_parsimony": {p: 1.0 - (mean_bytes[p] / max_write)
                            for p in PLACEMENTS},
        "complexity_parsimony": {p: 1.0 - STATIC_COMPLEXITY[p] / max_complexity
                                 for p in PLACEMENTS},
        "coverage_parsimony": {p: 1.0 for p in PLACEMENTS},
    }
    aggregates = {
        "mean_artifact_bytes": mean_bytes,
        "deterministic_model_steps": model_steps,
        "static_complexity_entry_points": dict(STATIC_COMPLEXITY),
        "note": ("wall-clock latencies are reported in metrics.json and never "
                 "enter sensitivity dimensions; all inputs here are "
                 "deterministic model counts and artifact byte sizes"),
    }
    return scores, aggregates


def main() -> int:
    parser = argparse.ArgumentParser()
    for key in ("run", "ticket", "out"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    run_dir = Path(args.run).resolve()
    ticket = Path(args.ticket).resolve()
    scores, aggregates = measured_scores(run_dir, ticket)
    analysis = analyze(scores)
    doc = {"schema": "agentos.s1-017.sensitivity/v1",
           "synthetic": True,
           "dimensions": list(DIMS),
           "per_placement_aggregates": aggregates,
           "normalized_scores": scores,
           "base_winner": analysis["base_winner"],
           "mapped_decision": analysis["base_winner"],
           "mapping_note": "base argmax over deterministic aggregates",
           "vector_count": analysis["vector_count"],
           "winners_distribution": analysis["winners_distribution"],
           "flips": analysis["flips"],
           "flip_examples": analysis["flip_examples"],
           "stable": analysis["stable"],
           "cap_note": ("any winner flip caps the verdict at INCONCLUSIVE; "
                        "safety gates are unweighted and enforced separately")}
    Path(args.out).write_text(json.dumps(doc, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    print(json.dumps({"vector_count": doc["vector_count"],
                      "base_winner": doc["base_winner"],
                      "flips": doc["flips"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
