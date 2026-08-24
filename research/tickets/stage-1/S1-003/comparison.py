#!/usr/bin/env python3
"""Compare structural oracle results (raw-results.json) with pySHACL engine
results (engine-results.json) for S1-003.

Acceptance: 26/26 agreement on (conforms, intended primary reason).

This is a pure JSON consumer — it does NOT import rdflib or pyshacl and can
run in the stdlib-only core interpreter.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def compare(engine_results: dict, structural_results: dict) -> dict[str, Any]:
    """Compare engine vs structural oracle across all profile runs.

    Returns a comparison report with per-run details and overall verdict.
    """
    # Build structural lookup: (fixture_id, profile) -> result
    struct_by_key: dict[tuple[str, str], dict] = {}
    for r in structural_results["results"]:
        key = (r["fixture_id"], r.get("profile", "open"))
        struct_by_key[key] = r

    per_run: list[dict[str, Any]] = []
    total_runs = 0
    matched = 0
    mismatches: list[str] = []

    for r in engine_results["results"]:
        total_runs += 1
        fid = r["fixture_id"]
        profile = r["profile"]
        sr = struct_by_key.get((fid, profile), {})

        # Check 1: conforms matches (engine observed vs structural observed)
        c1 = (r["observed_conforms"] == sr.get("observed_conforms"))
        # Check 2: primary reason — engine must produce the expected reason in
        # its normalized violations
        c2 = True
        if not r["expected_conforms"] and r.get("expected_primary_reason"):
            c2 = r["expected_primary_reason"] in r.get("normalized_violations", [])
        # Check 3: structural oracle also observed the same primary reason
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

    verdict = "pass" if matched == total_runs and len(mismatches) == 0 else "fail"
    return {
        "total_runs": total_runs,
        "matched": matched,
        "mismatches": mismatches,
        "per_run": per_run,
        "verdict": verdict,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="S1-003 structural vs pySHACL comparison")
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
        "output": str(args.out),
    }, sort_keys=True))
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
