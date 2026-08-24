"""Bounded executable fallback for the S1-003 ontology contract.

This is deliberately not a SHACL engine.  It executes the ticket's lifecycle,
scope, provenance, and independence matrix with Python's standard library and
records whether rdflib/pySHACL were importable.  A successful fallback run is
therefore PASS_WITH_LIMITS until the same fixtures are executed by pySHACL.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ASSERTION_STATES = {
    "proposed",
    "under_review",
    "promoted",
    "challenged",
    "retracted",
    "superseded",
    "rejected",
}
GRANT_STATES = {"proposed", "active", "revoked", "expired", "exhausted", "denied"}
EVIDENCE_FIELDS = (
    "canonical_source_id",
    "publisher_id",
    "independence_group",
    "resolver_version",
    "metadata_frozen_at",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _scope(value: Any) -> tuple[str | None, list[str]]:
    if value is None or value == "":
        return None, ["missing_effective_scope"]
    if isinstance(value, list):
        scopes = [str(item).strip() for item in value if str(item).strip()]
        if len(scopes) != 1:
            return None, ["multiple_effective_scopes"]
        return scopes[0], []
    if not isinstance(value, str) or not value.strip():
        return None, ["invalid_effective_scope"]
    return value.strip(), []


def _resolve_evidence(refs: Any, catalog: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    if refs is None:
        return [], []
    if not isinstance(refs, list):
        return [], ["supported_by_not_list"]
    resolved: list[dict[str, Any]] = []
    failures: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or ref not in catalog:
            failures.append("unknown_evidence_reference")
            continue
        resolved.append(catalog[ref])
    return resolved, failures


def _validate_assertion(
    record: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
    profile: str,
) -> list[str]:
    status = record.get("status")
    if profile == "promoted_only" and status != "promoted":
        return ["not_promoted_status"]

    failures: list[str] = []
    scope, scope_failures = _scope(record.get("located_in"))
    failures.extend(scope_failures)
    if status not in ASSERTION_STATES:
        failures.append("stale_or_unknown_status")
    if status == "superseded" and not record.get("superseded_by"):
        failures.append("missing_superseding_assertion")

    evidence, evidence_failures = _resolve_evidence(record.get("supported_by"), catalog)
    failures.extend(evidence_failures)
    for item in evidence:
        if item.get("type") != "Evidence":
            failures.append("supported_node_not_evidence")
        for field in EVIDENCE_FIELDS:
            if item.get(field) in (None, ""):
                failures.append(f"evidence_missing_{field}")
        if scope is not None and item.get("located_in") != scope:
            failures.append("evidence_scope_mismatch")

    if status == "promoted":
        activity = record.get("generated_by")
        if not isinstance(activity, dict) or activity.get("type") != "PromotionActivity":
            failures.append("missing_promotion_activity")
        elif scope is not None and activity.get("actor_scope") != scope:
            failures.append("promotion_actor_scope_mismatch")
        if len(evidence) < 2:
            failures.append("insufficient_evidence_count")
        canonical_ids = {item.get("canonical_source_id") for item in evidence
                         if item.get("canonical_source_id")}
        groups = {item.get("independence_group") for item in evidence
                  if item.get("independence_group")}
        if len(canonical_ids) < 2:
            failures.append("insufficient_distinct_canonical_sources")
        if len(groups) < 2:
            failures.append("insufficient_independence_groups")
    return _unique(failures)


def _duration_minutes(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"PT([0-9]+)M", value)
    return int(match.group(1)) if match else None


def _validate_grant(record: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    scope, scope_failures = _scope(record.get("located_in"))
    failures.extend(scope_failures)
    if record.get("status") not in GRANT_STATES:
        failures.append("stale_or_unknown_status")

    subject = record.get("subject")
    if not isinstance(subject, dict) or subject.get("type") not in {
        "HumanUser", "SharedWorkspace", "PlatformOpsSubject"
    }:
        failures.append("invalid_subject")
    elif scope is not None and subject.get("workspace") != scope:
        failures.append("subject_scope_mismatch")

    actor = record.get("actor")
    if not isinstance(actor, dict) or actor.get("type") != "AgentInstallation":
        failures.append("invalid_actor")
    elif scope is not None and actor.get("workspace") != scope:
        failures.append("actor_scope_mismatch")

    if not isinstance(record.get("actions"), list) or not record["actions"]:
        failures.append("missing_actions")
    if not isinstance(record.get("resources"), list) or not record["resources"]:
        failures.append("missing_resources")
    if not isinstance(record.get("jti"), str) or not record["jti"].strip():
        failures.append("missing_jti")
    minutes = _duration_minutes(record.get("ttl"))
    if minutes is None:
        failures.append("invalid_ttl")
    elif minutes > 15:
        failures.append("ttl_above_15_minutes")
    budget = record.get("budget")
    if not isinstance(budget, (int, float)) or isinstance(budget, bool):
        failures.append("invalid_budget")
    elif budget < 0:
        failures.append("negative_budget")
    constraints = record.get("constraints")
    if isinstance(constraints, list) and len(constraints) > 1:
        failures.append("multiple_constraint_sets")
    return _unique(failures)


def validate_record(
    record: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
    profile: str,
) -> list[str]:
    record_type = record.get("type")
    if record_type == "KnowledgeAssertion":
        return _validate_assertion(record, catalog, profile)
    if record_type == "DelegationGrant":
        if profile != "open":
            return ["profile_not_applicable"]
        return _validate_grant(record)
    return ["unknown_record_type"]


def _shape_contract_checks(text: str) -> dict[str, Any]:
    required_tokens = [
        "hubs:KnowledgeAssertionShape a sh:NodeShape",
        "hubs:GroundedAssertionShape a sh:NodeShape",
        "hubs:EvidenceShape a sh:NodeShape",
        "hubs:DelegationGrantShape a sh:NodeShape",
        "sh:maxInclusive",
        "sh:minInclusive 0",
        "COUNT(DISTINCT ?canonical)",
        "COUNT(DISTINCT ?group)",
        'sh:hasValue "promoted"',
        'sh:hasValue "superseded"',
    ]
    for state in sorted(ASSERTION_STATES | GRANT_STATES):
        required_tokens.append(f'"{state}"')
    forbidden_tokens = [
        "sh:maxExclusiveInclusive",
        "sh:closed true",
        '"accepted"',
        '"withdrawn"',
    ]
    missing = [token for token in required_tokens if token not in text]
    forbidden_present = [token for token in forbidden_tokens if token in text]
    return {
        "ok": not missing and not forbidden_present,
        "required_token_count": len(required_tokens),
        "missing_tokens": missing,
        "forbidden_tokens_present": forbidden_present,
        "open_shapes_confirmed": "sh:closed true" not in text,
    }


def execute(fixtures_path: Path, shapes_path: Path) -> tuple[dict[str, Any], bool]:
    fixture_doc = json.loads(fixtures_path.read_text(encoding="utf-8"))
    shapes_text = shapes_path.read_text(encoding="utf-8")
    catalog = fixture_doc["evidence_catalog"]
    results: list[dict[str, Any]] = []
    expectation_matches = True

    for fixture in fixture_doc["fixtures"]:
        profiles: list[tuple[str, dict[str, Any]]] = [
            (fixture.get("profile", "open"), fixture["expected"])
        ]
        profiles.extend((profile, expected) for profile, expected in
                        fixture.get("additional_expectations", {}).items())
        for profile, expected in profiles:
            failures = validate_record(fixture["data"], catalog, profile)
            conforms = not failures
            primary = expected.get("primary_reason")
            matched = conforms == bool(expected["conforms"])
            if not expected["conforms"] and primary:
                matched = matched and primary in failures
            expectation_matches = expectation_matches and matched
            results.append({
                "fixture_id": fixture["id"],
                "record_type": fixture["data"].get("type"),
                "status": fixture["data"].get("status"),
                "profile": profile,
                "tags": fixture.get("tags", []),
                "expected_conforms": bool(expected["conforms"]),
                "expected_primary_reason": primary,
                "observed_conforms": conforms,
                "observed_violations": failures,
                "expectation_matched": matched,
            })

    fixtures = fixture_doc["fixtures"]
    valid_count = sum(bool(item["expected"]["conforms"]) for item in fixtures)
    invalid_count = len(fixtures) - valid_count
    scope_failure_count = sum("ownership_scope" in item.get("tags", []) for item in fixtures)
    observed_states: dict[str, set[str]] = {"KnowledgeAssertion": set(), "DelegationGrant": set()}
    for item in fixtures:
        kind = item["data"].get("type")
        status = item["data"].get("status")
        if kind in observed_states and isinstance(status, str):
            observed_states[kind].add(status)
    expected_states = fixture_doc["expected_lifecycle_states"]
    missing_states = {
        kind: sorted(set(states) - observed_states.get(kind, set()))
        for kind, states in expected_states.items()
    }
    lifecycle_ok = all(not values for values in missing_states.values())

    by_key = {(item["fixture_id"], item["profile"]): item for item in results}
    proposed_open = by_key[("assertion-proposed-inherited", "open")]
    proposed_promoted = by_key[("assertion-proposed-inherited", "promoted_only")]
    orphan = by_key[("invalid-orphan-promoted", "open")]
    mirror = by_key[("invalid-mirror-sybil-promoted", "open")]
    no_group = by_key[("invalid-no-independence-group", "open")]
    probes = {
        "proposed_open_but_not_promoted": (
            proposed_open["observed_conforms"]
            and not proposed_promoted["observed_conforms"]
            and "not_promoted_status" in proposed_promoted["observed_violations"]
        ),
        "orphan_promotion_rejected": (
            not orphan["observed_conforms"]
            and "missing_promotion_activity" in orphan["observed_violations"]
        ),
        "mirror_promotion_rejected": (
            not mirror["observed_conforms"]
            and "insufficient_distinct_canonical_sources" in mirror["observed_violations"]
        ),
        "missing_independence_group_rejected": (
            not no_group["observed_conforms"]
            and "evidence_missing_independence_group" in no_group["observed_violations"]
        ),
    }
    shape_checks = _shape_contract_checks(shapes_text)
    matrix_ok = all((
        len(fixtures) >= 8,
        valid_count >= 4,
        invalid_count >= 4,
        scope_failure_count >= 2,
        lifecycle_ok,
        expectation_matches,
        all(probes.values()),
        shape_checks["ok"],
    ))

    rdflib_available = importlib.util.find_spec("rdflib") is not None
    pyshacl_available = importlib.util.find_spec("pyshacl") is not None
    report = {
        "schema": "agentos.s1-003-structural-results/v1",
        "executed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "execution_path": "bounded-stdlib-structural-validator-v1",
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "rdflib_available": rdflib_available,
            "pyshacl_available": pyshacl_available,
            "pyshacl_executed": False,
            "limitation": (
                "No RDF parser or pySHACL engine was executed. Turtle syntax, SHACL engine "
                "conformance, RDF entailment, and SHACL-SPARQL behavior remain unverified."
            ),
        },
        "inputs": {
            "fixtures_path": fixtures_path.as_posix(),
            "fixtures_sha256": _sha256(fixtures_path),
            "shapes_path": shapes_path.as_posix(),
            "shapes_sha256": _sha256(shapes_path),
        },
        "coverage": {
            "fixture_count": len(fixtures),
            "profile_run_count": len(results),
            "valid_fixture_count": valid_count,
            "invalid_fixture_count": invalid_count,
            "ownership_scope_failure_count": scope_failure_count,
            "expected_lifecycle_state_count": sum(len(states) for states in expected_states.values()),
            "observed_lifecycle_state_count": sum(
                len(observed_states.get(kind, set()) & set(states))
                for kind, states in expected_states.items()
            ),
            "missing_lifecycle_states": missing_states,
            "lifecycle_coverage_ratio": 1.0 if lifecycle_ok else 0.0,
        },
        "shape_contract_checks": shape_checks,
        "adversarial_probes": probes,
        "results": results,
        "all_expectations_matched": expectation_matches,
        "structural_matrix_passed": matrix_ok,
        "verdict": "pass_with_limits" if matrix_ok else "fail",
    }
    return report, matrix_ok


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=here / "fixtures.json")
    parser.add_argument("--shapes", type=Path, default=here / "shapes.ttl")
    parser.add_argument("--output", type=Path, default=here / "raw-results.json")
    args = parser.parse_args()
    report, ok = execute(args.fixtures.resolve(), args.shapes.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({
        "status": report["verdict"],
        "fixtures": report["coverage"]["fixture_count"],
        "runs": report["coverage"]["profile_run_count"],
        "pyshacl_executed": report["runtime"]["pyshacl_executed"],
        "output": args.output.as_posix(),
    }, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
