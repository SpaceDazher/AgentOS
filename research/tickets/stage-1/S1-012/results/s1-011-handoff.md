# S1-011 handoff (what S1-012 changes for the gate)

S1-011's provisional threshold (>=2 verified evidence, >=2 declared
independence groups) becomes the calibrated MVP counting rule:
independent weight counts distinct allowed upstream groups (cap 2)
with strict digest/verified/publisher bindings, lifecycle exclusion
and UNKNOWN abstention. S1-011 history, contracts and results are not
rewritten; S1-012 ran as a versioned experiment on top.

Preserved from S1-011: challenge/retraction/revocation/supersession
semantics, scope/version bindings, derived-claim-needs-own-evidence,
atomic transition+audit discipline, policy firewall against external
content. S1-012 adds no challenge mechanics of its own.

## Downstream plan

- S1-013: operator study must validate the 5-state gate plus the
  abstention/queue-triage UX; measured resolution cost replaces the
  model estimates recorded here; approval-fatigue bounds gate any
  production rollout.
- S1-019: synthesis may place document-granularity counting with
  upstream collapse as the knowledge-layer boundary, carrying the
  standing limits (uncalibrated threshold, non-blinded holdout,
  document~span tie, digest identical-text limit, no cyclic graphs).
- Any production promotion threshold requires measured calibration
  data first; until then the cap stays at PASS_WITH_LIMITS.
