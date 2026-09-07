# S1-019 dependency review — publication blocker resolved

Current status: **CANONICAL_VERIFICATION_REQUIRED**. This is not an S1-019
completion record or a full dependency-gate PASS.

## Resolution after operator authorization

Canonical main now contains `19ff320adfe7153267fb634268038ae16ba25a16`:
S1-014 evaluation record, content-addressed canonical/ticket packs, the original
approved preparation bundle, portable chain input and canonical artifact bodies.
The original operator answers and frozen research inputs were not rewritten.
S1-014 remains `pass_with_limits`, operator_review_n=1, human_study_n=0,
comparative_human_effectiveness=NOT_MEASURED.

Publication evidence: 23 targeted tests passed (including real browser), full
suite 1138 tests exit 0 with one checkpoint-before-crash skip, corpus 78/78,
wiki 3667 files/9381 links with no issues, and 62 tracked hashes plus the full
chain verified from a clean Git archive without a DB. The first full-suite
attempt failed because this new worktree lacked the required local test DB
and S1-008 raw traces; after provisioning an isolated SQLite snapshot and the
existing traces, the exact full suite passed. No tests were weakened.

S1-019 availability and wall-clock reports now use that immutable main commit.
All 18 evaluation records are present and parse strictly. Full schema-specific
pack/identity/chain/frozen-input verification still precedes synthesis; the
availability checker intentionally does not grant authorization.

## Historical blocker diagnosis (retained, no longer current)

## Immutable input

- Canonical input commit: `26f360bb4045e14c1b2cd4d36596d8b5eceea60d`.
- S1-019 task commit: `986478b6855ee4d3bb5bd4cd2d0950c534f17ce4`.
- Wall-clock preflight against the canonical input completed with exit 0;
  see `wall-clock-preflight.json`. A passing clock preflight does not prove
  canonical dependency publication.

## Confirmed blocker: S1-014

At the canonical input commit, S1-014 has `candidate-record.json`, but no
`evaluation-record.json` or tracked evidence pack. The ticket registry itself
states that a canonical evaluation record is still required before downstream
dependency verification. The known S1-014 remote-tracking branch also lacks
those published artifacts. A candidate verdict cannot substitute for canonical
bindings.

Read-only local investigation found an evaluation in the separate S1-014 task
worktree database, not in the main checkout database:

- goal: `goal_899YPYXSJFFTM36801M1QQXEKF`
- campaign: `rcamp_K50NQ8VJX7PBGD1K01M1QQXEKF`
- evaluation: `reval_9FPBQ790226WSNCE01M1QQXEM4`
- result: `pass_with_limits`
- recorded and independently recomputed artifact chain:
  `b1a00bd279fbc0de72f71c84820f82415a0cf1c37f78458e51bf7d5b10496ece`

The local runtime evidence pack exists under that task's ignored
`.agentos-research/` directory. These observations distinguish missing
publication from a missing local run. They are diagnostic evidence only:
neither the local database nor this report is a portable canonical dependency
proof, and the pack has not been independently qualified here for publication.

## Recovery sequence

1. In S1-014 scope, independently verify the local evaluation, current bundle,
   limitations and pack; rerun canonicalization if any binding is stale.
2. Publish a tracked content-addressed pack and a programmatically generated
   evaluation record with the real canonical IDs and full hashes. Preserve
   the single-operator and unmeasured comparative-human-effectiveness limits.
3. Verify those artifacts from a clean Git archive and integrate the corrective
   S1-014 commit into canonical main with operator authorization.
4. Resolve the resulting immutable main SHA, rerun the complete S1-019
   dependency gate and clock preflight, and only then freeze synthesis inputs.

TASK_FOR_AGENT.md sections 2 and 20 prohibit proceeding with an unverified
dependency. No final synthesis, operator approval, research-plan acceptance,
or S1-019 closure has been manufactured to bypass the dependency gate.
Steps 1–3 were completed with the operator's explicit publication/merge
authorization. Step 4's full dependency verification remains to be implemented.
