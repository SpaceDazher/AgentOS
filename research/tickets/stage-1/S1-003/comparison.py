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
ENGINE_SCHEMA = "agentos.s1-003-engine-results/v2"
SEMANTIC_TUPLE_SCHEMA = "agentos.s1-003-semantic/v1"
CONFORMS_REASON = "__conforms__"

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
    "validate_structural": "validate_structural.py",
    "validate_pyshacl": "validate_pyshacl.py",
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


def _compute_fixture_rdf_hash(fixture: dict, catalog: dict) -> str:
    """Recompute the SHA-256 of the single-fixture Turtle graph.

    Uses fixtures_to_rdf.build_graph which is stdlib-only (no rdflib needed
    for Turtle *generation* — only the shapes evaluation requires rdflib).
    This lets the comparator independently verify the engine's per-run
    rdf_input_sha256 field.
    """
    sys.path.insert(0, str(HERE))
    from fixtures_to_rdf import build_graph
    doc = {"evidence_catalog": catalog, "fixtures": [fixture]}
    turtle, sha = build_graph(doc)
    return sha


import re as _re
_HEX_SHA256_RE = _re.compile(r"^[0-9a-f]{64}$")


def _is_hex_sha256(value: Any) -> bool:
    """Return True only if value is a string of exactly 64 lowercase hex chars."""
    return isinstance(value, str) and _HEX_SHA256_RE.match(value) is not None


def _canonical_semantic_tuples(fixture_id: str, profile: str,
                               conforms: bool,
                               violations: list[str]) -> list[str]:
    """Build the structural semantic-evidence contract for one run.

    The tuple deliberately contains only stable, oracle-owned values.  It is
    independent of pySHACL validation-result blank nodes while still binding
    the evidence to the exact fixture/profile/outcome and normalized reason.
    Each tuple is a canonical JSON string so the comparator can validate both
    its shape and its byte representation without importing rdflib.
    """
    reasons = sorted(set(violations))
    if not reasons:
        reasons = [CONFORMS_REASON]
    outcome = "conforms" if conforms else "violates"
    return [json.dumps(
        [SEMANTIC_TUPLE_SCHEMA, fixture_id, profile, outcome, reason],
        ensure_ascii=False, separators=(",", ":"),
    ) for reason in reasons]


def _semantic_digest_from_tuples(tuples: list[str]) -> str:
    """Hash the exact canonical tuple bytes, including their required order."""
    return hashlib.sha256("\n".join(tuples).encode("utf-8")).hexdigest()


def _expected_semantic_tuples(sr: dict[str, Any], fixture_id: str,
                              profile: str) -> list[str]:
    """Derive authoritative tuples from a structural-oracle result."""
    observed = sr.get("observed_conforms")
    if type(observed) is not bool:
        observed = bool(sr.get("expected_conforms"))
    violations = sr.get("observed_violations", [])
    if not isinstance(violations, list) or not all(
            isinstance(item, str) for item in violations):
        violations = []
    return _canonical_semantic_tuples(fixture_id, profile, observed, violations)


def _validate_semantic_tuples(value: Any, expected: list[str]) -> list[str]:
    """Return schema errors for a semantic-tuple list.

    Equality with ``expected`` is intentional: tuple content is anchored to
    structural oracle data, not merely to a self-consistent digest supplied by
    the untrusted engine artifact.
    """
    errors: list[str] = []
    if not isinstance(value, list):
        return [f"semantic_tuples must be a list[str] (got {value!r})"]
    if not all(type(item) is str for item in value):
        errors.append("semantic_tuples must contain only strings")
        return errors
    if value != sorted(value):
        errors.append("semantic_tuples must be sorted")
    if len(value) != len(set(value)):
        errors.append("semantic_tuples must not contain duplicates")
    for item in value:
        try:
            parsed = json.loads(item)
        except (TypeError, ValueError) as exc:
            errors.append(f"semantic_tuples contains invalid JSON tuple: {exc}")
            continue
        if not isinstance(parsed, list) or len(parsed) != 5 \
                or not all(type(part) is str for part in parsed):
            errors.append(f"semantic_tuples tuple has invalid format: {item!r}")
            continue
        canonical = json.dumps(parsed, ensure_ascii=False,
                               separators=(",", ":"))
        if canonical != item:
            errors.append(f"semantic_tuples tuple is not canonical: {item!r}")
        if parsed[0] != SEMANTIC_TUPLE_SCHEMA:
            errors.append(f"semantic_tuples tuple has unknown schema: {item!r}")
    if value != expected:
        errors.append(
            f"semantic_tuples do not match structural oracle: "
            f"engine={value!r} expected={expected!r}")
    return errors


def _disk_hashes(here: Path) -> dict[str, str]:
    """Recompute every pinned file hash from disk."""
    return {role: _sha256_file(here / fname) for role, fname in PINNED.items()}


def _object_keys(value: Any, field: str, expected: set[str]) -> list[str]:
    """Require a JSON object with exactly the declared keys."""
    if not isinstance(value, dict):
        return [f"{field} must be a JSON object"]
    errors: list[str] = []
    actual = set(value)
    missing = expected - actual
    extra = actual - expected
    if missing:
        errors.append(f"{field} missing keys: {sorted(missing)}")
    if extra:
        errors.append(f"{field} has unknown keys: {sorted(extra)}")
    return errors


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
    if not isinstance(engine_results, dict):
        return _fail("engine results must be a JSON object", 0)
    if not isinstance(structural_results, dict):
        return _fail("structural results must be a JSON object", 0)

    # Load fixtures for per-run RDF hash verification.  The fixtures and all
    # generator inputs are local deterministic sources, never engine authority.
    fixtures_doc = _load_json(HERE / "fixtures.json")
    catalog = fixtures_doc.get("evidence_catalog", {})
    fixture_map = {
        f.get("id"): f for f in fixtures_doc.get("fixtures", [])
        if isinstance(f, dict) and isinstance(f.get("id"), str)
    }

    # --- Top-level schema and execution gate --------------------------------
    if engine_results.get("schema") != ENGINE_SCHEMA:
        mismatches.append(
            f"schema expected={ENGINE_SCHEMA!r} got={engine_results.get('schema')!r}")
    py_exec = engine_results.get("pyshacl_executed")
    if py_exec is not True:
        return _fail(
            f"pyshacl_executed is not boolean True (got {py_exec!r} of type "
            f"{type(py_exec).__name__}) — engine did not run", 0)

    # --- Runtime identity and top-level provenance ---------------------------
    rt = engine_results.get("runtime")
    mismatches.extend(_object_keys(rt, "runtime", set(EXPECTED_RUNTIME)))
    if isinstance(rt, dict):
        for k, v in EXPECTED_RUNTIME.items():
            if rt.get(k) != v:
                mismatches.append(f"runtime.{k} expected={v} got={rt.get(k)}")

    input_to_disk = {
        "fixtures_sha256": "fixtures_json",
        "shapes_open_sha256": "shapes_open",
        "shapes_promoted_only_sha256": "shapes_promoted_only",
        "rdf_input_sha256": "fixtures_ttl",
        "validate_structural_sha256": "validate_structural",
        "fixtures_to_rdf_sha256": "fixtures_to_rdf",
        "validate_pyshacl_sha256": "validate_pyshacl",
    }
    inp = engine_results.get("inputs")
    mismatches.extend(_object_keys(inp, "inputs", set(input_to_disk)))
    if isinstance(inp, dict):
        for field, disk_key in input_to_disk.items():
            value = inp.get(field)
            if not _is_hex_sha256(value):
                mismatches.append(f"{field} must be a lowercase SHA-256 digest")
            elif value != disk_hashes[disk_key]:
                mismatches.append(
                    f"{field}: engine={value} disk={disk_hashes[disk_key]}")

    # --- Oracle and run key-set checks ---------------------------------------
    struct_results = structural_results.get("results")
    if not isinstance(struct_results, list):
        return _fail("structural results.results must be a list", 0)
    if len(struct_results) != EXPECTED_RUN_COUNT:
        mismatches.append(
            f"expected {EXPECTED_RUN_COUNT} structural runs, got {len(struct_results)}")

    def record_key(record: Any, label: str, index: int) -> tuple[str, str] | None:
        if not isinstance(record, dict):
            mismatches.append(f"{label}[{index}] must be a JSON object")
            return None
        fid = record.get("fixture_id")
        profile = record.get("profile")
        if not isinstance(fid, str) or not fid:
            mismatches.append(f"{label}[{index}].fixture_id must be a non-empty string")
            return None
        if profile not in {"open", "promoted_only"}:
            mismatches.append(
                f"{label}[{index}].profile must be open/promoted_only")
            return None
        return fid, profile

    struct_keys_list = [record_key(r, "structural", i)
                        for i, r in enumerate(struct_results)]
    struct_keys = {key for key in struct_keys_list if key is not None}
    if len(struct_keys) != len([key for key in struct_keys_list if key is not None]):
        mismatches.append("duplicate structural run key")

    engine_runs = engine_results.get("results")
    if not isinstance(engine_runs, list):
        return _fail("engine results.results must be a list", 0)
    if len(engine_runs) != EXPECTED_RUN_COUNT:
        mismatches.append(
            f"expected {EXPECTED_RUN_COUNT} engine runs, got {len(engine_runs)}")
    engine_keys_list = [record_key(r, "engine", i)
                        for i, r in enumerate(engine_runs)]
    engine_keys = {key for key in engine_keys_list if key is not None}
    if len(engine_keys) != len([key for key in engine_keys_list if key is not None]):
        mismatches.append("duplicate engine run key")
    missing = struct_keys - engine_keys
    extra = engine_keys - struct_keys
    if missing:
        mismatches.append(f"missing engine runs: {sorted(missing)}")
    if extra:
        mismatches.append(f"extra engine runs: {sorted(extra)}")

    struct_by_key: dict[tuple[str, str], dict] = {
        key: record for key, record in zip(struct_keys_list, struct_results)
        if key is not None and isinstance(record, dict)
    }

    # --- Top-level summary types are checked now and values after the loop ---
    engine_mismatches = engine_results.get("mismatches")
    if not isinstance(engine_mismatches, list) or not all(
            type(item) is str for item in engine_mismatches):
        mismatches.append("engine.mismatches must be a list[str]")
    elif engine_mismatches:
        mismatches.append(
            f"engine.mismatches expected=[] got={engine_mismatches!r}")
    engine_verdict = engine_results.get("verdict")
    if engine_verdict != "pass":
        mismatches.append(
            f"engine.verdict expected='pass' got={engine_verdict!r}")
    cov = engine_results.get("coverage")
    mismatches.extend(_object_keys(
        cov, "engine.coverage",
        {"fixture_count", "profile_run_count", "matched_run_count"}))
    summary = engine_results.get("summary")
    mismatches.extend(_object_keys(
        summary, "engine.summary",
        {"total_runs", "matched_runs", "mismatch_count", "verdict"}))

    # --- Per-run provenance and oracle comparison ----------------------------
    per_run: list[dict[str, Any]] = []
    matched = 0
    required_run_keys = {
        "fixture_id", "profile", "expected_conforms", "observed_conforms",
        "expected_primary_reason", "normalized_violations",
        "unclassified_violations", "report_text", "semantic_tuples",
        "semantic_digest", "runtime", "shapes_sha256", "fixtures_sha256",
        "rdf_input_sha256", "validate_structural_sha256",
        "fixtures_to_rdf_sha256", "validate_pyshacl_sha256", "matched",
    }
    per_run_hashes = {
        "fixtures_sha256": "fixtures_json",
        "validate_structural_sha256": "validate_structural",
        "fixtures_to_rdf_sha256": "fixtures_to_rdf",
        "validate_pyshacl_sha256": "validate_pyshacl",
    }
    for index, er in enumerate(engine_runs):
        key = engine_keys_list[index]
        if key is None:
            continue
        fid, profile = key
        sr = struct_by_key.get(key)
        if sr is None:
            mismatches.append(f"no structural oracle record for {key}")
            continue

        run_mismatches: list[str] = []
        run_mismatches.extend(_object_keys(er, f"{fid}/{profile}", required_run_keys))

        expected_conforms = sr.get("expected_conforms")
        oracle_observed = sr.get("observed_conforms")
        if type(expected_conforms) is not bool:
            run_mismatches.append("structural expected_conforms is not boolean")
            expected_conforms = False
        if type(oracle_observed) is not bool:
            run_mismatches.append("structural observed_conforms is not boolean")
            oracle_observed = expected_conforms
        if expected_conforms != oracle_observed:
            run_mismatches.append(
                f"structural oracle expected/observed conforms disagree: "
                f"expected={expected_conforms} observed={oracle_observed}")

        expected_primary = sr.get("expected_primary_reason")
        if expected_primary is not None and type(expected_primary) is not str:
            run_mismatches.append("structural expected_primary_reason must be string/null")
            expected_primary = None
        if er.get("expected_conforms") is not expected_conforms:
            run_mismatches.append(
                f"expected_conforms: oracle={expected_conforms} "
                f"engine={er.get('expected_conforms')!r}")
        if er.get("expected_primary_reason") != expected_primary:
            run_mismatches.append(
                f"expected_primary_reason: oracle={expected_primary!r} "
                f"engine={er.get('expected_primary_reason')!r}")

        # Runtime and deterministic file hashes are checked for every run.
        er_rt = er.get("runtime")
        run_mismatches.extend(_object_keys(
            er_rt, f"{fid}/{profile}.runtime", set(EXPECTED_RUNTIME)))
        if isinstance(er_rt, dict):
            for name, value in EXPECTED_RUNTIME.items():
                if er_rt.get(name) != value:
                    run_mismatches.append(
                        f"runtime.{name} expected={value} got={er_rt.get(name)}")
        expected_shapes_hash = (disk_hashes["shapes_promoted_only"]
                               if profile == "promoted_only"
                               else disk_hashes["shapes_open"])
        hash_checks = {"shapes_sha256": expected_shapes_hash,
                       **{field: disk_hashes[disk_key]
                          for field, disk_key in per_run_hashes.items()}}
        for field, expected_hash in hash_checks.items():
            value = er.get(field)
            if not _is_hex_sha256(value):
                run_mismatches.append(f"{field} must be a lowercase SHA-256 digest")
            elif value != expected_hash:
                run_mismatches.append(
                    f"{field}: engine={value} disk={expected_hash}")

        observed_conforms = er.get("observed_conforms")
        if type(observed_conforms) is not bool:
            run_mismatches.append(
                f"observed_conforms is not a JSON boolean (got {observed_conforms!r})")
        elif observed_conforms != expected_conforms:
            run_mismatches.append(
                f"conforms: oracle={expected_conforms} engine={observed_conforms}")

        struct_violations_raw = sr.get("observed_violations", [])
        if not isinstance(struct_violations_raw, list) or not all(
                type(item) is str for item in struct_violations_raw):
            run_mismatches.append("structural observed_violations must be list[str]")
            struct_violations: list[str] = []
        else:
            struct_violations = sorted(set(struct_violations_raw))
            if struct_violations_raw != struct_violations:
                run_mismatches.append(
                    "structural observed_violations must be sorted and unique")
        unknown_struct = set(struct_violations) - _KNOWN_VIOLATION_REASONS
        if unknown_struct:
            run_mismatches.append(
                f"structural oracle has unknown violation reasons: {sorted(unknown_struct)}")

        engine_violations = er.get("normalized_violations")
        if not isinstance(engine_violations, list) or not all(
                type(item) is str for item in engine_violations):
            run_mismatches.append("normalized_violations must be a list[str]")
            engine_violations = []
        else:
            if engine_violations != sorted(engine_violations):
                run_mismatches.append("normalized_violations must be sorted")
            if len(engine_violations) != len(set(engine_violations)):
                run_mismatches.append("normalized_violations must not contain duplicates")
            unknown_reasons = set(engine_violations) - _KNOWN_VIOLATION_REASONS
            if unknown_reasons:
                run_mismatches.append(
                    f"unknown violation reasons in engine output: {sorted(unknown_reasons)}")
            if engine_violations != struct_violations:
                run_mismatches.append(
                    f"normalized_violations: oracle={struct_violations!r} "
                    f"engine={engine_violations!r}")
        if not expected_conforms and expected_primary and expected_primary not in engine_violations:
            run_mismatches.append(
                f"primary_reason '{expected_primary}' missing from engine violations")
        uv = er.get("unclassified_violations")
        if uv != [] or not isinstance(uv, list):
            run_mismatches.append(
                f"unclassified_violations must be an empty list (got {uv!r})")

        # Recompute the single-fixture RDF hash from fixtures.json, not from
        # any engine-supplied content.
        expected_rdf_hash = _compute_fixture_rdf_hash(
            fixture_map.get(fid, {}), catalog)
        rdf_value = er.get("rdf_input_sha256")
        if not _is_hex_sha256(rdf_value) or rdf_value != expected_rdf_hash:
            run_mismatches.append(
                f"rdf_input_sha256: engine={rdf_value} recomputed={expected_rdf_hash}")

        expected_tuples = _expected_semantic_tuples(sr, fid, profile)
        if "semantic_tuples" in sr and sr.get("semantic_tuples") != expected_tuples:
            run_mismatches.append(
                "structural semantic_tuples do not match its observed violations")
        run_mismatches.extend(_validate_semantic_tuples(
            er.get("semantic_tuples"), expected_tuples))
        expected_digest = _semantic_digest_from_tuples(expected_tuples)
        digest = er.get("semantic_digest")
        if not _is_hex_sha256(digest) or digest != expected_digest:
            run_mismatches.append(
                f"semantic_digest: engine={digest!r} expected={expected_digest}")
        if type(er.get("report_text")) is not str:
            run_mismatches.append("report_text must be a string")

        computed_run_pass = not run_mismatches
        reported_matched = er.get("matched")
        if type(reported_matched) is not bool:
            run_mismatches.append(
                f"matched must be a JSON boolean (got {reported_matched!r})")
        elif reported_matched != computed_run_pass:
            run_mismatches.append(
                f"matched inconsistent with computed run result: "
                f"reported={reported_matched} computed={computed_run_pass}")

        if run_mismatches:
            mismatches.extend(f"{fid}/{profile}: {item}" for item in run_mismatches)
        else:
            matched += 1

        per_run.append({
            "fixture_id": fid,
            "profile": profile,
            "expected_conforms": expected_conforms,
            "observed_conforms": observed_conforms,
            "expected_primary_reason": expected_primary,
            "engine_normalized_violations": engine_violations,
            "structural_observed_violations": struct_violations,
            "semantic_tuples_match": er.get("semantic_tuples") == expected_tuples,
            "semantic_digest_match": digest == expected_digest,
            "shapes_sha256_match": er.get("shapes_sha256") == expected_shapes_hash,
            "fixtures_sha256_match": er.get("fixtures_sha256") == disk_hashes["fixtures_json"],
            "runtime_match": isinstance(er_rt, dict) and all(
                er_rt.get(k) == v for k, v in EXPECTED_RUNTIME.items()),
            "passed": not run_mismatches,
            "run_mismatches": run_mismatches,
        })

    # Verdict is derived independently.  A self-reported PASS, coverage, or
    # summary cannot turn a mismatch-free-looking subset into acceptance.
    verdict = "pass" if matched == EXPECTED_RUN_COUNT and not mismatches else "fail"
    expected_coverage = {
        "fixture_count": len({key[0] for key in struct_keys}),
        "profile_run_count": len(struct_results),
        "matched_run_count": matched,
    }
    if isinstance(cov, dict):
        for field, expected_value in expected_coverage.items():
            actual = cov.get(field)
            if type(actual) is not int or actual != expected_value:
                mismatches.append(
                    f"engine.coverage.{field} expected={expected_value} got={actual!r}")
    expected_summary = {
        "total_runs": len(engine_runs),
        "matched_runs": matched,
        "mismatch_count": len(mismatches),
        "verdict": verdict,
    }
    if isinstance(summary, dict):
        for field, expected_value in expected_summary.items():
            if summary.get(field) != expected_value:
                mismatches.append(
                    f"engine.summary.{field} expected={expected_value!r} "
                    f"got={summary.get(field)!r}")
    # A summary mismatch itself changes the authoritative result; report it in
    # a second pass only for verdict computation, without recursively changing
    # the expected mismatch_count field.
    if mismatches and verdict == "pass":
        verdict = "fail"

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
            ("rdf_input_sha256", inp.get("rdf_input_sha256"), disk["fixtures_ttl"]),
            ("validate_structural_sha256",
             inp.get("validate_structural_sha256"), disk["validate_structural"]),
            ("fixtures_to_rdf_sha256",
             inp.get("fixtures_to_rdf_sha256"), disk["fixtures_to_rdf"]),
            ("validate_pyshacl_sha256",
             inp.get("validate_pyshacl_sha256"), disk["validate_pyshacl"]),
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
