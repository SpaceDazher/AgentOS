# S1-006 — QA2 execution backend: in-process scheduler versus durable-execution engine

**Wave 2 · Priority 1 · Owner: architecture · Deps: S1-002 + S1-005 (done)**

## Research question

Which execution backend best preserves task/run durability, checkpoint/resume,
deterministic testing, and acceptable latency: the in-process scheduler or a
durable-execution engine?

## Decision (QA2)

Keep the **in-process scheduler** as the MVP execution backend for the
Coordinator. It best preserves single-host task/run durability, sha-verified
checkpoint/resume, deterministic testing, and acceptable latency (S1-002 p99
≤ 7.4 ms cold) against the tested evidence. The ticket sets a **backend
boundary**, a **measured migration trigger**, a **rollback trigger**, and
**evidence requirements** for any future durable-execution change. No
production durable-execution engine is installed; durable-engine latency and
recovery cells are explicit `unavailable` labels in this offline environment.

## Files

| File | Purpose |
|---|---|
| `bundle.json` | FLOW-11 research bundle (config, 14 verified sources, 18 claims, 11 artifacts, audit, 2 probes) |
| `replay_resume_probe.py` | Executable replay/resume safety probe (crash-A/B/C/D, duplicate-effect guard, checkpoint corruption, dependency ordering, source-hash re-verification) |
| `comparability_probe.py` | Executable comparability probe (same-DAG + crash-recovery rule, near-miss rejection, QA2 matrix checks, live engine benchmark) |
| `probe-results.json` | Probe verdicts + live benchmark observations (regenerated on every run) |
| `README.md` | This file |

## Evidence

- **Sources (all verified, ≥3 classes):** architecture (spec/SPEC.md,
  AGENTS.md, engine.py, gateway.py, journal.py, S1-005 bundle), formal
  lifecycle (S1-004 bundle + invariant simulation, Azure Durable Functions
  docs), benchmark/method (S1-002 raw results + benchmark harness, S1-005
  probe, Temporal docs/whitepaper). Repo-local hashes are real SHA-256 from
  disk, re-verified by the replay-resume probe.
- **4+ crash/replay scenarios:** crash-before-publish (CRASH-A), unknown
  outcome (CRASH-B), mid-DAG crash (CRASH-C), crash-during-resume (CRASH-D),
  duplicate-effect near-miss, checkpoint corruption.
- **3 load levels:** 10 / 34 / 100 events per second, same task DAG across
  backends, p95/p99 + recovery-time observations (in-process, measured) or
  explicit `unavailable` labels (durable engine).

## Validation

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-006 QA2 execution backend in process versus durable engine" --bundle "research/tickets/stage-1/S1-006/bundle.json" --db ".agentos-research/platform-stage-1"
```

Last evaluation: **`pass_with_limits`** (goal `goal_0Y5RC32BDZ4P42J801M1K83GR7`);
both probes `pass`. Probes run offline in < 60 s each (full budget < 120 s).

## Scope / non-scope

Scope: checkpoint/resume, crash/retry, idempotency, scheduling latency,
operator visibility, test determinism, dependency-ready task execution.
Non-scope: production vendor integration, changing the current core runtime,
claiming durability beyond tested evidence.