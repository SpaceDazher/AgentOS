# S1-009-FU-01 — Delegation Grant Contract

**Owner:** Gateway/Policy
**Status:** Open follow-up from S1-009
**Scope:** SM6 exact-action delegation grants and child scope.

MCP 2026-07-28 and A2A 1.0.0 do not carry a hub-authoritative delegation
grant. This follow-up owns the missing hub contract: actor, exact operation,
canonical argument digest, expiry, one-time atomic consumption, narrowed child
scope, fencing token, and revocation epoch.

**Exit evidence:** a versioned contract, negative replay/expiry/scope tests,
and a clean process-separated measurement showing that protocol payload claims
cannot create or widen a grant. S1-010 remains exclusively the tool-poisoning
follow-up.
