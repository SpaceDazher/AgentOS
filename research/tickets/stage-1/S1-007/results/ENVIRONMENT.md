# S1-007 — execution environment

- Main executor: `agentos-s1-007-producer`
- Rerun executor: `agentos-s1-007-independent-verifier` (separate subprocess and output directory)
- Python: 3.12.6
- Platform: Windows-11-10.0.22631-SP0
- Commit: 0e93364078f95e9053430698614c0cc94e683793
- Tree SHA: c7f6fd7f88f93f25a5056ff40fa28ce80f58177f
- Dirty tree: False
- Environment hash (main): 160c65cdd2f53261ee09931f1c896f740e4c1ca72fa0eadbeab53bc3f2a4cf2c
- Environment hash (rerun): dfa4d75218bcd5926a961c298db7e1ac159508e65e01f117cec881df46bc5063

## Frozen input hashes (SHA-256)

- corpus-manifest.json: a03c537bf530b7cdc69d6756e3277e5b4c4ee04dbe1de4a33ed5d394e912cfa9
- fixtures.json: de6d459158764c1221935200d15a23ec8e8097f4d78d8f34bb836437753edbe1
- isolation-contract.json: 30dfa3469e372f5ed05f173df521d3c0b1cd6f00bab2f3bba3bf0e0d3beb9d5b
- rubric.json: 3dee1570bf5a8e35a666b985ab0a92893c627cc7b7ac8de97e4b067d34301b0d
- threat-model.json: cd45c5998c4e0cb2c0e80f17585d1ac1cbe1fea7b71de1f5f4a48904b5cd36e8

## Executed script hashes (SHA-256)

- bundle_content.py: a1b96fcb8e6a54655b54f565c30dac4b741e5daac6a3cf05f61e77b60501d636
- dependency_gate.py: fd4e7cfa40ab60b9b6a9e680fdc44340b5a1ee06e7a4e19b4ffd13a7db013a34
- evaluator.py: a05d30a6521e71bbbab0345a2996795637da2eb01f8f9e82d82e4691d016d6fc
- finalize_record.py: aaa5e5070d302476672a537f3e868203bb2dbfb07891cb74388f01438ec0215a
- make_bundle.py: 6b4c4482e2bd0cf0bf5751d6c853cf1f57b75f912085d4a5a661282113478031
- publish_evidence_pack.py: 7b4d2262ce32e6e66422a22f6a07be20504ef3fa916b25ce67aecfc7ff172ecd
- runner.py: fba32905903673023cbcc7f4ef70260ab95285b5ad72117907aa76aa76a4fb7c

## Commands

```
py research/tickets/stage-1/S1-007/dependency_gate.py
AGENTOS_EXECUTOR_ID=agentos-s1-007-producer py research/tickets/stage-1/S1-007/runner.py --mode main --out results/run-a   # exit 0
AGENTOS_EXECUTOR_ID=agentos-s1-007-independent-verifier py research/tickets/stage-1/S1-007/runner.py --mode rerun --out results/run-b   # exit 0
py research/tickets/stage-1/S1-007/runner.py --mode probes --out results   # exit 0
AGENTOS_RUN_NONCE=s1-007-0e93364078f9-8afba5fbd4e7 py research/tickets/stage-1/S1-007/evaluator.py ...   # exit 0
py research/tickets/stage-1/S1-007/make_bundle.py   # orchestrates the above with exact-argument invocations
```

## Timing note

The timing probe is a bounded same-host wall-clock measurement (perf_counter_ns) of a microsecond-scale in-process path; cross-executor medians vary with OS scheduling. Timing never gates the safety verdict and is never a production SLO.
