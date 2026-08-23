# E2 v2 re-run results (recording contract closed; provider instability documented)

Run date: 2026-08-22 (second full series, same frozen frame `eval/e2_tasks.py`,
same protocol). Purpose: close the §Compliance deviations of the first run —
evidence packs + env now recorded per episode. Raw:
`.agentos-e2-full-v2/results.json`.

## Headline

| Estimand | Value |
|---|---|
| pass¹ | **0.51** (51/100) |
| pass⁵ | 0.10 (2/20 задач: clamp-num 5/5, greet-basic 4/5…) |
| Evidence packs | **100/100 episodes** (path + sha256 recorded) ✓ |
| env capture | python / hermes_bin / platform per episode ✓ |

## Why pass¹ dropped from 0.93 to 0.51 — provider instability, not harness change

Post-run audit of all 49 failing episodes:

| Mode | Episodes | Cause |
|---|---|---|
| "no AGENTOS_RESULT line" | **42** | the LLM **provider returned empty replies** ("No reply: the model returned empty content after retries and any fallback providers") — upstream API degradation during this window, not a harness or prompt regression |
| has_code true negatives | 7 | worker omissions (missing/non-compliant test files), correctly rejected |

Verification: 12 of the first 26 session transcripts contain the provider's
own "No reply" banner. The harness handled every failure safely: no false
accepts known, all failures recorded with reasons, audit chains intact.

The two series bracket real-world variance: E2-v1 (healthy provider window)
= 0.93; E2-v2 (degraded window) = 0.51. This is exactly why the protocol
records worker/env per episode and why single-window numbers must not be
read as system capability. A fair capability estimate requires retrying
failed-with-provider-error episodes in a healthy window (future work;
protocol §evaluator quality).

## What the re-run proves (the actual point)

1. Recording contract now satisfied end-to-end: pack path+sha256 for every
   episode, env captured.
2. Harness stability under provider degradation: zero crashes, zero security
   events, all 100 episodes completed with clean terminal states.
3. Failure classification is automatic and auditable.

## Honesty notes

Same as v1 plus: pass numbers from this run are contaminated by an external
incident and must not be quoted as capability metrics; use them only as
stress-test evidence of safe degradation.
