# S1-009-FU-02 — Budget Conservation Contract

**Owner:** Scheduler/Budget
**Status:** Open follow-up from S1-009
**Scope:** SM8 budget reservation, consumption, aggregation, and reconciliation.

MCP 2026-07-28 and A2A 1.0.0 do not carry hub-authoritative budget
semantics. This follow-up owns the missing hub contract: currency/unit,
parent total, reservation, consumption, child splits, parallel aggregation,
overflow, negative/malformed values, and unknown-outcome reconciliation.

**Exit evidence:** a versioned contract, conservation/property tests, and a
clean measurement proving that protocol-provided budget claims cannot increase
the hub ledger. It is intentionally separate from S1-010 and does not alter
that ticket's tool-poisoning scope.
