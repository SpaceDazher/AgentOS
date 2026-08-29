# SLOQUAL-001 — Production-like SLO qualification report

Contract version: `1.0.6` · frozen at `2026-08-28T15:33:00Z` · self-hash `4a660709fa06b9b9…`

## Verdict: **PASS_WITH_LIMITS**

Runs compared: `sloqual-final-a13-20260828`, `sloqual-final-b12-20260828-execB`

## SLO table

| SLI | Scope | Threshold | Observed | 95% CI | Verdict |
|---|---|---|---|---|---|
| `latency_end_to_end_ms.p95` | warm_steady_state@nominal | <=20.0 ms | 5.315288 | [4.875928, 26.149678] | CI_CROSSES_THRESHOLD |
| `throughput_realization_fraction` | warm_steady_state@nominal | >=0.999 | 1.0 | [0.9992473397044779, 1.0] | PASS_CANDIDATE |
| `availability_fraction` | all non-injected windows | >=0.999 | 1.0 | [0.999896723432781, 1.0] | PASS_CANDIDATE |
| `error_rate_fraction` | all non-injected windows | <=0.01 | 0.0 | [6.776263578034403e-21, 0.00010327656721913339] | PASS_CANDIDATE |
| `latency_end_to_end_ms.p95` | burst@phase_burst | <=200.0 ms | 21.743948 | [20.922722, 27.286767] | PASS_CANDIDATE |
| `recovery_time_seconds` | worker_restart|scheduler_restart|full_restart|network_faults|provider_*|sqlite_lock_contention|disk_slow_saturation | <=30.0 s | 0.174818 | [0.028407, 0.623298] | PASS_CANDIDATE |
| `db_transaction_latency_ms.p95` | warm_steady_state@nominal | <=10.0 ms | 0.9444 | [0.7798, 2.6434] | PASS_CANDIDATE |
| `audit_journal_latency_ms.p95` | warm_steady_state@nominal | <=10.0 ms | 0.0214 | [0.0202, 0.0286] | PASS_CANDIDATE |
| `revocation_enforcement_latency_ms` | revocation_under_load, all trials | <=5000.0 ms for EVERY observed trial (max) | 55.635 | [23.461, 1444.849] | PASS_CANDIDATE |

## S1-008 revocation security gate

- trials (main run): **105** (minimum 100)
- trials by run: **{'sloqual-final-a13-20260828': 105, 'sloqual-final-b12-20260828-execB': 105}**
- max observed enforcement latency: **1444.849 ms** (limit ≤ 5000.0 ms)
- post-revoke forbidden side effects: **0**

## Fail conditions

- none

## Limits (why not full PASS)

- LIMIT: `insufficient-statistical-power:sloqual-final-a13-20260828:disk_slow_saturation:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-a13-20260828:disk_slow_saturation:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-a13-20260828:disk_slow_saturation:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-a13-20260828:disk_slow_saturation:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-a13-20260828:disk_slow_saturation:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-a13-20260828:soak:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-a13-20260828:soak:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-a13-20260828:soak:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-a13-20260828:soak:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-a13-20260828:soak:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-a13-20260828:sqlite_lock_contention:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-a13-20260828:sqlite_lock_contention:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-a13-20260828:sqlite_lock_contention:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-a13-20260828:sqlite_lock_contention:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-a13-20260828:sqlite_lock_contention:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-b12-20260828-execB:disk_slow_saturation:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-b12-20260828-execB:disk_slow_saturation:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-b12-20260828-execB:disk_slow_saturation:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-b12-20260828-execB:disk_slow_saturation:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-b12-20260828-execB:disk_slow_saturation:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-b12-20260828-execB:soak:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-b12-20260828-execB:soak:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-b12-20260828-execB:soak:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-b12-20260828-execB:soak:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-b12-20260828-execB:soak:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-b12-20260828-execB:sqlite_lock_contention:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-b12-20260828-execB:sqlite_lock_contention:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-b12-20260828-execB:sqlite_lock_contention:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-b12-20260828-execB:sqlite_lock_contention:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-b12-20260828-execB:sqlite_lock_contention:55`
- LIMIT: `owner-confirmation-pending:thresholds-marked-in-contract`
- LIMIT: `production-like-profile-not-proven:sloqual-final-a13-20260828:{}`
- LIMIT: `production-like-profile-not-proven:sloqual-final-b12-20260828-execB:{}`
- LIMIT: `production-like-proof-missing-or-insufficient:verdict-capped-at-PWL`
- LIMIT: `slo-cannot-pass:latency_end_to_end_ms.p95@warm_steady_state@nominal:CI_CROSSES_THRESHOLD`
- LIMIT: `sloqual-final-a13-20260828:db_growth:db-growth-below-target`
- LIMIT: `sloqual-final-a13-20260828:soak:below-required-scale`
- LIMIT: `sloqual-final-a13-20260828:sustained_load:below-required-scale`
- LIMIT: `sloqual-final-b12-20260828-execB:db_growth:db-growth-below-target`
- LIMIT: `sloqual-final-b12-20260828-execB:soak:below-required-scale`
- LIMIT: `sloqual-final-b12-20260828-execB:sustained_load:below-required-scale`

## Independent rerun comparison

- status: compared · divergences flagged by frozen contract tolerances: **0**

Interpretation: PASS requires every proof complete; PASS_WITH_LIMITS itemizes exactly which production-grade proofs are still missing; any invariant/security failure forces FAIL regardless of latency or throughput.
