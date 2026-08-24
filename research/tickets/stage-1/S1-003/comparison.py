#!/usr/bin/env python3
"""Compare structural oracle results (raw-results.json) with pySHACL engine
results (engine-results.json) for S1-003.

Acceptance: 26/26 agreement on (conforms, intended primary reason).

This is a pure JSON consumer — it does NOT import rdflib or pyshacl and can
run in the stdlib-only core interpreter.

Fail-closed: verifies pyshacl_executed, exact run count (26), key-set
completeness, no duplicates, runtime identity, and hashes match before
comparing outcomes.  Any gap => verdict=fail.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

EXPECTED_RUN_COUNT = 26
EXPECTED_RUNTIME = {"python": "3.11.15", "rdflib": "7.6.0", "pyshacl": "0.40.1"}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _expected_keys(structural_results: dict) -> set[tuple[str, str]]:
    """Build the set of (fixture_id, profile) pairs the structural oracle ran."""
    keys: set[tuple[str, str]] = set()
    for r in structural_results["results"]:
        keys.add((r["fixture_id"], r.get("profile", "open")))
    return keys


def compare(engine_results: dict, structural_results: dict) -> dict[str, Any]:
    """Compare engine vs structural oracle across all profile runs.

    Fail-closed: every precondition is verified before outcome comparison.
    """
    mismatches: list[str] = []

    # --- Precondition 1: pyshacl_executed must be true ---
    if not engine_results.get("pyshacl_executed"):
        mismatches.append("pyshacl_executed is not true — engine was not executed")
        return {
            "total_runs": len(engine_results.get("results", [])),
            "matched": 0,
            "mismatches": mismatches,
            "per_run": [],
            "verdict": "fail",
            "fail_closed": True,
        }

    # --- Precondition 2: runtime versions must match expected ---
    rt = engine_results.get("runtime", {})
    for k, v in EXPECTED_RUNTIME.items():
        if rt.get(k) != v:
            mismatches.append(f"runtime.{k} expected={v} got={rt.get(k)}")

    # --- Precondition 3: exactly EXPECTED_RUN_COUNT runs ---
    engine_keys: list[tuple[str, str]] = []
    for r in engine_results.get("results", []):
        engine_keys.append((r["fixture_id"], r.get("profile", "open")))

    if len(engine_keys) != EXPECTED_RUN_COUNT:
        mismatches.append(
            f"expected {EXPECTED_RUN_COUNT} engine runs, got {len(engine_keys)}"
        )

    # --- Precondition 4: no duplicate keys ---
    seen: set[tuple[str, str]] = set()
    for k in engine_keys:
        if k in seen:
            mismatches.append(f"duplicate engine run: {k}")
        seen.add(k)

    # --- Precondition 5: key set must match structural oracle exactly ---
    expected_keys = _expected_keys(structural_results)
    engine_key_set = set(engine_keys)
    missing_keys = expected_keys - engine_key_set
    extra_keys = engine_key_set - expected_keys
    if missing_keys:
        mismatches.append(f"missing engine runs: {sorted(missing_keys)}")
    if extra_keys:
        mismatches.append(f"extra engine runs: {sorted(extra_keys)}")

    if mismatches:
        return {
            "total_runs": len(engine_keys),
            "matched": 0,
            "mismatches": mismatches,
            "per_run": [],
            "verdict": "fail",
            "fail_closed": True,
        }

    # --- Precondition 6: hashes must match ---
    inp = engine_results.get("inputs", {})
    expected_fixtures_sha = structural_results.get("inputs", {}).get("fixtures_sha256")
    if expected_fixtures_sha and inp.get("fixtures_sha256") != expected_fixtures_sha:
        mismatches.append(
            f"fixtures_sha256 mismatch: engine={inp.get('fixtures_sha256')} "
            f"structural={expected_fixtures_sha}"
        )

    if mismatches:
        return {
            "total_runs": len(engine_keys),
            "matched": 0,
            "mismatches": mismatches,
            "per_run": [],
            "verdict": "fail",
            "fail_closed": True,
        }

    # --- Build structural lookup ---
    struct_by_key: dict[tuple[str, str], dict] = {}
    for r in structural_results["results"]:
        key = (r["fixture_id"], r.get("profile", "open"))
        struct_by_key[key] = r

    # --- Outcome comparison ---
    per_run: list[dict[str, Any]] = []
    matched = 0
    for r in engine_results["results"]:
        fid = r["fixture_id"]
        profile = r["profile"]
        sr = struct_by_key.get((fid, profile), {})

        c1 = r["observed_conforms"] == sr.get("observed_conforms")
        c2 = True
        if not r["expected_conforms"] and r.get("expected_primary_reason"):
            c2 = r["expected_primary_reason"] in r.get("normalized_violations", [])
        c3 = True
        sr_pr = sr.get("expected_primary_reason")
        if not r["expected_conforms"] and sr_pr:
            c3 = sr_pr in set(sr.get("observed_violations", []))

        passed = c1 and c2 and c3
        if passed:
            matched += 1
        else:
            if not c1:
                mismatches.append(
                    f"{fid}/{profile}: conforms engine={r['observed_conforms']} "
                    f"vs structural={sr.get('observed_conforms')}"
                )
            if not c2:
                mismatches.append(
                    f"{fid}/{profile}: engine primary_reason "
                    f"'{r.get('expected_primary_reason')}' not in "
                    f"{r.get('normalized_violations', [])}"
                )
            if not c3:
                mismatches.append(
                    f"{fid}/{profile}: structural primary_reason "
                    f"'{sr_pr}' not in observed_violations "
                    f"{sr.get('observed_violations', [])}"
                )

        per_run.append({
            "fixture_id": fid,
            "profile": profile,
            "engine_conforms": r["observed_conforms"],
            "structural_conforms": sr.get("observed_conforms"),
            "engine_primary": r.get("expected_primary_reason"),
            "structural_primary": sr.get("expected_primary_reason"),
            "engine_violations": r.get("normalized_violations", []),
            "structural_violations": sorted(sr.get("observed_violations", [])),
            "conforms_match": c1,
            "primary_reason_match": c2,
            "structural_primary_confirmed": c3,
            "passed": passed,
        })

    verdict = "pass" if matched == EXPECTED_RUN_COUNT and len(mismatches) == 0 else "fail"
    return {
        "total_runs": len(engine_keys),
        "matched": matched,
        "mismatches": mismatches,
        "per_run": per_run,
        "verdict": verdict,
        "fail_closed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="S1-003 structural vs pySHACL comparison (fail-closed)")
    parser.add_argument("--engine-results", type=Path,
                        default=HERE / "engine-results.json")
    parser.add_argument("--structural-results", type=Path,
                        default=HERE / "raw-results.json")
    parser.add_argument("--out", type=Path,
                        default=HERE / "comparison-results.json")
    args = parser.parse_args()

    engine = _load_json(args.engine_results)
    structural = _load_json(args.structural_results)

    report = compare(engine, structural)
    args.out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")

    print(json.dumps({
        "verdict": report["verdict"],
        "total_runs": report["total_runs"],
        "matched": report["matched"],
        "mismatches": len(report["mismatches"]),
        "fail_closed": report["fail_closed"],
        "output": str(args.out),
    }, sort_keys=True))
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
