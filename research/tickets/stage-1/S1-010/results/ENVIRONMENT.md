# S1-010 Run Environment

## Host
- python: 3.12.14
- platform: linux
- orchestrator_pid: 4896

## Git provenance (identical for both runs)
- branch: codex/s1-010-tool-poisoning
- commit_sha: 26458d329ec94ac3dd2e8dfea03c76444d656f40
- tree_sha: 4c8988568703a7343a65187c7b93019eace8135e
- clean: True

## Process separation
- run-a: executor=verifier-A nonce=a41bd0d9ad1f4ae188a299b638806fe6 runner_pid=4907 evaluator_pid=4918 output_root=/tmp/s1-010-runner-a-i60jov4_
- run-b: executor=verifier-B nonce=6d79e447c9ab4a2183f53a2f1abe7e0b runner_pid=4944 evaluator_pid=4955 output_root=/tmp/s1-010-runner-b-73dllan_
- runner_sha256: 992b525e2e5d693cabead37e876f8e189c44dbb4069d1d8f55206692bc2d5cf6
- evaluator_sha256: 0eda25d7639c608cc9212bd02d7f40b48076ac38400f31dfa6b77a671bdebe19
- invocation_digest_a: ddd4f782c4bd8c6f5443b88b3fc3ea0a7e7740be26762576ef9f41fddbdc328f
- invocation_digest_b: 0a9cced3e39dc754ffcb3cb88e224c6c4943a0eb259de677fda843711f962fab

Each run executed as an independent runner child process (distinct runner PID), each spawning its own evaluator grandchild process (distinct evaluator PID), with distinct executor IDs, nonces, and output roots.  Child outputs were produced in per-run temp directories outside the repository (so every process observes a clean tree) and transplanted byte-identically into results/run-a and results/run-b.
