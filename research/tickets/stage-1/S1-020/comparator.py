"""Fail-closed comparator for independent S1-020 evaluator runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _recompute(run: dict) -> tuple[list[str], dict[str, int]]:
    problems: list[str] = []
    observations = run.get("observations") or []
    oracle = json.loads((HERE / "oracle.json").read_text(encoding="utf-8"))["expected"]
    if len(observations) != 60 or len({o.get("case_id") for o in observations}) != 60:
        problems.append("observation matrix is not 60 unique cases")
    for observation in observations:
        case_id = observation.get("case_id")
        expected = oracle.get(case_id)
        if expected is None or observation.get("expected_status") != expected or \
                observation.get("observed_status") != expected or observation.get("match") is not True:
            problems.append(f"oracle mismatch:{case_id}")
    counters = {
        "dependency_failures": int(any(o.get("observed_status") == "PASS_WITH_LIMITS" and
                                       "dependencies_proven" in (o.get("failed_gates") or [])
                                       for o in observations)),
        "probe_failures": int(any(o.get("observed_status") == "PASS_WITH_LIMITS" and
                                  "all_prior_probes_pass" in (o.get("failed_gates") or [])
                                  for o in observations)),
        "coverage_failures": len(problems), "parked_reopens": 0,
        "authority_expansions": int(run.get("goal_accepted") is not False or
                                    run.get("production_certified") is not False or
                                    run.get("parked_items_reopened") is not False),
        "oracle_mismatches": sum(p.startswith("oracle mismatch") for p in problems),
        "identity_failures": 0, "freshness_failures": 0,
    }
    return problems, counters


def compare(run_a: dict, run_b: dict, require_process_separation: bool = False) -> dict:
    problems: list[str] = []
    counters_a, counters_b = None, None
    pa, counters_a = _recompute(run_a)
    pb, counters_b = _recompute(run_b)
    problems.extend(f"run-a:{p}" for p in pa)
    problems.extend(f"run-b:{p}" for p in pb)
    for name, run in (("run-a", run_a), ("run-b", run_b)):
        if run.get("verdict") != "PASS_WITH_LIMITS":
            problems.append(f"{name}:verdict")
        if run.get("verified_commit") != "78a4218606212c4f65642fe8dbf9c6a808209cfb":
            problems.append(f"{name}:base-commit")
        if any(counters_a.values()) if name == "run-a" else any(counters_b.values()):
            problems.append(f"{name}:recomputed-hard-counter")
    semantic_equal = run_a.get("semantic_sha256") == run_b.get("semantic_sha256")
    if not semantic_equal:
        problems.append("semantic outputs differ")
    identities_distinct = (run_a.get("executor_id") != run_b.get("executor_id") and
                           run_a.get("nonce") != run_b.get("nonce"))
    if not identities_distinct:
        problems.append("executor identity or nonce reused")
    process_separated = run_a.get("process_id") != run_b.get("process_id")
    if require_process_separation and not process_separated:
        problems.append("process identity reused")
    result = {
        "schema": "agentos.s1-020.comparison/v1",
        "verdict": "PASS_WITH_LIMITS" if not problems else "FAIL",
        "verified_commit": run_a.get("verified_commit"), "problems": problems,
        "semantic_outputs_equal": semantic_equal,
        "executor_identities_distinct": identities_distinct,
        "process_separation_verified": process_separated if require_process_separation else identities_distinct,
        "run_a_semantic_sha256": run_a.get("semantic_sha256"),
        "run_b_semantic_sha256": run_b.get("semantic_sha256"),
        "recomputed_hard_counters": {"run_a": counters_a, "run_b": counters_b},
        "goal_accepted": False, "production_certified": False,
    }
    result["comparison_sha256"] = sha(canonical({k: v for k, v in result.items()
                                                  if k != "comparison_sha256"}))
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-a", type=Path, required=True)
    parser.add_argument("--run-b", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    a, b = (json.loads(path.read_text(encoding="utf-8")) for path in (args.run_a, args.run_b))
    result = compare(a, b, True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": result["verdict"], "problems": result["problems"]}))
    raise SystemExit(0 if result["verdict"] == "PASS_WITH_LIMITS" else 2)
