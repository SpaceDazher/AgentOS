# S1-007 — execution environment

- Main executor: `agentos-s1-007-producer`
- Rerun executor: `agentos-s1-007-independent-verifier` (separate subprocess and output directory)
- Python: 3.12.6
- Platform: Windows-11-10.0.22631-SP0
- Commit: 18b292a33f47b353e1f9aff4a00b92ebf5422a4a
- Tree SHA: ee131cdfbff045b8a5e9aae3997a9dacfc628697
- Dirty tree: False
- Environment hash (main): 54335aa657615550eb730749d257351189895b3079d595574647c53bdcb72ad2
- Environment hash (rerun): f44b750742cb0b115f07cfff7e49cc12b857bbdaec2a66ad0901d3b442f6e928

## Frozen input hashes (SHA-256)

- corpus-manifest.json: a03c537bf530b7cdc69d6756e3277e5b4c4ee04dbe1de4a33ed5d394e912cfa9
- fixtures.json: de6d459158764c1221935200d15a23ec8e8097f4d78d8f34bb836437753edbe1
- isolation-contract.json: 30dfa3469e372f5ed05f173df521d3c0b1cd6f00bab2f3bba3bf0e0d3beb9d5b
- rubric.json: fd3ff0ff8e3534d61e4de113aeca9067d933221a796e3695f92998b75d8564eb
- threat-model.json: cd45c5998c4e0cb2c0e80f17585d1ac1cbe1fea7b71de1f5f4a48904b5cd36e8

## Executed script hashes (SHA-256)

- bundle_content.py: fd4f3a3c705b4a129d6180a86ebac26aa6e557bb39256ec38cb9af206e0b258e
- dependency_gate.py: fd4e7cfa40ab60b9b6a9e680fdc44340b5a1ee06e7a4e19b4ffd13a7db013a34
- evaluator.py: 7772cb6f48f4fe21c7404031d71674b5faeedda59ff6d19eaec8401768dcd5e7
- make_bundle.py: 42645f8c10c18576ba24d1ae6ae4972480b7b14db5e55f36344d17edb9c96481
- publish_evidence_pack.py: 7b4d2262ce32e6e66422a22f6a07be20504ef3fa916b25ce67aecfc7ff172ecd
- runner.py: 3b26004c48f265106033bc9af17d25494784e772b1c21d6973b4eef7d7383a0b

## Commands

```
py research/tickets/stage-1/S1-007/dependency_gate.py
AGENTOS_EXECUTOR_ID=agentos-s1-007-producer py research/tickets/stage-1/S1-007/runner.py --mode main --out results/run-a   # exit 0
AGENTOS_EXECUTOR_ID=agentos-s1-007-independent-verifier py research/tickets/stage-1/S1-007/runner.py --mode rerun --out results/run-b   # exit 0
py research/tickets/stage-1/S1-007/runner.py --mode probes --out results   # exit 0
AGENTOS_RUN_NONCE=s1-007-18b292a33f47-89d524c88c74 py research/tickets/stage-1/S1-007/evaluator.py ...   # exit 0
py research/tickets/stage-1/S1-007/make_bundle.py   # orchestrates the above with exact-argument invocations
```

## Timing note

The timing probe is a bounded same-host wall-clock measurement (perf_counter_ns) of a microsecond-scale in-process path; cross-executor medians vary with OS scheduling. Timing never gates the safety verdict and is never a production SLO.
