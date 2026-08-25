---
title: SLOQUAL-001 production-like SLO qualification
id: sloqual-001
aliases:
  - SLOQUAL-001
  - Production SLO qualification extending S1-002
tags:
  - agentos/research
  - agentos/stage-1
  - agentos/slo
created_at: 2026-08-24
stage: 1
status: IN_PROGRESS
owner: capacity
extends: "[[S1-002]]"
security_gate: "[[S1-008]]"
ticket_dir: research/tickets/stage-1/SLOQUAL-001
---

# SLOQUAL-001 — production-like SLO qualification

[[S1-002]] measured the **local** control-plane benchmark envelope (2 s
trials). This ticket extends it into a reproducible qualification process:
frozen [[SLOQUAL-001 contract|SLO contract v1.0.1]], 17 mandatory scenarios,
open-loop load generation, multi-process fault injection, and the [[S1-008]]
revocation security gate (every trial ≤5 s from durable revoke commit to
guaranteed deny at every affected instance).

Key invariants carried from the platform spec: no false ACCEPTED; transition+
audit atomicity; approvals exactly-once; untrusted content cannot expand
authority. Any violation forces `FAIL` regardless of latency or throughput.

Verdict semantics: `PASS` needs every proof including a quantitatively
mapped production-like profile, full-scale long runs (≥6 h sustained, ≥24 h
soak), ≥100 revocation trials within bound, verified hashes, and a
consistent independent rerun. Missing proofs ⇒ `PASS_WITH_LIMITS`
(itemized); violations ⇒ `FAIL`.

Harness: `src/agentos/sloqual/` (stdlib-only, ADR-0010). Comparator is
fail-closed: empty measurement sets can never yield PASS.
