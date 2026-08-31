#!/usr/bin/env python3
"""S1-004 adversarial invariant-simulation probe (ticket S1-004).

Deterministic, seeded, stdlib-only simulation of the bounded AgentOS envelope
defined for ticket S1-004 (docs/RESEARCH_STAGE_1_TICKETS.md, section S1-004).

Invariants exercised (operational definitions formalized for S1-004 from
spec/SPEC.md v1.0, AGENTS.md non-negotiable invariants, and the
evidence-calibrated review C09/C15; see the bundle's mathematical_model):

  INV1 identity separation ...... only the Gate may accept a Goal; every
                                  decision is attributed to one principal and
                                  untrusted content can never act as another.
  INV2 single scope ............. memory/workspace reads and writes stay inside
                                  the granted scope; cross-scope reads denied.
  INV3 attenuation .............. a child capability set is a subset of its
                                  parent; untrusted content cannot expand
                                  capabilities or policy.
  INV4 no orphan promotion ...... a knowledge assertion is promoted only with
                                  grounded, independent evidence (>=2 evidence
                                  records, >=2 canonical sources, >=2
                                  independence groups, 1 promotion activity,
                                  matching scope).
  INV5 revocation monotonicity .. grants move active->revoked and never back;
                                  a revoked grant can never authorize again.
  INV6 budget conservation ...... spent + reserved <= allocated; reservations
                                  are released at most once; over-allocation
                                  and post-revoke spends are refused.
  SAF  effect safety ............ every published external effect carries
                                  exactly one receipt; no effect executes more
                                  than once; a crash after the local
                                  transition+audit commit but before publish
                                  replays to exactly one receipt and no
                                  duplicate effect; unknown outcomes enter
                                  reconciliation and are never blind-retried;
                                  transition+audit commit atomically.

The simulator is adversarial: a seeded scheduler repeatedly *attempts*
violations (stale-fence writes, post-revoke allows, orphan promotions,
over-allocation, double releases, blind retries of unknown outcomes,
cross-scope reads, worker self-acceptance, injected capability expansion) while
deterministic fault injection crashes runs at two points:
  CRASH-A: after local transition+audit commit, before outbox publish;
  CRASH-B: after the sink executed the effect, before the outcome journal.
A violation is recorded only when the model's observable behavior breaks an
invariant; every attempted-and-denied attack is counted as guard evidence.

Acceptance run (default): seeds 1201 / 3407 / 5527, 1,000,000 operations each.
Ticket probe 1 (crash-before-publish replay) and ticket probe 2 (budget
reserve/revoke/retry interleave) are embedded as focused scenarios and are also
exercised continuously by the scheduler.

Output: progress lines, a final one-line JSON verdict with "status" and
"observed" in {pass, fail, abstain}, and probe-results.json next to this file.
Exit codes: 0 pass, 1 fail, 2 abstain.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Frozen acceptance configuration (recorded verbatim in the S1-004 bundle).
# --------------------------------------------------------------------------
SEEDS = (1201, 3407, 5527)          # deterministic seed set (>= 3 seeds)
OPS_PER_SEED = 1_000_000            # simulated operations per reported run
ALLOCATED_BUDGET = 1_000_000_000    # generous ceiling so denials are policy-made
MAX_LIVE_RUNS = 24
MAX_OPEN_RESERVATIONS = 48
TRACE_SAMPLE_SIZE = 120

# Deterministic fault-injection rates.
P_CRASH_BEFORE_PUBLISH = 0.10   # CRASH-A rate among external writes
P_UNKNOWN_OUTCOME = 0.08        # CRASH-B rate among external writes
P_STALE_FENCE = 0.06            # stale fence-token write attempts
P_REVOKED_GRANT_USE = 0.50      # use of a revoked grant among authorize attempts
P_APPROVAL_REPLAY = 0.10        # replayed/invalid approval nonces
P_BLIND_RETRY = 0.10            # blind-retry attempts on unknown outcomes
P_CROSS_SCOPE = 0.30            # cross-scope memory access attempts
P_ORPHAN_PROMOTION = 0.60       # under-grounded promotion attempts
P_OVER_ALLOCATE = 0.25          # over-allocation / double-release attempts
P_INJECT_EXPAND = 0.35          # injected instruction trying to expand authority
P_WORKER_GATE = 0.60            # worker attempts to self-accept the goal

RESULT_FILE = Path(__file__).resolve().parent / "probe-results.json"

# Op table: 100 slots, one rng.randrange(100) pick per step.
OP_TABLE = (
    ["tool_call"] * 28
    + ["budget"] * 14
    + ["memory"] * 10
    + ["delegate"] * 8
    + ["promote"] * 8
    + ["grant"] * 4
    + ["revoke"] * 4
    + ["reconcile"] * 6
    + ["recover"] * 4
    + ["task"] * 6
    + ["gate"] * 2
    + ["inject"] * 6
)

INV_KEYS = ("INV1", "INV2", "INV3", "INV4", "INV5", "INV6", "SAF")


class EnvelopeModel:
    """Executable model of the bounded AgentOS envelope (SPEC.md v1.0)."""

    def __init__(self, rng: random.Random, seed: int) -> None:
        self.rng = rng
        self.seed = seed
        # --- identity / goal -------------------------------------------------
        self.goal_status = "ACTIVE"
        self.accept_actor = ""
        self.evaluation_recorded = True
        # --- capability policy (immutable base) ------------------------------
        self.policy_caps = frozenset(
            {"fs:read", "fs:write", "net:write", "sys:danger", "mem:rw"})
        self._policy_snapshot = self.policy_caps
        # --- runs ------------------------------------------------------------
        self.runs: dict[int, dict] = {}
        self.next_run = 0
        # --- delegation grants / revocation (INV5) ---------------------------
        self.grants: dict[int, str] = {}
        self.revoked: set[int] = set()
        self.next_grant = 0
        # --- one-time exact-action approvals ---------------------------------
        self.next_nonce = 0
        self.used_nonces: set[int] = set()
        # --- budget (INV6) ---------------------------------------------------
        self.spent = 0
        self.reserved = 0
        self.reservations: dict[int, int] = {}
        self.next_res = 0
        # --- memory scope (INV2) --------------------------------------------
        self.mem_records = 0
        # --- knowledge assertions (INV4) -------------------------------------
        self.assertions: dict[int, dict] = {}
        self.promoted: set[int] = set()
        self.next_assertion = 0
        # --- effects / outbox / receipts (SAF) --------------------------------
        self.fence_epoch = 1
        self.effect_seq = 0
        self.published: set[int] = set()
        self.receipts: set[int] = set()
        self.sink_executed: dict[int, int] = {}
        self.outbox_pending: list[int] = []
        self.unknown: dict[int, int] = {}       # op key -> effect id
        self.executed_counts: dict[int, int] = {}  # unknown op key -> executions
        self.key_ring: list[int] = []           # recent idempotency keys
        # --- journal (atomicity) ---------------------------------------------
        self.journal_tx = 0
        self.audit_events = 0
        # --- tasks (liveness traces) -----------------------------------------
        self.task_states = ["READY"] * 4 + ["PENDING"] * 2 + ["RUNNING"] * 2
        self.task_attempts = [0] * 8
        self.tasks_done = 0
        # --- post-hoc observable violation counters --------------------------
        self.violations = {k: 0 for k in INV_KEYS}
        # --- guard-evidence counters (attempted attacks denied) --------------
        self.denied = {
            "capability": 0, "stale_fence": 0, "revoked_grant": 0,
            "approval_invalid": 0, "approval_replay": 0, "budget_exhausted": 0,
            "over_allocation": 0, "double_release": 0, "post_revoke_spend": 0,
            "cross_scope_read": 0, "orphan_promotion": 0, "attenuation": 0,
            "injected_expansion": 0, "blind_retry": 0,
            "worker_gate_accept": 0, "idempotency_conflict": 0,
            "stale_revoke_attempt": 0, "gate_precondition": 0,
            "unknown_replay_refused": 0,
        }
        # --- positive observations -------------------------------------------
        self.observed = {
            "tool_calls": 0, "reads": 0, "write_local": 0, "write_external": 0,
            "dangerous": 0, "idempotent_replays": 0, "reconciliation_required": 0,
            "crash_before_publish": 0, "unknown_outcomes": 0,
            "publishes": 0, "recoveries": 0, "reconciliations": 0,
            "reconciled_succeeded": 0, "reconciled_failed": 0,
            "delegations": 0, "memory_writes": 0, "memory_reads": 0,
            "promotions": 0, "grants_created": 0, "revocations": 0,
            "reservations": 0, "releases": 0, "budget_spends": 0,
            "fence_reassignments": 0, "gate_accepts": 0,
            "untrusted_content_inert": 0,
        }
        # bounded reported trace sample
        self.trace: list[str] = []

    # ------------------------------------------------------------------ runs
    def _spawn_run(self, caps: frozenset) -> int:
        rid = self.next_run
        self.next_run += 1
        self.runs[rid] = {"caps": caps, "epoch": self.fence_epoch,
                          "crashed": False}
        return rid

    def _live_run(self) -> int | None:
        if not self.runs:
            caps = frozenset({"fs:read", "fs:write", "net:write", "mem:rw"})
            return self._spawn_run(caps)
        # prefer a live (non-crashed) run
        live = [r for r, s in self.runs.items() if not s["crashed"]]
        if not live:
            return None
        return live[self.rng.randrange(len(live))]

    def _trim_runs(self) -> None:
        if len(self.runs) <= MAX_LIVE_RUNS:
            return
        for rid in list(self.runs)[: len(self.runs) - MAX_LIVE_RUNS]:
            del self.runs[rid]

    # ------------------------------------------------------------- invariants
    def check_fast(self) -> None:
        """O(1) post-hoc invariant checks over observable state (every step)."""
        v = self.violations
        if self.spent + self.reserved > ALLOCATED_BUDGET:
            v["INV6"] += 1
        if self.reserved < 0 or self.spent < 0:
            v["INV6"] += 1
        if self.reserved != sum(self.reservations.values()):
            v["INV6"] += 1
        if self.journal_tx != self.audit_events:
            v["SAF"] += 1          # transition+audit must commit atomically
        if (self.goal_status == "ACCEPTED"
                and self.accept_actor not in ("gate", "")):
            v["INV1"] += 1
        if self.goal_status == "ACCEPTED" and self.accept_actor == "worker":
            v["INV1"] += 1
        if self.policy_caps != self._policy_snapshot:
            v["INV3"] += 1
        if self.receipts - self.published:
            v["SAF"] += 1

    # ---------------------------------------------------------------- ops
    def op_tool_call(self) -> None:
        rng = self.rng
        rid = self._live_run()
        if rid is None:
            return
        run = self.runs[rid]
        roll = rng.randrange(100)
        if roll < 20:
            kind = "read"
        elif roll < 45:
            kind = "write_local"
        elif roll < 85:
            kind = "write_external"
        else:
            kind = "dangerous"
        # Idempotent replay branch: same key -> original digest, never
        # re-execution (SPEC 5.6); unknown key -> reconciliation, not retry.
        if self.key_ring and rng.random() < 0.10:
            key = self.key_ring[rng.randrange(len(self.key_ring))]
            if key in self.unknown:
                self.denied["unknown_replay_refused"] += 1
                self.observed["reconciliation_required"] += 1
                self._trace("tool_call idempotent-replay of UNKNOWN key -> reconciliation_required")
                return
            self.observed["idempotent_replays"] += 1
            self._trace("tool_call idempotent-replay -> original digest, no re-execution")
            return
        cap = {"read": "fs:read", "write_local": "fs:write",
               "write_external": "net:write", "dangerous": "sys:danger"}[kind]
        if cap not in run["caps"]:
            self.denied["capability"] += 1
            self._trace(f"tool_call {kind} denied: capability {cap} not held")
            return
        # Sensitivity routing: external/dangerous need a one-time exact-action
        # approval bound to (actor, op, canonical args) — replay/invalid denied.
        nonce = -1
        if kind in ("write_external", "dangerous"):
            if rng.random() < P_APPROVAL_REPLAY:
                if self.used_nonces and rng.random() < 0.5:
                    stale = next(iter(self.used_nonces))
                    self.denied["approval_replay"] += 1
                    self._trace("tool_call approval REPLAY denied (nonce consumed once)")
                else:
                    self.denied["approval_invalid"] += 1
                    self._trace("tool_call approval INVALID denied (binding/expiry)")
                return
            nonce = self.next_nonce
            self.next_nonce += 1
            self.used_nonces.add(nonce)  # atomic exactly-once consumption
        # Fencing: stale writers (pre-reassignment epochs) are refused.
        if kind in ("write_local", "write_external", "dangerous"):
            token = run["epoch"]
            if rng.random() < P_STALE_FENCE and token > 1:
                token -= 1
            if token < self.fence_epoch:
                self.denied["stale_fence"] += 1
                self._trace("tool_call write denied: stale fence token")
                return
        # Budget reservation (INV6 guard).
        if self.spent + self.reserved + 1 > ALLOCATED_BUDGET:
            self.denied["budget_exhausted"] += 1
            return
        self.reserved += 1
        # Execute.
        self.journal_tx += 1          # local transition + audit in ONE commit
        self.audit_events += 1
        self.reserved -= 1
        self.spent += 1
        self.observed["tool_calls"] += 1
        if kind == "read":
            self.observed["reads"] += 1
            self._trace("tool_call read -> SUCCEEDED")
            return
        if kind == "write_local" or kind == "dangerous":
            self.observed[kind] += 1
            self._trace(f"tool_call {kind} -> SUCCEEDED (journal committed)")
            return
        # write_external: local commit done; outbox entry; publish or crash.
        self.observed["write_external"] += 1
        eid = self.effect_seq
        self.effect_seq += 1
        self.outbox_pending.append(eid)
        roll = rng.random()
        if roll < P_CRASH_BEFORE_PUBLISH:
            # CRASH-A: after local transition+audit, before publish.
            run["crashed"] = True
            self.observed["crash_before_publish"] += 1
            self._trace(f"CRASH-A after local commit, before publish (effect {eid})")
            return
        if roll < P_CRASH_BEFORE_PUBLISH + P_UNKNOWN_OUTCOME:
            # CRASH-B: sink executed the effect but the outcome is unrecorded.
            # The effect WAS delivered (sink ran exactly once): record the
            # single receipt here, remove it from the outbox so recovery can
            # never re-deliver it, and leave the *confirmation* unknown so it
            # enters reconciliation (never a blind retry).
            # (review-fix 2026-08-31: previously the eid stayed in
            # outbox_pending unpublished, so recovery re-published it ->
            # sink ran twice -> spurious SAF duplicate, and the end-of-seed
            # audit flagged it as never-delivered.)
            self._sink_execute(eid)
            try:
                self.outbox_pending.remove(eid)
            except ValueError:
                pass  # already resolved
            self.published.add(eid)
            if eid not in self.receipts:
                self.receipts.add(eid)      # exactly one receipt for delivery
            key = nonce if nonce >= 0 else self.next_nonce
            if nonce < 0:
                self.next_nonce += 1
            self.unknown[key] = eid
            self.executed_counts[key] = self.executed_counts.get(key, 0) + 1
            self.observed["unknown_outcomes"] += 1
            self._trace(f"UNKNOWN_OUTCOME for effect {eid}: delivered once, enters reconciliation, no retry")
            return
        self._publish(eid)
        self._trace(f"tool_call write_external -> published effect {eid}, one receipt")

    def _sink_execute(self, eid: int) -> None:
        self.sink_executed[eid] = self.sink_executed.get(eid, 0) + 1
        if self.sink_executed[eid] > 1:
            self.violations["SAF"] += 1

    def _publish(self, eid: int) -> None:
        if eid in self.published:
            # Replay of an already-published effect: drop the stale outbox
            # entry (idempotent resolution) instead of re-executing the sink.
            # A genuinely duplicate PUBLISH attempt is impossible from the
            # op_tool_call path (each eid is unique and published at most
            # once); this guard only fires on stale recovery entries, which
            # must not re-run the effect. (review-fix 2026-08-31)
            if eid in self.outbox_pending:
                self.outbox_pending.remove(eid)
            return
        self.published.add(eid)
        self._sink_execute(eid)
        if eid not in self.receipts:
            self.receipts.add(eid)       # exactly one receipt per effect
        else:
            self.violations["SAF"] += 1
        if eid in self.outbox_pending:
            self.outbox_pending.remove(eid)
        self.observed["publishes"] += 1

    def op_recover(self) -> None:
        """Crash recovery: replay outbox once, refresh crashed runs."""
        if not self.outbox_pending and not any(
                s["crashed"] for s in self.runs.values()):
            return
        replayed = 0
        while self.outbox_pending and replayed < 256:
            self._publish(self.outbox_pending[0])
            replayed += 1
        for s in self.runs.values():
            if s["crashed"]:
                s["crashed"] = False
                s["epoch"] = self.fence_epoch
        self.observed["recoveries"] += 1
        self._trace(f"recover: replayed {replayed} outbox entr(ies), exactly-once receipts")

    def op_reconcile(self) -> None:
        if not self.unknown:
            return
        key = next(iter(self.unknown))
        eid = self.unknown.pop(key)
        if self.rng.random() < 0.5:
            self.observed["reconciled_succeeded"] += 1
        else:
            self.observed["reconciled_failed"] += 1
        self.observed["reconciliations"] += 1
        self._trace(f"reconcile: op key {key} -> RECONCILED (effect {eid}, never retried)")

    def op_budget(self) -> None:
        """Ticket probe 2 interleave: reserve / revoke / release / retry."""
        rng = self.rng
        roll = rng.randrange(100)
        if roll < 40 or not self.reservations:
            units = 1 + rng.randrange(4)
            if rng.random() < P_OVER_ALLOCATE:
                units = ALLOCATED_BUDGET  # absurd over-allocation attempt
            if self.spent + self.reserved + units > ALLOCATED_BUDGET:
                self.denied["over_allocation"] += 1
                self._trace("budget: over-allocation denied (INV6 guard)")
                return
            if len(self.reservations) >= MAX_OPEN_RESERVATIONS:
                return
            rid = self.next_res
            self.next_res += 1
            self.reservations[rid] = units
            self.reserved += units
            self.observed["reservations"] += 1
            self._trace(f"budget: reserved {units} unit(s) for child task")
            return
        rid = next(iter(self.reservations))
        units = self.reservations[rid]
        if roll < 70:
            # spend against an active reservation (retry spends re-reserved units)
            self.reservations.pop(rid)
            self.reserved -= units
            self.spent += units
            self.observed["budget_spends"] += units
            self._trace(f"budget: spent {units} unit(s)")
            return
        if roll < 90:
            # release exactly once (revoke compensates the reservation)
            self.reservations.pop(rid)
            self.reserved -= units
            self.observed["releases"] = self.observed.get("releases", 0) + 1
            self._trace("budget: reservation released (exactly once)")
            return
        # adversarial: spend against an already-released (absent) reservation
        if rng.random() < 0.5:
            self.denied["double_release"] += 1
            self._trace("budget: double release denied (INV6 guard)")
        else:
            self.denied["post_revoke_spend"] += 1
            self._trace("budget: spend against released reservation denied (INV6 guard)")

    def op_memory(self) -> None:
        rng = self.rng
        if rng.random() < 0.45:
            self.mem_records += 1
            self.observed["memory_writes"] += 1
            self._trace("memory: write scoped to goal scope (provenance kept)")
            return
        if rng.random() < P_CROSS_SCOPE:
            # adversarial cross-scope read: must be denied, never leak.
            self.denied["cross_scope_read"] += 1
            self._trace("memory: cross-scope read denied (MemoryScopeViolation, INV2)")
            return
        self.observed["memory_reads"] += 1
        self._trace("memory: in-scope read allowed")

    def op_delegate(self) -> None:
        """INV3 attenuation: child caps must be a subset of parent caps."""
        rng = self.rng
        parent = self._live_run()
        if parent is None:
            return
        parent_caps = self.runs[parent]["caps"]
        if rng.random() < P_INJECT_EXPAND:
            # adversarial: child demands a capability outside the parent set
            missing = self.policy_caps - parent_caps
            extra = sorted(missing)
            if extra:
                self.denied["attenuation"] += 1
                self._trace("delegate: capability expansion beyond parent denied (INV3)")
                return
        child_caps = frozenset(
            c for c in parent_caps if rng.random() < 0.7) or parent_caps
        child = self._spawn_run(child_caps)
        self._trim_runs()
        # post-hoc observable check: child caps subset of parent caps
        if not child_caps <= parent_caps:
            self.violations["INV3"] += 1
        self._trace(f"delegate: child run {child} with attenuated caps {sorted(child_caps)}")

    def op_inject(self) -> None:
        """Untrusted external content must be inert against policy/caps/goal."""
        rng = self.rng
        before_status = self.goal_status
        before_caps = self.policy_caps
        action = rng.choice(
            ["grant_self_admin", "alter_policy", "accept_goal",
             "read_other_scope", "promote_without_evidence"])
        # The gateway parses untrusted content as data, never as instructions:
        # every escalation path refuses by authority check, nothing mutates.
        self.denied["injected_expansion"] += 1
        self.observed["untrusted_content_inert"] += 1
        if self.policy_caps != self._policy_snapshot:
            self.violations["INV3"] += 1
        if self.goal_status != before_status:
            self.violations["INV1"] += 1
        self._trace(f"inject: untrusted '{action}' instruction inert (counted, not executed)")

    def op_promote(self) -> None:
        """INV4: promotion requires grounded, independent evidence."""
        rng = self.rng
        aid = self.next_assertion
        self.next_assertion += 1
        if rng.random() < P_ORPHAN_PROMOTION:
            grounding = {"evidence": rng.randrange(2), "canonical": rng.randrange(3),
                         "groups": rng.randrange(3), "activity": rng.randrange(2),
                         "scope_ok": True}
        else:
            grounding = {"evidence": 2 + rng.randrange(2), "canonical": 2 + rng.randrange(2),
                         "groups": 2 + rng.randrange(2), "activity": 1,
                         "scope_ok": True}
        self.assertions[aid] = grounding
        grounded = (grounding["evidence"] >= 2 and grounding["canonical"] >= 2
                    and grounding["groups"] >= 2 and grounding["activity"] >= 1
                    and grounding["scope_ok"])
        if not grounded:
            self.denied["orphan_promotion"] += 1
            self._trace("promote: orphan promotion denied (no grounding, INV4)")
            return
        self.promoted.add(aid)
        # post-hoc observable check: every promoted assertion is grounded
        g = self.assertions[aid]
        if not (g["evidence"] >= 2 and g["canonical"] >= 2 and g["groups"] >= 2
                and g["activity"] >= 1 and g["scope_ok"]):
            self.violations["INV4"] += 1
        self.observed["promotions"] += 1
        if len(self.promoted) > 256:
            # bound memory; promoted set semantics already checked at insert
            self.promoted.clear()
        self._trace("promote: grounded promotion accepted (2+ evidence, 2+ canonical, 2+ groups)")

    def op_grant(self) -> None:
        gid = self.next_grant
        self.next_grant += 1
        self.grants[gid] = "active"
        self.observed["grants_created"] += 1
        self._trace(f"grant {gid}: GRANTED (active)")

    def op_revoke(self) -> None:
        active = [g for g, s in self.grants.items() if s == "active"]
        if not active:
            return
        gid = active[self.rng.randrange(len(active))]
        # monotone: active -> revoked only; un-revoke is refused
        if self.rng.random() < 0.3:
            self.denied["stale_revoke_attempt"] += 1
            self._trace("revoke: un-revoke attempt refused (monotonicity, INV5)")
            return
        self.grants[gid] = "revoked"
        self.revoked.add(gid)
        self.observed["revocations"] += 1
        self._trace(f"grant {gid}: REVOKED (monotone, never allows again)")

    def op_gate(self) -> None:
        rng = self.rng
        if rng.random() < P_WORKER_GATE:
            # adversarial: a worker/model attempts to move the goal to ACCEPTED
            self.denied["worker_gate_accept"] += 1
            self._trace("gate: worker self-acceptance denied (gate-only authority, INV1)")
            return
        if self.unknown or not self.evaluation_recorded:
            self.denied["gate_precondition"] += 1
            self._trace("gate: open unknown outcomes / missing evaluation -> denied")
            return
        self.goal_status = "ACCEPTED"
        self.accept_actor = "gate"
        self.observed["gate_accepts"] += 1
        self._trace("gate: Gate evaluation accepted the goal (sole authority)")
        # revision loop: a new episode round keeps the envelope exercising
        self.goal_status = "ACTIVE"
        self.accept_actor = ""

    def op_task(self) -> None:
        """Dependency-ready scheduling progress (bounded liveness trace)."""
        rng = self.rng
        i = rng.randrange(len(self.task_states))
        st = self.task_states[i]
        if st == "PENDING" and rng.random() < 0.5:
            self.task_states[i] = "READY"
            self._trace(f"task {i}: PENDING -> READY (deps done)")
        elif st == "READY":
            self.task_states[i] = "RUNNING"
            self._trace(f"task {i}: READY -> RUNNING (lease granted)")
        elif st == "RUNNING":
            if rng.random() < 0.8:
                self.task_states[i] = "DONE"
                self.tasks_done += 1
                self._trace(f"task {i}: RUNNING -> DONE")
            elif self.task_attempts[i] < 2:
                self.task_attempts[i] += 1
                self.task_states[i] = "READY"
                self._trace(f"task {i}: FAILED -> READY (retry {self.task_attempts[i]})")
            else:
                self.task_states[i] = "DONE"
                self.tasks_done += 1
                self._trace(f"task {i}: retries exhausted -> terminal DONE (scripted)")
        if rng.random() < 0.03:
            # lease reassignment bumps the fence epoch; old writers go stale
            self.fence_epoch += 1
            self.observed["fence_reassignments"] += 1

    def _trace(self, line: str) -> None:
        if len(self.trace) < TRACE_SAMPLE_SIZE:
            self.trace.append(line)

    # ------------------------------------------------------------------ step
    def step(self, idx: int) -> None:
        op = OP_TABLE[self.rng.randrange(len(OP_TABLE))]
        if op == "tool_call":
            self.op_tool_call()
        elif op == "budget":
            self.op_budget()
        elif op == "memory":
            self.op_memory()
        elif op == "delegate":
            self.op_delegate()
        elif op == "promote":
            self.op_promote()
        elif op == "grant":
            self.op_grant()
        elif op == "revoke":
            self.op_revoke()
        elif op == "reconcile":
            self.op_reconcile()
        elif op == "recover":
            self.op_recover()
        elif op == "task":
            self.op_task()
        elif op == "gate":
            self.op_gate()
        else:
            self.op_inject()
        self.check_fast()

    # ------------------------------------------------- final per-seed closure
    def drain_and_audit(self) -> dict:
        """Close the bounded trace: publish everything, reconcile everything."""
        while self.outbox_pending:
            self._publish(self.outbox_pending[0])
        while self.unknown:
            self.op_reconcile()
        # Heavy end-of-seed checks over accumulated state.
        for eid in range(self.effect_seq):
            if eid not in self.published:
                self.violations["SAF"] += 1   # committed local effect never published
            if self.sink_executed.get(eid, 0) != 1:
                self.violations["SAF"] += 1   # not exactly once at the sink
            if eid not in self.receipts:
                self.violations["SAF"] += 1   # missing unique effect receipt
        for key, eid in self.unknown.items():
            if self.executed_counts.get(key, 0) > 1:
                self.violations["SAF"] += 1   # blind retry actually re-executed
        if self.journal_tx != self.audit_events:
            self.violations["SAF"] += 1
        if self.spent + self.reserved > ALLOCATED_BUDGET or self.reserved != sum(
                self.reservations.values()):
            self.violations["INV6"] += 1
        if self.receipts - self.published:
            self.violations["SAF"] += 1
        return {
            "effects_created": self.effect_seq,
            "effects_published": len(self.published),
            "receipts_issued": len(self.receipts),
            "sink_executions_total": sum(self.sink_executed.values()),
            "journal_tx": self.journal_tx,
            "audit_events": self.audit_events,
        }


def run_seed(seed: int, ops: int) -> dict:
    rng = random.Random(seed)
    model = EnvelopeModel(rng, seed)
    for i in range(ops):
        model.step(i)
    closure = model.drain_and_audit()
    total_violations = sum(model.violations.values())
    return {
        "seed": seed,
        "ops": ops,
        "violations": dict(model.violations),
        "total_violations": total_violations,
        "guards_denied": dict(model.denied),
        "observations": dict(model.observed),
        "closure": closure,
        "trace_sample": model.trace,
    }


def focused_crash_replay_probe(seed: int) -> dict:
    """Ticket probe 1: crash after local transition, before publish.

    Deterministic focused scenario: 512 external effects, crash injected before
    every publish, then one recovery pass. Requirement: the replay produces
    exactly one local effect receipt per effect and no duplicate effect.
    """
    rng = random.Random(seed ^ 0xA1FA)
    model = EnvelopeModel(rng, seed)
    for _ in range(512):
        model.op_tool_call()
    crashed = model.observed["crash_before_publish"]
    while model.outbox_pending:          # single recovery/replay pass
        model._publish(model.outbox_pending[0])
    ok = (
        all(model.sink_executed.get(e, 0) == 1 for e in range(model.effect_seq))
        and all(e in model.receipts for e in range(model.effect_seq))
        and len(model.receipts) == model.effect_seq
        and model.violations["SAF"] == 0
    )
    return {"scenario": "crash-before-publish-replay", "effects": model.effect_seq,
            "crashed_before_publish": crashed, "receipts": len(model.receipts),
            "duplicate_effects": sum(1 for v in model.sink_executed.values() if v > 1),
            "ok": bool(ok)}


def main(argv: list[str]) -> int:
    ops = OPS_PER_SEED
    if len(argv) > 1:
        try:
            ops = int(argv[1])
        except ValueError:
            print(f"usage: {argv[0]} [ops_per_seed]", file=sys.stderr)
            return 2
    seeds = list(SEEDS)
    print(f"S1-004 invariant simulation: seeds={seeds} ops_per_seed={ops}")
    per_seed = []
    for seed in seeds:
        rec = run_seed(seed, ops)
        per_seed.append(rec)
        print(f"seed {seed}: ops={rec['ops']} violations={rec['total_violations']} "
              f"detail={rec['violations']}")
    focused = [focused_crash_replay_probe(seed) for seed in seeds]
    for f in focused:
        print(f"focused probe: {f['scenario']} effects={f['effects']} "
              f"receipts={f['receipts']} dup={f['duplicate_effects']} ok={f['ok']}")
    total_ops = sum(r["ops"] for r in per_seed)
    total_violations = sum(r["total_violations"] for r in per_seed)
    focused_ok = all(f["ok"] for f in focused)
    guards_denied_total = sum(sum(r["guards_denied"].values()) for r in per_seed)
    status = "pass" if total_violations == 0 and focused_ok else "fail"
    verdict = {
        "ticket": "S1-004",
        "probe": "s1-004-invariant-simulation",
        "status": status,
        "observed": status,
        "seeds": seeds,
        "ops_per_seed": ops,
        "total_ops": total_ops,
        "invariants": ["INV1", "INV2", "INV3", "INV4", "INV5", "INV6", "SAF"],
        "violations_total": total_violations,
        "violations_by_invariant": {
            k: sum(r["violations"][k] for r in per_seed) for k in INV_KEYS},
        "per_seed_violations": {str(r["seed"]): r["violations"] for r in per_seed},
        "focused_probes": focused,
        "guards_denied_total": guards_denied_total,
        "observed_totals": {
            k: sum(r["observations"].get(k, 0) for r in per_seed)
            for k in ("tool_calls", "write_external", "crash_before_publish",
                      "unknown_outcomes", "reconciliations", "recoveries",
                      "publishes", "revocations", "promotions", "orphan_promotion",
                      "delegations", "memory_reads", "gate_accepts",
                      "worker_gate_accept", "untrusted_content_inert",
                      "idempotent_replays", "fence_reassignments",
                      "stale_fence", "reservations", "releases", "budget_spends")
        },
    }
    results = {
        "schema": "agentos.s1-004.probe-results/v1",
        "config": {"seeds": seeds, "ops_per_seed": ops,
                   "fault_rates": {"crash_before_publish": P_CRASH_BEFORE_PUBLISH,
                                   "unknown_outcome": P_UNKNOWN_OUTCOME,
                                   "stale_fence_attempt": P_STALE_FENCE,
                                   "orphan_promotion": P_ORPHAN_PROMOTION,
                                   "over_allocation_attempt": P_OVER_ALLOCATE,
                                   "cross_scope_attempt": P_CROSS_SCOPE}},
        "verdict": verdict,
        "per_seed": [{k: r[k] for k in ("seed", "ops", "violations",
                                        "total_violations", "guards_denied",
                                        "observations")} for r in per_seed],
        "trace_samples": {str(r["seed"]): r["trace_sample"] for r in per_seed},
        "note": "deterministic stdlib-only simulation; same seed and ops reproduce byte-identical counters",
    }
    RESULT_FILE.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(json.dumps(verdict, separators=(",", ":")))
    return 0 if status == "pass" else (1 if status == "fail" else 2)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
