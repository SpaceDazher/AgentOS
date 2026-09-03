# S1-011 — research closure, 2026-09-03

Verdict: **PASS_WITH_LIMITS**. Phase A and trusted-local Phase B completed.
This closes the research ticket, not a production implementation.

## Decision and corrective evidence

The MVP recommendation is the minimal promote/challenge gate. PROMOTED means
passage of a versioned scope/policy gate, never objective truth. Naive
argumentation and TMS alternatives fail safety gates and are excluded from
ranking; this is not a claim that every possible implementation of either
family is unsafe.

R2's nine findings are repaired: explicit evidence bindings, shared promotion
predicates, stale-view exclusion, complete case-bound ledgers, exact per-cell
matrix, real Git provenance, dependency identity, raw-derived publication,
and simultaneous UNKNOWN bounds. Additional negative probes fixed evidence-free
reads and shared-branch ledger identities for all designs. See
[corrective report](../research/tickets/stage-1/S1-011/results/CORRECTIVE_R3.md).

Fresh measurement commit: `9d4c910`. Two series, each 72 cases x three designs
x three seeds = 648 rows; 18 distinct runner processes. Minimal gate:
zero hard counters, zero invalid transitions, transition/view exactness 1.0.
Sensitivity: zero winner flips and no UNKNOWN-dependent winner.

## Verification

- Full repository suite: 708 tests, exit 0, one existing skip.
- Ticket + independent corrective + canonical binding tests: 100, all pass.
- Corpus: 78 checked, zero violations.
- Native `research-plan`: exit 0, `pass_with_limits`, no rejection reasons;
  `chain_fresh=true`, `latest_evaluation_valid=true`.
- `wiki-check --db D:/Project/AgentOS/.agentos-research/platform-stage-1`:
  `ok=true`, 3,534 files, 9,083 checked links, no issues.
- S1-001 revision 1 and S1-003 revision 24: tracked records equal latest
  canonical DB rows; artifact chains freshly recomputed from disk match.
- Publisher re-evaluates both raw series and dependencies, binds the exact
  current bundle to the canonical series, checks current on-disk artifact
  chain, and publishes file-addressed canonical and ticket packs.

## Canonical identity

- Research revision: 1.
- Goal: `goal_00THNQYSRE841R1201M1MSPWPR`.
- Campaign: `rcamp_6P8Q5BC9SE6NXD8501M1MSPWPR`.
- Evaluation: `reval_94X52VCQDV30J84Z01M1MSPWRD`.
- Chain: `027c456355d30f760dc4fe077c29c619a91db1fd7d26f31f2a6cb9f18210b313`.
- Canonical pack file SHA: `4604abf3a74d6b96dca2ad4d827ec9f9be631f09cfcfd0111498973bdf6f6862`.
- Canonical payload SHA: `4dcba212c64ba40ff8e0233222d09f1f9a4b022f73b570a90c5fb9cd5824c1a2`.

Exact paths, ticket-pack digests, dependency proofs and per-file hash registry:
[evaluation-record.json](../research/tickets/stage-1/S1-011/evaluation-record.json).
The frozen Phase A bundle/candidate retains its historical "Phase B required"
wording; this report and the DB-derived evaluation record document completion
of that step. The original evidence was not rewritten to manufacture closure.

## Limits and handoff

- S1-012: calibrate independence, correlation/Sybil resistance and evidence units.
- S1-013: measure real operator comprehension, workload and approval fatigue.
- Cyclic attack graphs and SHACL mapping of richer relations remain unproven.
- Same-host deterministic models, not production concurrency/persistence tests
  or an external audit. No new production claims.

Changes are local to branch `codex/s1-011-knowledge-gate` in
`.codex-work/s1-011-task`. Main was not merged or modified; unrelated user
changes were preserved. No push performed.
