# S1-013 — independent corrective review R1

Reviewed baseline: `bd20757`. Scope: preparation package, never closure of the
15–20-person human pilot. No real participant records were used in this review.

## Baseline findings and observed reproductions

| Finding | Observed negative control | Required correction |
|---|---|---|
| Publication authority | `derive_verdict` accepts gate `{all_proven:true}` and comparison `{replicated:true}` with no blockers | Revalidate pinned dependency evidence, frozen bytes, exact input matrix, both analyses and all probes; reject stale/failed/missing evidence |
| Dependency identity | Replace goal/campaign/evaluation/chain with `fabricated`, retain genuine packs: `PROVEN` | Compare identities, revision and result with schema-specific pack contents |
| Comprehension scoring | C4 wrong primary answer, no second rater, `adjudicated=correct`: 1/1; repeat answer twenty times: 20/20 for one participant | Separate trusted grading from observations, unique participant/measure, account for missing responses |
| Stop timing | Task presented at 0, request at 60000, acknowledgement at 61000: 1000 ms and correct | Start from task presentation, require mock-agent acknowledgement, retain slow/missing observations |
| UI/data contract | HTML exports `{session,events}` while importer expects three files; answer buttons and fatigue choices discard values | One canonical exchange shape, retained responses, actual browser-to-Python round-trip |
| Boundary/privacy | Forged protocol/consent versions and backwards timestamps import as ok; email inside answer imports as ok | Strict recursive schema and lifecycle validation, privacy checks over every input/output |
| Approval-rate calculation | Counts comprehension prompts, uses session max timestamp; impossible-task exclusion is `prompts>48` | Frozen block/scenario eligibility, measured active intervals, participant-level accounting |

Additional baseline evidence: 21 frozen entries checked; `source-registry.json`
and `make_bundle.py` differed from the recorded hashes. Their presence in a
manifest is not evidence that the publisher enforces the manifest.

## Baseline executable checks

- `py -3.12 -m unittest discover -s tests -p "test_s1_013*.py" -v`:
  35 tests, 34 passed and one browser test skipped.
- `py -3.12 -m evals.gen_fixtures --check`: 78 checked, no violations.
- `git diff --check`: clean; source tree remained unchanged during review.
- Real browser: bundled Node Playwright with installed Edge `152.0.4191.53`.
  Start with mock consent, click Feeling OK: exported event contains no fatigue
  value. This is an executed browser observation, not an HTML substring check.
- Core baseline excluding S1-013: 810 tests in 87.273 seconds, one skip and one
  failure in `test_concurrent_exact_repeats_create_one_goal` (unique constraint
  on research_evaluation campaign/version). Immediate isolated rerun passed.
  This concurrency failure is outside the S1-013 correction scope; disclose it
  alongside subsequent suite results, do not silently call the first run green.

## Independent acceptance after implementation

Require positive and negative controls for each finding, strict mutation refusal
at publication, actual browser response/fatigue/stop/export flow imported by the
same Python boundary, fresh process-separated recomputation, manifest and tracked
artifact hash checks, targeted tests and a full clean-commit suite. Test failures
must be reported with their actual exit status; no fake optional browser pass.

Use an isolated snapshot for tests that need legacy runtime evidence. The original
canonical DB is not a test output target. No canonical research-plan, human pilot,
real data collection or main-branch merge is authorized by this corrective review.

This file records baseline observations and acceptance requirements, not a claim
that the corrective implementation has already passed them. Final evidence belongs
in a separately dated corrective report with the exact tested commit.
