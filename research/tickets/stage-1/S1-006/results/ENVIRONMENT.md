# S1-006 — Environment, commands, and provenance

Ticket: `research/tickets/stage-1/S1-006` — QA2 execution backend:
in-process scheduler versus durable-execution engine (provider-neutral).

## Runtime

- Python 3.12.6, stdlib only for all research tooling (no new Core AgentOS
  dependencies).
- Same host as S1-002/S1-005 measurements; canonical DB root
  `.agentos-research/platform-stage-1`.

## Dependency gate (executed before research)

```powershell
py research/tickets/stage-1/S1-006/dependency_gate.py
```

- exit 0; S1-002 (rev 1, pass_with_limits) and S1-005 (rev 7,
  pass_with_limits) verified against the canonical DB, tracked evidence
  packs, file/payload SHA-256 and docs status.
- Inherited limits carried into S1-006: S1-002 is not a production SLO;
  S1-005 measurements are same-host and bounded, not multi-host/container
  reliability.

## Simulation chain (deterministic, stdlib-only)

```powershell
py research/tickets/stage-1/S1-006/runner.py --mode main   --out research/tickets/stage-1/S1-006/results/run-a
py research/tickets/stage-1/S1-006/runner.py --mode rerun  --out research/tickets/stage-1/S1-006/results/run-b
py research/tickets/stage-1/S1-006/runner.py --mode probes --out research/tickets/stage-1/S1-006/results
py research/tickets/stage-1/S1-006/evaluator.py --runs-manifest research/tickets/stage-1/S1-006/results/run-a/run-manifest.json --runs-manifest-sha <sha>
py research/tickets/stage-1/S1-006/make_bundle.py
```

- The runner is a discrete-event deterministic simulator over the frozen
  backend contract: both backends implement identical AgentOS semantics
  (atomic transition+audit/outbox, gateway-only effects, reconciliation
  for unknown outcomes, lease/fencing, checkpoint-hash resume,
  deduplicated at-least-once delivery) and differ only in measured cost
  parameters (S1-005 E1/E2) and crash blast radius.
- run matrix: 2 backends x 3 loads x 3 seeds = 18 throughput runs plus
  4 crash/replay scenarios x 3 loads x 3 seeds x 2 backends = 72 scenario
  runs; 90 runs per executor, 90 more in the independent rerun.
- Observed semantics per scenario run: S3 checkpoint resumes are executed
  only through the registered, content-hash-verified `CheckpointStore`
  (recorded in `resumes`); S4 lease expiry performs a real at-least-once
  redelivery absorbed by the local dedup (recorded in `redeliveries`,
  never a second receipt); S2 unknown outcomes enter reconciliation and
  are retried only after recorded resolution (`reconciled_unknown_outcomes`).
- Model-based metrics come from measured parameters (S1-005 E1 dispatch
  4.86/25.71 us; E2 SQLite 20,587 tx/s single vs 1,694 tx/s multi-writer);
  they are research measurements, not production SLO claims.

## Fail-closed rules encoded in the pipeline

- dependency gate: any pack/record/DB/docs divergence -> BLOCKED;
- runner: non-zero exit, timeout, missing output file -> failure;
- evaluator: run-matrix divergence (missing/extra/duplicate), hash
  divergence vs frozen contract/workload/rubric, safety-counter key set
  mismatch, non-zero safety counter, empty raw observations, missing
  terminal reason, dirty working tree, expected-commit mismatch, mixed
  commit/tree provenance across compared runs, undetected probe ->
  FAIL/error exit;
- make_bundle: runs the evaluator and experiments as subprocesses and
  requires exit 0 (timeouts are converted to failures), fresh
  nonce-bound evaluator output, and schema-correct results; the bundle
  verdict is derived, never hardcoded;
- independent rerun: `run-b` is produced by a separate runner process in
  a separate output directory; safety verdicts must match run-a and
  latency deltas stay within the frozen 2x tolerance.
