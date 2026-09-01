# S1-008 Environment Manifest

## Platform
- OS: Windows 10 (x64)
- OS Build: 10.0.22631.n/A
- Python: 3.11.15 (win_amd64)
- Git: 2.x

## Measurement Environment
- All measurements conducted on the same Windows host
- No network partition isolation — revocation enforced via `RevocationTracker` (in-memory component-state map)
- Cache implemented as in-process `Cache` class (no disk/network boundary)
- Clock: monotonic for elapsed, UTC wall for audit (both from `time.perf_counter_ns` / `datetime.now(timezone.utc)`)
- Jitter introduced by `random.Random(seed)` with fixed seeds 11, 22, 33

## Limitations (transferred from S1-002/PASS_WITH_LIMITS)
- Same-host model-only: no production network/cache topology
- Process-separated auditor: not an external audit firm
- Local model cannot prove absence of all network/cache side channels

## Run Parameters
- Matrix: 4 paths × 2 cache × 3 loads × 3 seeds = 72 observations
- Trials per observation: 5
- Mandatory trials: 360 (72 × 5)
- Fault trials: 24 (8 fault modes × 3 seeds)
- Probe trials: 18 (6 probe types × 3 seeds)
- Total trials per run: 402

## Commit
- git_commit: d5743e5 (evaluator.py percentile fix)
- dirty: False (runner committed before measurement)
