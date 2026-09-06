# S1-004 canonical formal execution evidence (S1-017 evidence role: formal-execution)

Provenance: excerpts of `origin/main` tracked bytes (evaluation record,
formal summary, Alloy/TLC verdicts). Record: result `pass_with_limits`,
revision 7, goal `goal_Z9TP87YGTAMDPD9801M18BSRXE`,
evaluation `reval_5JJ8C83TCA8CNQ5Q01M18BSRZX`,
chain `ce1fcfd5e17cec41ae8c23233b276b709f6da5f978da0ad11a0cdb07f2f1d349`,
tracked pack `research/tickets/stage-1/S1-004/results/evidence/evidence-pack-98f6b998909983706ea993e6877b56b003bb64f5228a50559bdb4e01feb98841.json`.

Canonical URI: https://local.agentos.invalid/AgentOS/research/tickets/stage-1/S1-004/results/formal-evidence
Publisher: AgentOS S1-004 (canonical rev 7)
Version: canonical record at origin/main, retrieved 2026-09-05
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: formal-execution (Alloy/TLC/simulation markers)
Access/license: local repo bytes, excerpt authorized

## Execution markers (origin/main bytes)

- Alloy: SAT on valid grant/promotion commands within stated scopes; UNSAT on
  dual-identity, dual-scope and rights-expansion near-miss commands.
- TLC: `completed_no_error: true`, 271168 distinct states of 903731
  generated, temporal properties checked, named invariants verified
  (ActivationWithinOneTick, BudgetConservation, NoBlindRetry,
  RevocationMonotonicity, among others).
- Simulator: seeds 11/22/33 with config/result/trace_digest triples and a
  probes file; `run_acceptance.py` + `run_formal.py` entry points.

## Honest limits carried

- Bounds are explicit per command/config; nothing is proven beyond the
  enumerated scopes and checked properties.
- Same-host execution; engine versions recorded in verdict files.
- S1-017 runs its own bounded model; S1-004 runs are precedent for
  discipline, never S1-017 proof.
