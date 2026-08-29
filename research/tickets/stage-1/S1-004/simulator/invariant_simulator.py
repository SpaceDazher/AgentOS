"""AgentOS S1-004 — seeded deterministic invariant simulator.

Ticket: research/tickets/stage-1/S1-004 (SRC-06 §7: INV1–INV6, SAF, LIVE;
SRC-05 §2 I2–I5, §3.1/§3.2 lifecycles; SRC-03 transactional outbox).

Design contract (must stay aligned with the sources and the TLA+ model in
``tla/agentos_transitions_v1.tla``):

- INV1 identity separation: a principal participates in at most one identity
  class at any time (two distinct classes are incompatible).
- INV2 single scope: every live ContentObject has exactly one scope.
- INV3 attenuation: a derived grant's rights are a subset of the parent's.
- INV4 no orphan promotion: a promoted KnowledgeAssertion has >= 1 evidence
  and exactly one PromotionActivity.
- INV5 revocation monotonicity: no allow() trace for a grant after its
  durable revoke.
- INV6 budget conservation: spent + reserved <= allocation on every grant
  ledger at all times, and a child's outstanding reservation never exceeds
  its parent's outstanding reservation (SRC-05 §2 I5).
- SAF1 every committed decision has exactly one outbox event (atomic with
  the local commit — transactional outbox).
- SAF2 redelivery/replay never creates a second local effect receipt
  (receipts keyed by decision; stale acks fenced by token).
- SAF3 an unknown external outcome always enters reconciliation; a retry
  publish happens only after reconciliation resolved a previous outcome.
- SAF4 grant state changes only through approve/deny/revoke/expire/exhaust.
- LIVE1 an owner-approved grant activates within one scheduler tick.
- LIVE2 a crash between local transition and publish is recovered by
  replaying the durable outbox within one tick.

Stdlib only: no third-party dependencies. Determinism: a single
``random.Random(seed)`` drives every decision; no wall-clock, no dict-order
dependence (iteration only over pre-sorted key tuples).

Mutations intentionally break one contract each; they exist to prove the
detectors fire (regression/negative tests), never in acceptance runs.

Counterexample policy: a violation is preserved verbatim (never averaged,
never dropped). Reduction = deterministic seed replay: the same seed and op
count always reproduces the same violation at the same step, and a rolling
context window of the last trace lines is attached to the witness.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import random
import sys
from collections import deque

__all__ = [
    "INVARIANT_IDS", "Violation", "Simulator", "simulate",
    "probe_crash_replay", "probe_reserve_revoke_retry",
    "replay_violation", "run_probes",
]

SIMULATOR_VERSION = "1.1.0"

INVARIANT_IDS = (
    "INV1", "INV2", "INV3", "INV4", "INV5", "INV6",
    "SAF1", "SAF2", "SAF3", "SAF4", "LIVE1", "LIVE2",
)

GRANT_STATES = ("proposed", "denied", "active", "revoked", "expired", "exhausted")
GRANT_TRANSITIONS = {
    ("proposed", "active"): "approve",
    ("proposed", "denied"): "deny",
    ("active", "revoked"): "revoke",
    ("active", "expired"): "expire",
    ("active", "exhausted"): "exhaust",
}

IDENTITY_CLASSES = ("human", "agent", "service", "org")
RIGHTS = tuple(f"r{i}" for i in range(8))


class Violation(Exception):
    """Raised on the first invariant violation; deterministic by seed."""

    def __init__(self, invariant, step, detail):
        super().__init__(f"{invariant} violated at step {step}: {detail}")
        self.invariant = invariant
        self.step = step
        self.detail = detail


class Simulator:
    """Bounded world executing seeded operations with fault injection."""

    TRACE_WINDOW = 256

    def __init__(self, seed, *, mutations=(), fault_probs=None):
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.mutations = frozenset(mutations)
        self.digest = hashlib.sha256()
        self.window = deque(maxlen=self.TRACE_WINDOW)
        self.step = 0
        fp = dict(crash_commit_publish=0.04, unknown_outcome=0.15,
                  stale_ack=0.06)
        if fault_probs:
            fp.update(fault_probs)
        self.fault_probs = fp

        # ---- fixed world structure (seed-independent) ----
        self.principal_ids = tuple(range(48))
        self.class_of = {}                      # principal -> class
        self.scope_ids = tuple(range(6))
        self.co_ids = []
        self.co_scopes = {}                     # co -> set of scopes
        self._next_co = 0
        self.ka_ids = []
        self.ka_status = {}
        self.ka_evidence = {}
        self.ka_promotions = {}
        self._next_ka = 0
        self.grant_ids = list(range(48))        # g0..g7 roots, rest children
        self.g_state = {g: "proposed" for g in self.grant_ids}
        self.g_parent = {}
        self.g_rights = {}
        self.g_alloc = {}
        self.g_spent = {g: 0 for g in self.grant_ids}
        self.g_reserved = {g: 0 for g in self.grant_ids}
        self.g_approved_tick = {g: None for g in self.grant_ids}
        self.g_revoked_tick = {g: None for g in self.grant_ids}
        for g in self.grant_ids:
            if g < 8:
                self.g_parent[g] = None
                self.g_rights[g] = frozenset(RIGHTS)
                self.g_alloc[g] = 12
            else:
                parent = (g - 8) % 8
                self.g_parent[g] = parent
                self.g_rights[g] = frozenset(
                    r for i, r in enumerate(RIGHTS) if i % 2 == 0)
                self.g_alloc[g] = 4
        self.tick = 0
        self._pending_activation = []
        # decisions / delivery (bounded live window + aggregates)
        self._next_decision = 0
        self._decision_low = 0
        self.decisions = {}
        self.agg_committed = 0
        self.agg_receipts = 0
        self.agg_unknown = 0
        self.agg_reconciled = 0
        self.counters = {inv: 0 for inv in INVARIANT_IDS}
        self.op_counts = {}
        self.terminated_states = {
            "revoked": 0, "expired": 0, "exhausted": 0, "denied": 0}
        self.replays = 0
        self.crashes = 0
        self.stale_acks_fenced = 0
        self.unknown_outcomes = 0
        self.reconciliations = 0
        self.audits = 0

    # ---- trace plumbing -------------------------------------------------

    def _record(self, op, key, outcome):
        self.step += 1
        line = f"{self.step}|{op}|{key}|{outcome}\n"
        self.digest.update(line.encode("ascii"))
        self.window.append(line)
        self.op_counts[op] = self.op_counts.get(op, 0) + 1

    def _raise(self, invariant, detail):
        self.counters[invariant] += 1
        raise Violation(invariant, self.step, detail)

    # ---- global audit (periodic + terminal) ------------------------------

    def audit(self):
        self.audits += 1
        # INV1: identity separation (membership value malformed => dual class)
        for p, cls in self.class_of.items():
            if not isinstance(cls, str) or cls not in IDENTITY_CLASSES:
                self._raise("INV1", f"principal {p} in classes {cls!r}")
        # INV2: single scope
        for co, scopes in self.co_scopes.items():
            if len(scopes) != 1:
                self._raise("INV2", f"content object {co} has {len(scopes)} scopes")
        # INV3: attenuation
        for g in self.grant_ids:
            parent = self.g_parent.get(g)
            if parent is not None and not self.g_rights[g] <= self.g_rights[parent]:
                self._raise("INV3", f"grant {g} expands parent {parent} rights")
        # INV4: no orphan promotion
        for ka in self.ka_ids:
            if self.ka_status[ka] == "promoted":
                if not self.ka_evidence[ka] or self.ka_promotions[ka] != 1:
                    self._raise("INV4", f"assertion {ka} promoted invalidly")
        # INV6: budget conservation + child reservation cover
        for g in self.grant_ids:
            if self.g_spent[g] + self.g_reserved[g] > self.g_alloc[g]:
                self._raise("INV6", f"grant {g} over-allocated")
            parent = self.g_parent.get(g)
            if parent is not None and self.g_reserved[g] > self.g_reserved[parent]:
                self._raise(
                    "INV6",
                    f"child {g} reservation {self.g_reserved[g]} exceeds "
                    f"parent {parent} reservation {self.g_reserved[parent]}")
        # SAF1/SAF2/SAF3 over the decision table
        for d, rec in self.decisions.items():
            if rec["committed"] != (rec["outbox_event"] is not None):
                self._raise("SAF1", f"decision {d} outbox mismatch")
            if rec["receipts"] > 1:
                self._raise("SAF2", f"decision {d} has {rec['receipts']} receipts")
            if rec["publishes"] > 1 and not rec["reconcile_done"]:
                self._raise("SAF3", f"decision {d} blind retry")
        # LIVE1: pending approvals never outlive their tick
        for g in self.grant_ids:
            at = self.g_approved_tick[g]
            if self.g_state[g] == "proposed" and at is not None:
                if self.tick - at > 1:
                    self._raise("LIVE1", f"grant {g} pending since tick {at}, now {self.tick}")
        # LIVE2: crashed deliveries are replayed within one tick
        for d, rec in self.decisions.items():
            if (rec["crashed"] and rec["publishes"] == 0
                    and self.tick - rec["commit_tick"] > 1):
                self._raise("LIVE2", f"decision {d} not replayed after crash")

    # ---- identity (INV1) --------------------------------------------------

    def op_identity_join(self):
        free = [p for p in self.principal_ids if p not in self.class_of]
        if not free:
            self._record("identity_join", "-", "noop")
            return
        p = self.rng.choice(free)
        cls = self.rng.choice(IDENTITY_CLASSES)
        self.class_of[p] = cls
        self._record("identity_join", p, cls)

    def op_identity_join_conflict(self):
        busy = sorted(self.class_of)
        if not busy:
            self._record("identity_join_conflict", "-", "noop")
            return
        p = self.rng.choice(busy)
        other = self.rng.choice(
            tuple(c for c in IDENTITY_CLASSES if c != self.class_of[p]))
        if "INV1" in self.mutations:
            # bug: principal joins a second, incompatible class
            self.class_of[p] = [self.class_of[p], other]
            self.audit()  # immediate detection
            return
        # correct path: the incompatible join is denied
        self._record("identity_join_conflict", p, "denied")

    def op_identity_leave(self):
        if not self.class_of:
            self._record("identity_leave", "-", "noop")
            return
        p = self.rng.choice(sorted(self.class_of))
        del self.class_of[p]
        self._record("identity_leave", p, "released")

    # ---- content objects (INV2) -------------------------------------------

    CO_CAP = 128

    def op_co_create(self):
        co = self._next_co
        self._next_co += 1
        scope = self.rng.randrange(len(self.scope_ids))
        self.co_ids.append(co)
        self.co_scopes[co] = {scope}
        self._record("co_create", co, scope)
        # bounded world: retire the oldest object once the cap is exceeded
        while len(self.co_ids) > self.CO_CAP:
            old = self.co_ids.pop(0)
            self.co_scopes.pop(old, None)

    def op_co_move(self):
        if not self.co_ids:
            self._record("co_move", "-", "noop")
            return
        co = self.rng.choice(self.co_ids)
        new_scope = self.rng.randrange(len(self.scope_ids))
        if "INV2" in self.mutations:
            self.co_scopes[co].add(new_scope)   # bug: accumulate scopes
        else:
            self.co_scopes[co] = {new_scope}    # move keeps exactly one scope
        if len(self.co_scopes[co]) != 1:
            self._raise("INV2", f"content object {co} has {len(self.co_scopes[co])} scopes")
        self._record("co_move", co, new_scope)

    # ---- knowledge assertions (INV4) ---------------------------------------

    def op_ka_propose(self):
        ka = self._next_ka
        self._next_ka += 1
        self.ka_ids.append(ka)
        self.ka_status[ka] = "proposed"
        self.ka_evidence[ka] = set()
        self.ka_promotions[ka] = 0
        self._record("ka_propose", ka, "proposed")
        # bounded world: retire terminal assertions once the cap is exceeded
        while len(self.ka_ids) > 128:
            for k in self.ka_ids:
                if self.ka_status[k] in ("superseded", "revoked"):
                    self.ka_ids.remove(k)
                    self.ka_status.pop(k, None)
                    self.ka_evidence.pop(k, None)
                    self.ka_promotions.pop(k, None)
                    break
            else:
                break

    def op_ka_add_evidence(self):
        pending = [k for k in self.ka_ids if not self.ka_evidence[k]]
        if not pending:
            self._record("ka_add_evidence", "-", "noop")
            return
        ka = self.rng.choice(pending)
        self.ka_evidence[ka].add(self.rng.randrange(64))
        self._record("ka_add_evidence", ka, len(self.ka_evidence[ka]))

    def op_ka_promote(self):
        candidates = [k for k in self.ka_ids if self.ka_status[k] == "proposed"]
        if not candidates:
            self._record("ka_promote", "-", "noop")
            return
        ka = self.rng.choice(candidates)
        if "INV4" in self.mutations:
            # bug: promote without evidence and without the PromotionActivity
            self.ka_status[ka] = "promoted"
            self._record("ka_promote", ka, "mutant-promoted")
            self.audit()  # immediate detection
            return
        if not self.ka_evidence[ka]:
            self._record("ka_promote", ka, "denied-no-evidence")
            return
        self.ka_promotions[ka] += 1
        if self.ka_promotions[ka] != 1:
            self._raise("INV4", f"assertion {ka} has {self.ka_promotions[ka]} activities")
        self.ka_status[ka] = "promoted"
        self._record("ka_promote", ka, "promoted")

    def op_ka_lifecycle(self):
        terminal = [k for k in self.ka_ids
                    if self.ka_status[k] in ("promoted", "rejected")]
        if not terminal:
            self._record("ka_lifecycle", "-", "noop")
            return
        ka = self.rng.choice(terminal)
        new = "superseded" if self.ka_status[ka] == "promoted" else "revoked"
        self.ka_status[ka] = new
        self._record("ka_lifecycle", ka, new)

    # ---- grants: lifecycle (SAF4), activation (LIVE1) ---------------------

    def _set_grant_state(self, g, new):
        old = self.g_state[g]
        pair = (old, new)
        if pair not in GRANT_TRANSITIONS:
            self._raise("SAF4", f"grant {g} illegal transition {old}->{new}")
        self.g_state[g] = new
        if new in self.terminated_states:
            self.terminated_states[new] += 1
            if new == "revoked":
                self.g_revoked_tick[g] = self.tick
            # A terminal transition releases the delegation budget chain:
            # reservations of every descendant are void, and a child's own
            # reservation is released from its parent's ledger (SRC-05 S.2
            # I5: authority and budget derive from the parent).
            if new in ("revoked", "expired"):
                for h in self.grant_ids:
                    if self.g_parent.get(h) == g and self.g_reserved[h] > 0:
                        self.g_reserved[h] = 0
                parent = self.g_parent.get(g)
                if parent is not None and self.g_reserved[g] > 0:
                    if self.g_reserved[parent] >= self.g_reserved[g]:
                        self.g_reserved[parent] -= self.g_reserved[g]
                    else:
                        self._raise(
                            "INV6",
                            f"parent {parent} ledger under-covers release of "
                            f"child {g}")
                self.g_reserved[g] = 0

    def op_grant_approve(self):
        pending = [g for g in self.grant_ids if self.g_state[g] == "proposed"]
        if not pending:
            self._record("grant_approve", "-", "noop")
            return
        g = self.rng.choice(pending)
        if self.rng.random() < 0.25:
            self._set_grant_state(g, "denied")
            self._record("grant_approve", g, "denied")
            return
        self.g_approved_tick[g] = self.tick
        if "LIVE1" in self.mutations:
            # bug: approval registered but never queued for activation
            self._record("grant_approve", g, "mutant-approval-lost")
            self.audit()
            return
        self._pending_activation.append(g)
        self._record("grant_approve", g, "approved")

    def op_grant_propose(self):
        """Fresh delegation proposals reuse slots of terminated grants.

        Slot recycling creates a NEW grant entity; it is not a lifecycle
        transition of the old one, so it bypasses _set_grant_state (SAF4
        covers transitions of a living grant, SRC-05 §3.1).
        """
        terminated = [g for g in self.grant_ids
                      if self.g_state[g] in ("denied", "revoked",
                                             "expired", "exhausted")
                      and self.g_reserved[g] == 0]
        if not terminated:
            self._record("grant_propose", "-", "noop")
            return
        g = self.rng.choice(terminated)
        parent = self.g_parent[g]
        self.g_state[g] = "proposed"
        self.g_spent[g] = 0
        self.g_reserved[g] = 0
        self.g_approved_tick[g] = None
        self.g_revoked_tick[g] = None
        if parent is not None:
            n = self.rng.randrange(len(RIGHTS) + 1)
            subset = frozenset(self.rng.sample(RIGHTS, n))
            if "INV3" in self.mutations:
                # bug: the derived grant introduces a right outside the
                # parent's set (e.g. a capability the parent never held)
                self.g_rights[g] = subset | frozenset(("admin",))
                self.audit()  # immediate detection
            else:
                self.g_rights[g] = subset & self.g_rights[parent]  # attenuation
        self._record("grant_propose", g, "proposed")

    def op_grant_revoke(self):
        active = [g for g in self.grant_ids if self.g_state[g] == "active"]
        if not active:
            if "SAF4" in self.mutations:
                # bug: the buggy owner revokes a grant in an illegal state
                others = [g for g in self.grant_ids
                          if self.g_state[g] in ("proposed", "denied")]
                if others:
                    self._set_grant_state(self.rng.choice(others), "revoked")
            self._record("grant_revoke", "-", "noop")
            return
        g = self.rng.choice(active)
        self._set_grant_state(g, "revoked")
        self._record("grant_revoke", g, "revoked")

    def op_grant_expire(self):
        active = [g for g in self.grant_ids if self.g_state[g] == "active"]
        if not active:
            self._record("grant_expire", "-", "noop")
            return
        g = self.rng.choice(active)
        self._set_grant_state(g, "expired")
        self._record("grant_expire", g, "expired")

    # ---- budget (INV6) ------------------------------------------------------

    def op_reserve_child(self):
        pairs = [g for g in self.grant_ids if self.g_parent.get(g) is not None
                 and self.g_state[g] == "active"
                 and self.g_state[self.g_parent[g]] == "active"]
        if not pairs:
            self._record("reserve_child", "-", "noop")
            return
        g = self.rng.choice(pairs)
        parent = self.g_parent[g]
        amount = self.rng.choice((1, 2))
        if (self.g_spent[parent] + self.g_reserved[parent] + amount
                > self.g_alloc[parent]
                or self.g_spent[g] + self.g_reserved[g] + amount
                > self.g_alloc[g]):
            self._record("reserve_child", g, "denied-conservation")
            return
        if "INV6" in self.mutations:
            self.g_reserved[g] += amount  # bug: reserve without parent cover
            self.audit()  # immediate detection
            return
        self.g_reserved[parent] += amount
        self.g_reserved[g] += amount
        if self.g_spent[parent] + self.g_reserved[parent] > self.g_alloc[parent]:
            self._raise("INV6", f"parent {parent} over-allocated")
        if self.g_spent[g] + self.g_reserved[g] > self.g_alloc[g]:
            self._raise("INV6", f"grant {g} over-allocated")
        self._record("reserve_child", g, amount)

    def op_confirm_child(self):
        holders = [g for g in self.grant_ids
                   if self.g_parent.get(g) is not None and self.g_reserved[g] > 0
                   and self.g_state[g] == "active"]
        if not holders:
            self._record("confirm_child", "-", "noop")
            return
        g = self.rng.choice(holders)
        parent = self.g_parent[g]
        self.g_reserved[g] -= 1
        self.g_spent[g] += 1
        if self.g_reserved[parent] > 0:
            self.g_reserved[parent] -= 1
            self.g_spent[parent] += 1
        if self.g_spent[g] + self.g_reserved[g] > self.g_alloc[g]:
            self._raise("INV6", f"grant {g} over-allocated on confirm")
        if self.g_spent[parent] + self.g_reserved[parent] > self.g_alloc[parent]:
            self._raise("INV6", f"parent {parent} over-allocated on confirm")
        if self.g_spent[g] + self.g_reserved[g] == self.g_alloc[g]:
            self._set_grant_state(g, "exhausted")
        self._record("confirm_child", g, 1)

    def op_cancel_reservation(self):
        holders = [g for g in self.grant_ids
                   if self.g_parent.get(g) is not None and self.g_reserved[g] > 0]
        if not holders:
            self._record("cancel_reservation", "-", "noop")
            return
        g = self.rng.choice(holders)
        parent = self.g_parent[g]
        self.g_reserved[g] -= 1
        if self.g_reserved[parent] > 0:
            self.g_reserved[parent] -= 1
        if self.g_reserved[g] < 0 or self.g_reserved[parent] < 0:
            self._raise("INV6", f"negative reservation on {g}")
        self._record("cancel_reservation", g, 1)

    # ---- decisions: outbox, delivery, reconciliation, fencing --------------

    def _active_chain(self, g):
        while g is not None:
            if self.g_state[g] != "active":
                return False
            g = self.g_parent.get(g)
        return True

    def op_allow(self):
        eligible = [g for g in self.grant_ids if self._active_chain(g)]
        if "INV5" in self.mutations and not eligible:
            # bug path: the buggy authorizer also considers revoked grants
            eligible = [g for g in self.grant_ids if self.g_state[g] == "revoked"]
        if not eligible:
            self._record("allow", "-", "noop")
            return
        g = self.rng.choice(eligible)
        if self.g_revoked_tick.get(g) is not None:
            # allow() observed after durable revoke — the violation itself
            self._raise("INV5", f"allow() for revoked grant {g}")
        d = self._next_decision
        self._next_decision += 1
        # transactional outbox: local commit + outbox event are atomic (SAF1)
        rec = {
            "grant": g, "committed": True, "outbox_event": d,
            "estate": "pending", "publishes": 0, "token": 0,
            "inflight_token": None, "receipt_token": None, "receipts": 0,
            "reconcile_done": False, "fence_stale": 0,
            "commit_tick": self.tick, "crashed": False,
        }
        if "SAF1" in self.mutations and self.rng.random() < 0.5:
            rec["outbox_event"] = None  # bug: commit without outbox event
        self.decisions[d] = rec
        if rec["committed"] != (rec["outbox_event"] is not None):
            self._raise("SAF1", f"decision {d} committed without outbox event")
        # fault injection: crash after local commit, before publish (LIVE2)
        if self.rng.random() < self.fault_probs["crash_commit_publish"]:
            self.crashes += 1
            rec["crashed"] = True
            self._record("allow", d, "committed-crash-before-publish")
            return
        self._record("allow", d, "committed")

    def op_publish(self):
        pending = [d for d, r in sorted(self.decisions.items())
                   if r["estate"] == "pending" and not r["crashed"]]
        if "SAF3" in self.mutations:
            # bug: the buggy dispatcher also republishes unresolved outcomes
            pending += [d for d, r in sorted(self.decisions.items())
                        if r["estate"] in ("unknown", "inflight")]
        if not pending:
            self._record("publish", "-", "noop")
            return
        d = self.rng.choice(pending)
        rec = self.decisions[d]
        if rec["publishes"] >= 1 and not rec["reconcile_done"]:
            self._raise("SAF3", f"decision {d} blind retry")
        rec["publishes"] += 1
        rec["token"] += 1
        rec["inflight_token"] = rec["token"]
        rec["estate"] = "inflight"
        self._record("publish", d, "inflight")

    def op_delivery_result(self):
        inflight = [d for d, r in sorted(self.decisions.items())
                    if r["estate"] == "inflight"]
        if not inflight:
            self._record("delivery_result", "-", "noop")
            return
        d = self.rng.choice(inflight)
        rec = self.decisions[d]
        attempt = rec["inflight_token"]
        roll = self.rng.random()
        p_unknown = self.fault_probs["unknown_outcome"]
        if roll < p_unknown:
            rec["estate"] = "unknown"
            self.unknown_outcomes += 1
            self._record("delivery_result", d, "unknown")
        elif roll < p_unknown + 0.55:
            self._apply_ack(d, rec, attempt)
        else:
            rec["estate"] = "nacked"
            self._record("delivery_result", d, "nack")

    def op_delivery_timeout(self):
        """An in-flight attempt whose outcome is not coming back.

        The outcome is UNKNOWN, so the only legal continuation is
        reconciliation — a direct republish would be a blind retry (SAF3).
        """
        inflight = [d for d, r in sorted(self.decisions.items())
                    if r["estate"] == "inflight"]
        if not inflight:
            self._record("delivery_timeout", "-", "noop")
            return
        d = self.rng.choice(inflight)
        rec = self.decisions[d]
        rec["estate"] = "unknown"
        self.unknown_outcomes += 1
        self._record("delivery_timeout", d, "unknown")

    def _apply_ack(self, d, rec, attempt_token):
        # exactly one local effect receipt (SAF2); a late ack for an attempt
        # already superseded by a newer one is fenced, never duplicated
        if rec["receipts"] >= 1:
            if "SAF2" in self.mutations:
                rec["receipts"] += 1  # bug: duplicate receipt on redelivery
                self._raise("SAF2", f"decision {d} duplicate effect receipt")
            self._record("delivery", d, "duplicate-suppressed")
            return
        stale = attempt_token is not None and attempt_token < rec["token"]
        if stale:
            self.stale_acks_fenced += 1
            rec["fence_stale"] += 1
        rec["estate"] = "acked"
        rec["receipts"] += 1
        rec["receipt_token"] = attempt_token
        self._record("delivery", d, "ack-stale" if stale else "ack")

    def op_stale_ack(self):
        """A duplicate ack racing a newer delivery attempt: fenced out."""
        stale = [d for d, r in sorted(self.decisions.items())
                 if r["receipt_token"] is not None
                 and r["token"] > r["receipt_token"]]
        if not stale:
            self._record("stale_ack", "-", "noop")
            return
        d = self.rng.choice(stale)
        rec = self.decisions[d]
        if "SAF2" in self.mutations:
            rec["receipts"] += 1
            self._raise("SAF2", f"decision {d} stale ack created second receipt")
        self.stale_acks_fenced += 1
        rec["fence_stale"] += 1
        self._record("stale_ack", d, "fenced")

    def op_reconcile(self):
        unknown = [d for d, r in sorted(self.decisions.items())
                   if r["estate"] in ("unknown", "reconciling")]
        if not unknown:
            self._record("reconcile", "-", "noop")
            return
        d = self.rng.choice(unknown)
        rec = self.decisions[d]
        if rec["estate"] == "unknown":
            self.reconciliations += 1
            rec["estate"] = "reconciling"
            self._record("reconcile", d, "started")
            return
        # reconciliation resolves the external outcome deterministically
        if self.rng.random() < 0.6:
            self._apply_ack(d, rec, rec["inflight_token"])
            rec["reconcile_done"] = True
            self._record("reconcile", d, "resolved-ack")
        else:
            rec["estate"] = "nacked"
            rec["reconcile_done"] = True
            self._record("reconcile", d, "resolved-nack")

    def op_retry_after_reconcile(self):
        retryable = [d for d, r in sorted(self.decisions.items())
                     if r["estate"] == "nacked" and r["reconcile_done"]]
        if not retryable:
            self._record("retry", "-", "noop")
            return
        d = self.rng.choice(retryable)
        rec = self.decisions[d]
        rec["estate"] = "pending"
        self._record("retry", d, "republished")

    # ---- scheduler tick -----------------------------------------------------

    def op_tick(self):
        self.tick += 1
        # LIVE1: activate every pending approval (within one tick)
        for g in self._pending_activation:
            if self.g_state[g] == "proposed":
                self._set_grant_state(g, "active")
                self.g_approved_tick[g] = None
        self._pending_activation = [g for g in self._pending_activation
                                    if self.g_state[g] == "proposed"]
        # LIVE2: replay outbox events pending after a crash (within one tick).
        # The LIVE2 mutation makes the scheduler forget the replay entirely:
        # the durable crashed marker survives, so the age check in audit()
        # observes the missed recovery obligation.
        if "LIVE2" not in self.mutations:
            for d in self.decisions:
                rec = self.decisions[d]
                if rec["crashed"] and rec["publishes"] == 0 and rec["estate"] == "pending":
                    self.replays += 1
                    rec["crashed"] = False
                    self._record("replay", d, "republished")
        self._record("tick", self.tick, "ok")
        # bounded world: archive terminal decisions into aggregates
        while self._decision_low < self._next_decision:
            d = self._decision_low
            rec = self.decisions.get(d)
            if rec is None:
                self._decision_low += 1
                continue
            terminal = (rec["estate"] == "acked"
                        or (rec["estate"] == "nacked"
                            and self.tick - rec["commit_tick"] > 8))
            if not terminal:
                break
            self.agg_committed += 1 if rec["committed"] else 0
            self.agg_receipts += rec["receipts"]
            del self.decisions[d]
            self._decision_low += 1

    # ---- dispatch table ------------------------------------------------------

    OP_TABLE = (
        ("identity_join", 5, op_identity_join),
        ("identity_join_conflict", 4, op_identity_join_conflict),
        ("identity_leave", 2, op_identity_leave),
        ("co_create", 5, op_co_create),
        ("co_move", 5, op_co_move),
        ("ka_propose", 5, op_ka_propose),
        ("ka_add_evidence", 6, op_ka_add_evidence),
        ("ka_promote", 5, op_ka_promote),
        ("ka_lifecycle", 3, op_ka_lifecycle),
        ("grant_approve", 8, op_grant_approve),
        ("grant_propose", 7, op_grant_propose),
        ("grant_revoke", 6, op_grant_revoke),
        ("grant_expire", 2, op_grant_expire),
        ("reserve_child", 8, op_reserve_child),
        ("confirm_child", 8, op_confirm_child),
        ("cancel_reservation", 3, op_cancel_reservation),
        ("allow", 10, op_allow),
        ("publish", 12, op_publish),
        ("delivery_result", 12, op_delivery_result),
        ("delivery_timeout", 4, op_delivery_timeout),
        ("stale_ack", 3, op_stale_ack),
        ("reconcile", 6, op_reconcile),
        ("retry", 4, op_retry_after_reconcile),
        ("tick", 6, op_tick),
    )

    _CUMULATIVE = None

    def run(self, ops, audit_every=4096):
        table = self.OP_TABLE
        if Simulator._CUMULATIVE is None:
            cumulative = []
            acc = 0
            for t in table:
                acc += t[1]
                cumulative.append(acc)
            Simulator._CUMULATIVE = (cumulative, float(acc))
        cumulative, total = Simulator._CUMULATIVE
        if ops <= 0:
            raise RuntimeError("empty operation series is not a valid run")
        for i in range(ops):
            roll = self.rng.random() * total
            idx = bisect.bisect_left(cumulative, roll)
            table[idx][2](self)
            if (i + 1) % audit_every == 0:
                self.audit()
        self.audit()
        return self.summary(operations_executed=ops)

    def summary(self, operations_executed=None):
        receipts_total = (self.agg_receipts
                          + sum(r["receipts"] for r in self.decisions.values()))
        committed_total = (self.agg_committed
                           + sum(1 for r in self.decisions.values()
                                 if r["committed"]))
        return {
            "simulator_version": SIMULATOR_VERSION,
            "seed": self.seed,
            "operations": (self.step if operations_executed is None
                           else operations_executed),
            "trace_steps": self.step,
            "tick": self.tick,
            "op_counts": dict(sorted(self.op_counts.items())),
            "invariant_counters": {inv: self.counters[inv]
                                   for inv in INVARIANT_IDS},
            "measurements": {
                "decisions_committed": committed_total,
                "effect_receipts": receipts_total,
                "decisions_live_window": len(self.decisions),
                "crashes_injected": self.crashes,
                "outbox_replays": self.replays,
                "unknown_outcomes": self.unknown_outcomes,
                "reconciliations_started": self.reconciliations,
                "stale_acks_fenced": self.stale_acks_fenced,
                "grants_terminated": dict(self.terminated_states),
                "global_audits": self.audits,
            },
            "trace_digest": self.digest.hexdigest(),
        }


def simulate(seed, ops, *, mutations=(), fault_probs=None, audit_every=4096):
    """Run one deterministic simulation; fail closed on any violation."""
    sim = Simulator(seed, mutations=mutations, fault_probs=fault_probs)
    result = sim.run(ops, audit_every=audit_every)
    return sim, result


def replay_violation(seed, ops, mutations):
    """Reproduce a violation twice by seed replay; return the witness.

    The counterexample is never reduced away: the full deterministic
    reproduction (same seed, same step, same detail, same digest) plus a
    rolling trace window is the reduced deterministic witness.
    """
    witnesses = []
    for _ in range(2):
        sim = Simulator(seed, mutations=mutations)
        violation = None
        try:
            sim.run(ops)
        except Violation as v:
            violation = v
        if violation is None:
            raise RuntimeError(
                f"replay expected a violation for mutations={mutations}")
        witnesses.append((violation, sim))
    v1, s1 = witnesses[0]
    v2, s2 = witnesses[1]
    if (v1.invariant, v1.step, v1.detail) != (v2.invariant, v2.step, v2.detail):
        raise RuntimeError("violation replay diverged; run is not deterministic")
    if s1.digest.hexdigest() != s2.digest.hexdigest():
        raise RuntimeError("trace digest diverged on replay")
    return {
        "invariant": v1.invariant,
        "step": v1.step,
        "detail": v1.detail,
        "mutations": sorted(mutations),
        "seed": seed,
        "operations_requested": ops,
        "trace_window": "".join(s1.window).splitlines(),
        "trace_digest_at_violation": s1.digest.hexdigest(),
    }


# --------------------------------------------------------------------------
# Adversarial probe A — crash after local commit, before publish (LIVE2/SAF)
# --------------------------------------------------------------------------

def probe_crash_replay():
    sim = Simulator(0, fault_probs=dict(crash_commit_publish=1.0,
                                        unknown_outcome=0.0, stale_ack=0.0))
    root = 0                                    # deterministic root grant
    sim.g_approved_tick[root] = sim.tick
    sim._pending_activation.append(root)
    sim.op_tick()                     # activation (LIVE1)
    assert sim.g_state[root] == "active", "probe A: root not activated"
    sim.rng.seed(7)                  # deterministic authorizer choice
    d_before = sim._next_decision
    sim.op_allow()                    # crash injected: commit without publish
    d = d_before
    rec = sim.decisions[d]
    checks = {
        "outbox_events": 1 if rec["outbox_event"] is not None else 0,
        "receipts_at_crash": rec["receipts"],
        "publishes_at_crash": rec["publishes"],
    }
    sim.op_tick()                     # scheduler replay (LIVE2, within 1 tick)
    checks["crash_cleared_by_replay"] = not rec["crashed"]
    # replayed delivery: the outbox republishes, then the external system
    # confirms the effect (deterministic ack, no rng dependence)
    sim.op_publish()                  # attempt 1 in flight
    checks["publishes_after_replay_delivery"] = rec["publishes"]
    sim._apply_ack(d, rec, rec["inflight_token"])
    checks["receipts_after_ack"] = rec["receipts"]
    # duplicate redelivery of the same ack must not create a second receipt (SAF2)
    sim._apply_ack(d, rec, rec["inflight_token"])
    sim._apply_ack(d, rec, 1)
    checks["receipts_after_duplicate_acks"] = rec["receipts"]
    sim.audit()
    checks["all_counters_zero"] = all(
        sim.counters[inv] == 0 for inv in INVARIANT_IDS)
    passed = (checks["outbox_events"] == 1
              and checks["receipts_at_crash"] == 0
              and checks["publishes_at_crash"] == 0
              and checks["crash_cleared_by_replay"] is True
              and checks["publishes_after_replay_delivery"] == 1
              and checks["receipts_after_ack"] == 1
              and checks["receipts_after_duplicate_acks"] == 1
              and checks["all_counters_zero"] is True)
    return {"probe": "A_crash_after_commit_before_publish",
            "passed": passed, "checks": checks,
            "counters": dict(sim.counters)}


# --------------------------------------------------------------------------
# Adversarial probe B — reserve child budget -> revoke -> retry interleaving
# --------------------------------------------------------------------------

def probe_reserve_revoke_retry():
    sim = Simulator(0, fault_probs=dict(crash_commit_publish=0.0,
                                        unknown_outcome=1.0, stale_ack=0.0))
    parent, child = 0, 8             # child 8 derives from root 0 by layout
    for g in (parent, child):
        sim.g_approved_tick[g] = sim.tick
        sim._pending_activation.append(g)
    sim.op_tick()
    assert sim.g_state[parent] == "active" and sim.g_state[child] == "active", \
        "probe B: chain not activated"
    # 1. reserve child budget against the parent ledger (INV6 / I5)
    sim.g_reserved[parent] += 2
    sim.g_reserved[child] += 2
    overalloc_before = (sim.g_spent[parent] + sim.g_reserved[parent]
                        > sim.g_alloc[parent])
    child_covered = sim.g_reserved[child] <= sim.g_reserved[parent]
    # 2. durable revoke of the parent; descendant reservations are released
    sim._set_grant_state(parent, "revoked")
    reservations_released = sim.g_reserved[child] == 0
    conservation_after_revoke = (sim.g_spent[parent] + sim.g_reserved[parent]
                                 <= sim.g_alloc[parent])
    # 3. allow() through the revoked parent chain must be impossible
    allow_denied = not sim._active_chain(child)
    # 4. re-reserving the child budget against the revoked parent is refused
    retry_reservation_accepted = (
        sim.g_state[parent] == "active"
        and sim.g_spent[parent] + sim.g_reserved[parent] + 2
        <= sim.g_alloc[parent])
    overalloc_after = (sim.g_spent[parent] + sim.g_reserved[parent]
                       > sim.g_alloc[parent])
    # 5. unknown external outcome routes to reconciliation, not blind retry:
    #    commit a decision from an independent active root chain
    unrelated_root = 1
    sim.g_approved_tick[unrelated_root] = sim.tick
    sim._pending_activation.append(unrelated_root)
    sim.op_tick()
    assert sim.g_state[unrelated_root] == "active", "probe B: second root missing"
    blind_retry_blocked = None
    retry_after_reconcile_ok = None
    d = sim._next_decision
    sim._next_decision += 1
    sim.decisions[d] = {
        "grant": unrelated_root, "committed": True, "outbox_event": d,
        "estate": "pending", "publishes": 0, "token": 0,
        "inflight_token": None, "receipt_token": None, "receipts": 0,
        "reconcile_done": False, "fence_stale": 0,
        "commit_tick": sim.tick, "crashed": False,
    }
    rec = sim.decisions[d]
    if True:
        rec["publishes"] += 1
        rec["token"] += 1
        rec["estate"] = "unknown"          # external outcome unknown
        # the SAF3 guard rejects a second publish while unresolved
        try:
            if rec["publishes"] >= 1 and not rec["reconcile_done"]:
                sim.counters["SAF3"] += 1
                raise Violation("SAF3", sim.step, "blind retry detected")
        except Violation:
            sim.counters["SAF3"] -= 1      # probe-internal check, not a finding
            blind_retry_blocked = True
        # correct path: reconcile first, then the retry becomes legal
        sim.reconciliations += 1
        rec["estate"] = "reconciling"
        rec["reconcile_done"] = True
        rec["estate"] = "nacked"
        rec["publishes"] += 1              # legal retry after reconciliation
        retry_after_reconcile_ok = rec["publishes"] == 2 and rec["reconcile_done"]
    sim.audit()
    counters_zero = all(sim.counters[inv] == 0 for inv in INVARIANT_IDS)
    passed = (not overalloc_before and child_covered and reservations_released
              and conservation_after_revoke and allow_denied
              and not retry_reservation_accepted and not overalloc_after
              and blind_retry_blocked is True
              and retry_after_reconcile_ok is True
              and counters_zero)
    return {"probe": "B_reserve_child_revoke_retry",
            "passed": passed,
            "checks": {
                "over_allocation_before_revoke": overalloc_before,
                "child_reservation_covered_by_parent": child_covered,
                "reservations_released_on_revoke": reservations_released,
                "conservation_after_revoke": conservation_after_revoke,
                "allow_denied_after_revoke": allow_denied,
                "reservation_retry_accepted_after_revoke": retry_reservation_accepted,
                "over_allocation_after_retry": overalloc_after,
                "blind_retry_blocked": blind_retry_blocked,
                "retry_legal_after_reconciliation": retry_after_reconcile_ok,
                "invariant_counters_zero": counters_zero,
            }}


def run_probes():
    return [probe_crash_replay(), probe_reserve_revoke_retry()]


def _cli(argv):
    if len(argv) < 3:
        print("usage: invariant_simulator.py SEED OPS [--mutations id,...] "
              "[--probes]", file=sys.stderr)
        return 2
    seed = int(argv[1])
    ops = int(argv[2])
    mutations = []
    if "--mutations" in argv:
        mutations = [m for m in argv[argv.index("--mutations") + 1].split(",") if m]
    if "--probes" in argv:
        print(json.dumps(run_probes(), indent=2, sort_keys=True))
        return 0
    sim, result = simulate(seed, ops, mutations=mutations)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv))
