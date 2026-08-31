# S1-007 — execution environment

- Main executor: `agentos-s1-007-producer`
- Rerun executor: `agentos-s1-007-independent-verifier` (separate subprocess and output directory)
- Python: 3.12.6
- Platform: Windows-11-10.0.22631-SP0
- Commit: bdb7e4bcacfdadafb090381a80b6aee55b6232b4
- Tree SHA: 8720bac566337284eb4d1c04cb310111822015a8
- Dirty tree: False
- Environment hash (main): f29e22c6bef652cf0a6f414a8f6e0ea00badbb423ba0ed325417d7e80219f277
- Environment hash (rerun): 650f5074ed1b85882aa1c5ab6f4fb0b8ca381484d84451435178bbe58c72da74

## Frozen input hashes (SHA-256)

- corpus-manifest.json: d894973e8819c0d94e863ca1a84aaf3fdf63ae73c998cbb69b1d7247105d7dd9
- fixtures.json: de6d459158764c1221935200d15a23ec8e8097f4d78d8f34bb836437753edbe1
- isolation-contract.json: 30dfa3469e372f5ed05f173df521d3c0b1cd6f00bab2f3bba3bf0e0d3beb9d5b
- rubric.json: fd3ff0ff8e3534d61e4de113aeca9067d933221a796e3695f92998b75d8564eb
- threat-model.json: cd45c5998c4e0cb2c0e80f17585d1ac1cbe1fea7b71de1f5f4a48904b5cd36e8

## Executed script hashes (SHA-256)

- bundle_content.py: 08428e053e896ef6669bbe519b683d24c2a5cb0be4bce12d83e57e7213788949
- dependency_gate.py: fd4e7cfa40ab60b9b6a9e680fdc44340b5a1ee06e7a4e19b4ffd13a7db013a34
- evaluator.py: b27cdacd2b79977772270a2dbc6d7fbe2def50016851d03757a885c17109d37c
- make_bundle.py: baba6332eac13a81d6c143efd84a15296fa3d61d72ab8e7323c674257d95962a
- publish_evidence_pack.py: 7b4d2262ce32e6e66422a22f6a07be20504ef3fa916b25ce67aecfc7ff172ecd
- runner.py: 52aa1d9a295bc64ac3210e6352903defb085dcc2e536dfd9359cd2f03d470e69

## Commands

```
py research/tickets/stage-1/S1-007/dependency_gate.py
AGENTOS_EXECUTOR_ID=agentos-s1-007-producer py research/tickets/stage-1/S1-007/runner.py --mode main --out results/run-a   # exit 0
AGENTOS_EXECUTOR_ID=agentos-s1-007-independent-verifier py research/tickets/stage-1/S1-007/runner.py --mode rerun --out results/run-b   # exit 0
py research/tickets/stage-1/S1-007/runner.py --mode probes --out results   # exit 0
AGENTOS_RUN_NONCE=s1-007-bdb7e4bcacfd-8e07245d2a29 py research/tickets/stage-1/S1-007/evaluator.py ...   # exit 0
py research/tickets/stage-1/S1-007/make_bundle.py   # orchestrates the above with exact-argument invocations
```

## Timing note

The timing probe is a bounded same-host wall-clock measurement (perf_counter_ns) of a microsecond-scale in-process path; cross-executor medians vary with OS scheduling. Timing never gates the safety verdict and is never a production SLO.
