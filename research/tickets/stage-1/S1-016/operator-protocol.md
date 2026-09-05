# S1-016 operator architecture-decision protocol (single review)

Scope: one operator architecture decision over the frozen comparison of
representations A/B/C. This is NOT an implementation-conformance proof and
NOT a distributed-systems proof: no production graph store, no arbitrary
executions. Maximum honest status `PASS_WITH_LIMITS`.

## Review material

- `results/comparison.json` (replay verdict + digests), `results/metrics.json`
  (L1-L12 counters, rates, latencies), `results/sensitivity.json` (748 weight
  vectors, flips), `results/decision.md`, `results/limitations.md`,
  `results/independent-audit.md`, candidate FLOW-11 `bundle.json`.
- Corpus: 48 scenarios; matrix 48 x 3 x 3 x 2 = 864 observations.

## Questions (exactly 10, one message, answer format `1A 2A ... 10A`)

1. Authoritative runtime scope? A: exactly one flat canonical scope; B: several scopes from provenance graph.
2. Full PROV-Dictionary form? A: derived/export projection; B: authoritative runtime; C: minimal runtime relations + derived export.
3. Cross-scope copy? A: new target version + explicit copy operation; B: rewrite the original's scope.
4. Cross-scope move? A: copy/create + source tombstone/removal with observable partial state; B: in-place scope rewrite.
5. Membership deletion? A: append-only removal, insertion/history kept; B: physically delete history.
6. Lineage in authorization? A: no, scope/policy only; B: yes, provenance edge inherits access.
7. Round-trip gate? A: 100% semantic match on the declared profile; B: best effort with silent field loss.
8. Unsupported PROV constructs? A: explicit UNSUPPORTED/limitation; B: silently ignore.
9. Result interpretation? A: bounded architecture decision, not implementation conformance; B: production proof.
10. Status after all gates? A: PASS_WITH_LIMITS; B: OPEN/INCONCLUSIVE; C: PASS.

## Recording and fail-closed bindings

Only structured answers (10 letters), timestamp (UTC), opaque operator ID and
SHA-256 of reviewed contract/corpus/bundle artifacts are stored in
`operator-decision.json`. No raw content, secrets or identity mappings enter Git.

- 1B, 3B, 4B, 5B, 6B, 7B, 8B, 9B, 10C forbidden (block closure).
- 2A/2C admissible on evidence; 2B admissible only if B is the unique hard-safe
  winner and never becomes an authorization source.
- 10B leaves the ticket open.
- Verifier rejects missing/extra answers, unknown letters, stale artifact
  hashes, forged counts and manual verdict substitution.
- A recorded sensitivity flip caps the verdict at INCONCLUSIVE even with
  admissible answers.
