# S1-010 — research closure, 2026-09-04

Verdict: **PASS_WITH_LIMITS**. Phase A (cloud), independent round-3 review,
and trusted-local canonical Phase B completed. This closes the research
ticket, not a production rollout.

## Decision

The evaluated layered tool-poisoning admission/output contract resolves G-07
with a detection/evidence contract for EP-06. Eight frozen layers
(structural → provenance → capability-diff → advisory indicators →
policy/effect → output guard → fail-closed routing → immutable audit)
produce ALLOW/DENY/QUARANTINE/HUMAN_REVIEW/UNSUPPORTED decisions in which no
advisory heuristic can compensate for an authorization, provenance,
critical-poison, or fail-closed violation. External content never expands
registry capabilities, policy, approvals, budgets, knowledge status, or
terminal authority (all expansion counters exactly 0).

## Measurement (frozen corpus, commit `eccba25c`)

56 deterministic cases (14 benign / 14 malicious manifest / 14 malicious
output / 14 near-miss; 31 critical). Two process-separated A/B runs
(runner pids 5259/5296, distinct evaluator children, distinct
nonces/output roots), byte-identical decision sets:

- TP=34, FP=3 (all oracle-sanctioned quarantine/human-review routing),
  TN=19, FN=0;
- precision 0.9189 (Wilson 95% [0.7870, 0.9720]), recall 1.0000
  (Wilson 95% [0.8985, 1.0000]);
- benign hard FPR 0.0, raw benign FPR 0.1364;
- critical escapes 0; capability/policy/approval/budget/knowledge/acceptance
  expansions 0; reason-class mismatch count 0;
- probes A–F all detected through the production evaluator path.

## Review chain

- Independent review round 2 (bundle 2, HEAD `22dfbe8`): REVISE, 7 findings.
- Round 3 fixes (bundle 3, HEAD `ee1578c`): publication/provenance
  reconciliation, audit-evidence grounding, decision authority, input schema,
  Windows portability — all negative repros now drive the real generator
  entry points.
- Independent pi review (2026-09-04,
  `.codex-work/S1-010_PI_REVIEW.md`): all seven findings verified fixed with
  independent probes; verdict READY_FOR_CANONICALIZATION; no blocking
  findings. Full-discover adds zero failures versus the `a0116167` baseline
  in an identical environment.

## Verification (this closure)

- S1-010 targeted suite at the closure commit: 102 tests OK, exit 0
  (clean disposable worktree; the user-dirty main worktree skips 13
  production-path tests by design).
- `evals.gen_fixtures --check`: 78 checked, zero violations.
- `git diff --check`: clean.
- Native `research-plan` (trusted host): exit 0, `pass_with_limits`, no
  rejection reasons; `chain_fresh=true`, `latest_evaluation_valid=true`.
- `wiki-build` + `wiki-check`: ok=true, 3,588 files, 9,196 checked links,
  no issues.
- Canonical dependencies S1-001 (revision 1) and S1-009 (revision 11):
  tracked records equal the latest canonical DB rows; artifact chains
  freshly recomputed from disk match.
- Phase B prep fix: the ATLAS source `canonical_uri` carried a parenthetical
  file annotation rejected by the append-only `research_source` trigger
  (migrations/0013); fixed via a URI override and bundle/candidate
  regeneration through the real generators (commit `b802765`), frozen inputs
  and A/B evidence unchanged.

## Canonical identity

- Research revision: 1.
- Goal: `goal_0YJGMZWAHCSRGCVR01M1N3F77T`.
- Campaign: `rcamp_DVXATRP0N41EZQ9601M1N3F77T`.
- Evaluation: `reval_R3Y7MD5STXP6SR3101M1N3F79N`.
- Chain: `8442d0dee8992f77f364ca7bfa1383babba4c5fca5beef9eb5ed0315d9010269`.
- Canonical pack file SHA-256:
  `22f1d222878b2771c92a648c884808f660d01e1459b56343fc4540ce43e84e4a`.

Exact paths, ticket-pack digests, dependency proofs and the per-file hash
registry:
[evaluation-record.json](../research/tickets/stage-1/S1-010/evaluation-record.json).
The frozen Phase A bundle/candidate retains its historical "Phase B required"
wording; this report and the DB-derived evaluation record document completion
of that step. The original evidence was not rewritten to manufacture closure.

## Limits and handoff

- Same-host process separation and deterministic declared pattern families:
  no universal-detection or production claim is licensed; unseen obfuscation
  relies on quarantine/human-review routing.
- `pre_approved` is a boolean entitlement in the evaluated model;
  exact-action+operation+expiry approval binding is production-gateway
  responsibility.
- The frozen 56-case corpus measures declared classes only.
- Downstream: S1-013/S1-016/S1-019 consume this contract as an input, not as
  a production gateway change.
- Windows hosts must verify evidence with LF checkouts (system
  `core.autocrlf=true` clones break byte-hash checks; see the pi review,
  observation Н-2).

Changes are local to branch `codex/s1-010-tool-poisoning` in the main
worktree. Unrelated user changes (`.gitignore`, `.opencode/`,
`opencode.json`, `docs/OPENCODE.md`, `scripts/`) were preserved and not
committed. No push performed.
