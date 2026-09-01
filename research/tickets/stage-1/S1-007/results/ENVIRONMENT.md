# S1-007 — execution environment

- Main executor: `agentos-s1-007-producer`
- Rerun executor: `agentos-s1-007-independent-verifier` (separate subprocess and output directory)
- Python: 3.12.6
- Platform: Windows-11-10.0.22631-SP0
- Commit: 98ff9654ebe34de3bcacc687a481a04502cb85e9
- Tree SHA: 8cac3f1ed57ee60435838dfbaeee078158663f82
- Dirty tree: False
- Environment hash (main): 5bfebdc77b61048250f9d7a7c1ec48b943a1accd876ab791cf4d6361d2ff4cc6
- Environment hash (rerun): 12c7c5d95b20c1191af2084e7974abbebe06e0432f3ae55281a82febfead0fe4

## Frozen input hashes (SHA-256)

- corpus-manifest.json: a03c537bf530b7cdc69d6756e3277e5b4c4ee04dbe1de4a33ed5d394e912cfa9
- fixtures.json: de6d459158764c1221935200d15a23ec8e8097f4d78d8f34bb836437753edbe1
- isolation-contract.json: 30dfa3469e372f5ed05f173df521d3c0b1cd6f00bab2f3bba3bf0e0d3beb9d5b
- rubric.json: 3dee1570bf5a8e35a666b985ab0a92893c627cc7b7ac8de97e4b067d34301b0d
- threat-model.json: cd45c5998c4e0cb2c0e80f17585d1ac1cbe1fea7b71de1f5f4a48904b5cd36e8

## Executed script hashes (SHA-256)

- bundle_content.py: a1b96fcb8e6a54655b54f565c30dac4b741e5daac6a3cf05f61e77b60501d636
- dependency_gate.py: fd4e7cfa40ab60b9b6a9e680fdc44340b5a1ee06e7a4e19b4ffd13a7db013a34
- evaluator.py: 527384ce7ad996af82b914a284fcb679458211688362bb92379d9a5142ef47e8
- finalize_record.py: 1b9a9a9f066d739628e1662550fae8a9cbd12f5b5112e429959a59c896a630b1
- make_bundle.py: 6b4c4482e2bd0cf0bf5751d6c853cf1f57b75f912085d4a5a661282113478031
- publish_evidence_pack.py: 7b4d2262ce32e6e66422a22f6a07be20504ef3fa916b25ce67aecfc7ff172ecd
- runner.py: fba32905903673023cbcc7f4ef70260ab95285b5ad72117907aa76aa76a4fb7c

## Commands

```
py research/tickets/stage-1/S1-007/dependency_gate.py
AGENTOS_EXECUTOR_ID=agentos-s1-007-producer py research/tickets/stage-1/S1-007/runner.py --mode main --out results/run-a   # exit 0
AGENTOS_EXECUTOR_ID=agentos-s1-007-independent-verifier py research/tickets/stage-1/S1-007/runner.py --mode rerun --out results/run-b   # exit 0
py research/tickets/stage-1/S1-007/runner.py --mode probes --out results   # exit 0
AGENTOS_RUN_NONCE=s1-007-98ff9654ebe3-6d507a5b546f py research/tickets/stage-1/S1-007/evaluator.py ...   # exit 0
py research/tickets/stage-1/S1-007/make_bundle.py   # orchestrates the above with exact-argument invocations
```

## Timing note

The timing probe is a bounded same-host wall-clock measurement (perf_counter_ns) of a microsecond-scale in-process path; cross-executor medians vary with OS scheduling. Timing never gates the safety verdict and is never a production SLO.
