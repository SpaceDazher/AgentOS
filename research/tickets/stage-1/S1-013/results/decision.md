# S1-013 decision: PREPARATION_READY, human pilot BLOCKED_HUMAN_PILOT

Phase 1 preparation is complete and dry-run green. No human data
exists; no human claim is made. The human pilot is blocked pending
operator-approved protocol/consent/privacy, dependency acceptance,
recruitment of 15–20 real participants, and a separate go-decision.

## What was built (frozen 1.0.0-draft)

- Dependency inventory: S1-011 and S1-012 canonically closed rev 1,
  proven from cross-branch tracked bytes (see dependency-gate.json).
- Literature: UDAC primary fragment, Nudges citation record, SRC-04
  unavailability record with explicit substitution, S1-011/S1-012
  canonical decisions.
- Frozen protocol, rubric, 10 transfer scenarios, 6 approval
  prompts, frozen JSON Schemas, consent/privacy/facilitator
  docs, analysis plan.
- Static mock UI with schema-identical event vocabulary, export and
  import round-trip.
- Deterministic importer, scorer with probes A-H, independent
  replication record, native FLOW-11 bundle, derived candidate.

## Dry-run evidence (synthetic only, never human claims)

- 11 synthetic sessions: 7 ok, 3 rejected (duplicate id, malformed
  id, no consent), 1 quarantined (PII).
- C1/C3 target_met on synthetic positives; C2/C4/C5 not_met —
  correct dry-run behavior, not human rates.
- Approval oracle accuracy 4/4 on covered prompts; N/hour reported
  per role with load probes excluded and flagged.
- Probes A-H pass through the real path; replication byte-identical
  across distinct processes.

## Standing limits (transferred)

SRC-04 unavailable; planning targets are hypotheses; N=16 never
proves universal accuracy; short blocks prove no stamina; Beta-free
design; reputation never authorizes; privacy outranks Git.
