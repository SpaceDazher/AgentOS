# S1-008 Environment Manifest

## Platform
- OS: Windows 10 (x64)
- OS Build: 10.0.22631
- Python: 3.11.15 (win_amd64)
- Git: 2.x

## Measurement Environment
- All measurements conducted on the same host (same-host model).
- Same-host model-only: no production network/cache topology tested.
- Process-separated auditor (evaluator.py), not an external/independent audit firm.
- Local model cannot prove absence of all network/cache side channels.

## Run A
- executor_id: executor-run-a-190bd171
- git_commit: 9546585
- total_trials: 402 (360 mandatory + 24 fault + 18 probe)
- max_latency: 1.6352ms
- hard_counters: all 0

## Run B (independent rerun)
- executor_id: executor-run-b-94619b75
- git_commit: 9546585
- total_trials: 402 (360 mandatory + 24 fault + 18 probe)
- max_latency: 2.053ms
- hard_counters: all 0

## Comparison
- verdict: PASS (both runs match)
- executor IDs differ: true
- output roots differ: true
- hard counters match: true
- verdicts match: true
