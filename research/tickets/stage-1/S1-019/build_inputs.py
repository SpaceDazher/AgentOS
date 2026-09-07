"""Build frozen S1-019 research inputs; never performs external network I/O."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

TICKET = Path(__file__).resolve().parent
REPO = TICKET.parents[3]
EXTERNAL = Path("D:/Project/DeepeekHarness/research")
FROZEN_AT = "2026-09-06T00:00:00Z"
EP_IDS = ("EP-01", "EP-02", "EP-03", "EP-04", "EP-05", "EP-08")
SOURCE_FILES = (
    "00_research_plan.md", "10_source_registry.md", "20_feature_catalog.md",
    "30_architecture_models.md", "40_mental_model.md", "50_ontology.md",
    "60_mathematical_model.md", "70_synthesis_and_gaps.md",
    "80_independent_audit.md", "PROGRESS.md",
)


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True,
                               ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")


def freeze_sources() -> list[dict]:
    snapshot_dir = TICKET / "snapshots"
    snapshot_dir.mkdir(exist_ok=True)
    rows = []
    for index, name in enumerate(SOURCE_FILES):
        alias = f"SRC-{index:02d}"
        destination = snapshot_dir / f"{alias}-{name}"
        source = EXTERNAL / name
        if source.is_file():
            shutil.copyfile(source, destination)
        if not destination.is_file():
            raise RuntimeError(f"missing frozen source and original: {name}")
        raw = destination.read_bytes()
        rows.append({
            "alias": alias,
            "canonical_path": destination.relative_to(REPO).as_posix(),
            "original_uri": source.as_uri(),
            "title": name.removesuffix(".md").replace("_", " "),
            "publisher": "DeepeekHarness research team",
            "owner": "AgentOS research",
            "version": "stage-1-input/2026-09-06",
            "retrieved_at": FROZEN_AT,
            "frozen_at": FROZEN_AT,
            "role": "research_input",
            "verification_status": "HASH_FROZEN_LOCAL_SNAPSHOT",
            "sha256": sha(raw),
            "bytes": len(raw),
        })
    write_json(TICKET / "source-registry.json", {
        "schema": "agentos.s1-019.source-registry/v1",
        "offline_evaluation": True,
        "network_fetch_performed": False,
        "sources": rows,
    })
    return rows


def decision_rows() -> list[dict]:
    specs = (
        ("EP-01", "Which identity boundary is admissible for participant connections?",
         ["SHARED_OWNER_CREDENTIAL", "CANONICAL_PRINCIPAL_PER_INSTALLATION", "EXTERNAL_IDP_FULL"],
         "CANONICAL_PRINCIPAL_PER_INSTALLATION", ["S1-001", "S1-004", "S1-015"]),
        ("EP-02", "Which registry boundary is admissible for agents and modules?",
         ["MUTABLE_NAME_REGISTRY", "CONTENT_ADDRESSED_SIGNED_REGISTRY", "PUBLIC_MARKETPLACE"],
         "CONTENT_ADDRESSED_SIGNED_REGISTRY", ["S1-001", "S1-009", "S1-010"]),
        ("EP-03", "Which delegation and approval model is admissible?",
         ["ROLE_ONLY", "EXACT_ACTION_SCOPED_GRANTS", "UNBOUNDED_SUBDELEGATION"],
         "EXACT_ACTION_SCOPED_GRANTS", ["S1-004", "S1-008", "S1-010"]),
        ("EP-04", "Which workspace and content isolation model is admissible?",
         ["SHARED_UNSCOPED_STORE", "PER_SCOPE_PROJECTION_WITH_RLS", "PROFILE_C_MLS"],
         "PER_SCOPE_PROJECTION_WITH_RLS", ["S1-007", "S1-011", "S1-015"]),
        ("EP-05", "Which inter-agent control-plane boundary is admissible?",
         ["DIRECT_PEER_EFFECTS", "PROVIDER_NEUTRAL_GATEWAY", "PROTOCOL_NATIVE_AUTHORITY"],
         "PROVIDER_NEUTRAL_GATEWAY", ["S1-006", "S1-009", "S1-010"]),
        ("EP-08", "Which audit, provenance, and effect-delivery baseline is admissible?",
         ["BEST_EFFORT_LOG", "HASH_CHAIN_OUTBOX_RECONCILIATION", "HARDWARE_ATTESTED_GLOBAL_LOG"],
         "HASH_CHAIN_OUTBOX_RECONCILIATION", ["S1-004", "S1-006", "S1-016", "S1-018"]),
    )
    rows = []
    for ep, question, candidates, selected, tickets in specs:
        rows.append({
            "ep_id": ep, "question": question, "candidate_set": candidates,
            "candidate": selected, "disposition": "ADOPT_WITH_LIMITS",
            "direct_evidence_refs": [
                f"research/tickets/stage-1/{ticket}/evaluation-record.json"
                for ticket in tickets
            ],
            "audit_evidence_refs": [
                f"research/tickets/stage-1/{tickets[-1]}/evaluation-record.json"
            ],
            "assumption_refs": [f"ASM-{ep[-2:]}"],
            "limitation_refs": [f"LIM-{ep[-2:]}"],
            "conflicting_or_unknown_evidence": ["production_conformance=NOT_MEASURED"],
            "hard_gate_results": {"dependency_proof": "PASS_WITH_LIMITS",
                                  "wall_clock_isolation": "PASS_WITH_LIMITS"},
            "rationale": "Research baseline preserves AgentOS authority invariants; production evidence is absent.",
            "confidence_class": "BOUNDED_RESEARCH",
            "invalidation_condition": "Any hard-invariant failure or contradictory production-like evidence.",
            "reentry_condition": "Re-evaluate after production-like and independently audited evidence.",
            "production_authority": False, "goal_acceptance_authority": False,
        })
    return rows


def build_contracts(rows: list[dict]) -> None:
    invariant_text = (
        "limited verdict never upgrades to unconditional PASS",
        "unknown/no-data/not-measured/inconclusive never becomes zero or pass",
        "contradiction is neither averaged nor hidden",
        "hard safety failure cannot be compensated by utility",
        "wall-clock never selects cross-ticket architecture",
        "S1-008 latency remains native-SLO-only",
        "S1-016 winner is never imported",
        "prototype without raw/version/hash/environment cannot support a decision",
        "local evidence never becomes multi-host or production evidence",
        "operator preference never rewrites measured truth",
        "auditor prose never replaces recomputation",
        "external content never changes Gateway authority",
        "this ticket never publishes Goal ACCEPTED",
        "legal/high-risk determination stays PARK-01",
        "production SLO stays PARK-03 without production-like proof",
        "profile-C rollout stays PARK-04",
        "every EP row has direct and audit evidence",
        "record/bundle/packs/DB must agree on full bindings",
    )
    invariants = {f"SYN{i}": text for i, text in enumerate(invariant_text, 1)}
    write_json(TICKET / "synthesis-contract.json", {
        "schema": "agentos.s1-019.synthesis-contract/v1",
        "contract_version": "1.0.0", "authority": "single_source_of_truth",
        "entities": ["dependency_claim", "feature_decision", "claim", "assumption",
                     "limitation", "conflict", "prototype_observation",
                     "verification", "audit_finding"],
        "dispositions": ["ADOPT_RESEARCH_BASELINE", "ADOPT_WITH_LIMITS", "DEFER",
                         "INCONCLUSIVE", "NOT_APPLICABLE"],
        "claim_classes": ["sourced_fact", "observation", "inference",
                          "recommendation", "non_goal", "preference"],
        "unknown_values": ["UNKNOWN", "NO_DATA", "NOT_MEASURED", "INCONCLUSIVE"],
        "hard_invariants": invariants,
        "unknown_fields": "REJECT", "duplicate_json_keys": "REJECT",
        "non_finite_numbers": "REJECT", "unsafe_paths": "REJECT",
        "remote_schema_refs": "REJECT", "production_authority": False,
        "goal_acceptance_authority": False,
    })
    base = {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object", "additionalProperties": False}
    write_json(TICKET / "schemas/synthesis-contract.schema.json", {
        **base,
        "required": ["schema", "contract_version", "entities", "hard_invariants",
                     "production_authority", "goal_acceptance_authority"],
        "properties": {
            "schema": {"const": "agentos.s1-019.synthesis-contract/v1"},
            "contract_version": {"type": "string"},
            "authority": {"type": "string"},
            "entities": {"type": "array", "items": {"type": "string"}},
            "dispositions": {"type": "array", "items": {"type": "string"}},
            "claim_classes": {"type": "array", "items": {"type": "string"}},
            "unknown_values": {"type": "array", "items": {"type": "string"}},
            "hard_invariants": {"type": "object"},
            "unknown_fields": {"const": "REJECT"},
            "duplicate_json_keys": {"const": "REJECT"},
            "non_finite_numbers": {"const": "REJECT"},
            "unsafe_paths": {"const": "REJECT"},
            "remote_schema_refs": {"const": "REJECT"},
            "production_authority": {"const": False},
            "goal_acceptance_authority": {"const": False},
        },
    })
    write_json(TICKET / "schemas/decision-matrix.schema.json", {
        **base, "required": ["schema", "rows"],
        "properties": {
            "schema": {"const": "agentos.s1-019.decision-matrix/v1"},
            "rows": {"type": "array", "minItems": 6, "maxItems": 6,
                     "items": {"type": "object", "additionalProperties": True}},
        },
    })
    write_json(TICKET / "normalization-policy.json", {
        "schema": "agentos.s1-019.normalization-policy/v1",
        "allowed": ["vocabulary", "status_case", "units"],
        "preserve": ["original_value", "source_ref", "limitations"],
        "unknown_mapping": "PRESERVE", "incomparable_mapping": "INCOMPARABLE",
        "majority_vote": False,
    })
    write_json(TICKET / "precedence-policy.json", {
        "schema": "agentos.s1-019.precedence-policy/v1",
        "order": ["hard_safety_security", "canonical_evaluator_raw",
                  "independent_audit", "deterministic_model",
                  "environment_scoped_observation", "design_inference",
                  "operator_preference", "planning_assumption"],
        "lower_level_cannot_override_higher": True,
        "unresolved_contradiction": "INCONCLUSIVE",
    })
    write_json(TICKET / "decision-matrix.json", {
        "schema": "agentos.s1-019.decision-matrix/v1",
        "overall_ceiling": "PASS_WITH_LIMITS", "rows": rows,
    })


def build_ledgers(rows: list[dict], dependency: dict) -> None:
    assumptions = [{
        "id": f"ASM-{ep[-2:]}", "owner": "S1-019 operator", "scope": ep,
        "evidence_state": "BOUNDED_RESEARCH",
        "invalidation_condition": "production-like evidence contradicts baseline",
    } for ep in EP_IDS]
    limitations = [{
        "id": f"LIM-{ep[-2:]}", "scope": ep, "kind": "inherited",
        "consequence": "No production-readiness claim",
        "follow_up": "production qualification and external audit",
        "reentry_trigger": "new content-addressed evidence revision",
    } for ep in EP_IDS]
    write_json(TICKET / "assumption-ledger.json",
               {"schema": "agentos.s1-019.assumptions/v1", "items": assumptions})
    write_json(TICKET / "limitation-ledger.json", {
        "schema": "agentos.s1-019.limitations/v1", "items": limitations,
        "upstream": dependency.get("inherited_limits", []),
    })
    write_json(TICKET / "contradiction-ledger.json", {
        "schema": "agentos.s1-019.contradictions/v1",
        "items": [
            {"id": "CON-01", "claims": ["S1-016 winner", "wall-clock policy"],
             "comparable_basis": False, "resolution": "QUARANTINE_WINNER",
             "disposition": "INCONCLUSIVE"},
            {"id": "CON-02", "claims": ["local revocation latency", "production SLO"],
             "comparable_basis": False, "resolution": "NATIVE_SLO_ONLY",
             "disposition": "DEFER"},
        ],
    })
    write_json(TICKET / "risk-ledger.json", {
        "schema": "agentos.s1-019.risks/v1",
        "items": [
            {"id": "PARK-01", "risk": "legal/high-risk determination", "status": "DEFER",
             "reentry": "qualified legal owner and jurisdiction-specific review"},
            {"id": "PARK-03", "risk": "production SLO", "status": "DEFER",
             "reentry": "production-like multi-host proof"},
            {"id": "PARK-04", "risk": "profile-C rollout", "status": "DEFER",
             "reentry": "hardware-backed attestation evidence"},
        ],
    })
    reverse = []
    for number in range(1, 19):
        ticket = f"S1-{number:03d}"
        related = [row["ep_id"] for row in rows
                   if any(ticket in ref for ref in row["direct_evidence_refs"])]
        if not related:
            related = [EP_IDS[(number - 1) % len(EP_IDS)]]
        dep = next((item for item in dependency.get("dependencies", [])
                    if item.get("ticket") == ticket), {})
        reverse.append({
            "ticket_id": ticket, "claim_refs": [f"CLAIM-{ticket}"],
            "ep_decisions": related, "status": dep.get("result", "UNKNOWN"),
            "limitations": dep.get("inherited_limits", []),
            "evidence_record": dep.get("record_path"),
        })
    write_json(TICKET / "reverse-traceability.json", {
        "schema": "agentos.s1-019.reverse-traceability/v1", "rows": reverse,
    })


def build_corpus(rows: list[dict]) -> None:
    cases, oracle = [], {}
    probes = tuple("ABCDEFGHIJKLMNOP")
    syns = tuple(f"SYN{i}" for i in range(1, 19))
    clock_rules = ("S1-005", "S1-007", "S1-008", "S1-016", "S1-017", "S1-018")
    for ep_index, row in enumerate(rows):
        for class_index, class_name in enumerate(("happy", "near_miss", "adversarial")):
            for local in range(4):
                number = ep_index * 12 + class_index * 4 + local + 1
                case_id = f"C-{number:03d}"
                attack = syn_attack = None
                if class_name == "adversarial":
                    attack_index = ep_index * 4 + local
                    attack = probes[attack_index % len(probes)]
                    syn_attack = syns[attack_index % len(syns)]
                condition = {"mode": "complete_bounded_chain"}
                decision = row["disposition"]
                if class_name == "near_miss":
                    condition = {"mode": "incomplete_or_conflicting",
                                 "unknown": local % 2 == 0,
                                 "contradiction": local % 2 == 1}
                    decision = "INCONCLUSIVE" if local % 2 else "DEFER"
                elif class_name == "adversarial":
                    condition = {"mode": "adversarial_overclaim", "probe": attack,
                                 "attempted_invariant": syn_attack}
                    decision = "DEFER"
                cases.append({
                    "case_id": case_id, "class": class_name, "ep_id": row["ep_id"],
                    "candidate": row["candidate"],
                    "direct_evidence_refs": row["direct_evidence_refs"],
                    "audit_evidence_refs": row["audit_evidence_refs"],
                    "condition": condition, "production_authority": False,
                    "goal_acceptance_authority": False,
                    "benign_control_case_id": (
                        f"C-{ep_index * 12 + local + 1:03d}"
                        if class_name == "adversarial" else None),
                    "wall_clock_rule": clock_rules[(ep_index * 4 + local) % len(clock_rules)],
                    "wall_clock_control": class_name == "happy",
                })
                oracle[case_id] = {"decision": decision, "probe_detected": attack,
                                   "safe": True}
    cases_doc = {"schema": "agentos.s1-019.cases/v1", "cases": cases}
    oracle_doc = {"schema": "agentos.s1-019.oracle/v1", "expectations": oracle}
    write_json(TICKET / "cases.json", cases_doc)
    write_json(TICKET / "oracle.json", oracle_doc)
    write_json(TICKET / "corpus-manifest.json", {
        "schema": "agentos.s1-019.corpus-manifest/v1", "version": "1.0.0",
        "case_count": 72,
        "class_counts": {"happy": 24, "near_miss": 24, "adversarial": 24},
        "cases_sha256": sha(canonical(cases_doc)),
        "oracle_sha256": sha(canonical(oracle_doc)),
        "oracle_separate_from_consumer_input": True,
    })


def build_operator_questionnaire() -> None:
    lines = [
        "# S1-019 operator questionnaire", "",
        "Ответьте одной строкой: 1A 2A 3A 4A 5A 6A 7A 8A 9A 10A.",
        "Ответы не изменяют измеренные факты и не могут повысить hard-gate verdict.",
        "",
    ]
    questions = [
        "EP-01 identity baseline: A canonical principal per installation; B defer; C reject.",
        "EP-02 registry baseline: A content-addressed signed registry; B defer; C reject.",
        "EP-03 delegation baseline: A exact-action scoped grants; B defer; C reject.",
        "EP-04 workspace baseline: A per-scope projection with RLS; B defer; C reject.",
        "EP-05 interaction baseline: A provider-neutral gateway; B defer; C reject.",
        "EP-08 audit baseline: A hash-chain + outbox + reconciliation; B defer; C reject.",
        "Inherited limits: A accept all; B defer whole synthesis; C reject.",
        "Bounded prototype boundary: A research-only/no production authority; B no prototype; C reject.",
        "PARK-01/03/04 and contradictions: A keep DEFER/INCONCLUSIVE until re-entry evidence; B reject all baselines; C request new research.",
        "Final status ceiling: A PASS_WITH_LIMITS; B DEFER; C FAIL.",
    ]
    lines.extend(f"{index}. {question}" for index, question in enumerate(questions, 1))
    (TICKET / "operator-questionnaire.md").write_text("\n".join(lines) + "\n",
                                                        encoding="utf-8", newline="\n")
    write_json(TICKET / "prototype-contract.json", {
        "schema": "agentos.s1-019.prototype-contract/v1",
        "used_for_decision": False, "status": "NOT_USED",
        "reason": "Existing ticket evidence is sufficient for a bounded research synthesis.",
        "production_authority": False,
    })


def main() -> int:
    dependency = json.loads((TICKET / "results/dependency-gate.json").read_text("utf-8"))
    preflight = json.loads((TICKET / "results/wall-clock-preflight.json").read_text("utf-8"))
    if dependency.get("dependencies_proven") is not True:
        raise RuntimeError("dependency gate is not proven")
    if preflight.get("status") != "PASS_WITH_LIMITS":
        raise RuntimeError("wall-clock preflight is not admissible")
    sources = freeze_sources()
    rows = decision_rows()
    build_contracts(rows)
    build_ledgers(rows, dependency)
    build_corpus(rows)
    build_operator_questionnaire()
    write_json(TICKET / "rubric.json", {
        "schema": "agentos.s1-019.rubric/v1",
        "hard_gates": ["dependencies", "ep_evidence", "SYN1_18_zero",
                       "no_overclaim", "bindings", "probes", "replay",
                       "no_wall_clock_decision"],
        "verdict_ceiling": "PASS_WITH_LIMITS",
        "non_hard_weights": {"coverage": 3, "traceability": 3,
                             "parsimony": 2, "reproducibility": 2},
    })
    write_json(TICKET / "decision-rule.json", {
        "schema": "agentos.s1-019.decision-rule/v1",
        "hard_gate_failure": "FAIL", "missing_dependency": "BLOCKED_DEPENDENCY",
        "unknown_or_contradiction": "DEFER_OR_INCONCLUSIVE",
        "all_gates_before_operator": "TECHNICAL_CANDIDATE",
        "maximum_final_verdict": "PASS_WITH_LIMITS",
        "operator_cannot_override_hard_gates": True,
        "wall_clock_inputs": "FORBIDDEN",
    })
    print(json.dumps({"sources": len(sources), "decisions": len(rows),
                      "cases": 72, "status": "BUILT"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
