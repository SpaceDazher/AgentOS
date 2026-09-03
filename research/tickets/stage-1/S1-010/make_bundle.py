#!/usr/bin/env python3
"""Assemble the FLOW-11 bundle for S1-010 (native schema, offline).

Round 2 (post independent review REVISE):

- emits the NATIVE FLOW-11 schema consumed by src/agentos/research.py:
  sources are objects with canonical_uri/title/source_type/verification and
  verifier_provenance, claims are objects with text/class/source_ids, the
  eleven FLOW artifacts are mappings with non-empty ``content``, explicit
  ``producer`` bindings and ``claim_refs``, and a top-level ``audit`` block
  carries subject_producer/auditor/verdict/limitations;
- the generated bundle is validated with the REAL normalizer
  (``agentos.research._normalise_config`` + ``_normalize_bundle`` +
  ``_evaluation_checks``) BEFORE it is written; any error aborts without
  writing (fail-closed);
- the bundle verdict is derived from the recorded evidence (run verdicts,
  comparison, probes, dependency gate).  Generators refuse to publish a
  bundle when any mandatory gate did not pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

DEFAULT_TICKET = Path(__file__).resolve().parent
DEFAULT_REPO = DEFAULT_TICKET.parents[3]

FLOW_KINDS = ("research_plan", "source_registry", "feature_catalog",
              "architecture_models", "mental_model", "ontology",
              "mathematical_model", "synthesis_and_gaps", "independent_audit",
              "platform_plan", "progress")

SUBJECT_PRODUCER = "verifier-A"
AUDITOR = "verifier-B"

SOURCE_TITLES = {
    "src_mitre_atlas_taxonomy":
        "MITRE ATLAS adversarial-ML threat taxonomy (ATLAS.yaml, pinned commit)",
    "src_cwe_74_injection":
        "CWE-74: Improper Neutralization of Special Elements in Output Used by Others",
    "src_slsa_v1_1":
        "SLSA v1.1 — Supply-chain Levels for Software Artifacts specification",
    "src_nist_ssdf_sp800_218":
        "NIST SP 800-218 Secure Software Development Framework (SSDF v1.1)",
    "src_agentos_gateway_spec":
        "AgentOS gateway architecture (src/agentos/gateway.py at the pinned commit)",
    "src_wilson_ci_nist_handbook":
        "NIST/SEMATECH e-Handbook of Statistical Methods §2.4.1 (Wilson intervals)",
}

# The gateway source's registry URI uses a repo:// scheme; the bundle needs
# the canonical HTTP location of the exact pinned commit.
SOURCE_URI_OVERRIDES = {
    "src_agentos_gateway_spec":
        "https://github.com/SpaceDazher/AgentOS/blob/"
        "a0116167e0351beb1eef804d83845890be7253c9/src/agentos/gateway.py",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load(ticket: Path, path: str):
    return json.loads((ticket / path).read_text(encoding="utf-8"))


def results(ticket: Path, path: str):
    return json.loads((ticket / "results" / path).read_text(encoding="utf-8"))


def evidence_gates(ticket: Path) -> dict:
    """Read every mandatory verdict from the recorded evidence.  Returns the
    basis dict; raises RuntimeError when any mandatory gate did not pass."""
    comparison = results(ticket, "comparison.json")
    probes = results(ticket, "probes.json")
    metrics = results(ticket, "metrics.json")
    gate = load(ticket, "dependency-gate.json")
    basis = {
        "comparison_verdict": comparison.get("verdict"),
        "comparison_identical": comparison.get("identical"),
        "process_separation_verified":
            comparison.get("process_separation_verified"),
        "run_a_verdict": comparison.get("run_a_verdict"),
        "run_b_verdict": comparison.get("run_b_verdict"),
        "gates_verdict": (metrics.get("run_a", {}).get("gates", {})
                          .get("verdict")),
        "all_probes_pass": probes.get("all_probes_pass"),
        "dependency_gate_verdict": gate.get("verdict"),
    }
    failed = [k for k, v in basis.items() if v != "PASS" and v is not True]
    if failed:
        raise RuntimeError(
            "evidence gates did not pass; refusing to publish a bundle: "
            + ", ".join(f"{k}={basis[k]!r}" for k in failed))
    return basis


def metrics_block(ticket: Path) -> str:
    m = results(ticket, "metrics.json")["run_a"]["metrics"]
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


def build_sources(ticket: Path, registry: dict) -> list[dict]:
    sources = []
    for s in registry["sources"]:
        snap = s["snapshots"][0]
        uri = SOURCE_URI_OVERRIDES.get(s["id"], s["canonical_uri"])
        sources.append({
            "id": s["id"],
            "canonical_uri": uri,
            "title": SOURCE_TITLES[s["id"]],
            "source_type": s["role"],
            "version": s["version"],
            "sha256": snap["sha256"],
            "verification_status": "verified",
            "verifier": "fetch_sources.py (S1-010 cloud Phase A, byte-frozen)",
            "verification_method":
                "byte-exact frozen snapshot verified by SHA-256 against "
                "source-registry.json; snapshots are tracked files in the "
                "same Git commit as this bundle",
            "verifier_provenance": {
                "method":
                    "byte-exact frozen snapshot verified by SHA-256 against "
                    "source-registry.json",
                "path": snap["snapshot_path"],
                "file_sha256": snap["sha256"],
                "retrieved_at": snap["retrieved_at"],
            },
        })
    return sources


def build_claims() -> list[dict]:
    return [
        {"id": "clm-atlas-tool-poisoning", "claim_class": "fact",
         "text": "MITRE ATLAS catalogues adversarial-ML techniques that "
                 "motivate tool-poisoning defenses, including LLM prompt "
                 "injection (AML.T0051) and poisoned training data "
                 "(AML.T0020).",
         "source_ids": ["src_mitre_atlas_taxonomy"]},
        {"id": "clm-cwe-74-output-injection", "claim_class": "fact",
         "text": "CWE-74 defines the injection weakness class where "
                 "improperly neutralized special elements in output used by "
                 "others change control flow; tool-output content is data, "
                 "never commands.",
         "source_ids": ["src_cwe_74_injection"]},
        {"id": "clm-slsa-provenance", "claim_class": "fact",
         "text": "SLSA v1.1 defines provenance and verification levels for "
                 "build artifacts; supply-chain changes must be detected by "
                 "provenance and digest comparisons, not by trust.",
         "source_ids": ["src_slsa_v1_1"]},
        {"id": "clm-nist-ssdf", "claim_class": "fact",
         "text": "NIST SP 800-218 (SSDF) requires verification of component "
                 "integrity and provenance of build inputs (PO tasks) for "
                 "software supply chains.",
         "source_ids": ["src_nist_ssdf_sp800_218"]},
        {"id": "clm-gateway-authority-boundary", "claim_class": "fact",
         "text": "The AgentOS gateway treats registered context as the only "
                 "authoritative capability/policy source; approvals live in "
                 "registered_context.pre_approved, and external content can "
                 "never create, consume, or extend authority.",
         "source_ids": ["src_agentos_gateway_spec"]},
        {"id": "clm-wilson-method", "claim_class": "fact",
         "text": "Wilson score intervals are the standard method for "
                 "binomial proportion confidence intervals on small "
                 "detection corpora.",
         "source_ids": ["src_wilson_ci_nist_handbook"]},
        {"id": "clm-detection-measurement", "claim_class": "inference",
         "text": "On the frozen 56-case corpus the layered controls blocked "
                 "every malicious case (recall 1.0, Wilson 95% lower bound "
                 "recorded in metrics), with zero critical escapes and zero "
                 "authority expansions across two process-separated runs.",
         "source_ids": []},
        {"id": "clm-fail-closed-routing", "claim_class": "inference",
         "text": "Detector faults, scanner disagreement, malformed inputs, "
                 "unknown effects, and revocation all route to "
                 "DENY/QUARANTINE/HUMAN_REVIEW/UNSUPPORTED and never collapse "
                 "to ALLOW; quarantine/human-review routing carries the "
                 "residual risk of unseen obfuscation families.",
         "source_ids": []},
        {"id": "clm-residual-risk", "claim_class": "assumption",
         "text": "Deterministic pattern layers cannot cover unseen "
                 "obfuscation families; the evaluated defense is "
                 "routing-level (quarantine/human review), not "
                 "universal detection.",
         "source_ids": []},
        {"id": "clm-approval-model-limitation", "claim_class": "assumption",
         "text": "In the evaluated model pre_approved is a boolean "
                 "entitlement; exact-action+operation+expiry approval "
                 "binding is declared by the contract but not enforced by "
                 "the deterministic evaluator and must be enforced by the "
                 "production gateway.",
         "source_ids": []},
        {"id": "clm-phase-b-target", "claim_class": "target",
         "text": "Local canonical Phase B (canonical DB revision/IDs/chain, "
                 "tracked packs, wiki check) remains mandatory before any "
                 "closure; this bundle is cloud Phase A evidence only and "
                 "the ticket stays READY_FOR_CANONICALIZATION.",
         "source_ids": []},
    ]


def build_artifacts(ticket: Path, registry: dict, threat: dict, contract: dict,
                    manifest: dict, comparison: dict, probes: dict) -> dict:
    def artifact(content, claim_refs, producer=SUBJECT_PRODUCER):
        return {"content": content, "claim_refs": claim_refs,
                "producer": producer}

    return {
        "research_plan": artifact({
            "question":
                "Which layered controls detect malicious or misleading tool "
                "manifests and outputs, and when must the gateway quarantine "
                "or require human approval instead of trusting a scanner?",
            "design":
                "Deterministic, frozen-corpus adversarial evaluation of an "
                "8-layer admission/output contract; two process-separated "
                "runner processes with distinct evaluator processes, "
                "executors, nonces, and output roots on one clean commit; "
                "host-owned oracle; fail-closed hard gates.",
            "claims_classes": ["threat_fact", "detection_measurement", "risk",
                               "abstention", "control_decision"],
            "scope_boundary":
                "Evidence for G-07 / EP-06 only; no universal-detection or "
                "production-rollout claim.",
        }, ["clm-phase-b-target"]),
        "source_registry": artifact({
            "schema": registry["schema"],
            "sources": [{
                "id": s["id"],
                "role": s["role"],
                "canonical_uri": s["canonical_uri"],
                "version": s["version"],
                "snapshots": [{"path": x["snapshot_path"],
                               "sha256": x["sha256"],
                               "byte_length": x["byte_length"],
                               "retrieved_at": x["retrieved_at"]}
                              for x in s["snapshots"]],
            } for s in registry["sources"]],
            "note": "Tests and evaluation are offline; snapshots are "
                    "byte-frozen and hash-bound in the same commit.",
        }, ["clm-atlas-tool-poisoning", "clm-cwe-74-output-injection"]),
        "feature_catalog": artifact({
            "signals": [
                "manifest structural validity (required fields, types, unknown fields)",
                "registered-context completeness (required authority fields, "
                "strict boolean entitlements)",
                "tool_output schema (object with required string text)",
                "identity charset hygiene (zero-width/bidi rejection, NFC)",
                "content digest format and dependency digest coverage",
                "publisher registration and drift",
                "SBOM declaration for external/dangerous effects",
                "version and schema skew vs registration",
                "requested-vs-registered capability diff",
                "effect-class power ordering (including registered-effect "
                "routing for output-only invocations)",
                "revocation state (registered_context.revoked routes to "
                "QUARANTINE before any permissive branch)",
                "advisory static indicators (entropy, keywords, obfuscation "
                "markers) with a closed detector-status set",
                "output directive/expansion/override/secret/exfiltration patterns",
                "governance claims (approval, knowledge, budget, "
                "reconciliation, acceptance)",
                "detector health (timeout, crash, malformed, disagreement, "
                "unknown status)",
            ],
            "advisory_vs_authoritative":
                "Only registry/policy/digest/capability layers decide; static "
                "indicators may add reason codes and escalate to "
                "quarantine/review, never to ALLOW or sole DENY of benign "
                "cases.",
        }, ["clm-detection-measurement"]),
        "architecture_models": artifact({
            "layers": contract["layer_ordering"],
            "trust_boundaries": threat["trust_boundaries"],
            "decision_flow":
                "context validation + revocation check -> L1-L3 gate -> L4 "
                "advisory evidence (closed status set) -> L6 output guard -> "
                "L7 fail-closed routing (faults override) -> L5 policy -> L8 "
                "audit; DENY/QUARANTINE/HUMAN_REVIEW/UNSUPPORTED never "
                "collapse to ALLOW.",
            "authority_boundaries": contract["authority_boundaries"],
        }, ["clm-gateway-authority-boundary"]),
        "mental_model": artifact({
            "operator_view":
                "A tool is admitted only when provenance, capability, and "
                "policy layers all agree, the context is complete and "
                "unrevoked, and the output path is clean; anything uncertain "
                "on an effect-capable path is quarantined or reviewed.",
            "adversary_view":
                "Poisoning must defeat digest/provenance checks, stay inside "
                "registered capabilities, avoid output-injection signatures, "
                "and keep detectors healthy - simultaneously.",
            "auditor_view":
                "Every decision carries reason codes, layer trace, and empty "
                "authority_mutations; oracle outcomes live only in "
                "host-owned fixtures.",
        }, ["clm-fail-closed-routing"]),
        "ontology": artifact({
            "entities": ["ToolManifest", "ToolOutput", "RegisteredContext",
                         "Decision", "ReasonCode", "LayerTrace", "AuditRecord",
                         "DetectorFault", "FrozenCase", "Corpus", "Rubric"],
            "decision_values": contract["decision_enum"],
            "effect_classes": contract["effect_classes"],
            "severity_scale": contract["severity_taxonomy"],
            "relations": {
                "FrozenCase":
                    "binds input + registered context + oracle expectation",
                "Decision":
                    "produced by pipeline, graded only against oracle",
                "AuditRecord": "immutable evidence of one decision",
            },
        }, ["clm-cwe-74-output-injection"]),
        "mathematical_model": artifact({
            "reward_model":
                "Binary treatment per case: blocked = decision in {DENY, "
                "QUARANTINE, HUMAN_REVIEW, UNSUPPORTED}.",
            "metrics":
                "precision = TP/(TP+FP), recall = TP/(TP+FN), FPR = "
                "FP/(FP+TN), FNR = FN/(FN+TP); Wilson score interval with "
                "z=1.959963984540054 for binomial proportions.",
            "confusion_semantics":
                "Raw matrix counts oracle-sanctioned benign routings as FP "
                "for visibility (raw FPR is reported separately); the "
                "hard-gate benign FPR excludes sanctioned routing.",
            "observed": metrics_block(ticket),
        }, ["clm-wilson-method"]),
        "synthesis_and_gaps": artifact({
            "synthesis":
                "Layered controls detected every malicious class in the "
                "frozen corpus with zero critical escapes and zero authority "
                "expansions; obfuscated content routes to quarantine; "
                "detector faults, unknown statuses, revoked tools, and "
                "malformed inputs/contexts fail closed; benign unusual cases "
                "are not silently denied by advisory heuristics.",
            "probes": {k: {"all_pass": v["all_pass"], "cases":
                           [e["case_id"] for e in v["entries"]]}
                       for k, v in probes["probes"].items()},
            "gaps": [
                "Deterministic pattern layers cannot cover unseen obfuscation "
                "families; routing-level defense (quarantine/human review) "
                "carries that residual risk.",
                "No statistical/learned detector was evaluated; disagreement "
                "handling is exercised only via declared deterministic faults.",
                "The 56-case corpus measures declared classes only.",
                "pre_approved is a boolean entitlement in the evaluated "
                "model; exact-action+operation+expiry approval binding is "
                "declared by the contract but must be enforced by the "
                "production gateway.",
            ],
        }, ["clm-residual-risk", "clm-approval-model-limitation"]),
        "independent_audit": artifact({
            "auditor": AUDITOR,
            "method":
                "Same frozen inputs; runs execute as two independent runner "
                "child processes with distinct evaluator grandchildren, "
                "executors, nonces, and output roots; the orchestrator "
                "validates full binding schemas, re-verifies staged digests, "
                "recomputes metrics from raw records, and rejects any "
                "divergence; oracle expectations are excluded from decisions.",
            "comparison": {"identical": comparison["identical"],
                           "violations": comparison["violations"],
                           "commit_sha": comparison["commit_sha"],
                           "tree_sha": comparison["tree_sha"]},
            "limitations": [
                "Same-host process separation, not an external human auditor.",
                "The auditor shares the codebase with the producer "
                "(independent process and identity, not an independent "
                "implementation).",
            ],
        }, ["clm-detection-measurement"], producer=AUDITOR),
        "platform_plan": artifact({
            "Scope":
                "Adopt the evaluated eight-layer tool-poisoning controls in "
                "the AgentOS gateway admission and output-handling path for "
                "registered tools.",
            "Architecture":
                "Mirror agentos.gateway ToolContract semantics: effect "
                "classes read/write_local/write_external/dangerous, "
                "capability diffs at registration, registered context as "
                "the only authority, advisory scanners outside the "
                "authorization path.",
            "Workstreams":
                "1) registration-time provenance and capability diffing; "
                "2) admission policy matrix and revocation handling; "
                "3) output-guard patterns and governance-claim inertness; "
                "4) detector health routing; 5) immutable audit records.",
            "Milestones":
                "M1 contract versioning wired to gateway config; M2 "
                "capability diff and effect-power enforcement at "
                "registration; M3 quarantine/human-review routing for "
                "uncertain effect-capable paths; M4 audit record emission "
                "with reason codes.",
            "Verification":
                "Frozen-corpus regression suite (TDD), process-separated "
                "A/B evidence runs with full binding schemas, dependency "
                "gate, git-archive reproducibility, and local canonical "
                "Phase B before closure.",
            "Risks":
                "Unseen obfuscation families rely on routing-level defense; "
                "scanner automation must never regain authorization power; "
                "approval binding (action/operation/expiry) must be enforced "
                "by the production gateway, not the deterministic model.",
            "Open decisions":
                "Whether to promote the evaluated deterministic patterns to "
                "the production detector stack or keep them as admission "
                "regression tests; which additional corpus classes justify a "
                "contract version bump.",
            "gateway_binding":
                "Layer semantics mirror agentos.gateway ToolContract: effect "
                "classes read/write_local/write_external/dangerous, "
                "capability checks, exact-action approvals consumed "
                "atomically once.",
            "adoption_steps": [
                "keep advisory scanners out of the authorization path",
                "enforce capability diff and effect-power ordering at registration",
                "route uncertain effect-capable cases to quarantine/human review",
                "treat tool output as data; deny effect paths on taint findings",
                "emit immutable audit records with reason codes",
            ],
            "phase_b":
                "Local canonicalization on the trusted host (research-plan, "
                "tracked packs, wiki check, canonical evidence pack) before "
                "any status change.",
        }, ["clm-phase-b-target", "clm-slsa-provenance"]),
        "progress": artifact({
            "phase": "A (cloud branch work) COMPLETE; post-review round 2 fixes applied",
            "status": "READY_FOR_CANONICALIZATION",
            "runs": {"comparison": comparison["verdict"],
                     "case_count": comparison["case_count"],
                     "process_separation_verified":
                         comparison["process_separation_verified"]},
            "probes_all_pass": probes["all_probes_pass"],
            "todo_phase_b": ["canonical DB revision/IDs/chain", "tracked packs",
                             "wiki-check", "final verdict and closure"],
        }, ["clm-phase-b-target"]),
    }


def flow11_selfcheck(bundle: dict, repo_root: Path) -> None:
    """Validate the generated bundle with the REAL platform normalizer
    before writing.  Any normalization error or evaluation failure aborts
    the generation (fail-closed)."""
    sys.path.insert(0, str(repo_root / "src"))
    try:
        from agentos import research as flow11
    finally:
        pass
    config, cfg_errors = flow11._normalise_config(None, bundle)
    if cfg_errors:
        raise RuntimeError("FLOW-11 config errors: " + "; ".join(cfg_errors))
    normalized, errors = flow11._normalize_bundle(bundle, config,
                                                  workspace_root=repo_root)
    if errors:
        raise RuntimeError("FLOW-11 normalization errors: "
                           + "; ".join(errors))
    failures, next_actions = flow11._evaluation_checks(normalized, config)
    if failures:
        raise RuntimeError("FLOW-11 evaluation failures: "
                           + "; ".join(failures)
                           + (" | next: " + "; ".join(next_actions)
                              if next_actions else ""))
    kinds = sorted(normalized["artifacts"].keys())
    missing = [k for k in FLOW_KINDS if k not in kinds]
    if missing:
        raise RuntimeError(f"FLOW-11 artifacts missing after normalization: "
                           f"{missing}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket-root", default=str(DEFAULT_TICKET))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    args = parser.parse_args()
    ticket = Path(args.ticket_root).resolve()
    repo_root = Path(args.repo_root).resolve()

    basis = evidence_gates(ticket)

    registry = load(ticket, "source-registry.json")
    threat = load(ticket, "threat-model.json")
    contract = load(ticket, "tool-poisoning-contract.json")
    manifest = load(ticket, "corpus-manifest.json")
    probes = results(ticket, "probes.json")
    comparison = results(ticket, "comparison.json")

    artifacts = build_artifacts(ticket, registry, threat, contract,
                                manifest, comparison, probes)
    bodies_empty = [k for k, v in artifacts.items() if not v["content"]]
    if bodies_empty:
        raise RuntimeError(f"FLOW-11 artifact {bodies_empty} is empty")
    missing_kinds = [k for k in FLOW_KINDS if k not in artifacts]
    if missing_kinds:
        raise RuntimeError(f"FLOW-11 mandatory artifacts missing: {missing_kinds}")

    tracked_hashes = {}
    for rel in ("threat-model.json", "tool-poisoning-contract.json",
                "rubric.json", "cases.json", "corpus-manifest.json",
                "source-registry.json", "dependency-gate.json", "runner.py",
                "evaluator.py", "build_corpus.py", "make_bundle.py",
                "make_candidate_record.py", "results/comparison.json",
                "results/metrics.json", "results/probes.json"):
        tracked_hashes[f"research/tickets/stage-1/S1-010/{rel}"] = sha256_file(
            ticket / rel)

    audit_limitations = [
        "Same-host process separation (verifier-A/verifier-B runner "
        "processes with distinct evaluator children), not an external "
        "human auditor or independently implemented auditor.",
        "Cloud Phase A proves tracked Git evidence only; canonical DB "
        "state is rechecked in local Phase B.",
        "pre_approved is a boolean entitlement in the evaluated model; "
        "exact-action+operation+expiry approval binding must be enforced "
        "by the production gateway.",
    ]
    bundle = {
        "schema": "agentos.s1-010.bundle/v1",
        "ticket": "S1-010",
        "bundle_version": "2.0",
        "frozen_at": "2026-09-03T00:00:00Z",
        "contract_version": contract["contract_version"],
        "corpus_version": manifest["corpus_version"],
        "producer": SUBJECT_PRODUCER,
        "sources": build_sources(ticket, registry),
        "claims": build_claims(),
        "artifacts": artifacts,
        "audit": {
            "subject_producer": SUBJECT_PRODUCER,
            "auditor": AUDITOR,
            "verdict": "pass_with_limits",
            "limitations": audit_limitations,
        },
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
        "verdict_basis": basis,
        "note": "Cloud Phase A only; canonical local Phase B is required "
                "before any closure. Branch remains IN_REVIEW.",
    }

    # Fail-closed: the real platform normalizer must accept this bundle
    # before it is written; Phase B must never receive an unnormalizable
    # bundle again.
    flow11_selfcheck(bundle, repo_root)

    (ticket / "bundle.json").write_bytes(
        json.dumps(bundle, indent=1, sort_keys=True, ensure_ascii=False)
        .encode("utf-8") + b"\n")
    print(json.dumps({"artifacts": len(artifacts),
                      "sources": len(bundle["sources"]),
                      "claims": len(bundle["claims"]),
                      "case_count": bundle["case_count"],
                      "verdict": bundle["verdict"],
                      "flow11_selfcheck": "pass"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"make_bundle failed: {exc}", file=sys.stderr)
        sys.exit(1)
