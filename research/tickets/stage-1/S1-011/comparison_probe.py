#!/usr/bin/env python3
"""Executable S1-011 acceptance-criteria probe (stdlib-only, deterministic).

Machine-checks the S1-011 ticket's acceptance criteria against the authored
bundle and the current S1-003 ontology contract:

  A1 (comparison): the promote/challenge versus argumentation/TMS comparison
     covers at least 5 named dimensions (6 are authored), each dimension claim
     names both designs, and the synthesis artifact carries the full table.

  A2 (MVP recommendation): one decision claim states the evidence threshold,
     the challenge action, the retraction behavior, and operator escalation;
     the platform plan claims no truth oracle and adopts no autonomous truth
     resolution or reputation-as-enforcement.

  A3 (lifecycle definition): the ontology artifact defines a transition table
     that matches, row for row, the executable machine in lifecycle_probe.py
     (every lifecycle transition defined).

  A4 (S1-003 alignment): the machine's states are exactly the KnowledgeAssertion
     status vocabulary parsed from shapes-v3.ttl, and the bundle keeps an
     explicit alignment claim.

Output: writes comparison-results.json and prints one JSON verdict line
{"status": "pass"|"fail", "observed": ...}; exit 0 on pass, 1 on fail.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]  # research/tickets/stage-1/S1-011 -> repository root
BUNDLE = HERE / "bundle.json"
SHAPES = REPO / "research" / "tickets" / "stage-1" / "S1-003" / "shapes-v3.ttl"
RESULTS = HERE / "comparison-results.json"

sys.path.insert(0, str(HERE))
from lifecycle_probe import STATES, TRANSITIONS  # noqa: E402  (local, stdlib-only)


def _lower(value: str) -> str:
    return str(value).lower()


def parse_transition_table(ontology_content: str):
    """Parse the ontology artifact's lifecycle transition table."""
    start = ontology_content.find("## Lifecycle transition table")
    if start < 0:
        return [], "missing '## Lifecycle transition table' section"
    tail = ontology_content[start:]
    nxt = re.search(r"\n# ", tail[1:])
    section = tail[1: nxt.start() + 1] if nxt else tail[1:]
    rows = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        first = cells[0]
        if first in {"From state", "from"} or set(first) <= set("-: "):
            continue  # header or separator row
        guard = cells[2].split(":", 1)[0].strip()
        rows.append((first, cells[1], guard))
    return rows, None


def parse_shape_status_vocabulary(shapes_text: str):
    """First sh:in list in shapes-v3.ttl = KnowledgeAssertion status sh:in."""
    match = re.search(r"sh:in\s*\(([^)]*)\)", shapes_text)
    if not match:
        return []
    return re.findall(r'"([^"]+)"', match.group(1))


def main(argv=None) -> int:
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    claims = bundle.get("claims", [])
    artifacts = bundle.get("artifacts", {})
    checks: list[dict] = []
    failures: list[str] = []

    def check(name: str, passed: bool, detail) -> bool:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        if not passed:
            failures.append(f"{name}: {detail}")
        return bool(passed)

    # A0: source mix floor from the ticket (>= 4 verified sources).
    sources = bundle.get("sources", [])
    all_verified = all(
        str(s.get("verification_status", "")).lower() == "verified"
        for s in sources)
    check("A0_sources_at_least_four_all_verified",
          len(sources) >= 4 and all_verified,
          {"count": len(sources), "all_verified": all_verified})

    # A1: five-or-more-dimension comparison across both designs.
    dim_claims = [c for c in claims if c.get("comparison_dimension")]
    dims = sorted({str(c["comparison_dimension"]) for c in dim_claims})
    check("A1_at_least_five_dimensions", len(dims) >= 5, dims)
    both_designs = all(
        "promote/challenge" in _lower(c.get("text", ""))
        and "argumentation" in _lower(c.get("text", ""))
        for c in dim_claims)
    check("A1_each_dimension_names_both_designs", both_designs and bool(dim_claims),
          f"{len(dim_claims)} dimension claims")
    synthesis = artifacts.get("synthesis_and_gaps", {}).get("content", "")
    check("A1_synthesis_carries_full_table",
          all(d in synthesis for d in dims)
          and "Design A" in synthesis and "Design B" in synthesis,
          {"dimensions_found_in_synthesis": [d for d in dims if d in synthesis]})

    # A2: one MVP recommendation with all four required decision fields.
    mvp = next((c for c in claims if c.get("id") == "claim-mvp-decision"), None)
    mvp_text = _lower(mvp.get("text", "")) if mvp else ""
    required_fragments = [
        "evidence threshold", "two canonical sources", "two independence groups",
        "challenge action", "derived view", "retraction behavior",
        "append-only retraction marker", "operator escalation", "human operator",
        "reputation is never enforcement authority",
    ]
    missing = [f for f in required_fragments if f not in mvp_text]
    check("A2_mvp_recommendation_complete", mvp is not None and not missing,
          {"claim_found": mvp is not None, "missing_fragments": missing})

    platform = artifacts.get("platform_plan", {}).get("content", "")
    platform_l = _lower(platform)
    check("A2_no_truth_oracle_claimed",
          "no truth oracle" in platform_l
          and "autonomous truth resolution is adopted" not in platform_l
          and "truth oracle assigns" not in platform_l
          and "reputation is enforcement authority" not in platform_l,
          {"has_disclaimer": "no truth oracle" in platform_l})

    # A3: the ontology transition table matches the executable machine.
    ontology = artifacts.get("ontology", {}).get("content", "")
    rows, parse_error = parse_transition_table(ontology)
    machine = {(f, t, g) for (f, t), g in TRANSITIONS.items()}
    parsed = set(rows)
    check("A3_transition_table_parses", parse_error is None and len(rows) == 10,
          {"parse_error": parse_error, "rows": len(rows)})
    check("A3_every_lifecycle_transition_defined",
          parsed == machine and len(rows) == len(TRANSITIONS),
          {"missing_from_artifact": sorted(machine - parsed),
           "extra_in_artifact": sorted(parsed - machine)})

    # A4: S1-003 vocabulary alignment.
    shapes_text = SHAPES.read_text(encoding="utf-8")
    shape_statuses = parse_shape_status_vocabulary(shapes_text)
    check("A4_machine_states_equal_s1_003_vocabulary",
          len(shape_statuses) == 7 and set(shape_statuses) == set(STATES),
          {"shapes_v3_statuses": shape_statuses, "machine_states": list(STATES)})
    table_states = {f for f, _t, _g in rows} | {t for _f, t, _g in rows}
    check("A4_transition_states_within_s1_003_vocabulary",
          table_states <= set(shape_statuses),
          sorted(table_states - set(shape_statuses)) or "all inside vocabulary")
    alignment_claim = next(
        (c for c in claims if c.get("id") == "claim-s1-003-alignment"), None)
    check("A4_alignment_claim_present", alignment_claim is not None,
          "claim-s1-003-alignment")

    # A5: the bundle probes block wires both executable probes as expected pass.
    probes = bundle.get("probes", [])
    names = sorted(str(p.get("name", "")) for p in probes)
    expected_ok = (
        len(probes) >= 2
        and all(str(p.get("expected", "")) == "pass" for p in probes)
        and "s1-011-lifecycle-adversarial" in names
        and "s1-011-comparison-acceptance" in names)
    check("A5_probes_block_wires_both_probes", expected_ok,
          {"names": names})

    observed = "pass" if not failures else "fail"
    report = {
        "schema": "agentos.s1-011-comparison-probe/v1",
        "probe": "s1-011-comparison-acceptance",
        "expected": "pass",
        "observed": observed,
        "status": observed,
        "dimensions": dims,
        "transitions_defined": sorted([f"{f}->{t}:{g}" for f, t, g in rows]),
        "s1_003_status_vocabulary": shape_statuses,
        "total_checks": len(checks),
        "passed_checks": sum(1 for c in checks if c["passed"]),
        "failures": failures,
        "checks": checks,
    }
    RESULTS.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8", newline="\n")
    print(json.dumps({
        "schema": report["schema"],
        "probe": report["probe"],
        "status": observed,
        "observed": observed,
        "expected": "pass",
        "total_checks": report["total_checks"],
        "passed_checks": report["passed_checks"],
        "failures": report["failures"],
        "results_file": str(RESULTS),
    }, ensure_ascii=False))
    return 0 if observed == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
