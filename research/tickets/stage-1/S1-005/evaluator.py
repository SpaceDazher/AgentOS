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
import os
import random
import re
from pathlib import Path

from experiments import validate_experiment_result

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
    """Legacy helper kept for compatibility; strict authority is enforced
    in _resolve_ref below."""
    if not ref:
        return False
    path_part = ref.split("#", 1)[0].strip()
    if not _PATHLIKE_RE.match(path_part):
        return False
    candidates = [
        ticket_dir / path_part,
        ticket_dir.parents[3] / path_part,
    ]
    return any(c.is_file() or c.is_dir() for c in candidates)


def _load_ref_index(ticket_dir: Path) -> dict:
    """The evidence-ref registry: maps non-path source ids to hash-bound
    repository files. Free-form references are authority-free and are
    rejected (review R2, finding F2)."""
    index_path = ticket_dir / "evidence-ref-index.json"
    if not index_path.is_file():
        raise EvalError(
            f"evidence-ref registry missing: {index_path}")
    index = load_json(index_path)
    for ref, binding in index.items():
        bound = (ticket_dir / binding["path"].replace("/", "\\"))
        if not bound.is_file():
            bound = ticket_dir.parents[3] / binding["path"]
        if not bound.is_file():
            raise EvalError(
                f"evidence-ref registry entry {ref!r} binds a missing file: "
                f"{binding['path']}")
        digest = sha256_file(bound)
        if digest != binding.get("sha256"):
            raise EvalError(
                f"evidence-ref registry entry {ref!r} digest mismatch for "
                f"{binding['path']}")
    return index


def _resolve_ref(ref: str, ticket_dir: Path, index: dict,
                 probe_candidate: bool) -> tuple:
    """Resolve one evidence ref. Returns (resolved_path|None, kind).
    Only two authorities exist: hash-bound registry source ids and
    repository paths that exist on disk. Free-form strings are rejected
    (review R2, finding F2)."""
    if not ref or not isinstance(ref, str):
        raise EvalError(f"empty evidence ref")
    if ref == "probe":
        if not probe_candidate:
            raise EvalError(
                f"'probe' evidence is only valid on probe candidates")
        return None, "probe"
    if ref in index:
        binding = index[ref]
        bound = ticket_dir / binding["path"].replace("/", "\\")
        if not bound.is_file():
            bound = ticket_dir.parents[3] / binding["path"]
        if not bound.is_file():
            raise EvalError(f"evidence ref {ref!r} binds a missing file")
        if sha256_file(bound) != binding.get("sha256"):
            raise EvalError(
                f"evidence ref {ref!r} file digest mismatch")
        return bound, binding.get("kind", "source")
    path_part = ref.split("#", 1)[0].strip()
    if _PATHLIKE_RE.match(path_part):
        for base in (ticket_dir, ticket_dir.parents[3]):
            candidate = base / path_part
            if candidate.is_file() or candidate.is_dir():
                return candidate, "path"
    raise EvalError(
        f"evidence ref {ref!r} is neither a registry source id nor an "
        "existing repository path (free-form authority is not allowed)")


def _validate_cell(cell: dict, dim: str, cid: str, ticket_dir: Path,
                   known_violations: set, index: dict,
                   probe_candidate: bool) -> None:
    ctype = cell.get("claim_type")
    if ctype not in CLAIM_TYPES:
        raise EvalError(f"{dim}/{cid}: claim_type {ctype!r} invalid")
    statement = cell.get("statement")
    if not isinstance(statement, str) or not statement.strip():
        raise EvalError(f"{dim}/{cid}: statement must be non-empty")
    refs = cell.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        raise EvalError(f"{dim}/{cid}: evidence_refs must be a non-empty list")
    resolved = []
    for ref in refs:
        path, kind = _resolve_ref(ref, ticket_dir, index, probe_candidate)
        resolved.append((ref, path, kind))
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
    # claim classification is enforced harness-side (review R2, finding F2):
    # a measurement claim needs a hash-bound measurement artifact; a fact
    # claim needs an implementation/source artifact. Unknown-to-scored
    # transitions therefore require new canonical evidence by construction.
    def satisfies(kind_or_loc):
        for _, path, kind in resolved:
            if kind == kind_or_loc:
                return True
            if kind == "path" and path is not None:
                parts = [x.lower() for x in path.parts]
                if kind_or_loc == "measurement" and "results" in parts                         and "s1-005" in parts:
                    return True
                if kind_or_loc == "implementation" and (
                        "src" in parts or "adr" in parts or "spec" in parts
                        or "tests" in parts):
                    return True
        return False

    if ctype == "measurement":
        if not satisfies("measurement"):
            raise EvalError(
                f"{dim}/{cid}: measurement claim requires a hash-bound "
                "measurement artifact in evidence_refs")
    if ctype == "fact":
        if not (satisfies("implementation") or satisfies("source")):
            raise EvalError(
                f"{dim}/{cid}: fact claim requires an implementation or "
                "source artifact in evidence_refs")


def validate_matrix(matrix: dict, rubric: dict, rubric_sha: str,
                    ticket_dir: Path) -> tuple:
    """Returns (scoring_candidates, rejections, rejected_real)."""
    index = _load_ref_index(ticket_dir)
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
                           known_violations, index,
                           bool(candidates[cid].get("probe")))

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
        results.setdefault("s2_runs", []).append({
            "run": i,
            "weights": vector_map,
            "total": total,
            "weights_sha256": digest,
            "winner": win,
            "indeterminate": tie,
        })

    for label, fill in (("pessimistic_0", 0), ("optimistic_4", 4)):
        fill_map = {cid: fill for cid in scoring}
        scores, _ = weighted_scores(matrix, weights, scoring, unknown_fill=fill_map)
        win, tie = winner_of(scores)
        record(win, tie, {"kind": "S3_unknown", "bounds": label})

    for run in results.get("s2_runs", []):
        digest = hashlib.sha256(
            json.dumps(run["weights"], sort_keys=True).encode()).hexdigest()
        if digest != run["weights_sha256"] or run["total"] != total:
            raise EvalError("persisted S2 vector failed digest verification")
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
            if value is None:
                raise EvalError(f"scenario {sid}: field {field} is missing")
            _reject_empty(value, f"scenario {sid}.{field}")
        for topology in ("monolith", "containers"):
            owner = sc["authoritative_state_owner"].get(topology)
            if not isinstance(owner, str) or not owner.strip():
                raise EvalError(
                    f"scenario {sid}: authoritative_state_owner.{topology} "
                    "must be a non-empty string")
            transitions = sc["allowed_transitions"].get(topology)
            if not isinstance(transitions, list):
                raise EvalError(
                    f"scenario {sid}: allowed_transitions.{topology} must be "
                    "a non-empty list of strings")
            _reject_empty(transitions,
                          f"scenario {sid}.allowed_transitions.{topology}")
            recovery = sc["recovery_path"].get(topology)
            if not isinstance(recovery, str) or not recovery.strip():
                raise EvalError(
                    f"scenario {sid}: recovery_path.{topology} must be a "
                    "non-empty string")
            impact = sc["invariant_impact"].get(topology)
            if not isinstance(impact, str) or not impact.strip():
                raise EvalError(
                    f"scenario {sid}: invariant_impact.{topology} must be a "
                    "non-empty string")
            if not INVARIANT_REF_RE.search(impact):
                raise EvalError(
                    f"scenario {sid}: invariant impact for {topology} does "
                    "not reference INV/SAF/LIVE")
        artifacts = sc["observable_artifacts"]
        if not isinstance(artifacts, list):
            raise EvalError(
                f"scenario {sid}: observable_artifacts must be a list")
        _reject_empty(artifacts, f"scenario {sid}.observable_artifacts")
        _reject_empty(sc["stop_condition"], f"scenario {sid}.stop_condition")


def _reject_empty(value, where: str) -> None:
    """Recursively forbid empty strings, lists and dicts (review R2 F3)."""
    if isinstance(value, str):
        if not value.strip():
            raise EvalError(f"{where}: empty string")
    elif isinstance(value, list):
        if not value:
            raise EvalError(f"{where}: empty list")
        for i, item in enumerate(value):
            _reject_empty(item, f"{where}[{i}]")
    elif isinstance(value, dict):
        if not value:
            raise EvalError(f"{where}: empty dict")
        for k, v in value.items():
            if not str(k).strip():
                raise EvalError(f"{where}: empty key")
            _reject_empty(v, f"{where}.{k}")

def validate_experiments(experiments: dict, *,
                         expected_commit: str | None = None,
                         verify_script_hashes: bool = False) -> None:
    """Delegate to THE single shared strict validator (review R3, F5);
    no weaker local copy is allowed."""
    try:
        validate_experiment_result(
            experiments, expected_commit=expected_commit,
            verify_script_hashes=verify_script_hashes)
    except ValueError as exc:
        raise EvalError(str(exc)) from exc


def _enforce_host_classification(matrix: dict, host: dict) -> None:
    """Review R3, finding 6: the host-owned classification freezes
    claim_type, score, confidence and evidence_refs for every candidate x
    dimension. Matrix cells are candidate narrative; score inputs are
    host-authoritative. Any deviation (including reclassifying an unknown
    cell with unrelated-but-valid evidence) is rejected."""
    cells = {(d["dimension"], cid): cell
             for d in matrix["matrix"] for cid, cell in d["cells"].items()}
    for key, frozen in host.get("cells", {}).items():
        cell = cells.get(tuple(key.split("|")))
        if cell is None:
            raise EvalError(f"host classification key {key!r} has no cell")
        for field in ("claim_type", "score", "confidence"):
            if cell.get(field) != frozen.get(field):
                raise EvalError(
                    f"{key}: {field} deviates from the frozen host "
                    f"classification (matrix={cell.get(field)!r} "
                    f"host={frozen.get(field)!r})")
        frozen_refs = sorted(frozen.get("evidence_refs", []))
        cell_refs = sorted(cell.get("evidence_refs", []))
        if frozen_refs != cell_refs:
            raise EvalError(
                f"{key}: evidence_refs deviate from the frozen host "
                "classification")


def evaluate(ticket_dir: Path, out_dir: Path, *,
             experiments_path: Path | None = None,
             experiments_sha: str | None = None,
             expected_commit: str | None = None,
             run_nonce: str | None = None,
             host_classification: dict | None = None) -> dict:
    rubric = load_json(ticket_dir / "rubric.json")
    rubric_sha = sha256_file(ticket_dir / "rubric.json")
    weights = validate_rubric(rubric, ticket_dir / "rubric.json")
    matrix = load_json(out_dir / "qa1-decision-matrix.json")
    scenarios = load_json(out_dir / "failure-scenarios.json")
    # experiments binding (review R3, findings 3-5): the evaluator scores
    # EXACTLY the frozen experiment artifact named by the caller and
    # verifies its byte digest before use.
    if experiments_path is None:
        experiments_path = out_dir / "boundary-experiments.json"
    experiments = load_json(experiments_path)
    if experiments_sha:
        actual = hashlib.sha256(
            Path(experiments_path).read_bytes()).hexdigest()
        if actual != experiments_sha:
            raise EvalError(
                f"experiments digest mismatch: {actual} != {experiments_sha}")
    validate_experiments(experiments, expected_commit=expected_commit,
                         verify_script_hashes=True)
    # host-owned classification (review R3, finding 6): the frozen
    # classification per candidate x dimension is authoritative; a matrix
    # cell that deviates is rejected.
    host = host_classification or load_json(
        ticket_dir / "host-classification.json")
    _enforce_host_classification(matrix, host)
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
        "run_nonce": run_nonce,
        "experiments_binding": {
            "path": Path(experiments_path).name,
            "sha256": sha256_file(Path(experiments_path)),
        },
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
            "s2_runs": sens.get("s2_runs", []),
            "total_weight": sens.get("total_weight"),
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
    parser.add_argument("--experiments", default=None,
                        help="frozen boundary-experiments artifact to score")
    parser.add_argument("--experiments-sha", default=None,
                        help="sha256 of the frozen experiments artifact")
    parser.add_argument("--expected-commit", default=None)
    args = parser.parse_args(argv)
    ticket_dir = Path(args.ticket).resolve()
    out_dir = (ticket_dir / args.out).resolve() if not Path(args.out).is_absolute() \
        else Path(args.out)
    try:
        result = evaluate(
            ticket_dir, out_dir,
            experiments_path=(Path(args.experiments).resolve()
                              if args.experiments else None),
            experiments_sha=args.experiments_sha,
            expected_commit=args.expected_commit,
            run_nonce=os.environ.get("AGENTOS_RUN_NONCE"))
    except EvalError as exc:
        print(json.dumps({"verdict": "FAIL", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
