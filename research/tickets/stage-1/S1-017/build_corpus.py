"""Deterministic 48-scenario corpus generator for S1-017 (Phase A).

Single source of corpus.json + oracle.json structure. Oracle semantic entries
are frozen by the reference analyzer at build time; the Phase B evaluator
recomputes everything from corpus bytes. Re-running must be byte-identical.
Phase A runs the generator (fixtures), never the final 864-cell matrix.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SA = {"tenant_id": "t-a", "workspace_id": "w-1", "goal_id": "g-1"}
SB = {"tenant_id": "t-a", "workspace_id": "w-2", "goal_id": "g-2"}
SC = {"tenant_id": "t-b", "workspace_id": "w-1", "goal_id": "g-3"}
SCOPES = {"S_A": SA, "S_B": SB, "S_C": SC}

GRANT = "grant1"


def grant(gid=GRANT, scope="S_A", actions=None, revoked=False, expired=False):
    return {gid: {"scope": dict(SCOPES[scope]),
                  "actions": list(actions or ["read"]),
                  "revoked": revoked, "expired": expired}}


def principal(pid, scope, display=None):
    entry = {"principal_id": pid, "scope": dict(SCOPES[scope])}
    if display is not None:
        entry["display"] = display
    return entry


def state(sid, authority=None, phase="ready"):
    return {"state_id": sid, "authority": authority or {}, "phase": phase}


def trans(frm, actor, action, to, authority=None, outcome="effect",
          env=None, audit=None, args=None, reconciled_as=None):
    entry = {"from": frm, "actor": actor, "action": action,
             "args": dict(args or {}), "to": to,
             "authority_required": authority,
             "outcome": outcome, "environment_move": env,
             "audit_ref": audit or f"ev-{frm}-{action}"}
    if reconciled_as is not None:
        entry["reconciled_as"] = reconciled_as
    return entry


def trace_events(transitions, request_scope="S_A", redacted=None):
    events = []
    for index, transition in enumerate(transitions):
        events.append({"seq": index, "kind": "audit",
                       "actor": transition["actor"],
                       "action": transition["action"],
                       "decision": "ALLOW" if transition["outcome"] == "effect"
                       else ("UNKNOWN" if transition["outcome"] == "unknown"
                             else "DENY"),
                       "ref": transition["audit_ref"]})
    return {"events": events, "request_scope": dict(SCOPES[request_scope]),
            "redacted": list(redacted or [])}


def case(sid, klass, desc, principals, states, initial, transitions,
         trace, hint, tags):
    return {"scenario_id": sid, "class": klass, "description": desc,
            "principals": principals, "states": states, "initial": initial,
            "transitions": transitions, "trace": trace,
            "oracle_hint": {"kind": hint}, "tags": list(tags)}


def grant_game(actor="prin_A", scope="S_A", actions=None, gid=GRANT,
               revoked=False, expired=False, extra_transitions=None,
               wait=True, effect_phase="done"):
    authority = {"grants": grant(gid, scope, actions, revoked, expired)}
    transitions = [trans("s0", actor, "read", "s1",
                         {"grant_id": gid}, "effect", None, "ev1",
                         {"path": "doc"})]
    if wait:
        transitions.append(trans("s0", actor, "wait", "s0", None,
                                 "effect", None, "ev0", {}))
    transitions.extend(extra_transitions or [])
    return ([state("s0", authority),
             state("s1", {}, effect_phase)], transitions)


def SCENARIOS():
    scenarios = []
    add = scenarios.append
    # ---------------- complete_supported (12) ----------------
    states, transitions = grant_game()
    add(case("CS-01", "complete_supported", "grant allows read effect",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_holds", ["grant"]))
    states, transitions = grant_game(extra_transitions=[
        trans("s0", "prin_A", "write", "s0", {"grant_id": "nope"},
              "denied", None, "ev2", {})])
    add(case("CS-02", "complete_supported",
             "denial with desired but unauthorised alternative",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_absent", ["denial"]))
    states = [state("s0", {"grants": grant("g-parent", "S_A", ["delegate"])}),
              state("s1", {}), state("s2", {}, "done")]
    transitions = [
        trans("s0", "prin_parent", "delegate", "s1", {"grant_id": "g-parent"},
              "effect", None, "ev1", {"child": "prin_child", "actions": ["read"]}),
        trans("s1", "prin_child", "read", "s2", {"grant_id": "g-child"},
              "effect", None, "ev2", {"delegation": "g-parent"})]
    states[1]["authority"] = {"grants": grant("g-child", "S_A", ["read"])}
    add(case("CS-03", "complete_supported", "delegated child action attributed",
             [principal("prin_parent", "S_A"), principal("prin_child", "S_A")],
             states, "s0", transitions, trace_events(transitions),
             "stit_holds", ["delegation"]))
    states, transitions = grant_game(revoked=True)
    add(case("CS-04", "complete_supported", "revoke before decision denies",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_absent", ["denial", "revocation"]))
    states, transitions = grant_game()
    transitions.append(trans("s1", "prin_A", "read", "s1", {"grant_id": "grant1"},
                             "denied", None, "ev3", {"reuse": "consumed"}))
    add(case("CS-05", "complete_supported", "approval consumed once",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_holds", ["denial"]))
    states, transitions = grant_game(expired=True)
    add(case("CS-06", "complete_supported", "lease expiry denies",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_absent", ["denial", "revocation"]))
    states, transitions = grant_game()
    transitions[0]["outcome"] = "unknown"
    transitions[0]["reconciled_as"] = "effect"
    add(case("CS-07", "complete_supported", "worker crash reconciled to effect",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_holds", ["unknown"]))
    states = [state("s0", {"grants": grant("gA", "S_A", ["push"])}),
              state("s1", {}, "done")]
    transitions = [
        trans("s0", "prin_A", "push", "s1", {"grant_id": "gA"},
              "effect", None, "ev1", {}),
        trans("s0", "env", "perturb", "s0", None, "effect", "perturb", "ev9", {}),
        trans("s0", "prin_A", "wait", "s0", None, "effect", None, "ev0", {})]
    add(case("CS-08", "complete_supported", "coalition ability vs adversarial env",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "atl_holds", ["coalition"]))
    states = [state("s0", {"grants": grant("g1", "S_A", ["step"])}),
              state("s1", {"grants": grant("g2", "S_A", ["step"])}),
              state("s2", {}, "done")]
    transitions = [
        trans("s0", "prin_parent", "step", "s1", {"grant_id": "g1"},
              "effect", None, "ev1", {"delegate": "prin_child"}),
        trans("s1", "prin_child", "step", "s2", {"grant_id": "g2"},
              "effect", None, "ev2", {})]
    add(case("CS-09", "complete_supported", "multi-step delegated chain",
             [principal("prin_parent", "S_A"), principal("prin_child", "S_A")],
             states, "s0", transitions, trace_events(transitions),
             "stit_holds", ["delegation", "grant"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["derive"])}),
              state("s1", {}, "derived")]
    transitions = [
        trans("s0", "prin_A", "derive", "s1", {"grant_id": "g"},
              "effect", None, "ev1", {"sources": ["s1", "s2"]}),
        trans("s0", "prin_A", "wait", "s0", None, "effect", None, "ev0", {})]
    add(case("CS-10", "complete_supported", "derive effect from two sources",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_holds", ["grant"]))
    transitions = [
        trans("s0", "prin_A", "merge", "s1", {"grant_id": "g"},
              "effect", None, "ev1", {"sources": ["a", "b"]}),
        trans("s0", "prin_A", "wait", "s0", None, "effect", None, "ev0", {})]
    states = [state("s0", {"grants": grant("g", "S_A", ["merge"])}),
              state("s1", {}, "merged")]
    add(case("CS-11", "complete_supported", "merge lineage effect",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_holds", ["grant"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["act"])}),
              state("s1", {}, "done")]
    transitions = [
        trans("s0", "prin_svc", "act", "s1", {"grant_id": "g"},
              "effect", None, "ev1", {"on_behalf": "prin_owner"}),
        trans("s0", "prin_svc", "wait", "s0", None, "effect", None, "ev0", {})]
    add(case("CS-12", "complete_supported",
             "on-behalf attributes canonical service actor despite shared display",
             [principal("prin_svc", "S_A", display="Helper"),
              principal("prin_owner", "S_A", display="Helper")],
             states, "s0", transitions, trace_events(transitions),
             "stit_holds", ["delegation", "identity"]))
    # ---------------- complete_no_responsibility (12) ----------------
    states = [state("s0", {"grants": grant("g", "S_A", ["read"])}),
              state("s1", {}, "done")]
    transitions = [trans("s0", "prin_A", "read", "s1", {"grant_id": "g"},
                         "effect", None, "ev1", {})]
    add(case("CN-01", "complete_no_responsibility", "single authorised action",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_absent", ["grant"]))
    states = [state("s0", {"grants": {}}), state("s0d", {}, "denied")]
    transitions = [
        trans("s0", "prin_A", "read", "s0d", {"grant_id": "missing"},
              "denied", None, "ev1", {}),
        trans("s0", "prin_A", "write", "s0d", {"grant_id": "missing"},
              "denied", None, "ev2", {})]
    add(case("CN-02", "complete_no_responsibility", "all alternatives denied",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_absent", ["denial"]))
    states, transitions = grant_game(revoked=True, wait=False)
    add(case("CN-03", "complete_no_responsibility", "revoked grant attempted",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_absent", ["revocation"]))
    states, transitions = grant_game(expired=True, wait=False)
    add(case("CN-04", "complete_no_responsibility", "expired approval attempted",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_absent", ["denial", "revocation"]))
    states, transitions = grant_game()
    transitions[0]["outcome"] = "unknown"
    transitions[0]["reconciled_as"] = "failed"
    add(case("CN-05", "complete_no_responsibility",
             "unknown reconciled as failed, no effect",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_absent", ["unknown"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["read"])}),
              state("s1", {}, "done")]
    transitions = [
        trans("s0", "prin_A", "read", "s0", {"grant_id": "g"},
              "effect", None, "ev1", {}),
        trans("s0", "env", "flip", "s1", None, "effect", "flip", "ev9", {}),
        trans("s0", "prin_A", "wait", "s0", None, "effect", None, "ev0", {})]
    add(case("CN-06", "complete_no_responsibility",
             "environment move alone causes outcome",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_absent", ["coalition"]))
    states, transitions = grant_game()
    transitions[0]["authority_required"] = {"grant_id": "missing"}
    transitions[0]["outcome"] = "denied"
    add(case("CN-07", "complete_no_responsibility", "attempt denied, no effect",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_absent", ["denial"]))
    states, transitions = grant_game()
    add(case("CN-08", "complete_no_responsibility",
             "duplicate retry is a single effect",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_holds", ["grant"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["read"])}),
              state("s0d", {}, "denied")]
    transitions = [
        trans("s0", "prin_sup", "override", "s0d", {"grant_id": "g"},
              "effect", None, "ev0", {"delegated": "prin_A"}),
        trans("s0", "prin_A", "read", "s0d", {"grant_id": "g"},
              "denied", None, "ev1", {})]
    add(case("CN-09", "complete_no_responsibility", "supervisor override denies",
             [principal("prin_sup", "S_A"), principal("prin_A", "S_A")],
             states, "s0", transitions, trace_events(transitions),
             "stit_absent", ["denial", "delegation"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["read"])}),
              state("s0d", {}, "denied")]
    transitions = [trans("s0", "prin_A", "read", "s0d", {"grant_id": "g"},
                         "denied", None, "ev1", {"scope": "foreign"})]
    add(case("CN-10", "complete_no_responsibility", "out-of-scope request denied",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_absent", ["denial"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["read", "write"])}),
              state("s1", {}, "done")]
    transitions = [
        trans("s0", "prin_A", "read", "s1", {"grant_id": "g"},
              "effect", None, "ev1", {}),
        trans("s0", "prin_A", "write", "s1", {"grant_id": "g"},
              "effect", None, "ev2", {})]
    add(case("CN-11", "complete_no_responsibility",
             "alternative leads to same outcome, no difference",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "stit_absent", ["grant"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["push"])}),
              state("s1", {}, "done")]
    transitions = [
        trans("s0", "prin_A", "push", "s0", {"grant_id": "g"},
              "effect", None, "ev1", {}),
        trans("s0", "env", "block", "s1", None, "effect", "block", "ev9", {})]
    add(case("CN-12", "complete_no_responsibility",
             "coalition lacks strategy against environment",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "atl_absent", ["coalition"]))
    # ---------------- underdetermined (12) ----------------
    states = [state("s0", {}), state("s1", {}, "done")]
    transitions = [trans("s0", "prin_A", "read", "s1", {"grant_id": "g-missing"},
                         "effect", None, "ev1", {})]
    add(case("UD-01", "underdetermined", "incomplete trace, grant record missing",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "underdetermined", ["incomplete"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["read"])}),
              state("s1", {}, "done")]
    transitions = [trans("s0", "prin_X", "read", "s1", {"grant_id": "g"},
                         "effect", None, "ev1", {})]
    add(case("UD-02", "underdetermined", "redacted trace hides actor",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions, redacted=["actor"]), "underdetermined",
             ["incomplete"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["read"])}),
              state("s1", {}, "done")]
    transitions = [
        trans("s0", "prin_A", "read", "s1", {"grant_id": "g"},
              "effect", None, "ev1", {}),
        trans("s0", "prin_A", "read", "s1", {"grant_id": "g"},
              "effect", None, "ev1b", {"duplicate_paths": True})]
    add(case("UD-03", "underdetermined", "ambiguous indistinguishable alternatives",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "underdetermined", ["incomplete"]))
    states, transitions = grant_game()
    add(case("UD-04", "underdetermined", "model disagreement abstains",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "underdetermined",
             ["incomplete", "delegation"]))
    states, transitions = grant_game()
    transitions[0]["outcome"] = "unknown"
    add(case("UD-05", "underdetermined", "unknown after revoke without reconcile",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "underdetermined",
             ["unknown", "revocation", "incomplete"]))
    states = [state("s0", {"grants": {"g": {"scope": dict(SA),
                                            "actions": ["read"],
                                            "revoked": "UNKNOWN",
                                            "expired": False}}}),
              state("s1", {}, "done")]
    transitions = [trans("s0", "prin_A", "read", "s1", {"grant_id": "g"},
                         "effect", None, "ev1", {})]
    add(case("UD-06", "underdetermined", "revocation status missing",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "underdetermined",
             ["revocation", "incomplete"]))
    states = [state("s0", {"grants": grant("g-child", "S_A", ["read"])}),
              state("s1", {}, "done")]
    transitions = [trans("s0", "prin_child", "read", "s1", {"grant_id": "g-child"},
                         "effect", None, "ev1", {"delegation": "unknown-parent"})]
    add(case("UD-07", "underdetermined", "partial delegation chain",
             [principal("prin_child", "S_A")], states, "s0", transitions,
             trace_events(transitions), "underdetermined",
             ["delegation", "incomplete"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["read"])}),
              state("s1", {}, "done")]
    transitions = [
        trans("s0", "prin_A", "read", "s1", {"grant_id": "g"},
              "effect", None, "ev1", {}),
        trans("s0", "prin_B", "read", "s1", {"grant_id": "g"},
              "effect", None, "ev1x", {"same_display": "Helper"})]
    add(case("UD-08", "underdetermined",
             "conflicting order with same-named actors",
             [principal("prin_A", "S_A", display="Helper"),
              principal("prin_B", "S_A", display="Helper")],
             states, "s0", transitions, trace_events(transitions),
             "underdetermined", ["incomplete", "identity"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["read"])}),
              state("s1", {}, "done")]
    transitions = [trans("s0", "prin_A", "read", "s1", {"grant_id": "g"},
                         "effect", None, "ev1", {})]
    add(case("UD-09", "underdetermined", "redacted content hides effect",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions, redacted=["content"]), "underdetermined",
             ["incomplete"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["push"])}),
              state("s1", {}, "done")]
    transitions = [
        trans("s0", "prin_A", "push", "s1", {"grant_id": "g"},
              "effect", None, "ev1", {}),
        trans("s0", "prin_A", "wait", "s0", None, "effect", None, "ev0", {})]
    add(case("UD-10", "underdetermined", "coalition with unknown environment",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "underdetermined",
             ["coalition", "unknown", "incomplete"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["read"])}),
              state("s1", {}, "done")]
    transitions = [
        trans("s0", "prin_A", "read", "s1", {"grant_id": "g"},
              "effect", None, "ev1", {}),
        trans("s0", "prin_B", "read", "s1", {"grant_id": "g"},
              "effect", None, "ev2", {})]
    add(case("UD-11", "underdetermined",
             "display collision without canonical binding abstains",
             [principal("prin_A", "S_A", display="Alex")], states, "s0",
             transitions, trace_events(transitions), "underdetermined",
             ["identity", "incomplete"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["read"])}),
              state("s1", {}, "done")]
    transitions = [trans("s0", "prin_A", "read", "s1", {"grant_id": "g"},
                         "effect", None, "ev1", {"legacy_gap": "v1-missing"})]
    add(case("UD-12", "underdetermined", "legacy version gaps",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "underdetermined", ["incomplete"]))
    # ---------------- adversarial_or_invalid (12) ----------------
    states, transitions = grant_game()
    transitions[0]["authority_required"] = {"grant_id": "missing"}
    transitions[0]["outcome"] = "denied"
    add(case("AX-01", "adversarial_or_invalid",
             "annotation suggesting allow after DENY changes nothing",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "invalid",
             ["denial", "revocation"]))
    states = [state("s0", {"grants": grant("g-child", "S_A", ["read"])}),
              state("s1", {}, "done")]
    transitions = [trans("s0", "prin_child", "read", "s1", {"grant_id": "g-child"},
                         "effect", None, "ev1", {})]
    add(case("AX-02", "adversarial_or_invalid", "dropped delegator edge abstains",
             [principal("prin_child", "S_A")], states, "s0", transitions,
             trace_events(transitions), "underdetermined", ["delegation"]))
    states, transitions = grant_game()
    add(case("AX-03", "adversarial_or_invalid", "revoke removed is detected",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "invalid", ["revocation"]))
    states = [state("s0", {}), state("s1", {}, "done")]
    transitions = [trans("s0", "prin_A", "read", "s1", {"grant_id": "phantom"},
                         "effect", None, "ev1", {})]
    add(case("AX-04", "adversarial_or_invalid", "unavailable declared available",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "invalid", ["denial"]))
    states = [state("s0", {}), state("s1", {}, "done")]
    transitions = [trans("s0", "prin_A", "read", "s1", None,
                         "effect", None, "ev1", {"absence_claim": True})]
    add(case("AX-05", "adversarial_or_invalid", "absence sold as proof fails",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "invalid", ["incomplete"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["read"])}),
              state("s1", {}, "done")]
    transitions = [trans("s0", "Alex", "read", "s1", {"grant_id": "g"},
                         "effect", None, "ev1", {})]
    add(case("AX-06", "adversarial_or_invalid", "petname collapse refused",
             [principal("prin_A", "S_A", display="Alex"),
              principal("prin_B", "S_A", display="Alex")],
             states, "s0", transitions, trace_events(transitions),
             "invalid", ["identity"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["read"])}),
              state("s1", {}, "done")]
    transitions = [trans("s0", "prin_A", "read", "s1", {"grant_id": "g"},
                         "effect", None, "ev1", {"foreign_trace": "t-b"})]
    add(case("AX-07", "adversarial_or_invalid", "cross-goal trace mix rejected",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "invalid", ["incomplete"]))
    states = [state("s0", {}), state("s1", {}, "granted")]
    transitions = [trans("s0", "prin_A", "escalate", "s1",
                         {"grant_id": "modal"}, "effect", None, "ev1", {})]
    add(case("AX-08", "adversarial_or_invalid",
             "modal result creating capability refused",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "invalid", ["denial"]))
    states, transitions = grant_game()
    add(case("AX-09", "adversarial_or_invalid", "post-hoc audit mutation detected",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "invalid", ["grant"]))
    states, transitions = grant_game()
    transitions[0]["outcome"] = "unknown"
    add(case("AX-10", "adversarial_or_invalid",
             "partial labeled success without reconciliation fails",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "underdetermined", ["unknown"]))
    states = [state("s0", {"grants": grant("g", "S_A", ["push"])}),
              state("s1", {}, "done")]
    transitions = [trans("s0", "prin_A", "push", "s1", {"grant_id": "g"},
                         "effect", None, "ev1", {})]
    add(case("AX-11", "adversarial_or_invalid",
             "coalition ability without environment moves is incomplete",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "invalid", ["coalition"]))
    states, transitions = grant_game()
    add(case("AX-12", "adversarial_or_invalid", "hidden model disagreement fails",
             [principal("prin_A", "S_A")], states, "s0", transitions,
             trace_events(transitions), "underdetermined",
             ["delegation", "incomplete"]))
    return scenarios


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def validate_case(case: dict, known_ids: set | None = None) -> dict:
    """Fail-closed case validation (schema lives beside the corpus)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "s1017_contract_val", HERE / "contract.py")
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    schema = contract.load("schemas/scenario.schema.json")
    contract.validate(case, schema)
    if known_ids is not None and case["scenario_id"] in known_ids:
        raise ValueError("duplicate scenario id")
    return case


def build(reference=None):
    """Build corpus + oracle skeleton; reference fills semantic digests."""
    sys.path.insert(0, str(HERE))
    import runner as runner_mod
    cases = []
    oracle = {}
    seen: set[str] = set()
    for scenario in SCENARIOS():
        validate_case({k: v for k, v in scenario.items()
                       if k in ("scenario_id", "class", "description",
                                "principals", "states", "initial",
                                "transitions", "trace", "oracle_hint")}, seen)
        seen.add(scenario["scenario_id"])
        digest = sha(canonical({k: scenario[k] for k in sorted(scenario)
                                if k != "tags"}))
        entry = dict(scenario)
        entry["semantic_digest"] = digest
        cases.append(entry)
        oracle[scenario["scenario_id"]] = runner_mod.oracle_for(scenario)
    ids = [c["scenario_id"] for c in cases]
    assert len(ids) == len(set(ids)) == 48, "scenario ids must be 48 unique"
    assert len({c["semantic_digest"] for c in cases}) == 48
    by_class: dict[str, int] = {}
    for c in cases:
        by_class[c["class"]] = by_class.get(c["class"], 0) + 1
    assert by_class == {"complete_supported": 12, "complete_no_responsibility": 12,
                        "underdetermined": 12, "adversarial_or_invalid": 12}, by_class
    tags: dict[str, int] = {}
    for c in cases:
        for tag in c.get("tags", []):
            tags[tag] = tags.get(tag, 0) + 1
    for tag, minimum in (("denial", 8), ("delegation", 8), ("revocation", 8),
                         ("unknown", 4), ("coalition", 4),
                         ("incomplete", 4), ("identity", 4)):
        assert tags.get(tag, 0) >= minimum, (tag, tags.get(tag, 0))
    corpus = {"schema": "agentos.s1-017.corpus/v1", "ticket": "S1-017",
              "phase": "A", "scenario_count": 48, "cases": cases}
    oracle_doc = {"schema": "agentos.s1-017.oracle/v1", "ticket": "S1-017",
                  "phase": "A", "entries": oracle}
    return corpus, oracle_doc


def main() -> int:
    corpus, oracle_doc = build()
    (HERE / "corpus.json").write_text(
        json.dumps(corpus, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    (HERE / "oracle.json").write_text(
        json.dumps(oracle_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    manifest = {
        "schema": "agentos.s1-017.corpus-manifest/v1",
        "ticket": "S1-017",
        "phase": "A",
        "corpus_sha256": sha((HERE / "corpus.json").read_bytes()),
        "oracle_sha256": sha((HERE / "oracle.json").read_bytes()),
        "generator_sha256": sha((HERE / "build_corpus.py").read_bytes()),
        "scenario_count": 48,
        "deterministic": True,
    }
    (HERE / "corpus-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"scenarios": 48, **manifest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
