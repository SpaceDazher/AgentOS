# S1-005 independent review R4 corrective record

Status at review: **REVISE**. The QA1 score remained stable, but the evidence
validator and the core autoresearch worktree copy still contained fail-open
paths. This record defines the corrective acceptance bar before a new research
revision may be published.

## Confirmed findings

1. `tree_sha` was syntactically checked but was not resolved from the recorded
   commit.
2. `script_hashes` accepted a non-empty subset instead of the exact producer
   and evaluator set.
3. transport validation accepted any three counter names rather than the exact
   `in_process`, `pipe`, and `tcp` observations.
4. a failed `git rev-parse HEAD` disabled the expected-commit comparison.
5. `run_experiments()` overwrote the artifact's canonical payload digest with
   a different file-byte digest in the returned mapping.
6. autoresearch silently omitted arbitrary inaccessible entries while copying
   `src/`, `evals/`, and `spec/` into the candidate worktree.
7. the prior narrative mixed the revision-5 payload digest
   `0fd8b8ff...449c9` with the revision-6 pack file digest. Revision 6 actually
   binds payload `2ece6834...f8985`.

## Corrective contract

- Resolve `<commit>^{tree}` from Git and require exact equality with
  `tree_sha`; Git lookup failure is terminal.
- Require the exact script-hash set `{experiments.py, evaluator.py}`, with
  valid SHA-256 values that match disk.
- Require the exact transport-count set `{in_process, pipe, tcp}`.
- Require a successful, valid `git rev-parse HEAD` before bundle publication.
- Return the schema-valid experiment document unchanged; bind file bytes with
  a separate caller-owned digest.
- Ignore only explicit generated/cache names during worktree creation. Any
  other access/copy failure propagates and stops the campaign.
- Add deterministic negative regressions for every finding above.

## Publication rule

Tooling fixes must be committed first. Experiments then run on that clean
commit, followed by the evaluator, FLOW-11 bundle, a new research revision,
tracked content-addressed evidence pack, and an updated evaluation record.
`PASS_WITH_LIMITS` remains the maximum possible verdict: all measurements are
same-host and no production or multi-host claim is authorized.
