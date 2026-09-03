# S1-011 decision: minimal promote/challenge gate as MVP (PASS_WITH_LIMITS)

Verdict: `PASS_WITH_LIMITS` (cap forced by the provisional independence
threshold and the absence of a human operator study; see limits below).
Phase A result: `READY_FOR_CANONICALIZATION`. No truth oracle is claimed.

## Recommendation

Adopt the **minimal promote/challenge gate** exactly as frozen in
`knowledge-gate-contract.json` v1.0.0 / `state-machine.json`:

- States: `PROPOSED -> PROMOTED / REJECTED / RETRACTED`,
  `PROMOTED -> CHALLENGED / RETRACTED`, `CHALLENGED -> PROMOTED (new
  decision/version) / RETRACTED`. `REJECTED` and `RETRACTED` are terminal
  and preserve immutable history.
- `PROMOTED` means only "passed the versioned governance gate for the
  stated scope/policy". It is not truth.
- Provisional evidence threshold: >=2 verified evidence records, >=2
  declared independence groups (lineage-collapsed: same provenance
  lineage is one group even under different URLs/labels), same claim
  version/scope, no unresolved challenge or source revocation,
  provenance/digest/policy present, final transition by the governance
  gate only.
- Authority: worker proposes/opens challenges; governance gate promotes/
  upholds/retracts; operator resolves/escalates/revokes/rolls back.
  External content never transitions anything (quarantine).
- Challenge immediately excludes the claim from the eligible derived
  view; history stays hash-verifiable. Source revocation invalidates the
  claim and its dependents. Supersession links `SUPERSEDES` and retires
  the old version. Derived claims need their own evidence and decision.
- Rollback: select a prior contract version and re-run the gate over
  preserved history; nothing is ever rewritten.

## Evidence (540 rows/run, two process-separated runs, one commit/tree)

- minimal-gate: all 11 hard safety counters exactly zero, probes A-H
  pass on all seeds, confusion P/R 1.0, score 0.936.
- argumentation (naive grounded-style, no independence counting,
  transitive support allowed): 12 false promotions / 12 false
  retentions; probes A, D, G fail; score 0.489. Failure mode: single or
  correlated support suffices for IN, and parent support transitively
  promotes derived claims without their own evidence.
- tms (naive automatic revision by `tms_engine`): 15 false promotions /
  15 false retentions, 33 authority expansions, 2 derived-without-
  evidence promotions; probes A, D, G fail; score 0.489. Failure modes:
  same acceptability weakness plus view-changing transitions with no
  governance decision.
- All three: recall 1.0 (no valid promotion missed), probes B/C/E/F/H
  pass (shared governance plumbing holds).
- Sensitivity: 20 per-weight (+-50%) sweeps + 200 seeded normalized
  compositions, 0 winner flips. The winner is robust because measured
  safety dimensions (52% weight) floor minimal-gate above any
  reweighting the rubric permits. argumentation and tms tie for second
  on scores but differ in failure mode (acceptability-only vs
  acceptability-plus-authority); both are hard-excluded regardless of
  soft weighting.

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
2. Operator workload (0.35-0.40 actions/case) is a model/simulation
   estimate, not a human study. Comprehension and approval fatigue are
   S1-013; explainability cells stay low-confidence until then.
3. No SHACL mapping exists yet for attack/support/justification
   relations (ontology_shacl_fit abstains for both alternatives); S1-003
   alignment holds only for the minimal mapping.
4. Argumentation cycles never occur in the corpus (no cyclic attack
   graphs); convergence behavior on hostile graphs is UNKNOWN.
5. Cloud/worktree evidence only: live DB consistency, artifact chain
   freshness and wiki checks require the Phase B local harness.

## Rollback without history loss

Re-select any prior contract version; replay immutable history through
its gate; past decisions are re-evaluated, never edited (contract
section `migration_expiry_rollback`). The corpus, runner and evaluator
are deterministic, so any rollback decision is exactly reproducible.
