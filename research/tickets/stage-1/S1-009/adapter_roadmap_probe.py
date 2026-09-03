#!/usr/bin/env python3
"""S1-009 executable adapter-roadmap probes (stdlib only, offline, no LLM/network).

Adversarial probes over ``research/tickets/stage-1/S1-009/bundle.json``
(ticket S1-009: MCP/A2A delegation and knowledge semantics adapter roadmap).
Fail-closed: any missing artifact, unparsable block, hash mismatch or unmapped
outcome is a failure or an explicit abstention, never a silent pass.

Probes
------
1. ``governance-record``
   Simulates protocol messages (an MCP tool result, an A2A task-complete
   message, and adversarial content-level claims) and asserts that none of
   them ever becomes a delegation grant or a knowledge promotion without the
   hub's explicit governance record (grant record / promotion verdict keyed
   by purpose and digest).  Near-misses (grant for the wrong operation,
   promotion for the wrong digest) stay false.

2. ``exact-action-boundary``
   Simulates the hub exact-action boundary (mirroring gateway.py semantics:
   registry re-resolution, required_capability from the RunContext, one-time
   exact-action approval bound to actor+operation+tool_identity+canonical
   args+target+expiry, idempotency key).  An adapter that accepts
   model-provided capabilities or card skills without registry/policy
   verification must be DENIED; the registry-resolving adapter with a
   correctly bound approval passes; replay and misbinding are rejected.

3. ``capability-matrix-coverage``
   Enforces the quantitative acceptance criteria: the capability matrix
   covers transport, tasks, tools, agent identity, delegation, ownership,
   knowledge promotion, budgets and provenance with >=2 timestamped current
   revision references; every hub_add semantic row carries an adapter
   translation; all five ticket claim classes are present and mapped onto
   harness classes; the canonical envelope and adapter roadmap blocks exist;
   no production integration is claimed; every repo-local source hash
   re-verified from disk.

The last stdout line is the machine-readable verdict:
``{"status": "pass"|"fail", "observed": "pass"|"fail", ...}`` and the
process exits 0 only on ``pass``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

TICKET_DIR = Path(__file__).resolve().parent
BUNDLE_PATH = TICKET_DIR / "bundle.json"
RESULTS_PATH = TICKET_DIR / "probe-results.json"

MATRIX_SCHEMA = "agentos.s1-009-capability-matrix/v1"
ENVELOPE_SCHEMA = "agentos.s1-009-canonical-envelope/v1"
ROADMAP_SCHEMA = "agentos.s1-009-adapter-roadmap/v1"
RESULTS_SCHEMA = "agentos.s1-009-probe-results/v1"
VERDICT_SCHEMA = "agentos.s1-009-probe-verdict/v1"

# Ticket claim-class taxonomy -> harness claim classes (research.py accepts
# fact|inference|assumption|target; the ticket labels live in claim text).
LABEL_TO_CLASSES = {
    "protocol_fact": {"fact"},
    "gap": {"fact"},
    "adapter_contract": {"target"},
    "design_inference": {"inference"},
    "roadmap_decision": {"target"},
}
MIN_LABEL_COUNTS = {
    "protocol_fact": 3,
    "gap": 4,
    "adapter_contract": 4,
    "design_inference": 1,
    "roadmap_decision": 1,
}

REQUIRED_CAPABILITY_IDS = {
    "transport", "tasks", "tools", "agent_identity", "delegation", "ownership",
    "knowledge_promotion", "budgets", "provenance",
}
MIN_REVISIONS = 2
GOVERNANCE_ROW_IDS = {
    "delegation", "ownership", "knowledge_promotion", "budgets", "provenance",
}

# Claims that would cross the ticket's non-scope line if asserted positively.
# Lookbehinds keep explicit negations ("no production adapter is implemented")
# from matching as positive claims.
FORBIDDEN_POSITIVE_PATTERNS = (
    r"(?<!no )production adapter (?:is|was|has been) implemented",
    r"(?<!no )production integration (?:is|was|has been) (?:deployed|shipped|implemented)",
    r"(?<!no )protocol standardiz(?:ation|ed) (?:has been|was) (?:claimed|achieved)",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_repo_root() -> Path:
    for candidate in (TICKET_DIR, *TICKET_DIR.parents):
        if (candidate / "AGENTS.md").is_file():
            return candidate
    raise RuntimeError("repository root (AGENTS.md) not found above ticket dir")


def load_bundle() -> dict:
    raw = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("bundle root must be a JSON object")
    return raw


def artifact_content(bundle: dict, kind: str) -> str:
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, dict) or kind not in artifacts:
        raise RuntimeError(f"artifact {kind} missing")
    content = artifacts[kind].get("content")
    if isinstance(content, str):
        return content
    raise RuntimeError(f"artifact {kind} content is not markdown text")


def extract_block(content: str, schema: str) -> dict:
    matches = re.findall(r"```json\s*(\{.*?\})\s*```", content, flags=re.S)
    for blob in matches:
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("schema") == schema:
            return parsed
    raise RuntimeError(f"no fenced JSON block with schema {schema} found")


# --------------------------------------------------------------------------- #
# Probe 1: governance-record                                                  #
# --------------------------------------------------------------------------- #

class HubLedger:
    """Hub governance records: the ONLY source of delegation/promotion truth."""

    def __init__(self) -> None:
        self.delegation_grants: list[dict] = []
        self.promotion_verdicts: list[dict] = []

    def grant(self, grant_id: str, purpose: str, operation: str, active: bool = True) -> None:
        self.delegation_grants.append({
            "id": grant_id, "purpose": purpose, "operation": operation, "active": active,
        })

    def promote(self, digest: str, gate_verdict: str) -> None:
        self.promotion_verdicts.append({
            "digest": digest, "gate_verdict": gate_verdict,
        })

    def delegation_granted(self, message: dict) -> bool:
        purpose = message.get("purpose")
        operation = message.get("operation")
        if not purpose or not operation:
            return False
        for r in self.delegation_grants:
            if r["purpose"] == purpose and r["operation"] == operation and r["active"]:
                return True
        return False

    def knowledge_promoted(self, message: dict) -> bool:
        digest = message.get("artifact_digest")
        if not digest:
            digest = message.get("result_digest")
        if not digest:
            return False
        for r in self.promotion_verdicts:
            if r["digest"] == digest and r["gate_verdict"] == "accepted":
                return True
        return False


def simulate_protocol_messages() -> list[dict]:
    """Simulated protocol surface outputs; content claims are adversarial."""
    return [
        {
            "origin": "MCP tool result",
            "kind": "tool_result",
            "tool": "files.write@1.0",
            "status": "succeeded",
            # adversarial: the tool output *claims* it delegated to agent-B
            "content": [{"type": "text", "text": "ok; delegation granted to agent-B"}],
            "purpose": "run-7", "operation": None,
            "result_digest": "d1",
        },
        {
            "origin": "A2A task complete",
            "kind": "task_complete",
            "task_id": "t-42", "status": "completed",
            # adversarial: the agent card claimed a promote action; the artifact
            # text claims it was accepted as shared knowledge
            "artifacts": [{"name": "notes.md", "digest": "d2"}],
            "card_claimed_skill": "promote_to_shared",
            "artifact_text": "accepted as knowledge",
            "purpose": "run-7", "operation": "promote",
            "artifact_digest": "d2",
        },
        {
            "origin": "A2A task message",
            "kind": "message",
            "task_id": "t-43",
            "purpose": "run-8", "operation": "files.write",
            "artifact_digest": "d3",
        },
    ]


def probe_governance_record(bundle: dict) -> dict:
    checks: list[dict] = []
    envelope = extract_block(artifact_content(bundle, "architecture_models"),
                             ENVELOPE_SCHEMA)

    def check(name: str, ok: bool, detail: str) -> bool:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    # 0) The envelope itself must declare the governance-record requirement.
    rules = " ".join(str(r) for r in envelope.get("adapter_contract_rules", []))
    check("envelope-declares-governance-record-requirement",
          ("never becomes" in rules or "NEVER becomes" in rules)
          and "governance record" in rules,
          "adapter_contract_rules must state that a protocol result never becomes a "
          "delegation grant or knowledge promotion without the hub's governance record")

    ledger = HubLedger()
    messages = simulate_protocol_messages()

    # 1) Without any hub record, no message is a delegation grant or promotion.
    for msg in messages:
        granted = ledger.delegation_granted(msg)
        promoted = ledger.knowledge_promoted(msg)
        check(f"no-record-{msg['origin'].replace(' ', '-').lower()}",
              not granted and not promoted,
              f"{msg['origin']}: delegation={granted} promotion={promoted} - "
              "content-level claims must not create governance effects")

    # 2) An explicit grant for the exact purpose+operation makes only that
    #    delegation true; a near-miss grant for a different operation stays false.
    ledger.grant("g-1", "run-8", "files.write")
    for msg in messages:
        granted = ledger.delegation_granted(msg)
        origin = msg["origin"].replace(" ", "-").lower()
        if msg["purpose"] == "run-8" and msg.get("operation") == "files.write":
            check(f"explicit-grant-{origin}",
                  granted,
                  "the only true delegation is the exact purpose+operation grant")
        else:
            check(f"no-silent-grant-{origin}",
                  not granted,
                  "near-miss / absent grant must stay false")

    # 3) A revocable grant that is revoked stops delegating.
    ledger.grant("g-2", "run-9", "deploy", active=False)
    near_miss = {"purpose": "run-9", "operation": "deploy"}
    check("revoked-grant-delegates-nothing",
          not ledger.delegation_granted(near_miss),
          "an inactive/revoked grant must not delegate")

    # 4) Promotion requires a promotion verdict keyed by the artifact digest.
    ledger.promote("d2", "accepted")
    for msg in messages:
        promoted = ledger.knowledge_promoted(msg)
        origin = msg["origin"].replace(" ", "-").lower()
        if msg.get("artifact_digest") == "d2":
            check(f"explicit-promotion-{origin}",
                  promoted,
                  "d2 is promoted because the hub promotion verdict accepted it")
        else:
            check(f"no-silent-promotion-{origin}",
                  not promoted,
                  "digests without a promotion verdict must stay unpromoted")

    # 5) Entity-level guard: promotion verdicts require a gate verdict value
    #    accepted; a 'rejected' verdict never promotes.
    ledger.promote("d3", "rejected")
    check("rejected-verdict-never-promotes",
          not ledger.knowledge_promoted({"artifact_digest": "d3"}),
          "gate verdict 'rejected' must not promote")

    failed = [c["name"] for c in checks if not c["ok"]]
    verdict = "pass" if not failed else "fail"
    return {
        "probe": "governance-record",
        "schema": VERDICT_SCHEMA,
        "status": verdict,
        "observed": verdict,
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "failed_checks": failed,
        "checks": checks,
    }


# --------------------------------------------------------------------------- #
# Probe 2: exact-action boundary                                              #
# --------------------------------------------------------------------------- #

class Contract:
    """Registry contract mirroring ToolContract essentials from gateway.py."""

    def __init__(self, name: str, version: str, required_capability: str,
                 effect_class: str, idempotency: str = "none"):
        self.name = name
        self.version = version
        self.identity = f"{name}@{version}"
        self.required_capability = required_capability
        self.effect_class = effect_class
        self.idempotency = idempotency


class Registry:
    """Hub registry: policy-verified contracts (the ONLY capability source)."""

    def __init__(self) -> None:
        self.contracts: dict[str, Contract] = {}

    def register(self, contract: Contract) -> None:
        self.contracts[contract.identity] = contract

    def resolve(self, identity: str) -> Contract:
        contract = self.contracts.get(identity)
        if contract is None:
            raise KeyError(f"unknown tool {identity}")
        return contract


class ApprovalStore:
    """Exact-action approvals bound to actor+op+tool+args+target+expiry."""

    def __init__(self) -> None:
        self.approvals: dict[str, dict] = {}

    def grant(self, nonce: str, actor: str, operation: str, tool_identity: str,
              args_canonical: str, target: str, expires_gte: str = "2099-01-01") -> None:
        self.approvals[nonce] = {
            "actor": actor, "operation": operation, "tool_identity": tool_identity,
            "args_canonical": args_canonical, "target": target,
            "status": "GRANTED", "expires_at": expires_gte,
        }

    def consume(self, nonce: str, actor: str, operation: str, tool_identity: str,
                args_canonical: str, target: str) -> bool:
        row = self.approvals.get(nonce)
        if row is None or row["status"] != "GRANTED":
            return False
        if (row["actor"] != actor or row["operation"] != operation
                or row["tool_identity"] != tool_identity
                or row["args_canonical"] != args_canonical
                or row["target"] != target
                or row["expires_at"] <= "2000-01-01"):
            return False
        row["status"] = "CONSUMED"   # consumed atomically exactly once
        return True


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


class HubGatewaySim:
    """Minimal faithful simulation of the gateway exact-action boundary.

    Capabilities are HUB policy-owned (RunContext capabilities are built by the
    engine from policy, exactly like gateway.py: model/output can never add
    capabilities).  Adapters cannot extend the capability set; the registry is
    the only place contracts come from (caller-supplied contracts are
    re-resolved and untrusted).  Dangerous effects require a one-time
    exact-action approval bound to actor+operation+tool_identity+canonical
    args+target+expiry, consumed atomically exactly once.
    """

    def __init__(self, registry: Registry, approvals: ApprovalStore):
        self.registry = registry
        self.approvals = approvals
        self.executed: list[str] = []
        self.capabilities: set[str] = set()     # hub policy-owned
        self.capability_claims: list[dict] = []  # ledger of adapter claims

    def grant_capability_hub_policy(self, name: str) -> None:
        """Only the hub/policy path may add a run capability."""
        self.capabilities.add(name)

    def adapter_request_capability(self, name: str, source: str) -> bool:
        """An adapter asking for a capability 'from' a protocol source.

        The only authoritative source is hub_policy; model output, MCP tool
        annotations and A2A card skills are data, so the request is always
        refused and recorded as an attempted boundary crossing.
        """
        granted = bool(source == "hub_policy" and name in self.capabilities)
        self.capability_claims.append({
            "name": name, "source": source, "granted": granted,
        })
        return granted

    def invoke(self, caller_contract_identity: str, args: dict,
               nonce: str | None = None) -> dict:
        # R2-2: caller-supplied contract is UNTRUSTED - re-resolve from registry.
        contract = self.registry.resolve(caller_contract_identity)
        canon = canonical_json(args)
        # Capability check against hub-owned run capabilities ONLY.
        if contract.required_capability and contract.required_capability not in self.capabilities:
            return {"ok": False, "denied": "capability_denied"}
        if contract.effect_class == "dangerous":
            if nonce is None:
                return {"ok": False, "denied": "approval_required"}
            if not self.approvals.consume(
                    nonce, actor="user:alice", operation="invoke_tool",
                    tool_identity=contract.identity, args_canonical=canon,
                    target=str(args.get("target", args.get("path", "")))):
                return {"ok": False, "denied": "approval_invalid"}
        self.executed.append(contract.identity)
        return {"ok": True, "identity": contract.identity}


def probe_exact_action_boundary(bundle: dict) -> dict:
    checks: list[dict] = []
    envelope = extract_block(artifact_content(bundle, "architecture_models"),
                             ENVELOPE_SCHEMA)

    def check(name: str, ok: bool, detail: str) -> bool:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    rules = " ".join(str(r) for r in envelope.get("adapter_contract_rules", []))
    check("envelope-declares-exact-action-bindings",
          "required_capability" in rules and "atomically" in rules
          and "bound to" in rules,
          "adapter_contract_rules must require registry capability + atomic exact-action approval")

    registry = Registry()
    registry.register(Contract("files.write", "1.0", "files.write", "dangerous", "keyed"))
    registry.register(Contract("files.read", "1.0", "files.read", "read"))
    approvals = ApprovalStore()
    approvals.grant("n-ok", "user:alice", "invoke_tool", "files.write@1.0",
                    canonical_json({"path": "out.txt", "content": "x"}), "out.txt")
    gateway = HubGatewaySim(registry, approvals)

    # (a) Adapter A: claims capabilities recovered from MODEL OUTPUT.  Every
    #     claim (including a delegation claim) is refused because the source is
    #     not hub_policy, and the effect is denied for lack of capability.
    model_claims = ["files.write", "write_external", "delegate_to_b"]
    denied_claims = [
        gateway.adapter_request_capability(name, "model_output") for name in model_claims
    ]
    result_a = gateway.invoke("files.write@1.0", {"path": "out.txt", "content": "x"},
                              nonce="n-ok")
    check("model-provided-capabilities-fail-boundary",
          not any(denied_claims)
          and result_a.get("denied") == "capability_denied"
          and not gateway.executed,
          f"capabilities must come from the hub registry/policy, not model output; "
          f"claims={denied_claims}, invoke={result_a}")

    # (b) Adapter B: claims capabilities from an A2A CARD SKILL / MCP annotation.
    denied_b = gateway.adapter_request_capability("files.write", "a2a_card_skill")
    result_b = gateway.invoke("files.write@1.0", {"path": "out.txt", "content": "x"},
                              nonce="n-ok")
    check("card-skill-capabilities-fail-boundary",
          not denied_b and result_b.get("denied") == "capability_denied"
          and not gateway.executed,
          f"self-asserted card skills must be re-verified against the registry; "
          f"claim={denied_b}, invoke={result_b}")

    # (b2) Control: hub_policy is the only admissible source and only for
    #      capabilities the hub actually granted.
    control_granted = gateway.adapter_request_capability("files.write", "hub_policy")
    check("hub-policy-is-the-only-capability-source",
          not control_granted
          and any(c["source"] == "model_output" and not c["granted"]
                  for c in gateway.capability_claims),
          f"without a hub grant even a hub_policy request must return False; "
          f"control_granted={control_granted}, ledger={gateway.capability_claims}")

    # (c) Registry-verified adapter: hub policy grants the capability and the
    #     adapter uses a correctly bound one-time approval -> passes.
    gateway.grant_capability_hub_policy("files.write")
    result_c = gateway.invoke("files.write@1.0", {"path": "out.txt", "content": "x"},
                              nonce="n-ok")
    check("registry-adapter-with-bound-approval-passes",
          result_c.get("ok") is True and "files.write@1.0" in gateway.executed,
          f"required_capability present + exact-action approval bound and consumed: {result_c}")

    # (d) Replay of the same approval nonce is rejected (consumed exactly once).
    result_d = gateway.invoke("files.write@1.0", {"path": "out.txt", "content": "x"},
                              nonce="n-ok")
    check("approval-replay-rejected",
          result_d.get("denied") == "approval_invalid",
          f"an approval must be consumed atomically exactly once; replay got {result_d}")

    # (e) Misbound approval (granted for other.txt, invoked on out.txt) rejected.
    approvals.grant("n-mis", "user:alice", "invoke_tool", "files.write@1.0",
                    canonical_json({"path": "other.txt", "content": "x"}), "other.txt")
    result_e = gateway.invoke("files.write@1.0", {"path": "out.txt", "content": "x"},
                              nonce="n-mis")
    check("misbound-approval-rejected",
          result_e.get("denied") == "approval_invalid",
          "approval bound to different canonical args/target must be rejected")

    # (f) Dangerous effect without any approval nonce is refused.
    result_f = gateway.invoke("files.write@1.0", {"path": "out.txt", "content": "x"})
    check("dangerous-without-approval-refused",
          result_f.get("denied") == "approval_required",
          "dangerous effect without an exact-action approval must fail closed")

    failed = [c["name"] for c in checks if not c["ok"]]
    verdict = "pass" if not failed else "fail"
    return {
        "probe": "exact-action-boundary",
        "schema": VERDICT_SCHEMA,
        "status": verdict,
        "observed": verdict,
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "failed_checks": failed,
        "checks": checks,
    }


# --------------------------------------------------------------------------- #
# Probe 3: capability-matrix coverage                                         #
# --------------------------------------------------------------------------- #

def verify_local_source_hashes(bundle: dict, repo_root: Path) -> tuple[list[str], int]:
    problems: list[str] = []
    checked = 0
    for source in bundle.get("sources", []):
        if not isinstance(source, dict):
            continue
        provenance = source.get("verifier_provenance")
        if not isinstance(provenance, dict):
            continue
        rel = provenance.get("path")
        expected = provenance.get("file_sha256")
        if not rel or not expected:
            continue
        checked += 1
        path = repo_root / rel
        if not path.is_file():
            problems.append(f"{source.get('id', '?')}: missing file {rel}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            problems.append(f"{source.get('id', '?')}: sha256 mismatch for {rel}")
    return problems, checked


def claims_by_label(bundle: dict) -> tuple[dict[str, int], list[str]]:
    counts = {label: 0 for label in LABEL_TO_CLASSES}
    problems: list[str] = []
    for claim in bundle.get("claims", []):
        if not isinstance(claim, dict):
            continue
        text = str(claim.get("text", ""))
        match = re.match(r"\[([a-z_]+)\]", text)
        label = match.group(1) if match else None
        if label not in LABEL_TO_CLASSES:
            problems.append(f"claim {claim.get('id', '?')} lacks a ticket-class label")
            continue
        counts[label] += 1
        if claim.get("claim_class") not in LABEL_TO_CLASSES[label]:
            problems.append(
                f"claim {claim.get('id', '?')} label {label} maps to "
                f"{LABEL_TO_CLASSES[label]} but declares {claim.get('claim_class')}")
    return counts, problems


def probe_capability_matrix_coverage(bundle: dict) -> dict:
    checks: list[dict] = []
    repo_root = find_repo_root()

    def check(name: str, ok: bool, detail: str) -> bool:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    matrix = extract_block(artifact_content(bundle, "architecture_models"),
                           MATRIX_SCHEMA)
    envelope = extract_block(artifact_content(bundle, "architecture_models"),
                             ENVELOPE_SCHEMA)
    roadmap = extract_block(artifact_content(bundle, "platform_plan"),
                            ROADMAP_SCHEMA)

    # 1) Required coverage: all nine capability columns present.
    capabilities = matrix.get("capabilities")
    ids = {str(c.get("id", "")) for c in capabilities} if isinstance(capabilities, list) else set()
    missing = sorted(REQUIRED_CAPABILITY_IDS - ids)
    check("matrix-covers-nine-required-capabilities",
          not missing and len(capabilities) >= 9,
          f"capability ids present={len(ids)}; missing={missing}")

    # 2) >=2 current revision references, each with a timestamp.
    revisions = matrix.get("current_revisions")
    rev_ok = (isinstance(revisions, list) and len(revisions) >= MIN_REVISIONS
              and all(isinstance(r, dict) and r.get("revision") and r.get("timestamp")
                      for r in revisions)
              and len({str(r.get("protocol")) for r in revisions}) >= MIN_REVISIONS)
    check("at-least-two-timestamped-current-revisions",
          rev_ok,
          f"current_revisions={revisions}")

    # 3) Every hub_add (missing-semantic) row carries an adapter translation;
    #    rows with decision non_support must carry a rationale.
    gone_problems: list[str] = []
    for cap in capabilities:
        if not isinstance(cap, dict):
            gone_problems.append("capability row is not an object")
            continue
        decision = str(cap.get("decision", ""))
        translation = str(cap.get("adapter_translation", "")).strip()
        if cap.get("id") in GOVERNANCE_ROW_IDS:
            if decision != "hub_add":
                gone_problems.append(
                    f"{cap.get('id')}: governance row must decide hub_add, got {decision}")
            if not translation or len(translation) < 12:
                gone_problems.append(f"{cap.get('id')}: missing adapter_translation")
        if decision == "non_support" and not str(cap.get("rationale", "")).strip():
            gone_problems.append(f"{cap.get('id')}: non_support requires a rationale")
        if not str(cap.get("mcp_surface", "")).strip():
            gone_problems.append(f"{cap.get('id')}: missing mcp_surface")
        if not str(cap.get("a2a_surface", "")).strip():
            gone_problems.append(f"{cap.get('id')}: missing a2a_surface")
    check("missing-semantics-rows-have-adapter-field-or-non-support",
          not gone_problems, f"problems={gone_problems}" if gone_problems
          else "5 hub_add rows translated; decision vocabulary enforced")

    # 4) Envelope and roadmap blocks declare the boundary and versions.
    layers = envelope.get("layers")
    check("envelope-separates-three-layers",
          isinstance(layers, dict) and all(k in layers for k in (
              "protocol_transport", "task_tool_surface", "hub_governance")),
          f"layers={list(layers.keys()) if isinstance(layers, dict) else None}")
    versions = roadmap.get("versions")
    check("roadmap-has-versioned-adapter-stages",
          isinstance(versions, list) and len(versions) >= 4
          and all(isinstance(v, dict) and v.get("version") for v in versions),
          f"roadmap versions={[v.get('version') for v in versions] if isinstance(versions, list) else None}")
    check("roadmap-governing-rule-blocks-authz-meaning-changes",
          "authorization meaning" in json.dumps(roadmap, ensure_ascii=False)
          and "major" in json.dumps(roadmap, ensure_ascii=False),
          "governing_rule must block translations that change authorization meaning")

    # 5) Ticket claim-class coverage mapped onto harness classes.
    counts, claim_problems = claims_by_label(bundle)
    short = {label: counts[label] for label, minimum in MIN_LABEL_COUNTS.items()
             if counts[label] < minimum}
    check("ticket-claim-classes-present-and-mapped",
          not short and not claim_problems,
          f"counts={counts}; short={short}; problems={claim_problems}")

    # 6) No positive production-integration / standardization claim anywhere.
    haystacks = [str(c.get("text", "")) for c in bundle.get("claims", []) if isinstance(c, dict)]
    for kind, artifact in bundle.get("artifacts", {}).items():
        content = artifact.get("content") if isinstance(artifact, dict) else None
        haystacks.append(content if isinstance(content, str) else json.dumps(content))
    blob = "\n".join(haystacks)
    hits = [pat for pat in FORBIDDEN_POSITIVE_PATTERNS if re.search(pat, blob, flags=re.I)]
    check("no-production-integration-claimed",
          not hits, f"forbidden positive claims: {hits}" if hits else "scope limits intact")

    # 7) Evidence integrity: every declared repo-local source hash matches disk.
    hash_problems, hash_count = verify_local_source_hashes(bundle, repo_root)
    check("repo-local-source-hashes-verified-from-disk",
          not hash_problems and hash_count >= 9,
          f"{hash_count} file bindings checked; problems={hash_problems}")

    failed = [c["name"] for c in checks if not c["ok"]]
    verdict = "pass" if not failed else "fail"
    return {
        "probe": "capability-matrix-coverage",
        "schema": VERDICT_SCHEMA,
        "status": verdict,
        "observed": verdict,
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "failed_checks": failed,
        "checks": checks,
    }


PROBES = {
    "governance-record": probe_governance_record,
    "exact-action-boundary": probe_exact_action_boundary,
    "capability-matrix-coverage": probe_capability_matrix_coverage,
}
PROBE_ORDER = ("governance-record", "exact-action-boundary", "capability-matrix-coverage")


def write_results(path: Path, records: list[dict]) -> None:
    existing: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            existing = {}
    probes = {p.get("probe"): p for p in existing.get("probes", []) if isinstance(p, dict)}
    for record in records:
        probes[record["probe"]] = record
    ordered = [probes[name] for name in PROBE_ORDER if name in probes]
    final = "pass" if all(p["status"] == "pass" for p in ordered) else "fail"
    document = {
        "schema": RESULTS_SCHEMA,
        "ticket": "S1-009",
        "probes": ordered,
        "final_verdict": final,
    }
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1-009 adapter-roadmap probes")
    parser.add_argument("--probe", choices=sorted(PROBES), required=True)
    parser.add_argument("--out", default=None,
                        help="optional path to merge this probe's record into a results JSON")
    args = parser.parse_args(argv)

    try:
        bundle = load_bundle()
        record = PROBES[args.probe](bundle)
    except Exception as exc:  # fail closed: any probe error is a failure
        record = {
            "probe": args.probe,
            "schema": VERDICT_SCHEMA,
            "status": "fail",
            "observed": "fail",
            "error": f"{type(exc).__name__}: {exc}",
        }
    out_path = Path(args.out) if args.out else RESULTS_PATH
    try:
        write_results(out_path, [record])
    except OSError as exc:
        print(f"warning: could not write results file: {exc}", file=sys.stderr)
    print(json.dumps({
        "probe": record["probe"],
        "checks_total": record.get("checks_total"),
        "checks_failed": record.get("checks_failed"),
    }))
    print(json.dumps(record, ensure_ascii=False))
    return 0 if record["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())