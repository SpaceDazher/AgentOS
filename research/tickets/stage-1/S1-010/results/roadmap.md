# S1-010 Implementation & Rollback Roadmap

## Phase A (this branch, cloud) — COMPLETE

1. Dependency gate over S1-001/S1-009 tracked packs (`dependency_gate.py`,
   `dependency-gate.json`; `canonical_db_recheck_required: true`).
2. Six official sources byte-snapshotted and SHA-256-bound
   (`source-registry.json`, `snapshots/`).
3. Frozen control contract, rubric (pre-run thresholds), threat model.
4. Frozen 56-case corpus with per-case SHA-256 and probes A–F.
5. TDD regression suite (`tests/test_s1_010_regressions.py`, 21+ tests).
6. Deterministic stdlib evaluator + process-separated runner; Run A/B on one
   clean commit; comparison, metrics, probes, environment evidence.
7. FLOW-11 bundle and candidate record (`READY_FOR_CANONICALIZATION`).

## Phase B (trusted local host) — PENDING

1. Operator runs:
   ```powershell
   $env:PYTHONPATH = "src"
   py -3.12 -m agentos.cli research-plan --topic "S1-010 tool poisoning detection evaluation" --bundle "research/tickets/stage-1/S1-010/bundle.json" --db ".agentos-research/platform-stage-1"
   py -3.12 -m agentos.cli wiki-check --db ".agentos-research/platform-stage-1"
   ```
2. The local round derives the exact canonical DB revision/IDs/chain, publishes
   tracked ticket and canonical evidence packs, re-runs all checks.
3. Only then may S1-010 move to `PASS` / `PASS_WITH_LIMITS` / `FAIL` /
   `BLOCKED` and `closed` where justified; the PR merges only after review.

## Implementation adoption sequence (gateway, later work)

1. **Registration path**: enforce L1–L3 (structural, provenance, capability
   diff, effect-power ordering) in `agentos.gateway.register`/`resolve`; deny
   drift unconditionally; keep heuristics out of the authorization path.
2. **Invocation path**: apply L5 policy matrix over exact effect classes with
   exact-action approvals; bind approvals to actor+operation+args+expiry.
3. **Output path**: apply L6 taint guard on tool outputs; mark tainted output,
   deny the effect path, keep instruction text inert data.
4. **Routing**: L7 quarantine/human-review buckets with auditable state; never
   collapse uncertainty to allow.
5. **Audit**: L8 immutable audit records with reason codes and layer traces;
   feed EP-06 evidence pack.

## Rollback plan

- Contract versions are semver; any change recomputes `contract_sha256` and
  invalidates prior frozen runs (by design).
- Reverting = restore the previous `tool-poisoning-contract.json` +
  `rubric.json` + `cases.json` + `corpus-manifest.json` quartet and re-run;
  prior runs remain valid evidence **for that frozen version only**.
- Gateway-side rollback: disable the new admission layers behind the existing
  approval semantics; quarantined entries stay quarantined (fail-closed) until
  an operator reviews them; never bulk-allow on rollback.
- Escalation triggers are listed in `control-decision.md` (critical escape,
  authority mutation, run divergence, dependency re-check failure).
