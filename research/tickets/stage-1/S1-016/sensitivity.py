"""S1-016 sensitivity analysis: deterministic weight robustness of the winner.

Safety gates are never weighted. Dimensions (all measured, higher is better):
utility (reconstruction rate + query efficiency), state/storage/constraint/
latency/implementation parsimony. Base weights equal; perturbations +-50%
per dimension, leave-one-dimension-out, and the full deterministic 0.5/1/1.5
grid (729 vectors). Any winner flip is recorded and caps the verdict.
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _mod(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = _mod("s1016_contract_sens", "contract.py")
models = _mod("s1016_models_sens", "models.py")

DIMS = ("utility", "state_parsimony", "storage_parsimony",
        "constraint_parsimony", "latency_parsimony", "implementation_parsimony")
REPS = ("A", "B", "C")


def load_json(path: Path):
    return contract.loads(path.read_text(encoding="utf-8"))


def per_rep_aggregates(observations: list, metrics: dict) -> dict:
    agg: dict[str, dict] = {}
    for rep in REPS:
        cells = [o["core"] for o in observations
                 if o["core"].get("representation") == rep
                 and o["core"].get("status") == "ok"]
        rows = sum(sum(c.get("state_rows", {}).get(k, 0) for k in
                       ("versions", "memberships", "operations", "events"))
                   for c in cells)
        num_bytes = sum(c.get("state_bytes", 0) for c in cells)
        checks = sum(c.get("complexity", {}).get("checks_executed", 0) for c in cells)
        steps = sum(c.get("query_probe", {}).get("steps", 0) for c in cells)
        queries = sum(c.get("query_probe", {}).get("queries", 0) for c in cells)
        lat = sorted(o.get("latencies", {}).get("export_ns", 0)
                     for o in observations
                     if o["core"].get("representation") == rep
                     and o["core"].get("status") == "ok")
        p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else 0
        recon = metrics["rates"]["audit_reconstruction"]["rate"]
        agg[rep] = {"rows": rows, "bytes": num_bytes, "checks": checks,
                    "steps": steps, "queries": queries, "latency_p95_ns": p95,
                    "reconstruction_rate": recon if recon is not None else 0.0,
                    "static": {"tables": models.TABLE_COUNTS[rep],
                               "constraints": models.CONSTRAINT_COUNTS[rep],
                               "entry_points": models.QUERY_ENTRY_POINTS[rep]}}
    return agg


def normalize_scores(agg: dict) -> dict:
    def inv(values: dict) -> dict:
        top = max(values.values()) or 1
        return {rep: 1.0 - values[rep] / top for rep in REPS}

    query_eff = {}
    for rep in REPS:
        per_query = agg[rep]["steps"] / max(1, agg[rep]["queries"])
        query_eff[rep] = 1.0 / (1.0 + math.log10(1.0 + per_query))
    utility = {rep: 0.5 * agg[rep]["reconstruction_rate"] + 0.5 * query_eff[rep]
               for rep in REPS}
    static_cost = {rep: (agg[rep]["static"]["tables"]
                         + agg[rep]["static"]["constraints"]
                         + agg[rep]["static"]["entry_points"]) for rep in REPS}
    return {
        "utility": utility,
        "state_parsimony": inv({rep: agg[rep]["rows"] for rep in REPS}),
        "storage_parsimony": inv({rep: agg[rep]["bytes"] for rep in REPS}),
        "constraint_parsimony": inv({rep: agg[rep]["checks"] for rep in REPS}),
        "latency_parsimony": inv({rep: agg[rep]["latency_p95_ns"] for rep in REPS}),
        "implementation_parsimony": inv(static_cost),
    }


def score(scores: dict, weights: dict) -> dict:
    return {rep: sum(scores[dim][rep] * weights[dim] for dim in DIMS) for rep in REPS}


def winner_of(totals: dict) -> str:
    best = max(totals.values())
    winners = sorted(rep for rep, value in totals.items() if value == best)
    return winners[0] if len(winners) == 1 else "TIE"


def analyze(run_dir: Path, ticket: Path, metrics_path: Path | None = None):
    observations = load_json(run_dir / "observations.json")["observations"]
    if metrics_path is None:
        candidate = run_dir.parent / "metrics.json"
        metrics_path = candidate if candidate.exists() else run_dir / "metrics.json"
    metrics = load_json(metrics_path)
    agg = per_rep_aggregates(observations, metrics)
    scores = normalize_scores(agg)
    base_weights = {dim: 1.0 for dim in DIMS}
    base_totals = score(scores, base_weights)
    base_winner = winner_of(base_totals)
    vectors = [{"name": "base_equal", "weights": dict(base_weights)}]
    for dim in DIMS:
        for factor in (0.5, 1.5):
            weights = dict(base_weights)
            weights[dim] = factor
            vectors.append({"name": f"{dim}_x{factor}", "weights": weights})
    for dim in DIMS:
        weights = dict(base_weights)
        weights[dim] = 0.0
        vectors.append({"name": f"lodo_{dim}", "weights": weights})
    grid = 0
    for combo in itertools.product((0.5, 1.0, 1.5), repeat=len(DIMS)):
        weights = dict(zip(DIMS, combo))
        vectors.append({"name": f"grid_{grid:03d}", "weights": weights})
        grid += 1
    results = []
    for vector in vectors:
        totals = score(scores, vector["weights"])
        results.append({"name": vector["name"], "weights": vector["weights"],
                        "totals": totals, "winner": winner_of(totals)})
    flips = [r for r in results if r["winner"] != base_winner]
    winners_dist: dict[str, int] = {}
    for result in results:
        winners_dist[result["winner"]] = winners_dist.get(result["winner"], 0) + 1
    # Decision-rule mapping on the BASE weights (sensitivity only caps).
    gap = {rep: scores["utility"][rep] - scores["utility"]["A"] for rep in ("B", "C")}
    if base_winner == "B" and gap["B"] <= 1e-9:
        mapped, mapping_note = "A", "B shows no necessary correctness benefit; A wins"
    elif base_winner == "C" and gap["C"] <= 1e-9:
        mapped, mapping_note = "A", "C shows no necessary correctness benefit; A wins"
    else:
        mapped, mapping_note = base_winner, "base argmax stands on measured utility"
    stable = not flips
    return {"schema": "agentos.s1-016.sensitivity/v1", "synthetic": True,
            "dimensions": list(DIMS),
            "per_rep_aggregates": agg,
            "normalized_scores": scores,
            "base_totals": base_totals, "base_winner": base_winner,
            "mapped_decision": mapped, "mapping_note": mapping_note,
            "utility_gaps_vs_A": gap,
            "vector_count": len(results),
            "winners_distribution": winners_dist,
            "flips": len(flips),
            "flip_examples": flips[:12],
            "stable": stable,
            "cap_note": ("any winner flip caps the verdict at INCONCLUSIVE; "
                         "safety gates are unweighted and enforced separately")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--metrics", required=False)
    parser.add_argument("--ticket", required=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run)
    ticket = Path(args.ticket).resolve() if args.ticket else HERE
    # Metrics live next to the run dir (publisher layout: results/metrics.json).
    doc = analyze(run_dir, ticket, Path(args.metrics) if args.metrics else None)
    Path(args.out).write_text(json.dumps(doc, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    print(json.dumps({"vectors": doc["vector_count"], "base_winner": doc["base_winner"],
                      "mapped": doc["mapped_decision"], "flips": doc["flips"],
                      "stable": doc["stable"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
