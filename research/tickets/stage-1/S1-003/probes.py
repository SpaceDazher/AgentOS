#!/usr/bin/env python3
"""Mandatory pySHACL probes for S1-003.

Each probe constructs a synthetic RDF data graph and validates it against
shapes-v3.ttl (open profile) or shapes-v3-promoted-only.ttl (promoted_only
profile).  All 10 probes MUST pass.

Probes:
  1. proposed assertion with inherited ContentObject fields passes open shape.
  2. the same assertion does NOT pass promoted_only (status != promoted).
  3. promoted without PromotionActivity is rejected.
  4. two mirror URLs sharing one canonical_source_id are rejected.
  5. missing independence_group is rejected.
  6. cross-workspace evidence/actor/subject are rejected.
  7. superseded without successor (supersededBy) is rejected.
  8. stale status "accepted" is rejected.
  9. negative budget is rejected.
 10. verify forbidden tokens are absent from shapes-v3.ttl:
     sh:maxExclusiveInclusive, sh:closed true, "accepted", "withdrawn".
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _import_pyshacl():
    try:
        import rdflib  # noqa: F401
        import pyshacl  # noqa: F401
    except ImportError:
        print(json.dumps({
            "error": "rdflib/pySHACL not importable",
            "hint": "Use the isolated venv with pinned deps",
        }, indent=2))
        sys.exit(1)
    return {"python": sys.version.split()[0], "rdflib": rdflib.__version__,
            "pyshacl": pyshacl.__version__}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _validate(shapes_text: str, data_ttl: str):
    from pyshacl import validate as _pv
    from rdflib import Graph
    sg = Graph().parse(data=shapes_text, format="turtle")
    dg = Graph().parse(data=data_ttl, format="turtle")
    conforms, report_graph, report_text = _pv(
        dg, shacl_graph=sg, inference=False, advanced=False,
        abort_on_first=False, allow_infos=False, allow_warnings=False,
        meta_shacl=False, debug=False)
    return conforms, report_text


def _load_shapes():
    return (
        (HERE / "shapes-v3.ttl").read_text(encoding="utf-8"),
        (HERE / "shapes-v3-promoted-only.ttl").read_text(encoding="utf-8"),
    )


# --------------------------------------------------------------------------- #
# Probe data graphs — hand-crafted, minimal Turtle for each probe
# --------------------------------------------------------------------------- #

def _probe_1_proposed_inherited():
    """Proposed assertion with additional inherited ContentObject fields
    passes the open KnowledgeAssertionShape."""
    return """
@prefix hubs: <https://example.org/agent-hub#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<urn:s1-003:fixture:probe-proposed-inherited>
a hubs:KnowledgeAssertion ;
hubs:status "proposed" ;
hubs:locatedIn <urn:s1-003:workspace:workspace-a> ;
hubs:supportedBy <urn:s1-003:evidence:probe-1:ev-a> ;
hubs:ttl "PT5M"^^xsd:string .

<urn:s1-003:workspace:workspace-a>
a hubs:Workspace .

<urn:s1-003:evidence:probe-1:ev-a>
  a hubs:Evidence ;
  hubs:canonicalSourceId "src-a" ;
  hubs:publisherId "pub-a" ;
  hubs:independenceGroup "group-a" ;
  hubs:resolverVersion "v1" ;
  hubs:metadataFrozenAt "2026-01-01T00:00:00Z"^^xsd:dateTime ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> .
"""


def _probe_3_promoted_no_activity():
    """Promoted assertion without PromotionActivity is rejected."""
    return """
@prefix hubs: <https://example.org/agent-hub#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<urn:s1-003:fixture:probe-promoted-no-activity>
  a hubs:KnowledgeAssertion ;
  hubs:status "promoted" ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> ;
  hubs:supportedBy <urn:s1-003:evidence:probe-3:ev-a> ;
  hubs:supportedBy <urn:s1-003:evidence:probe-3:ev-b> .

<urn:s1-003:evidence:probe-3:ev-a>
  a hubs:Evidence ;
  hubs:canonicalSourceId "src-a" ;
  hubs:publisherId "pub-a" ;
  hubs:independenceGroup "group-a" ;
  hubs:resolverVersion "v1" ;
  hubs:metadataFrozenAt "2026-01-01T00:00:00Z"^^xsd:dateTime ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> .

<urn:s1-003:evidence:probe-3:ev-b>
  a hubs:Evidence ;
  hubs:canonicalSourceId "src-b" ;
  hubs:publisherId "pub-b" ;
  hubs:independenceGroup "group-b" ;
  hubs:resolverVersion "v1" ;
  hubs:metadataFrozenAt "2026-01-01T00:00:00Z"^^xsd:dateTime ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> .
"""


def _probe_4_mirror_sybil():
    """Two mirror evidence nodes with the same canonical_source_id are rejected."""
    return """
@prefix hubs: <https://example.org/agent-hub#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<urn:s1-003:fixture:probe-mirror-sybil>
  a hubs:KnowledgeAssertion ;
  hubs:status "promoted" ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> ;
  prov:wasGeneratedBy <urn:s1-003:activity:probe-4> ;
  hubs:supportedBy <urn:s1-003:evidence:probe-4:mirror-a1> ;
  hubs:supportedBy <urn:s1-003:evidence:probe-4:mirror-a2> .

<urn:s1-003:activity:probe-4>
  a hubs:PromotionActivity ;
  hubs:actorScope <urn:s1-003:workspace:workspace-a> .

<urn:s1-003:evidence:probe-4:mirror-a1>
  a hubs:Evidence ;
  hubs:canonicalSourceId "source-a" ;
  hubs:publisherId "pub-mirror-1" ;
  hubs:independenceGroup "group-a" ;
  hubs:resolverVersion "v1" ;
  hubs:metadataFrozenAt "2026-01-01T00:00:00Z"^^xsd:dateTime ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> .

<urn:s1-003:evidence:probe-4:mirror-a2>
  a hubs:Evidence ;
  hubs:canonicalSourceId "source-a" ;
  hubs:publisherId "pub-mirror-2" ;
  hubs:independenceGroup "group-a" ;
  hubs:resolverVersion "v1" ;
  hubs:metadataFrozenAt "2026-01-01T00:00:00Z"^^xsd:dateTime ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> .
"""


def _probe_5_no_independence_group():
    """Missing independence_group on evidence is rejected."""
    return """
@prefix hubs: <https://example.org/agent-hub#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<urn:s1-003:fixture:probe-no-group>
  a hubs:KnowledgeAssertion ;
  hubs:status "promoted" ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> ;
  prov:wasGeneratedBy <urn:s1-003:activity:probe-5> ;
  hubs:supportedBy <urn:s1-003:evidence:probe-5:ev-a> ;
  hubs:supportedBy <urn:s1-003:evidence:probe-5:ev-b> .

<urn:s1-003:activity:probe-5>
  a hubs:PromotionActivity ;
  hubs:actorScope <urn:s1-003:workspace:workspace-a> .

<urn:s1-003:evidence:probe-5:ev-a>
  a hubs:Evidence ;
  hubs:canonicalSourceId "src-a" ;
  hubs:publisherId "pub-a" ;
  hubs:independenceGroup "group-a" ;
  hubs:resolverVersion "v1" ;
  hubs:metadataFrozenAt "2026-01-01T00:00:00Z"^^xsd:dateTime ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> .

<urn:s1-003:evidence:probe-5:ev-b>
  a hubs:Evidence ;
  hubs:canonicalSourceId "src-b" ;
  hubs:publisherId "pub-b" ;
  hubs:resolverVersion "v1" ;
  hubs:metadataFrozenAt "2026-01-01T00:00:00Z"^^xsd:dateTime ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> .
"""


def _probe_6_cross_workspace():
    """Cross-workspace evidence/actor/subject are rejected."""
    # (a) cross-workspace evidence
    data_ev = """
@prefix hubs: <https://example.org/agent-hub#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<urn:s1-003:fixture:probe-cross-ev>
  a hubs:KnowledgeAssertion ;
  hubs:status "promoted" ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> ;
  prov:wasGeneratedBy <urn:s1-003:activity:probe-6> ;
  hubs:supportedBy <urn:s1-003:evidence:probe-6:ev-a> ;
  hubs:supportedBy <urn:s1-003:evidence:probe-6:ev-b> .

<urn:s1-003:activity:probe-6>
  a hubs:PromotionActivity ;
  hubs:actorScope <urn:s1-003:workspace:workspace-a> .

<urn:s1-003:evidence:probe-6:ev-a>
  a hubs:Evidence ;
  hubs:canonicalSourceId "src-a" ;
  hubs:publisherId "pub-a" ;
  hubs:independenceGroup "group-a" ;
  hubs:resolverVersion "v1" ;
  hubs:metadataFrozenAt "2026-01-01T00:00:00Z"^^xsd:dateTime ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> .

<urn:s1-003:evidence:probe-6:ev-b>
  a hubs:Evidence ;
  hubs:canonicalSourceId "src-b" ;
  hubs:publisherId "pub-b" ;
  hubs:independenceGroup "group-b" ;
  hubs:resolverVersion "v1" ;
  hubs:metadataFrozenAt "2026-01-01T00:00:00Z"^^xsd:dateTime ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-b> .
"""
    # (b) cross-workspace actor scope
    data_act = """
@prefix hubs: <https://example.org/agent-hub#> .
@prefix prov: <http://www.w3.org/ns/prov#> .

<urn:s1-003:fixture:probe-cross-act>
  a hubs:KnowledgeAssertion ;
  hubs:status "promoted" ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> ;
  prov:wasGeneratedBy <urn:s1-003:activity:probe-6b> ;
  hubs:supportedBy <urn:s1-003:evidence:probe-6:ev-a> ;
  hubs:supportedBy <urn:s1-003:evidence:probe-6:ev-b> .

<urn:s1-003:activity:probe-6b>
  a hubs:PromotionActivity ;
  hubs:actorScope <urn:s1-003:workspace:workspace-b> .

<urn:s1-003:evidence:probe-6:ev-a>
  a hubs:Evidence ;
  hubs:canonicalSourceId "src-a" ;
  hubs:publisherId "pub-a" ;
  hubs:independenceGroup "group-a" ;
  hubs:resolverVersion "v1" ;
  hubs:metadataFrozenAt "2026-01-01T00:00:00Z"^^<http://www.w3.org/2001/XMLSchema#dateTime> ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> .

<urn:s1-003:evidence:probe-6:ev-b>
  a hubs:Evidence ;
  hubs:canonicalSourceId "src-b" ;
  hubs:publisherId "pub-b" ;
  hubs:independenceGroup "group-b" ;
  hubs:resolverVersion "v1" ;
  hubs:metadataFrozenAt "2026-01-01T00:00:00Z"^^<http://www.w3.org/2001/XMLSchema#dateTime> ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> .
"""
    # (c) cross-workspace grant subject
    data_sub = """
@prefix hubs: <https://example.org/agent-hub#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<urn:s1-003:fixture:probe-cross-subj>
  a hubs:DelegationGrant ;
  hubs:status "active" ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> ;
  hubs:subject <urn:s1-003:subject:probe-6b> ;
  hubs:actor <urn:s1-003:actor:probe-6b> ;
  hubs:actions ("read" "write") ;
  hubs:resources ("res1") ;
  hubs:jti "jti-probe-6" ;
  hubs:ttl "PT5M"^^xsd:string ;
  hubs:budget "100"^^xsd:decimal .

<urn:s1-003:subject:probe-6b>
  a hubs:HumanUser ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-b> .

<urn:s1-003:actor:probe-6b>
  a hubs:AgentInstallation ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> .
"""
    return data_ev, data_act, data_sub


def _probe_7_superseded_no_successor():
    """Superseded assertion without supersededBy is rejected."""
    return """
@prefix hubs: <https://example.org/agent-hub#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<urn:s1-003:fixture:probe-superseded-no-successor>
  a hubs:KnowledgeAssertion ;
  hubs:status "superseded" ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> .
"""


def _probe_8_stale_status():
    """Stale status 'accepted' is rejected."""
    return """
@prefix hubs: <https://example.org/agent-hub#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<urn:s1-003:fixture:probe-stale-status>
  a hubs:KnowledgeAssertion ;
  hubs:status "accepted" ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> .
"""


def _probe_9_negative_budget():
    """Negative budget is rejected."""
    return """
@prefix hubs: <https://example.org/agent-hub#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<urn:s1-003:fixture:probe-neg-budget>
  a hubs:DelegationGrant ;
  hubs:status "active" ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> ;
  hubs:subject <urn:s1-003:subject:probe-neg> ;
  hubs:actor <urn:s1-003:actor:probe-neg> ;
  hubs:actions ("read") ;
  hubs:resources ("res1") ;
  hubs:jti "jti-probe-neg" ;
  hubs:ttl "PT5M"^^xsd:string ;
  hubs:budget "-1"^^xsd:decimal .

<urn:s1-003:subject:probe-neg>
  a hubs:HumanUser ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> .

<urn:s1-003:actor:probe-neg>
  a hubs:AgentInstallation ;
  hubs:locatedIn <urn:s1-003:workspace:workspace-a> .
"""


def _probe_10_forbidden_tokens(shapes_text: str) -> bool:
    """Check that forbidden tokens are absent from shapes text (excluding comments)."""
    # Strip comment lines (lines starting with #)
    lines = [ln for ln in shapes_text.split("\n") if not ln.strip().startswith("#")]
    code = "\n".join(lines)
    forbidden = ["sh:maxExclusiveInclusive", "sh:closed true",
                 '"accepted"', '"withdrawn"']
    found = [tok for tok in forbidden if tok in code]
    return len(found) == 0


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    _import_pyshacl()
    shapes_open, shapes_po = _load_shapes()

    results: list[dict[str, Any]] = []

    # Probe 1: proposed assertion with inherited ContentObject fields passes open
    conforms, _ = _validate(shapes_open, _probe_1_proposed_inherited())
    results.append({"probe": "1_proposed_inherited_passes_open", "passed": conforms,
                    "expected": True, "observed": conforms})

    # Probe 2: same assertion does NOT pass promoted_only (not promoted)
    conforms, _ = _validate(shapes_po, _probe_1_proposed_inherited())
    results.append({"probe": "2_proposed_inherited_fails_promoted_only", "passed": not conforms,
                    "expected": False, "observed": conforms})

    # Probe 3: promoted without PromotionActivity rejected
    conforms, _ = _validate(shapes_open, _probe_3_promoted_no_activity())
    results.append({"probe": "3_promoted_no_activity_rejected", "passed": not conforms,
                    "expected": False, "observed": conforms})

    # Probe 4: two mirror URLs with one canonical_source_id rejected
    conforms, _ = _validate(shapes_open, _probe_4_mirror_sybil())
    results.append({"probe": "4_mirror_sybil_rejected", "passed": not conforms,
                    "expected": False, "observed": conforms})

    # Probe 5: missing independence_group rejected
    conforms, _ = _validate(shapes_open, _probe_5_no_independence_group())
    results.append({"probe": "5_no_independence_group_rejected", "passed": not conforms,
                    "expected": False, "observed": conforms})

    # Probe 6: cross-workspace evidence/actor/subject rejected
    data_ev, data_act, data_sub = _probe_6_cross_workspace()
    c1, _ = _validate(shapes_open, data_ev)
    results.append({"probe": "6a_cross_workspace_evidence_rejected", "passed": not c1,
                    "expected": False, "observed": c1})
    c2, _ = _validate(shapes_open, data_act)
    results.append({"probe": "6b_cross_workspace_actor_rejected", "passed": not c2,
                    "expected": False, "observed": c2})
    c3, _ = _validate(shapes_open, data_sub)
    results.append({"probe": "6c_cross_workspace_subject_rejected", "passed": not c3,
                    "expected": False, "observed": c3})

    # Probe 7: superseded without successor rejected
    conforms, _ = _validate(shapes_open, _probe_7_superseded_no_successor())
    results.append({"probe": "7_superseded_no_successor_rejected", "passed": not conforms,
                    "expected": False, "observed": conforms})

    # Probe 8: stale status "accepted" rejected
    conforms, _ = _validate(shapes_open, _probe_8_stale_status())
    results.append({"probe": "8_stale_status_accepted_rejected", "passed": not conforms,
                    "expected": False, "observed": conforms})

    # Probe 9: negative budget rejected
    conforms, _ = _validate(shapes_open, _probe_9_negative_budget())
    results.append({"probe": "9_negative_budget_rejected", "passed": not conforms,
                    "expected": False, "observed": conforms})

    # Probe 10: forbidden tokens absent
    ok = _probe_10_forbidden_tokens(shapes_open)
    results.append({"probe": "10_forbidden_tokens_absent", "passed": ok,
                    "expected": True, "observed": ok})

    passed_count = sum(1 for r in results if r["passed"])
    all_passed = passed_count == len(results)

    report = {
        "schema": "agentos.s1-003-probes/v1",
        "total_probes": len(results),
        "passed": passed_count,
        "verdict": "pass" if all_passed else "fail",
        "probes": results,
    }

    out_path = HERE / "probe-results.json"
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")

    print(json.dumps({
        "verdict": report["verdict"],
        "passed": passed_count,
        "total": len(results),
        "output": str(out_path),
    }, sort_keys=True))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
