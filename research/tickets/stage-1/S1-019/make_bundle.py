"""Derive the FLOW-11 bundle from frozen evidence and operator decision."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

TICKET = Path(__file__).resolve().parent
REPO = TICKET.parents[3]
FLOW = ("research_plan", "source_registry", "feature_catalog",
        "architecture_models", "mental_model", "ontology",
        "mathematical_model", "synthesis_and_gaps", "independent_audit",
        "platform_plan", "progress")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str) -> dict:
    return json.loads((TICKET / name).read_text("utf-8"))


def verify_operator() -> dict:
    decision = load("operator-decision.json")
    checks = {
        "questionnaire_sha256": TICKET / "operator-questionnaire.md",
        "frozen_manifest_sha256": TICKET / "frozen-manifest.json",
        "technical_comparison_sha256": TICKET / "results/comparison.json",
        "decision_matrix_sha256": TICKET / "decision-matrix.json",
    }
    for key, path in checks.items():
        if decision.get(key) != sha(path):
            raise ValueError(f"stale operator binding: {key}")
    if decision.get("derived_status") not in {"PASS_WITH_LIMITS", "DEFER"}:
        raise ValueError("operator did not authorize a limited/deferred result")
    return decision


def artifact_content(kind: str, decision: dict) -> str:
    status = decision["derived_status"]
    if kind == "platform_plan":
        return """# Scope
Research-only architecture baseline for EP-01..EP-05 and EP-08; no rollout.
# Architecture
Canonical principals, signed content-addressed registry, exact-action grants,
per-scope projections, provider-neutral gateway, hash chain, outbox and reconciliation.
# Workstreams
Implement each accepted row behind its gateway and evidence gates.
# Milestones
M1 contracts; M2 bounded implementation; M3 production-like qualification.
# Verification
Re-run frozen corpus, probes A-P, sensitivity, security and canonical evidence checks.
# Risks
Inherited local-model, same-host, operator-n=1 and no-production-proof limits remain.
# Open decisions
PARK-01 legal, PARK-03 production SLO and PARK-04 profile-C stay deferred.
"""
    labels = {
        "research_plan": "Dependency proof, frozen inputs, technical replay, operator decision, canonical publication.",
        "source_registry": "Ten hash-frozen research snapshots plus eighteen immutable dependency records.",
        "feature_catalog": "EP-01..05 and EP-08 carry bounded dispositions and explicit re-entry conditions.",
        "architecture_models": "Selected research baseline preserves all eight AgentOS authority invariants.",
        "mental_model": "Evidence ranks above preference; unknown and contradiction force abstention.",
        "ontology": "Dependencies, decisions, claims, assumptions, limits, conflicts and audits are typed.",
        "mathematical_model": "Hard gates are conjunctive; non-hard weights never compensate safety failure.",
        "synthesis_and_gaps": "All six rows remain bounded; PARK-01/03/04 and production proof remain gaps.",
        "independent_audit": "Process-separated replay agrees semantically and probes A-P fail closed.",
        "progress": f"Technical matrix complete; operator-derived status is {status}; canonical record pending.",
    }
    return "# S1-019 " + kind.replace("_", " ").title() + "\n" + labels[kind] + "\n"


def build() -> dict:
    decision = verify_operator()
    registry = load("source-registry.json")
    comparison = load("results/comparison.json")
    dependencies = load("results/dependency-gate.json")
    if comparison.get("verdict") != "TECHNICAL_CANDIDATE":
        raise ValueError("technical comparison failed")
    sources = [{
        "id": item["alias"],
        "canonical_uri": "https://local.agentos.invalid/" + item["canonical_path"],
        "title": item["title"], "source_type": "frozen_research_snapshot",
        "content_sha256": item["sha256"], "verification_status": "verified",
        "verifier": "agentos-s1-019-source-freezer",
        "verification_method": "sha256 local snapshot",
        "verifier_provenance": {"method": "sha256 local snapshot",
                                "path": item["canonical_path"],
                                "file_sha256": item["sha256"]},
    } for item in registry["sources"]]
    classes = ("synthesis", "decision", "assumption", "prototype_measurement",
               "residual_risk", "limitation", "audit_finding", "non_goal")
    claims = [{
        "id": f"CL-{index:02d}", "claim_class": (
            "fact" if cls in {"synthesis", "audit_finding"} else
            "assumption" if cls in {"assumption", "residual_risk", "limitation"} else
            "target" if cls == "decision" else "inference"),
        "s1_019_class": cls,
        "text": f"{cls}: S1-019 remains bounded and has no production or Goal-acceptance authority.",
        "source_ids": [sources[index % len(sources)]["id"]],
    } for index, cls in enumerate(classes)]
    artifacts = {}
    for index, kind in enumerate(FLOW):
        producer = ("agentos-s1-019-independent-verifier"
                    if kind == "independent_audit" else "agentos-s1-019-producer")
        artifacts[kind] = {"content": artifact_content(kind, decision),
                           "claim_refs": [claims[index % len(claims)]["id"]],
                           "producer": producer}
    limits = dependencies.get("inherited_limits", []) + [
        "same-host process-separated replay, not external audit",
        "ten initial sources are frozen local research snapshots",
        "no production-like, legal, hardware or population-human proof",
    ]
    return {
        "schema": "agentos.research-bundle/v1",
        "config": {"min_source_count": 10, "min_verified_ratio": 1.0,
                   "required_artifacts": list(FLOW)},
        "sources": sources, "claims": claims, "artifacts": artifacts,
        "audit": {"subject_producer": "agentos-s1-019-producer",
                  "auditor": "agentos-s1-019-independent-verifier",
                  "verdict": "pass_with_limits", "limitations": limits},
        "s1_019": {
            "operator_decision_sha256": sha(TICKET / "operator-decision.json"),
            "comparison_sha256": sha(TICKET / "results/comparison.json"),
            "frozen_manifest_sha256": sha(TICKET / "frozen-manifest.json"),
            "dependencies_sha256": sha(TICKET / "results/dependency-gate.json"),
            "wall_clock_preflight_sha256": sha(
                TICKET / "results/wall-clock-preflight.json"),
            "decision_matrix_sha256": sha(TICKET / "decision-matrix.json"),
            "technical_verdict": comparison["verdict"],
            "operator_status": decision["derived_status"],
            "verdict_ceiling": "PASS_WITH_LIMITS",
        },
    }


def main() -> int:
    bundle = build()
    (TICKET / "bundle.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    candidate = {
        "schema": "agentos.s1-019.candidate-record/v1",
        "status": bundle["s1_019"]["operator_status"],
        "bundle_sha256": sha(TICKET / "bundle.json"),
        "operator_decision_sha256": bundle["s1_019"]["operator_decision_sha256"],
        "comparison_sha256": bundle["s1_019"]["comparison_sha256"],
        "production_authority": False, "goal_acceptance_authority": False,
        "canonicalized": False,
    }
    (TICKET / "candidate-record.json").write_text(
        json.dumps(candidate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({"status": candidate["status"],
                      "bundle_sha256": candidate["bundle_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
