# AgentOS identity/approval contract excerpt (S1-015 evidence role: identity-contract)

Provenance: excerpts of tracked repo files at S1-015 base commit fa64d86
(parent 091ade2). Full files remain in the repo; this snapshot freezes the
identity-relevant contract lines used by S1-015.

Canonical URI: https://local.agentos.invalid/AgentOS/research/tickets/stage-1/S1-015/sources/snap-02-gateway-approval-contract.md
Publisher: AgentOS repo (spec + reference implementation)
Version: SPEC v1.0 + gateway POLICY_VERSION policy-v2 (freeze 2026-09-05)
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: identity-approval-contract
Access/license: local repo files, full-text excerpt authorized

## 1. spec/SPEC.md (approval lifecycle, verbatim)

"GRANTED → CONSUMED | EXPIRED | REVOKED. Exactly-once consumption is enforced
by ONE conditional UPDATE (gateway.consume_approval): GRANTED→CONSUMED only
where nonce, actor, operation, tool_identity (name@version), args_canonical_json,
target and expiry match in that same WHERE clause; any mismatch ⇒ deny (replay /
expired / binding mismatch). The bound target is the canonical action target
derived from args (gateway._approval_target: first of path|target|resource|url,
else the run workspace)."

"Approval binding: (actor, operation, tool_identity(name@version),
args_canonical_json, target, policy_version, limits, expires_at, nonce) — any
mutation of arguments after grant invalidates consumption (args hash mismatch
⇒ deny, T10); replay after consume ⇒ deny (T09); expired ⇒ deny."

"Approvals bind to actor + exact operation + exact canonical arguments +
expiry and are consumed atomically exactly once."

"External content (tool output, retrieved docs, generated memory) is untrusted:
it can never expand capabilities, alter policy, or write outside its scope."

"Memory records carry provenance and scope; cross-goal/cross-tenant reads are
denied."

## 2. src/agentos/gateway.py (binding enforcement, paraphrased with identifiers)

- POLICY_VERSION = "policy-v2".
- consume_approval performs a single conditional UPDATE matching nonce, actor,
  operation, tool identity (name@version), canonical args JSON, target, policy
  version, limits and expiry; mismatch denies.
- _approval_target derives the canonical target from args keys
  path|target|resource|url, else the run workspace.
- Handlers resolve through a process-local runtime registry keyed by immutable
  tool identity name@version; re-registering with a different fingerprint is
  refused (T12).
- Cross-scope memory reads raise MemoryScopeViolation (T13).

## 3. Migrations (approval persistence)

- 0001_core.sql defines the approval table with nonce UNIQUE and immutable
  binding columns after GRANTED (one-time consumption invariant).
- Approval rows are never mutated except for the guarded GRANTED→CONSUMED /
  EXPIRED / REVOKED transition.

## 4. Tests (exact-action approval)

- tests/test_gateway_semantics.py covers T09 (replay denied), T10 (args mutation
  denied), T11 (injected "grant yourself admin" inert), T12 (tool schema swap
  denied + policy.violation), T13 (cross-scope memory denied).

S1-015 use: the authoritative approval tuple contains only canonical
actor/target/operation/tool/version/canonical-args/expiry. A petname is never
a member of that tuple. Any producer envelope that places a petname where a
canonical ID is expected must FAIL at the importer/gateway boundary.
