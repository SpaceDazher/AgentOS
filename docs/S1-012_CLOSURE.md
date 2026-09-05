# S1-012 — research closure, 2026-09-04

Verdict: **PASS_WITH_LIMITS**. Phase A (agent), two independent review
rounds, and trusted-local canonical Phase B completed. This closes the
research ticket, not a production reputation service and not a claim of
objective truth.

## Decision

Adopt **document granularity with upstream collapse** as the MVP evidence
unit: one unit per source document, grouping by provenance lineage,
independent weight counting distinct allowed groups (cap 2), strict
scope/version/lifecycle bindings, UNKNOWN abstention (never an invented
group), and a structural policy firewall — Beta tails and EigenTrust rank
review queues at most; `enforcement_allow` is always false, so no score can
create ALLOW, capability, approval, budget, PROMOTED or ACCEPTED. Span is
safety-tied with document and retained for fine-grained revocation; digest
is cheapest but requires a bound upstream (identical-text independents
collapse). Reputation-only is excluded as a negative control.

## Measurement (frozen matrix, commit `f43217c`)

60 cases (12 per family: gold / correlation / Sybil-collusion ×3 attack
shapes / invalid-stale-revoked / near-miss; 40 dev + 20 holdout split by
lineage cluster, non-blinded — disclosed) × 4 variants × 3 frozen seeds =
720 rows per run; two process-separated A/B runs (24 runner processes with
distinct PIDs/invocations/nonces/executors/output roots), byte-identical
decision rows.

- Governed variants: all hard counters exactly zero (mirror/Sybil
  double-count, cross-scope/stale/revoked acceptance, authority expansion,
  unbound observations), precision/recall 1.0, transition exactness 1.0,
  abstention 0.083 only where the oracle allows it.
- Reputation-only: FAIL in all cells (51 mirror/Sybil double counts).
- Beta math verified against exact binomial references (1e-9) and
  independent numerical integration; invalid parameters fail closed.
- Sensitivity: 20 weight sweeps + 200 seeded compositions + 135 joint
  prior/decay/threshold/cap combos through the real decision core — 0
  winner flips; document~span tie recorded as an explicit limitation,
  never resolved by reweighting.

## Review chain

- Round 1 (HEAD `fb12872`): REVISE — publication trusted stored PASS flags
  (F1), raw run evidence untracked with a false ENVIRONMENT.md claim (F2),
  no tracked-artifact hash registry (F3). See `S1-012_PI_REVIEW.md`.
- Fixes `23ff603`/`f43217c`/`f51319c`: publication recomputes the whole
  pipeline from tracked raw cells via the real compare entry point and
  crosschecks saved merged artifacts; 24 raw cells (96 files) tracked with
  per-row self-hashes; 133-entry artifact registry; fresh full A/B re-run
  (byte-identical rows).
- Round 2 (HEAD `f51319c`): all findings verified fixed with independent
  negative probes through real entry points; READY_FOR_CANONICALIZATION;
  no new findings. See `S1-012_PI_REVIEW_R2.md`.

## Verification (this closure)

- `unittest discover -p "test_s1_012*.py"`: 48 tests OK, exit 0;
  full discover at the closure tree: 855 tests, failing set identical to
  the `d7e88df` baseline (0 new failures).
- `evals.gen_fixtures --check`: 78 checked, zero violations;
  `git diff --check`: clean.
- Publication basis re-run inside finalize (raw-cell recompute +
  crosscheck): admissible, 12 cells / 720 rows, winner TIE(document/span)
  with recorded limitation.
- Native `research-plan` (trusted host): exit 0, `pass_with_limits`,
  revision 1, no rejection reasons; `chain_fresh=true`,
  `latest_evaluation_valid=true`.
- `wiki-build` + `wiki-check`: ok=true, 3,627 files, 9,287 checked links,
  no issues.
- Canonical dependencies S1-001 (revision 1), S1-003 (revision 24) and
  S1-011 (revision 1): tracked records equal the latest canonical DB rows;
  artifact chains freshly recomputed from disk match.

## Canonical identity

- Research revision: 1.
- Goal: `goal_8VBM41JB75VDTSP201M1NNPB3S`.
- Campaign: `rcamp_29WZZQ406M19WJS801M1NNPB3S`.
- Evaluation: `reval_EPR9JR5JWBHXST6301M1NNPB5P`.
- Chain: `818a25e67a1865d425eebcb754376f06d143aaac9fa7f07aa704804311ffb21c`.
- Canonical pack file SHA-256:
  `fd26269588c0ab4470360c688c5cabf5f19e023ffd3684944a99bd81b4958775`.

Exact paths, ticket-pack digests, dependency proofs and the 133-entry
per-file hash registry:
[evaluation-record.json](../research/tickets/stage-1/S1-012/evaluation-record.json).
The frozen Phase A candidate retains its historical "Phase B required"
wording; this report and the DB-derived evaluation record document
completion of that step. The original evidence was not rewritten to
manufacture closure.

## Limits and handoff

- The planning threshold `P[theta > 0.9] >= 0.95` remains a hypothesis —
  no measured calibration data; all numbers are corpus/model-level.
- Holdout is lineage-isolated but author-visible, not blinded; no human
  study (S1-013 owns comprehension/fatigue).
- Same-host deterministic pipeline; internally consistent fabrication of
  both raw series is beyond what byte hashes and A/B identity can exclude
  (declared limitation, same class as accepted for S1-010).
- Cyclic attack graphs and real-wild Sybil rates are unproven unknowns.
- Downstream: S1-013 (human factors) and S1-019 (synthesis) consume this
  contract as an input; no production rollout is licensed.

Changes are local to branch `codex/s1-012-evidence-independence` in the
`.codex-work/s1-012-task` worktree. Main was not merged or modified; no
push performed.
