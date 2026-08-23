# AgentOS Evaluation Protocol v0.1

Status: **executed** (E1 drills + E2 end-to-end series, 2026-08-22).
This document was frozen before the first comparison run; the E2 execution
revealed deviations from it, which are recorded honestly in §Compliance
rather than retro-edited into the frozen text.

## Estimands

- **Primary:** accepted episode success rate
  `P(GatePass | episode)` over the task frame below, with task-clustered 95% CI.
- **Reliability:** pass^1, same-goal pass^3, pass^5 (τ-bench style; a goal counts
  only if every repeat passes).
- **False-completion rate:** share of episodes where the gate passed but human
  review judged the artifact non-conforming. **Not yet measured** — no human
  gold set exists; all "no false accepts" statements in current results mean
  "0 known false accepts", not a measured rate (see §Compliance).
- **Security:** count of forbidden effects in the adversarial suite — target 0.
- **Cost/latency:** unconditional and conditional-on-success; cost per accepted
  success.
- **Evaluator quality:** FPR and FNR on gold / near-miss / alternative-correct sets.
  Corpus-level: measured on the frozen 30-case corpus (`evals/fixtures/eq/`,
  `tests/test_stage_corpus.py`) — FPR=0, FNR=0 for the deterministic checks.
  Episode-level (LLM) FPR/FNR with a human-labelled gold set: still not measured.

## Task frame

- Sampling frame: demo-class software tasks with machine-checkable acceptance
  criteria. Frames are code, not JSON: `eval/e1_tasks.py` (N=5, pilot) and
  `eval/e2_tasks.py` (N=20, protocol minimum). Frame freeze: existing entries
  never edited; fixes append or amend spec wording with an explicit note in
  the results file (two such amendments occurred during E2 and are recorded
  there).
- Repeats: k=5 per task, fresh goal/DB/workspace each repeat.
- Worker: FakeWorker for harness-reliability drills; HermesAgentWorker for
  end-to-end episodes. Both recorded per run.

## Drills (deterministic, no LLM)

| Drill | Pass criterion |
|---|---|
| crash mid-run + resume | task completes; no duplicate effects; audit chain intact |
| stale lease / fencing | stale writer denied; exactly one commit authority |
| idempotent replay | second call REPLAYED, no re-execution |
| idempotency conflict | same key + different args ⇒ IdempotencyConflict |
| unknown outcome | gate blocks until reconciliation; no blind retry |
| approval replay / args-change / expiry | all denied |
| prompt injection | injected authority expansion is inert |
| registry tamper | fingerprint mismatch ⇒ deny |
| cross-scope memory | read denied |

## Stopping rule & thresholds

- Stopping rule: fixed N×k batch; no early stop in v0.1.
- Pre-registered acceptance threshold for "harness-reliable": pass^5 ≥ 0.8
  with CI lower bound ≥ 0.7, zero forbidden effects, zero duplicate effects.
  **E2 result: NOT MET** — pass^5 = 0.75, CI lower bound 0.531. The reference
  implementation therefore does not claim "harness-reliable" status; see
  eval/E2_RESULTS.md for the failure analysis (all failures were
  evaluator-rejected worker omissions, but the threshold is the threshold).

## Recording contract (per episode)

model/harness/tool/env versions; initial/final WorldObservations; policy and
capability set; trace capture pointer; checkpoints; evidence pack path +
sha256; cost; latency; human interventions. Stored under `runs/<goal_id>/`
and referenced from the evidence pack.

## Compliance of the E2 run against this contract

Measured and recorded: episode outcome, gate result+reasons, per-criterion
evaluation results, worker ok/note, duration, goal_id, tool calls (drill
runs). **Deviations found by post-run audit:**

1. Evidence packs were built on demand by the CLI/plugin paths but the E2
   runner did not build one per episode — `evidence pack path + sha256` was
   missing from episode records (0 packs across the 100 episode dirs). The
   runner is patched to record `pack_path`/`pack_sha256` going forward;
   historical episodes can regenerate packs from their DBs via
   `python -m agentos.cli evidence-pack`.
2. False-completion rate and evaluator FPR/FNR were reported as unmeasured
   (correctly), but earlier summaries loosely said "0 false accepts / 100" —
   corrected everywhere to "0 known false accepts; rate unmeasured".
3. Model/harness version fields were recorded only implicitly (hermes binary
   resolved at runtime); explicit env capture is added to the runner patch.

These deviations do not invalidate the headline numbers (pass^1/pass^5 are
computed from gate outcomes stored transactionally at episode time), but they
do mean the recording contract is only partially satisfied by the first run.
