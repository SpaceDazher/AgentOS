# S1-007 — QA3: retrieval and index isolation (per-scope vs shared RLS)

**Wave:** W2 · **Priority:** P0 · **Owner:** security · **Deps:** S1-003, S1-005 (both done)

## Research question
Is per-scope indexing safer and sufficiently useful than a shared index with
row-level retrieval filtering, and can either design prove no cross-scope
reads or leakage?

## Decision (resolved by this ticket)
QA3 selects **per-scope indexing** as the retrieval isolation contract for the
in-scope profiles (A, B), over canonical scope-tagged rows, with:

- the **retrieval-time scope check mandatory** (defense in depth, never skipped
  on cache-hit paths);
- a **cache key binding (scope_id, object_id, version)** — scopeless /
  object-id-only cache keys are a demonstrated near miss and are rejected;
- **scope-first projection** — scope_id and provenance survive projection for
  same-scope records; cross-scope projections are empty;
- **version-bumped invalidation** on revoke / move / edit so no cached key
  survives;
- the existing SQL `WHERE scope_goal_id = ?` filter (spec/SPEC.md §7) retained
  as storage-level defense in depth, never the sole boundary;
- **residual risk, migration triggers and non-goals** recorded in the QA3
  decision contract (`agentos.s1-007-qa3-contract/v1` in `architecture_models`);
- **profile C deferred** (MLS/TEE evidence weak per G-04; rollout is
  S1-018's domain and remains non-scope here).

## Evidence classes (all verified)
- ontology/scope: SRC-05, S1-003-SHAPES, AGENTS-INVARIANTS
- architecture/data model: SPEC-ARCH, GATEWAY-IMPL, MIGRATIONS-IMPL,
  S1-003-BUNDLE, S1-005-BUNDLE, SRC-03, SRC-06, PLAN-DEF
- authorization/security: SRC-02, SRC-07, OWASP-AUTHZ, PG-RLS
- retrieval isolation test method: OWASP-WSTG-IDOR, S1-007-RESULTS

Quantitative acceptance: **3 scopes** (scope-alpha/beta/gamma), **12 isolation
test cases** (6 cross-scope + 6 cache/revocation), **0 unauthorized content
disclosures**.

## Files
- `bundle.json` — FLOW-11 research bundle (17 sources, 16 claims, 11
  artifacts, independent audit, 2 probes).
- `retrieval_isolation_probe.py` — executable stdlib probes
  (`cross-scope-isolation`, `cache-revocation`); also drives the real
  `ToolGateway` memory-scoping path and re-verifies repo-local source hashes
  from disk.
- `probe-results.json` — probe records, `final_verdict: pass` (byte-stable so
  its on-disk SHA-256 binding stays reproducible).
- `README.md` — this file.

## Run
```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-007 QA3 retrieval and index isolation per scope versus shared RLS" --bundle "research/tickets/stage-1/S1-007/bundle.json" --db ".agentos-research/platform-stage-1"
```

Expected result: `pass_with_limits` (deterministic research evaluation; never
`Goal ACCEPTED`).

## Adversarial probes (both expected `pass`)
1. `cross-scope-isolation` — valid object id queried from another scope
   returns deny/empty with **byte-identical error detail and bounded p50
   timing** vs an unknown id (no existence leak); 6 cases.
2. `cache-revocation` — a shared-index cache hit for a revoked/moved object
   **never returns stale content to the old scope**; 6 cases with an
   injectable clock.