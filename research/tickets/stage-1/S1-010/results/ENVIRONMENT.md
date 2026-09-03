# S1-010 Run Environment

## Host
- python: 3.12.14
- platform: linux
- runner_pid: 2808

## Git provenance (identical for both runs)
- branch: codex/s1-010-tool-poisoning
- commit_sha: 6814dbb00dbbee510733e9640459a489c5868be8
- tree_sha: a8a7ac2be045097abc22a006d375f580c683dff7
- clean: True

## Process separation
- run-a: executor=verifier-A nonce=s1-010-run-a-nonce pid=2819 evaluator_pid=2819 output_root=/home/z/my-project/agentos-repo/research/tickets/stage-1/S1-010/results/run-a
- run-b: executor=verifier-B nonce=s1-010-run-b-nonce pid=2830 evaluator_pid=2830 output_root=/home/z/my-project/agentos-repo/research/tickets/stage-1/S1-010/results/run-b
- invocation_digest_a: 90169ff7cda24c437e81903202250b8cac236e396dce0e7e43be6f6d87ab15b0
- invocation_digest_b: dfee7e0325f5806eb321ee3fb3553e81388bd4ff0dbce812ded9328ebf75f906

Child outputs were produced in per-run temp directories outside the repository (so the child provenance observes a clean tree) and transplanted byte-identically into results/run-a and results/run-b.
