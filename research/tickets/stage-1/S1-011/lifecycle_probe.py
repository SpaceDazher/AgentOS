#!/usr/bin/env python3
"""Executable S1-011 lifecycle and adversarial probes (stdlib-only, deterministic).

Implements the S1-011 ticket's adversarial/near-miss probes as DATA driven by a
deterministic state machine over the S1-003 KnowledgeAssertion vocabulary:

  P1 (single-source-no-independence): a message with one source and no
     independent provenance must NOT promote, even if its text agrees with an
     existing promoted claim.  A mirror with a different publisher label but
     the same canonical_source_id / independence_group must not change the
     distinct canonical-source or independence-group counts (S1-001/S1-003
     consistency).  A control message with two independent groups promotes.

  P2 (challenge/retract invalidation): a challenge and a retraction must
     invalidate the derived promoted-only knowledge view without deleting the
     immutable assertion or any audit history.  Row counts never shrink, a
     retraction marker is appended, and recorded assertion hashes stay
     byte-identical (append-only).

  P3 (transition completeness): every lifecycle transition of the MVP gate is
     defined in the transition table, every one is actually executed in this
     run, and terminal-state or gate-skipping attempts are refused and
     audited fail-closed.

The evidence gate reuses the S1-003 promoted preconditions verbatim (>= 2
Evidence, >= 2 distinct canonicalSourceId, >= 2 distinct independenceGroup,
complete EvidenceShape provenance, scope match, one PromotionActivity with a
matching actor scope) and the S1-001 independence rules (mirrors inherit
identity; text agreement is not provenance).

Output: writes probe-results.json and prints one JSON verdict line
{"status": "pass"|"fail", "observed": ...}; exit 0 on pass, 1 on fail.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLE = HERE / "bundle.json"
RESULTS = HERE / "probe-results.json"

# The S1-003 KnowledgeAssertion status vocabulary (shapes-v3.ttl sh:in list).
STATES = ("proposed", "under_review", "promoted", "challenged",
          "retracted", "superseded", "rejected")
TERMINAL = {"retracted", "superseded", "rejected"}

# The MVP transition table: (from, to) -> guard name.  Guard names match the
# ontology artifact's lifecycle transition table row-for-row.
TRANSITIONS = {
    ("proposed", "under_review"): "review_opened",
    ("proposed", "rejected"): "intake_rejection",
    ("under_review", "promoted"): "evidence_gate_passed",
    ("under_review", "rejected"): "evidence_gate_failed",
    ("promoted", "challenged"): "challenge_raised",
    ("promoted", "retracted"): "retraction_raised",
    ("promoted", "superseded"): "superseded_by_successor",
    ("challenged", "promoted"): "challenge_dismissed_by_operator",
    ("challenged", "retracted"): "challenge_upheld_by_operator",
    ("challenged", "superseded"): "challenge_resolved_by_supersession",
}

EVIDENCE_FIELDS = ("canonical_source_id", "publisher_id", "independence_group",
                   "resolver_version", "metadata_frozen_at")


def _canon(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _sha(value) -> str:
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def make_evidence(eid: str, canonical: str, publisher: str, group: str,
                  scope: str, resolver: str = "v1",
                  frozen: str = "2026-01-01T00:00:00Z") -> dict:
    return {
        "id": eid,
        "canonical_source_id": canonical,
        "publisher_id": publisher,
        "independence_group": group,
        "resolver_version": resolver,
        "metadata_frozen_at": frozen,
        "scope": scope,
    }


class KnowledgeGateStore:
    """Append-only assertion store + audit journal + derived current status.

    Assertion and evidence records are immutable once declared (hash-pinned).
    Status transitions and audit events commit atomically in ``transition``:
    a successful transition appends exactly one TransitionEvent and updates
    the status in the same step; a refused attempt appends only a refusal
    event and changes nothing.
    """

    def __init__(self, scope: str):
        self.scope = scope
        self.assertions: dict[str, dict] = {}
        self.assertion_hashes: dict[str, str] = {}
        self.evidence: dict[str, dict] = {}
        self.events: list[dict] = []
        self.status: dict[str, str] = {}
        self.successor: dict[str, str] = {}
        self.ever_promoted: set[str] = set()
        self._seq = 0

    # -- internals ----------------------------------------------------------
    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _append(self, event: dict) -> dict:
        stored = {"seq": self._next_seq(), **event}
        self.events.append(stored)
        return stored

    # -- declarations -------------------------------------------------------
    def add_evidence(self, ev: dict) -> dict:
        record = dict(ev)
        record["scope"] = self.scope
        self.evidence[record["id"]] = record
        return record

    def declare_assertion(self, aid: str, text: str, evidence_ids,
                          actor: str = "submitter") -> dict:
        record = {
            "id": aid,
            "text": text,
            "scope": self.scope,
            "supported_by": tuple(sorted(evidence_ids)),
            "declared_by": actor,
        }
        self.assertions[aid] = record
        self.assertion_hashes[aid] = _sha(record)
        self.status[aid] = "proposed"
        self._append({
            "type": "assertion_declared",
            "assertion": aid,
            "actor": actor,
            "payload_sha256": self.assertion_hashes[aid],
            "evidence_ids": list(record["supported_by"]),
        })
        return record

    def set_successor(self, aid: str, successor_id: str) -> None:
        self.successor[aid] = successor_id

    # -- evidence gate (S1-003 promoted preconditions + S1-001 rules) -------
    def evidence_gate(self, aid: str) -> tuple[bool, list[str]]:
        a = self.assertions[aid]
        evs = [self.evidence[e] for e in a["supported_by"]]
        reasons: list[str] = []
        if len(evs) < 2:
            reasons.append("insufficient_evidence_count")
        canonical = {e["canonical_source_id"] for e in evs}
        groups = {e["independence_group"] for e in evs}
        if len(canonical) < 2:
            reasons.append("insufficient_distinct_canonical_sources")
        if len(groups) < 2:
            reasons.append("insufficient_independence_groups")
        incomplete = sorted(
            e["id"] for e in evs
            if any(not str(e.get(f, "")).strip() for f in EVIDENCE_FIELDS))
        if incomplete:
            reasons.append("incomplete_evidence_provenance:" + ",".join(incomplete))
        mismatched = sorted(e["id"] for e in evs if e["scope"] != a["scope"])
        if mismatched:
            reasons.append("evidence_scope_mismatch:" + ",".join(mismatched))
        return (not reasons), reasons

    # -- transitions --------------------------------------------------------
    def transition(self, aid: str, to_state: str, actor: str = "operator",
                   actor_scope: str | None = None, detail: str = "") -> dict:
        cur = self.status.get(aid)
        key = (cur, to_state)

        def refuse(reason: str) -> dict:
            self._append({"type": "transition_refused", "assertion": aid,
                          "from": cur, "to": to_state, "reason": reason,
                          "actor": actor, "detail": detail})
            return {"applied": False, "refused": reason}

        if cur not in STATES:
            return refuse("unknown_status")
        if cur in TERMINAL:
            return refuse("terminal_state_no_outgoing_transitions")
        if key not in TRANSITIONS:
            return refuse("undefined_transition")
        guard = TRANSITIONS[key]

        a = self.assertions[aid]
        if to_state == "promoted":
            ok, reasons = self.evidence_gate(aid)
            if not ok:
                return refuse("evidence_gate_failed:" + ";".join(reasons))
            if actor_scope != a["scope"]:
                return refuse("promotion_actor_scope_mismatch")
        if key == ("challenged", "promoted") and not detail.strip():
            return refuse("operator_rationale_required")
        if key == ("promoted", "challenged") and not detail.strip():
            return refuse("challenge_provenance_required")
        if to_state == "retracted" and not detail.strip():
            return refuse("retraction_reason_required")
        if key == ("proposed", "rejected") and not detail.strip():
            return refuse("intake_rationale_required")
        if key == ("under_review", "rejected"):
            ok, reasons = self.evidence_gate(aid)
            if ok and not detail.strip():
                return refuse("rejection_requires_failed_gate_or_rationale")
        if to_state == "superseded":
            succ = self.successor.get(aid)
            if succ is None or succ not in self.assertions:
                return refuse("missing_superseding_assertion")

        # Atomic success: one TransitionEvent, then the status change.
        event = self._append({
            "type": "transition", "guard": guard, "assertion": aid,
            "from": cur, "to": to_state, "actor": actor,
            "actor_scope": actor_scope, "detail": detail,
        })
        if to_state == "promoted":
            self._append({"type": "promotion_recorded", "assertion": aid,
                          "activity": f"PromotionActivity:{aid}",
                          "actor": actor, "actor_scope": actor_scope})
        if to_state == "challenged":
            self._append({"type": "challenge_recorded", "assertion": aid,
                          "activity": f"ChallengeActivity:{aid}",
                          "challenger": actor, "detail": detail})
        if to_state == "retracted":
            self._append({"type": "retraction_recorded", "assertion": aid,
                          "activity": f"RetractionActivity:{aid}",
                          "reason": detail})
        if to_state == "superseded":
            self._append({"type": "supersession_recorded", "assertion": aid,
                          "successor": self.successor.get(aid)})
        self.status[aid] = to_state
        if to_state == "promoted":
            self.ever_promoted.add(aid)
        return {"applied": True, "event": event,
                "guard": guard, "from": cur, "to": to_state}

    # -- derived view -------------------------------------------------------
    def derived_view(self) -> list[str]:
        """Promoted-only projection (mirrors shapes-v3-promoted-only.ttl)."""
        return sorted(a for a in self.assertions if self.status[a] == "promoted")

    def independence_counts(self, aid: str) -> tuple[int, int]:
        a = self.assertions[aid]
        evs = [self.evidence[e] for e in a["supported_by"]]
        return (len({e["canonical_source_id"] for e in evs}),
                len({e["independence_group"] for e in evs}))


# ---------------------------------------------------------------------------
# Deterministic scenario exercising the whole lifecycle
# ---------------------------------------------------------------------------

def run_scenario() -> tuple[dict, list[dict]]:
    store = KnowledgeGateStore("workspace-knowledge")
    exercised: set[tuple[str, str]] = set()
    refusals: list[dict] = []
    checks: list[dict] = []
    failures: list[str] = []

    def check(name: str, passed: bool, detail) -> bool:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        if not passed:
            failures.append(f"{name}: {detail}")
        return bool(passed)

    def T(aid: str, to: str, **kw) -> dict:
        frm = store.status.get(aid)
        result = store.transition(aid, to, **kw)
        if result["applied"]:
            exercised.add((frm, to))
        else:
            refusals.append({"assertion": aid, "from": frm, "to": to,
                             "reason": result["refused"]})
        return result

    T1 = ("The MVP knowledge gate requires two independence groups before a "
          "message may promote.")
    T2 = ("A challenge or retraction must invalidate the derived knowledge "
          "view without deleting the immutable assertion.")
    T3 = ("Challenge queue items each require exactly one journaled operator "
          "decision.")

    for eid, args in (
        ("ev-a1-w3c", ("prov-o-w3c", "w3c", "w3c-prov-working-group")),
        ("ev-a1-toto", ("in-toto-cncf", "cncf", "cncf-in-toto")),
        ("ev-a2-shacl", ("shacl-w3c", "w3c", "w3c-data-shapes")),
        ("ev-a2-dung", ("dung-1995", "elsevier-ai", "dung-argumentation-framework")),
        ("ev-m2-queue", ("s1-001-queue", "agentos", "agentos-s1-001-artifacts")),
        ("ev-m2-tickets", ("stage1-tickets", "agentos", "agentos-stage1-planning")),
        ("ev-single-x", ("src-x", "pub-x", "group-x")),
        ("ev-mirror-x", ("src-x", "mirror-publisher-label", "group-x")),
        ("ev-bad-1", ("src-bad", "pub-bad", "")),
        ("ev-a3-1", ("a3-src-1", "pub-1", "group-a3-1")),
        ("ev-a3-2", ("a3-src-2", "pub-2", "group-a3-2")),
        ("ev-a3c-1", ("a3c-src-1", "pub-3", "group-a3c-1")),
        ("ev-a3c-2", ("a3c-src-2", "pub-4", "group-a3c-2")),
    ):
        store.add_evidence(make_evidence(eid, *args, scope="workspace-knowledge"))

    scope = store.scope

    # --- promoted baseline -------------------------------------------------
    store.declare_assertion("A1", T1, ["ev-a1-w3c", "ev-a1-toto"])
    T("A1", "under_review")
    r = T("A1", "promoted", actor="gate", actor_scope=scope)
    check("A1_control_promotes", r["applied"], r)

    store.declare_assertion("A2", T2, ["ev-a2-shacl", "ev-a2-dung"])
    T("A2", "under_review")
    r = T("A2", "promoted", actor="gate", actor_scope=scope)
    check("A2_control_promotes", r["applied"], r)

    # --- P1: single-source message whose text agrees with A1 ---------------
    store.declare_assertion("M-single", T1, ["ev-single-x"])
    agrees = _norm_text(T1) == _norm_text(store.assertions["A1"]["text"])
    check("P1_text_agrees_with_existing_promoted_claim", agrees,
          {"message": "M-single", "existing": "A1"})
    T("M-single", "under_review")
    attempt = T("M-single", "promoted", actor="gate", actor_scope=scope)
    reasons = attempt["refused"].split(":", 1)[1] if not attempt["applied"] else ""
    check("P1_single_source_never_promotes",
          (not attempt["applied"]) and store.status["M-single"] != "promoted"
          and "M-single" not in store.ever_promoted,
          {"refusal": attempt.get("refused"), "reasons": reasons,
           "status": store.status["M-single"]})
    check("P1_gate_reasons_independent_provenance",
          all(token in reasons for token in (
              "insufficient_evidence_count",
              "insufficient_distinct_canonical_sources",
              "insufficient_independence_groups")),
          reasons)

    # Mirror with a different publisher label must not change counts.
    store.declare_assertion("M-mirror", T1, ["ev-single-x", "ev-mirror-x"])
    T("M-mirror", "under_review")
    attempt_mirror = T("M-mirror", "promoted", actor="gate", actor_scope=scope)
    c_single, g_single = store.independence_counts("M-single")
    c_mirror, g_mirror = store.independence_counts("M-mirror")
    check("P1_mirror_delta_zero",
          (c_mirror, g_mirror) == (c_single, g_single) == (1, 1)
          and not attempt_mirror["applied"],
          {"canonical": [c_single, c_mirror], "groups": [g_single, g_mirror],
           "mirror_promotes": attempt_mirror["applied"]})
    T("M-mirror", "rejected", detail="single source; mirror does not add independence")
    T("M-single", "rejected",
      detail="single source; no second independence group after review")

    # Control: two independent groups promote (gate is not trivially refusing).
    store.declare_assertion("M2", T3, ["ev-m2-queue", "ev-m2-tickets"])
    T("M2", "under_review")
    r = T("M2", "promoted", actor="gate", actor_scope=scope)
    check("P1_control_two_groups_promotes", r["applied"], r)

    # --- intake rejection on EvidenceShape-invalid evidence ----------------
    store.declare_assertion("B0", "Incomplete evidence cannot enter review.",
                            ["ev-bad-1"])
    r = T("B0", "rejected",
          detail="intake: incomplete EvidenceShape provenance (no independence_group)")
    check("B0_intake_rejected", r["applied"], r)

    # --- P2: challenge and retraction invalidate the derived view ----------
    view_before = store.derived_view()
    snap_before = {
        "assertion_ids": sorted(store.assertions),
        "assertion_count": len(store.assertions),
        "event_count": len(store.events),
        "event_prefix": list(store.events),
        "hashes": dict(store.assertion_hashes),
        "view": list(view_before),
    }
    check("P2_view_before_contains_A2", "A2" in view_before, view_before)

    r = T("A2", "challenged", actor="agent-challenger",
          detail="challenge: counter-evidence offered by challenger agent")
    check("P2_challenge_removes_from_view",
          r["applied"] and store.status["A2"] == "challenged"
          and "A2" not in store.derived_view(),
          {"view_after_challenge": store.derived_view()})

    r = T("A2", "retracted", actor="operator",
          detail="challenge upheld: counter-evidence from an independent group")
    view_after = store.derived_view()
    marker = [e for e in store.events if e["type"] == "retraction_recorded"
              and e["assertion"] == "A2"]
    snap_after = {
        "assertion_ids": sorted(store.assertions),
        "assertion_count": len(store.assertions),
        "event_count": len(store.events),
        "hashes": dict(store.assertion_hashes),
    }
    check("P2_retraction_marker_added",
          r["applied"] and len(marker) == 1, [m["seq"] for m in marker])
    check("P2_nothing_deleted_row_counts",
          snap_after["assertion_ids"] == snap_before["assertion_ids"]
          and snap_after["assertion_count"] == snap_before["assertion_count"]
          and snap_after["event_count"] > snap_before["event_count"],
          {"assertions_before": snap_before["assertion_count"],
           "assertions_after": snap_after["assertion_count"],
           "events_before": snap_before["event_count"],
           "events_after": snap_after["event_count"]})
    check("P2_audit_history_append_only_prefix",
          snap_before["event_prefix"] == store.events[:snap_before["event_count"]],
          "pre-challenge journal is an exact prefix of the final journal")
    live_hashes_unchanged = all(
        _sha(store.assertions[aid]) == pinned
        for aid, pinned in store.assertion_hashes.items())
    check("P2_immutable_assertion_hashes_unchanged",
          snap_after["hashes"] == snap_before["hashes"] and live_hashes_unchanged,
          "every assertion payload re-hashes to its declaration-time digest")
    check("P2_view_invalidated_after_retraction",
          "A2" not in view_after and store.status["A2"] == "retracted",
          {"view_after_retraction": view_after})
    a2_chain = [e["type"] for e in store.events if e.get("assertion") == "A2"]
    check("P2_audit_history_preserved",
          a2_chain == ["assertion_declared", "transition", "transition",
                       "promotion_recorded", "transition", "challenge_recorded",
                       "transition", "retraction_recorded"],
          a2_chain)

    # Direct operator retraction of a promoted assertion (no challenge).
    r = T("M2", "retracted", actor="operator", detail="author withdrawal")
    check("P2_direct_retraction_invalidates_view",
          r["applied"] and "M2" not in store.derived_view(),
          {"view": store.derived_view()})

    # Dismissal path restores view membership.
    r = T("A1", "challenged", actor="agent-challenger",
          detail="challenge: mirror evidence offered as counter-evidence")
    dropped = "A1" not in store.derived_view()
    r2 = T("A1", "promoted", actor="operator", actor_scope=scope,
           detail="operator rationale: challenge evidence was a mirror of "
                  "existing support; no independent counter-evidence")
    check("P2_challenge_dismissal_restores_view",
          r["applied"] and dropped and r2["applied"]
          and "A1" in store.derived_view(),
          {"view": store.derived_view()})

    # --- supersession paths -------------------------------------------------
    store.declare_assertion("A3", T3 + " Version one.", ["ev-a3-1", "ev-a3-2"])
    T("A3", "under_review")
    T("A3", "promoted", actor="gate", actor_scope=scope)
    store.declare_assertion("A3b", T3 + " Version two.", ["ev-a3-1", "ev-a3-2"])
    T("A3b", "under_review")
    T("A3b", "promoted", actor="gate", actor_scope=scope)
    store.set_successor("A3", "A3b")
    r = T("A3", "superseded")
    check("P3_promoted_superseded_with_successor",
          r["applied"] and store.status["A3"] == "superseded"
          and "A3" not in store.derived_view(), r)

    r = T("A3b", "challenged", actor="agent-challenger",
          detail="challenge: wording conflicts with corrected policy")
    store.declare_assertion("A3c", T3 + " Corrected successor.",
                            ["ev-a3c-1", "ev-a3c-2"])
    T("A3c", "under_review")
    T("A3c", "promoted", actor="gate", actor_scope=scope)
    store.set_successor("A3b", "A3c")
    r = T("A3b", "superseded", actor="operator",
          detail="challenge resolved by publishing corrected successor")
    check("P3_challenge_resolved_by_supersession",
          r["applied"] and store.status["A3b"] == "superseded", r)

    # --- fail-closed refusals ------------------------------------------------
    status_before_refusals = dict(store.status)
    r1 = T("M2", "promoted")                    # from retracted: terminal
    r2 = T("A3", "challenged")                  # from superseded: terminal
    r3 = T("B0", "under_review")                # from rejected: terminal
    store.declare_assertion("A4", T2 + " Skip attempt.", ["ev-a1-w3c", "ev-a1-toto"])
    r4 = T("A4", "promoted")                    # undefined: proposed skips review
    check("P3_terminal_and_undefined_refused_fail_closed",
          all(not x["applied"] for x in (r1, r2, r3, r4))
          and all(r["refused"] for r in (r1, r2, r3, r4)),
          [x.get("refused") for x in (r1, r2, r3, r4)])
    check("P3_refusals_change_no_status",
          status_before_refusals | {"A4": "proposed"} == store.status,
          "status snapshot identical after refusals")
    refusal_events = [e for e in store.events if e["type"] == "transition_refused"]
    check("P3_refusals_audited", len(refusal_events) >= 4, len(refusal_events))

    # --- P3: transition completeness ----------------------------------------
    check("P3_all_states_from_s1_003_vocabulary",
          set(STATES) == {"proposed", "under_review", "promoted", "challenged",
                          "retracted", "superseded", "rejected"},
          sorted(STATES))
    check("P3_every_transition_defined_with_guard",
          len(TRANSITIONS) == 10 and all(
              isinstance(g, str) and g for g in TRANSITIONS.values()),
          {f"{f}->{t}": g for (f, t), g in sorted(TRANSITIONS.items())})
    non_terminal = [s for s in STATES if s not in TERMINAL]
    check("P3_non_terminal_states_have_exits",
          all(any(f == s for (f, _t) in TRANSITIONS) for s in non_terminal),
          non_terminal)
    check("P3_terminal_states_have_no_exits",
          not any(f in TERMINAL for (f, _t) in TRANSITIONS),
          sorted(TERMINAL))
    check("P3_transition_targets_valid",
          all(t in STATES for (_f, t) in TRANSITIONS), "all targets in vocabulary")
    check("P3_all_transitions_exercised",
          set(exercised) == set(TRANSITIONS),
          {"missing": sorted(set(TRANSITIONS) - set(exercised)),
           "exercised": sorted(exercised)})

    # --- journal/status consistency (atomicity) ------------------------------
    consistent = True
    history: dict[str, list[str]] = {}
    for e in store.events:
        if e["type"] == "transition":
            history.setdefault(e["assertion"], []).append(e["to"])
    for aid, chain in history.items():
        expected = "proposed"
        ok_chain = True
        for step_to in chain:
            if (expected, step_to) not in TRANSITIONS:
                ok_chain = False
                break
            expected = step_to
        if not ok_chain or store.status[aid] != expected:
            consistent = False
    check("P3_journal_matches_status_history", consistent,
          {aid: chain for aid, chain in sorted(history.items())})
    check("P3_terminal_statuses_stable",
          all(store.status[a] in TERMINAL for a in ("A2", "M2", "A3", "A3b", "B0",
                                                    "M-single", "M-mirror")),
          {a: store.status[a] for a in ("A2", "M2", "A3", "A3b", "B0",
                                        "M-single", "M-mirror")})

    details = {
        "view_final": store.derived_view(),
        "statuses_final": dict(sorted(store.status.items())),
        "assertion_rows": len(store.assertions),
        "audit_rows": len(store.events),
        "refusals": refusals,
    }
    return {"checks": checks, "details": details, "failures": failures,
            "exercised": sorted(exercised)}, []


def main(argv=None) -> int:
    result, _ = run_scenario()
    observed = "pass" if not result["failures"] else "fail"
    report = {
        "schema": "agentos.s1-011-lifecycle-probe/v1",
        "probe": "s1-011-lifecycle-adversarial",
        "expected": "pass",
        "observed": observed,
        "status": observed,
        "total_checks": len(result["checks"]),
        "passed_checks": sum(1 for c in result["checks"] if c["passed"]),
        "failures": result["failures"],
        "checks": result["checks"],
        "transitions_exercised": result["exercised"],
        "details": result["details"],
    }
    RESULTS.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8", newline="\n")
    print(json.dumps({
        "schema": report["schema"],
        "probe": report["probe"],
        "status": observed,
        "observed": observed,
        "expected": "pass",
        "total_checks": report["total_checks"],
        "passed_checks": report["passed_checks"],
        "failures": report["failures"],
        "results_file": str(RESULTS),
    }, ensure_ascii=False))
    return 0 if observed == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
