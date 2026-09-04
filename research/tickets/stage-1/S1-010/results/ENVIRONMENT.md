# S1-010 Run Environment

## Host
- python: 3.12.14
- platform: linux
- orchestrator_pid: 5248

## Git provenance (identical for both runs)
- branch: codex/s1-010-tool-poisoning
- commit_sha: eccba25ca028b5fb8d53030952d6cf0d1fc57a36
- tree_sha: 14f6254c10241b688ff4898d1cfcbc8b20203453
- clean: True

## Process separation
- run-a: executor=verifier-A nonce=1f82be39e12f4ef4b341afd9f78bd57e runner_pid=5259 evaluator_pid=5270 output_root=/tmp/s1-010-runner-a-b5wu05hn
- run-b: executor=verifier-B nonce=77ed326209da417b975874066fa0e748 runner_pid=5296 evaluator_pid=5307 output_root=/tmp/s1-010-runner-b-hi60y_90
- runner_sha256: 3e7a3bd400494a33c2b0d70b97507c8757acc9f8225a953894109ad47ac19c14
- evaluator_sha256: 0eda25d7639c608cc9212bd02d7f40b48076ac38400f31dfa6b77a671bdebe19
- invocation_digest_a: 7a08f78f0c3326094926944d8149e1840e87cc1d78bcb03e4ca00946d9896a1d
- invocation_digest_b: 3787829952e41c2ad0c70233da532fea5336673931a1f1eb97555e1365d3796f

Each run executed as an independent runner child process (distinct runner PID), each spawning its own evaluator grandchild process (distinct evaluator PID), with distinct executor IDs, nonces, and output roots.  Child outputs were produced in per-run temp directories outside the repository (so every process observes a clean tree) and transplanted byte-identically into results/run-a and results/run-b.
