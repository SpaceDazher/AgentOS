# ADR-0002: Architecture — monolith, three logical planes, transactional journal

- Status: Accepted
- Date: 2026-08-21

## Context

Research (`executive_summary.md`, C23) supports execution/assurance/governance as
*logical* responsibility boundaries; nothing justifies splitting services for the MVP.

## Decision

One Python package (`agentos`) deployed as one runtime:

- **Execution control** — `engine.py` (scheduler, runs, checkpoints),
  `workers.py` (WorkerAdapter protocol).
- **Assurance control** — `machines.py` (state machines), `evaluator.py`,
  `gates.py`, `evidence_pack.py`, immutable artifact versioning in `db.py`.
- **Governance** — `gateway.py` (tool registry, capabilities, approvals,
  idempotency, fencing, reconciliation).

All state lives in one SQLite database. Every guarded state transition writes
its row change and its audit event **in the same transaction**
(`journal.py::transition`). The append-only `audit_event` table is the
authoritative audit log; projections (current object state) are derived tables
that can be rebuilt from goals/tasks/runs + events if needed.

Large artifacts (spec text, code blobs, evidence pack JSON) go to
object-storage-style paths under `runs/<goal_id>/artifacts/` with SHA-256
recorded in `artifact_version`.

## Consequences

- Crash-consistency of "accepted transition + audit event" comes free from the
  DB transaction boundary (test: audit/event atomicity).
- Moving to Postgres later means changing the connection layer only; all
  transition semantics live in Python guards, not DB triggers.
