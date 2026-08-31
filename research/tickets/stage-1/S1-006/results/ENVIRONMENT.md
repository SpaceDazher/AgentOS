# S1-006 — Environment, commands, and provenance (R2)

Ticket: QA2 execution backend — in-process scheduler versus a
provider-neutral durable-execution engine.

## Runtime and frozen execution identity

- Python 3.12.6; S1-006 tooling is stdlib-only.
- Same Windows host as S1-002/S1-005; canonical DB root:
  `.agentos-research/platform-stage-1`.
- Final experiment commit:
  `30cdd80d8b47168522248fac5516cc7f773a018a`.
- Final experiment tree:
  `abc0d9f26b5dc3e8603988fd76955a17a7a4a193`.
- run-a executor: `agentos-s1-006-producer`; run-b executor:
  `agentos-s1-006-independent-verifier`; both recorded `dirty=false`.
- Every evidence script records both its executed disk-byte SHA-256 and
  commit-blob SHA-256. The evaluator re-resolves the commit tree and checks
  the exact required script set.

## Reproduction

```powershell
py -3.12 research/tickets/stage-1/S1-006/dependency_gate.py
py -3.12 research/tickets/stage-1/S1-006/make_bundle.py
py -3.12 -m unittest tests.test_s1_006_regressions -v
$env:PYTHONPATH = "src"
py -3.12 -m agentos.cli research-plan --topic "S1-006 QA2 execution backend in process versus durable engine" --bundle "research/tickets/stage-1/S1-006/bundle.json" --db ".agentos-research/platform-stage-1"
py -3.12 -m agentos.cli wiki-check --db ".agentos-research/platform-stage-1"
```

Observed before publication: dependency gate exit 0; bundle pipeline exit 0;
68/68 S1-006 regression tests; research-plan exit 0 with
`pass_with_limits`; wiki check `ok=true` (2378 files, 6430 links).

## Evidence authority

- run-a manifest SHA-256:
  `a846abeb0df4bc0518a9691cb91ed23b97bb8c56ba3483e29197502b866fb4af`.
- digest-bound probes SHA-256:
  `234a0bb36186b01dae9bde2fc12fe4941f44f23e31083938989c63ca3d1cd8dc`.
- 90 run-a + 90 run-b records. The evaluator loads only files named by
  each manifest, verifies their SHA-256, derives counters/latency/throughput/
  queue depth from raw observations and ledgers, then requires the saved
  comparison projection to equal the derived comparison.
- Rerun result: identical verdict; all normalized-score and metric deltas
  are 0, below the frozen 0.01 tolerances.
- Sensitivity: 22 per-dimension perturbations + 200 seeded integer
  compositions = 222; zero flips and zero ties.

## Scenario semantics

- S1: atomic transition/outbox commit is recorded before coordinator crash;
  pending delivery is replayed after recovery.
- S2: every seed contains a deterministic unknown-outcome injection, and
  every such decision has reconciliation evidence before retry.
- S3: a registered content hash is verified; resume creates a distinct new
  run with `resumed_from_run_id` and no completed-step re-execution.
- S4: duplicate delivery reaches the gateway, is absorbed by dedup, and a
  stale lower fencing token is explicitly rejected.
- Probe A produces a real second effect and receipt; probe C records actual
  blind retries; probe B carries a divergent workload hash.
- Repeated 12-task DAG instances are dependency-valid. Low/nominal are
  planning-envelope loads; high (20,000/s) is an explicit same-host
  saturation probe that produces measurable queue pressure.

## Result and limits

Derived score: in-process 3.88 versus modeled durable engine 3.20.
Verdict: `PASS_WITH_LIMITS`. No production SLO, vendor-engine, multi-host,
or external-auditor claim is made.
