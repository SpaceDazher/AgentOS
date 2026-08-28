# SLOQUAL-001 — Production-like SLO qualification report

Contract version: `1.0.5` · frozen at `2026-08-25T17:57:43Z` · self-hash `698bd8943f00f4cf…`

## Verdict: **FAIL**

Runs compared: `sloqual-final-a11-20260826`, `sloqual-final-b10-20260826-execB`

## SLO table

| SLI | Scope | Threshold | Observed | 95% CI | Verdict |
|---|---|---|---|---|---|
| `latency_end_to_end_ms.p95` | warm_steady_state@nominal | <=20.0 ms | 14.126258 | [12.764133, 26.513055] | CI_CROSSES_THRESHOLD |
| `throughput_realization_fraction` | warm_steady_state@nominal | >=0.999 | 1.0 | [0.9992473397044779, 1.0] | PASS_CANDIDATE |
| `availability_fraction` | all non-injected windows | >=0.999 | 1.0 | [0.999896723432781, 1.0] | PASS_CANDIDATE |
| `error_rate_fraction` | all non-injected windows | <=0.01 | 0.0 | [6.776263578034403e-21, 0.00010327656721913339] | PASS_CANDIDATE |
| `latency_end_to_end_ms.p95` | burst@phase_burst | <=200.0 ms | 11918.387 | [3211.572039, 12573.434854] | FAIL |
| `recovery_time_seconds` | worker_restart|scheduler_restart|full_restart|network_faults|provider_*|sqlite_lock_contention|disk_slow_saturation | <=30.0 s | 0.210657 | [0.028146, 0.953994] | PASS_CANDIDATE |
| `db_transaction_latency_ms.p95` | warm_steady_state@nominal | <=10.0 ms | 2.6144 | [2.4544, 5.4083] | PASS_CANDIDATE |
| `audit_journal_latency_ms.p95` | warm_steady_state@nominal | <=10.0 ms | 0.036 | [0.03, 0.0424] | PASS_CANDIDATE |
| `revocation_enforcement_latency_ms` | revocation_under_load, all trials | <=5000.0 ms for EVERY observed trial (max) | 1560.748 | [91.643, 2546.742] | PASS_CANDIDATE |

## S1-008 revocation security gate

- trials (main run): **105** (minimum 100)
- trials by run: **{'sloqual-final-a11-20260826': 105, 'sloqual-final-b10-20260826-execB': 105}**
- max observed enforcement latency: **2546.742 ms** (limit ≤ 5000.0 ms)
- post-revoke forbidden side effects: **0**

## Fail conditions

- FAIL: `slo-threshold-violation:latency_end_to_end_ms.p95@burst@phase_burst:11918.387!<=200.0`

## Limits (why not full PASS)

- LIMIT: `insufficient-statistical-power:sloqual-final-a11-20260826:disk_slow_saturation:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-a11-20260826:disk_slow_saturation:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-a11-20260826:disk_slow_saturation:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-a11-20260826:disk_slow_saturation:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-a11-20260826:disk_slow_saturation:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-a11-20260826:soak:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-a11-20260826:soak:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-a11-20260826:soak:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-a11-20260826:soak:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-a11-20260826:soak:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-a11-20260826:sqlite_lock_contention:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-a11-20260826:sqlite_lock_contention:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-a11-20260826:sqlite_lock_contention:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-a11-20260826:sqlite_lock_contention:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-a11-20260826:sqlite_lock_contention:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-b10-20260826-execB:disk_slow_saturation:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-b10-20260826-execB:disk_slow_saturation:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-b10-20260826-execB:disk_slow_saturation:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-b10-20260826-execB:disk_slow_saturation:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-b10-20260826-execB:disk_slow_saturation:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-b10-20260826-execB:soak:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-b10-20260826-execB:soak:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-b10-20260826-execB:soak:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-b10-20260826-execB:soak:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-b10-20260826-execB:soak:55`
- LIMIT: `insufficient-statistical-power:sloqual-final-b10-20260826-execB:sqlite_lock_contention:11`
- LIMIT: `insufficient-statistical-power:sloqual-final-b10-20260826-execB:sqlite_lock_contention:22`
- LIMIT: `insufficient-statistical-power:sloqual-final-b10-20260826-execB:sqlite_lock_contention:33`
- LIMIT: `insufficient-statistical-power:sloqual-final-b10-20260826-execB:sqlite_lock_contention:44`
- LIMIT: `insufficient-statistical-power:sloqual-final-b10-20260826-execB:sqlite_lock_contention:55`
- LIMIT: `owner-confirmation-pending:thresholds-marked-in-contract`
- LIMIT: `production-like-profile-not-proven:sloqual-final-a11-20260826:{}`
- LIMIT: `production-like-profile-not-proven:sloqual-final-b10-20260826-execB:{}`
- LIMIT: `production-like-proof-missing-or-insufficient:verdict-capped-at-PWL`
- LIMIT: `slo-cannot-pass:latency_end_to_end_ms.p95@warm_steady_state@nominal:CI_CROSSES_THRESHOLD`
- LIMIT: `sloqual-final-a11-20260826:db_growth:db-growth-below-target`
- LIMIT: `sloqual-final-a11-20260826:soak:below-required-scale`
- LIMIT: `sloqual-final-a11-20260826:sustained_load:below-required-scale`
- LIMIT: `sloqual-final-b10-20260826-execB:db_growth:db-growth-below-target`
- LIMIT: `sloqual-final-b10-20260826-execB:soak:below-required-scale`
- LIMIT: `sloqual-final-b10-20260826-execB:sustained_load:below-required-scale`

## Independent rerun comparison

- status: compared · gross divergences (>50% relative diff): **1**

Interpretation: PASS requires every proof complete; PASS_WITH_LIMITS itemizes exactly which production-grade proofs are still missing; any invariant/security failure forces FAIL regardless of latency or throughput.

