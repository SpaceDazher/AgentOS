"""State machines with authority guards. See spec/SPEC.md §2.

Terminal acceptance authority: the GATE_PENDING→ACCEPTED / →REJECTED transitions
are executed ONLY through `accept_by_gate_record`, which (a) requires an
internal, non-forgeable GateAuthority token object and (b) verifies inside the
same transaction that a PASSING gate row exists for this exact goal state.
A caller-supplied actor string can never authorize these transitions.
"""
from __future__ import annotations

from .journal import Journal, TransitionError

# Goal transitions: (from, to, allowed_actors) — EXCEPT terminal ones, which are
# routed exclusively through accept_by_gate_record below.
GOAL_TRANSITIONS = {
    ("DRAFT", "ACTIVE"): {"system", "requester"},
    ("ACTIVE", "GATE_PENDING"): {"system"},
    ("GATE_PENDING", "ESCALATED"): {"system"},
    ("REJECTED", "ACTIVE"): {"system", "requester"},
    ("ESCALATED", "ACTIVE"): {"system", "requester"},
    ("DRAFT", "CANCELLED"): {"requester"},
    ("ACTIVE", "CANCELLED"): {"requester"},
    ("GATE_PENDING", "CANCELLED"): {"requester"},
    ("REJECTED", "CANCELLED"): {"requester"},
}

TASK_TRANSITIONS = {
    ("PENDING", "READY"): {"system"},
    ("PENDING", "CANCELLED"): {"system", "requester"},
    ("READY", "RUNNING"): {"system", "worker"},
    ("READY", "CANCELLED"): {"system", "requester"},
    ("RUNNING", "DONE"): {"system", "worker"},
    ("RUNNING", "FAILED"): {"system", "worker"},
    ("RUNNING", "BLOCKED"): {"system", "worker"},
    ("FAILED", "READY"): {"system"},          # bounded retry
    ("BLOCKED", "READY"): {"system"},
    ("FAILED", "CANCELLED"): {"system", "requester"},
}

RUN_TRANSITIONS = {
    ("PLANNED", "RUNNING"): {"system", "worker"},
    ("RUNNING", "COMPLETED"): {"system", "worker"},
    ("RUNNING", "FAILED"): {"system", "worker"},
    ("RUNNING", "PAUSED"): {"system", "worker", "requester"},
    ("PAUSED", "RUNNING"): {"system"},
    ("RUNNING", "CANCELLED"): {"system", "requester"},
    ("PAUSED", "CANCELLED"): {"system", "requester"},
}


class GateAuthority:
    """Internal capability token. Never serialized; only Gates holds one.

    Possession of this OBJECT (not any string) is what authorizes the
    ACCEPTED/REJECTED transitions — plus the passing-gate-row check that runs
    in the same transaction.
    """
    __slots__ = ("_token",)

    def __init__(self, token: bytes):
        self._token = token

    def _check(self) -> bool:
        return isinstance(self._token, bytes) and len(self._token) == 32


def gate_authority() -> GateAuthority:
    import os
    return GateAuthority(os.urandom(32))


class Machines:
    def __init__(self, db, journal: Journal):
        self.db = db
        self.j = journal
        self._gate_auth: GateAuthority | None = None
        # Capability held only by this state-machine instance.  It allows the
        # research workflow to record a supersession without pretending that
        # an end user requested it or broadening the normal actor allow-list.
        self._supersession_authority = object()

    def set_gate_authority(self, auth: GateAuthority) -> None:
        self._gate_auth = auth

    def _do(self, table: str, transitions: dict, obj_id: str, frm: str, to: str,
            actor: str, goal_id: str | None, event_type: str, payload: dict,
            extra_sets: dict | None = None, transition_key: str | None = None,
            authority_ok: bool = True,
            internal_authority: object | None = None) -> dict:
        allowed = transitions.get((frm, to))
        if allowed is None:
            raise TransitionError(f"{table} {frm}->{to} is not a defined transition")
        if to in ("ACCEPTED", "REJECTED"):
            raise TransitionError(
                f"{table} {frm}->{to} must go through accept_by_gate_record()")
        internal_ok = internal_authority is self._supersession_authority
        if not authority_ok or (actor not in allowed and not internal_ok):
            raise TransitionError(
                f"actor '{actor}' may not move {table}:{obj_id} {frm}->{to} "
                f"(allowed: {sorted(allowed)})"
            )
        return self.j.transition(
            table=table, obj_id=obj_id, expect_from=frm, to=to, actor=actor,
            authority_ok=True, goal_id=goal_id, event_type=event_type,
            payload=payload, extra_sets=extra_sets, transition_key=transition_key,
        )

    # -- Goal -----------------------------------------------------------------
    def goal_transition(self, goal_id: str, frm: str, to: str, actor: str,
                        payload: dict | None = None) -> dict:
        return self._do("goal", GOAL_TRANSITIONS, goal_id, frm, to, actor, goal_id,
                        f"goal.{to.lower()}", payload or {})

    def cancel_superseded_goal(self, goal_id: str,
                               payload: dict | None = None) -> dict:
        """Journal a host-owned cancellation for an obsolete revision.

        This is intentionally a separate capability from ``goal_transition``:
        callers cannot claim requester authority, while the transition still
        uses the same state-machine table and atomic Journal CAS.
        """
        row = self.db.conn.execute(
            "SELECT status FROM goal WHERE id=?", (goal_id,)).fetchone()
        if not row:
            raise TransitionError(f"goal {goal_id} does not exist")
        status = row["status"]
        if (status, "CANCELLED") not in GOAL_TRANSITIONS:
            raise TransitionError(
                f"goal {goal_id} cannot be superseded from {status}")
        return self._do("goal", GOAL_TRANSITIONS, goal_id, status,
                        "CANCELLED", "research-planner", goal_id,
                        "goal.cancelled",
                        payload or {}, internal_authority=self._supersession_authority)

    def accept_by_gate_record(self, goal_id: str, to: str, *,
                              auth: GateAuthority, gate_id: str,
                              reasons: list[str]) -> dict:
        """The ONLY path to ACCEPTED/REJECTED.

        Review round 2 hardening: the passing-gate-row check and the goal
        status CAS happen INSIDE ONE transaction (BEGIN IMMEDIATE), so no
        window exists where the gate row is checked against a state that then
        changes. The GateAuthority must be THE instance bound via
        set_gate_authority(); `gate_authority()` alone proves nothing.
        Additionally this method verifies that the goal has ≥1 evaluation per
        current criterion version — a passing gate row without underlying
        evaluations is treated as corrupt state and refused.
        """
        if to not in ("ACCEPTED", "REJECTED"):
            raise TransitionError("accept_by_gate_record only accepts ACCEPTED|REJECTED")
        if self._gate_auth is None or auth is not self._gate_auth or not auth._check():
            raise TransitionError(
                "terminal transition denied: no valid GateAuthority")
        with self.db.tx() as conn:
            row = conn.execute(
                "SELECT status FROM goal WHERE id=?", (goal_id,)).fetchone()
            if not row or row["status"] != "GATE_PENDING":
                raise TransitionError(
                    f"goal {goal_id} is not GATE_PENDING"
                    f" (found {row['status'] if row else '<missing>'})")
            if to == "ACCEPTED":
                ok = conn.execute(
                    "SELECT COUNT(*) FROM gate WHERE goal_id=? AND result='pass'"
                    " AND id=?", (goal_id, gate_id)).fetchone()[0]
                if not ok:
                    raise TransitionError(
                        "ACCEPTED requires a passing gate record for this goal")
                # corruption guard: every current criterion version must have at
                # least one recorded evaluation for THIS goal
                missing = conn.execute(
                    "SELECT COUNT(*) FROM acceptance_criteria c"
                    " WHERE c.goal_id=? AND c.criterion_version = ("
                    "  SELECT MAX(c2.criterion_version) FROM acceptance_criteria c2"
                    "  WHERE c2.goal_id=c.goal_id AND c2.criterion_id=c.criterion_id)"
                    " AND NOT EXISTS (SELECT 1 FROM evaluation e WHERE e.goal_id=c.goal_id"
                    "  AND e.criterion_id=c.criterion_id"
                    "  AND e.criterion_version=c.criterion_version)",
                    (goal_id,)).fetchone()[0]
                if missing:
                    raise TransitionError(
                        f"ACCEPTED refused: {missing} criterion version(s) have "
                        f"no evaluation record (corrupt gate row)")
            event_type = f"goal.{to.lower()}"
            payload = {"gate_id": gate_id,
                       **({"gaps": reasons} if reasons else {})}
            return self.j.transition_locked(
                conn, table="goal", obj_id=goal_id, expect_from="GATE_PENDING",
                to=to, actor="gate", authority_ok=True, goal_id=goal_id,
                event_type=event_type, payload=payload)

    def assert_not_worker(self, actor: str) -> None:
        if actor == "worker":
            raise TransitionError("workers may never move a Goal state directly")

    # -- Task -----------------------------------------------------------------
    def task_transition(self, task_id: str, frm: str, to: str, actor: str,
                        goal_id: str, extra_sets: dict | None = None,
                        payload: dict | None = None,
                        transition_key: str | None = None) -> dict:
        return self._do("task", TASK_TRANSITIONS, task_id, frm, to, actor, goal_id,
                        f"task.{to.lower()}", payload or {}, extra_sets,
                        transition_key)

    # -- Run ------------------------------------------------------------------
    def run_transition(self, run_id: str, frm: str, to: str, actor: str,
                       goal_id: str, extra_sets: dict | None = None,
                       payload: dict | None = None) -> dict:
        return self._do("run", RUN_TRANSITIONS, run_id, frm, to, actor, goal_id,
                        f"run.{to.lower()}", payload or {}, extra_sets)
