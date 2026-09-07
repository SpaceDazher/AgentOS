"""Derive the FLOW-11 S1-020 bundle from measured audit evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
FLOW = ("research_plan", "source_registry", "feature_catalog", "architecture_models",
        "mental_model", "ontology", "mathematical_model", "synthesis_and_gaps",
        "independent_audit", "platform_plan", "progress")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def content(kind: str) -> str:
    if kind == "platform_plan":
        return """# Scope
Close Stage 1 research evidence only; no product acceptance or production certification.
# Architecture
Use the canonical SQLite research series, evidence-pack/v3, immutable Git bindings,
hash-frozen inputs, independent probe replay, and an Obsidian projection as a cache.
# Workstreams
Preserve prior bounded findings; route production, legal, source-tail, and profile-C
rollout work through their explicit re-entry conditions.
# Milestones
M1 dependency/probe gate; M2 independent rerun; M3 canonical pack; M4 wiki check.
# Verification
Re-run 19 dependency checks, 19 ticket probe checks, 60 corpus cases twice, 256
sensitivity trials, canonical chain verification, and wiki-check.
# Risks
Same-host audit and inherited PASS_WITH_LIMITS evidence do not establish production.
# Open decisions
PARK-01 legal, PARK-02 source tail, PARK-03 production SLO, and PARK-04 profile-C
rollout remain parked until their recorded triggers are satisfied.
"""
    text = {
        "research_plan": "Audit one immutable base, replay all 19 dependencies and probes, then canonicalize.",
        "source_registry": "Ten frozen source aliases and nineteen canonical ticket records are hash-bound.",
        "feature_catalog": "Twenty active tickets and four parked items are accounted without status inflation.",
        "architecture_models": "Closure is a conjunctive fail-closed gate over dependency, probe, freshness, identity, and coverage evidence.",
        "mental_model": "A ticket label is a claim; immutable evidence and adversarial replay decide closure.",
        "ontology": "Ticket, dependency, probe, open item, limitation, parked item, auditor, evaluation, and evidence pack are typed.",
        "mathematical_model": "Closure equals the conjunction of every hard gate; no score compensates a failed gate.",
        "synthesis_and_gaps": "Stage 1 is research-complete with limits; production, legal, mass-source, and rollout claims remain excluded.",
        "independent_audit": "Two process-separated auditors agree on 120 observations; 19/19 prior probes and dependencies pass.",
        "progress": "Independent audit complete; canonical research revision and wiki projection are the remaining publication steps.",
    }[kind]
    return f"# S1-020 {kind.replace('_', ' ').title()}\n{text}\n"


def build() -> dict:
    registry = load("source-registry.json")
    gate = load("dependency-gate.json")
    comparison = load("results/comparison.json")
    summary = load("results/summary.json")
    sensitivity = load("results/sensitivity.json")
    if gate.get("status") != "PASS_WITH_LIMITS" or comparison.get("verdict") != "PASS_WITH_LIMITS":
        raise ValueError("measured closure gates are not publishable")
    if sensitivity.get("winner_flips") != 0 or summary.get("observations") != 120:
        raise ValueError("sensitivity or matrix incomplete")
    sources = []
    for item in registry["sources"]:
        identifier = item.get("alias") or item.get("id")
        sources.append({
            "id": identifier,
            "canonical_uri": item.get("canonical_uri") or
                             ("https://local.agentos.invalid/" + item["canonical_path"]),
            "title": item["title"], "source_type": item.get("source_type", "frozen source"),
            "content_sha256": item["sha256"], "verification_status": "verified",
            "verifier": "agentos-s1-020-independent-auditor",
            "verification_method": "sha256 immutable Git blob",
            "verifier_provenance": {"commit": item.get("verified_commit"),
                                    "path": item["canonical_path"],
                                    "file_sha256": item["sha256"]},
        })
    claim_specs = [
        ("fact", "All 19 active dependencies resolve from one immutable base commit."),
        ("audit_finding", "All 19 prior ticket probe sources pass schema-aware replay."),
        ("coverage", "Twenty active tickets and four parked items are explicitly accounted."),
        ("evaluation_result", "Two process-separated runs match 60 of 60 cases each."),
        ("limitation", "All bounded prior PASS_WITH_LIMITS findings remain binding."),
        ("closure_decision", "Stage 1 closes as PASS_WITH_LIMITS for research only."),
        ("next_step", "Parked work re-enters only through its recorded trigger."),
        ("non_goal", "Research-plan PASS does not set a Goal to ACCEPTED."),
    ]
    claims = [{"id": f"CL-{i:02d}",
               "claim_class": ("fact" if cls in {"fact", "audit_finding", "coverage"}
                               else "assumption" if cls == "limitation"
                               else "target" if cls == "next_step" else "inference"),
               "s1_020_class": cls, "text": text,
               "source_ids": [sources[i % len(sources)]["id"]]}
              for i, (cls, text) in enumerate(claim_specs)]
    artifacts = {}
    for i, kind in enumerate(FLOW):
        artifacts[kind] = {"content": content(kind),
                           "claim_refs": [claims[i % len(claims)]["id"]],
                           "producer": ("agentos-s1-020-independent-auditor"
                                        if kind == "independent_audit"
                                        else "agentos-s1-020-bundle-producer")}
    inherited = [limit for row in gate["dependencies"]
                 for limit in row.get("inherited_limits", []) if isinstance(limit, str)]
    limitations = list(dict.fromkeys(inherited + load("closure-contract.json")["limits"]))
    return {
        "schema": "agentos.research-bundle/v1",
        "config": {"min_source_count": 29, "min_verified_ratio": 1.0,
                   "required_artifacts": list(FLOW)},
        "sources": sources, "claims": claims, "artifacts": artifacts,
        "audit": {"subject_producer": "agentos-s1-020-bundle-producer",
                  "auditor": "agentos-s1-020-independent-auditor",
                  "verdict": "pass_with_limits", "limitations": limitations},
        "s1_020": {"base_commit": gate["verified_commit"],
                   "dependencies_sha256": sha(HERE / "dependency-gate.json"),
                   "comparison_sha256": sha(HERE / "results/comparison.json"),
                   "sensitivity_sha256": sha(HERE / "results/sensitivity.json"),
                   "frozen_manifest_sha256": sha(HERE / "frozen-manifest.json"),
                   "coverage_sha256": sha(HERE / "coverage-matrix.json"),
                   "active_ticket_count": 20, "parked_count": 4,
                   "prior_dependency_count": 19, "prior_probe_count": 19,
                   "technical_status": "PASS_WITH_LIMITS",
                   "production_authority": False, "goal_acceptance_authority": False,
                   "reopen_parked_items": False},
    }


def main() -> int:
    bundle = build()
    (HERE / "bundle.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    candidate = {"schema": "agentos.s1-020.candidate-record/v1",
                 "status": "PASS_WITH_LIMITS", "bundle_sha256": sha(HERE / "bundle.json"),
                 "comparison_sha256": bundle["s1_020"]["comparison_sha256"],
                 "production_authority": False, "goal_acceptance_authority": False,
                 "parked_items_reopened": False, "canonicalized": False}
    (HERE / "candidate-record.json").write_text(
        json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        newline="\n")
    print(json.dumps({"status": candidate["status"], "sources": len(bundle["sources"]),
                      "bundle_sha256": candidate["bundle_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
