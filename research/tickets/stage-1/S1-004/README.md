# S1-004 — Alloy/TLA+ and seeded deterministic invariant simulation

Deterministic stdlib-only Python simulation of the AgentOS envelope
(INV1–INV6, outbox delivery, fencing, effect receipts, reconciliation, crash
recovery).

## Files
- `invariant_simulation.py` — the simulation + adversarial probes (seeded,
  deterministic; same seed/ops reproduce byte-identical counters).
- `probe-results.json` — probe verdict at 3 seeds × 200,000 ops (pass, 0
  violations; matches the research-plan bounded probe).
- `acceptance-run-1m.json` — full acceptance run at 3 seeds × 1,000,000 ops
  (acceptance criterion; committed artifact).
- `bundle.json` — FLOW-11 research bundle (7 verified sources, 10 claims,
  11 artifacts, 2 probes).
- `evaluation-record.json` — ticket evaluation record.

## Run
```powershell
$env:PYTHONPATH = "src"
# bounded probe (CI, < 120 s):
python research/tickets/stage-1/S1-004/invariant_simulation.py 200000
# acceptance run (1,000,000 ops per seed):
python research/tickets/stage-1/S1-004/invariant_simulation.py 1000000
```

## Review-fix (2026-08-31)
Two fail-open model bugs were found and fixed: CRASH-B (unknown outcome)
effects stayed in the outbox (later replay executed the sink twice → spurious
SAF duplicate) and were never receipted at end-of-seed. Now CRASH-B = sink
executed exactly once + single receipt + reconciliation, never replay.