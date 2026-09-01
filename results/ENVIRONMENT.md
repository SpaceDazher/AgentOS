# S1-008 Environment Manifest

## Runtime
- Python: 3.11.15
- OS: Windows 11
- Platform: x86_64
- Working directory: D:/Project/AgentOS

## Clock Model
- Monotonic clock: `time.perf_counter()` for elapsed latency measurement
- Wall clock: `datetime.now(timezone.utc)` for audit/provenance only (NOT used for latency)
- Clock domain: monotonic (authoritative), UTC wall (audit only)
- Precision: nanosecond

## Environment Hash
```
env_sha256: computed from python version, OS, env vars, and runtime parameters
```

## Environment Variables
- PYTHONPATH: src
- No network dependencies (stdlib only)

## Executor Identities
- Run A: executor-run-a
- Run B: executor-run-b

## Output Roots
- Run A: results/run-a/
- Run B: results/run-b/
