# S1-007 corrective review R2

Reviewed HEAD: `d49ea483f0d6c80c514919d5fb0e4146204451bb`.

Verdict: **REVISE**. Do not push and do not treat S1-007 as closed.

The targeted and full regression suites are green, the 168 tracked run
records are internally hash-consistent, and the content-addressed pack and raw
archive files match the SHA-256 values written in `evaluation-record.json`.
However, four P1 evidence/scoring paths remain open.

## Findings

### 1. [P1] Evaluation record disagrees with the canonical chain

`evaluation-record.json` records:

```text
d44a4e1074c3a7452c90ee4fbd5fdd2eb0a9eaa4a24bc26ed09641e16b34d477
```

The canonical `research_evaluation` row and the evaluation embedded in the
tracked evidence pack both contain:

```text
d44a4e1074c3a7454878a7fd0307fcf450285170a5879eea0e5f0b6bcefcad7d
```

Only the abbreviated prefix `d44a4e10...` agrees. The full values differ, so
the published evaluation record is not consistent with canonical state even
though it claims `chain_fresh=true`.

Required correction: populate the full hash from canonical state, verify exact
record/DB/pack equality, and add a regression test that compares all 64 hex
characters rather than an abbreviated display value.

### 2. [P1] The raw-observation archive is outside the evidence chain

`make_bundle.py` creates the tracked archive
`raw-observations-4fbaaee6...json`, but then calls
`bundle_content.build(gate, evaluation, probe_evidence, provenance)` without
passing the archive path or digest. Neither `bundle.json` nor the evidence pack
contains the archive SHA-256 or `raw-observations` reference.

The only link is in the separately tracked `evaluation-record.json`; that
record is not itself part of the canonical pack payload. This does not satisfy
the R1 correction requirement to bind the lossless raw archive into the pack.

Required correction: make the archive an explicit hash-verified input to the
bundle, carry its path/SHA/member count into a canonical research artifact or
equivalent pack field, then produce a new revision and pack. The clean-clone
test must assert that the pack itself contains the archive digest, not only
that `evaluation-record.json` points to it.

### 3. [P1] D10 rewards higher measured cost

The implementation says lower cost must score higher, but calculates:

```python
storage_score = 4.0 * bytes_v[variant] / max_bytes
scan_score = 4.0 * scans_v[variant] / max_scans
```

This gives the most expensive value on each component the maximum score. The
published cells are therefore reversed relative to their stated semantics:

```text
per_scope:  1388 B,  51 rows scanned -> D10 2.9714
shared_rls:  876 B, 105 rows scanned -> D10 3.2622
```

`evaluation-record.json` nevertheless claims that the costlier variant scores
strictly lower. The current regression test checks only that the two D10 scores
differ; it does not verify their direction.

Required correction: freeze an explicit lower-cost-higher normalization,
assert direction independently for storage and scan inputs, and regenerate the
matrix, totals, sensitivity analysis, bundle and evidence revision. A simple
inverse normalization would preserve the selected winner but change the
published quantitative scores; the exact rule must be fixed in the contract
before regeneration.

### 4. [P1] Timing evaluator trusts producer-derived differences

`recompute_timing()` reads `paired_diffs_ns` and `control_samples_ns`, but does
not require `foreign_samples_ns` and does not verify that each paired
difference equals `foreign - control`.

Observed adversarial probe:

```text
foreign_samples_ns := control_samples_ns + 1,000,000
paired_diffs_ns    := all zero
result             := WITHIN_TOLERANCE

foreign_samples_ns removed entirely
result             := WITHIN_TOLERANCE
```

Thus a producer-controlled derived array can suppress a real signal while the
evaluator reports that it recomputed the result from raw paired samples.
Hash-binding the inconsistent file does not validate its semantics.

Required correction: require equal-length foreign/control arrays with the
exact frozen sample count, derive all differences inside the evaluator, reject
any supplied derived array that disagrees, and add both inconsistency and
missing-arm regression tests.

### 5. [P2] Wiki verification counts are missing from the record

The live check returned:

```text
files=2507, links_checked=6733, issues=[], ok=true
```

`evaluation-record.json` stores `files: null` and `links_checked: null`.

Required correction: record the observed counts produced by the successful
command in the next evaluation record.

## Independently verified evidence

```text
py -3.12 -m unittest tests.test_s1_007_regressions -v
  -> 40 tests OK

py -3.12 -m unittest discover -s tests
  -> 507 tests OK, 1 skipped

py -3.12 -m evals.gen_fixtures --check
  -> 78 checked, 0 violations

$env:PYTHONPATH='src'; py -3.12 -m agentos.cli wiki-check \
  --db .agentos-research/platform-stage-1
  -> ok=true, files=2507, links_checked=6733, issues=[]

py -3.12 research/tickets/stage-1/S1-007/dependency_gate.py
  -> S1-003 and S1-005 PROVEN

raw run verification
  -> 168/168 manifest member hashes match tracked files

git diff --check
  -> exit 0

git status --short
  -> clean before this review file was added
```

The evidence-pack file SHA and payload SHA are internally valid, and the raw
archive file SHA matches its content-addressed filename and evaluation-record
entry. Those facts do not close the chain-binding, score-direction or timing
semantic gaps above.

## Required corrective round

1. Repair the full chain hash in the record and test exact DB/pack/record
   equality.
2. Bind the raw archive SHA into the bundle and canonical evidence pack.
3. Correct and freeze D10 direction; regenerate all derived results.
4. Derive timing differences from both required raw timing arms and reject
   inconsistent inputs.
5. Record the actual wiki counts.
6. Add adversarial regression tests for every reproduction above.
7. Run the experiment/evaluator pipeline on a clean frozen commit, publish a
   new research revision and evidence pack, then rerun the full verification
   set.

