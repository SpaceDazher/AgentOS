#!/usr/bin/env python3
"""Real pySHACL engine runner for S1-003.

Runs the frozen fixtures through the SHACL engine (shapes-v3.ttl for the open
profile, shapes-v3-promoted-only.ttl for the promoted_only profile), captures
conformance results + normalized violations, and writes engine-results.json.

Design
------
* Fails closed (exit 1) when rdflib/pySHACL is not importable or the version
  differs from the pinned set.
* Each of the 26 profile runs is executed as a SEPARATE single-fixture data
  graph so that sh:targetClass targeting yields exactly that fixture's
  focus node, mirroring the structural oracle's per-record evaluation.
* For each run we record:
    fixture_id, profile, expected_conforms, observed_conforms,
    expected_primary_reason, normalized_violations, report_text,
    semantic_digest, runtime versions, SHA-256 of shapes, fixtures, and RDF.
* The semantic digest is a sorted set of
  "<focusNode>|<severity>|<normalized-reason>" tuples — stable across runs
  and independent of blank-node identifiers in the report graph.
* Exit code is non-zero if any expected outcome does not match.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _import_pyshacl():
    """Import pyshacl/rdflib and enforce the pinned runtime identity."""
    try:
        import rdflib  # noqa: F401
        import pyshacl  # noqa: F401
    except ImportError:
        print(json.dumps({
            "error": "rdflib/pySHACL not importable in this interpreter",
            "hint": "Use the isolated venv: research/tickets/stage-1/S1-003/.venv-pyshacl",
        }, indent=2))
        sys.exit(1)
    versions = {
        "python": platform.python_version(),
        "rdflib": rdflib.__version__,
        "pyshacl": pyshacl.__version__,
    }
    expected = {"rdflib": "7.6.0", "pyshacl": "0.40.1", "python": "3.11.15"}
    mismatches = {k: v for k, v in versions.items() if v != expected[k]}
    if mismatches:
        print(json.dumps({
            "error": "runtime version mismatch",
            "expected": expected,
            "actual": versions,
            "mismatches": mismatches,
        }, indent=2))
        sys.exit(1)
    return versions


# --------------------------------------------------------------------------- #
# Violation normalisation: maps a pySHACL result to the structural oracle's
# reason vocabulary so the comparison is meaningful.
# --------------------------------------------------------------------------- #
HUBS = "https://example.org/agent-hub#"

# Every violation that shapes-v3.ttl and shapes-v3-promoted-only.ttl can emit
# carries an sh:message that IS the structural reason string.  This set is the
# authoritative whitelist — any message not in this set is 'unclassified'.
_KNOWN_REASONS = frozenset({
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


def _classify_violation(source_shape: str, constraint_component: str,
                        result_path: str | None,
                        result_message: str | None,
                        focus_node: str,
                        status_map: dict[str, set[str]]) -> str:
    """Classify a single pySHACL result into an oracle reason string.

    Primary strategy: the ``sh:message`` on every shapes-v2 constraint is set
    to the exact structural reason string, so we read it directly.
    Fallback: infer from shape name + property path + constraint component
    when no message is present (defensive — every shapes-v2 constraint has one).
    """
    msg = (result_message or "").strip()
    if msg in _KNOWN_REASONS:
        return msg

    # --- Fallback: path + component classification (no message) ---
    path = result_path.split("#")[-1] if result_path else ""
    cc = constraint_component.split("#")[-1] if constraint_component else ""

    if path == "status" and cc == "InConstraintComponent":
        return "stale_or_unknown_status"
    if path == "status" and cc == "HasValueConstraintComponent":
        return "not_promoted_status"
    if path == "locatedIn" and cc == "MinCountConstraintComponent":
        return "missing_effective_scope"
    if path == "locatedIn" and cc == "MaxCountConstraintComponent":
        return "multiple_effective_scopes"
    if path == "budget" and cc == "MinInclusiveConstraintComponent":
        return "negative_budget"
    if path == "ttl" and cc == "MaxInclusiveConstraintComponent":
        return "ttl_above_15_minutes"
    if path == "independenceGroup" and cc == "MinCountConstraintComponent":
        return "evidence_missing_independence_group"
    if path == "canonicalSourceId" and cc == "MinCountConstraintComponent":
        return "evidence_missing_canonical_source_id"
    if path == "publisherId" and cc == "MinCountConstraintComponent":
        return "evidence_missing_publisher_id"
    if path == "resolverVersion" and cc == "MinCountConstraintComponent":
        return "evidence_missing_resolver_version"
    if path == "metadataFrozenAt" and cc == "MinCountConstraintComponent":
        return "evidence_missing_metadata_frozen_at"

    return "unclassified"


def _build_single_fixture_graph(fixture: dict[str, Any],
                                catalog: dict[str, Any]) -> tuple[str, dict[str, set[str]]]:
    """Build a Turtle data graph for ONE fixture and return (ttl, status_map).

    status_map maps fixture_id -> {status_value} so the classifier can inspect
    the focus node's status without re-parsing.
    """
    sys.path.insert(0, str(HERE))
    from fixtures_to_rdf import build_graph

    doc = {"evidence_catalog": catalog, "fixtures": [fixture]}
    turtle, _ = build_graph(doc)
    status_val = fixture["data"].get("status", "")
    status_map = {fixture["id"]: {status_val}}
    return turtle, status_map


def _run_validation(shapes_text: str, data_ttl: str) -> dict[str, Any]:
    """Run pyshacl.validate on a single data graph; return raw + semantic info."""
    import pyshacl
    from rdflib import Graph

    sg = Graph().parse(data=shapes_text, format="turtle")
    dg = Graph().parse(data=data_ttl, format="turtle")

    conforms, report_graph, report_text = pyshacl.validate(
        dg,
        shacl_graph=sg,
        inference=False,
        advanced=False,
        abort_on_first=False,
        allow_infos=False,
        allow_warnings=False,
        meta_shacl=False,
        debug=False,
    )

    raw_hash = hashlib.sha256(report_text.encode("utf-8")).hexdigest()

    return {
        "conforms": bool(conforms),
        "report_text": report_text,
        "raw_report_hash": raw_hash,
        "report_graph": report_graph,
    }


def _iter_results(report_graph: Any):
    """Yield each sh:ValidationResult node from a pySHACL report graph."""
    from rdflib import Namespace, RDF
    sh = Namespace("http://www.w3.org/ns/shacl#")
    for _report in report_graph.subjects(RDF.type, sh.ValidationReport):
        for result in report_graph.objects(_report, sh.result):
            yield result


def _result_field(report_graph: Any, result, prop: str) -> str:
    """Extract a property value from a ValidationResult node."""
    from rdflib import Namespace
    sh = Namespace("http://www.w3.org/ns/shacl#")
    attr = getattr(sh, prop)
    val = report_graph.value(result, attr)
    return str(val) if val is not None else ""


def _normalize_violations(
    report_graph: Any, status_map: dict[str, set[str]]
) -> tuple[list[str], list[dict[str, str]]]:
    """Extract and classify every sh:result in the report graph.

    Returns (classified, unclassified) where *classified* is a sorted list of
    oracle-reason strings and *unclassified* is a list of raw dicts
    ``{source_shape, constraint_component, result_path, result_message,
    focus_node}`` for results that did not map to a known reason.

    Fail-closed design: unclassified results are NOT discarded — the caller
    must check the unclassified list and fail unless every entry matches an
    explicit versioned allowlist.
    """
    violations: list[str] = []
    unclassified: list[dict[str, str]] = []
    for result in _iter_results(report_graph):
        source_shape = _result_field(report_graph, result, "sourceShape")
        cc = _result_field(report_graph, result, "sourceConstraintComponent")
        path = _result_field(report_graph, result, "resultPath")
        message = _result_field(report_graph, result, "resultMessage")
        focus = _result_field(report_graph, result, "focusNode")

        reason = _classify_violation(source_shape, cc, path, message, focus, status_map)
        if reason == "unclassified":
            unclassified.append({
                "source_shape": source_shape,
                "constraint_component": cc,
                "result_path": path,
                "result_message": message,
                "focus_node": focus,
            })
        elif reason not in violations:
            violations.append(reason)

    return sorted(violations), unclassified


#: Versioned allowlist of unclassified violation signatures that are known
#: to be benign for shapes-v3.  Each entry is a frozen tuple
#: ``(constraint_component_suffix, result_path_suffix, message_prefix)``.
#: The component and path are matched by suffix (to be robust against IRI-prefix
#: differences).  The message is matched by PREFIX — this handles the
#: ``sh:or`` wrapper violation whose message includes the focus node IRI
#: (which varies per fixture).
#:
#: An empty message_prefix ("") matches any message (catch-all for that
#: component+path).
#: An empty allowlist means *any* unclassified result blocks the run.
UNCLASSIFIED_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset({
    # sh:Or on KnowledgeAssertionShape emits a generic wrapper violation whose
    # message starts with "Node ... must conform to one or more shapes".
    # These fire alongside classified sibling violations (e.g.
    # missing_promotion_activity, insufficient_independence_groups) and are
    # redundant — the structural oracle tracks only the specific reason.
    ("OrConstraintComponent", "", "Node "),
})


def _filter_unclassified(
    unclassified: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Filter unclassified violations through the versioned allowlist.

    Returns the list of unclassified entries that are NOT covered by the
    allowlist — i.e. truly unexpected violations that must cause a fail.

    Matching: (cc_suffix, path_suffix, msg_prefix).  The message is matched
    by prefix; an empty prefix matches any message for the component.
    """
    unexpected: list[dict[str, str]] = []
    for entry in unclassified:
        cc = entry.get("constraint_component", "")
        cc_suffix = cc.split("#")[-1] if cc else ""
        path = entry.get("result_path", "") or ""
        path_suffix = path.split("#")[-1] if path else ""
        msg = entry.get("result_message", "") or ""

        allowed = False
        for allow_cc, allow_path, allow_msg in UNCLASSIFIED_ALLOWLIST:
            if cc_suffix == allow_cc and path_suffix == allow_path:
                if not allow_msg or msg.startswith(allow_msg):
                    allowed = True
                    break

        if not allowed:
            unexpected.append(entry)
    return unexpected





def _semantic_digest(report_graph: Any) -> str:
    """Produce a stable, blank-node-independent digest of the report.

    For each result we hash the tuple (focusNode, severity, sourceShape,
    resultPath, resultMessage).  Blank nodes in the report graph are replaced
    by the focus node's stable IRI, so the digest is deterministic.
    """
    tuples: list[str] = []
    for result in _iter_results(report_graph):
        focus = _result_field(report_graph, result, "focusNode")
        severity = _result_field(report_graph, result, "resultSeverity")
        shape = _result_field(report_graph, result, "sourceShape")
        path = _result_field(report_graph, result, "resultPath")
        message = _result_field(report_graph, result, "resultMessage")
        tuples.append(f"{focus}|{severity}|{shape}|{path}|{message}")
    tuples.sort()
    joined = "\n".join(tuples)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _load_fixtures(fixtures_path: Path) -> dict[str, Any]:
    return json.loads(fixtures_path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="S1-003 pySHACL engine runner (ADR-0009)")
    parser.add_argument("--fixtures", type=Path,
                        default=HERE / "fixtures.json")
    parser.add_argument("--shapes-open", type=Path,
                        default=HERE / "shapes-v3.ttl")
    parser.add_argument("--shapes-promoted-only", type=Path,
                        default=HERE / "shapes-v3-promoted-only.ttl")
    parser.add_argument("--out", type=Path,
                        default=HERE / "engine-results.json")
    args = parser.parse_args()

    versions = _import_pyshacl()
    fixtures_doc = _load_fixtures(args.fixtures)
    catalog = fixtures_doc["evidence_catalog"]
    fixtures = fixtures_doc["fixtures"]

    shapes_open_text = args.shapes_open.read_text(encoding="utf-8")
    shapes_promoted_text = args.shapes_promoted_only.read_text(encoding="utf-8")

    shapes_sha = _sha256(args.shapes_open)
    fixtures_sha = _sha256(args.fixtures)

    sys.path.insert(0, str(HERE))
    from fixtures_to_rdf import build_graph
    full_turtle, rdf_input_sha = build_graph(fixtures_doc)

    run_results: list[dict[str, Any]] = []
    mismatches: list[str] = []

    for fixture in fixtures:
        fixture_id = fixture["id"]
        expected = fixture["expected"]
        additional = fixture.get("additional_expectations", {})

        # open profile
        data_ttl, status_map = _build_single_fixture_graph(fixture, catalog)
        raw = _run_validation(shapes_open_text, data_ttl)
        normalized, unclassified = _normalize_violations(raw["report_graph"], status_map)
        unclassified_unexpected = _filter_unclassified(unclassified)
        digest = _semantic_digest(raw["report_graph"])
        expected_conforms = bool(expected["conforms"])
        observed_conforms = raw["conforms"]
        match = (expected_conforms == observed_conforms)
        if not match:
            mismatches.append(f"{fixture_id}/open: conforms expected={expected_conforms} got={observed_conforms}")
        if not expected_conforms and expected.get("primary_reason"):
            if expected["primary_reason"] not in normalized:
                match = False
                mismatches.append(f"{fixture_id}/open: primary_reason '{expected['primary_reason']}' not in {normalized}")
        if unclassified_unexpected:
            match = False
            mismatches.append(
                f"{fixture_id}/open: {len(unclassified_unexpected)} unexpected unclassified violations: "
                f"{unclassified_unexpected}"
            )
        run_results.append({
            "fixture_id": fixture_id,
            "profile": "open",
            "expected_conforms": expected_conforms,
            "observed_conforms": observed_conforms,
            "expected_primary_reason": expected.get("primary_reason"),
            "normalized_violations": normalized,
            "unclassified_violations": unclassified_unexpected,
            "report_text": raw["report_text"][:8000],
            "semantic_digest": digest,
            "runtime": versions,
            "shapes_sha256": shapes_sha,
            "fixtures_sha256": fixtures_sha,
            "rdf_input_sha256": hashlib.sha256(data_ttl.encode("utf-8")).hexdigest(),
            "matched": match,
        })

        # promoted_only profile (if declared)
        if "promoted_only" in additional:
            exp = additional["promoted_only"]
            raw_po = _run_validation(shapes_promoted_text, data_ttl)
            normalized_po, unclassified_po = _normalize_violations(raw_po["report_graph"], status_map)
            unclassified_po_unexpected = _filter_unclassified(unclassified_po)
            digest_po = _semantic_digest(raw_po["report_graph"])
            exp_conforms = bool(exp["conforms"])
            obs_conforms = raw_po["conforms"]
            match_po = (exp_conforms == obs_conforms)
            if not match_po:
                mismatches.append(f"{fixture_id}/promoted_only: conforms expected={exp_conforms} got={obs_conforms}")
            if not exp_conforms and exp.get("primary_reason"):
                if exp["primary_reason"] not in normalized_po:
                    match_po = False
                    mismatches.append(f"{fixture_id}/promoted_only: primary_reason '{exp['primary_reason']}' not in {normalized_po}")
            if unclassified_po_unexpected:
                match_po = False
                mismatches.append(
                    f"{fixture_id}/promoted_only: {len(unclassified_po_unexpected)} "
                    f"unexpected unclassified violations: {unclassified_po_unexpected}"
                )
            run_results.append({
                "fixture_id": fixture_id,
                "profile": "promoted_only",
                "expected_conforms": exp_conforms,
                "observed_conforms": obs_conforms,
                "expected_primary_reason": exp.get("primary_reason"),
                "normalized_violations": normalized_po,
                "unclassified_violations": unclassified_po_unexpected,
                "report_text": raw_po["report_text"][:8000],
                "semantic_digest": digest_po,
                "runtime": versions,
                "shapes_sha256": _sha256(args.shapes_promoted_only),
                "fixtures_sha256": fixtures_sha,
                "rdf_input_sha256": hashlib.sha256(data_ttl.encode("utf-8")).hexdigest(),
                "matched": match_po,
            })

    # Summary
    total = len(run_results)
    matched_count = sum(1 for r in run_results if r["matched"])
    fixture_count = len(fixtures_doc["fixtures"])

    overall_pass = len(mismatches) == 0 and matched_count == total

    report = {
        "schema": "agentos.s1-003-engine-results/v1",
        "pyshacl_executed": True,
        "runtime": versions,
        "inputs": {
            "fixtures_sha256": fixtures_sha,
            "shapes_open_sha256": shapes_sha,
            "shapes_promoted_only_sha256": _sha256(args.shapes_promoted_only),
            "rdf_input_sha256": rdf_input_sha,
        },
        "coverage": {
            "fixture_count": fixture_count,
            "profile_run_count": total,
            "matched_run_count": matched_count,
        },
        "mismatches": mismatches,
        "results": run_results,
        "verdict": "pass" if overall_pass else "fail",
    }

    args.out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")

    print(json.dumps({
        "status": report["verdict"],
        "pyshacl_executed": True,
        "fixtures": fixture_count,
        "runs": total,
        "matched": matched_count,
        "mismatches": len(mismatches),
        "output": str(args.out),
    }, sort_keys=True))
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
