# S1-011 roadmap: handoffs out of this ticket

## To S1-012 (evidence independence and Beta/Sybil calibration)

- Calibrate the provisional threshold: real independence groups,
  correlation caps, collusion resistance, evidence-unit sizing.
- Decide the fate of transitive support: grounded support rules that
  would let an argumentation layer pass probe G.
- Re-run this ticket's matrix with the calibrated threshold; the
  `PASS_WITH_LIMITS` cap lifts only on S1-012 evidence.

## To S1-013 (comprehension and approval-fatigue pilot)

- Validate the 5-state mental model with 15-20 operators; measure
  challenge resolution cost and approval fatigue.
- Replace the operator workload model estimate with measured numbers;
  revisit operator_load utility and weights.

## To S1-019 (architecture synthesis)

- Carry the frozen contract (v1.0.1), state machine, and MVP
  recommendation as the knowledge-layer boundary.
- Carried unknowns: cyclic attack-graph convergence, justification
  completeness, UNDECIDED/backtracking operator procedures.

## To Phase B (local trusted harness, required before closure)

- `research-plan` with `bundle.json`, revision write to
  `.agentos-research/platform-stage-1/agentos.db`, wiki check,
  artifact chain, tracked evidence packs.
- Recheck: live DB consistency, `chain_fresh`, latest evaluation
  validity, pack hash binding (all recorded `canonical_db_recheck_
  required: true` in dependency-gate.json).

## Residual risks kept open

- Provisional threshold may admit correlated evidence that lineage
  analysis misses (novel Sybil shapes).
- Automatic-revision designs remain excluded until a governed variant
  passes this same matrix.
- Full-suite `unittest discover` cannot go green in a worktree without
  the canonical DB (pre-existing environment failures in
  test_s1_004/005/006/007/008/009, all "unable to open database file"
  or missing-DB assertions); S1-011 adds no new failures
  (tests/test_s1_011_regressions.py green).
- Independent review F1-F12 was addressed in the second evidence
  revision (contract v1.0.1, 72-case corpus, ledger-backed evaluation,
  native harness bundle, derived verdict); a fresh independent
  re-review is still recommended before Phase B.
