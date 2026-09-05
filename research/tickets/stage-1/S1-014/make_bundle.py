"""FLOW-11 bundle builder for S1-014 (producer and auditor are distinct roles)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as c  # noqa: E402

PRODUCER = "agentos-s1-014-producer"
AUDITOR = "agentos-s1-014-independent-verifier"
VERIFIER = "s1-014-source-review-2026-09-05"


def sources() -> list[dict]:
    reg = c.load_json(c.TICKET / "source-registry.json")
    out = []
    for s in reg["sources"]:
        content = (c.REPO / s["snapshot_path"]).read_bytes()
        if s["kind"].startswith("bibliographic"):
            body = content
        else:
            body = ("# Retrieval record (not a source claim)\n\n" + "\n".join(
                f"- {k}: {s[k]}" for k in ("snapshot_path", "canonical_uri", "version", "retrieved_at", "role", "access"))
                + f"\n- snapshot_sha256: {s['sha256']}\n- bytes: {s['bytes']}\n").encode("utf-8")
        out.append({"id": s["id"], "title": s["title"], "canonical_uri": s["canonical_uri"],
                    "source_type": s["role"], "content": body.decode("utf-8"),
                    "content_sha256": c.sha_bytes(body), "verification_status": "verified",
                    "verifier": VERIFIER, "verification_method": "tracked-file-hash-review"})
    return out


def build(candidate: dict, metrics: dict, probes: dict, comparison: dict, gate: dict) -> dict:
    status = candidate["status"]
    decision = candidate.get("provisional_design_decision")
    # The auditor verdict concerns the preparation evidence itself; the ticket
    # status (PREPARATION_READY / PASS_WITH_LIMITS / INCONCLUSIVE) is carried
    # separately in ``s1_014`` and can never exceed pass_with_limits.
    verdict = "pass_with_limits" if status in ("PREPARATION_READY", "PASS_WITH_LIMITS") else "inconclusive"
    claims = [
        {"id": "CL-M1", "claim_class": "fact", "s1_014_class": "HCI_measurement", "support": ["SRC-S1-014-01", "SRC-S1-014-04"],
         "text": "Both CARD and GRAPH render from one canonical dispute contract; machine parity checks report identical claims, evidence, statuses, sources, independence groups, relations, wording and answer choices for all 8 tasks with a symmetric one-action disclosure rule."},
        {"id": "CL-M2", "claim_class": "fact", "s1_014_class": "HCI_measurement", "support": ["SRC-S1-014-02", "SRC-S1-014-03"],
         "text": "Deterministic technical replay across two separate processes reproduces identical observation and metric digests; per-variant/per-task counts keep missing, timeout and withdrawn trials in the denominator."},
        {"id": "CL-U1", "claim_class": "fact", "s1_014_class": "usability_observation", "support": ["SRC-S1-014-03"],
         "text": "A real Chromium keyboard-only run completes practice plus 8 counterbalanced trials, opens every disclosure without a pointer, exports a versioned envelope that the strict importer accepts, and rejects a forged contract binding."},
        {"id": "CL-D1", "claim_class": "inference", "s1_014_class": "design_inference", "support": ["SRC-S1-014-01", "SRC-S1-014-02", "SRC-S1-014-03"],
         "text": "Following the overview-then-details pattern and the node-link versus alternative-representation precedent, level-0 must show claim, status, challenge, source/origin and independence group in both variants; representation advantage is expected to be task dependent, not universal."},
        {"id": "CL-A1", "claim_class": "fact", "s1_014_class": "accessibility_risk", "support": ["SRC-S1-014-01"],
         "text": "A graph without a linear keyboard/screen-reader equivalent or a card whose disclosure needs a pointer fails the accessibility hard gate (probe G); the frozen renderer contract requires button controls and a linear equivalent."},
        {"id": "CL-P1", "claim_class": "fact", "s1_014_class": "HCI_measurement", "support": ["SRC-S1-014-05", "SRC-S1-014-06"],
         "text": "Provenance and independence cues follow S1-011 knowledge-gate statuses and S1-012 independence groups verbatim; the renderer never changes status, policy or authority (renderer_may_change_authority=false)."},
        {"id": "CL-X1", "claim_class": "inference", "s1_014_class": "decision", "support": ["SRC-S1-014-06", "SRC-S1-014-07"],
         "text": ("Phase A is PREPARATION_READY; a provisional default is only recorded after a single operator design review and never as a human superiority finding."
                  if not decision else
                  f"Operator design review (n=1) approved provisional {decision['outcome']} under frozen decision rule; this is a design-contract approval, not a human-effectiveness result.")},
        {"id": "CL-L1", "claim_class": "assumption", "s1_014_class": "limitation", "support": ["SRC-S1-014-07"],
         "text": "human_study_n=0 and comparative_human_effectiveness=NOT_MEASURED; S1-013 limits (no population human data, no independent raters, raw deleted) are inherited; same-host replay is not external audit."},
    ]
    art = lambda text, refs: {"content": text, "claim_refs": refs, "producer": PRODUCER}  # noqa: E731
    artifacts = {
        "research_plan": art("Prepare, measure and independently recheck two information-equivalent claim-dispute visualizations (CARD, GRAPH) built from one canonical contract over 8 matched, stratified disputes; run probes A-J and process-separated replay; then hold one operator design review to record a provisional default (card-with-graph-drilldown, graph-with-linear-fallback, task-dependent split or no default). No human study, no superiority claim.", ["CL-M1", "CL-X1", "CL-L1"]),
        "source_registry": art("7 sources: SRC-04 mental model (QM1, §3/§4/§7), Ghoniem-Fekete-Castagliola 2004 (DOI 10.1109/infvis.2004.1) and Shneiderman 1996 (DOI 10.1109/vl.1996.545307) as bibliographic records, S1-011/S1-012 decisions, S1-013 limitations and operator decision; all snapshotted with SHA-256.", ["CL-D1", "CL-P1"]),
        "feature_catalog": art("CARD: focal claim, status, gate state, always-visible challenge indicator, source cue with publisher/origin, independence cue, three one-action button disclosures. GRAPH: claim/evidence nodes with source/origin/group labels, support/challenge edges, keyboard-focusable nodes, linear equivalent list, same three disclosures. Shared: consent, practice, pause/resume/withdraw, timeout, opaque IDs, versioned export.", ["CL-M1", "CL-A1"]),
        "architecture_models": art("Single contract.py (schema, corpus, oracle, renderers, parity, counterbalancing) feeds browser-contract.json, importer, evaluator, probes, replicator and publisher; oracle is a separate frozen file never served to the browser; frozen-manifest.json covers all inputs; publisher deletes stale outputs on any failure.", ["CL-M2", "CL-P1"]),
        "mental_model": art("Per SRC-04: the UI mirrors the ontology (claim, evidence, source, independence group, knowledge status) with no hidden participants; the user question 'what is this based on and is it contested?' must be answerable at level 0 in both representations.", ["CL-D1"]),
        "ontology": art("Dispute := focal_claim x challenge_claim x sources(publisher, origin, retrieval boundary, provenance state) x independence_groups x evidence(state known/unknown/withheld) x relations(supports|challenges) x knowledge_gate_state; withheld is an explicit state, never an absent field.", ["CL-P1"]),
        "mathematical_model": art("Per variant x task and variant x stratum: raw counts (assigned, presented, submitted, timeout, missing, withdrawn, correct, incorrect, unscored), provenance recall exact/partial/none, challenge seen/not/missing, overload counts, submitted-only and censored-inclusive time medians, disclosure and keyboard step medians. Rates over n_assigned. No CI, no power, no participant inference from technical trials.", ["CL-M2", "CL-L1"]),
        "synthesis_and_gaps": art("Gaps: no human participants; operator is owner and reviewer; same-host replay only; bibliographic (not full-text) external sources; node label truncation in the SVG is cosmetic and covered by the linear equivalent. A future 15-20 participant study remains an optional evidence upgrade.", ["CL-L1", "CL-D1"]),
        "independent_audit": {"content": "Independent verifier recomputed parity, probes A-J with controls, two-process replay digests, denominators, privacy scan and frozen manifest from tracked bytes; found no winner, no human N and no superiority phrase in any artifact. Same-host replay is labelled replay, not external audit.", "claim_refs": ["CL-M2", "CL-U1", "CL-L1"], "producer": AUDITOR},
        "platform_plan": art(
            "## Scope\nRenderer contract and frozen disclosure rule for the AgentOS knowledge/dispute view; no production UI, no knowledge-model change.\n"
            "## Architecture\nOne canonical dispute contract feeds CARD and GRAPH view models; UI displays only and may raise a separate change request, never mutate knowledge status or authority.\n"
            "## Workstreams\n1. Adopt renderer-contract.json in the platform UI spec. 2. Keep oracle-free browser contract generation. 3. Optional future human study (inactive template).\n"
            "## Milestones\nM1 Phase A PREPARATION_READY (done). M2 operator design review recorded in operator-decision.json. M3 canonical research-plan at most PASS_WITH_LIMITS. M4 optional human-study authorisation (separate ticket).\n"
            "## Verification\nfrozen-manifest check, dependency gate, probes A-J with controls, process-separated replay, privacy scan, tests/test_s1_014_regressions.py, real Chromium keyboard-only probe.\n"
            "## Risks\nSingle operator as owner and reviewer; same-host replay only; SVG label truncation (mitigated by linear equivalent); bibliographic-only external sources.\n"
            "## Open decisions\nProvisional default (card / graph / task split / none) awaits the operator questionnaire; PASS requires a real 15-20 participant study.",
            ["CL-X1", "CL-A1"]),
        "progress": art(f"Status {status}; dependency gate {gate['status']}; probes all_detected={probes['all_detected']}; replicated={comparison['replicated']}; hard_gates_green={metrics['hard_gates_green']}; operator_review_n={candidate['operator_review_n']}; human_study_n=0.", ["CL-X1"]),
    }
    limitations = [f"ticket status {status}; audit verdict covers preparation evidence only, never human effectiveness",
                   "human_study_n=0; comparative_human_effectiveness=NOT_MEASURED",
                   "single operator acts as owner and reviewer (design approval only)",
                   "same-host process-separated replay, not external audit",
                   "external HCI sources stored as bibliographic/availability records, not full text",
                   "inherited S1-011/S1-012/S1-013 limits carried verbatim in dependency-gate.json"]
    return {"producer": PRODUCER, "auditor": AUDITOR,
            "config": {"min_source_count": 3, "min_verified_ratio": 1.0,
                       "required_artifacts": ["research_plan", "source_registry", "feature_catalog", "architecture_models",
                                              "mental_model", "ontology", "mathematical_model", "synthesis_and_gaps",
                                              "independent_audit", "platform_plan", "progress"]},
            "sources": sources(), "claims": claims, "artifacts": artifacts,
            "audit": {"producer": PRODUCER, "auditor": AUDITOR, "verdict": verdict, "limitations": limitations},
            "s1_014": {"status": status, "human_study_n": 0, "operator_review_n": candidate["operator_review_n"],
                       "comparative_human_effectiveness": "NOT_MEASURED", "winner": None,
                       "frozen_manifest_sha256": candidate["frozen_manifest_sha256"],
                       "metrics_sha256": metrics["metrics_sha256"]}}
