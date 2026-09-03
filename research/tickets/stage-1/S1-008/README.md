# S1-008 — Revocation latency validation (≤5 seconds)

Deterministic, stdlib-only revocation probe over the **real AgentOS approval
state machine** (gateway grant/revoke/consume + hash-chained journal), answering
the ticket RQ on the bounded single-host path:

> Can the platform enforce that new authorization decisions observe revocation
> within ≤5 seconds across gateway, retrieval, delegation, and cached
> projections?

## Files
- `revocation_probe.py` — the executable probe: 34 revoke-to-deny traces across
  gateway/retrieval/delegation (cold + warm cache, outage/unknown cases), plus
  the two adversarial probes:
  1. **cached-auth-after-revoke** — revoke immediately before a cached
     authorization check; asserts no allow after the bound and that clock
     assumptions are surfaced (measured, not silent).
  2. **dropped-hop** — drops one propagation hop → unknown; asserts deny or
     reconciliation, never a silent allow.
- `probe-results.json` — committed full-run verdict + per-trace records (34
  traces, all ≤5 s) and clock-assumption fields.
- `bundle.json` — FLOW-11 research bundle (13 verified sources, 12 claims,
  11 artifacts, independent audit, 3 probes).

## Run
```powershell
$env:PYTHONPATH = "src"
# full trace run (writes probe-results.json):
python research/tickets/stage-1/S1-008/revocation_probe.py
# focused adversarial probes:
python research/tickets/stage-1/S1-008/revocation_probe.py cached-revoke
python research/tickets/stage-1/S1-008/revocation_probe.py dropped-hop

# research-plan validation:
python -m agentos.cli research-plan `
  --topic "S1-008 revocation latency validation at most 5 seconds" `
  --bundle "research/tickets/stage-1/S1-008/bundle.json" `
  --db ".agentos-research/platform-stage-1"
```

## Results (committed run, seed 20260902)
- **34 traces** across gateway/retrieval/delegation, cold + warm cache, plus
  `outage_unknown` / `outage_reconcile` cases.
- All revoke-to-deny latencies **≤ 5 s** (observed max ~2.4 ms, p95 ~2.2 ms on
  this single-host SQLite/WAL control plane).
- Both adversarial probes pass; every unknown/outage trace ends in explicit
  deny or reconciliation; INV5 revocation monotonicity holds.
- Research-plan status: **pass_with_limits**.

## Boundary (honest limits)
Single-host SQLite/WAL control plane (S1-002/S1-005 boundary). Retrieval and
delegation propagation hops are modeled in-process over the real authoritative
store with measured per-hop latency; a real multi-host hop, cross-host clock
skew, and NTP/TrueTime-style uncertainty are **not** measured and are out of
scope. The ≤5 s value is a **bounded research target, not a production SLA**.
