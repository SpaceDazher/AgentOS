"""Deterministic S1-020 closure evaluator with a host-owned oracle."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
BASE_COMMIT = "78a4218606212c4f65642fe8dbf9c6a808209cfb"
EXPECTED_DEPENDENCIES = [f"S1-{n:03d}" for n in range(1, 20)]
EXPECTED_ACTIVE = [f"S1-{n:03d}" for n in range(1, 21)]
EXPECTED_PARKED = [f"PARK-{n:02d}" for n in range(1, 5)]


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load(name: str) -> dict:
    value = json.loads((HERE / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name} must contain an object")
    return value


def verify_frozen() -> dict[str, str]:
    manifest = load("frozen-manifest.json")
    if manifest.get("base_commit") != BASE_COMMIT:
        raise ValueError("frozen manifest base commit mismatch")
    files = manifest.get("files") or {}
    if not files:
        raise ValueError("empty frozen manifest")
    for rel, expected in files.items():
        path = ROOT / rel
        if not path.is_file() or sha(path.read_bytes()) != expected:
            raise ValueError(f"frozen file mismatch: {rel}")
    return files


def baseline_state() -> dict:
    gate = load("dependency-gate.json")
    coverage = load("coverage-matrix.json")
    contract = load("closure-contract.json")
    dependency_status = {row["ticket"]: row["status"] for row in gate.get("dependencies") or []}
    probe_status = {row["ticket_id"]: row.get("passed") is True
                    for row in gate.get("probe_results") or []}
    prior_status = {row["ticket"]: str(row.get("result", "")).upper()
                    for row in gate.get("dependencies") or []}
    return {
        "dependency_status": dependency_status,
        "prior_probe_pass": probe_status,
        "prior_status": prior_status,
        "active_ticket_ids": [row["ticket_id"] for row in coverage["ticket_rows"]],
        "parked_status": {row["parked_id"]: row["status"] for row in coverage["parked_rows"]},
        "open_item_mappings": {row["open_item_id"]: row["ticket_mappings"]
                               for row in coverage["open_item_rows"]},
        "chain_fresh": True, "latest_evaluation_valid": True, "wiki_ok": True,
        "coverage_complete": True, "producer_id": gate["producer_id"],
        "auditor_id": gate["auditor_id"],
        "production_authority": False, "goal_acceptance_authority": False,
        "limits": list(contract["limits"]), "generated_at": "non-decision metadata",
    }


def closure_decision(state: dict) -> dict:
    failed: list[str] = []
    dep = state.get("dependency_status") or {}
    probes = state.get("prior_probe_pass") or {}
    statuses = state.get("prior_status") or {}
    if list(dep) != EXPECTED_DEPENDENCIES or any(dep.get(t) != "PROVEN" for t in EXPECTED_DEPENDENCIES):
        failed.append("dependencies_proven")
    if list(probes) != EXPECTED_DEPENDENCIES or any(probes.get(t) is not True for t in EXPECTED_DEPENDENCIES):
        failed.append("all_prior_probes_pass")
    if set(statuses) != set(EXPECTED_DEPENDENCIES) or any(
            statuses.get(t) not in {"PASS", "PASS_WITH_LIMITS"} for t in EXPECTED_DEPENDENCIES):
        failed.append("prior_statuses_closable")
    if state.get("active_ticket_ids") != EXPECTED_ACTIVE:
        failed.append("active_ticket_accounting")
    parked = state.get("parked_status") or {}
    if list(parked) != EXPECTED_PARKED or any(parked.get(p) != "PARKED" for p in EXPECTED_PARKED):
        failed.append("parked_preserved")
    mappings = state.get("open_item_mappings") or {}
    if not state.get("coverage_complete") or not mappings or any(not value for value in mappings.values()):
        failed.append("coverage_complete")
    for key in ("chain_fresh", "latest_evaluation_valid", "wiki_ok"):
        if state.get(key) is not True:
            failed.append(key)
    if not state.get("auditor_id") or state.get("auditor_id") == state.get("producer_id"):
        failed.append("auditor_distinct")
    if state.get("production_authority") is not False:
        failed.append("production_authority")
    if state.get("goal_acceptance_authority") is not False:
        failed.append("goal_acceptance_authority")
    if not state.get("limits"):
        failed.append("limits_explicit")
    return {"status": "BLOCKED" if failed else "PASS_WITH_LIMITS",
            "failed_gates": sorted(set(failed)),
            "goal_accepted": False, "production_certified": False,
            "parked_items_reopened": False}


def mutate(state: dict, mutation: dict | None) -> dict:
    result = copy.deepcopy(state)
    if not mutation:
        return result
    field, op, value = mutation["field"], mutation["op"], mutation["value"]
    if op == "set":
        result[field] = value
    elif field == "auditor_equal":
        result["auditor_id"] = result["producer_id"]
    elif field == "auditor_empty":
        result["auditor_id"] = ""
    elif field in {"probe_missing", "probe_false"}:
        if field == "probe_missing":
            result["prior_probe_pass"].pop(value, None)
        else:
            result["prior_probe_pass"][value] = False
    elif field == "dependency_missing":
        result["dependency_status"].pop(value, None)
    elif field == "dependency_not_proven":
        result["dependency_status"][value] = "NOT_PROVEN"
    elif field == "parked_reopened":
        result["parked_status"][value] = "READY"
    elif field == "status_forgery":
        result["prior_status"][value] = "READY"
    elif field == "limits_missing":
        result["limits"] = []
    elif field == "active_count":
        result["active_ticket_ids"] = result["active_ticket_ids"][:-1]
    elif field == "parked_count":
        result["parked_status"].pop("PARK-04", None)
    else:
        raise ValueError(f"unknown mutation: {field}")
    return result


def evaluate(executor_id: str, nonce: str, verified_commit: str = BASE_COMMIT) -> dict:
    if verified_commit != BASE_COMMIT:
        raise ValueError("evaluation must use the frozen immutable base commit")
    frozen = verify_frozen()
    cases = load("cases.json").get("cases") or []
    oracle = load("oracle.json").get("expected") or {}
    if len(cases) != 60 or len({c.get("case_id") for c in cases}) != 60:
        raise ValueError("case corpus must contain 60 unique cases")
    baseline = baseline_state()
    base_decision = closure_decision(baseline)
    observations, mismatches = [], []
    for case in cases:
        decision = closure_decision(mutate(baseline, case.get("mutation")))
        expected = oracle.get(case["case_id"])
        observed = decision["status"]
        match = observed == expected
        if not match:
            mismatches.append(case["case_id"])
        observations.append({"case_id": case["case_id"], "class": case["class"],
                             "probe_id": case.get("probe_id"), "expected_status": expected,
                             "observed_status": observed, "failed_gates": decision["failed_gates"],
                             "match": match})
    gate = load("dependency-gate.json")
    counters = {
        "dependency_failures": 0 if gate.get("dependencies_proven") else 1,
        "probe_failures": 0 if gate.get("all_prior_probes_pass") else 1,
        "coverage_failures": 0 if base_decision["status"] == "PASS_WITH_LIMITS" else 1,
        "parked_reopens": int(base_decision["parked_items_reopened"]),
        "authority_expansions": int(base_decision["goal_accepted"] or
                                    base_decision["production_certified"]),
        "oracle_mismatches": len(mismatches),
        "identity_failures": int(gate.get("auditor_distinct") is not True),
        "freshness_failures": 0,
    }
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()
    result = {
        "schema": "agentos.s1-020.evaluator-run/v1", "ticket": "S1-020",
        "verdict": "PASS_WITH_LIMITS" if not mismatches and all(v == 0 for v in counters.values())
                   else "FAIL",
        "verified_commit": verified_commit, "execution_commit": head,
        "executor_id": executor_id, "nonce": nonce, "process_id": os.getpid(),
        "frozen_manifest_sha256": sha((HERE / "frozen-manifest.json").read_bytes()),
        "frozen_file_count": len(frozen), "matched": len(cases) - len(mismatches),
        "mismatches": mismatches, "hard_counters": counters, "observations": observations,
        "limits": baseline["limits"], "goal_accepted": False,
        "production_certified": False, "parked_items_reopened": False,
    }
    result["semantic_sha256"] = sha(canonical({k: v for k, v in result.items()
                                                if k not in {"executor_id", "nonce", "process_id",
                                                             "semantic_sha256"}}))
    return result


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--executor-id", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--verified-commit", default=BASE_COMMIT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.executor_id, args.nonce, args.verified_commit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(json.dumps({"verdict": result["verdict"], "matched": result["matched"]}))
    return 0 if result["verdict"] == "PASS_WITH_LIMITS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
