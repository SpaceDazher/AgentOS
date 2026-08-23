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
| False completion rate | **не измерена** — human gold set отсутствует; ниже: «0 известных false accepts» | — |
| Mean duration | 17.1 s / episode; conditional-on-success 17.3 s | — |
| Tool calls | 1.0 / episode (mean) | — |

Pre-registered threshold (pass⁵ ≥ 0.8, CI LB ≥ 0.7): **NOT MET** — статус
"harness-reliable" не заявляется.

## Failure analysis (7 failing episodes)

| Mode | Episodes | Root cause |
|---|---|---|
| `has_code`: "no test_* functions" | 6 | worker declared implementation but tests missing/non-compliant (doctest-only or forgotten) — true negatives, evaluator correctly refused |
| `runs`: "entry not in artifact" | 1 | sum-list r1: worker declared only a test file, implementation missing — true negative |

**0 known false accepts** among the 93 accepted episodes — but this was NOT
verified by independent human review (no gold set); the accepted artifacts
passed the machine-checkable criteria only. False-completion rate and
evaluator FPR/FNR remain unmeasured.

No security-policy violations observed. All 7 failures are evaluator-rejected
worker omissions — the harness behaved as designed.

## Recording-contract deviations (found by post-run audit)

- Evidence packs were NOT built per episode by the E2 runner (0 packs across
  episode dirs) — the protocol's recording contract is only partially
  satisfied. Runner patched to record pack path+sha256 going forward;
  historical packs regenerate via `python -m agentos.cli evidence-pack`.
- Env/model versions recorded only implicitly.
Details: docs/EVALUATION_PROTOCOL.md §Compliance.

## Frame amendments during the run (recorded per freeze policy)

- fib-list: expectation in criterion was wrong (`13` for fib(7)); worker output
  `[0, 1, 1, 2, 3, 5, 8]` was correct. Fixed to exact-list match; re-run PASS.
- clamp-num: spec said "with tests" ambiguously; worker produced doctest-only
  module → correctly rejected. Spec amended to require a pytest-style test
  file; re-run PASS.

## Interpretation

- pass¹ 0.93 with CI lower bound 0.863: the harness reliably converts a
  successful worker declaration into an accepted, evidence-backed artifact.
- pass⁵ 0.75: per-task repeatability is bounded by worker variance
  (occasionally forgetting the test file), not by harness nondeterminism —
  the same tasks pass on other repeats, and every failure is a correctly
  flagged omission. The pre-registered reliability bar is nonetheless not met.
- Protocol next steps: human gold-set for false-completion; near-miss
  FPR/FNR corpora; frame expansion beyond N=20 for tighter CIs.

## Honesty notes

- Demo-class tasks, single worker (Hermes), single host, no concurrency.
- CI at n=20 tasks is coarse for pass⁵; treat [0.531, 0.888] as indicative.
- No production SLO claims — reference implementation.
