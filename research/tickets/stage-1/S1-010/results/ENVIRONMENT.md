# S1-010 Run Environment

## Host
- python: 3.12.14
- platform: linux
- runner_pid: 3226

## Git provenance (identical for both runs)
- branch: codex/s1-010-tool-poisoning
- commit_sha: 77e81738b4b3b49d3281885cbe15a15f41e8a02d
- tree_sha: fd54b1424a1d7934b7fe013a3cfad2c4f6818faa
- clean: True

## Process separation
- run-a: executor=verifier-A nonce=s1-010-run-a-nonce pid=3237 evaluator_pid=3237 output_root=/home/z/my-project/agentos-repo/research/tickets/stage-1/S1-010/results/run-a
- run-b: executor=verifier-B nonce=s1-010-run-b-nonce pid=3248 evaluator_pid=3248 output_root=/home/z/my-project/agentos-repo/research/tickets/stage-1/S1-010/results/run-b
- invocation_digest_a: d9935fbf9dd53a113e74cf5432ae184fb945d08dba83ad0ccd7c54d77f0675cf
- invocation_digest_b: f01d9191c674f1ba18983673c3ec345f66b77645a79712a8b36b12da054400cb

Child outputs were produced in per-run temp directories outside the repository (so the child provenance observes a clean tree) and transplanted byte-identically into results/run-a and results/run-b.
