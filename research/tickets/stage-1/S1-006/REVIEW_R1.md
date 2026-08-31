# S1-006 — REVIEW_R1 (corrective round, recorded)

Scope: corrective round executed after the initial implementation of the
S1-006 research pipeline. Every finding below is fixed by commits in this
branch; each fix is covered by a regression test in
`tests/test_s1_006_regressions.py` (TDD: the failing assertion was
observed RED before the fix, then GREEN).

## Findings and fixes

1. **Commit/tree provenance was not comparable-checked.** Compared runs
   carried only contract/workload/rubric hashes; two runs from different
   commits or trees could be mixed into one comparison.
   *Fix:* every run record now carries `commit`/`tree_sha`/`dirty`; the
   evaluator rejects any compared run whose commit/tree diverges from the
   run-manifest provenance, rejects a dirty working tree and honours the
   mandatory `--expected-commit` binding.
   *Tests:* `ProvenanceMixingTests` (mixed commit, fabricated tree,
   dirty tree, expected-commit mismatch/match).

2. **Probe B detection was truthiness-based, not behavioural.** The
   incomparable-workload probe was "detected" whenever a workload hash
   string existed, even if it equalled the frozen hash.
   *Fix:* the evaluator now compares the probe's workload hash against
   the frozen manifest; an identical hash means the probe is NOT
   detected and the whole evaluation fails closed.
   *Tests:* `ProbeTests.test_undetected_probe_b_rejected`.

3. **Scenario semantics were not observable.** S3 resume, S4 redelivery
   dedup and S2 reconciliation were implicit; nothing prevented an
   unregistered or corrupted checkpoint from resuming, and no test could
   distinguish duplicate delivery from a reconciled retry.
   *Fix:* the runner now executes S3 resumes only through a registered,
   content-hash-verified `CheckpointStore` (unregistered ->
   `unregistered-checkpoint`, wrong hash -> `corrupt-checkpoint`, both
   rejected); S4 performs a real at-least-once redelivery absorbed by
   the dedup (`redeliveries`, never a second receipt); S2 unknown
   outcomes retry only after recorded reconciliation
   (`retry_after_unknown`, `reconciled_unknown_outcomes`).
   *Tests:* `CheckpointResumeTests`, `DeliveryDedupTests`,
   `ReconciliationTests`.

4. **Subprocess timeout escaped the fail-closed contract.** A timed-out
   subprocess raised `subprocess.TimeoutExpired` instead of stopping the
   pipeline as an error.
   *Fix:* `make_bundle.sh` converts timeouts to `SystemExit`.
   *Tests:* `ProvenanceTests.test_timeout_runner_rejected`.

5. **Test-suite hygiene.** A dead helper, duplicated `__main__` blocks
   and an evaluator call that fabricated raw observations
   (`raw_observations=[1]`) weakened the negative-mutation coverage.
   *Fix:* tests now drive the evaluator through injected
   `comparison_data`/`probes_data`/`manifest_data` parameters; comparison
   entries carry real `raw_observation_count` and `terminal_reason`;
   empty/absent observations fail closed.
   *Tests:* `SafetyCounterTests`,
   `MatrixIntegrityTests.test_complete_matrix_accepted`.

6. **Hard-safety/weights interaction made explicit.** A non-zero safety
   counter now aborts evaluation before any weighted scoring, so no
   weight vector can compensate a safety violation; unknown/NO_DATA
   dimensions are excluded for BOTH candidates (no side can gain an
   advantage from missing data) and recorded as limits.
   *Tests:* `SafetyCounterTests.
   test_hard_safety_failure_not_compensable_by_weights`,
   `UnknownPolicyTests`.

7. **Git porcelain status parsing stripped the leading status column.**
   `_git()` applied a global `.strip()` to `git status --porcelain`
   output, dropping the positional leading space of the FIRST line when
   it was a modified-file entry (` M path` -> `M path`); the research-
   surface filter then misparsed the path and wrongly flagged the tree
   dirty (or, in the opposite direction, could have masked a real
   modification). Committed evidence is unaffected (verified: at build
   time the first porcelain line was an untracked `??` research path,
   parsed correctly; `dirty=false` was accurate), but the parser is now
   positional-safe: raw lines via `_git_lines()` + tested
   `research_surface_dirty_lines()`.
   *Tests:* `ProvenanceTests.
   test_porcelain_first_line_modified_file_excluded`.

8. **Nonce-less evaluator invocations could clobber the published,
   nonce-bound sensitivity result.** `evaluator.py` main() always wrote
   `results/sensitivity-analysis.json`; a manual or test invocation
   without `AGENTOS_RUN_NONCE` silently replaced the published verdict
   with a nonce-less copy (observed once during this round and restored
   from git).
   *Fix:* the output location is an explicit `--out`; the published
   default stays for `make_bundle.py`, which enforces fresh nonce-bound
   writes. A guard test asserts the published file keeps its
   producer nonce.
   *Tests:* `PositiveFlowTests.
   test_published_sensitivity_stays_nonce_bound`.

## Result

46/46 regression tests green; corrective round R1 re-executes the full
pipeline on a clean committed tree: 90 main runs + 90 independent rerun
runs, probes A/B/C detected, sensitivity 222 runs with zero flips,
verdict `PASS_WITH_LIMITS` (recommendation: in_process), fresh research
revision and evidence chain published.
