# ADR-0008: Autoresearch keep/discard policy

Date: 2026-08-22. Status: Accepted.

## Context

The harness adapts itself through experiments (Karpathy-style autoresearch).
Without a strict decision policy, noisy measurements and reward hacking
produce false progress.

## Decision

An experiment is one hypothesis, one mutable scope, one budgeted run against
frozen evals. Outcomes:

- **KEEP** — candidate improves the primary metric above the recorded noise
  floor AND no hard regression on any frozen eval AND all hard constraints
  hold (zero false accepts on adversarial/near-miss holdout, zero forbidden
  effects, audit/evidence completeness 100%, evaluator/corpus hashes
  unchanged, budgets respected). Complexity penalty breaks ties: a
  statistically equal candidate is DISCARDed.
- **DISCARD** — anything else that completed honestly. Evidence is kept;
  the abandoned worktree/commit stays recoverable via the experiment record.
- **RETEST** — measurement ambiguity or noise suspicion; at most one retest
  per experiment, then decide.
- **CRASH** — infrastructure/provider failure; recorded separately, never
  counted as capability signal.
- **QUARANTINED** — security/integrity violation (frozen-hash mismatch,
  forbidden effect, policy bypass). Candidate scope is marked untrusted;
  campaign stops.

Stop conditions for a campaign: experiment budget exhausted; three
consecutive CRASHes; frozen-hash change detected; ambiguous measurement;
scope expansion required; wall-clock/cost budget exhausted. No unbounded
loops. `git reset --hard` on user branches is forbidden; experiments run in
separate worktrees/branches.

## Consequences

- Self-improvement claims always trace to a manifest, frozen hashes and a
  recorded decision — auditable and reproducible.
- Progress is intentionally slow; the policy prefers discarding over
  uncertain keeping.
