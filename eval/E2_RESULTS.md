# E2 full-series results (N=20 tasks × 5 repeats = 100 episodes, real Hermes worker)

Run date: 2026-08-22. Frame: `eval/e2_tasks.py` (frozen). Protocol:
`docs/EVALUATION_PROTOCOL.md`. Raw: `.agentos-e2-full/results.json`
(copied to `eval/e2_results_hermes_full.json`). Aggregate:
`eval/e2_aggregate_hermes_full.json`.

## Headline estimands

| Estimand | Value | Wilson 95% CI |
|---|---|---|
| pass¹ | **0.93** (93/100) | [0.863, 0.966] |
| pass⁵ (task-clustered) | **0.75** (15/20 задач) | [0.531, 0.888] |
| False completion rate | 0 observed (no human gold set yet) | — |
| Mean duration | 17.1 s / episode (13.7 s conditional on success) | — |
| Tool calls | 1.0 / episode (mean) | — |

## Failure analysis (7 failing episodes)

| Mode | Episodes | Root cause |
|---|---|---|
| `has_code`: "no test_* functions" | 6 | worker declared implementation but tests missing/non-compliant (doctest-only or forgotten) — **true negatives**, evaluator correctly refused |
| `runs`: "entry not in artifact" | 1 | sum-list r1: worker declared only a test file, implementation missing — **true negative** |

No false accepts observed. No security-policy violations. All 7 failures are
evaluator-rejected worker omissions — the harness behaved as designed.

## Interpretation

- pass¹ 0.93 with CI lower bound 0.863: the harness reliably converts a
  successful worker declaration into an accepted, evidence-backed artifact.
- pass⁵ 0.75: per-task repeatability is bounded by worker variance
  (occasionally forgetting the test file), not by harness nondeterminism —
  the same tasks pass on other repeats, and every failure is a correctly
  flagged omission.
- Protocol next steps: N=20 frame reached ✓; human gold-set for
  false-completion and near-miss FPR/FNR remains future work.

## Honesty notes

- Demo-class tasks, single worker (Hermes), single host, no concurrency.
- CI at n=20 tasks is still coarse for pass⁵; treat [0.531, 0.888] as
  indicative, not definitive.
- No production SLO claims — reference implementation.
