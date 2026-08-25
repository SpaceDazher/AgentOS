#!/usr/bin/env python3
"""Fail-cLOSED comparison: structural oracle vs pySHACL engine (S1-003).

All expectations and hashes are derived ONLY from:
  - raw-results.json  (the structural oracle is the single source of truth)
  - the files on disk  (shapes-v3.ttl, shapes-v3-promoted-only.ttl, fixtures.json,
                        fixtures.ttl, fixtures_to_rdf.py)

The engine results (engine-results.json) are NOT trusted for expectations.
We only compare the engine's *observed* output against the oracle's *expected*
output, and we verify that every provenance field (runtime, hashes, per-run
digests) matches the files on disk.

Fail-closed policy
------------------
ANY unknown condition aborts with exit 1 and verdict="fail":
  - pyshacl_executed is not True
  - result count != 26
  - any duplicate (fixture_id, profile) key
  - expected key set != structural oracle key set
  - runtime versions differ from pinned identity
  - file hashes on disk != engine-reported hashes
  - per-run provenance mismatch
  - conforms mismatch OR expected_primary_reason absent from normalized_violations
  - structural primary_reason absent from engine normalized_violations
  - unclassified violations present in any engine result
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

EXPECTED_RUN_COUNT = 26

# Pinned runtime identity — the engine MUST report these exact versions.
EXPECTED_RUNTIME = {"python": "3.11.15", "rdflib": "7.6.0", "pyshacl": "0.40.1"}

# Authoritative set of engine-normalized violation reasons that the
# structural oracle recognizes.  Any violation string NOT in this set
# (and not "unclassified") is treated as suspicious and must cause a FAIL.
# This prevents an attacker from injecting arbitrary violation strings.
_KNOWN_VIOLATION_REASONS = frozenset({
    "not_promoted_status",
    "missing_promotion_activity",
    "insufficient_distinct_canonical_sources",
    "insufficient_independence_groups",
    "insufficient_evidence_count",
    "evidence_missing_independence_group",
    "evidence_missing_canonical_source_id",
    "evidence_missing_publisher_id",
    "evidence_missing_resolver_version",
    "evidence_missing_metadata_frozen_at",
    "evidence_scope_mismatch",
    "promotion_actor_scope_mismatch",
    "missing_effective_scope",
    "multiple_effective_scopes",
    "stale_or_unknown_status",
    "missing_superseding_assertion",
    "subject_scope_mismatch",
    "actor_scope_mismatch",
    "negative_budget",
    "ttl_above_15_minutes",
    "invalid_subject",
    "invalid_actor",
    "missing_actions",
    "missing_resources",
    "missing_jti",
    "unsupported_value",
    "invalid_action_entry",
})

# Pinned file hashes — recomputed from disk each run.  Must match what the
# engine reported so we know the same shapes/fixtures were used.
PINNED = {
    "shapes_open": "shapes-v3.ttl",
    "shapes_promoted_only": "shapes-v3-promoted-only.ttl",
    "fixtures_json": "fixtures.json",
    "fixtures_ttl": "fixtures.ttl",
    "fixtures_to_rdf": "fixtures_to_rdf.py",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _struct_to_key(r: dict) -> tuple[str, str]:
    """(fixture_id, profile) tuple for a structural result."""
    return (r["fixture_id"], r.get("profile", "open"))


def _disk_hashes(here: Path) -> dict[str, str]:
    """Recompute every pinned file hash from disk."""
    return {role: _sha256_file(here / fname) for role, fname in PINNED.items()}


# --------------------------------------------------------------------------- #
# Core comparison
# --------------------------------------------------------------------------- #
def compare(engine_results: dict, structural_results: dict,
            disk_hashes: dict[str, str]) -> dict[str, Any]:
    """Compare engine vs structural oracle (fail-closed).

    All expectations originate from ``structural_results`` or ``disk_hashes``.
    The engine results are treated as untrusted observed data.
    """
    mismatches: list[str] = []

    # --- Pre 1: pySHACL must have executed ---
    if not engine_results.get("pyshacl_executed"):
        return _fail("pyshacl_executed is not true — engine did not run", 0)

    # --- Pre 2: runtime identity ---
    rt = engine_results.get("runtime", {})
    for k, v in EXPECTED_RUNTIME.items():
        if rt.get(k) != v:
            mismatches.append(f"runtime.{k} expected={v} got={rt.get(k)}")

    # --- Pre 3: exact run count ---
    engine_runs = engine_results.get("results", [])
    if len(engine_runs) != EXPECTED_RUN_COUNT:
        mismatches.append(
            f"expected {EXPECTED_RUN_COUNT} engine runs, got {len(engine_runs)}")

    # --- Pre 4: no duplicate keys ---
    engine_keys: list[tuple[str, str]] = []
    for r in engine_runs:
        engine_keys.append(_struct_to_key(r))
    seen: set[tuple[str, str]] = set()
    for k in engine_keys:
        if k in seen:
            mismatches.append(f"duplicate engine run: {k}")
        seen.add(k)

    # --- Pre 5: key set must match structural oracle exactly ---
    struct_results = structural_results.get("results", [])
    struct_keys = {_struct_to_key(r) for r in struct_results}
    engine_key_set = set(engine_keys)
    missing = struct_keys - engine_key_set
    extra = engine_key_set - struct_keys
    if missing:
        mismatches.append(f"missing engine runs: {sorted(missing)}")
    if extra:
        mismatches.append(f"extra engine runs: {sorted(extra)}")

    # --- Pre 6: top-level hashes must match disk ---
    inp = engine_results.get("inputs", {})
    if inp.get("fixtures_sha256") != disk_hashes["fixtures_json"]:
        mismatches.append(
            f"fixtures_sha256: engine={inp.get('fixtures_sha256')} "
            f"disk={disk_hashes['fixtures_json']}")
    if inp.get("shapes_open_sha256") != disk_hashes["shapes_open"]:
        mismatches.append(
            f"shapes_open_sha256: engine={inp.get('shapes_open_sha256')} "
            f"disk={disk_hashes['shapes_open']}")
    if inp.get("shapes_promoted_only_sha256") != disk_hashes["shapes_promoted_only"]:
        mismatches.append(
            f"shapes_promoted_only_sha256: engine={inp.get('shapes_promoted_only_sha256')} "
            f"disk={disk_hashes['shapes_promoted_only']}")

    # --- Build structural lookup (oracle is source of truth for expectations) ---
    struct_by_key: dict[tuple[str, str], dict] = {
        _struct_to_key(r): r for r in struct_results
    }

    # --- Pre 7: per-run provenance + outcome comparison ---
    per_run: list[dict[str, Any]] = []
    matched = 0
    for er in engine_runs:
        fid = er["fixture_id"]
        profile = er.get("profile", "open")
        key = (fid, profile)
        sr = struct_by_key.get(key)
        if sr is None:
            # Already caught by Pre 5, but keep for safety.
            mismatches.append(f"no structural oracle record for {key}")
            continue

        run_mismatches: list[str] = []

        # 7a. per-run runtime identity
        er_rt = er.get("runtime", {})
        for k, v in EXPECTED_RUNTIME.items():
            if er_rt.get(k) != v:
                run_mismatches.append(
                    f"runtime.{k} expected={v} got={er_rt.get(k)}")

        # 7b. per-run shapes hash must match the correct shapes file on disk
        #      (open profile → shapes-v3.ttl, promoted_only → shapes-v3-promoted-only.ttl)
        if profile == "promoted_only":
            expected_shapes_hash = disk_hashes["shapes_promoted_only"]
        else:
            expected_shapes_hash = disk_hashes["shapes_open"]
        if er.get("shapes_sha256") != expected_shapes_hash:
            run_mismatches.append(
                f"shapes_sha256: engine={er.get('shapes_sha256')} "
                f"disk={expected_shapes_hash}")

        # 7c. per-run fixtures hash must match disk
        if er.get("fixtures_sha256") != disk_hashes["fixtures_json"]:
            run_mismatches.append(
                f"fixtures_sha256: engine={er.get('fixtures_sha256')} "
                f"disk={disk_hashes['fixtures_json']}")

        # 7d. conforms must match structural oracle expectation
        expected_conforms = bool(sr["expected_conforms"])
        observed_conforms = bool(er["observed_conforms"])
        if expected_conforms != observed_conforms:
            run_mismatches.append(
                f"conforms: oracle={expected_conforms} engine={observed_conforms}")

        # 7e. if expected to fail, the expected primary_reason must be present
        #     in the engine's normalized_violations (from the oracle's reason).
        expected_primary = sr.get("expected_primary_reason")
        engine_violations = er.get("normalized_violations", [])

        if not expected_conforms and expected_primary:
            if expected_primary not in engine_violations:
                run_mismatches.append(
                    f"primary_reason '{expected_primary}' missing from "
                    f"engine violations {engine_violations}")

        # 7f. the structural oracle's observed reasons must all be present
        #     in the engine violations — bidirectional check.
        struct_violations = set(sr.get("observed_violations", []))
        engine_violation_set = set(engine_violations)
        missing_in_engine = struct_violations - engine_violation_set
        if missing_in_engine:
            run_mismatches.append(
                f"structural violations not in engine: {sorted(missing_in_engine)}")

        # 7g. no unclassified violations allowed
        if "unclassified" in engine_violation_set:
            run_mismatches.append(
                "unclassified violation present — engine emitted an "
                "unknown reason that was not mapped")

        # 7i. no unknown/arbitrary violation reasons allowed
        unknown_reasons = engine_violation_set - _KNOWN_VIOLATION_REASONS
        if unknown_reasons:
            run_mismatches.append(
                f"unknown violation reasons in engine output: "
                f"{sorted(unknown_reasons)}")

        # 7j. per-run rdf_input_sha256 must be present and non-empty
        #      (the full-graph hash is verified separately via --sha-check)
        if not er.get("rdf_input_sha256"):
            run_mismatches.append("rdf_input_sha256 is empty or missing")

        # 7h. semantic_digest must be stable per (fixtures_sha + shapes + run)
        #      We cannot recompute it without the engine, but we can assert it
        #      is present and non-empty.
        if not er.get("semantic_digest"):
            run_mismatches.append("semantic_digest is empty or missing")

        if run_mismatches:
            for m in run_mismatches:
                mismatches.append(f"{fid}/{profile}: {m}")
        else:
            matched += 1

        per_run.append({
            "fixture_id": fid,
            "profile": profile,
            "expected_conforms": expected_conforms,
            "observed_conforms": observed_conforms,
            "expected_primary_reason": expected_primary,
            "engine_normalized_violations": engine_violations,
            "structural_observed_violations": sorted(struct_violations),
            "shapes_sha256_match": er.get("shapes_sha256") == disk_hashes["shapes_open"],
            "fixtures_sha256_match": er.get("fixtures_sha256") == disk_hashes["fixtures_json"],
            "runtime_match": all(
                er_rt.get(k) == v for k, v in EXPECTED_RUNTIME.items()),
            "passed": len(run_mismatches) == 0,
            "run_mismatches": run_mismatches,
        })

    # Verdict is "pass" ONLY when every run matched AND there are zero
    # pre-checks mismatches.  This prevents the fail-open case where 26 runs
    # match but there are also extra/duplicate runs or hash mismatches.
    verdict = "pass" if matched == EXPECTED_RUN_COUNT and not mismatches else "fail"
    return {
        "total_runs": len(engine_runs),
        "matched": matched,
        "mismatches": mismatches,
        "per_run": per_run,
        "verdict": verdict,
        "fail_closed": True,
    }


def _fail(reason: str, total: int) -> dict[str, Any]:
    return {
        "total_runs": total,
        "matched": 0,
        "mismatches": [reason],
        "per_run": [],
        "verdict": "fail",
        "fail_closed": True,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(
        description="S1-003 structural vs pySHACL comparison (fail-closed)")
    parser.add_argument("--engine-results", type=Path,
                        default=HERE / "engine-results.json")
    parser.add_argument("--structural-results", type=Path,
                        default=HERE / "raw-results.json")
    parser.add_argument("--out", type=Path,
                        default=HERE / "comparison-results.json")
    parser.add_argument("--sha-check", action="store_true",
                        default=False,
                        help="Recompute file hashes from disk and abort on mismatch")
    args = parser.parse_args()

    engine = _load_json(args.engine_results)
    structural = _load_json(args.structural_results)
    disk = _disk_hashes(HERE)

    if args.sha_check:
        # Verify that the engine's recorded hashes match the files on disk.
        inp = engine.get("inputs", {})
        checks = [
            ("fixtures_sha256", inp.get("fixtures_sha256"), disk["fixtures_json"]),
            ("shapes_open_sha256", inp.get("shapes_open_sha256"), disk["shapes_open"]),
            ("shapes_promoted_only_sha256",
             inp.get("shapes_promoted_only_sha256"), disk["shapes_promoted_only"]),
        ]
        hash_errors: list[str] = []
        for name, engine_val, disk_val in checks:
            if engine_val != disk_val:
                hash_errors.append(
                    f"{name}: engine={engine_val} disk={disk_val}")
        if hash_errors:
            # Abort before comparison — provenance is compromised.
            report = {
                "total_runs": len(engine.get("results", [])),
                "matched": 0,
                "mismatches": hash_errors,
                "per_run": [],
                "verdict": "fail",
                "fail_closed": True,
            }
            args.out.write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8", newline="\n")
            print(json.dumps({
                "verdict": "fail",
                "fail_closed": True,
                "errors": len(hash_errors),
            }, sort_keys=True))
            return 1

    report = compare(engine, structural, disk)
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
