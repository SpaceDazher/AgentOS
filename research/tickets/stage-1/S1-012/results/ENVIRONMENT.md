# S1-012 execution environment (Phase A)

- OS: Windows-11-10.0.22631-SP0 (Windows host, PowerShell)
- Python: 3.12.6 (`py -3.12`), stdlib only for all ticket tooling
- `$env:PYTHONPATH = "src"` (repo-root convention; ticket scripts need no PYTHONPATH)
- Commit: `f43217c53b89` (measurement commit; all 24 cells agree)
- Tree: single tree shared by all 24 cells (see comparison.json)
- Clean tree: true for every cell (verified per-manifest)
- Corpus: 60 cases (40 dev + 20 holdout, lineage-isolated) x 4 variants
  (document/span/digest/reputation-only) x 3 seeds = 720 rows per run
- Seeds (frozen, corpus-manifest.json): 12012, 22022, 33033
- Contracts: evidence-unit.schema, independence-contract, threat-model,
  calibration-plan, rubric (frozen pre-run; Beta references verified
  before freeze)
- Line endings: LF for all generated ticket files (newline="\n");
  snapshots are byte-frozen and untouched

## Run commands (each a separate process; 24 runner PIDs + 24 evaluator PIDs)

Run A (12 processes; run B identical with run-b roots):

```powershell
py -3.12 research/tickets/stage-1/S1-012/runner.py --variant document --seed 12012 --out <stage>/run-a/document-12012
py -3.12 research/tickets/stage-1/S1-012/runner.py --variant document --seed 22022 --out <stage>/run-a/document-22022
py -3.12 research/tickets/stage-1/S1-012/runner.py --variant document --seed 33033 --out <stage>/run-a/document-33033
# ... same for span, digest, reputation-only with seeds 12012/22022/33033
```

Evaluation (per cell, 24 processes):

```powershell
py -3.12 research/tickets/stage-1/S1-012/evaluator.py --run <cell> --out <cell>/metrics.json --probes <cell>/probes.json
```

Comparison + joint sensitivity + merged metrics/probes:

```powershell
py -3.12 research/tickets/stage-1/S1-012/compare_runs.py --a <stage>/run-a --b <stage>/run-b --out <stage>/comparison.json --sensitivity <stage>/sensitivity.json --metrics <stage>/metrics.json --probes <stage>/probes.json
```

Bundle + candidate record (verdict re-derived from tracked raw cells,
refuses on blockers):

```powershell
py -3.12 research/tickets/stage-1/S1-012/make_bundle.py
```

## Staging and import (corrected record)

`<stage>` was a temp dir outside the repo: writing cell outputs
directly into the worktree would have made later cells record
`clean_tree=false`, breaking the same-clean-tree requirement. After
verification, the staging tree was copied into
`research/tickets/stage-1/S1-012/results/` with robocopy and verified
byte-for-byte plus `git ls-files` count (24 cells x 4 files + 4 merged
files + 5 docs = 105 tracked files under results/). An earlier import
attempt with PowerShell `Copy-Item` silently produced empty trees and
was caught by the ls-files check; the false "copied verbatim" claim
from that attempt is retracted here (see corrective-log.md items 6-7).
Manifest `output_root` values still point at the staging paths by
design: they record where the bytes were produced.

## Determinism notes

- Runner/evaluator/compare/canonicalizer: stdlib only, sorted keys,
  no wall-clock inside rows (manifest carries PID/UUID/nonce only).
- Outputs are seed-invariant by construction; the evaluator re-checks
  the exact matrix per cell and the comparison re-checks A/B identity
  (720/720 identical rows).
- Sensitivity grid (135 prior/decay/threshold/cap combos) executes the
  real decision core in-process; thresholds were chosen on dev, holdout
  metrics reported separately per split.
- No network, no LLM, no canonical DB in any step. Missing canonical DB
  in this worktree is expected per the task (Phase B rechecks live DB).

## Input hashes (pinned at run time; see corpus-manifest.json)

Recorded per-manifest under `input_hashes` for all 16 frozen inputs:
cases.json, cases-dev/holdout.src.json, evidence-unit.schema.json,
independence-contract.json, threat-model.json, calibration-plan.json,
rubric.json, source-registry.json, retrieval-manifest.json,
split-manifest.json, corpus-manifest.json, runner.py, evaluator.py,
compare_runs.py, dependency_gate.py, canonicalize_corpus.py,
make_bundle.py.
