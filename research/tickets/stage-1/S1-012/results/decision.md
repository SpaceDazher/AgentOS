# S1-012 decision: document granularity as MVP (PASS_WITH_LIMITS)

Verdict: `PASS_WITH_LIMITS` (cap forced: planning threshold stays a
hypothesis, no measured calibration data, non-blinded holdout, no
human study). Phase A result: `READY_FOR_CANONICALIZATION`. No truth
oracle, no production threshold, no autonomous trust is claimed.

## Recommendation

Adopt **document granularity with upstream collapse** as the MVP
counting rule: one unit per source document, groups by provenance
lineage, independent weight counts distinct allowed groups (cap 2),
strict bindings, lifecycle exclusion, UNKNOWN abstention, policy
firewall, Beta tails and EigenTrust as recommendation-only inputs to
the review queue.

- Span view is **safety-tied** with document on this corpus (identical
  independence decisions everywhere) at higher measured cost
  (456 vs 420 units, 45,012 vs 39,240 bytes per run-a). Keep it for
  fine-grained revocation, not as the default.
- Digest view is cheapest (354 units, 39,120 bytes) but carries a
  documented keying limit: identical-text independents collapse
  (D02/D33/H03/H17). Viable only with bound upstream, never alone.
- Reputation-only is **excluded**: 17 mirror/Sybil double counts plus
  unbound observations, FAIL in all 6 cells. Scores never create
  enforcement, capability, approval, budget, PROMOTED or ACCEPTED.
- The document~span safety tie is recorded as an explicit limitation
  (tie_limitation in comparison.json), not resolved by reweighting.
  The MVP choice between the tied views rests on measured cost and
  simplicity, stated as hypothesis, with span retained as an
  equivalent alternative.

## Evidence (720 rows/run, two process-separated runs, one commit/tree)

- document/span/digest: all hard counters exactly zero, probes A-G
  pass on all seeds, confusion P/R 1.0, transition exactness 1.0,
  abstention only where the oracle allows it (rate 0.083).
- Beta tails agree with exact binomial references to 1e-9 on all
  integer parameters; metamorphic properties hold (monotone,
  washout, decay); invalid params rejected; zero trials carry no
  posterior. Tail AUC against admit labels (hypothesis quantities):
  digest 0.724, document 0.568, span 0.495.
- EigenTrust: frozen 2-node reference matches 20/37, 17/37 to 1e-6;
  anchorless graphs abstain with null trust; anchored vectors are
  stochastic; recommendation-only everywhere.
- Sensitivity: 20 weight sweeps + 200 seeded compositions + 135 joint
  prior/decay/threshold/cap combos executed through the real decision
  core — 0 flips; UNKNOWN disclosure clean apart from the recorded
  tie. Thresholds were chosen on dev; holdout metrics reported
  separately per split (no holdout-driven change occurred).

## Why not the alternatives

Digest-alone is unsafe on identical-text independents; span-alone
buys no safety over document at higher cost; reputation-alone fails
the hard gates by construction (that is its job as negative control).
The planning threshold P[theta>0.9]>=0.95 stays a hypothesis: tails
are reported, never enforced.

## Limits (transferred, must gate production)

1. Provisional counting rule is uncalibrated against measured data:
   production thresholds stay blocked (S1-012 follow-up with data).
2. Beta formulas are standard results with independent computation,
   not archived primary full text (explicit retrieval limit).
3. Holdout is lineage-isolated but author-visible, not blinded.
4. No cyclic attack graphs in corpus; no operator study (S1-013).
5. Cloud/worktree evidence only: live DB consistency, artifact chain
   freshness and wiki checks require the Phase B local harness.

## Rollback without history loss

Re-select any prior contract version; replay immutable history
through its rules; past rows are re-evaluated, never edited. Corpus,
runner and evaluator are deterministic, so any rollback comparison
is exactly reproducible.
