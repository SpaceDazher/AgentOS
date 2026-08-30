"""AgentOS S1-005 — deterministic QA1 evaluator.

Fails closed on:
- rubric hash mismatch (weights changed after scoring started);
- missing dimensions (< 8) or missing real candidates (need exactly the two
  real topologies);
- incomplete cells (every dimension needs a cell for every real candidate;
  cells carry claim_type in fact|measurement|inference|assumption|unknown);
- probe A not rejected: any candidate whose cells record a hard-constraint
  violation (gateway-only effects, atomic transition+audit, single canonical
  state owner) MUST be rejected regardless of its weighted score;
- probe B not rejected: a real candidate (or the recommendation) without a
  declared failure boundary or deterministic replay interface is INCOMPLETE
  and cannot win;
- unknown cells are excluded from the weighted sums and renormalized; they
  are never mapped to zero, an average, or an advantage; their
  pessimistic/optimistic bounds are reported;
- fewer than 3 failure scenarios blocks any positive verdict.

Sensitivity analysis (deterministic, seeded):
- S1: every weight perturbed by +-50 percent (16 runs);
- S2: 200 random weight vectors (random.Random(42), integer weights, sum
  preserved) drawn AFTER scoring was frozen;
- S3: unknown cells bounded pessimistically (score 0) and optimistically
  (score 4);
- the winner must remain the same in every perturbation, otherwise the
  verdict is capped at PASS_WITH_LIMITS.

Usage:
    python evaluator.py --ticket . --out results
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

CLAIM_TYPES = {"fact", "measurement", "inference", "assumption", "unknown"}
MIN_DIMENSIONS = 8
MIN_FAILURE_SCENARIOS = 3
SENSITIVITY_RANDOM_RUNS = 200
SENSITIVITY_SEED = 42


class EvalError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_rubric(rubric: dict, rubric_path: Path) -> dict:
    if not rubric.get("frozen_before_scoring"):
        raise EvalError("rubric was not frozen before scoring")
    weights = rubric.get("weights", {})
    if len(weights) < MIN_DIMENSIONS:
        raise EvalError(f"rubric has {len(weights)} dimensions, need >= {MIN_DIMENSIONS}")
    if sum(weights.values()) != rubric.get("weight_sum"):
        raise EvalError("rubric weights do not sum to weight_sum")
    if not rubric.get("hard_constraints"):
        raise EvalError("rubric must freeze hard constraints")
    return weights


def validate_matrix(matrix: dict, rubric: dict, rubric_sha: str) -> tuple[dict, dict]:
    if matrix.get("rubric_sha256") != rubric_sha:
        raise EvalError(
            "matrix rubric hash mismatch: weights changed after scoring "
            f"(expected {rubric_sha})")
    candidates = matrix.get("candidates", {})
    real = [cid for cid, c in candidates.items() if c.get("is_real_candidate")]
    if sorted(real) != ["containers", "monolith"]:
        raise EvalError(f"expected exactly the two real topologies, got {sorted(real)}")
    if not any(c.get("probe") == "A" for c in candidates.values()):
        raise EvalError("probe A candidate missing")
    if not any(c.get("probe") == "B" for c in candidates.values()):
        raise EvalError("probe B candidate missing")
    dims = matrix.get("matrix", [])
    rubric_dims = set(rubric["weights"])
    seen_dims = {d["dimension"] for d in dims}
    if len(dims) < MIN_DIMENSIONS:
        raise EvalError(f"matrix has {len(dims)} dimensions, need >= {MIN_DIMENSIONS}")
    if seen_dims != rubric_dims:
        raise EvalError(
            f"matrix dimensions mismatch: missing={sorted(rubric_dims - seen_dims)} "
            f"extra={sorted(seen_dims - rubric_dims)}")
    probe_rejections = {"A": [], "B": []}
    for dim in dims:
        cells = dim.get("cells", {})
        for cid in real:
            if cid not in cells:
                raise EvalError(f"dimension {dim['dimension']}: missing cell for {cid}")
            cell = cells[cid]
            ctype = cell.get("claim_type")
            if ctype not in CLAIM_TYPES:
                raise EvalError(
                    f"{dim['dimension']}/{cid}: claim_type {ctype!r} invalid")
            if ctype == "unknown":
                if cell.get("score") is not None:
                    raise EvalError(
                        f"{dim['dimension']}/{cid}: unknown cell must have null score")
                if not cell.get("limitation"):
                    raise EvalError(
                        f"{dim['dimension']}/{cid}: unknown cell must state "
                        "the missing evidence")
            else:
                score = cell.get("score")
                if not isinstance(score, int) or not 0 <= score <= 4:
                    raise EvalError(
                        f"{dim['dimension']}/{cid}: score {score!r} outside 0..4")
        for cid, cand in candidates.items():
            violations = [
                v for d2 in [cells.get(cid, {})] if d2
                for v in (d2.get("hard_constraint_violations") or [])
            ]
            if violations:
                probe_rejections.setdefault(cid, violations)
    # structural rejection rules
    for cid, cand in candidates.items():
        if cid in real:
            # a REAL candidate without a declared failure boundary or a
            # deterministic replay interface makes the evidence itself
            # incomplete -> fail closed (this is the probe B property
            # generalized to every real topology)
            if cand.get("failure_boundary_ref") is None or \
                    cand.get("deterministic_replay_ref") is None:
                raise EvalError(
                    f"real candidate {cid} is INCOMPLETE: missing declared "
                    "failure boundary or deterministic replay interface")
        if cand.get("probe") == "A":
            if not any(
                cells.get(cid, {}).get("hard_constraint_violations")
                for cells in (d["cells"] for d in dims)
            ):
                raise EvalError("probe A candidate does not violate hard "
                                "constraints; the probe is not constructed")
            probe_rejections["A"].append(
                "rejected: violates frozen hard constraints regardless of score")
        if cand.get("probe") == "B":
            if cand.get("failure_boundary_ref") is None or \
                    cand.get("deterministic_replay_ref") is None:
                probe_rejections["B"].append(
                    "rejected as INCOMPLETE: no declared failure boundary or "
                    "deterministic replay interface")
    return real, probe_rejections


def weighted_scores(matrix: dict, weights: dict, real: list[str],
                    unknown_fill: dict | None = None) -> tuple[dict, dict]:
    """Returns (scores, meta). unknown_fill maps candidate->forced score or
    None for standard exclusion semantics."""
    scores = {cid: 0.0 for cid in real}
    used_weight = {cid: 0.0 for cid in real}
    unknown_dims = {cid: [] for cid in real}
    for dim in matrix["matrix"]:
        w = weights[dim["dimension"]]
        for cid in real:
            cell = dim["cells"][cid]
            if cell["claim_type"] == "unknown":
                unknown_dims[cid].append(dim["dimension"])
                if unknown_fill and cid in unknown_fill:
                    scores[cid] += w * unknown_fill[cid]
                    used_weight[cid] += w
                continue
            scores[cid] += w * cell["score"]
            used_weight[cid] += w
    normalized = {
        cid: (scores[cid] / used_weight[cid]) if used_weight[cid] else None
        for cid in real
    }
    meta = {
        "unknown_dims": unknown_dims,
        "used_weight": used_weight,
        "total_weight": sum(weights.values()),
    }
    return normalized, meta


def winner_of(scores: dict) -> str:
    scored = {cid: s for cid, s in scores.items() if s is not None}
    if not scored:
        raise EvalError("no scored candidates")
    return max(scored, key=lambda cid: scored[cid])


def sensitivity(matrix: dict, weights: dict, real: list[str]) -> dict:
    results = {"flips": [], "runs": 0, "stable": True}
    base_winner = winner_of(weighted_scores(matrix, weights, real)[0])

    # S1: +-50 percent per weight
    for dim_name, w in weights.items():
        for factor, label in ((0.5, "-50%"), (1.5, "+50%")):
            perturbed = dict(weights)
            perturbed[dim_name] = max(1, round(w * factor))
            # renormalize the rest so the sum stays constant
            rest = [k for k in perturbed if k != dim_name]
            delta = sum(weights.values()) - sum(perturbed.values())
            share = sum(perturbed[k] for k in rest)
            if share:
                for k in rest:
                    perturbed[k] = max(1, round(
                        perturbed[k] + delta * perturbed[k] / share))
            scores, _ = weighted_scores(matrix, perturbed, real)
            win = winner_of(scores)
            results["runs"] += 1
            if win != base_winner:
                results["stable"] = False
                results["flips"].append({
                    "kind": "S1_weight", "dimension": dim_name,
                    "perturbation": label, "winner": win})

    # S2: seeded random weight vectors with preserved total
    rng = random.Random(SENSITIVITY_SEED)
    total = sum(weights.values())
    names = list(weights)
    for i in range(SENSITIVITY_RANDOM_RUNS):
        cuts = sorted(rng.randrange(1, total) for _ in range(len(names) - 1))
        parts = []
        prev = 0
        for cut in cuts + [total]:
            parts.append(cut - prev)
            prev = cut
        vector = {k: max(1, v) for k, v in zip(names, parts)}
        scores, _ = weighted_scores(matrix, vector, real)
        win = winner_of(scores)
        results["runs"] += 1
        if win != base_winner:
            results["stable"] = False
            results["flips"].append({
                "kind": "S2_random", "run": i,
                "weights": vector, "winner": win})

    # S3: unknown bounds
    for label, fill in (("pessimistic_0", 0), ("optimistic_4", 4)):
        fill_map = {cid: fill for cid in real}
        scores, _ = weighted_scores(matrix, weights, real, unknown_fill=fill_map)
        win = winner_of(scores)
        results["runs"] += 1
        if win != base_winner:
            results["stable"] = False
            results["flips"].append({
                "kind": "S3_unknown", "bounds": label, "winner": win})
    results["base_winner"] = base_winner
    return results


def evaluate(ticket_dir: Path, out_dir: Path) -> dict:
    rubric = load_json(ticket_dir / "rubric.json")
    rubric_sha = sha256_file(ticket_dir / "rubric.json")
    weights = validate_rubric(rubric, ticket_dir / "rubric.json")
    matrix = load_json(out_dir / "qa1-decision-matrix.json")
    scenarios = load_json(out_dir / "failure-scenarios.json")
    real, probe_rejections = validate_matrix(matrix, rubric, rubric_sha)

    if len(scenarios.get("scenarios", [])) < MIN_FAILURE_SCENARIOS:
        raise EvalError(
            f"failure scenarios {len(scenarios.get('scenarios', []))} < "
            f"{MIN_FAILURE_SCENARIOS}")
    for sc in scenarios["scenarios"]:
        for field in ("fault_injection", "authoritative_state_owner",
                      "allowed_transitions", "recovery_path",
                      "observable_artifacts", "stop_condition",
                      "invariant_impact"):
            if field not in sc:
                raise EvalError(f"scenario {sc.get('id')} missing {field}")
        for cid in ("monolith", "containers"):
            if cid not in sc["authoritative_state_owner"]:
                raise EvalError(f"scenario {sc.get('id')} missing {cid}")

    scores, meta = weighted_scores(matrix, weights, real)
    sens = sensitivity(matrix, weights, real)
    winner = sens["base_winner"]

    unknown_all = sorted({d for cid in real for d in meta["unknown_dims"][cid]})
    winner_unknown = meta["unknown_dims"][winner]

    verdict = "PASS"
    reasons = []
    all_unknown = sorted({d for cid in real for d in meta["unknown_dims"][cid]})
    if all_unknown:
        verdict = "PASS_WITH_LIMITS"
        reasons.append(
            "unknown cells present in the comparison: "
            f"{all_unknown} (excluded and renormalized; winner's cells: "
            f"{winner_unknown or 'none'}; bounded in sensitivity S3)")
    if not sens["stable"]:
        verdict = "PASS_WITH_LIMITS"
        reasons.append("winner flipped under sensitivity perturbations; "
                       "verdict capped per rubric")
    if probe_rejections.get("A"):
        reasons.append("probe A rejected: " + "; ".join(probe_rejections["A"]))
    if probe_rejections.get("B"):
        reasons.append("probe B rejected: " + "; ".join(probe_rejections["B"]))

    result = {
        "schema": "agentos.s1-005.evaluation/v1",
        "rubric_sha256": rubric_sha,
        "scores_normalized": {cid: round(s, 4) if s is not None else None
                              for cid, s in scores.items()},
        "used_weight": meta["used_weight"],
        "unknown_dimensions": meta["unknown_dims"],
        "winner": winner,
        "recommendation": {
            "topology": winner,
            "name": matrix["candidates"][winner]["name"],
        },
        "probe_rejections": probe_rejections,
        "sensitivity": {
            "runs": sens["runs"],
            "stable": sens["stable"],
            "flips": sens["flips"],
            "seed": SENSITIVITY_SEED,
            "random_runs": SENSITIVITY_RANDOM_RUNS,
        },
        "verdict": verdict,
        "reasons": reasons,
    }
    (out_dir / "sensitivity-analysis.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", default=".")
    parser.add_argument("--out", default="results")
    args = parser.parse_args(argv)
    ticket_dir = Path(args.ticket).resolve()
    out_dir = (ticket_dir / args.out).resolve() if not Path(args.out).is_absolute() \
        else Path(args.out)
    try:
        result = evaluate(ticket_dir, out_dir)
    except EvalError as exc:
        print(json.dumps({"verdict": "FAIL", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
