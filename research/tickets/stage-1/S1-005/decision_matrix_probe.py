#!/usr/bin/env python3
"""S1-005 executable decision-matrix probes (stdlib only, offline, no LLM/network).

Adversarial probes over ``research/tickets/stage-1/S1-005/bundle.json``
(ticket S1-005, QA1: modular monolith versus containers).  Fail-closed: any
missing artifact, unparsable matrix, hash mismatch, or unmapped outcome is a
failure or an explicit abstention, never a silent pass.

Probes
------
1. ``gateway-audit-invariants``
   Parses the QA1 decision matrix (``agentos.s1-005-decision-matrix/v1``,
   embedded as a fenced JSON block in the ``architecture_models`` artifact)
   and the recommended topology, then:
     a. verifies the recommendation preserves the hard invariants:
        effects only through the gateway, a single policy-state owner, and
        atomic transition+audit semantics;
     b. rejects a near-miss container split that duplicates policy state and
        weakens the audit boundary EVEN THOUGH it reports a better
        superficial latency score (latency is not an acceptance input);
     c. marks a modular-monolith recommendation that omits a failure
        boundary or the deterministic-simulation interface as incomplete
        (it must not be acceptable as-is);
     d. re-verifies every repo-local source hash declared in the bundle's
        ``verifier_provenance`` against the bytes on disk.

2. ``matrix-coverage``
   Verifies the quantitative acceptance criteria: both topologies compared
   on >=6 explicit dimensions with 1..5 scores and evidence references,
   >=3 failure/recovery scenarios, a single recommended topology with
   explicit assumptions, a migration trigger and non-goals, the required
   ticket claim-class coverage, and no production-build / measured-
   reliability claim.

The last stdout line is a machine-readable verdict:
``{"status": "pass"|"fail", "observed": "pass"|"fail", ...}`` and the
process exits 0 only on ``pass``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

TICKET_DIR = Path(__file__).resolve().parent
BUNDLE_PATH = TICKET_DIR / "bundle.json"
MATRIX_SCHEMA = "agentos.s1-005-decision-matrix/v1"
RESULTS_SCHEMA = "agentos.s1-005-probe-results/v1"
VERDICT_SCHEMA = "agentos.s1-005-probe-verdict/v1"

REQUIRED_TOPOLOGY = "modular_monolith"
MIN_DIMENSIONS = 6
MIN_SCENARIOS = 3
MIN_SCORE, MAX_SCORE = 1, 5

# Ticket claim-class taxonomy -> harness claim classes (research.py accepts
# fact|inference|assumption|target; the ticket labels live in claim text).
LABEL_TO_CLASSES = {
    "architecture_fact": {"fact"},
    "tradeoff": {"fact"},
    "design_inference": {"inference"},
    "risk": {"assumption"},
    "decision": {"inference", "target"},
}
MIN_LABEL_COUNTS = {
    "architecture_fact": 4,
    "tradeoff": 2,
    "design_inference": 2,
    "risk": 2,
    "decision": 2,
}

# Claims that would cross the ticket's non-scope line if asserted positively.
# Lookbehinds keep explicit negations ("no production containers are built")
# from matching as positive claims.
FORBIDDEN_POSITIVE_PATTERNS = (
    r"(?<!no )production containers (?:were|have been|are) built",
    r"(?<!no )cloud vendor (?:was|has been|is) selected",
    r"measured reliability (?:is|was|has been) (?:demonstrated|proven|established)",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_repo_root() -> Path:
    for candidate in (TICKET_DIR, *TICKET_DIR.parents):
        if (candidate / "AGENTS.md").is_file():
            return candidate
    raise RuntimeError("repository root (AGENTS.md) not found above ticket dir")


def load_bundle() -> dict:
    raw = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("bundle root must be a JSON object")
    return raw


def extract_matrix(bundle: dict) -> dict:
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, dict):
        raise RuntimeError("bundle has no artifacts object")
    arch = artifacts.get("architecture_models")
    if not isinstance(arch, dict):
        raise RuntimeError("architecture_models artifact missing")
    content = arch.get("content")
    text = content if isinstance(content, str) else json.dumps(content)
    matches = re.findall(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    for blob in matches:
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("schema") == MATRIX_SCHEMA:
            return parsed
    raise RuntimeError(f"no fenced JSON block with schema {MATRIX_SCHEMA} found")


def recommendation_of(matrix: dict) -> dict:
    rec = matrix.get("recommendation")
    if not isinstance(rec, dict):
        raise RuntimeError("matrix has no recommendation object")
    return rec


def invariant_violations(candidate: dict) -> list[str]:
    """Hard-invariant evaluation. Latency is deliberately NOT an input."""
    violations: list[str] = []
    if candidate.get("effects_gateway_only") is not True:
        violations.append("effects_not_gateway_only")
    if candidate.get("policy_state_single_owner") is not True:
        violations.append("policy_state_duplicated_or_unowned")
    if candidate.get("audit_boundary_atomic") is not True:
        violations.append("audit_boundary_weakened")
    return violations


def completeness_gaps(rec: dict) -> list[str]:
    """A recommendation is incomplete without these explicit parts."""
    gaps: list[str] = []
    if rec.get("topology") != REQUIRED_TOPOLOGY:
        gaps.append("topology_not_recommended")
    for key in ("failure_boundary", "deterministic_simulation_interface"):
        value = rec.get(key)
        if not isinstance(value, str) or len(value.strip()) < 12:
            gaps.append(f"missing_{key}")
    assumptions = rec.get("assumptions")
    if not isinstance(assumptions, list) or len([a for a in assumptions if str(a).strip()]) < 2:
        gaps.append("missing_explicit_assumptions")
    trigger = rec.get("migration_trigger")
    if not isinstance(trigger, list) or not [t for t in trigger if str(t).strip()]:
        gaps.append("missing_migration_trigger")
    non_goals = rec.get("non_goals")
    if not isinstance(non_goals, list) or len([n for n in non_goals if str(n).strip()]) < 2:
        gaps.append("missing_non_goals")
    return gaps


def verify_local_source_hashes(bundle: dict, repo_root: Path) -> tuple[list[str], int]:
    """Recompute every declared repo-local source binding from disk."""
    problems: list[str] = []
    checked = 0
    for source in bundle.get("sources", []):
        if not isinstance(source, dict):
            continue
        provenance = source.get("verifier_provenance")
        if not isinstance(provenance, dict):
            continue
        rel = provenance.get("path")
        expected = provenance.get("file_sha256")
        if not rel or not expected:
            continue
        checked += 1
        path = repo_root / rel
        if not path.is_file():
            problems.append(f"{source.get('id', '?')}: missing file {rel}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            problems.append(
                f"{source.get('id', '?')}: sha256 mismatch for {rel}")
    return problems, checked


def claims_by_label(bundle: dict) -> tuple[dict[str, int], list[str]]:
    counts = {label: 0 for label in LABEL_TO_CLASSES}
    problems: list[str] = []
    for claim in bundle.get("claims", []):
        if not isinstance(claim, dict):
            continue
        text = str(claim.get("text", ""))
        match = re.match(r"\[([a-z_]+)\]", text)
        label = match.group(1) if match else None
        if label not in LABEL_TO_CLASSES:
            problems.append(f"claim {claim.get('id', '?')} lacks a ticket-class label")
            continue
        counts[label] += 1
        if claim.get("claim_class") not in LABEL_TO_CLASSES[label]:
            problems.append(
                f"claim {claim.get('id', '?')} label {label} maps to "
                f"{LABEL_TO_CLASSES[label]} but declares {claim.get('claim_class')}")
    return counts, problems


# -- near-miss candidates (adversarial data evaluated with the same rules) --

NEAR_MISS_SPLIT = {
    "candidate": "container-split-policy-cache",
    "topology": "container_split",
    "policy_state_single_owner": False,
    "policy_state_note": "each container keeps a local copy of the policy/capability tables for fast checks",
    "audit_boundary_atomic": False,
    "audit_note": "audit events are buffered per container and flushed asynchronously to the audit store",
    "effects_gateway_only": True,
    "superficial_latency_ms_p99": 1.9,
    "latency_claim": "policy checks served from the local copy skip cross-process gateway serialization",
}

NEAR_MISS_MONOLITH_INCOMPLETE = {
    "candidate": "modular-monolith-incomplete",
    "topology": REQUIRED_TOPOLOGY,
    "policy_state_single_owner": True,
    "audit_boundary_atomic": True,
    "effects_gateway_only": True,
    "failure_boundary": "",
    "deterministic_simulation_interface": None,
    "assumptions": ["single host"],
    "migration_trigger": [],
    "non_goals": [],
}


def probe_gateway_audit_invariants(bundle: dict) -> dict:
    checks: list[dict] = []
    repo_root = find_repo_root()
    matrix = extract_matrix(bundle)
    rec = recommendation_of(matrix)

    def check(name: str, ok: bool, detail: str) -> bool:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    # (a) the recorded recommendation preserves the hard invariants.
    rec_violations = invariant_violations(rec)
    check("recommendation-preserves-gateway-audit-invariants",
          not rec_violations,
          f"violations={rec_violations}" if rec_violations
          else "effects_gateway_only, policy_state_single_owner, audit_boundary_atomic all hold")
    rec_gaps = completeness_gaps(rec)
    check("recommendation-declares-failure-boundary-and-simulation-interface",
          not rec_gaps, f"gaps={rec_gaps}" if rec_gaps else "failure boundary and deterministic-simulation interface present")
    check("recommendation-is-modular-monolith",
          rec.get("topology") == REQUIRED_TOPOLOGY,
          f"topology={rec.get('topology')}")

    # (b) near-miss split with duplicated policy state + async audit must be
    # rejected even though its superficial latency beats the measured
    # baseline (latency is not an acceptance input).
    baseline = float(matrix.get("baseline", {}).get(
        "measured_p99_end_to_end_ms_cold_100eps", 0) or 0)
    split_violations = invariant_violations(NEAR_MISS_SPLIT)
    latency_better = NEAR_MISS_SPLIT["superficial_latency_ms_p99"] < baseline
    check("near-miss-container-split-rejected-despite-better-latency",
          bool(split_violations) and latency_better,
          f"violations={split_violations}; superficial latency "
          f"{NEAR_MISS_SPLIT['superficial_latency_ms_p99']}ms < measured baseline {baseline}ms; "
          "rejection is latency-independent")
    # (c) modular-monolith recommendation omitting a failure boundary or the
    # deterministic-simulation interface must be marked incomplete.
    incomplete_gaps = completeness_gaps(NEAR_MISS_MONOLITH_INCOMPLETE)
    check("near-miss-monolith-omitting-boundaries-marked-incomplete",
          bool(incomplete_gaps),
          f"completeness gaps={incomplete_gaps}")

    # (d) evidence integrity: every declared repo-local source hash must
    # still match the bytes on disk.
    hash_problems, hash_count = verify_local_source_hashes(bundle, repo_root)
    check("repo-local-source-hashes-verified-from-disk",
          not hash_problems and hash_count >= 5,
          f"{hash_count} file bindings checked; problems={hash_problems}")

    # platform_plan must state the preserved semantics explicitly.
    platform = bundle.get("artifacts", {}).get("platform_plan", {})
    platform_text = platform.get("content") if isinstance(platform.get("content"), str) else json.dumps(platform.get("content", ""))
    check("platform-plan-states-gateway-only-effects-and-atomic-audit",
          "gateway-only" in platform_text.lower()
          and "transition+audit" in platform_text.lower(),
          "platform_plan must preserve gateway-only effects and atomic transition+audit")

    failed = [c["name"] for c in checks if not c["ok"]]
    verdict = "pass" if not failed else "fail"
    return {
        "probe": "gateway-audit-invariants",
        "schema": VERDICT_SCHEMA,
        "status": verdict,
        "observed": verdict,
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "failed_checks": failed,
        "checks": checks,
    }


def probe_matrix_coverage(bundle: dict) -> dict:
    checks: list[dict] = []
    matrix = extract_matrix(bundle)

    def check(name: str, ok: bool, detail: str) -> bool:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    # >=6 dimensions, both options scored 1..5 with evidence references.
    dimensions = matrix.get("dimensions")
    dims_ok = isinstance(dimensions, list) and len(dimensions) >= MIN_DIMENSIONS
    problems: list[str] = []
    sums = {"modular_monolith": 0, "container_split": 0}
    if dims_ok:
        for dim in dimensions:
            if not isinstance(dim, dict) or not dim.get("id") or not dim.get("name"):
                problems.append("dimension missing id/name")
                continue
            for option in ("modular_monolith", "container_split"):
                side = dim.get(option)
                if not isinstance(side, dict):
                    problems.append(f"{dim.get('id')}/{option} missing")
                    continue
                score = side.get("score")
                if not isinstance(score, int) or not MIN_SCORE <= score <= MAX_SCORE:
                    problems.append(f"{dim.get('id')}/{option} score {score!r} outside {MIN_SCORE}..{MAX_SCORE}")
                else:
                    sums[option] += score
                if not side.get("evidence"):
                    problems.append(f"{dim.get('id')}/{option} lacks evidence refs")
                if not str(side.get("notes", "")).strip():
                    problems.append(f"{dim.get('id')}/{option} lacks notes")
    else:
        problems.append(f"only {len(dimensions) if isinstance(dimensions, list) else 0} dimensions present")
    check(f"at-least-{MIN_DIMENSIONS}-dimensions-both-options-scored-with-evidence",
          dims_ok and not problems, f"{len(dimensions) if isinstance(dimensions, list) else 0} dimensions; problems={problems}")

    totals = matrix.get("totals") if isinstance(matrix.get("totals"), dict) else {}
    check("totals-consistent-with-dimension-scores",
          totals.get("modular_monolith") == sums["modular_monolith"]
          and totals.get("container_split") == sums["container_split"],
          f"declared={totals} recomputed={sums}")

    # >=3 failure/recovery scenarios with detection + both recoveries.
    scenarios = matrix.get("failure_scenarios")
    scen_problems: list[str] = []
    if isinstance(scenarios, list) and len(scenarios) >= MIN_SCENARIOS:
        for scenario in scenarios:
            sid = scenario.get("id", "?") if isinstance(scenario, dict) else "?"
            for key in ("detection", "modular_monolith_recovery", "container_split_recovery", "evidence"):
                value = scenario.get(key) if isinstance(scenario, dict) else None
                if not value or (key == "evidence" and not isinstance(value, list)):
                    scen_problems.append(f"{sid} missing {key}")
    else:
        scen_problems.append(f"only {len(scenarios) if isinstance(scenarios, list) else 0} scenarios present")
    check(f"at-least-{MIN_SCENARIOS}-failure-recovery-scenarios-complete",
          not scen_problems, f"{len(scenarios) if isinstance(scenarios, list) else 0} scenarios; problems={scen_problems}")

    # Single recommended topology with assumptions, trigger, non-goals.
    rec = recommendation_of(matrix)
    gaps = completeness_gaps(rec)
    check("single-recommendation-with-assumptions-trigger-and-non-goals",
          not gaps, f"gaps={gaps}" if gaps else "assumptions, migration trigger and non-goals present")

    non_goals_text = " ".join(str(n) for n in rec.get("non_goals", [])).lower()
    check("non-goals-cover-production-cloud-vendor-and-measured-reliability",
          all(token in non_goals_text for token in ("production", "cloud vendor", "measured reliability")),
          f"non_goals={non_goals_text}")

    # Ticket claim-class coverage and harness-class mapping.
    counts, claim_problems = claims_by_label(bundle)
    short = {label: counts[label] for label, minimum in MIN_LABEL_COUNTS.items()
             if counts[label] < minimum}
    check("ticket-claim-class-coverage-present-and-mapped",
          not short and not claim_problems,
          f"counts={counts}; short={short}; problems={claim_problems}")

    # No positive production-build / measured-reliability claim anywhere.
    haystacks = [str(c.get("text", "")) for c in bundle.get("claims", []) if isinstance(c, dict)]
    for kind, artifact in bundle.get("artifacts", {}).items():
        content = artifact.get("content") if isinstance(artifact, dict) else None
        haystacks.append(content if isinstance(content, str) else json.dumps(content))
    blob = "\n".join(haystacks)
    hits = [pat for pat in FORBIDDEN_POSITIVE_PATTERNS if re.search(pat, blob, flags=re.I)]
    check("no-production-build-or-measured-reliability-claim",
          not hits, f"forbidden positive claims: {hits}" if hits else "scope limits intact")

    failed = [c["name"] for c in checks if not c["ok"]]
    verdict = "pass" if not failed else "fail"
    return {
        "probe": "matrix-coverage",
        "schema": VERDICT_SCHEMA,
        "status": verdict,
        "observed": verdict,
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "failed_checks": failed,
        "checks": checks,
    }


PROBES = {
    "gateway-audit-invariants": probe_gateway_audit_invariants,
    "matrix-coverage": probe_matrix_coverage,
}


def write_results(path: Path, records: list[dict]) -> None:
    existing: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            existing = {}
    probes = {p.get("probe"): p for p in existing.get("probes", []) if isinstance(p, dict)}
    for record in records:
        probes[record["probe"]] = record
    ordered = [probes[name] for name in ("gateway-audit-invariants", "matrix-coverage") if name in probes]
    final = "pass" if all(p["status"] == "pass" for p in ordered) else "fail"
    document = {
        "schema": RESULTS_SCHEMA,
        "ticket": "S1-005",
        "probes": ordered,
        "final_verdict": final,
    }
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1-005 decision-matrix probes")
    parser.add_argument("--probe", choices=sorted(PROBES), required=True)
    parser.add_argument("--out", default=None,
                        help="optional path to merge this probe's record into a results JSON")
    args = parser.parse_args(argv)

    try:
        bundle = load_bundle()
        record = PROBES[args.probe](bundle)
    except Exception as exc:  # fail closed: any probe error is a failure
        record = {
            "probe": args.probe,
            "schema": VERDICT_SCHEMA,
            "status": "fail",
            "observed": "fail",
            "error": f"{type(exc).__name__}: {exc}",
        }
    if args.out:
        try:
            write_results(Path(args.out), [record])
        except OSError as exc:
            print(f"warning: could not write results file: {exc}", file=sys.stderr)
    print(json.dumps({
        "probe": record["probe"],
        "checks_total": record.get("checks_total"),
        "checks_failed": record.get("checks_failed"),
    }))
    print(json.dumps(record, ensure_ascii=False))
    return 0 if record["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
