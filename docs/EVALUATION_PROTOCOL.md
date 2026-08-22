# AgentOS Evaluation Protocol v0.1 (draft — fix before first comparison)

> Rule: this protocol is frozen BEFORE any comparison run. Numbers marked TBD
> do not exist yet; the reference implementation has never been evaluated.

## Estimands

- **Primary:** accepted episode success rate
  `P(GatePass | episode)` over the task frame below, with task-clustered 95% CI.
- **Reliability:** pass^1, same-goal pass^3, pass^5 (τ-bench style; a goal counts
  only if every repeat passes).
- **False-completion rate:** share of episodes where the gate passed but human
  review judged the artifact non-conforming.
- **Security:** count of forbidden effects in the adversarial suite — target 0.
- **Cost/latency:** unconditional and conditional-on-success; cost per accepted
  success.
- **Evaluator quality:** FPR and FNR on gold / near-miss / alternative-correct sets.

## Task frame

- Sampling frame: demo-class software tasks (small library/CLI features with
  machine-checkable acceptance criteria), drawn from a fixed public list
  (`demo/tasks.json`, to be created before E1) — N=20 tasks minimum.
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
- Acceptance threshold for "harness-reliable": pass^5 ≥ 0.8 with CI lower bound
  ≥ 0.7, zero forbidden effects, zero duplicate effects. **TBD-pending-first-data**
  — revisit after E1 before any external claim.

## Recording contract (per episode)

model/harness/tool/env versions; initial/final WorldObservations; policy and
capability set; trace capture pointer; checkpoints; evidence pack path + sha256;
cost; latency; human interventions. Stored under `runs/<goal_id>/` and referenced
from the evidence pack.

## Ablation policy

Every complexity addition (multi-agent, memory services, routing, extra gates)
requires a pre-registered ablation at matched resources before it becomes a
default. No component ships as "production-ready" without measured SLOs and the
reliability numbers above.
