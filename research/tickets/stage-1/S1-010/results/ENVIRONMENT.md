# S1-010 Run Environment

## Host
- python: 3.12.14
- platform: linux
- orchestrator_pid: 24283

## Git provenance (identical for both runs)
- branch: codex/s1-010-tool-poisoning
- commit_sha: 02cd76891b3962d3078abd47c84272513ad50352
- tree_sha: 2d94589d4091440bd52d6622cfa8e94d78683747
- clean: True

## Process separation
- run-a: executor=verifier-A nonce=00ae0e62ca9c40ccb77a82f3d425f618 runner_pid=24294 evaluator_pid=24305 output_root=/tmp/s1-010-runner-a-ub895sv_
- run-b: executor=verifier-B nonce=edb16a39fbfc45a5bc91dc292381462e runner_pid=24316 evaluator_pid=24327 output_root=/tmp/s1-010-runner-b-b9245aq1
- runner_sha256: d136c7cb963e724b0a93811dd129a7efb55420f6c9689645cf389ae8589217df
- evaluator_sha256: 1ba7e064234637835b39be610433c8a6e4547db4e09031f49b5b527ee02b07bd
- invocation_digest_a: 794b797076670d3aea0be36c4c6ff2bc23ea9b426b4c74434462d190de1f7dc2
- invocation_digest_b: b867e0a790402aed2d3a88736048e1ce5331e880848804a9d5403efeb4a0f77e

Each run executed as an independent runner child process (distinct runner PID), each spawning its own evaluator grandchild process (distinct evaluator PID), with distinct executor IDs, nonces, and output roots.  Child outputs were produced in per-run temp directories outside the repository (so every process observes a clean tree) and transplanted byte-identically into results/run-a and results/run-b.
