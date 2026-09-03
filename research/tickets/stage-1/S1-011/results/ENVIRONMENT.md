# S1-011 execution environment (Phase A)

- OS: Windows-11-10.0.22631-SP0 (Windows host, PowerShell)
- Python: 3.12.6 (`py -3.12`), stdlib only for all ticket tooling
- `$env:PYTHONPATH = "src"` (repo-root convention; ticket scripts need no PYTHONPATH)
- Commit: `2b64743c362a01f509fac3a110b9a50d065173de`
- Tree: `beb512200e4aa286caea07312e47a22d09130b06` (same for all 18 cells)
- Clean tree: true for every cell (verified per-manifest)
- Corpus: 60 cases x 3 designs x 3 seeds = 540 rows per run
- Seeds (frozen, corpus-manifest.json): 11011, 22022, 33033

## Run commands (each a separate process; 18 runner PIDs + 18 evaluator PIDs)

Run A (9 processes):

```powershell
py -3.12 research/tickets/stage-1/S1-011/runner.py --design minimal-gate --seed 11011 --out <stage>/run-a/minimal-gate-11011
py -3.12 research/tickets/stage-1/S1-011/runner.py --design minimal-gate --seed 22022 --out <stage>/run-a/minimal-gate-22022
py -3.12 research/tickets/stage-1/S1-011/runner.py --design minimal-gate --seed 33033 --out <stage>/run-a/minimal-gate-33033
py -3.12 research/tickets/stage-1/S1-011/runner.py --design argumentation --seed 11011 --out <stage>/run-a/argumentation-11011
py -3.12 research/tickets/stage-1/S1-011/runner.py --design argumentation --seed 22022 --out <stage>/run-a/argumentation-22022
py -3.12 research/tickets/stage-1/S1-011/runner.py --design argumentation --seed 33033 --out <stage>/run-a/argumentation-33033
py -3.12 research/tickets/stage-1/S1-011/runner.py --design tms --seed 11011 --out <stage>/run-a/tms-11011
py -3.12 research/tickets/stage-1/S1-011/runner.py --design tms --seed 22022 --out <stage>/run-a/tms-22022
py -3.12 research/tickets/stage-1/S1-011/runner.py --design tms --seed 33033 --out <stage>/run-a/tms-33033
```

Run B: identical with `--out <stage>/run-b/<design>-<seed>` (9 more processes).

Evaluation (per cell, 18 processes):

```powershell
py -3.12 research/tickets/stage-1/S1-011/evaluator.py --run <cell> --out <cell>/metrics.json --probes <cell>/probes.json
```

Comparison + sensitivity + merged metrics/probes:

```powershell
py -3.12 research/tickets/stage-1/S1-011/compare_runs.py --a <stage>/run-a --b <stage>/run-b --out <stage>/comparison.json --sensitivity <stage>/sensitivity.json --metrics <stage>/metrics.json --probes <stage>/probes.json
```

## Staging note (provenance-relevant)

`<stage>` was `C:\Users\Daniil\AppData\Local\Temp\opencode\s1-011-runs`
(a temp dir outside the repo). Reason: writing 9 cell outputs directly
into the worktree would have made cells 2-9 record `clean_tree=false`
(their siblings' outputs dirty the tree), breaking the same-clean-tree
requirement. All 18 manifests therefore record one commit, one tree,
`clean_tree=true`, distinct PID/PPID/invocation_id/nonce/executor_id and
distinct output roots. After verification, the staging tree was copied
verbatim to `research/tickets/stage-1/S1-011/results/`. Manifest
`output_root` values still point at the staging paths by design: they
record where the bytes were produced.

## Determinism notes

- Runner/evaluator/compare/canonicalizer: stdlib only, sorted keys,
  no wall-clock inside rows (manifest carries PID/UUID/nonce only).
- Outputs are seed-invariant by construction; the evaluator re-checks
  the exact matrix per cell and the comparison re-checks A/B identity
  (540/540 identical rows expected for deterministic designs).
- No network, no LLM, no canonical DB in any step. Missing canonical DB
  in this worktree is expected per the task (Phase B rechecks live DB).

## Input hashes (pinned at run time; see corpus-manifest.json)

Recorded per-manifest under `input_hashes` for: cases.json,
knowledge-gate-contract.json, state-machine.json, rubric.json,
design-alternatives.json, knowledge-record.schema.json,
source-registry.json, runner.py, evaluator.py.
