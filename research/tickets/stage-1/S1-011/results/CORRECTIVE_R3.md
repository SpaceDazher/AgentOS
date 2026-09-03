# S1-011 corrective R3

## Findings and evidence

1. Missing/null evidence scope, source state and claim version fail closed.
2. Derived and concurrent promotions use the same challenge/policy/evidence gate.
3. Superseded, revoked, unbound and evidence-free claims cannot remain visible.
4. The verifier requires exact case-bound assertion/evidence/challenge/prior-decision/decision/audit records, not just a valid hash chain.
5. Every design/seed cell must contain the exact frozen case set.
6. Recorded commit/tree must resolve in Git and carry the exact frozen bytes.
7. Dependency records are bound to the pack's goal, campaign and latest evaluation.
8. Publication re-evaluates raw A/B evidence and compares every derived summary.
9. UNKNOWN sensitivity includes simultaneous adversarial bounds across candidates.

Additional probes fixed empty-evidence visibility and alternative-design ledgers
that inherited minimal-gate identifiers on shared branches.

## RED to GREEN

The independent nine-finding regression file initially produced 18 failures.
The evidence-free read and all-design ledger probes also failed before fixes.
The resulting ticket and independent regression suites pass 97 tests; three
additional canonical publication tests verify successful and rejected bindings.
Full-suite and canonical closure results are recorded separately by the host.

## Fresh measurement

Commit `9d4c910`, one clean Git tree, 18 runner processes: 72 cases x three
designs x three seeds x two executors = 1,296 rows. Comparison: 648 rows per
run, nine exact cells, identical decisions, zero sensitivity winner flips,
UNKNOWN-independent winner. Minimal gate has zero hard counters and zero
invalid transitions. Naive alternatives remain FAIL for their measured unsafe
semantics; they are not silently repaired into a different design.

## Scope

Research result only, capped at PASS_WITH_LIMITS. S1-012 must calibrate evidence
independence and Sybil resistance; S1-013 must measure operator comprehension
and workload. No production, distributed-persistence or truth-oracle claim.
