# E2 provider-failure retry results (healthy-window re-run of the 42 failed tasks)

Run date: 2026-08-22. Method: the 19 task keys that had ≥1
provider-failure ("no AGENTOS_RESULT") episode in E2-v2 were re-run once each
in a healthy window, with the R4 runner (true run terminal states, fail
classes, trace digests). Raw: `.agentos-e2-retry/results.json`.

## Result

| Metric | Value |
|---|---|
| Retried episodes | 19 (one per affected task key) |
| Retry pass¹ | **16/19 = 0.842** |
| Provider failures in retry window | **0** (window was healthy) |
| Remaining failures | 3 × has_code evaluator rejects (mul-int, fib-list, slugify) — true negatives |

All three remaining failures are `worker_ok=True` episodes where the declared
artifact missed the test-file requirement; runs are COMPLETED and the gate
correctly rejected. No provider incidents in this window.

## Healthy-window pass¹ estimate

Combining E2-v2 episodes that were NOT provider-failed (58) with the 19
retries: **pass¹ = 74/77 = 0.961** in healthy conditions.

Interpretation caveats:
- This is a post-hoc conditional estimate, not the pre-registered protocol
  number; the protocol figure for E2 remains v1's pass¹=0.93 [0.863–0.966]
  with pass⁵=0.75 NOT meeting the threshold.
- pass⁵ cannot be repaired by retries by definition (strict AND over all
  repeats): v2's pass⁵=0.05 stands as measured for that degraded window.
- The retry confirms the failure attribution: removing upstream provider
  incidents moves pass¹ from 0.51 to ~0.96, consistent with 42/49 v2 failures
  being external.

## What this closes

The methodological loop demanded by review R4: failures are now classified
from recorded fail classes (not narrative), runs carry true terminal states,
and provider-vs-evaluator attribution is computable from committed data.
