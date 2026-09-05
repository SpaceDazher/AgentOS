# S1-003 SHACL/ontology decision and executable artifacts (S1-016 evidence role: formal-semantics)

Provenance: excerpts of `origin/main` tracked bytes (evaluation record,
engine results, shapes). Record: result `pass`, revision 24,
goal `goal_RVX89EP2SEQ94MSZ01M0VAVECK`,
campaign `rcamp_6FTDN1FMJ9BNV65501M0VAVECK`,
evaluation `reval_KHXH2JAY5JFW8YJM01M0VAVEEM`,
chain `b9c9e2fbbac5db994e584a24669f0f5475e0f6942fe3d5347fad8592fbf83157`.

Canonical URI: https://local.agentos.invalid/AgentOS/research/tickets/stage-1/S1-003/results/decision-evidence
Publisher: AgentOS S1-003 (canonical rev 24)
Version: branch codex/s1-003-executable-shacl (frozen shapes-v3), retrieved 2026-09-05
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: formal-semantics (real pySHACL execution precedent)
Access/license: local repo bytes, excerpt authorized

## Engine evidence (engine-results.json, origin/main bytes)

- `pyshacl_executed: true`, verdict `pass`.
- Coverage: 24 fixtures / 26 profile runs, 26 matched (open + promoted_only).
- Runtime identity: rdflib 7.6.0, pyshacl 0.40.1 (S1-016 reuses these exact
  engine versions and executes its own runs; S1-003 runs are precedent, not
  S1-016 proof).

## Lifecycle/scope/provenance vocabulary (shapes-v3.ttl, 9209 bytes)

- `hubs:locatedIn` split into `sh:minCount 1` (missing_effective_scope) and
  `sh:maxCount 1` (multiple_effective_scopes): exactly one effective scope
  per subject — the single-scope precedent for lineage invariant L1.
- Evidence bindings: canonicalSourceId, publisherId, independenceGroup,
  resolverVersion, metadataFrozenAt (the provenance tuple S1-007 ISO5 and
  S1-016 lineage provenance reuse).
- SPARQL-backed cross-checks bind evidence scope to subject scope
  (`?ev hubs:locatedIn ?evScope`), subject scope to actor scope, and budgets.

## Honest limits carried

- v1 record carries no limitations list; engine evidence is bounded to the
  frozen 24-fixture corpus (no arbitrary-graph proof).
- pySHACL runtime is optional/isolated (ADR-0009); core AgentOS stays
  stdlib-only.
