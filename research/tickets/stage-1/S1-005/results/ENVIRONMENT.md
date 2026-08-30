# S1-005 — Environment, commands, and provenance

Ticket: `research/tickets/stage-1/S1-005` — QA1 runtime topology: modular
monolith versus containers.

## Runtime

- Python 3.12.6 (stdlib only for all research tooling; no third-party
  dependencies were added to Core AgentOS).
- Host: Windows 11 10.0.22631, same host as the S1-002 benchmark baseline
  and the S1-004 simulation runs.
- Canonical DB root: `.agentos-research/platform-stage-1`.

## Dependency gate (executed before any research)

1. `research/tickets/stage-1/S1-002/evaluation-record.json` created from
   the live canonical DB (`research_series` revision 1 → goal
   `goal_8CTE14C6Q2E1TV8801M0TEN900`, evaluation
   `reval_N96W6BG39C3TPZZT01M0TEN90T`, result `pass_with_limits`, artifact
   chain `c03fe887…b7c4`, evidence-pack sha256 recomputed from disk);
   SLOQUAL-001 qualification checked separately (result
   `pass_with_limits`).
2. `docs/RESEARCH_STAGE_1_TICKETS.md` status diverged from the canonical
   DB (READY vs pass_with_limits) — fixed by the separate alignment commit
   `571fdfc` (statuses + durable records for S1-001/S1-002/S1-003) before
   any S1-005 research started. No evidence was rewritten.

## Experiments (measurement evidence)

Command (from this directory):

```powershell
python experiments.py > results/boundary-experiments.json
```

- E1 dispatch round trip (fixed 512B / 16KB policy payloads):
  in-process 4.86 µs / 37.77 µs; persistent child process over pipes
  25.71 µs / 207.89 µs; localhost TCP 18.20 µs / 168.03 µs.
- E2 canonical SQLite (WAL, synchronous=NORMAL) writers:
  single writer 20 587 tx/s; two writer processes 1 694 tx/s (12×
  degradation, busy-retry count 0, all committed rows complete — writes
  serialize correctly). These are same-host, bounded measurements — not
  production SLO claims.

## Rubric freeze and evaluation

The rubric (scale, weights, hard constraints, verdict rules) was frozen
before any topology was scored; the matrix binds
`rubric_sha256 = 1ee27dbb25f4ed00f9d43b526e4ba4507006e45bb4ae7d570cf4346d3308849e`.

```powershell
python evaluator.py --ticket . --out results
```

Result: winner = modular monolith (3.72 vs containers 2.07 normalized),
sensitivity 218 runs (16 weight ±50%, 200 seeded random weight vectors,
2 unknown-bounds) with zero flips; probe A rejected (violates frozen hard
constraints regardless of score); probe B rejected as INCOMPLETE (no
declared failure boundary / deterministic replay interface). Verdict
`PASS_WITH_LIMITS` — an unknown cell exists in the comparison
(containers restart/recovery was not measured on this host; production
container deployments are out of scope for this ticket).

## Wiki check

```powershell
$env:PYTHONPATH = "src"
py -m agentos.cli wiki-check --db ".agentos-research/platform-stage-1"
```

(the `--db` flag is required; without it the CLI checks a non-existent
repo-root vault and reports `missing_generated_projection`.)

## Fail-closed rules encoded in evaluator.py

- rubric hash mismatch → FAIL (weights changed after scoring = new
  research revision);
- < 8 dimensions, missing real candidate, missing matrix cell → FAIL;
- unknown cell with a numeric score, or unknown without a stated missing
  evidence → FAIL;
- probe A candidate without recorded hard-constraint violations → FAIL
  (the probe must be genuinely constructed);
- probe A violations present → candidate REJECTED regardless of score;
- real candidate without failure boundary or deterministic replay
  interface → FAIL (probe B property generalized to all real candidates);
- < 3 failure scenarios or missing scenario fields → FAIL.
