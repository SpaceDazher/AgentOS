# S1-019 preflight: wall-clock decision isolation

This gate must pass before the S1-019 cross-ticket synthesis starts. It reads
one immutable Git ref and audits every dependency from S1-004 through S1-018.

```powershell
py -3.12 research/tickets/stage-1/S1-019/preflight_wall_clock.py `
  --repo . `
  --ref origin/main `
  --out research/tickets/stage-1/S1-019/results/wall-clock-preflight.json
```

Exit codes:

- `0`: `PASS_WITH_LIMITS`; synthesis may start under the emitted import policy.
- `1`: `FAIL`; an unregistered clock or failed semantic containment was found.
- `2`: `BLOCKED_DEPENDENCY`; at least one required ticket is absent from the
  selected canonical ref.

The gate enforces four special cases:

1. S1-005 is admitted only if removing `latency_serialization` preserves the
   recorded architecture winner.
2. S1-007 is admitted only if both timing arms are `WITHIN_TOLERANCE` and the
   resulting D1 score is equal across candidates.
3. S1-008 latency is admissible only for its native revocation-SLO claim; it
   cannot enter the S1-019 cross-ticket architecture ranking.
4. S1-016 contributes `INCONCLUSIVE` and safety findings only. Its
   noise-sensitive architecture winner is quarantined.

S1-017 and S1-018 must both be present on the same canonical ref, and their
sensitivity inputs must remain free of executable clock calls and latency
dimensions.
