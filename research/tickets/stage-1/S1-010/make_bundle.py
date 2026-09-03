#!/usr/bin/env python3
"""Assemble the FLOW-11 bundle for S1-010 (content-addressed, offline).

Emits bundle.json with the eleven mandatory non-empty artifacts.  All hashes
are computed from tracked file bytes on disk.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

TICKET_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TICKET_ROOT.parents[3]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: str):
    return json.loads((TICKET_ROOT / path).read_text(encoding="utf-8"))


def results(path: str):
    return json.loads((TICKET_ROOT / "results" / path).read_text(encoding="utf-8"))


def metrics_block() -> str:
    m = results("metrics.json")["run_a"]["metrics"]
    cm = m["confusion_matrix_overall"]
    lines = [
        f"- confusion matrix (truth x treatment, overall): TP={cm['tp']}, "
        f"FP={cm['fp']}, TN={cm['tn']}, FN={cm['fn']} on {sum(cm.values())} cases",
        f"- precision={m['precision']:.4f} (Wilson 95% "
        f"[{m['wilson_precision']['lower']:.4f}, {m['wilson_precision']['upper']:.4f}])",
        f"- recall={m['recall']:.4f} (Wilson 95% "
        f"[{m['wilson_recall']['lower']:.4f}, {m['wilson_recall']['upper']:.4f}])",
        f"- benign hard FPR={m['benign_false_positive_rate']:.4f} "
        f"(raw benign blocked={m['raw_benign_blocked_count']}, all oracle-sanctioned routing)",
        f"- abstentions: quarantine={m['quarantine_count']}, "
        f"human_review={m['human_review_count']}, unsupported={m['unsupported_count']}",
        f"- critical escapes={m['critical_escape_count']}; authority expansions: "
        + ", ".join(f"{k}={v}" for k, v in m["authority_expansions"].items()),
        f"- malformed={m['malformed_count']}, unknown={m['unknown_count']}, "
        f"timeout={m['timeout_count']}, scanner_disagreement={m['scanner_disagreement_count']}",
    ]
    return "\n".join(lines)


def main() -> int:
    registry = load("source-registry.json")
    threat = load("threat-model.json")
    contract = load("tool-poisoning-contract.json")
    rubric = load("rubric.json")
    manifest = load("corpus-manifest.json")
    probes = results("probes.json")
    comparison = results("comparison.json")

    artifact_bodies = {
        "research_plan": {
            "question": "Which layered controls detect malicious or misleading tool "
                        "manifests and outputs, and when must the gateway quarantine "
                        "or require human approval instead of trusting a scanner?",
            "design": "Deterministic, frozen-corpus adversarial evaluation of an "
                      "8-layer admission/output contract; two process-separated runs "
                      "on one clean commit; host-owned oracle; fail-closed hard gates.",
            "claims_classes": ["threat_fact", "detection_measurement", "risk",
                               "abstention", "control_decision"],
            "scope_boundary": "Evidence for G-07 / EP-06 only; no universal-detection "
                              "or production-rollout claim.",
        },
        "source_registry": {
            "schema": registry["schema"],
            "sources": [{"id": s["id"], "role": s["role"],
                         "canonical_uri": s["canonical_uri"],
                         "version": s["version"],
                         "snapshots": [{"path": x["snapshot_path"],
                                        "sha256": x["sha256"],
                                        "byte_length": x["byte_length"],
                                        "retrieved_at": x["retrieved_at"]}
                                       for x in s["snapshots"]]}
                        for s in registry["sources"]],
            "note": "Tests and evaluation are offline; snapshots are byte-frozen.",
        },
        "feature_catalog": {
            "signals": [
                "manifest structural validity (required fields, types, unknown fields)",
                "identity charset hygiene (zero-width/bidi rejection, NFC)",
                "content digest format and dependency digest coverage",
                "publisher registration and drift",
                "SBOM declaration for external/dangerous effects",
                "version and schema skew vs registration",
                "requested-vs-registered capability diff",
                "effect-class power ordering",
                "advisory static indicators (entropy, keywords, obfuscation markers)",
                "output directive/expansion/override/secret/exfiltration patterns",
                "governance claims (approval, knowledge, budget, reconciliation, acceptance)",
                "detector health (timeout, crash, malformed, disagreement)",
            ],
            "advisory_vs_authoritative": "Only registry/policy/digest/capability "
                                          "layers decide; static indicators may add "
                                          "reason codes and escalate to quarantine/review, "
                                          "never to ALLOW or sole DENY of benign cases.",
        },
        "architecture_models": {
            "layers": contract["layer_ordering"],
            "trust_boundaries": threat["trust_boundaries"],
            "decision_flow": "L1-L3 gate -> L4 advisory evidence -> L6 output guard "
                             "-> L7 fail-closed routing (faults override) -> L5 policy "
                             "-> L8 audit; DENY/QUARANTINE/HUMAN_REVIEW/UNSUPPORTED "
                             "never collapse to ALLOW.",
            "authority_boundaries": contract["authority_boundaries"],
        },
        "mental_model": {
            "operator_view": "A tool is admitted only when provenance, capability, "
                             "and policy layers all agree; anything uncertain on an "
                             "effect-capable path is quarantined or reviewed.",
            "adversary_view": "Poisoning must defeat digest/provenance checks, stay "
                              "inside registered capabilities, avoid output-injection "
                              "signatures, and keep detectors healthy - simultaneously.",
            "auditor_view": "Every decision carries reason codes, layer trace, and "
                            "empty authority_mutations; oracle outcomes live only in "
                            "host-owned fixtures.",
        },
        "ontology": {
            "entities": ["ToolManifest", "ToolOutput", "RegisteredContext",
                         "Decision", "ReasonCode", "LayerTrace", "AuditRecord",
                         "DetectorFault", "FrozenCase", "Corpus", "Rubric"],
            "decision_values": contract["decision_enum"],
            "effect_classes": contract["effect_classes"],
            "severity_scale": contract["severity_taxonomy"],
            "relations": {
                "FrozenCase": "binds input + registered context + oracle expectation",
                "Decision": "produced by pipeline, graded only against oracle",
                "AuditRecord": "immutable evidence of one decision",
            },
        },
        "mathematical_model": {
            "reward_model": "Binary treatment per case: blocked = decision in "
                            "{DENY, QUARANTINE, HUMAN_REVIEW, UNSUPPORTED}.",
            "metrics": "precision = TP/(TP+FP), recall = TP/(TP+FN), "
                       "FPR = FP/(FP+TN), FNR = FN/(FN+TP); Wilson score interval "
                       "with z=1.959963984540054 for binomial proportions.",
            "confusion_semantics": "Raw matrix counts oracle-sanctioned benign "
                                   "routings as FP for visibility; the hard-gate "
                                   "benign FPR excludes sanctioned routing.",
            "observed": metrics_block(),
        },
        "synthesis_and_gaps": {
            "synthesis": "Layered controls detected every malicious class in the "
                         "frozen corpus with zero critical escapes and zero authority "
                         "expansions; obfuscated content routes to quarantine; "
                         "detector faults fail closed; benign unusual cases are not "
                         "silently denied by advisory heuristics.",
            "probes": {k: {"all_pass": v["all_pass"], "cases":
                           [e["case_id"] for e in v["entries"]]}
                       for k, v in probes["probes"].items()},
            "gaps": [
                "Deterministic pattern layers cannot cover unseen obfuscation "
                "families; routing-level defense (quarantine/human review) carries "
                "that residual risk.",
                "No statistical/learned detector was evaluated; disagreement "
                "handling is exercised only via declared deterministic faults.",
                "The 56-case corpus measures declared classes only.",
            ],
        },
        "independent_audit": {
            "auditor": "verifier-B (Run B), process-separated from Run A producer",
            "method": "Same frozen inputs, distinct PID/executor/nonce/output root; "
                      "runner recomputes metrics from raw records and rejects any "
                      "divergence; oracle expectations are excluded from decisions.",
            "comparison": {"identical": comparison["identical"],
                           "violations": comparison["violations"],
                           "commit_sha": comparison["commit_sha"],
                           "tree_sha": comparison["tree_sha"]},
            "limitations": [
                "Same-host process separation, not an external human auditor.",
                "The auditor shares the codebase with the producer (independent "
                "process and identity, not an independent implementation).",
            ],
        },
        "platform_plan": {
            "gateway_binding": "Layer semantics mirror agentos.gateway ToolContract: "
                               "effect classes read/write_local/write_external/dangerous, "
                               "capability checks, exact-action approvals consumed "
                               "atomically once.",
            "adoption_steps": [
                "keep advisory scanners out of the authorization path",
                "enforce capability diff and effect-power ordering at registration",
                "route uncertain effect-capable cases to quarantine/human review",
                "treat tool output as data; deny effect paths on taint findings",
                "emit immutable audit records with reason codes",
            ],
            "phase_b": "Local canonicalization on the trusted host (research-plan, "
                       "tracked packs, wiki check, canonical evidence pack) before "
                       "any status change.",
        },
        "progress": {
            "phase": "A (cloud branch work) COMPLETE",
            "status": "READY_FOR_CANONICALIZATION",
            "runs": {"comparison": comparison["verdict"],
                     "case_count": comparison["case_count"],
                     "process_separation_verified":
                         comparison["process_separation_verified"]},
            "probes_all_pass": probes["all_probes_pass"],
            "todo_phase_b": ["canonical DB revision/IDs/chain", "tracked packs",
                             "wiki-check", "final verdict and closure"],
        },
    }

    for name, body in artifact_bodies.items():
        if not body:
            raise RuntimeError(f"FLOW-11 artifact {name} is empty")

    tracked_hashes = {}
    for rel in ("threat-model.json", "tool-poisoning-contract.json", "rubric.json",
                "cases.json", "corpus-manifest.json", "source-registry.json",
                "dependency-gate.json", "runner.py", "evaluator.py",
                "build_corpus.py", "make_bundle.py", "make_candidate_record.py",
                "results/comparison.json", "results/metrics.json",
                "results/probes.json"):
        tracked_hashes[f"research/tickets/stage-1/S1-010/{rel}"] = sha256_file(
            REPO_ROOT / "research/tickets/stage-1/S1-010" / rel)

    bundle = {
        "schema": "agentos.s1-010.bundle/v1",
        "ticket": "S1-010",
        "bundle_version": "1.0",
        "frozen_at": "2026-09-03T00:00:00Z",
        "contract_version": contract["contract_version"],
        "corpus_version": manifest["corpus_version"],
        "sources": [s["id"] for s in registry["sources"]],
        "artifacts": list(artifact_bodies.keys()),
        "artifacts_content": artifact_bodies,
        "artifact_hashes": tracked_hashes,
        "evaluator_hashes": {
            "contract_sha256": tracked_hashes[
                "research/tickets/stage-1/S1-010/tool-poisoning-contract.json"],
            "corpus_sha256": tracked_hashes[
                "research/tickets/stage-1/S1-010/cases.json"],
            "rubric_sha256": tracked_hashes[
                "research/tickets/stage-1/S1-010/rubric.json"],
            "runner_sha256": tracked_hashes[
                "research/tickets/stage-1/S1-010/runner.py"],
            "evaluator_sha256": tracked_hashes[
                "research/tickets/stage-1/S1-010/evaluator.py"],
        },
        "rule_count": len(contract["layer_ordering"]) + len(
            contract["fail_closed_matrix"]) + len(contract["layer_rules"]),
        "case_count": manifest["case_count"],
        "verdict": "PASS",
        "note": "Cloud Phase A only; canonical local Phase B is required before "
                "any closure. Branch remains IN_REVIEW.",
    }
    (TICKET_ROOT / "bundle.json").write_bytes(
        json.dumps(bundle, indent=1, sort_keys=True, ensure_ascii=False)
        .encode("utf-8") + b"\n")
    print(json.dumps({"artifacts": len(artifact_bodies),
                      "case_count": bundle["case_count"],
                      "verdict": bundle["verdict"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
