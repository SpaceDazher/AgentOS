"""State machines with authority guards. See spec/SPEC.md §2."""
from __future__ import annotations

from .journal import Journal, TransitionError

# Goal transitions: (from, to, allowed_actors)
GOAL_TRANSITIONS = {
    ("DRAFT", "ACTIVE"): {"system", "requester"},
    ("ACTIVE", "GATE_PENDING"): {"system", "gate"},
    ("GATE_PENDING", "ACCEPTED"): {"gate"},
    ("GATE_PENDING", "REJECTED"): {"gate"},
    ("REJECTED", "ACTIVE"): {"system", "requester"},
    ("GATE_PENDING", "ESCALATED"): {"gate"},
    ("ESCALATED", "ACTIVE"): {"system", "requester", "gate"},
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


class Machines:
    def __init__(self, db, journal: Journal):
        self.db = db
        self.j = journal

    def _do(self, table: str, transitions: dict, obj_id: str, frm: str, to: str,
            actor: str, goal_id: str | None, event_type: str, payload: dict,
            extra_sets: dict | None = None, transition_key: str | None = None) -> dict:
        allowed = transitions.get((frm, to))
        if allowed is None:
            raise TransitionError(f"{table} {frm}->{to} is not a defined transition")
        if actor not in allowed:
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

    def assert_not_worker(self, actor: str) -> None:
        if actor == "worker":
            raise TransitionError("workers may never move a Goal state directly")

    # -- Task -----------------------------------------------------------------
    def task_transition(self, task_id: str, frm: str, to: str, actor: str,
                        goal_id: str, extra_sets: dict | None = None,
                        payload: dict | None = None,
                        transition_key: str | None = None) -> dict:
        return self._do("task", TASK_TRANSITIONS, task_id, frm, to, actor, goal_id,
                        f"task.{to.lower()}", payload or {}, extra_sets, transition_key)

    # -- Run ------------------------------------------------------------------
    def run_transition(self, run_id: str, frm: str, to: str, actor: str,
                       goal_id: str, extra_sets: dict | None = None,
                       payload: dict | None = None) -> dict:
        return self._do("run", RUN_TRANSITIONS, run_id, frm, to, actor, goal_id,
                        f"run.{to.lower()}", payload or {}, extra_sets)
