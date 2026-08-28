# ADR-0010: stdlib-only SLO qualification harness (`agentos.sloqual`)

Date: 2026-08-24. Status: Proposed (ticket SLOQUAL-001, extends S1-002; security gate per S1-008).

## Context

S1-002 produced a short single-process SQLite benchmark (2 s trials). Its own
`non_scope` forbids reading it as a production SLO. Stage 1 needs a
reproducible production-like qualification process covering performance,
availability, fault tolerance and revocation latency (S1-008 bound ≤5 s),
without violating two constraints: core AgentOS stays stdlib-only, and the
historical S1-002/S1-003 evidence is never rewritten.

## Decision

1. New package `src/agentos/sloqual/` — qualification harness only. It is
   never imported by core runtime paths (engine/gateway/journal stay
   untouched), uses Python stdlib exclusively (no new dependencies, nothing to
   ADR beyond this record), and records its `runner_version` in every result.
2. Revocation enforcement: core has durable approval revocation but no durable
   run-capability store. The harness adds a reference **durable capability
   ledger** (SQLite tables + gateway-compatible context whose capability set
   is re-read from durable state on every invocation) so that revoke-to-deny
   latency across multiple OS processes is measured against real durability,
   not simulation. Findings about core lacking this natively are reported.
3. Load generation is open-loop: pre-computed seeded arrival schedules,
   monotonic-clock latency referenced to scheduled send time, separate
   service/queueing decomposition, explicit dropped/late accounting — to avoid
   coordinated omission.
4. All 17 scenarios are data-driven from a versioned scenario manifest; long
   runs (≥6 h sustained, ≥24 h soak) are explicit runner invocations, never
   part of the unit-test suite. Unit tests cover statistics, contract freeze/
   verify, comparator gate semantics and ledger semantics with tiny inputs.
5. A fail-closed comparator recomputes hashes (contract self-hash,
   environment hash, artifact SHA-256s), rejects missing/empty/inconsistent
   evidence, and can only emit PASS / PASS_WITH_LIMITS / FAIL with itemized
   reasons. An empty measurement set can never yield PASS.

## Consequences

- No heavyweight dependency enters AgentOS; CI cost is a handful of fast unit
  tests plus optional manual scenario runs.
- Revocation measurements describe the harness's durable ledger path; until
  such a ledger lands in core, any production claim must say so explicitly
  (recorded as a limit in the ticket verdict).
- The comparator is intentionally stricter than the report generator: it may
  downgrade any pretty report to FAIL by rejecting its evidence chain.
