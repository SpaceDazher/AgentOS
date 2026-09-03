# S1-009 Adapter Implementation Roadmap

**Stage:** Stage-1 Research — Phase 1 (adapter contract, not production deployment)
**Status:** PASS (research evaluation; not a production deployment authorization)
**Created:** 2026-09-02
**Owner:** S1-009 research agent (process-separated verifier-A/verifier-B)

## Overview

This roadmap decomposes work on the **S1-009 adapter kernel and profile
contracts**. It is a research-phase plan only; it does not authorize production
deployment, standardization, or security certification. Each stage has an
owner, dependency, deliverable, test/evidence gate, rollback, residual risk,
and measurable trigger.

## Phases

### Phase 1 — Adapter Kernel and Schemas (M1)

| Field | Value |
|---|---|
| **Owner** | Research agent |
| **Dependency** | S1-001, S1-005 (dependency gate PASS) |
| **Deliverable** | `canonical-envelope.schema.json`, `adapter-contract.json`, `rubric.json` |
| **Test gate** | `tests/test_s1_009_regressions.py` — all hard-rule tests PASS |
| **Rollback** | Revert schema/contract files; revert DB migration |
| **Residual risk** | Schema may need extension for S1-010/S1-018 cross-surface attack modeling |
| **Trigger** | Research plan approved; dependency gate PASS |

**Canonical envelope fields (envelope_version 1.0):**

- `envelope_version`, `adapter_version`
- `operation.method`, `operation.id`, `operation.correlation_id`, `operation.causation_id`
- `identity.authenticated_actor` (hub-resolved), `identity.asserted_remote_actor` (untrusted)
- `identity.owner_principal`, `identity.delegator_chain`
- `capability.tool_contract_id`, `capability.tool_contract_version`, `capability.arguments_digest`
- `effect.effect_class` (`read`, `write`, `none`, `dangerous`), `effect.idempotency_key`
- `authorization.grant_present`, `authorization.grant_id`, `authorization.expiry`
- `fencing.fencing_token`, `fencing.revocation_epoch`
- `budget.parent_total`, `budget.reserved`, `budget.consumed`, `budget.remaining`, `budget.currency`, `budget.unit`
- `provenance.input_digest`, `provenance.output_digest`, `provenance.source_refs`
- `knowledge.status` (`proposal` only until governance event), `knowledge.promotion_event_id`
- `policy.version`, `policy.decision_reason`, `policy.audit_ref`
- `extensions.accepted`, `extensions.quarantined`

### Phase 2 — MCP Inbound/Outbound Profile (M2)

| Field | Value |
|---|---|
| **Owner** | Research agent |
| **Dependency** | Phase 1 |
| **Deliverable** | MCP-IN-01..07, MCP-OUT-01/02 rules in `adapter-contract.json` |
| **Test gate** | Probe A, F pass for MCP cases; 0 auth escalation |
| **Rollback** | Revert MCP rule definitions |
| **Residual risk** | MCP 2026-07-28 snapshot may drift; requires re-freeze for new versions |
| **Trigger** | Canonical envelope schema finalized |

**MCP rules:**
- MCP-IN-01: `initialize` — version validation, capability quarantine
- MCP-IN-02: `tools/list` — registry resolution, untrusted claim
- MCP-IN-03: `tools/call` — tool resolution, grant from hub ledger (not payload)
- MCP-IN-04: `resources/read` — resource registry resolution
- MCP-IN-05: `prompts/get` — prompt registry resolution
- MCP-IN-06: `tasks/create` — task creation, idempotency key host-assigned
- MCP-IN-07: `completion/complete` — completion, untrusted completion claim
- MCP-OUT-01: MCP Task result serialization — proposal-only until governance
- MCP-OUT-02: MCP Tool result serialization — no grant/promotion fields

### Phase 3 — A2A Inbound/Outbound Profile (M3)

| Field | Value |
|---|---|
| **Owner** | Research agent |
| **Dependency** | Phase 1 |
| **Deliverable** | A2A-IN-01..07, A2A-OUT-01/02 rules in `adapter-contract.json` |
| **Test gate** | Probe A, B, D, E pass for A2A cases; 0 auth escalation |
| **Rollback** | Revert A2A rule definitions |
| **Residual risk** | A2A 1.0.0 streaming/push bindings not fully modeled |
| **Trigger** | Canonical envelope schema finalized |

**A2A rules:**
- A2A-IN-01: `sendTask` — skill registry resolution, grant from hub ledger
- A2A-IN-02: `sendTaskStreaming` — streaming report (not terminal)
- A2A-IN-03: `getTask` — task state report (not terminal acceptance)
- A2A-IN-04: `cancelTask` — cancel ≠ reconcile-cancel; fencing/replay checks
- A2A-IN-05: `getAgentCard` — agent card as untrusted claim; registry resolution
- A2A-IN-06: `reportArtifact` — artifact knowledge claims rejected (Probe E)
- A2A-IN-07: `extensions` — unknown extension quarantine
- A2A-OUT-01: A2A Task serialization — proposal-only until governance
- A2A-OUT-02: A2A Artifact serialization — no promotion without governance

### Phase 4 — Registry/Policy Admission (M4)

| Field | Value |
|---|---|
| **Owner** | Research agent |
| **Dependency** | Phases 1-3 |
| **Deliverable** | ToolContract and Skill definition in hub registry; admission predicates |
| **Test gate** | Probe B (unregistered capability DENY); capability matrix passing ≥12 rows |
| **Rollback** | Revert registry definition |
| **Residual risk** | Dynamic discovery is explicitly out of scope |
| **Trigger** | All adapter rules validated |

### Phase 5 — Delegation/Budget/Receipt Integration (M5)

| Field | Value |
|---|---|
| **Owner** | Research agent |
| **Dependency** | Phase 4 |
| **Deliverable** | Budget conservation check; exact-action grant model; idempotency/reconciliation state machine |
| **Test gate** | Probe C (budget laundering DENY); Probe D (replay DENY); SM8 absent/underspecified documented |
| **Rollback** | Revert budget/conservation logic |
| **Residual risk** | Budget semantics ABSENT in both MCP and A2A — no normative integration possible |
| **Trigger** | Registry/policy admission implemented |

### Phase 6 — Knowledge Proposal Boundary (M6)

| Field | Value |
|---|---|
| **Owner** | Research agent |
| **Dependency** | Phase 4 |
| **Deliverable** | Knowledge proposal status (proposal-only); governance event model (placeholder for S1-011) |
| **Test gate** | Probe E (knowledge promotion loss DENY); accepted cases have knowledge.status=proposal |
| **Rollback** | Revert knowledge boundary logic |
| **Residual risk** | Knowledge promotion semantics ABSENT in both protocols; S1-011 will define governance event |
| **Trigger** | Registry/policy admission implemented |

### Phase 7 — Version Negotiation/Migration (M7)

| Field | Value |
|---|---|
| **Owner** | Research agent |
| **Dependency** | Phases 1-6 |
| **Deliverable** | Protocol version negotiation; extension accept/quarantine/reject policy |
| **Test gate** | Probe F (unknown version/extension QUARANTINE); downgrade rejected |
| **Rollback** | Revert version negotiation logic |
| **Residual risk** | Protocol versions change over time; requires new research per version |
| **Trigger** | All adapter rules validated |

### Phase 8 — Observability/Audit (M8)

| Field | Value |
|---|---|
| **Owner** | Research agent |
| **Dependency** | Phases 1-7 |
| **Deliverable** | Audit event emission (rule_id, version, provenance); deterministic replay fixtures |
| **Test gate** | `auditability_deterministic_replay` rubric dimension passes; process-separated rerun identical |
| **Rollback** | Revert audit logging |
| **Residual risk** | External audit (human third-party) not available at research stage |
| **Trigger** | Version negotiation implemented |

### Phase 9 — Downstream Hand-offs (M9)

| Field | Value |
|---|---|
| **Owner** | Research agent |
| **Dependency** | Phases 1-8 |
| **Deliverable** | Gap register entries linking to S1-010, S1-011, S1-018 |
| **Test gate** | Capability matrix explicitly marks SM6, SM8, SM11 as absent/underspecified with follow-up ticket |
| **Rollback** | N/A (documentation only) |
| **Residual risk** | Downstream tickets may refine semantics |
| **Trigger** | Phase 8 complete; evaluation PASS |

## Key Design Decisions

### Absent Semantics (SM6, SM8, SM11)

Three canonical AgentOS semantics are **ABSENT/UNDERSPECIFIED** in both MCP
2026-07-28 and A2A 1.0.0:

| Surface | Missing Semantic | Both Protocols | Adapter Decision | Follow-up Ticket |
|---|---|---|---|---|
| SM6 | Exact-action delegation grants and child scope | ABSENT | Unsupported (deny-by-default) | S1-010 |
| SM8 | Budget reservation/consumption/aggregation | ABSENT | Unsupported (deny-by-default) | — |
| SM11 | Knowledge promotion/challenge/rejection/revocation | ABSENT | Unsupported (knowledge stays proposal) | S1-011 |

### Provider-Neutral Boundary

The canonical envelope is provider-neutral. MCP and A2A are transport/task/tool
surfaces only. No adapter rule may inject vendor-specific authorization. All
authority fields (`grant_present`, `owner_principal`, `budget`,
`knowledge.status`) come from the hub ledger, never from protocol payload.

### Versioned Contract

- `envelope_version`: 1.0
- `adapter_version`: 1.0
- `contract_version`: 1.0
- Changes require a new research revision. No mixing of spec/contract/corpus
  revisions within one bundle.

### Migration Trigger and Rollback

- **Trigger:** Protocol version change, new capability surface, or security
  finding requiring adapter evolution.
- **Window:** New adapter version deployed alongside old; old version retired
  after 90 days (or faster if a hard-rule violation is found).
- **Rollback:** Revert to previous adapter_version; old cases remain valid
  under the frozen corpus hash contract.

## Residual Risks

1. **Protocol drift:** MCP/A2A may release new versions; each requires a new
   source-freeze and corpus hash. This ticket freezes 2026-07-28 / 1.0.0.
2. **No external audit:** Verifier identities are process-separated roles in one
   local environment, not external human auditors. Verdict is PASS_WITH_LIMITS
   due to this bounded limit.
3. **Budget/absent semantics:** Cannot be implemented because budget,
   delegation grants, and knowledge promotion are absent in both protocols.
   The adapter correctly denies-by-default and documents these as gaps.
4. **Knowledge governance:** S1-011 will define the governance event model;
   S1-009 correctly keeps knowledge at `proposal` until then.
