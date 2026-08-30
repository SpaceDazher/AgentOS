"""AgentOS S1-005 — deterministic QA1 evaluator (corrective revision 2).

Review R1 contract (research/tickets/stage-1/S1-005/REVIEW_R1.md):

- hard constraints (frozen ids in the rubric) reject ANY candidate that
  records a violation, not only probe candidates; fewer than two remaining
  real candidates is a FAIL;
- the decision matrix must have unique dimensions matching the rubric
  exactly (one row per dimension), and every real-candidate cell must carry
  claim_type, statement, evidence_refs, confidence and a valid score rule;
  unknown cells are excluded and renormalized, never mapped to a number;
  path-like evidence refs must exist on disk;
- failure scenarios need unique ids, non-empty required fields, both
  topology branches and INV/SAF/LIVE references (enforced here);
- sensitivity S2 draws EXACT integer compositions of the rubric total
  (every vector sums to the total), ties are indeterminate (never resolved
  by insertion order), and every S2 vector is recorded by digest;
- every S2 vector is validated before scoring.

Usage:
    python evaluator.py --ticket . --out results
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from pathlib import Path

CLAIM_TYPES = {"fact", "measurement", "inference", "assumption", "unknown"}
MIN_DIMENSIONS = 8
MIN_FAILURE_SCENARIOS = 3
SENSITIVITY_RANDOM_RUNS = 200
SENSITIVITY_SEED = 42
INVARIANT_REF_RE = re.compile(r"\b(INV[1-6]|SAF\d|LIVE\d)")
_PATHLIKE_RE = re.compile(
    r"^(?:src|docs|adr|spec|tests|research|evals|results)/[^#]*")


class EvalError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def random_composition(total: int, parts: int, rng: random.Random) -> list:
    """Exact uniform-ish positive integer composition of `total` into
    `parts` non-negative parts (each >= 1): stars and bars with distinct
    cut points, so the sum is exact by construction."""
    if parts < 1 or total < parts:
        raise ValueError("need total >= parts >= 1")
    cuts = sorted(rng.sample(range(1, total), parts - 1))
    result = []
    prev = 0
    for cut in cuts + [total]:
        result.append(cut - prev)
        prev = cut
    return result


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
    ids = rubric.get("hard_constraint_ids")
    if not ids or len(ids) != len(set(ids)):
        raise EvalError("rubric must define unique hard_constraint_ids")
    return weights


def _evidence_ref_exists(ref: str, ticket_dir: Path) -> bool:
    if not ref:
        return False
    if ref == "probe" or ref.startswith("probe "):
        return True
    path_part = ref.split("#", 1)[0].strip()
    if not _PATHLIKE_RE.match(path_part):
        # free-form references (e.g. "standard container practice") allowed
        return True
    candidates = [
        ticket_dir / path_part,
        ticket_dir.parents[3] / path_part,
    ]
    return any(c.is_file() or c.is_dir() for c in candidates)


def _validate_cell(cell: dict, dim: str, cid: str, ticket_dir: Path,
                   known_violations: set) -> None:
    ctype = cell.get("claim_type")
    if ctype not in CLAIM_TYPES:
        raise EvalError(f"{dim}/{cid}: claim_type {ctype!r} invalid")
    statement = cell.get("statement")
    if not isinstance(statement, str) or not statement.strip():
        raise EvalError(f"{dim}/{cid}: statement must be non-empty")
    refs = cell.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        raise EvalError(f"{dim}/{cid}: evidence_refs must be a non-empty list")
    for ref in refs:
        if not isinstance(ref, str) or not _evidence_ref_exists(ref, ticket_dir):
            raise EvalError(f"{dim}/{cid}: evidence ref does not resolve: {ref!r}")
    confidence = cell.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise EvalError(f"{dim}/{cid}: confidence must be in [0, 1]")
    violations = cell.get("hard_constraint_violations") or []
    for v in violations:
        if v not in known_violations:
            raise EvalError(
                f"{dim}/{cid}: unknown hard constraint id {v!r}")
    if ctype == "unknown":
        if cell.get("score") is not None:
            raise EvalError(
                f"{dim}/{cid}: unknown cell must not carry a numeric score")
        if not cell.get("limitation"):
            raise EvalError(
                f"{dim}/{cid}: unknown cell must state the missing evidence")
    else:
        score = cell.get("score")
        if not isinstance(score, int) or not 0 <= score <= 4:
            raise EvalError(f"{dim}/{cid}: score {score!r} outside 0..4")


def validate_matrix(matrix: dict, rubric: dict, rubric_sha: str,
                    ticket_dir: Path) -> tuple:
    """Returns (scoring_candidates, rejections, rejected_real)."""
    if matrix.get("rubric_sha256") != rubric_sha:
        raise EvalError(
            "matrix rubric hash mismatch: weights changed after scoring "
            f"(expected {rubric_sha})")
    candidates = matrix.get("candidates", {})
    real = sorted(cid for cid, c in candidates.items()
                  if c.get("is_real_candidate"))
    if real != ["containers", "monolith"]:
        raise EvalError(f"expected exactly the two real topologies, got {real}")
    if not any(c.get("probe") == "A" for c in candidates.values()):
        raise EvalError("probe A candidate missing")
    if not any(c.get("probe") == "B" for c in candidates.values()):
        raise EvalError("probe B candidate missing")
    known_violations = set(rubric.get("hard_constraint_ids") or ())

    dims = matrix.get("matrix", [])
    names = [d.get("dimension") for d in dims]
    if len(names) != len(set(names)):
        duplicates = sorted({n for n in names if names.count(n) > 1})
        raise EvalError(f"duplicate dimension rows: {duplicates}")
    rubric_dims = set(rubric["weights"])
    if len(dims) < MIN_DIMENSIONS:
        raise EvalError(f"matrix has {len(dims)} dimensions, need >= {MIN_DIMENSIONS}")
    if set(names) != rubric_dims:
        raise EvalError(
            f"matrix dimensions mismatch: missing={sorted(rubric_dims - set(names))} "
            f"extra={sorted(set(names) - rubric_dims)}")

    for dim in dims:
        cells = dim.get("cells", {})
        for cid in real:
            if cid not in cells:
                raise EvalError(
                    f"dimension {dim['dimension']}: missing cell for {cid}")
            _validate_cell(cells[cid], dim["dimension"], cid, ticket_dir,
                           known_violations)

    scoring = list(real)
    rejections = {"A": [], "B": []}
    rejected_real = {}
    for cid, cand in candidates.items():
        violations = set()
        for dim in dims:
            violations.update(
                dim["cells"].get(cid, {}).get("hard_constraint_violations") or [])
        if cand.get("probe") == "A":
            if not violations:
                raise EvalError(
                    "probe A candidate does not violate hard constraints; "
                    "the probe is not constructed")
            rejections["A"].append(
                "rejected: violates frozen hard constraints regardless of "
                f"score ({sorted(violations)})")
        elif cid in real:
            if cand.get("failure_boundary_ref") is None or \
                    cand.get("deterministic_replay_ref") is None:
                raise EvalError(
                    f"real candidate {cid} is INCOMPLETE: missing declared "
                    "failure boundary or deterministic replay interface")
            if violations:
                rejected_real[cid] = sorted(violations)
                scoring.remove(cid)
        if cand.get("probe") == "B":
            if cand.get("failure_boundary_ref") is None or \
                    cand.get("deterministic_replay_ref") is None:
                rejections["B"].append(
                    "rejected as INCOMPLETE: no declared failure boundary or "
                    "deterministic replay interface")
    if not scoring:
        raise EvalError(
            "all real candidates were rejected for hard-constraint "
            f"violations: {rejected_real}")
    return scoring, rejections, rejected_real


def weighted_scores(matrix: dict, weights: dict, scoring: list,
                    unknown_fill: dict | None = None) -> tuple:
    scores = {cid: 0.0 for cid in scoring}
    used_weight = {cid: 0.0 for cid in scoring}
    unknown_dims = {cid: [] for cid in scoring}
    for dim in matrix["matrix"]:
        w = weights[dim["dimension"]]
        for cid in scoring:
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
        for cid in scoring
    }
    meta = {
        "unknown_dims": unknown_dims,
        "used_weight": used_weight,
        "total_weight": sum(weights.values()),
    }
    return normalized, meta


def winner_of(scores: dict) -> tuple:
    """Returns (winner, tie). Exact ties are INDETERMINATE: None is
    returned instead of an insertion-order artifact."""
    scored = {cid: s for cid, s in scores.items() if s is not None}
    if not scored:
        raise EvalError("no scored candidates")
    best = max(scored.values())
    leaders = [cid for cid, s in scored.items() if s == best]
    if len(leaders) > 1:
        return None, True
    return leaders[0], False


def _renormalize_to_total(raw: dict, total: int) -> dict:
    """Largest-remainder integer apportionment: every weight >= 1 and the
    sum is exactly `total` (review R1 finding 6)."""
    names = list(raw)
    base = {k: 1 for k in names}
    remaining = total - len(names)
    raw_sum = sum(raw.values())
    if raw_sum <= 0:
        raise EvalError("cannot renormalize non-positive raw weights")
    shares = {k: remaining * raw[k] / raw_sum for k in names}
    floors = {k: int(shares[k]) for k in names}
    for k in names:
        base[k] += floors[k]
    leftover = total - sum(base.values())
    order = sorted(names, key=lambda k: shares[k] - floors[k], reverse=True)
    for k in order[:leftover]:
        base[k] += 1
    if sum(base.values()) != total or any(v < 1 for v in base.values()):
        raise EvalError("weight renormalization broke the total")
    return base


def sensitivity(matrix: dict, weights: dict, scoring: list) -> dict:
    results = {"flips": [], "runs": 0, "stable": True, "ties": 0,
               "s2_all_sums_valid": True, "s2_vector_digests": []}
    base_winner, _ = winner_of(weighted_scores(matrix, weights, scoring)[0])
    total = sum(weights.values())
    names = list(weights)

    def record(win, tie, entry):
        results["runs"] += 1
        if tie:
            results["stable"] = False
            results["ties"] += 1
            entry = dict(entry, winner=None, indeterminate=True)
            results["flips"].append(entry)
        elif win != base_winner:
            results["stable"] = False
            results["flips"].append(dict(entry, winner=win))

    for dim_name, w in weights.items():
        for factor, label in ((0.5, "-50%"), (1.5, "+50%")):
            raw = dict(weights)
            raw[dim_name] = w * factor
            perturbed = _renormalize_to_total(raw, total)
            scores, _ = weighted_scores(matrix, perturbed, scoring)
            win, tie = winner_of(scores)
            record(win, tie, {"kind": "S1_weight", "dimension": dim_name,
                              "perturbation": label,
                              "weights_sha256": hashlib.sha256(
                                  json.dumps(perturbed, sort_keys=True)
                                  .encode()).hexdigest()})

    rng = random.Random(SENSITIVITY_SEED)
    for i in range(SENSITIVITY_RANDOM_RUNS):
        vector = random_composition(total, len(names), rng)
        if sum(vector) != total:
            results["s2_all_sums_valid"] = False
            raise EvalError("S2 composition does not sum to the rubric total")
        vector_map = _renormalize_to_total(
            {k: max(1, v) for k, v in zip(names, vector)}, total)
        digest = hashlib.sha256(
            json.dumps(vector_map, sort_keys=True).encode()).hexdigest()
        scores, _ = weighted_scores(matrix, vector_map, scoring)
        win, tie = winner_of(scores)
        record(win, tie, {"kind": "S2_random", "run": i,
                          "weights_sha256": digest})
        results["s2_vector_digests"].append(digest)

    for label, fill in (("pessimistic_0", 0), ("optimistic_4", 4)):
        fill_map = {cid: fill for cid in scoring}
        scores, _ = weighted_scores(matrix, weights, scoring, unknown_fill=fill_map)
        win, tie = winner_of(scores)
        record(win, tie, {"kind": "S3_unknown", "bounds": label})

    results["base_winner"] = base_winner
    results["total_weight"] = total
    return results


def validate_scenarios(scenarios: dict) -> None:
    sc_list = scenarios.get("scenarios", [])
    if len(sc_list) < MIN_FAILURE_SCENARIOS:
        raise EvalError(
            f"failure scenarios {len(sc_list)} < {MIN_FAILURE_SCENARIOS}")
    ids = set()
    for sc in sc_list:
        sid = sc.get("id")
        if not sid or sid in ids:
            raise EvalError(f"scenario id missing or duplicated: {sid!r}")
        ids.add(sid)
        for field in ("title", "fault_injection", "initial_state",
                      "authoritative_state_owner", "allowed_transitions",
                      "recovery_path", "observable_artifacts",
                      "stop_condition", "invariant_impact"):
            value = sc.get(field)
            if value is None or value == "" or value == [] or value == {}:
                raise EvalError(f"scenario {sid}: field {field} is empty")
        for topology in ("monolith", "containers"):
            for field in ("authoritative_state_owner", "allowed_transitions",
                          "recovery_path", "invariant_impact"):
                branch = sc[field]
                if not isinstance(branch, dict) or topology not in branch:
                    raise EvalError(
                        f"scenario {sid}: {field} missing {topology} branch")
            impact = json.dumps(sc["invariant_impact"][topology])
            if not INVARIANT_REF_RE.search(impact):
                raise EvalError(
                    f"scenario {sid}: invariant impact for {topology} does "
                    "not reference INV/SAF/LIVE")
        if not sc["observable_artifacts"]:
            raise EvalError(f"scenario {sid}: no observable artifacts")


def validate_experiments(experiments: dict) -> None:
    if not str(experiments.get("schema", "")).startswith(
            "agentos.s1-005.boundary-experiments/"):
        raise EvalError("boundary experiments schema mismatch")
    exps = experiments.get("experiments", {})
    for key in ("small_512b", "large_16kb", "sqlite_multi_writer"):
        if key not in exps:
            raise EvalError(f"boundary experiments missing {key}")
    for key in ("small_512b", "large_16kb"):
        block = exps[key]
        for transport in ("in_process_us", "pipe_process_us", "tcp_localhost_us"):
            value = block.get(transport)
            if not isinstance(value, (int, float)) or value <= 0:
                raise EvalError(f"{key}.{transport} missing or non-positive")
        if not block["in_process_us"] < block["pipe_process_us"]:
            raise EvalError(
                f"{key}: in-process must be faster than a process boundary")
    e2 = exps["sqlite_multi_writer"]
    if e2.get("committed_rows_complete") is not True:
        raise EvalError("E2 committed rows are not complete; serialization "
                        "property not demonstrated")
    single = e2["single_writer"]["txns_per_second"]
    multi = e2["two_writers"]["txns_per_second"]
    if not (single > 0 and multi > 0 and multi < single):
        raise EvalError("E2 multi-writer must be slower than single writer")


def evaluate(ticket_dir: Path, out_dir: Path) -> dict:
    rubric = load_json(ticket_dir / "rubric.json")
    rubric_sha = sha256_file(ticket_dir / "rubric.json")
    weights = validate_rubric(rubric, ticket_dir / "rubric.json")
    matrix = load_json(out_dir / "qa1-decision-matrix.json")
    scenarios = load_json(out_dir / "failure-scenarios.json")
    experiments = load_json(out_dir / "boundary-experiments.json")
    validate_experiments(experiments)
    validate_scenarios(scenarios)
    scoring, rejections, rejected_real = validate_matrix(
        matrix, rubric, rubric_sha, ticket_dir)

    scores, meta = weighted_scores(matrix, weights, scoring)
    sens = sensitivity(matrix, weights, scoring)
    winner = sens["base_winner"]

    all_unknown = sorted({d for cid in scoring for d in meta["unknown_dims"][cid]})
    verdict = "PASS"
    reasons = []
    if all_unknown:
        verdict = "PASS_WITH_LIMITS"
        reasons.append(
            "unknown cells present in the comparison: "
            f"{all_unknown} (excluded and renormalized; winner's cells: "
            f"{meta['unknown_dims'][winner] or 'none'}; bounded in "
            "sensitivity S3)")
    if not sens["stable"]:
        verdict = "PASS_WITH_LIMITS"
        reasons.append("winner flipped or tied under sensitivity "
                       "perturbations; verdict capped per rubric")
    for probe, note in rejections.items():
        if note:
            reasons.append(f"probe {probe} rejected: " + "; ".join(note))
    if rejected_real:
        # a topology with a hard-constraint violation breaks the comparison:
        # the remaining candidate cannot receive a positive verdict
        verdict = "FAIL"
        reasons.append(
            "real candidate(s) rejected for hard-constraint violations: "
            + json.dumps(rejected_real)
            + " - a positive verdict requires both topologies to be valid")

    result = {
        "schema": "agentos.s1-005.evaluation/v1",
        "rubric_sha256": rubric_sha,
        "scores_normalized": {cid: round(s, 4) if s is not None else None
                              for cid, s in scores.items()},
        "used_weight": meta["used_weight"],
        "unknown_dimensions": meta["unknown_dims"],
        "rejected_real_candidates": rejected_real,
        "winner": winner,
        "recommendation": {
            "topology": winner,
            "name": matrix["candidates"][winner]["name"],
        },
        "probe_rejections": rejections,
        "sensitivity": {
            "runs": sens["runs"],
            "stable": sens["stable"],
            "ties": sens["ties"],
            "flips": sens["flips"],
            "seed": SENSITIVITY_SEED,
            "random_runs": SENSITIVITY_RANDOM_RUNS,
            "s2_all_sums_valid": sens["s2_all_sums_valid"],
            "s2_vector_digests": sens["s2_vector_digests"],
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
