"""S1-018 sensitivity math (pure functions, Phase A).

Weight sensitivity over decision dimensions: equal base weights, +-50% per
dimension, leave-one-dimension-out, and a deterministic seeded composition
fill guaranteeing at least 200 valid vectors. Safety gates are never
weighted. The full measured run happens in a later phase.
"""
from __future__ import annotations

import itertools

DIMS = ("utility", "bytes_parsimony", "write_parsimony",
        "complexity_parsimony", "coverage_parsimony")
PLACEMENTS = ("A", "B", "C")

# Determinism contract (S1-016/S1-018 lesson): every dimension is derived
# from deterministic model counts and canonical artifact byte sizes only —
# never from wall-clock latencies, which are reported separately in
# metrics.json and never enter the decision inputs.


def score(scores: dict, weights: dict) -> dict:
    return {rep: sum(scores[dim][rep] * weights[dim] for dim in DIMS)
            for rep in PLACEMENTS}


def winner_of(totals: dict) -> str:
    best = max(totals.values())
    winners = sorted(rep for rep, value in totals.items() if value == best)
    return winners[0] if len(winners) == 1 else "TIE"


def _seeded_weights(count: int, dims: list[str]) -> list[dict]:
    """Deterministic LCG compositions in [0.5, 1.5]^d (fixed seed 18018)."""
    state = 18018
    vectors = []
    for _ in range(count):
        weights = {}
        for dim in dims:
            state = (1103515245 * state + 12345) % (2 ** 31)
            weights[dim] = 0.5 + (state / (2 ** 31)) * 1.0
        vectors.append(weights)
    return vectors


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
    seen = {tuple(sorted(v["weights"].items())) for v in vectors}
    extra = 0
    for weights in _seeded_weights(400, list(DIMS)):
        key = tuple(sorted(weights.items()))
        if key in seen:
            continue
        seen.add(key)
        vectors.append({"name": f"seeded_{extra:03d}", "weights": weights})
        extra += 1
        if len(vectors) >= 260:
            break
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
