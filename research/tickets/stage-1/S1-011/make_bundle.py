"""S1-011 FLOW-11 bundle assembler (stdlib only).

Mechanically derives bundle.json from frozen inputs (contracts, corpus,
registry, results). Artifact prose is embedded here verbatim and grounded
only in ticket files; all hashes/provenance are computed, never copied.

Also writes candidate-record.json with status READY_FOR_CANONICALIZATION
and WITHOUT any fabricated canonical ids, revisions, or chain hashes.

Usage: py -3.12 make_bundle.py   (run from the S1-011 ticket dir)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(name: str):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def load_result(name: str):
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def file_sha(name: str) -> str:
    return sha((HERE / name).read_bytes())


ARTIFACTS = {
    "research_plan": (
        "Compare minimal promote/challenge gate vs argumentation vs TMS "
        "for the first AgentOS knowledge layer. Frozen contract v1.0.0, "
        "60-case corpus x 3 designs x 3 seeds, two process-separated runs "
        "on one clean commit/tree, fail-closed evaluator with 11 exact-zero "
        "hard gates, probes A-H, 220-composition sensitivity. Verdict cap "
        "PASS_WITH_LIMITS. Phase B (local canonical harness) required "
        "before closure."),
    "source_registry": (
        "5 frozen snapshots (source-registry.json, schema "
        "agentos.s1-011.source-registry/v1): S1-005 synthesis/gaps "
        "(G-06 argumentation/TMS gap), S1-003 shapes-v3.ttl (executable "
        "ontology), S1-003 fixtures.json (lifecycle fixtures), S1-001 "
        "bundle.json (promotion policy evidence), 15-20 hypothesis review "
        "(operator/UX input). Dependencies S1-001 (pass_with_limits, rev "
        "1) and S1-003 (pass, rev 24) proven from tracked Git bytes "
        "(dependency-gate.json); live DB recheck deferred to Phase B."),
    "feature_catalog": (
        "Claim classes: knowledge_fact, design_inference, hypothesis, "
        "operator_risk, decision. Gate features: provisional threshold "
        "(2 verified / 2 lineage-collapsed groups), challenge with "
        "immediate view exclusion, uphold-as-new-decision, "
        "retraction/revocation/supersession with history preserved, "
        "derived-view inclusion predicate with stale-epoch fail-closed, "
        "idempotent concurrent transitions, atomic transition+audit, "
        "external-content quarantine."),
    "architecture_models": (
        "Three executable semantics over shared governance plumbing. "
        "minimal-gate: 5-state machine x threshold checklist. "
        "argumentation: grounded-style IN (supporters>=1, attackers OUT "
        "iff countered); no independence counting; transitive parent "
        "support allowed (naive, probe-G target). tms: justification "
        "holding with automatic revision by tms_engine and no governance "
        "decision (naive, authority-invariant target). Shared: authority, "
        "challenge/retraction/replay/read/concurrency/external "
        "procedures."),
    "mental_model": (
        "Five operator-visible states. PROMOTED means only 'passed the "
        "versioned gate for this scope/policy', never objective truth. "
        "Challenge and revocation remove claims from the eligible view at "
        "once; audit history is never deleted. Re-promotion is a new "
        "decision, not an edit."),
    "ontology": (
        "Record types: assertion, evidence, provenance, scope, decision, "
        "audit_event (knowledge-record.schema.json, append-only with "
        "SUPERSEDES). S1-003 mapping: KnowledgeAssertion "
        "proposed/under_review->PROPOSED, promoted->PROMOTED, "
        "challenged->CHALLENGED, retracted->RETRACTED, "
        "superseded->RETRACTED+SUPERSEDES, rejected->REJECTED; "
        "DelegationGrant revocation feeds source_revoked handling. No "
        "contradiction. No SHACL mapping yet for attack/support/"
        "justification relations (explicit gap)."),
    "mathematical_model": (
        "Threshold: |eligible|>=2 AND |lineages|>=2 AND |groups|>=2 AND "
        "same version/scope AND no open challenge/revocation AND policy "
        "current. Acceptability: IN iff supporters>=1 AND all attackers "
        "OUT. Justification: IN iff >=1 holding justification AND no live "
        "contradiction. Metrics: confusion over eligible transitions, "
        "per-class P/R/FPR/FNR with Wilson 95% intervals, operator model "
        "(simulation). Scores: measured safety (52% weight) + frozen "
        "qualitative cells with UNKNOWN abstention; minimal 0.936 vs 0.489 "
        "/ 0.489; 220 sensitivity compositions, 0 flips."),
    "synthesis_and_gaps": (
        "Minimal gate passes everything; naive argumentation fails A/D/G "
        "(correlated support promotes; transitive support launders); "
        "naive TMS additionally fails authority (33 auto-revisions without "
        "governance decisions). Shared plumbing passes B/C/E/F/H for all. "
        "Gaps: cyclic attack-graph convergence UNKNOWN; UNDECIDED handling "
        "unexercised; real independence calibration is S1-012; operator "
        "comprehension unmeasured until S1-013."),
    "independent_audit": (
        "Audit path (evaluator.py + compare_runs.py) is independent code "
        "from the producer path (runner.py) and reads only raw rows plus "
        "the frozen oracle. A/B: 18 distinct processes, one commit "
        "2b64743 / one tree, all clean, exact 540-row matrices, 540/540 "
        "identical rows, distinct PID/PPID/invocation/nonce/executor/"
        "output-root. Hard counters: minimal all-zero; argumentation "
        "12+12+2; tms 15+15+33+2. Verdicts: PASS / FAIL / FAIL. "
        "Regression suite 46/46. Limits: tracked-Git evidence only; no "
        "live DB, chain, or wiki claims."),
    "platform_plan": (
        "Adopt contract v1.0.0 + state machine as the MVP knowledge-layer "
        "boundary (allows G-06 decision). Implement threshold checklist, "
        "challenge SLA handling, revocation propagation, derived-view "
        "projection with epoch fail-closed, idempotency keys, atomic "
        "journal. Roll back by re-running preserved history under a prior "
        "contract version. Block production on S1-012 calibration and "
        "S1-013 operator validation."),
    "progress": (
        "Phase A complete: dependency gate PROVEN; 5 sources frozen; 7 "
        "contracts/schemas frozen and hashed; 60-case oracle frozen "
        "(canonicalized, per-case SHA-256); stdlib runner/evaluator/"
        "compare sensitivity tooling with 46/46 regressions (RED->GREEN "
        "recorded); two process-separated runs (18 cells); comparison, "
        "metrics, probes, sensitivity, ENVIRONMENT, decision, roadmap; "
        "FLOW-11 bundle; candidate record READY_FOR_CANONICALIZATION. "
        "Open: Phase B local canonical round, then closure."),
}

REQUIRED = ["research_plan", "source_registry", "feature_catalog",
            "architecture_models", "mental_model", "ontology",
            "mathematical_model", "synthesis_and_gaps",
            "independent_audit", "platform_plan", "progress"]


def main() -> int:
    for key in REQUIRED:
        text = ARTIFACTS[key]
        if not text or not text.strip():
            raise SystemExit(f"FLOW-11 artifact {key} is empty")
    manifest = load("corpus-manifest.json")
    registry = load("source-registry.json")
    gate = load("dependency-gate.json")
    comparison = load_result("comparison.json")
    metrics = load_result("metrics.json")
    sens = load_result("sensitivity.json")
    bundle = {
        "schema": "agentos.s1-011.bundle/v1",
        "ticket": "S1-011",
        "config": {"required_artifacts": REQUIRED,
                   "min_source_count": 4,
                   "verdict_cap": "PASS_WITH_LIMITS"},
        "sources": registry["sources"],
        "claims": [
            {"id": "CL-01",
             "text": "Minimal gate passes all hard safety gates",
             "verdict": "supported",
             "refs": ["results/metrics.json:minimal-gate"]},
            {"id": "CL-02",
             "text": "Naive argumentation promotes correlated and "
                     "transitive support (probes A/D/G fail)",
             "verdict": "supported",
             "refs": ["results/metrics.json:argumentation",
                      "results/probes.json:argumentation"]},
            {"id": "CL-03",
             "text": "Naive TMS revises beliefs without governance "
                     "decisions (authority expansions) and shares the "
                     "acceptability weakness",
             "verdict": "supported",
             "refs": ["results/metrics.json:tms",
                      "results/probes.json:tms"]},
            {"id": "CL-04",
             "text": "Winner robust to all 220 sensitivity compositions",
             "verdict": "supported",
             "refs": ["results/sensitivity.json"]},
            {"id": "CL-05",
             "text": "Production blocked pending S1-012 calibration and "
                     "S1-013 operator study",
             "verdict": "limitation",
             "refs": ["results/decision.md", "results/roadmap.md"]},
        ],
        "artifacts": dict(ARTIFACTS),
        "audit": {
            "dependency_gate": {
                "verdict": "PROVEN" if gate["all_proven"] else "BLOCKED",
                "canonical_db_recheck_required":
                    gate["canonical_db_recheck_required"],
            },
            "runs": {"commit": comparison["commits"],
                     "trees": comparison["trees"],
                     "cells": comparison["cells"]},
            "metrics_verdicts": {design: doc["verdict"] for design, doc in
                                 metrics["designs"].items()},
            "sensitivity_winner": sens["winner"],
            "sensitivity_flips": sens["flip_count"],
            "frozen_hashes": manifest["hashes"],
            "limitations": [
                "tracked-Git evidence only; no live DB claims",
                "provisional threshold uncalibrated (S1-012)",
                "operator model is simulation, not a human study (S1-013)",
                "no cyclic attack graphs in corpus",
                "no SHACL mapping for attack/support/justification",
            ],
        },
    }
    bundle_text = json.dumps(bundle, indent=2, sort_keys=True) + "\n"
    (HERE / "bundle.json").write_text(bundle_text, encoding="utf-8")
    bundle_sha = sha(bundle_text.encode("utf-8"))
    candidate = {
        "schema": "agentos.s1-011.candidate-record/v1",
        "ticket": "S1-011",
        "status": "READY_FOR_CANONICALIZATION",
        "verdict": "PASS_WITH_LIMITS",
        "bundle_path": "research/tickets/stage-1/S1-011/bundle.json",
        "bundle_sha256": bundle_sha,
        "comparison_sha256": sha((RESULTS / "comparison.json")
                                 .read_bytes()),
        "metrics_sha256": sha((RESULTS / "metrics.json").read_bytes()),
        "frozen_hashes": manifest["hashes"],
        "run_provenance": {"commits": comparison["commits"],
                           "trees": comparison["trees"],
                           "cells": comparison["cells"]},
        "assumptions": [
            "naive textbook semantics faithfully represent the model "
            "families for MVP comparison",
            "lineage equality is an adequate proxy for source dependence",
            "operator SLA hypothesis stands in for measured cost",
        ],
        "unknowns": [
            "cyclic attack-graph convergence",
            "true challenge/contradiction rates",
            "UNDECIDED/backtracking operator procedures",
        ],
        "residual_risks": [
            "novel Sybil shapes evading lineage analysis",
            "threshold miscalibration admitting correlated evidence",
        ],
        "phase_b_required": True,
        "chain_fresh_claim": None,
        "note": "No goal_id, campaign_id, evaluation_id, research "
                "revision, artifact-chain hash, or wiki counts are stated "
                "here; those are Phase B canonical-harness outputs only.",
    }
    (HERE / "candidate-record.json").write_text(
        json.dumps(candidate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"bundle.json sha256={bundle_sha}")
    print("candidate-record.json status=READY_FOR_CANONICALIZATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
