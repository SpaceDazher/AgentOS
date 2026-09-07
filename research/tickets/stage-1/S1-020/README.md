# S1-020 — Independent Stage 1 closure audit

This ticket audits the immutable Stage 1 portfolio at commit
`78a4218606212c4f65642fe8dbf9c6a808209cfb`.

It verifies 19 canonical dependency records, 19 prior probe sources, 20 active
ticket rows, four parked rows, and every named open-item family. Two distinct
auditor processes evaluate a 60-case corpus; a comparator recomputes the
oracle result and 256 deterministic sensitivity runs exclude wall-clock data.

The only publishable result is `PASS_WITH_LIMITS`. It closes Stage 1 research;
it does not accept a product Goal, certify production, reopen parked work, or
authorize rollout.

Run `dependency_gate.py`, `freeze.py`, commit a clean input tree, then run
`runner.py`, `make_bundle.py`, the canonical `research-plan` command, and
`finalize_record.py`.
