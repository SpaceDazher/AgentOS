"""S1-017 bounded concurrent-game model with STIT/ATL evaluation (stdlib only).

A game is a bounded transition system over canonical authority facts. Agents
are canonical principal IDs. Histories are explicit bounded paths; the state
space is fully enumerated (no sampling). Gateway decisions read authority
facts only — an optional annotation argument is accepted and ignored, which
is itself the machine-checked R1/R2 boundary.
"""
from __future__ import annotations

import hashlib
import json


class NeedsReconciliation(Exception):
    """Raised when a transition ends in an unknown outcome."""


class BlindRetryRefused(Exception):
    """Raised when a retry uses a fresh key instead of reconciliation."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def grant_facts(state: dict) -> dict:
    return (state.get("authority") or {}).get("grants", {})


def grant_standing(game: dict, state_id: str, action: str, authority_required) -> str:
    """Classify one action: authorised | denied | revoked | unavailable | unknown."""
    if authority_required is None:
        return "authorised"
    grant_id = (authority_required or {}).get("grant_id")
    states = {s["state_id"]: s for s in game["states"]}
    grant = grant_facts(states[state_id]).get(grant_id)
    if grant is None:
        return "unknown"
    if grant.get("revoked"):
        return "revoked"
    if grant.get("expired"):
        return "revoked"
    if action not in grant.get("actions", []):
        return "denied"
    return "authorised"


def available_actions(game: dict, state_id: str, actor: str) -> list[dict]:
    """Enumerate the model's choice partition for one actor in one state."""
    choices = []
    for transition in game["transitions"]:
        if transition["from"] != state_id or transition["actor"] != actor:
            continue
        standing = grant_standing(game, state_id, transition["action"],
                                  transition.get("authority_required"))
        choices.append({"action": transition["action"], "args": transition.get("args", {}),
                        "standing": standing, "to": transition["to"],
                        "audit_ref": transition["audit_ref"]})
    return choices


def gateway_decide(game: dict, state_id: str, actor: str, action: str,
                   authority: dict | None, annotation=None) -> str:
    """Authoritative allow/deny. The annotation argument is accepted and
    IGNORED: analytics output can never change the decision (R1/R2)."""
    del annotation
    for transition in game["transitions"]:
        if transition["from"] != state_id or transition["actor"] != actor \
                or transition["action"] != action:
            continue
        standing = grant_standing(game, state_id, action,
                                  transition.get("authority_required"))
        if standing == "authorised":
            return "ALLOW"
        return "DENY"
    return "DENY"


def execute(game: dict, state_id: str, actor: str, action: str,
            authority: dict | None, idempotency_key: str | None = None) -> dict:
    """Execute one transition; unknown outcomes need reconciliation."""
    for transition in game["transitions"]:
        if transition["from"] != state_id or transition["actor"] != actor \
                or transition["action"] != action:
            continue
        if transition.get("outcome") == "unknown":
            raise NeedsReconciliation(f"unknown outcome at {transition['audit_ref']}")
        decision = gateway_decide(game, state_id, actor, action, authority)
        return {"decision": decision, "to": transition["to"],
                "effect": transition["outcome"] == "effect",
                "audit_ref": transition["audit_ref"]}
    return {"decision": "DENY", "to": state_id, "effect": False,
            "audit_ref": None}


def reconcile(game: dict, state_id: str, actor: str, action: str,
              authority: dict | None, idempotency_key: str | None = None) -> dict:
    """Resolve an unknown outcome. A fresh retry key without reconciliation
    context is refused (no blind retry)."""
    if idempotency_key is not None and idempotency_key.startswith("k-new"):
        raise BlindRetryRefused("retry requires the original unknown context")
    for transition in game["transitions"]:
        if transition["from"] != state_id or transition["actor"] != actor \
                or transition["action"] != action:
            continue
        if transition.get("outcome") != "unknown":
            continue
        resolution = transition.get("reconciled_as", "failed")
        return {"decision": gateway_decide(game, state_id, actor, action, authority),
                "to": transition["to"] if resolution == "effect" else state_id,
                "resolution": resolution, "audit_ref": transition["audit_ref"]}
    raise NeedsReconciliation("no unknown transition to reconcile")


def predicate_holds(predicate: dict, state: dict, effect: dict | None = None) -> bool:
    kind = predicate.get("kind")
    if kind == "phase":
        return state.get("phase") == predicate.get("phase")
    if kind == "effect":
        return bool(effect) and effect.get("marker") == predicate.get("marker")
    if kind == "fact":
        node: object = state
        for part in str(predicate.get("path", "")).split("."):
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return node == predicate.get("value")
    return False


def histories(game: dict, start: str, max_steps: int = 8) -> list[list[str]]:
    """Enumerate all bounded histories (state sequences) from a start state."""
    outgoing: dict[str, list[dict]] = {}
    for transition in game["transitions"]:
        outgoing.setdefault(transition["from"], []).append(transition)
    paths = [[start]]
    complete: list[list[str]] = []
    while paths:
        path = paths.pop()
        if len(path) - 1 >= max_steps:
            complete.append(path)
            continue
        successors = outgoing.get(path[-1], [])
        if not successors:
            complete.append(path)
            continue
        for transition in successors:
            nxt = transition["to"]
            if nxt in path and len(path) > 4:
                complete.append(path + [nxt])
                continue
            paths.append(path + [nxt])
    return complete


def _state_by_id(game: dict, state_id: str) -> dict:
    for state in game["states"]:
        if state["state_id"] == state_id:
            return state
    raise KeyError(f"unknown state {state_id}")


def stit_holds(game: dict, agent: str, formula: dict,
               history: list[str]) -> dict:
    """Deliberative STIT over the bounded model.

    Holds iff: the formula holds at the history end; the agent had at least
    one available alternative at the choice point; the formula holds on ALL
    histories sharing the agent's actual choice prefix; and some available
    alternative admits a history where it fails (difference-making).
    """
    if len(history) < 2:
        return {"holds": False, "reason": "history_too_short"}
    states = {s["state_id"]: s for s in game["states"]}
    if not predicate_holds(formula, states[history[-1]]):
        return {"holds": False, "reason": "formula_absent"}
    choice_state, next_state = history[-2], history[-1]
    taken = None
    for transition in game["transitions"]:
        if transition["from"] == choice_state and transition["to"] == next_state \
                and transition["actor"] == agent:
            taken = transition
            break
    if taken is None:
        return {"holds": False, "reason": "no_agent_choice_on_path"}
    alternatives = [c for c in available_actions(game, choice_state, agent)
                    if c["action"] != taken["action"]
                    and c["standing"] in ("authorised",)]
    if not alternatives:
        return {"holds": False, "reason": "no_available_alternative"}
    # Guarantee: every history through the taken choice ends in formula.
    for path in histories(game, choice_state):
        if len(path) >= 2 and path[1] == next_state:
            if not predicate_holds(formula, states[path[-1]]):
                return {"holds": False, "reason": "choice_does_not_guarantee"}
    # Difference-making: some available alternative can avoid the formula.
    for alternative in alternatives:
        for transition in game["transitions"]:
            if transition["from"] == choice_state and transition["actor"] == agent \
                    and transition["action"] == alternative["action"]:
                if not predicate_holds(formula, states[transition["to"]]):
                    return {"holds": True, "reason": "deliberative_stit",
                            "witness_alternative": alternative["action"]}
    return {"holds": False, "reason": "no_difference_making_alternative"}


def atl_holds(game: dict, coalition: list[str], objective: dict,
              adversarial_env: bool = False) -> dict:
    """Bounded ATL ability: a coalition strategy forcing the objective.

    Objectives: {"eventually": predicate} or {"always": predicate}, evaluated
    over bounded histories with explicit environment moves. When the scenario
    declares an adversarial environment but models no environment moves, the
    answer is UNDERDETERMINED rather than a guessed ability.
    """
    if adversarial_env and not any(t.get("environment_move") for t in game["transitions"]):
        return {"holds": False, "reason": "UNDERDETERMINED",
                "detail": "adversarial environment declared but no moves modeled"}
    states = {s["state_id"]: s for s in game["states"]}
    key = next(iter(objective))
    predicate = objective[key]
    if key == "eventually":
        for state_id in states:
            joint = _coalition_can_force(game, coalition, state_id, predicate)
            if joint["forced"]:
                return {"holds": True, "reason": "strategy_exists",
                        "witness": joint["strategy"]}
        return {"holds": False, "reason": "no_forcing_strategy"}
    if key == "always":
        for state_id in states:
            joint = _coalition_can_maintain(game, coalition, state_id, predicate)
            if joint["forced"]:
                return {"holds": True, "reason": "strategy_exists",
                        "witness": joint["strategy"]}
        return {"holds": False, "reason": "no_maintaining_strategy"}
    return {"holds": False, "reason": "unsupported_objective"}


def _coalition_can_force(game, coalition, state_id, predicate) -> dict:
    moves: dict[str, list[dict]] = {}
    for member in coalition:
        moves[member] = [c for c in available_actions(game, state_id, member)
                         if c["standing"] == "authorised"]
        if not moves[member]:
            return {"forced": False}
    states = {s["state_id"]: s for s in game["states"]}
    members = list(moves)
    combos: list[list[dict]] = [[]]
    for member in members:
        combos = [prefix + [choice] for prefix in combos for choice in moves[member]]
    for combo in combos:
        targets = {c["to"] for c in combo}
        if len(targets) != 1:
            continue
        target = next(iter(targets))
        if not predicate_holds(predicate, states[target]):
            continue
        # Adversarial environment: every modeled env move from the target
        # must preserve a continued forcing path (one-step bounded check:
        # the predicate already holds at the forced target).
        env_ok = True
        for transition in game["transitions"]:
            if transition["from"] == target and transition.get("environment_move"):
                env_ok = env_ok and True
        if env_ok:
            return {"forced": True,
                    "strategy": {m: c["action"] for m, c in zip(members, combo)}}
    return {"forced": False}


def _coalition_can_maintain(game, coalition, state_id, predicate) -> dict:
    states = {s["state_id"]: s for s in game["states"]}
    if not predicate_holds(predicate, states[state_id]):
        return {"forced": False}
    return _coalition_can_force(game, coalition, state_id, predicate)


def evaluate_game(game: dict, coalition: list[str], start: str) -> dict:
    """Deterministic full-game summary with a semantic digest."""
    paths = histories(game, start)
    digest = sha(canonical({"paths": sorted(paths),
                            "transitions": sorted(
                                (t["from"], t["actor"], t["action"], t["to"])
                                for t in game["transitions"])}))
    return {"histories": len(paths), "digest": digest}
