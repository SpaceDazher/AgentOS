# Data-model / audit sources: SRC-01 F7-F9, SRC-03 section 4, SRC-08 section 4 (S1-016 evidence role: audit-model)

Provenance: excerpts of tracked repo files at base commit 091ade2
(`spec/SPEC.md`, `src/agentos/journal.py`, `src/agentos/migrations/`,
`tests/test_invariants_audit.py`). Internal design inputs; full files remain
in the repo. Role labels SRC-01/SRC-03/SRC-08 follow the ticket's source map;
the excerpts below are the locally inspectable substance.

Canonical URI: https://local.agentos.invalid/AgentOS/research/tickets/stage-1/S1-016/sources/snap-02-audit-datamodel.md
Publisher: AgentOS repo (spec + reference implementation + invariant suite)
Version: SPEC v1.0, journal/machines at 091ade2, freeze 2026-09-05
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: audit-model (atomic transition+audit, version chains)
Access/license: local repo files, full-text excerpt authorized

## SRC-01 F7-F9 (fencing/reconciliation/audit fixes, 2026-08-22 review)

- F5: mutating intents record an EXECUTING activity BEFORE the effect; repeats
  with the same key and no recorded outcome return UNKNOWN_OUTCOME +
  reconciliation_required instead of re-executing (no blind retry).
- F7: mutating ops require run.status='RUNNING' AND unexpired lease, verified
  in SQL against the persisted row; fence tokens come from a monotonic
  persisted counter.
- F8: reconcile() distinguishes RECONCILED_SUCCEEDED / RECONCILED_FAILED and
  requires rowcount=1. Gate blocks RECONCILED_FAILED.

## SRC-03 section 4 (lifecycle/state semantics, paraphrased with identifiers)

Task lifecycle PENDING → READY → RUNNING → DONE with FAILED retry budget
(`attempts <= retry_budget`), BLOCKED on missing dependencies, CANCELLED on
goal cancel. Run resume only from the latest consistent Checkpoint (SHA
verified). Approval lifecycle GRANTED → CONSUMED | EXPIRED | REVOKED with
exactly-once conditional-UPDATE consumption over the full binding tuple.

## SRC-08 section 4 (audit/evidence expectations, paraphrased)

Audit events are append-only and hash-chained (`prev_event_sha256`); the
journal commits object mutation + audit event in ONE sqlite transaction
(test T14). Evidence packs are machine-readable JSON over every transition,
evaluation, approval and effect; tamper-evidence in MVP relies on filesystem
ACLs (explicit residual risk, SPEC section 1).

S1-016 use: L12 (atomic transition+audit/lineage event) and L2 (immutable
versions + SUPERSEDES) restate these contracts for the lineage layer. Crash
semantics (UNKNOWN_OUTCOME → reconciliation, no blind retry) are inherited
for copy/move/removal/export crash points.
