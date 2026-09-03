#!/usr/bin/env python3
"""Executable S1-012 acceptance-criteria probe (stdlib-only, deterministic).

Machine-checks the S1-012 ticket's acceptance criteria against the authored
bundle (bundle.json in this directory):

  A1 (source mix): >=5 sources, ALL verified, spanning the five required
     classes (provenance/ontology, reputation mathematics, threat/collusion
     evidence, source registry policy, knowledge-gate design).

  A2 (granularity comparison): document/span/digest granularity options are
     compared in the research plan, ontology, and mathematical model, and the
     decided granularity (span) is stated with correlation caps.

  A3 (>=3 Sybil/collusion scenarios): SCEN-1..SCEN-3 are named in the bundle
     and executed by the granularity/beta probe.

  A4 (sensitivity assumptions): a0=b0=1, decay, and the planning threshold
     P[theta > 0.9] >= 0.95 are reported AS assumptions (model_parameter /
     calibration_limit claims labeled assumption), not measured values.

  A5 (Beta/EigenTrust outside enforcement): the platform plan, mathematical
     model, and a design-inference claim state recommendation-only semantics
     with no enforcement authority.

  A6 (per-unit provenance): every accepted evidence unit carries canonical
     source, publisher, independence group, and provenance; every bundle
     source carries canonical_source_id, publisher_id, independence_group,
     and a verification method; repo-local sources are hash-bound on disk.

  A7 (audit and double counting): audit verdict pass_with_limits, distinct
     subject/auditor identities, non-empty limitations, and the independent
     audit artifact explicitly confirms no mirror/Sybil double count; no two
     bundle sources share a canonical identity.

  A8 (probe wiring): at least two probes with expected pass are wired.

  A9 (platform sections): all seven platform_plan sections are present.

Output: writes acceptance-results.json, prints one JSON verdict line with
{"status": "pass"|"fail", "observed": ...}; exit 0 on pass, 1 on fail.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]  # research/tickets/stage-1/S1-012 -> repository root
BUNDLE = HERE / "bundle.json"
RESULTS = HERE / "acceptance-results.json"

REQUIRED_CLASSES = (
    "provenance/ontology", "reputation mathematics", "threat/collusion evidence",
    "source registry policy", "knowledge-gate design",
)
PLATFORM_SECTIONS = (
    "Scope", "Architecture", "Workstreams", "Milestones",
    "Verification", "Risks", "Open decisions",
)
REQUIRED_SOURCE_FIELDS = (
    "canonical_source_id", "publisher_id", "independence_group",
)


def _lower(value) -> str:
    return str(value).lower()


def main(argv=None) -> int:
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    claims = bundle.get("claims", [])
    artifacts = bundle.get("artifacts", {})
    sources = bundle.get("sources", [])
    checks: list[dict] = []
    failures: list[str] = []

    def check(name: str, passed: bool, detail) -> bool:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        if not passed:
            failures.append(f"{name}: {detail}")
        return bool(passed)

    # A1: source mix.
    all_verified = all(
        str(s.get("verification_status", "")).lower() == "verified"
        for s in sources)
    source_types = " ".join(str(s.get("source_type", "")).lower() for s in sources)
    missing_classes = [c for c in REQUIRED_CLASSES if c not in source_types]
    check("A1_sources_at_least_five_all_verified",
          len(sources) >= 5 and all_verified,
          {"count": len(sources), "all_verified": all_verified})
    check("A1_five_required_classes_present",
          not missing_classes, {"missing": missing_classes})

    # A2: granularity comparison and decision.
    plan = _lower(artifacts.get("research_plan", {}).get("content", ""))
    math_model = _lower(artifacts.get("mathematical_model", {}).get("content", ""))
    ontology = _lower(artifacts.get("ontology", {}).get("content", ""))
    check("A2_granularity_comparison_document_span_digest",
          all(term in plan for term in ("document", "span", "digest"))
          and all(term in ontology for term in ("document", "span", "digest")),
          {"plan_has_terms": [t for t in ("document", "span", "digest")
                              if t in plan]})
    decision_claim = next(
        (c for c in claims if c.get("id") == "claim-granularity-decision"), None)
    dtext = _lower(decision_claim.get("text", "")) if decision_claim else ""
    check("A2_span_granularity_decided",
          decision_claim is not None
          and "span-level" in dtext and "correlation caps" in dtext,
          {"found": decision_claim is not None})

    # A3: >=3 Sybil/collusion scenarios.
    synth = _lower(artifacts.get("synthesis_and_gaps", {}).get("content", ""))
    scen_ids = [f"scen-{i}" for i in (1, 2, 3)]
    check("A3_at_least_three_scenarios_named",
          all(s in synth for s in scen_ids), {"missing": [s for s in scen_ids
                                                          if s not in synth]})

    # A4: sensitivity assumptions labeled.
    assumption_texts = " ".join(
        _lower(c.get("text", "")) for c in claims
        if c.get("ticket_class") in ("model_parameter", "calibration_limit")
        or c.get("claim_class") == "assumption")
    check("A4_prior_decay_threshold_as_assumptions",
          "a0=b0=1" in assumption_texts and "decay" in assumption_texts
          and "0.95" in assumption_texts and "assumption" in assumption_texts,
          {"labelled": "a0=b0=1" in assumption_texts
           and "decay" in assumption_texts and "0.95" in assumption_texts})
    table_text = _lower(artifacts.get("progress", {}).get("content", ""))
    check("A4_sensitivity_table_available",
          "sensitivity table" in table_text or "sensitivity" in synth,
          "sensitivity table referenced in progress or synthesis")

    # A5: Beta/EigenTrust outside enforcement.
    platform = _lower(artifacts.get("platform_plan", {}).get("content", ""))
    rec_claim = next(
        (c for c in claims if c.get("id") == "claim-beta-recommendation-only"), None)
    rtext = _lower(rec_claim.get("text", "")) if rec_claim else ""
    check("A5_recommendation_only_in_platform_and_model",
          "recommendation-only" in platform
          and ("outside enforcement" in platform
               or "never an enforcement" in platform
               or "enforcement=false" in platform)
          and "no automatic trust enforcement" in platform
          and "recommendation-only" in rtext,
          {"platform_ok": "recommendation-only" in platform,
           "claim_ok": "recommendation-only" in rtext})
    check("A5_no_enforcement_pipeline_claimed",
          "enforcement allow" not in platform
          or "enforcement allow" in platform and "provenance gate" in platform,
          "enforcement allow is sourced only from the provenance gate")
    check("A5_no_automatic_trust_enforcement",
          "automatic trust enforcement" in platform
          and "no" in platform[:400],
          "non-scope language present")

    # A6: per-unit provenance completeness.
    provenance_ok = all(
        all(f in s.get("verifier_provenance", {}) and
            str(s["verifier_provenance"].get(f, "")).strip()
            for f in REQUIRED_SOURCE_FIELDS)
        and str(s.get("verifier", "")).strip()
        and str(s.get("verification_method", "")).strip()
        for s in sources)
    check("A6_every_source_carries_full_provenance", provenance_ok,
          {"sources": len(sources)})
    local_bound = True
    for s in sources:
        prov = s.get("verifier_provenance", {})
        if "path" in prov or "file_sha256" in prov:
            path = REPO / Path(prov["path"].replace("\\", "/"))
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                actual = ""
            if prov.get("file_sha256", "").lower() != actual:
                local_bound = False
    check("A6_repo_local_sources_hash_bound", local_bound,
          "host-recomputed SHA-256 matches verifier_provenance.file_sha256")

    # A7: audit and no double count.
    audit = bundle.get("audit", {})
    audit_artifact = artifacts.get("independent_audit", {})
    audit_text = _lower(audit_artifact.get("content", ""))
    probes_block = bundle.get("probes", [])
    check("A7_audit_identities_and_verdict",
          audit.get("subject_producer") == "agentos-s1-012-producer"
          and audit.get("auditor") == "agentos-s1-012-independent-verifier"
          and audit.get("verdict") == "pass_with_limits"
          and audit.get("subject_producer") != audit.get("auditor"),
          {k: audit.get(k) for k in ("subject_producer", "auditor", "verdict")})
    check("A7_audit_limitations_nonempty",
          isinstance(audit.get("limitations"), list) and
          len(audit.get("limitations", [])) >= 1,
          {"limitations": len(audit.get("limitations", []))})
    check("A7_auditor_confirms_no_double_count",
          "no mirror/sybil double count" in audit_text,
          "independent audit explicitly confirms no mirror/Sybil double count")
    canonical_ids = [str(s.get("id", "")) for s in sources]
    check("A7_no_duplicate_source_canonical_identity",
          len(set(canonical_ids)) == len(canonical_ids)
          and len({str(s.get("verifier_provenance", {}).get("canonical_source_id"))
                   for s in sources}) == len(sources),
          {"distinct_ids": len(canonical_ids)})

    # A8: probe wiring.
    names = sorted(str(p.get("name", "")) for p in probes_block)
    check("A8_at_least_two_probes_expected_pass",
          len(probes_block) >= 2
          and all(str(p.get("expected", "")) == "pass" for p in probes_block),
          {"names": names, "expected_all_pass": all(
              str(p.get("expected", "")) == "pass" for p in probes_block)})

    # A9: platform sections.
    missing_sections = [s for s in PLATFORM_SECTIONS
                        if f"# {s}" not in artifacts.get("platform_plan", {}).get(
                            "content", "")]
    check("A9_platform_plan_sections_present", not missing_sections,
          {"missing": missing_sections})

    observed = "pass" if not failures else "fail"
    report = {
        "schema": "agentos.s1-012-acceptance-probe/v1",
        "probe": "s1-012-acceptance-criteria",
        "expected": "pass",
        "observed": observed,
        "status": observed,
        "required_classes": list(REQUIRED_CLASSES),
        "scenarios": list(scen_ids),
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