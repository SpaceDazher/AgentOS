"""S1-011 FLOW-11 bundle assembler (stdlib only).

Builds the NATIVE research bundle schema consumed by
src/agentos/research.py (_normalise_config, _normalize_bundle,
_evaluation_checks) — no shim fields. Sources embed their frozen
snapshot bytes with verified content hashes; claims carry typed classes
and support links; substantive artifacts carry claim references;
platform_plan carries the seven required sections; producer/auditor
identities are distinct and consistent.

Verdict is DERIVED, never constant (F9): the generator re-reads
dependency-gate.json, merged metrics/probes and comparison/sensitivity.
Any blocking cause (gate not proven, chosen design not PASS, probes not
all-pass, no winner, flips, unknown-dependence) refuses to publish a
ready record (exit 1, no candidate-record.json written).

Usage: py -3.12 make_bundle.py   (run from the S1-011 ticket dir)
"""
from __future__ import annotations

import hashlib
import json
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

PRODUCER = "agentos-s1-011-producer"
AUDITOR = "agentos-s1-011-independent-verifier"

FLOW = ["research_plan", "source_registry", "feature_catalog",
        "architecture_models", "mental_model", "ontology",
        "mathematical_model", "synthesis_and_gaps", "independent_audit",
        "platform_plan", "progress"]

SOURCE_SPECS = [
    ("SRC-S1-011-01", "snapshots/snap-01-s1-005-synthesis-gaps.md",
     "S1-005 synthesis and gaps (G-06 argumentation/TMS gap)",
     "research-snapshot",
     "Hash-reviewed tracked snapshot of prior-ticket synthesis evidence."),
    ("SRC-S1-011-02", "snapshots/snap-02-s1-003-shapes-v3.ttl",
     "S1-003 shapes-v3 (executable SHACL ontology)",
     "ontology-shacl",
     "Hash-reviewed tracked executable ontology used for lifecycle mapping."),
    ("SRC-S1-011-03", "snapshots/snap-03-s1-003-fixtures.json",
     "S1-003 fixtures (lifecycle cases)",
     "ontology-fixtures",
     "Hash-reviewed tracked fixture set backing the mapping proof."),
    ("SRC-S1-011-04", "snapshots/snap-04-s1-001-bundle.json",
     "S1-001 bundle (promotion policy evidence)",
     "policy-evidence",
     "Hash-reviewed tracked promotion-policy bundle (dependency)."),
    ("SRC-S1-011-05", "snapshots/snap-05-hypothesis-review-15-20.md",
     "15-20 hypothesis review (operator/UX input)",
     "operator-input",
     "Hash-reviewed tracked operator/UX hypothesis material."),
]

CLAIMS = [
    {"id": "CL-F1",
     "text": "S1-003 fixtures expose proposed, promoted, rejected, "
             "superseded and revoked lifecycle states with executable "
             "SHACL semantics.",
     "claim_class": "fact",
     "support": ["SRC-S1-011-02", "SRC-S1-011-03"]},
    {"id": "CL-F2",
     "text": "S1-001 promotion policy requires verified sources and "
             "independence handling before promotion.",
     "claim_class": "fact",
     "support": ["SRC-S1-011-04"]},
    {"id": "CL-I1",
     "text": "Naive acceptability without independence counting promotes "
             "single and correlated support, failing probes A and D.",
     "claim_class": "inference",
     "support": ["SRC-S1-011-01", "SRC-S1-011-03"]},
    {"id": "CL-I2",
     "text": "Automatic belief revision without a governance decision "
             "expands authority and fails the authority invariant.",
     "claim_class": "inference",
     "support": ["SRC-S1-011-01"]},
    {"id": "CL-I3",
     "text": "The minimal gate passes all hard safety gates and probes "
             "A-H on the frozen 72-case matrix in two process-separated "
             "runs.",
     "claim_class": "inference",
     "support": ["SRC-S1-011-02", "SRC-S1-011-03", "SRC-S1-011-04"]},
    {"id": "CL-A1",
     "text": "Provenance lineage equality is an adequate proxy for source "
             "dependence for MVP comparison.",
     "claim_class": "assumption",
     "support": ["SRC-S1-011-04"]},
    {"id": "CL-A2",
     "text": "The operator SLA hypothesis stands in for measured "
             "resolution cost until the S1-013 human study.",
     "claim_class": "assumption",
     "support": ["SRC-S1-011-05"]},
    {"id": "CL-T1",
     "text": "Adopt the minimal promote/challenge gate as the MVP "
             "knowledge-layer boundary, resolving G-06 for the MVP scope.",
     "claim_class": "target",
     "support": ["SRC-S1-011-01", "SRC-S1-011-02", "SRC-S1-011-05"]},
]

ARTIFACT_TEXTS = {
    "research_plan": (
        "Compare minimal promote/challenge gate vs argumentation vs TMS "
        "for the first AgentOS knowledge layer. Frozen contract v1.0.2, "
        "72-case corpus x 3 designs x 3 seeds, two process-separated runs "
        "on one clean commit/tree, fail-closed evaluator with 11 exact-zero "
        "hard gates plus transition-consistency and ledger checks, probes "
        "A-H, 220-composition sensitivity with UNKNOWN disclosure. Verdict "
        "cap PASS_WITH_LIMITS. Phase B local canonical round required."),
    "source_registry": (
        "Five frozen snapshots with SHA-256 (source-registry.json): prior "
        "synthesis/gaps, executable SHACL ontology and fixtures, "
        "promotion-policy bundle, operator hypothesis review. "
        "Dependencies S1-001/S1-003 proven from tracked Git bytes; live DB "
        "recheck deferred to Phase B."),
    "feature_catalog": (
        "Claim classes knowledge_fact, design_inference, hypothesis, "
        "operator_risk, decision. Gate features: provisional threshold "
        "with strict evidence bindings, challenge with immediate view "
        "exclusion, uphold-as-new-decision, retraction/revocation/"
        "supersession with preserved history, derived-view predicate with "
        "stale-epoch fail-closed, idempotent concurrency, atomic "
        "transition+audit ledger, external-content quarantine."),
    "architecture_models": (
        "Three executable semantics over shared strict plumbing. "
        "Minimal gate: 5-state machine x threshold checklist with "
        "authority, binding, challenge, revocation and policy checks. "
        "Argumentation: grounded-style IN without independence counting, "
        "transitive parent support allowed (naive). TMS: justification "
        "holding with automatic tms_engine revision (naive)."),
    "mental_model": (
        "Five operator-visible states. PROMOTED means only passage of the "
        "versioned gate for the stated scope and policy, never objective "
        "truth. Challenge and revocation exclude claims from the eligible "
        "view immediately; history is append-only and hash-chained. "
        "Re-promotion is a new decision, never an edit."),
    "ontology": (
        "Record types assertion, evidence, provenance, scope, decision, "
        "audit_event with SUPERSEDES versioning. S1-003 mapping: "
        "proposed/under_review to PROPOSED, promoted to PROMOTED, "
        "challenged to CHALLENGED, retracted to RETRACTED, superseded to "
        "RETRACTED plus SUPERSEDES, rejected to REJECTED. No SHACL mapping "
        "yet for attack, support or justification relations."),
    "mathematical_model": (
        "Threshold, acceptability and justification rules as frozen. "
        "Metrics: PROMOTED-positive confusion, per-class precision/recall "
        "with Wilson intervals, transition exactness, view correctness, "
        "operator model as simulation. Scores from measured safety plus "
        "frozen utility estimates with UNKNOWN bounds; numeric scores "
        "are bound in results/comparison.json; 220 sensitivity "
        "compositions with zero flips and explicit UNKNOWN disclosure."),
    "synthesis_and_gaps": (
        "Minimal gate passes every gate and probe; naive argumentation "
        "fails A, D, G; naive TMS additionally fails authority. Shared "
        "plumbing passes B, C, E, F, H for all designs. Gaps: cyclic "
        "attack convergence unknown, real independence calibration is "
        "S1-012, operator comprehension unmeasured until S1-013, no SHACL "
        "mapping for richer relations."),
    "independent_audit": (
        "Producer path (runner) and audit path (evaluator plus comparison) "
        "are independent code reading only raw rows and frozen inputs. "
        "A/B series: 18 distinct processes, one commit and tree, exact "
        "matrices, identical rows, distinct process identities, both "
        "series independently evaluated with matching verdicts. Limits: "
        "tracked-Git evidence only, provisional threshold, simulation "
        "operator model, corpus-bounded claims."),
    "progress": (
        "Phase A complete: dependency gate, frozen sources, contracts, "
        "72-case oracle, stdlib tooling with green regressions, two "
        "process-separated runs, comparison, metrics, probes, "
        "sensitivity, environment record, decision, roadmap, native "
        "FLOW-11 bundle and derived candidate record. Open: independent "
        "re-review, then Phase B canonical round and closure."),
}

PLATFORM_PLAN = {
    "Scope": "Adopt the frozen minimal knowledge gate (contract v1.0.2) "
             "as the MVP knowledge-layer boundary for the first AgentOS "
             "knowledge layer; richer argumentation and TMS stay deferred "
             "until S1-012 and S1-013 harden them.",
    "Architecture": "Five-state machine with threshold checklist, strict "
                    "evidence bindings, challenge and revocation handling, "
                    "derived-view projection with epoch fail-closed, "
                    "idempotency keys, and an atomic hash-chained "
                    "transition plus audit ledger.",
    "Workstreams": "Implement the checklist gate, challenge SLA handling, "
                   "revocation propagation, derived-view projection, and "
                   "the ledger journal; replay preserved history under the "
                   "frozen contract for acceptance.",
    "Milestones": "MVP boundary accepted on Phase B canonicalization; "
                  "production unblocked only after S1-012 calibration and "
                  "S1-013 operator validation milestones are met.",
    "Verification": "Re-run the frozen 72-case matrix with the reference "
                    "runner and evaluator; require all hard counters zero, "
                    "transition consistency clean, probes A through H "
                    "passing, and sensitivity without flips.",
    "Risks": "Provisional threshold may admit novel correlated evidence; "
             "operator cost is estimated, not measured; cyclic attack "
             "graphs are outside the evaluated corpus.",
    "Open decisions": "Final threshold calibration in S1-012; operator "
                      "procedures and fatigue bounds in S1-013; whether a "
                      "governed variant of argumentation or TMS ever "
                      "replaces the minimal gate.",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(name: str):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def load_result(name: str):
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def build_sources() -> list:
    sources = []
    for sid, rel, title, stype, note in SOURCE_SPECS:
        raw = (HERE / rel).read_bytes()
        text = raw.decode("utf-8")
        assert text.encode("utf-8") == raw, f"non-roundtrip bytes: {rel}"
        digest = sha(raw)
        sources.append({
            "id": sid,
            "canonical_uri": f"https://local.agentos.invalid/{rel}",
            "title": title,
            "source_type": stype,
            "verification_status": "verified",
            "verifier": "s1-011-source-review-2026-09-03",
            "verification_method": "tracked-file-hash-review",
            "note": note,
            "snapshot_path": f"research/tickets/stage-1/S1-011/{rel}",
            "content": text,
            "content_sha256": digest,
        })
    return sources


def build_artifacts() -> dict:
    artifacts = {}
    for kind in FLOW:
        if kind == "platform_plan":
            artifacts[kind] = {"content": dict(PLATFORM_PLAN),
                               "producer": PRODUCER,
                               "claim_refs": ["CL-T1", "CL-I3"]}
            continue
        artifacts[kind] = {"content": ARTIFACT_TEXTS[kind],
                           "producer": PRODUCER,
                           "claim_refs": ["CL-T1", "CL-I3"]}
    artifacts["independent_audit"]["producer"] = AUDITOR
    artifacts["independent_audit"]["claim_refs"] = ["CL-I3", "CL-A1"]
    artifacts["research_plan"]["claim_refs"] = ["CL-T1"]
    artifacts["source_registry"]["claim_refs"] = ["CL-F1", "CL-F2"]
    artifacts["progress"]["claim_refs"] = ["CL-I3"]
    return artifacts


def derive_verdict() -> tuple:
    """Re-derive the verdict from evidence. Returns (blockers, facts).
    Missing evidence files are blockers, never defaults."""
    blockers = []
    try:
        gate = load("dependency-gate.json")
    except (OSError, ValueError) as exc:
        return [f"dependency gate unreadable: {exc}"], {}
    if not gate.get("all_proven"):
        blockers.append("dependency gate not proven")
    try:
        metrics = load_result("metrics.json")
        probes = load_result("probes.json")
        comparison = load_result("comparison.json")
        sens = load_result("sensitivity.json")
    except (OSError, ValueError) as exc:
        return blockers + [f"results unreadable: {exc}"], {}
    chosen = "minimal-gate"
    doc = metrics["designs"].get(chosen)
    if doc is None or doc.get("verdict") != "PASS":
        blockers.append(f"chosen design {chosen} not PASS")
    hard_names = {"false_promotion_count", "false_retention_count",
                  "resurrection_count", "missed_invalidation_count",
                  "history_loss_or_rewrite_count", "stale_replay_acceptance_count",
                  "cross_scope_visibility_count", "authority_expansion_count",
                  "duplicate_active_decision_count",
                  "transition_audit_atomicity_violation_count",
                  "derived_without_evidence_promotion_count"}
    counters = (doc or {}).get("hard_counters", {})
    if (doc or {}).get("admissible") is not True or \
            (doc or {}).get("hard_fail") is not False or \
            type((doc or {}).get("invalid_transition_count")) is not int or \
            (doc or {}).get("invalid_transition_count") != 0 or \
            not isinstance(counters, dict) or set(counters) != hard_names or \
            any(type(v) is not int or v != 0 for v in counters.values()):
        blockers.append("chosen metrics inadmissible or hard counters invalid")
    probe_doc = probes["designs"].get(chosen, {})
    if not probe_doc.get("all_pass"):
        blockers.append(f"probes not all-pass for {chosen}")
    if comparison.get("sensitivity_winner") != chosen:
        blockers.append("comparison winner is not the chosen design")
    if comparison.get("sensitivity_flips"):
        blockers.append("sensitivity flips present")
    if comparison.get("unknown_dependent"):
        blockers.append("winner is UNKNOWN-dependent")
    if sens.get("winner") != chosen or sens.get("flip_count"):
        blockers.append("sensitivity artifact disagrees")
    if sens.get("unknown_dependent"):
        blockers.append("sensitivity UNKNOWN-dependent")
    if not blockers:
        # Never publish solely from a cached PASS summary. Re-evaluate both
        # complete raw series, frozen bytes and provenance in a separate process.
        with tempfile.TemporaryDirectory(prefix="s1011-publish-") as td:
            paths = {name: Path(td) / name for name in
                     ("comparison.json", "metrics.json", "probes.json", "sensitivity.json")}
            proc = subprocess.run([
                sys.executable, str(HERE / "compare_runs.py"),
                "--a", str(RESULTS / "run-a"), "--b", str(RESULTS / "run-b"),
                "--out", str(paths["comparison.json"]),
                "--metrics", str(paths["metrics.json"]),
                "--probes", str(paths["probes.json"]),
                "--sensitivity", str(paths["sensitivity.json"])],
                capture_output=True, text=True, timeout=120)
            if proc.returncode:
                blockers.append("raw re-evaluation failed: " + proc.stderr[:300])
            else:
                for name, recorded in (("comparison.json", comparison),
                                       ("metrics.json", metrics), ("probes.json", probes),
                                       ("sensitivity.json", sens)):
                    if json.loads(paths[name].read_text(encoding="utf-8")) != recorded:
                        blockers.append(f"cached {name} differs from raw-derived output")
        spec = importlib.util.spec_from_file_location("s1011_publish_dependency", HERE / "dependency_gate.py")
        dependency = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dependency)
        if any(dependency.check(t)["status"] != "PROVEN" for t in dependency.DEPS):
            blockers.append("live tracked dependency recheck failed")
    facts = {"gate": gate.get("all_proven"),
             "minimal_verdict": (doc or {}).get("verdict"),
             "probes": probe_doc.get("all_pass"),
             "winner": comparison.get("sensitivity_winner"),
             "flips": comparison.get("sensitivity_flips"),
             "unknown_dependent": comparison.get("unknown_dependent")}
    return blockers, facts


def main() -> int:
    blockers, facts = derive_verdict()
    if blockers:
        for line in blockers:
            print(f"BLOCKED: {line}", file=sys.stderr)
        return 1
    # Cap rationale: provisional threshold (S1-012) + no human study
    # (S1-013) force PASS_WITH_LIMITS even with all gates green.
    limitations = [
        "tracked-Git evidence only; live DB recheck required in Phase B",
        "provisional independence threshold uncalibrated (S1-012)",
        "operator workload is a simulation estimate (S1-013)",
        "corpus-bounded claims: no cyclic attack graphs evaluated",
        "no SHACL mapping for attack/support/justification relations",
    ]
    bundle = {
        "config": {"min_source_count": 4, "min_verified_ratio": 1.0,
                   "required_artifacts": list(FLOW)},
        "sources": build_sources(),
        "claims": [dict(c) for c in CLAIMS],
        "artifacts": build_artifacts(),
        "producer": PRODUCER,
        "auditor": AUDITOR,
        "audit": {"producer": PRODUCER, "auditor": AUDITOR,
                  "verdict": "pass_with_limits",
                  "limitations": limitations},
    }
    bundle_text = json.dumps(bundle, indent=2, sort_keys=True,
                             ensure_ascii=False) + "\n"
    (HERE / "bundle.json").write_text(bundle_text, encoding="utf-8",
                                      newline="\n")
    bundle_sha = sha((HERE / "bundle.json").read_bytes())
    manifest = load("corpus-manifest.json")
    comparison = load_result("comparison.json")
    candidate = {
        "schema": "agentos.s1-011.candidate-record/v1",
        "ticket": "S1-011",
        "status": "READY_FOR_CANONICALIZATION",
        "verdict": "PASS_WITH_LIMITS",
        "verdict_basis": facts,
        "verdict_cap_reason": "provisional threshold (S1-012) and no "
                              "human operator study (S1-013)",
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
        json.dumps(candidate, indent=2, sort_keys=True,
                   ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    print(f"bundle.json sha256={bundle_sha}")
    print("candidate-record.json status=READY_FOR_CANONICALIZATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
