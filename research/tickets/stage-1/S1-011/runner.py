"""S1-011 deterministic gate runner (stdlib only, no network/LLM).

Evaluates the frozen corpus (cases.json) under one design semantics and
emits raw observations plus a run manifest. All three designs share the
same governance plumbing (authority, challenge/retraction/replay/read/
concurrency/external procedures); they differ ONLY in the promote-family
acceptance rule, which is exactly what the ticket compares:

- minimal-gate: provisional threshold checklist (>=2 verified evidence,
  >=2 distinct lineages AND >=2 declared independence groups, same claim
  version/scope, no unresolved challenge/revocation, provenance/digest/
  policy present, governance-only final step).
- argumentation: grounded-style acceptability. Claim IN iff >=1 accepted
  supporter and every attacker is OUT (countered by fresh evidence).
  Independence counting is NOT applied (faithful naive variant); transitive
  parent support counts as support (probe G exercises this).
- tms: justification holding (>=1 justification with all IN-nodes eligible
  and all OUT-nodes revoked/absent, no live contradiction). Promotion is
  automatic belief revision by actor tms_engine (no governance decision),
  which the evaluator scores against the authority invariant.

Seeds are recorded but outputs are seed-invariant by construction (exact
deterministic replay); the evaluator cross-checks seed invariance.

Usage:
  py -3.12 runner.py --cases cases.json --design minimal-gate \\
      --seed 11011 --out results/run-a
Writes <out>/raw-observations.json and <out>/run-manifest.json.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import secrets
import subprocess
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY_CURRENT = "s1-011-policy-v1"
DESIGNS = ("minimal-gate", "argumentation", "tms")
GOVERNANCE_ACTORS = ("governance_gate", "operator")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(sym: str) -> str:
    # Same rule as canonicalize_corpus.digest (duplicated to avoid
    # cross-module imports; rule also documented in corpus-manifest.json).
    return sha(f"s1-011:digest:{sym}".encode("utf-8"))


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=HERE.parents[3],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: "
                           f"{proc.stderr[:200]}")
    return proc.stdout.strip()


def file_hashes() -> dict:
    names = ["cases.json", "knowledge-gate-contract.json",
             "state-machine.json", "rubric.json", "design-alternatives.json",
             "knowledge-record.schema.json", "source-registry.json",
             "runner.py", "evaluator.py"]
    out = {}
    for name in names:
        path = HERE / name
        out[name] = sha(path.read_bytes()) if path.is_file() else None
    return out


class Case:
    REQUIRED = ("actor_role", "tenant", "workspace", "goal", "scope",
                "policy_version", "idempotency_key")

    def __init__(self, raw: dict):
        self.raw = raw
        self.id = raw.get("case_id", "")
        self.action = raw.get("action", "")
        self.prior = raw.get("prior_status", "PROPOSED")
        self.actor = raw.get("actor_role")
        self.scope = raw.get("scope")
        self.policy = raw.get("policy_version")
        assertion = raw.get("assertion") or {}
        self.assertion_id = assertion.get("assertion_id")
        self.claim_version = assertion.get("claim_version")
        self.evidence = raw.get("evidence", []) or []
        self.challenge = raw.get("challenge")
        self.revoked = set(raw.get("source_revoked", []) or [])
        self.prior_keys = {d.get("idempotency_key") for d in
                           (raw.get("prior_decisions", []) or [])}
        self.key = raw.get("idempotency_key")

    def field_problems(self) -> list:
        """Fail-closed input validation. No defaults: a missing or empty
        required field is a problem, never silently repaired."""
        problems = []
        for key in self.REQUIRED:
            value = self.raw.get(key)
            if not isinstance(value, str) or not value:
                problems.append(f"missing {key}")
        if not isinstance(self.assertion_id, str) or not self.assertion_id:
            problems.append("missing assertion.assertion_id")
        if not isinstance(self.claim_version, int) or \
                isinstance(self.claim_version, bool):
            problems.append("missing assertion.claim_version")
        if not isinstance(self.id, str) or not self.id:
            problems.append("missing case_id")
        if self.action not in ("propose", "promote", "challenge", "uphold",
                               "retract", "revoke_source", "supersede",
                               "replay_decision", "read_view",
                               "derive_claim", "concurrent",
                               "external_inject"):
            problems.append(f"unknown action {self.action!r}")
        return problems

    def evidence_wellformed(self, ev: dict) -> bool:
        """Structural binding: 64-hex digest equal to the corpus digest
        rule, verified a real boolean, non-empty lineage and group."""
        if not isinstance(ev.get("digest"), str) or \
                len(ev.get("digest", "")) != 64:
            return False
        try:
            int(ev["digest"], 16)
        except ValueError:
            return False
        if ev["digest"] != digest(ev.get("evidence_id", "\x00") if
                                  isinstance(ev.get("evidence_id"), str)
                                  else "\x00"):
            return False
        if not isinstance(ev.get("verified"), bool):
            return False
        if not ev.get("lineage") or not ev.get("group"):
            return False
        return True

    def evidence_trusted(self, ev: dict) -> bool:
        """Semantic trust: verified true, source ACTIVE and lineage live."""
        if ev.get("verified") is not True:
            return False
        if ev.get("source_status", "ACTIVE") != "ACTIVE":
            return False
        return self.lineage_active(ev.get("lineage", ""))

    def evidence_binding_ok(self, ev: dict) -> bool:
        return self.evidence_wellformed(ev) and self.evidence_trusted(ev)

    def ev_scope(self, ev: dict) -> str:
        return ev.get("scope", self.scope)

    def ev_version(self, ev: dict) -> int:
        return ev.get("claim_version", self.claim_version)

    def lineage_active(self, lineage: str) -> bool:
        return bool(lineage) and lineage not in self.revoked

    def eligible(self, ev: dict) -> bool:
        return self.evidence_binding_ok(ev) and \
            self.ev_version(ev) == self.claim_version and \
            self.ev_scope(ev) == self.scope

    def eligible_items(self) -> list:
        return [ev for ev in self.evidence if self.eligible(ev)]

    def open_challenge(self) -> bool:
        return bool(self.challenge) and \
            self.challenge.get("state") == "open" and \
            bool(self.challenge.get("in_scope"))

    def policy_ok(self) -> bool:
        return self.policy == POLICY_CURRENT

    def scope_clean(self) -> bool:
        return all(self.ev_scope(ev) == self.scope for ev in self.evidence)

    def correlated(self, items: list) -> bool:
        lineages = {ev.get("lineage", "") for ev in items}
        groups = {ev.get("group", "") for ev in items}
        return len(lineages) < 2 or len(groups) < 2


def ledger_for(case: Case, design: str, seed: int, decision: str,
               transition, reason: str, actor: str,
               audit: list) -> list:
    """Deterministic hash-chained record model (an honest executable
    model of immutable records, not production storage). Each record
    carries {kind, id, prev, payload, hash}; genesis prev is zeros.
    Ids derive from case+design only (seed-invariant rows; A/B
    agreement for equal seeds is what the comparison checks)."""
    base = f"{case.id}:{design}"
    chain = []
    prev = "0" * 64

    def append(kind: str, name: str, payload: dict) -> None:
        nonlocal prev
        record = {"kind": kind, "id": f"{kind}-{name}-{sha(base.encode())[:12]}",
                  "prev": prev, "payload": payload}
        record["hash"] = sha(canonical(
            {k: record[k] for k in ("kind", "id", "prev", "payload")}))
        prev = record["hash"]
        chain.append(record)

    append("assertion", "a", {"assertion_id": case.assertion_id,
                              "claim_version": case.claim_version,
                              "status": case.prior})
    for ev in case.evidence:
        append("evidence", str(ev.get("evidence_id", "?")),
               {"evidence_id": ev.get("evidence_id"),
                "digest": ev.get("digest"),
                "verified": ev.get("verified"),
                "lineage": ev.get("lineage"),
                "group": ev.get("group")})
    decision_id = f"decision-{sha(base.encode())[:12]}"
    append("decision", "d", {"decision_id": decision_id,
                             "decision": decision,
                             "transition": transition,
                             "actor": actor,
                             "reason_code": reason,
                             "policy_version": case.policy})
    for event in audit:
        append("audit", str(event).lower(),
               {"event": event, "decision_id": decision_id,
                "actor": actor, "reason_code": reason})
    return chain


def out_row(case: Case, design: str, seed: int, decision: str,
            transition, reason: str, visible: bool, audit: list,
            actor: str) -> dict:
    row = {"case_id": case.id, "design": design, "seed": seed,
           "action": case.action, "prior_status": case.prior,
           "decision": decision, "transition": transition,
           "reason_code": reason, "view_visible": visible,
           "audit_events": audit, "history_preserved": True,
           "actor": actor, "idempotency_key": case.key,
           "policy_version": case.policy,
           "ledger": ledger_for(case, design, seed, decision,
                                transition, reason, actor, audit)}
    row["output_sha256"] = sha(canonical(
        {k: v for k, v in row.items() if k != "output_sha256"}))
    return row


def precheck(case: Case, design: str, seed: int):
    """Fail-closed input gate shared by all designs. Returns a deny row
    or None (proceed). Unknown actions and missing/empty required fields
    never transition."""
    problems = case.field_problems()
    if not problems:
        return None
    if any(p.startswith("unknown action") for p in problems):
        reason = "UNKNOWN_TRANSITION"
    elif any("actor_role" in p for p in problems):
        reason = "AUTHORITY_DENIED"
    else:
        reason = "MISSING_REQUIRED_FIELD"
    actor = case.actor if isinstance(case.actor, str) and case.actor \
        else "unknown"
    return out_row(case, design, seed, "NO_TRANSITION", None, reason,
                   False, [], actor)


def current_view(case: Case) -> bool:
    """Full derived-view inclusion predicate evaluated at decision time:
    prior PROMOTED, no open challenge, no revoked bound lineage, policy
    current, epoch current, no cross-scope read."""
    if case.prior != "PROMOTED":
        return False
    if case.open_challenge():
        return False
    if case.revoked:
        bound = {ev.get("lineage", "") for ev in case.evidence}
        if case.revoked & bound:
            return False
    if not case.policy_ok():
        return False
    if case.raw.get("view_epoch") == "stale":
        return False
    if case.raw.get("cross_scope"):
        return False
    return True


def binding_broken(case: Case) -> bool:
    """True when evidence is present but at least one item is
    structurally malformed (bad digest, non-boolean verified, missing
    lineage/group). Trust failures (unverified, revoked) are not
    malformed: they make items ineligible, not invalid."""
    return any(not case.evidence_wellformed(ev) for ev in case.evidence)


def decide_minimal(case: Case, seed: int) -> dict:
    d = "minimal-gate"
    act = case.action
    denied = precheck(case, d, seed)
    if denied is not None:
        return denied
    if act == "propose":
        if case.actor in ("worker", "operator", "governance_gate"):
            return out_row(case, d, seed, "RECORDED", None, "THRESHOLD_MET",
                           False, ["PROPOSE"], case.actor)
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "AUTHORITY_DENIED", False, [], case.actor)
    if act == "promote":
        if case.key and case.key in case.prior_keys:
            # Duplicate shortcut only when the full current predicate
            # still holds; otherwise fall through to fresh evaluation so
            # a stale record can never restore visibility.
            if case.prior == "PROMOTED" and current_view(case):
                return out_row(case, d, seed, "NO_TRANSITION", None,
                               "DUPLICATE_IDEMPOTENT", True, [], case.actor)
            if case.prior == "PROMOTED" and not current_view(case):
                return out_row(case, d, seed, "NO_TRANSITION", None,
                               "DUPLICATE_IDEMPOTENT", False, [],
                               case.actor)
        if case.actor not in GOVERNANCE_ACTORS:
            return out_row(case, d, seed, "NO_TRANSITION", None,
                           "AUTHORITY_DENIED", False, [], case.actor)
        if case.prior != "PROPOSED":
            return out_row(case, d, seed, "NO_TRANSITION", None,
                           "UNKNOWN_TRANSITION", current_view(case),
                           [], case.actor)
        if case.open_challenge():
            return out_row(case, d, seed, "NO_TRANSITION", None,
                           "CHALLENGE_OPENED", False, [], case.actor)
        if not case.policy_ok():
            return out_row(case, d, seed, "REJECTED", "gate_fail",
                           "POLICY_MISMATCH", False, ["REJECT"], case.actor)
        if not case.scope_clean():
            return out_row(case, d, seed, "REJECTED", "gate_fail",
                           "SCOPE_MISMATCH", False, ["REJECT"], case.actor)
        items = case.eligible_items()
        if len(items) < 2 or case.correlated(items):
            if binding_broken(case):
                reason = "INVALID_EVIDENCE_BINDING"
            else:
                ev = case.evidence
                lineages = {e.get("lineage", "") for e in ev}
                groups = {e.get("group", "") for e in ev}
                reason = "EVIDENCE_CORRELATED" if len(ev) >= 2 and (
                    len(lineages) < 2 or len(groups) < 2) else \
                    "EVIDENCE_INSUFFICIENT"
            return out_row(case, d, seed, "REJECTED", "gate_fail", reason,
                           False, ["REJECT"], case.actor)
        return out_row(case, d, seed, "PROMOTED", "gate_pass",
                       "THRESHOLD_MET", True, ["PROMOTE"], case.actor)
    if act == "challenge":
        if case.prior == "PROMOTED" and case.open_challenge() and \
                case.actor in ("worker", "operator", "governance_gate"):
            return out_row(case, d, seed, "CHALLENGED", "challenge_accepted",
                           "CHALLENGE_OPENED", False, ["CHALLENGE"],
                           case.actor)
        if case.prior == "PROMOTED" and case.challenge and \
                not case.challenge.get("in_scope", True):
            return out_row(case, d, seed, "NO_TRANSITION", None,
                           "SCOPE_MISMATCH", True, [], case.actor)
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "DUPLICATE_IDEMPOTENT", case.prior == "PROMOTED",
                       [], case.actor)
    if act == "uphold":
        if case.actor not in GOVERNANCE_ACTORS:
            return out_row(case, d, seed, "NO_TRANSITION", None,
                           "AUTHORITY_DENIED", False, [], case.actor)
        if case.prior == "CHALLENGED" and case.challenge and \
                case.challenge.get("state") == "resolved" and \
                case.challenge.get("fresh_evidence"):
            items = case.eligible_items()
            if len(items) >= 2 and not case.correlated(items) and \
                    case.policy_ok() and not binding_broken(case):
                return out_row(case, d, seed, "PROMOTED",
                               "upheld_with_evidence", "CHALLENGE_UPHELD",
                               True, ["UPHOLD"], case.actor)
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "THRESHOLD_NOT_MET", False, [], case.actor)
    if act == "retract":
        if case.prior == "CHALLENGED":
            if case.actor not in GOVERNANCE_ACTORS:
                return out_row(case, d, seed, "NO_TRANSITION", None,
                               "AUTHORITY_DENIED", False, [], case.actor)
            return out_row(case, d, seed, "RETRACTED",
                           "challenge_sustained_or_expired",
                           "CHALLENGE_SUSTAINED", False, ["RETRACT"],
                           case.actor)
        if case.prior == "PROPOSED" and case.actor in ("worker",
                                                       "operator"):
            return out_row(case, d, seed, "RETRACTED", "withdrawn",
                           "WITHDRAWN", False, ["RETRACT"], case.actor)
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "UNKNOWN_TRANSITION", False, [], case.actor)
    if act == "revoke_source":
        if case.actor not in GOVERNANCE_ACTORS:
            return out_row(case, d, seed, "NO_TRANSITION", None,
                           "AUTHORITY_DENIED", False, [], case.actor)
        if case.prior == "PROMOTED":
            return out_row(case, d, seed, "CHALLENGED", "source_revoked",
                           "SOURCE_REVOKED", False, ["CHALLENGE"],
                           case.actor)
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "UNKNOWN_TRANSITION", False, [], case.actor)
    if act == "supersede":
        if case.actor != "governance_gate":
            return out_row(case, d, seed, "NO_TRANSITION", None,
                           "AUTHORITY_DENIED", False, [], case.actor)
        if case.prior == "PROMOTED" and case.raw.get("superseded_by"):
            return out_row(case, d, seed, "RETRACTED", "superseded",
                           "SUPERSEDED", False, ["SUPERSEDE"], case.actor)
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "UNKNOWN_TRANSITION", False, [], case.actor)
    if act == "replay_decision":
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "REPLAY_REJECTED", False, ["REPLAY"], case.actor)
    if act == "read_view":
        if case.raw.get("cross_scope"):
            return out_row(case, d, seed, "HIDDEN", None, "SCOPE_MISMATCH",
                           False, ["READ"], case.actor)
        if case.raw.get("view_epoch") == "stale":
            return out_row(case, d, seed, "HIDDEN", None, "STALE_EPOCH",
                           False, ["READ"], case.actor)
        if not case.policy_ok():
            return out_row(case, d, seed, "HIDDEN", None, "POLICY_MISMATCH",
                           False, ["READ"], case.actor)
        if current_view(case):
            return out_row(case, d, seed, "VISIBLE", None, "THRESHOLD_MET",
                           True, ["READ"], case.actor)
        return out_row(case, d, seed, "HIDDEN", None, "CHALLENGE_SUSTAINED",
                       False, ["READ"], case.actor)
    if act == "derive_claim":
        if case.actor not in GOVERNANCE_ACTORS:
            return out_row(case, d, seed, "NO_TRANSITION", None,
                           "AUTHORITY_DENIED", False, [], case.actor)
        derive = case.raw.get("derive") or {}
        if derive.get("own_evidence"):
            items = case.eligible_items()
            if case.policy_ok() and len(items) >= 2 and \
                    not case.correlated(items) and \
                    not binding_broken(case):
                return out_row(case, d, seed, "PROMOTED", "gate_pass",
                               "THRESHOLD_MET", True, ["DERIVE", "PROMOTE"],
                               case.actor)
        return out_row(case, d, seed, "NOT_PROMOTED", None,
                       "THRESHOLD_NOT_MET", False, ["DERIVE"], case.actor)
    if act == "concurrent":
        ops = case.raw.get("concurrent", []) or []
        if "challenge" in ops and case.open_challenge():
            if case.actor not in ("worker", "operator",
                                  "governance_gate"):
                return out_row(case, d, seed, "NO_TRANSITION", None,
                               "AUTHORITY_DENIED", False, [], case.actor)
            return out_row(case, d, seed, "CHALLENGED", "challenge_accepted",
                           "CONCURRENT_RESOLVED", False, ["CHALLENGE"],
                           case.actor)
        if set(ops) == {"promote"}:
            if case.actor not in GOVERNANCE_ACTORS:
                return out_row(case, d, seed, "NO_TRANSITION", None,
                               "AUTHORITY_DENIED", False, [], case.actor)
            items = case.eligible_items()
            if case.policy_ok() and len(items) >= 2 and \
                    not case.correlated(items) and \
                    not binding_broken(case) and not case.open_challenge():
                return out_row(case, d, seed, "PROMOTED", "gate_pass",
                               "CONCURRENT_RESOLVED", True, ["PROMOTE"],
                               case.actor)
            return out_row(case, d, seed, "REJECTED", "gate_fail",
                           "THRESHOLD_NOT_MET", False, ["REJECT"],
                           case.actor)
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "UNKNOWN_TRANSITION", False, [], case.actor)
    if act == "external_inject":
        return out_row(case, d, seed, "QUARANTINED", None,
                       "EXTERNAL_CONTENT_QUARANTINED",
                       case.prior == "PROMOTED", [], case.actor)
    return out_row(case, d, seed, "NO_TRANSITION", None,
                   "UNKNOWN_TRANSITION", False, [], case.actor)


def decide_argumentation(case: Case, seed: int) -> dict:
    """Same plumbing as minimal except the promote-family acceptance rule:
    grounded-style IN (supporters>=1, all attackers OUT) replaces the
    independence-counting threshold. Scope/policy/authority preconditions
    are shared."""
    d = "argumentation"
    denied = precheck(case, d, seed)
    if denied is not None:
        return denied
    if case.action not in ("promote", "uphold", "derive_claim",
                           "concurrent"):
        row = decide_minimal(case, seed)
        row["design"] = d
        row["output_sha256"] = sha(canonical(
            {k: v for k, v in row.items() if k != "output_sha256"}))
        return row
    if case.action == "concurrent" and "challenge" in (
            case.raw.get("concurrent", []) or []):
        row = decide_minimal(case, seed)
        row["design"] = d
        row["output_sha256"] = sha(canonical(
            {k: v for k, v in row.items() if k != "output_sha256"}))
        return row
    # Shared preconditions first.
    if case.action == "promote" and case.actor not in GOVERNANCE_ACTORS:
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "AUTHORITY_DENIED", False, [], case.actor)
    if case.action in ("derive_claim", "concurrent") and \
            case.actor not in GOVERNANCE_ACTORS:
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "AUTHORITY_DENIED", False, [], case.actor)
    if not case.policy_ok():
        audit = ["REJECT"] if case.action == "promote" else []
        return out_row(case, d, seed, "REJECTED", "gate_fail",
                       "POLICY_MISMATCH", False, audit, case.actor)
    if not case.scope_clean():
        return out_row(case, d, seed, "REJECTED", "gate_fail",
                       "SCOPE_MISMATCH", False, ["REJECT"], case.actor)
    derive = case.raw.get("derive") or {}
    supporters = [ev.get("evidence_id") for ev in case.eligible_items()]
    if case.action == "derive_claim" and not derive.get("own_evidence"):
        if derive.get("parent"):
            supporters = [f"transitive:{derive['parent']}"]
    attackers = []
    if case.open_challenge():
        countered = bool(case.challenge.get("fresh_evidence")) and \
            len(case.eligible_items()) >= 1
        attackers.append({"id": case.challenge.get("challenge_id"),
                          "out": countered})
    claim_in = len(supporters) >= 1 and all(a["out"] for a in attackers)
    if case.action == "uphold":
        if case.actor not in GOVERNANCE_ACTORS:
            return out_row(case, d, seed, "NO_TRANSITION", None,
                           "AUTHORITY_DENIED", False, [], case.actor)
        if case.prior == "CHALLENGED" and claim_in and \
                case.challenge.get("state") == "resolved":
            return out_row(case, d, seed, "PROMOTED",
                           "upheld_with_evidence", "CHALLENGE_UPHELD",
                           True, ["UPHOLD"], case.actor)
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "THRESHOLD_NOT_MET", False, [], case.actor)
    if case.action == "derive_claim":
        if claim_in and derive.get("own_evidence"):
            return out_row(case, d, seed, "PROMOTED", "gate_pass",
                           "THRESHOLD_MET", True, ["DERIVE", "PROMOTE"],
                           case.actor)
        if claim_in and not derive.get("own_evidence"):
            # Naive transitive support: parent IN suffices (probe G target).
            return out_row(case, d, seed, "PROMOTED", "gate_pass",
                           "THRESHOLD_MET", True, ["DERIVE", "PROMOTE"],
                           case.actor)
        return out_row(case, d, seed, "NOT_PROMOTED", None,
                       "THRESHOLD_NOT_MET", False, ["DERIVE"], case.actor)
    if case.action == "concurrent":
        if claim_in:
            return out_row(case, d, seed, "PROMOTED", "gate_pass",
                           "CONCURRENT_RESOLVED", True, ["PROMOTE"],
                           case.actor)
        return out_row(case, d, seed, "REJECTED", "gate_fail",
                       "THRESHOLD_NOT_MET", False, ["REJECT"], case.actor)
    # promote
    if case.key and case.key in case.prior_keys:
        if case.prior == "PROMOTED":
            return out_row(case, d, seed, "NO_TRANSITION", None,
                           "DUPLICATE_IDEMPOTENT", current_view(case),
                           [], case.actor)
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "DUPLICATE_IDEMPOTENT", False, [], case.actor)
    if case.prior != "PROPOSED":
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "UNKNOWN_TRANSITION", current_view(case),
                       [], case.actor)
    if case.open_challenge():
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "CHALLENGE_OPENED", False, [], case.actor)
    if claim_in:
        return out_row(case, d, seed, "PROMOTED", "gate_pass",
                       "THRESHOLD_MET", True, ["PROMOTE"], case.actor)
    reason = "EVIDENCE_INSUFFICIENT" if not supporters else \
        "CHALLENGE_OPENED"
    if case.open_challenge() and not supporters:
        reason = "EVIDENCE_INSUFFICIENT"
    return out_row(case, d, seed, "REJECTED", "gate_fail", reason, False,
                   ["REJECT"], case.actor)


def decide_tms(case: Case, seed: int) -> dict:
    """Same plumbing as minimal except promote-family acceptance is
    automatic justification holding, executed by actor tms_engine (no
    governance decision) — the faithful naive TMS loop the authority
    invariant scores against."""
    d = "tms"
    denied = precheck(case, d, seed)
    if denied is not None:
        return denied
    if case.action not in ("promote", "uphold", "derive_claim",
                           "concurrent"):
        row = decide_minimal(case, seed)
        row["design"] = d
        row["output_sha256"] = sha(canonical(
            {k: v for k, v in row.items() if k != "output_sha256"}))
        return row
    if case.action == "concurrent" and "challenge" in (
            case.raw.get("concurrent", []) or []):
        row = decide_minimal(case, seed)
        row["design"] = d
        row["output_sha256"] = sha(canonical(
            {k: v for k, v in row.items() if k != "output_sha256"}))
        return row
    if not case.policy_ok():
        audit = ["REJECT"] if case.action in ("promote",) else []
        return out_row(case, d, seed, "REJECTED", "gate_fail",
                       "POLICY_MISMATCH", False, audit, "tms_engine")
    if case.action in ("promote", "uphold", "derive_claim",
                       "concurrent") and \
            case.actor not in GOVERNANCE_ACTORS:
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "AUTHORITY_DENIED", False, [], case.actor)
    if not case.scope_clean():
        return out_row(case, d, seed, "REJECTED", "gate_fail",
                       "SCOPE_MISMATCH", False, ["REJECT"], "tms_engine")
    items = case.eligible_items()
    contradiction = case.open_challenge()
    belief_in = len(items) >= 1 and not contradiction
    if case.action == "uphold":
        if case.prior == "CHALLENGED" and case.challenge and \
                case.challenge.get("state") == "resolved" and \
                case.challenge.get("fresh_evidence") and belief_in:
            return out_row(case, d, seed, "PROMOTED",
                           "upheld_with_evidence", "CHALLENGE_UPHELD",
                           True, ["UPHOLD"], "tms_engine")
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "THRESHOLD_NOT_MET", False, [], "tms_engine")
    if case.action == "derive_claim":
        derive = case.raw.get("derive") or {}
        if belief_in and derive.get("own_evidence"):
            return out_row(case, d, seed, "PROMOTED", "gate_pass",
                           "THRESHOLD_MET", True, ["DERIVE", "PROMOTE"],
                           "tms_engine")
        if not derive.get("own_evidence") and derive.get("parent"):
            # Automatic propagation through the justification network.
            return out_row(case, d, seed, "PROMOTED", "gate_pass",
                           "THRESHOLD_MET", True, ["DERIVE", "PROMOTE"],
                           "tms_engine")
        return out_row(case, d, seed, "NOT_PROMOTED", None,
                       "THRESHOLD_NOT_MET", False, ["DERIVE"], "tms_engine")
    if case.action == "concurrent":
        if belief_in:
            return out_row(case, d, seed, "PROMOTED", "gate_pass",
                           "CONCURRENT_RESOLVED", True, ["PROMOTE"],
                           "tms_engine")
        return out_row(case, d, seed, "REJECTED", "gate_fail",
                       "THRESHOLD_NOT_MET", False, ["REJECT"], "tms_engine")
    # promote
    if case.key and case.key in case.prior_keys:
        if case.prior == "PROMOTED":
            return out_row(case, d, seed, "NO_TRANSITION", None,
                           "DUPLICATE_IDEMPOTENT", current_view(case),
                           [], "tms_engine")
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "DUPLICATE_IDEMPOTENT", False, [], "tms_engine")
    if case.prior != "PROPOSED":
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "UNKNOWN_TRANSITION", current_view(case),
                       [], "tms_engine")
    if case.open_challenge():
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "CHALLENGE_OPENED", False, [], "tms_engine")
    if belief_in:
        return out_row(case, d, seed, "PROMOTED", "gate_pass",
                       "THRESHOLD_MET", True, ["PROMOTE"], "tms_engine")
    reason = "EVIDENCE_INSUFFICIENT"
    return out_row(case, d, seed, "REJECTED", "gate_fail", reason, False,
                   ["REJECT"], "tms_engine")


DECIDE = {"minimal-gate": decide_minimal, "argumentation":
          decide_argumentation, "tms": decide_tms}


def main() -> int:
    parser = argparse.ArgumentParser(description="S1-011 gate runner")
    parser.add_argument("--cases", default="cases.json")
    parser.add_argument("--design", required=True, choices=DESIGNS)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    cases_path = HERE / args.cases
    corpus = json.loads(cases_path.read_text(encoding="utf-8"))
    decide = DECIDE[args.design]
    rows = [decide(Case(raw), args.seed) for raw in corpus["cases"]]

    try:
        commit = git("rev-parse", "HEAD")
        tree = git("rev-parse", "HEAD^{tree}")
        dirty = bool(git("status", "--short"))
        describe = git("describe", "--always", "--dirty")
    except RuntimeError as exc:
        print(f"git provenance failed: {exc}", file=sys.stderr)
        return 1

    manifest = {
        "schema": "agentos.s1-011.run-manifest/v1",
        "ticket": "S1-011",
        "design": args.design,
        "seed": args.seed,
        "rows": len(rows),
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "invocation_id": uuid.uuid4().hex,
        "nonce": secrets.token_hex(16),
        "executor_id": f"{getpass.getuser()}@{platform.node()}"
                       f"#{os.getpid()}",
        "commit": commit,
        "tree": tree,
        "clean_tree": not dirty,
        "describe": describe,
        "python": sys.version.split()[0],
        "input_hashes": file_hashes(),
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = dict(manifest)
    manifest["output_root"] = str(out_dir.resolve())
    (out_dir / "raw-observations.json").write_text(
        json.dumps({"schema": "agentos.s1-011.raw-observations/v1",
                    "design": args.design, "seed": args.seed,
                    "rows": rows}, indent=2) + "\n", encoding="utf-8",
        newline="\n")
    (out_dir / "run-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
        newline="\n")
    print(f"design={args.design} seed={args.seed} rows={len(rows)} "
          f"pid={manifest['pid']} commit={commit[:12]} "
          f"clean={manifest['clean_tree']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
