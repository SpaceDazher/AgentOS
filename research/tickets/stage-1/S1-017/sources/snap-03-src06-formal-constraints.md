# SRC-06 formal/model constraints, sections 1-2 and 7 (S1-017 evidence role: formal-constraints)

Provenance: excerpts of `origin/main` tracked bytes from the S1-004 formal
program (`alloy/*.als`, `tla/*.tla`, `simulator/*.py`), which is the repo's
executable formal baseline. No formal text is invented; scope notes below
quote file structure, not semantics.

Canonical URI: https://local.agentos.invalid/AgentOS/research/tickets/stage-1/S1-004/formal-program
Publisher: AgentOS S1-004 formal program (origin/main bytes)
Version: agentos_structural_v1/v2 (.als), agentos_transitions_v1 (.tla/.cfg),
invariant_simulator.py; retrieved 2026-09-05
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: formal-constraints (bounded commands, scopes, simulator discipline)
Access/license: local repo bytes, excerpt authorized

## SRC-06 sections 1-2 (bounded modeling discipline, observed)

- Alloy commands carry exact scopes (`for 4 but exactly 2 Grant, exactly 2
  Right, exactly 1 IdentityMembership`): bounded, enumerated, no universal
  claims beyond the stated scope.
- Near-miss commands expect UNSAT (`NearMissDualIdentity`,
  `NearMissTwoScopes`, `NearMissRightsExpansion`): the model must REJECT
  dual identity, dual scope and rights expansion by construction.
- TLA+ transition system with .cfg bounds; TLC verdicts record engine
  version, distinct/generated state counts and temporal properties checked.

## SRC-06 section 7 (simulation discipline, observed)

- `simulator/invariant_simulator.py` with `run_acceptance.py` and
  `run_formal.py`; seeded runs (seed-11/22/33) with config/result/trace_digest
  triples; probes file alongside results.

S1-017 use: the S1-017 bounded Kripke/concurrent-game model follows the same
discipline (exact scopes, near-miss rejection, seeded determinism, engine
markers with versions and counts). A `checked=true` marker or narrative log
alone is never cited as proof.
