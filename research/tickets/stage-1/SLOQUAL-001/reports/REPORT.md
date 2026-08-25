# SLOQUAL-001 — Production-like SLO qualification report

Contract version: `1.0.5` · frozen at `2026-08-25T17:57:43Z` · self-hash `698bd8943f00f4cf…`

## Verdict: **FAIL**

Runs compared: `sloqual-final-a6-20260825`, `sloqual-final-b6-20260825-execB`

## SLO table

| SLI | Scope | Threshold | Observed | 95% CI | Verdict |
|---|---|---|---|---|---|
| `latency_end_to_end_ms.p95` | warm_steady_state@nominal | <=20.0 ms | 12.439613 | [5.129361, 55.091796] | CI_CROSSES_THRESHOLD |
| `throughput_realization_fraction` | warm_steady_state@nominal | >=0.999 | 1.0 | [0.9981204712312125, 1.0] | CI_CROSSES_THRESHOLD |
| `availability_fraction` | all non-injected windows | >=0.999 | 0.9476608267554113 | [0.9453239762832848, 0.9499030932752046] | FAIL |
| `error_rate_fraction` | all non-injected windows | <=0.01 | 0.052339173244588685 | [0.05009690672479534, 0.05467602371671514] | FAIL |
| `latency_end_to_end_ms.p95` | burst@phase_burst | <=200.0 ms | None | n/a | NO_DATA |
| `recovery_time_seconds` | worker_restart|scheduler_restart|full_restart|network_faults|provider_*|sqlite_lock_contention|disk_slow_saturation | <=30.0 s | 0.081602 | [0.019733, 0.526305] | PASS_CANDIDATE |
| `db_transaction_latency_ms.p95` | warm_steady_state@nominal | <=10.0 ms | 1.0256 | [0.8557, 2.782] | PASS_CANDIDATE |
| `audit_journal_latency_ms.p95` | warm_steady_state@nominal | <=10.0 ms | 0.0139 | [0.0119, 0.0203] | PASS_CANDIDATE |
| `revocation_enforcement_latency_ms` | revocation_under_load, all trials | <=5000.0 ms for EVERY observed trial (max) | 158.81 | [24.212, 3349.982] | PASS_CANDIDATE |

## S1-008 revocation security gate

- trials (main run): **210** (minimum 100)
- max observed enforcement latency: **3349.982 ms** (limit ≤ 5000.0 ms)
- post-revoke forbidden side effects: **0**

## Fail conditions

- FAIL: `slo-threshold-violation:availability_fraction@all non-injected windows:0.9476608267554113!>=0.999`
- FAIL: `slo-threshold-violation:error_rate_fraction@all non-injected windows:0.052339173244588685!<=0.01`

## Limits (why not full PASS)

- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:disk_slow_saturation:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:disk_slow_saturation:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:disk_slow_saturation:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:disk_slow_saturation:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:disk_slow_saturation:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:soak:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:soak:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:soak:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:soak:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:soak:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:sqlite_lock_contention:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:sqlite_lock_contention:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:sqlite_lock_contention:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:sqlite_lock_contention:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:sqlite_lock_contention:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:warm_steady_state:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:warm_steady_state:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:warm_steady_state:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:warm_steady_state:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-a6-20260825:warm_steady_state:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:disk_slow_saturation:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:disk_slow_saturation:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:disk_slow_saturation:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:disk_slow_saturation:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:disk_slow_saturation:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:soak:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:soak:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:soak:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:soak:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:soak:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:sqlite_lock_contention:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:sqlite_lock_contention:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:sqlite_lock_contention:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:sqlite_lock_contention:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:sqlite_lock_contention:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:warm_steady_state:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:warm_steady_state:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:warm_steady_state:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:warm_steady_state:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-b6-20260825-execB:warm_steady_state:55`
- LIMIT: `owner-confirmation-pending:thresholds-marked-in-contract`
- LIMIT: `production-like-profile-not-proven:sloqual-final-a6-20260825:{}`
- LIMIT: `production-like-profile-not-proven:sloqual-final-b6-20260825-execB:{}`
- LIMIT: `production-like-proof-missing-or-insufficient:verdict-capped-at-PWL`
- LIMIT: `rerun-missing-comparable:latency_end_to_end_ms.p95@burst@phase_burst`
- LIMIT: `slo-cannot-pass:latency_end_to_end_ms.p95@warm_steady_state@nominal:CI_CROSSES_THRESHOLD`
- LIMIT: `slo-cannot-pass:no-data:latency_end_to_end_ms.p95@burst@phase_burst`
- LIMIT: `slo-cannot-pass:throughput_realization_fraction@warm_steady_state@nominal:CI_CROSSES_THRESHOLD`
- LIMIT: `sloqual-final-a6-20260825:db_growth:db-growth-below-target`
- LIMIT: `sloqual-final-a6-20260825:soak:below-required-scale`
- LIMIT: `sloqual-final-a6-20260825:sustained_load:below-required-scale`
- LIMIT: `sloqual-final-b6-20260825-execB:db_growth:db-growth-below-target`
- LIMIT: `sloqual-final-b6-20260825-execB:soak:below-required-scale`
- LIMIT: `sloqual-final-b6-20260825-execB:sustained_load:below-required-scale`

## Independent rerun comparison

- status: compared · gross divergences (>50% relative diff): **2**

Interpretation: PASS requires every proof complete; PASS_WITH_LIMITS itemizes exactly which production-grade proofs are still missing; any invariant/security failure forces FAIL regardless of latency or throughput.

