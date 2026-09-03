# S1-011 decision: minimal promote/challenge gate as MVP (PASS_WITH_LIMITS)

Verdict: `PASS_WITH_LIMITS` (cap forced by the provisional independence
threshold and the absence of a human operator study; see limits below).
Phase A result: `READY_FOR_CANONICALIZATION`. No truth oracle is claimed.

Revision note: this is the R3 corrective evidence revision, measured
fresh at commit `9d4c910`. R2's nine findings are closed: explicit
evidence bindings, shared promotion predicates, stale-view exclusion,
complete case-bound ledgers, exact per-cell matrix, resolvable Git
provenance, dependency identity, raw-derived publication and simultaneous
UNKNOWN bounds. Follow-up probes also covered evidence-free reads and
the shared-path ledger identity for all three designs. See
`CORRECTIVE_R3.md`. The corpus contains 72 cases; the contract is v1.0.2.

## Recommendation

Adopt the **minimal promote/challenge gate** exactly as frozen in
`knowledge-gate-contract.json` v1.0.2 / `state-machine.json`:

- States: `PROPOSED -> PROMOTED / REJECTED / RETRACTED`,
  `PROMOTED -> CHALLENGED / RETRACTED`, `CHALLENGED -> PROMOTED (new
  decision/version) / RETRACTED`. `REJECTED` and `RETRACTED` are terminal
  and preserve immutable history.
- `PROMOTED` means only "passed the versioned governance gate for the
  stated scope/policy". It is not truth.
- Provisional evidence threshold with strict bindings: >=2 verified
  evidence records with valid digests, strict boolean verified flags,
  declared lineages and groups, >=2 distinct lineages AND >=2 groups
  (lineage-collapsed), same claim version/scope, active sources, no
  unresolved challenge or revocation, provenance/digest/policy present,
  governance-only final step. Malformed bindings fail as
  INVALID_EVIDENCE_BINDING; missing fields fail closed (no defaults).
- Authority: worker proposes/opens challenges and withdraws own
  proposals; governance gate promotes/upholds/retracts/revokes/
  supersedes; operator upholds/resolves/withdraws/revokes. External
  content never transitions anything (quarantine).
- Challenge immediately excludes the claim from the eligible derived
  view; history stays hash-verifiable in a hash-chained ledger.
  Source revocation invalidates the claim and its dependents.
  Supersession links `SUPERSEDES` and retires the old version. Derived
  claims need their own evidence and a governance decision. Duplicate
  keys and replays re-evaluate the live predicate; stale records never
  restore visibility.
- Rollback: select a prior contract version and re-run the gate over
  preserved history; nothing is ever rewritten.

## Evidence (648 rows/run, two process-separated runs, one commit/tree)

- minimal-gate: all 11 hard safety counters exactly zero,
  invalid_transition_count zero, transition exactness and view
  correctness 1.0, probes A-H pass on all seeds, confusion P/R 1.0.
- argumentation (naive grounded-style, no independence counting,
  transitive support allowed): false promotions (precision 0.448),
  probes A, D, G fail; exactness 0.778. Failure mode: single or
  correlated support suffices for IN, and parent support transitively
  promotes derived claims without their own evidence.
- tms (naive automatic revision by `tms_engine`): false promotions
  (precision 0.464), 96 ledger/authority consistency violations across
  merged seeds plus authority expansions, probes A, D, G fail. Failure
  modes: same acceptability weakness plus view-changing transitions
  with no governance decision.
- All three: recall 1.0 (no valid promotion missed), probes B/C/E/F/H
  pass (shared strict plumbing holds).
- Sensitivity: 20 per-weight (+-50%) sweeps + 200 seeded normalized
  compositions, 0 winner flips, UNKNOWN disclosure clean
  (unknown_dependent=false). The winner is robust because measured
  safety dimensions floor minimal-gate above any permitted reweighting.
  Hard-failed designs are excluded before ranking; an all-fail field
  would yield BLOCKED, never "best of the unsafe".

## Why not the richer models now

Both alternatives fail hard invariants in their textbook (naive) form,
not because of implementation bugs: acceptability without independence
binding promotes correlated/Sybil support, and automatic revision
bypasses governance authority. Hardening either (independence binding +
authority binding + UNDECIDED/backtracking operator procedure) is real
work that converges toward the minimal gate plus a graph cache. That
work is deferred, not denied (see handoffs). This resolves G-06 for the
MVP boundary: argumentation/TMS are rarely production-tested here
because their naive forms are unsafe under the frozen invariants.

## Limits (transferred, must gate production)

1. Provisional threshold is uncalibrated: real independence,
   correlation/Sybil resistance and evidence-unit calibration are
   S1-012. Any production use before S1-012 stays blocked; this task
   caps at `PASS_WITH_LIMITS`.
2. Operator workload is a model/simulation estimate, not a human study.
   Comprehension and approval fatigue are S1-013; explainability stays
   utility-estimated until then.
3. No SHACL mapping exists yet for attack/support/justification
   relations (ontology_shacl_fit abstains for both alternatives); S1-003
   alignment holds only for the minimal mapping.
4. Argumentation cycles never occur in the corpus (no cyclic attack
   graphs); convergence behavior on hostile graphs is UNKNOWN.
5. Phase A is worktree evidence. Live DB consistency, artifact-chain
   freshness and wiki checks are a separate Phase B result; consult
   `../evaluation-record.json` for canonical publication. Neither phase
   proves production persistence, distributed concurrency or human UX.

## Rollback without history loss

Re-select any prior contract version; replay immutable history through
its gate; past decisions are re-evaluated, never edited (contract
section `migration_expiry_rollback`). The corpus, runner and evaluator
are deterministic, so any rollback decision is exactly reproducible.
