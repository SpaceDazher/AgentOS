---
title: Revocation gate evidence (S1-008 via SLOQUAL-001)
id: sloqual-001-revocation-gate
tags:
  - agentos/security
  - agentos/stage-1
  - agentos/slo
created_at: 2026-08-24
related:
  - "[[SLOQUAL-001]]"
  - "[[S1-008]]"
  - "[[S1-002]]"
---

# Revocation gate — how SLOQUAL-001 measures [[S1-008]]

Core AgentOS grants run capabilities through the in-memory RunContext and has
durable revocation only for exact-action approvals. SLOQUAL-001 therefore
ships a reference **durable capability ledger** (`agentos.sloqual.revocation`):
GRANTED→REVOKED flips commit together with an append-only revocation event in
ONE SQLite transaction; the commit point is read strictly after COMMIT
returns.

Trial protocol (per trial): durable GRANT → all three gateway worker
processes confirm allow → durable REVOKE → each instance must observe DENY;
trial value = max(first-deny offset across instances) from the durable commit.
Any successful operation after the commit is a capability-scope violation and
forces FAIL for the whole ticket regardless of other results.

Additional checks: restart of a revoked instance must NOT resurrect the
capability; background loaders at nominal/burst levels exercise revocation
under real concurrent load; ≥100 trials across seeds × load levels.

Cross-process timing uses time.perf_counter_ns (QPC-backed on Windows,
CLOCK_MONOTONIC on Linux — same-host comparable), with wall-clock
time.time_ns recorded alongside as a cross-check.

Findings so far are recorded in `reports/REPORT.md` of the ticket package.
