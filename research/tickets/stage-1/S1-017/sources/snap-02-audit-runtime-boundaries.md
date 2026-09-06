# Audit/runtime boundaries: SRC-01 section 10 L5/L6, SRC-03 section 4 (S1-017 evidence role: audit-boundary)

Provenance: excerpts of tracked repo files at base commit 091ade2
(`spec/SPEC.md` sections 2/4/6, `src/agentos/gateway.py` approval pipeline,
`src/agentos/journal.py` atomic journal). Internal design inputs; full files
remain in the repo. Role labels follow the ticket's source map; the excerpts
are the locally inspectable substance.

Canonical URI: https://local.agentos.invalid/AgentOS/research/tickets/stage-1/S1-017/sources/snap-02-audit-runtime-boundaries.md
Publisher: AgentOS repo (spec + reference implementation)
Version: SPEC v1.0 at 091ade2, freeze 2026-09-05
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: audit-boundary (gateway ownership, atomic evidence)
Access/license: local repo files, full-text excerpt authorized

## SRC-01 section 10 L5/L6 (lease/fencing boundaries, paraphrased)

- L5-class: mutating intent is recorded BEFORE the effect; repeats without a
  recorded outcome surface UNKNOWN_OUTCOME + reconciliation, never blind retry.
- L6-class: mutating ops require a live RUNNING run with an unexpired lease
  verified in SQL; fence tokens come from a monotonic persisted counter and
  are stamped into the activity record.

## SRC-03 section 4 (lifecycle/state semantics, paraphrased with identifiers)

- Approval lifecycle GRANTED → CONSUMED | EXPIRED | REVOKED with exactly-once
  conditional-UPDATE consumption over (nonce, actor, operation,
  tool_identity, canonical args, target, expiry).
- Transition + audit event commit in ONE sqlite transaction (journal); the
  audit chain is hash-linked (`prev_event_sha256`); evidence packs fail loudly
  on chain gaps.
- Memory scoping enforced at SQL level; cross-scope reads raise
  MemoryScopeViolation. External content is untrusted and can never expand
  capabilities, policy, or scope.

S1-017 use: grounds invariants R1 (gateway ownership), R2 (non-authority),
R3 (immutable evidence), R5 (complete authority chain) and R12-adjacent
atomicity. Crash/reconciliation semantics are inherited for worker-crash and
unknown-outcome scenarios.
