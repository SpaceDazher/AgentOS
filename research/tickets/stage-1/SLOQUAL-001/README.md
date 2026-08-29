# SLOQUAL-001 — Production-like SLO qualification (extends S1-002)

Status: **COMPLETE · PASS_WITH_LIMITS** · Owner role:
`capacity` (co-owner `security` for the S1-008 gate) · Human threshold
countersignature: **PENDING**

## What this ticket is

S1-002 delivered a reproducible **local** SQLite benchmark (2 s trials,
single process). Its own `non_scope` forbids reading those numbers as
production SLOs. This ticket creates the *next*, separate qualification
package that:

1. freezes an SLO contract **before** any measurement (`slo-contract.json`
   v1.0.6, self-hashed; thresholds cannot change without a new version and a
   complete new run);
2. defines 17 mandatory scenarios in a versioned manifest
   (`scenario-manifest.json` v1.1.0);
3. executes them against the **real** AgentOS engine/gateway/journal with an
   open-loop load model (no coordinated omission), multi-process fault
   injection, and a durable capability ledger for the S1-008 revocation
   security gate;
4. evaluates everything through a fail-closed comparator
   (`agentos.sloqual.compare`) that can only emit `PASS`,
   `PASS_WITH_LIMITS`, or `FAIL` with itemized reasons;
5. requires an independent rerun under the same frozen contract before any
   full-PASS claim.

Relations: **extends S1-002** (supersedes nothing; historical S1-002 evidence
is read-only input). Security gate semantics from **S1-008** (revocation
≤5 s). S1-003 is intentionally untouched.

## Layout

| Path | Content |
|---|---|
| `slo-contract.json` | frozen SLO contract v1.0.6 (self-hash stamped) |
| `scenario-manifest.json` | versioned scenario definitions |
| `raw/<run-id>/` | per-scenario, per-seed raw results + environment manifest |
| `reports/` | `compare-result.json`, `REPORT.md` |
| `independent-rerun/` | rerun run-id reference + comparison note |
| `notes/` | Obsidian notes linking [[S1-002]] / [[S1-008]] |
| `artifact-manifest.json` | SHA-256 over every raw artifact |
| `bundle.json` | FLOW-11 research bundle for `research-plan` |

Harness code lives in `src/agentos/sloqual/` (stdlib-only; ADR-0010), unit
tests in `tests/test_sloqual_foundation.py` / `tests/test_sloqual_comparator.py`.

## Reproduce

```powershell
$env:PYTHONPATH = "src"
python -m agentos.sloqual.runner freeze-contract --ticket research/tickets/stage-1/SLOQUAL-001
python -m agentos.sloqual.runner env-manifest    --ticket research/tickets/stage-1/SLOQUAL-001 --repo-root . --work-root research/tickets/stage-1/SLOQUAL-001/raw
python -m agentos.sloqual.runner run-scenario    --ticket research/tickets/stage-1/SLOQUAL-001 --repo-src src --work-root research/tickets/stage-1/SLOQUAL-001/raw --run-id <run-id> --scenario warm_steady_state --seed 11
python -m agentos.sloqual.runner compare         --ticket research/tickets/stage-1/SLOQUAL-001 --repo-src src --work-root research/tickets/stage-1/SLOQUAL-001/raw --run-ids <main-run-id> <rerun-run-id>
python -m agentos.sloqual.runner report          --ticket research/tickets/stage-1/SLOQUAL-001
```

Full-scale long scenarios (sustained ≥6 h, soak ≥24 h) are explicit runner
invocations with duration overrides; they are never part of the unit suite.

## Honest-verdict rule

`PASS` requires every registered proof including a production-like profile,
full-scale long scenarios, ≥100 revocation trials ≤5 s each, zero
security/correctness violations, verified hashes, and a consistent
independent rerun. Anything less is `PASS_WITH_LIMITS` with the missing
proofs itemized by the comparator; any invariant or security violation is
`FAIL`. See `reports/REPORT.md` for the current outcome.

## Current outcome

The authoritative qualification under contract v1.0.6, scenario manifest
v1.1.0, and runner/comparator v2.1.1 is complete. Runs
`sloqual-final-a13-20260828` and
`sloqual-final-b12-20260828-execB` each contain 17 scenarios × 5 seeds and
105 revocation trials, all stamped with implementation commit `af57638`.

The fail-closed comparator reports `PASS_WITH_LIMITS`: zero hard failures,
zero mandatory security/correctness violations, burst p95 **21.744 ms**
against 200 ms, and S1-008 maximum **1444.849 ms** against 5000 ms with zero
forbidden post-revoke effects. Full `PASS` remains blocked by the warm p95
confidence interval crossing 20 ms, insufficient power in three fault/soak
scenario families, pilot durations and DB scale, absent production-profile
mapping, pending human SLO ownership, and same-host rather than external
independent execution. The exact 41 limits are in `reports/REPORT.md`.
