# S1-007 — REVIEW_R1

Reviewed HEAD: `9142905c9248ac826b45bdf496d021275790de42`.

Verdict: **REVISE**. Do not push and do not treat S1-007 as closed.

The canonical chain and the published pack are internally bound, and the
existing test suite is green. However, the decision/evidence pipeline still
contains fail-open paths. In particular, the exact raw observations are not
available from Git, the per-variant decision matrix is calculated
incorrectly, and producer-controlled timing/probe/provenance fields can be
accepted without the required independent reconstruction.

## Findings

### 1. [P1] Exact raw evidence is absent from Git

The two result directories contain 168 JSON run files on the review host:

- 84 main runs under `results/run-a/runs/`;
- 84 rerun records under `results/run-b/runs/`.

None is tracked. The global `.gitignore` entry `runs/` excludes every one of
them. Only the two manifests and timing summaries are committed. The
content-addressed evidence pack does not embed the run manifests or any raw
run file either.

Observed probe:

```text
disk_raw=168
tracked_raw=0
.gitignore:7:runs/
pack contains run-manifest ref: false
pack contains raw-run ref: false
```

A clean-clone auditor can generate a new series, but cannot verify the exact
observations from which revision 1 and its score were produced. This violates
the ticket requirement that evaluator/results be reproducible and
SHA-verifiable from a clean clone.

Required correction: track the exact raw runs, or publish an equivalent
content-addressed raw archive/index whose member hashes and bytes are bound to
both manifests and the evidence pack. Add a clean-clone verification probe.

### 2. [P1] Per-variant decision scores overwrite each other

In `evaluator.py`, `score_dimensions()` iterates over `per_scope` and
`shared_rls`, but `measured()` stores each result only as
`cells[weight_id]`. The second iteration overwrites the first. When the final
matrix is built, D1-D7 for both variants therefore use the shared-RLS score
and evidence references.

Observed evidence:

```text
D6 per_scope score:  3.25
D6 shared_rls score: 3.25

Both cells reference:
fault:shared_rls:{"corrupt_entry_affected_scopes":1,
                  "predicate_bypass_affected_scopes":2}
```

The actual probe data distinguishes a one-scope per-scope failure from a
two-scope shared-predicate failure, but the scoring path discards that
difference. D1 for `per_scope` likewise cites only `shared_rls` ISO and timing
refs. D10 also applies a symmetric `min/max` ratio to both variants and thus
cannot reward the variant with lower measured storage or scan cost.

Consequently, the published `3.7183 versus 3.5483` comparison and its
recommendation are not supported by the claimed per-variant calculation.

Required correction: store cells by `(dimension, variant)`, make D10
directional or explicitly non-scoring, add asymmetric regression fixtures,
and regenerate the matrix and sensitivity result from corrected scores.

### 3. [P1] Timing analysis trusts producer summaries

`analyze_timing()` reads producer-supplied `median_paired_diff_ns`,
`tolerance_ns`, `pooled_samples`, `per_seed`, and `verdict`. It does not
receive raw paired samples and does not independently recompute the statistic
or tolerance from the frozen contract.

Observed adversarial mutation:

```text
per_seed = []
pooled_paired_diffs_ns = [999999999]
stored median_paired_diff_ns = 6
stored verdict = WITHIN_TOLERANCE

evaluator result: WITHIN_TOLERANCE
```

The main timing file is digest-checked, but the digest is supplied by the same
runner. The rerun timing file is loaded without verifying its
`timing_sha256`, and the rerun value is only included in a note; it does not
participate in an independently derived timing verdict.

The runner also drops all paired samples after computing summaries. Its
relative tolerance component is never used because `control_median` is set to
`None`, making the effective tolerance the fixed absolute floor.

Required correction: preserve raw paired observations for both executions,
hash-bind both timing artifacts, validate exact seeds/sample count/order, and
recompute control median, pooled statistic, tolerance, and verdict inside the
evaluator.

### 4. [P1] FLOW-11 records a methodology that was not executed

The frozen contract and runner use:

```text
sample_count:       200
inner_repeats:      32
absolute_floor_ns:  2000
statistic:          pooled median of paired interleaved differences
```

`bundle_content.py` and the resulting `bundle.json` claim:

```text
inner_repeats:      8
absolute_floor_ns:  1000
statistic:          median-of-seed-medians
```

The canonical chain is cryptographically consistent with the bundle bytes,
but the bound content describes a different experiment. Correcting this is a
substantive evidence change and requires a new research revision, evaluation,
chain, pack, and evaluation record.

### 5. [P1] Script provenance validation is fail-open

`validate_provenance()` iterates only over the supplied `script_hashes`
mapping. It does not require the exact `EVIDENCE_SCRIPTS` set, and it never
validates `script_blob_hashes` against the recorded commit.

Observed adversarial mutation:

```text
script_hashes = {}
script_blob_hashes = {}
validate_provenance(...) -> accepted
```

The recorded manifest also contains different disk/blob hashes for
`bundle_content.py`:

```text
disk: 08428e053e896ef6669bbe519b683d24c2a5cb0be4bce12d83e57e7213788949
blob: b45634c2e270a6ced1c270302ea704c9704b31e23257ef1a39cef5fb78745ca3
```

This may be caused by checkout normalization, but the current checker neither
explains nor verifies it, so the claimed commit provenance remains
non-portable and incomplete.

Required correction: require exact script key sets, check every Git command
return code, validate commit blobs directly, define any line-ending
normalization explicitly, and reject missing/extra/mismatched entries.

### 6. [P1] Probe labels are not bound to their exact semantics

`evaluate_probes()` trusts each supplied `probe` label and only checks whether
the attached runs produce a suitable ISO counter. It does not require the
exact A/B/C/D set and does not bind a probe to its frozen class, cases, seeds,
run IDs, or `probe_hashes` entry.

Observed adversarial mutation:

```text
Probe C post-filter runs relabelled as A_existence_oracle
evaluator result: A detected as FAIL
```

This accepts a post-filter counterexample as proof that the object-existence
oracle was actually exercised.

Required correction: freeze and verify the exact probe matrix, candidate
identity, cases, seeds and run IDs; reject missing, extra, duplicated or
relabelled probes before evaluating their counters.

### 7. [P2] Sensitivity claims are arithmetically and semantically inaccurate

The implementation performs two one-at-a-time factors for every one of 11
dimensions, plus 200 random vectors:

```text
11 * 2 + 200 = 222
```

The bundle, evaluation record and ticket docs claim 212 perturbations and
describe only 11 one-at-a-time perturbations. The bundle also claims unknown
bounds are swung, while `sensitivity_analysis()` only varies weights.

Required correction: derive and store the executed count, record every tested
vector or a deterministic reconstruction manifest, either implement frozen
unknown-bound analysis or remove the claim, and update all generated text.

## Evidence that did pass review

The following claims were independently reproduced at HEAD:

- tracked pack file SHA matches the evaluation record;
- pack payload self-hash matches both pack and record;
- goal/campaign/evaluation/result/chain fields match the canonical DB;
- `chain_fresh=true` and `latest_evaluation_valid=true` are recorded;
- `py -3.12 -m unittest tests.test_s1_007_regressions -v`:
  33 tests, exit 0;
- `py -3.12 -m unittest discover -s tests`:
  500 tests, 1 skipped, exit 0;
- `py -3.12 -m evals.gen_fixtures --check`:
  78 checked, 0 violations;
- `wiki-check --db .agentos-research/platform-stage-1`:
  `ok=true`, 2421 files, 6531 links;
- `git diff --check`: exit 0;
- `git status --short`: clean before adding this review file.

These green checks show that the existing tests are stable; they do not close
the uncovered evaluator and reproducibility gaps above.

## Required corrective round

1. Preserve and track the exact raw run/timing evidence, or a
   content-addressed lossless equivalent, and bind it into the pack.
2. Fix per-variant score storage and directional D10 semantics.
3. Recompute timing only from raw hash-bound observations for both runs.
4. Enforce the exact script/blob provenance set.
5. Enforce the exact probe matrix and reject relabelling.
6. Correct sensitivity execution/count/claims.
7. Add one regression test for every reproduction in this review.
8. Run the main series and independent rerun again on a clean frozen commit.
9. Regenerate FLOW-11, run `research-plan`, publish a new tracked pack and
   evaluation record under a new research revision.
10. Re-run targeted/full tests, corpus, wiki, dependency gate,
    `git diff --check`, and a clean-clone evidence verification.

S1-007 may return to `PASS_WITH_LIMITS` only after all P1 findings are closed
with observed evidence. The existing honest limitations remain valid: local
model only, no production/privacy certification, timing cannot prove absence
of all side channels, D9/D11 remain inference, profile C belongs to S1-018,
and the revocation SLO belongs to S1-008.
