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
    def __init__(self, raw: dict):
        self.raw = raw
        self.id = raw["case_id"]
        self.action = raw["action"]
        self.prior = raw.get("prior_status", "PROPOSED")
        self.actor = raw.get("actor_role", "governance_gate")
        self.scope = raw.get("scope", "SCOPE-KB-1")
        self.policy = raw.get("policy_version", POLICY_CURRENT)
        assertion = raw.get("assertion") or {}
        self.claim_version = assertion.get("claim_version", 1)
        self.evidence = raw.get("evidence", []) or []
        self.challenge = raw.get("challenge")
        self.revoked = set(raw.get("source_revoked", []) or [])
        self.prior_keys = {d.get("idempotency_key") for d in
                           (raw.get("prior_decisions", []) or [])}
        self.key = raw.get("idempotency_key", "")

    def ev_scope(self, ev: dict) -> str:
        return ev.get("scope", self.scope)

    def ev_version(self, ev: dict) -> int:
        return ev.get("claim_version", self.claim_version)

    def lineage_active(self, lineage: str) -> bool:
        return bool(lineage) and lineage not in self.revoked

    def eligible(self, ev: dict) -> bool:
        return bool(ev.get("verified")) and self.lineage_active(
            ev.get("lineage", "")) and self.ev_version(ev) == \
            self.claim_version and self.ev_scope(ev) == self.scope and \
            bool(ev.get("group"))

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


def out_row(case: Case, design: str, seed: int, decision: str,
            transition, reason: str, visible: bool, audit: list,
            actor: str) -> dict:
    row = {"case_id": case.id, "design": design, "seed": seed,
           "decision": decision, "transition": transition,
           "reason_code": reason, "view_visible": visible,
           "audit_events": audit, "history_preserved": True,
           "actor": actor, "idempotency_key": case.key}
    row["output_sha256"] = sha(canonical(
        {k: v for k, v in row.items() if k != "output_sha256"}))
    return row


def decide_minimal(case: Case, seed: int) -> dict:
    d = "minimal-gate"
    act = case.action
    if act == "propose":
        if case.actor in ("worker", "operator", "governance_gate"):
            return out_row(case, d, seed, "RECORDED", None, "THRESHOLD_MET",
                           False, ["PROPOSE"], case.actor)
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "AUTHORITY_DENIED", False, [], case.actor)
    if act == "promote":
        if case.key and case.key in case.prior_keys:
            return out_row(case, d, seed, "NO_TRANSITION", None,
                           "DUPLICATE_IDEMPOTENT", case.prior == "PROMOTED",
                           [], case.actor)
        if case.actor not in GOVERNANCE_ACTORS:
            return out_row(case, d, seed, "NO_TRANSITION", None,
                           "AUTHORITY_DENIED", False, [], case.actor)
        if case.prior != "PROPOSED":
            return out_row(case, d, seed, "NO_TRANSITION", None,
                           "UNKNOWN_TRANSITION", case.prior == "PROMOTED",
                           [], case.actor)
        if not case.policy_ok():
            return out_row(case, d, seed, "REJECTED", "gate_fail",
                           "POLICY_MISMATCH", False, ["REJECT"], case.actor)
        if not case.scope_clean():
            return out_row(case, d, seed, "REJECTED", "gate_fail",
                           "SCOPE_MISMATCH", False, ["REJECT"], case.actor)
        items = case.eligible_items()
        if len(items) < 2 or case.correlated(items):
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
                    case.policy_ok():
                return out_row(case, d, seed, "PROMOTED",
                               "upheld_with_evidence", "CHALLENGE_UPHELD",
                               True, ["UPHOLD"], case.actor)
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "THRESHOLD_NOT_MET", False, [], case.actor)
    if act == "retract":
        if case.prior == "CHALLENGED":
            return out_row(case, d, seed, "RETRACTED",
                           "challenge_sustained_or_expired",
                           "CHALLENGE_SUSTAINED", False, ["RETRACT"],
                           case.actor)
        if case.prior == "PROPOSED" and case.actor == "worker":
            return out_row(case, d, seed, "RETRACTED", "withdrawn",
                           "WITHDRAWN", False, ["RETRACT"], case.actor)
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "UNKNOWN_TRANSITION", False, [], case.actor)
    if act == "revoke_source":
        if case.prior == "PROMOTED":
            return out_row(case, d, seed, "CHALLENGED", "source_revoked",
                           "SOURCE_REVOKED", False, ["CHALLENGE"],
                           case.actor)
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "UNKNOWN_TRANSITION", False, [], case.actor)
    if act == "supersede":
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
        if case.prior == "PROMOTED" and not case.open_challenge() and \
                not case.revoked:
            return out_row(case, d, seed, "VISIBLE", None, "THRESHOLD_MET",
                           True, ["READ"], case.actor)
        return out_row(case, d, seed, "HIDDEN", None, "CHALLENGE_SUSTAINED",
                       False, ["READ"], case.actor)
    if act == "derive_claim":
        derive = case.raw.get("derive") or {}
        if derive.get("own_evidence"):
            items = case.eligible_items()
            if case.policy_ok() and len(items) >= 2 and \
                    not case.correlated(items):
                return out_row(case, d, seed, "PROMOTED", "gate_pass",
                               "THRESHOLD_MET", True, ["DERIVE", "PROMOTE"],
                               case.actor)
        return out_row(case, d, seed, "NOT_PROMOTED", None,
                       "THRESHOLD_NOT_MET", False, ["DERIVE"], case.actor)
    if act == "concurrent":
        ops = case.raw.get("concurrent", []) or []
        if "challenge" in ops and case.open_challenge():
            return out_row(case, d, seed, "CHALLENGED", "challenge_accepted",
                           "CONCURRENT_RESOLVED", False, ["CHALLENGE"],
                           case.actor)
        if set(ops) == {"promote"}:
            if case.actor not in GOVERNANCE_ACTORS:
                return out_row(case, d, seed, "NO_TRANSITION", None,
                               "AUTHORITY_DENIED", False, [], case.actor)
            items = case.eligible_items()
            if case.policy_ok() and len(items) >= 2 and \
                    not case.correlated(items):
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
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "DUPLICATE_IDEMPOTENT", case.prior == "PROMOTED",
                       [], case.actor)
    if case.prior != "PROPOSED":
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "UNKNOWN_TRANSITION", case.prior == "PROMOTED",
                       [], case.actor)
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
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "DUPLICATE_IDEMPOTENT", case.prior == "PROMOTED",
                       [], "tms_engine")
    if case.prior != "PROPOSED":
        return out_row(case, d, seed, "NO_TRANSITION", None,
                       "UNKNOWN_TRANSITION", case.prior == "PROMOTED",
                       [], "tms_engine")
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
                    "rows": rows}, indent=2) + "\n", encoding="utf-8")
    (out_dir / "run-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"design={args.design} seed={args.seed} rows={len(rows)} "
          f"pid={manifest['pid']} commit={commit[:12]} "
          f"clean={manifest['clean_tree']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
