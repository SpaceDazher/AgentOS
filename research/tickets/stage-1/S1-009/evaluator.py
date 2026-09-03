#!/usr/bin/env python3
"""S1-009 deterministic evaluator.

Translates simulated MCP 2026-07-28 and A2A 1.0.0 protocol messages into the
AgentOS canonical hub envelope and checks each translation against a frozen
oracle (the corpus). Expected outcomes are ONLY taken from host-owned frozen
fixtures; the evaluator never self-derives a verdict from its own output.

stdlib-only. No network. No LLM. Deterministic.

Usage:
    python evaluator.py --corpus cases.json --out results/run-a \
        --executor "verifier-A" --nonce "run-a-nonce"
    python evaluator.py --corpus cases.json --out results/run-b \
        --executor "verifier-B" --nonce "run-b-nonce"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


# evaluator.py -> S1-009 -> stage-1 -> tickets -> research -> repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
_REQUIRED_HASH_KEYS = (
    "evaluator_sha256",
    "adapter_contract_sha256",
    "corpus_sha256",
    "envelope_schema_sha256",
    "rubric_sha256",
)

# ---------------------------------------------------------------------------
# Hashes
# ---------------------------------------------------------------------------

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(obj: Any) -> str:
    """Deterministic JSON serialization (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _git_value(*args: str) -> str:
    """Read a required git value, failing closed on any git/IO error."""
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True,
        check=False, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git provenance command failed ({' '.join(args)}): "
            f"{result.stderr.strip() or result.returncode}"
        )
    value = result.stdout.strip()
    if not value:
        raise RuntimeError(f"git provenance command returned empty value: {' '.join(args)}")
    return value


def _git_provenance(manifest_path: Path | None = None) -> dict[str, Any]:
    """Capture clean-tree and frozen-input provenance before writing output."""
    commit_sha = _git_value("rev-parse", "HEAD")
    tree_sha = _git_value("rev-parse", "HEAD^{tree}")
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=10,
    )
    if status.returncode != 0:
        raise RuntimeError(
            f"git status failed: {status.stderr.strip() or status.returncode}"
        )
    dirty_files = [line for line in status.stdout.splitlines() if line.strip()]
    manifest_sha = ""
    if manifest_path is not None:
        manifest_path = Path(manifest_path)
        if not manifest_path.is_file():
            raise RuntimeError(f"frozen input manifest is missing: {manifest_path}")
        manifest_sha = sha256_file(manifest_path)
    return {
        "commit_sha": commit_sha,
        "tree_sha": tree_sha,
        "dirty": bool(dirty_files),
        "clean": not dirty_files,
        "dirty_files": dirty_files[:50],
        "input_manifest_sha256": manifest_sha,
        "evaluator_pid": os.getpid(),
        "evaluator_ppid": os.getppid(),
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
    }


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------

def _empty_envelope(protocol: str, protocol_version: str,
                    direction: str) -> dict:
    """Return the canonical envelope shape with all authorization fields
    in their safe default (absent/false) state."""
    return {
        "envelope": {
            "envelope_version": "1.0",
            "adapter_version": "1.0",
            "protocol": protocol,
            "protocol_version": protocol_version,
            "direction": direction,
        },
        "operation": {
            "protocol": protocol,
            "operation_id": "",
            "correlation_id": "",
            "causation_id": "",
            "method": "",
        },
        "scopes": {
            "tenant_id": "",
            "workspace_id": "",
            "goal_id": "",
            "task_id": "",
            "run_id": "",
        },
        "identity": {
            "authenticated_actor": "",
            "asserted_remote_actor": None,
            "asserted_remote_actor_verified": False,
            "owner_principal": "",
            "delegator_delegatee_chain": [],
        },
        "capability": {
            "tool_contract_id": None,
            "tool_contract_version": None,
            "arguments_digest": "",
            "protocol_native_tool_name": "",
        },
        "effect": {
            "effect_class": "none",
            "idempotency_key": "",
            "receipt_state": "none",
            "reconciliation_state": "unknown_outcome",
            "cancellation_does_not_cancel_reconciliation": True,
        },
        "authorization": {
            "grant_present": False,
            "grant_id": None,
            "approval_id": None,
            "expiry": None,
            "consumed": False,
            "fencing_token": "",
            "revocation_epoch": "",
        },
        "budget": {
            "currency": "",
            "unit": "",
            "parent_total": 0,
            "reserved": 0,
            "consumed": 0,
            "remaining": 0,
            "child_reservation_ids": [],
        },
        "artifacts": {
            "input_artifacts": [],
            "output_artifacts": [],
            "protocol_payload_digest": "",
        },
        "knowledge": {
            "knowledge_id": None,
            "status": "proposal",
            "proposal_source": None,
            "promotion_event_id": None,
        },
        "policy": {
            "policy_version": "",
            "decision_reason": "",
            "audit_reference": "",
            "decision_epoch": "",
        },
        "extensions": {
            "accepted": [],
            "rejected": [],
            "quarantined": [],
        },
    }


def _payload_digest(obj: Any) -> str:
    """SHA-256 of the non-secret protocol payload (canonical JSON)."""
    return sha256_text(canonical_json(obj))


# ---------------------------------------------------------------------------
# MCP translation (adapter rules MCP-IN-01 through MCP-IN-07)
# ---------------------------------------------------------------------------

# Supported protocol versions — anything else is QUARANTINE/REJECT
_MCP_SUPPORTED_VERSIONS = {"2026-07-28"}
_A2A_SUPPORTED_VERSIONS = {"1.0.0"}


def _scan_for_auth_claims(text: str) -> list[str]:
    """Detect protocol payload text claiming delegation, approval, budget,
    ownership, or knowledge promotion. Returns list of detected claims.
    These are untrusted and cannot alter authorization semantics."""
    lowered = text.lower()
    claims: list[str] = []
    auth_markers = [
        ("delegation", "delegat"),
        ("approval", "approv"),
        ("grant", "grant"),
        ("ownership", "ownership"),
        ("budget", "budget"),
        ("promotion", "promot"),
        ("verified", "verifi"),
        ("reviewed", "review"),
        ("authority", "authority"),
        ("authorization", "authoriz"),
    ]
    for label, marker in auth_markers:
        if marker in lowered:
            claims.append(label)
    return claims


def translate_mcp(input_msg: dict, hub_ctx: dict) -> dict:
    """Translate one MCP message into a canonical envelope + decision.

    Returns a dict with: decision, envelope, rules_triggered, reasons,
    payload_digest.
    """
    env = _empty_envelope("MCP", hub_ctx.get("protocol_version", "2026-07-28"),
                          "inbound")
    method = input_msg.get("method", "")
    params = input_msg.get("params", {})
    msg_id = input_msg.get("id", "")
    result_data = input_msg.get("result", None)

    rules: list[str] = []
    reasons: list[str] = []
    decision = "ACCEPT"

    # --- MCP-IN-01: Initialize / version negotiation ---
    if method == "initialize" or method == "initialized":
        rules.append("MCP-IN-01")
        pv = params.get("protocolVersion", "") if isinstance(params, dict) else ""
        if pv not in _MCP_SUPPORTED_VERSIONS:
            # Unknown or downgraded version -> quarantine
            decision = "QUARANTINE"
            reasons.append(f"unknown_protocol_version:{pv}")
            env["extensions"]["quarantined"].append({
                "name": "protocol_version",
                "reason": "unsupported_version",
                "provenance": f"pv={pv}",
            })
            env["policy"]["decision_reason"] = "unsupported_protocol_version"
            return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

        # Accept known version. Check for unknown capabilities -> quarantine
        caps = params.get("capabilities", {}) if isinstance(params, dict) else {}
        known_caps = {"tools", "resources", "prompts", "tasks", "completion",
                      "prompts_list", "resources_list", "tools_list"}
        if isinstance(caps, dict):
            for cap_name in caps:
                if cap_name not in known_caps:
                    decision = "QUARANTINE"
                    reasons.append(f"unknown_capability:{cap_name}")
                    env["extensions"]["quarantined"].append({
                        "name": cap_name,
                        "reason": "unknown_extension",
                        "provenance": "InitializeResult.capabilities",
                    })
        env["operation"]["method"] = method
        env["operation"]["operation_id"] = f"init-{msg_id}"
        rules.append("MCP-IN-01")
        if decision != "QUARANTINE":
            env["policy"]["decision_reason"] = "initialized"
        else:
            env["policy"]["decision_reason"] = "unknown_extension_quarantined"
        return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

    # --- MCP-IN-02: tools/list ---
    if method == "tools/list":
        rules.append("MCP-IN-02")
        # Tools list is untrusted claim; resolve against registry
        registry = hub_ctx.get("registry", {})
        # No effect from listing; this is a capability inquiry
        env["operation"]["method"] = method
        env["operation"]["operation_id"] = f"tools-list-{msg_id}"
        env["policy"]["decision_reason"] = "capability_inquiry_untrusted"
        return _finalize("ACCEPT", env, rules, reasons, _payload_digest(input_msg))

    # --- MCP-IN-03: tools/call ---
    if method == "tools/call":
        rules.append("MCP-IN-03")
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}

        env["operation"]["method"] = method
        env["operation"]["operation_id"] = f"tools-call-{msg_id}"
        env["capability"]["protocol_native_tool_name"] = tool_name
        env["artifacts"]["protocol_payload_digest"] = _payload_digest(params)

        # 0. Scan result data for auth claims FIRST (MCP-IN-06, Probe A).
        # A protocol task/result declaring delegation/approval/budget/knowledge
        # promotion must be denied regardless of registry or grant state.
        # rule_1: protocol payload is never authority for grant.
        if result_data is not None:
            text_blob = json.dumps(result_data)
            auth_claims = _scan_for_auth_claims(text_blob)
            if auth_claims:
                decision = "DENY"
                reasons.append("protocol_task_is_not_a_grant")
                env["authorization"]["grant_present"] = False
                env["policy"]["decision_reason"] = "protocol_task_is_not_a_grant"
                env["knowledge"]["status"] = "proposal"
                return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

        # Scan arguments for auth claims (MCP-IN-03 hard rule: authorization fields
        # cannot be injected via protocol payload)
        if arguments:
            arg_blob = canonical_json(arguments)
            arg_claims = _scan_for_auth_claims(arg_blob)
            if arg_claims:
                decision = "DENY"
                reasons.append("protocol_payload_claims_authorization")
                env["authorization"]["grant_present"] = False
                env["policy"]["decision_reason"] = "protocol_payload_claims_authorization"
                return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

        # 1. Registry resolution (MCP-IN-02 / SM5)
        registry = hub_ctx.get("registry", {})
        if tool_name not in registry:
            decision = "DENY"
            reasons.append("unregistered_tool")
            env["policy"]["decision_reason"] = "capability_not_in_registry"
            return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

        contract = registry[tool_name]
        env["capability"]["tool_contract_id"] = contract.get("tool_contract_id")
        env["capability"]["tool_contract_version"] = contract.get("tool_contract_version")
        env["effect"]["effect_class"] = contract.get("effect_class", "read")
        env["capability"]["arguments_digest"] = sha256_text(canonical_json(arguments))

        # 2. Grant check — from hub ledger, NOT from protocol (rule_1)
        grants = hub_ctx.get("grants", {})
        grant_present = grants.get("grant_present", False)
        env["authorization"]["grant_present"] = grant_present

        if not grant_present:
            decision = "DENY"
            reasons.append("missing_grant_needs_governance")
            env["policy"]["decision_reason"] = "needs_governance"
            return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

        # 3. Schema validation
        schema = contract.get("input_schema", {})
        if not _matches_schema(arguments, schema):
            decision = "DENY"
            reasons.append("schema_mismatch")
            env["policy"]["decision_reason"] = "argument_schema_mismatch"
            return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

        # 5. Set hub-derived fields
        env["identity"]["authenticated_actor"] = hub_ctx.get("authenticated_actor", "")
        env["identity"]["owner_principal"] = hub_ctx.get("authenticated_actor", "")
        env["authorization"]["grant_id"] = grants.get("grant_id")
        env["authorization"]["fencing_token"] = hub_ctx.get("fencing_token", "")
        env["authorization"]["revocation_epoch"] = hub_ctx.get("revocation_epoch", "")
        env["effect"]["idempotency_key"] = f"hub-idem-{sha256_text(msg_id)[:16]}"

        # Budget check (MCP-IN-03 + SM8)
        budget = hub_ctx.get("budget", {})
        env["budget"] = dict(budget)

        # Knowledge stays proposal (SM11)
        env["knowledge"]["status"] = "proposal"

        env["policy"]["decision_reason"] = "accepted_by_registry_and_grant"
        env["policy"]["policy_version"] = hub_ctx.get("policy_version", "")
        return _finalize("ACCEPT", env, rules, reasons, _payload_digest(input_msg))

    # --- MCP-IN-04: resources/read ---
    if method == "resources/read":
        rules.append("MCP-IN-04")
        uri = params.get("uri", "")
        registry = hub_ctx.get("resource_registry", {})
        if uri not in registry:
            decision = "DENY"
            reasons.append("unregistered_resource_uri")
            env["policy"]["decision_reason"] = "resource_not_in_registry"
            return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))
        env["capability"]["tool_contract_id"] = registry[uri].get("resource_id")
        env["capability"]["tool_contract_version"] = registry[uri].get("version")
        env["effect"]["effect_class"] = "read"
        env["identity"]["authenticated_actor"] = hub_ctx.get("authenticated_actor", "")
        env["identity"]["owner_principal"] = hub_ctx.get("authenticated_actor", "")
        env["authorization"]["grant_present"] = hub_ctx.get("grants", {}).get("grant_present", False)
        env["authorization"]["fencing_token"] = hub_ctx.get("fencing_token", "")
        env["authorization"]["revocation_epoch"] = hub_ctx.get("revocation_epoch", "")
        env["effect"]["idempotency_key"] = f"hub-idem-{sha256_text(msg_id)[:16]}"
        env["knowledge"]["status"] = "proposal"
        env["policy"]["policy_version"] = hub_ctx.get("policy_version", "")
        env["policy"]["decision_reason"] = "resource_read_accepted"
        return _finalize("ACCEPT", env, rules, reasons, _payload_digest(input_msg))

    # --- MCP-IN-05: prompts/get ---
    if method == "prompts/get":
        rules.append("MCP-IN-05")
        prompt_name = params.get("name", "")
        registry = hub_ctx.get("prompt_registry", {})
        if prompt_name not in registry:
            decision = "DENY"
            reasons.append("unregistered_prompt")
            return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

        # Scan result for auth claims
        if result_data is not None:
            text_blob = json.dumps(result_data)
            auth_claims = _scan_for_auth_claims(text_blob)
            if auth_claims:
                decision = "DENY"
                reasons.append("protocol_task_is_not_a_grant")
                env["authorization"]["grant_present"] = False
                env["policy"]["decision_reason"] = "protocol_task_is_not_a_grant"
                return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

        env["capability"]["tool_contract_id"] = registry[prompt_name].get("prompt_id")
        env["effect"]["effect_class"] = "read"
        env["knowledge"]["status"] = "proposal"
        env["policy"]["decision_reason"] = "prompt_get_accepted"
        return _finalize("ACCEPT", env, rules, reasons, _payload_digest(input_msg))

    # --- Default: unknown method ---
    decision = "DENY"
    reasons.append("unhandled_method")
    env["policy"]["decision_reason"] = "method_not_mapped"
    return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))


# ---------------------------------------------------------------------------
# A2A translation (adapter rules A2A-IN-01 through A2A-IN-07)
# ---------------------------------------------------------------------------

def translate_a2a(input_msg: dict, hub_ctx: dict) -> dict:
    """Translate one A2A message into a canonical envelope + decision."""
    env = _empty_envelope("A2A", hub_ctx.get("protocol_version", "1.0.0"), "inbound")
    method = input_msg.get("method", "")
    params = input_msg.get("params", {})
    msg_id = input_msg.get("id", "")

    rules: list[str] = []
    reasons: list[str] = []
    decision = "ACCEPT"

    # --- A2A-IN-01: getAgentCard ---
    if method == "getAgentCard":
        rules.append("A2A-IN-01")
        card = params.get("agentCard", {}) if isinstance(params, dict) else {}
        skills = card.get("skills", []) if isinstance(card, dict) else []
        registry = hub_ctx.get("skill_registry", {})
        # Skills are untrusted claims; resolve against registry
        for skill in skills:
            skill_name = skill.get("id", "") if isinstance(skill, dict) else str(skill)
            if skill_name not in registry:
                decision = "DENY"
                reasons.append(f"unregistered_skill:{skill_name}")
                env["extensions"]["quarantined"].append({
                    "name": skill_name,
                    "reason": "capability_not_in_registry",
                    "provenance": "AgentCard.skills",
                })
                env["policy"]["decision_reason"] = "capability_not_in_registry"
                return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))
        env["operation"]["method"] = method
        env["policy"]["decision_reason"] = "agent_card_resolved"
        return _finalize("ACCEPT", env, rules, reasons, _payload_digest(input_msg))

    # --- A2A-IN-02: sendTask ---
    if method == "sendTask":
        rules.append("A2A-IN-02")
        task = params.get("task", {}) if isinstance(params, dict) else {}
        task_id = task.get("id", "")
        message = task.get("message", {}) if isinstance(task, dict) else {}

        env["operation"]["method"] = method
        env["operation"]["operation_id"] = f"send-task-{msg_id}"
        env["operation"]["correlation_id"] = msg_id
        env["scopes"]["task_id"] = task_id  # protocol id, secondary reference

        # 0. Scan ENTIRE task payload for auth claims (A2A-IN-07, Probe A/E).
        # Protocol task/result/message/artifact claiming delegation, approval,
        # budget, ownership, or knowledge promotion must be denied regardless
        # of registry or grant state. rule_1: protocol payload never authority.
        full_blob = canonical_json(params)
        auth_claims = _scan_for_auth_claims(full_blob)
        if auth_claims:
            decision = "DENY"
            reasons.append("protocol_task_is_not_a_grant")
            env["authorization"]["grant_present"] = False
            env["knowledge"]["status"] = "proposal"
            env["knowledge"]["promotion_event_id"] = None
            env["policy"]["decision_reason"] = "protocol_task_is_not_a_grant"
            return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

        # 1. Registry resolution of skill (from message data, A2A-IN-01)
        registry = hub_ctx.get("skill_registry", {})
        skill_name = message.get("skill_id", "") if isinstance(message, dict) else ""
        if skill_name and skill_name not in registry:
            decision = "DENY"
            reasons.append("unregistered_skill")
            env["policy"]["decision_reason"] = "capability_not_in_registry"
            return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

        # 2. Grant check (A2A-IN-02, rule_1)
        grants = hub_ctx.get("grants", {})
        grant_present = grants.get("grant_present", False)
        env["authorization"]["grant_present"] = grant_present

        if not grant_present:
            decision = "DENY"
            reasons.append("missing_grant_needs_governance")
            env["policy"]["decision_reason"] = "needs_governance"
            return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

        # 3. Budget check — from hub ledger, never protocol (rule_8, Probe C)
        budget = hub_ctx.get("budget", {})
        env["budget"] = _validate_budget(budget, reasons)
        if env["budget"]["parent_total"] == 0 and budget.get("parent_total", 0) != 0:
            decision = "DENY"
            reasons.append("budget_validation_failed")
            env["policy"]["decision_reason"] = "budget_validation_failed"
            return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

        # Fencing / revocation
        env["authorization"]["fencing_token"] = hub_ctx.get("fencing_token", "")
        env["authorization"]["revocation_epoch"] = hub_ctx.get("revocation_epoch", "")
        env["identity"]["authenticated_actor"] = hub_ctx.get("authenticated_actor", "")
        env["identity"]["owner_principal"] = hub_ctx.get("owner_principal", hub_ctx.get("authenticated_actor", ""))
        env["effect"]["idempotency_key"] = f"hub-idem-{sha256_text(msg_id)[:16]}"
        env["knowledge"]["status"] = "proposal"
        env["policy"]["policy_version"] = hub_ctx.get("policy_version", "")
        env["policy"]["decision_reason"] = "accepted_by_registry_and_grant"
        return _finalize("ACCEPT", env, rules, reasons, _payload_digest(input_msg))

    # --- A2A-IN-03: sendTaskStreaming ---
    if method == "sendTaskStreaming":
        rules.append("A2A-IN-03")
        env["operation"]["method"] = method
        env["operation"]["operation_id"] = f"send-task-stream-{msg_id}"
        env["authorization"]["grant_present"] = hub_ctx.get("grants", {}).get("grant_present", False)
        env["identity"]["authenticated_actor"] = hub_ctx.get("authenticated_actor", "")
        env["knowledge"]["status"] = "proposal"
        env["policy"]["decision_reason"] = "streaming_reported_not_terminal"
        return _finalize("ACCEPT", env, rules, reasons, _payload_digest(input_msg))

    # --- A2A-IN-04: cancelTask ---
    if method == "cancelTask":
        rules.append("A2A-IN-04")
        env["operation"]["method"] = method
        env["operation"]["operation_id"] = f"cancel-{msg_id}"

        # Fencing check (Probe D)
        provided_fence = params.get("fencing_token", "") if isinstance(params, dict) else ""
        expected_fence = hub_ctx.get("fencing_token", "")
        provided_epoch = params.get("revocation_epoch", "") if isinstance(params, dict) else ""
        expected_epoch = hub_ctx.get("revocation_epoch", "")

        if provided_fence and provided_fence != expected_fence:
            decision = "DENY"
            reasons.append("stale_fencing_token")
            env["policy"]["decision_reason"] = "stale_fencing_token"
            return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))
        if provided_epoch and provided_epoch != expected_epoch:
            decision = "DENY"
            reasons.append("stale_revocation_epoch")
            env["policy"]["decision_reason"] = "stale_revocation_epoch"
            return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

        env["authorization"]["fencing_token"] = expected_fence
        env["authorization"]["revocation_epoch"] = expected_epoch
        env["effect"]["receipt_state"] = "acknowledged"
        env["effect"]["cancellation_does_not_cancel_reconciliation"] = True
        env["policy"]["decision_reason"] = "cancellation_reported_reconciliation_continues"
        return _finalize("ACCEPT", env, rules, reasons, _payload_digest(input_msg))

    # --- A2A-IN-05: setTaskPushNotificationConfig ---
    if method == "setTaskPushNotificationConfig":
        rules.append("A2A-IN-05")
        env["operation"]["method"] = method
        # Push notification config is NOT a grant
        env["authorization"]["grant_present"] = False
        # Scan for auth claims in config
        push_config = params.get("pushNotificationConfig", {}) if isinstance(params, dict) else {}
        text_blob = json.dumps(push_config)
        auth_claims = _scan_for_auth_claims(text_blob)
        if auth_claims:
            decision = "DENY"
            reasons.append("protocol_task_is_not_a_grant")
            env["policy"]["decision_reason"] = "protocol_task_is_not_a_grant"
            return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))
        env["policy"]["decision_reason"] = "push_config_not_a_grant"
        return _finalize("ACCEPT", env, rules, reasons, _payload_digest(input_msg))

    # --- A2A-IN-06: TaskState mapping ---
    if method == "reportTaskState" or method == "getTask":
        rules.append("A2A-IN-06")
        task = params.get("task", {}) if isinstance(params, dict) else {}
        state = task.get("state", "") if isinstance(task, dict) else ""
        env["operation"]["method"] = method
        # TaskState is a STATUS_REPORTED event, not terminal authority
        if state in ("COMPLETED", "FAILED", "CANCELLED", "REJECTED"):
            env["operation"]["operation_id"] = f"status-report-{msg_id}"
            env["policy"]["decision_reason"] = f"task_state_{state}_is_reported_not_terminal"
            # FAILED/CANCELLED/REJECTED are error events
            if state in ("FAILED", "CANCELLED", "REJECTED"):
                env["effect"]["effect_class"] = "dangerous"
            return _finalize("ACCEPT", env, rules, reasons, _payload_digest(input_msg))
        # UNKNOWN state -> reconciliation
        if state == "UNKNOWN":
            env["effect"]["reconciliation_state"] = "unknown_outcome"
            env["policy"]["decision_reason"] = "unknown_outcome_enters_reconciliation"
            return _finalize("ACCEPT", env, rules, reasons, _payload_digest(input_msg))

    # --- A2A-IN-07: Artifact with knowledge claims ---
    if method == "reportArtifact" or (method == "sendTask" and params.get("artifact", None)):
        rules.append("A2A-IN-07")
        artifact = params.get("artifact", {}) if isinstance(params, dict) else {}
        # Artifact data may propose knowledge; metadata claiming promotion is untrusted
        art_data = json.dumps(artifact)
        auth_claims = _scan_for_auth_claims(art_data)
        if "promotion" in auth_claims or "verified" in auth_claims:
            # Knowledge proposal without promotion event -> proposal only
            env["knowledge"]["status"] = "proposal"
            env["knowledge"]["promotion_event_id"] = None
            env["policy"]["decision_reason"] = "knowledge_proposal_only_no_governance_event"
            # Check for missing source digest (Probe E)
            if "source" not in art_data.lower() and "digest" not in art_data.lower():
                decision = "DENY"
                reasons.append("knowledge_provenance_loss")
                env["policy"]["decision_reason"] = "knowledge_provenance_loss_rejected"
                return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))
            return _finalize("ACCEPT", env, rules, reasons, _payload_digest(input_msg))
        env["knowledge"]["status"] = "proposal"
        env["policy"]["decision_reason"] = "artifact_proposal_only"
        return _finalize("ACCEPT", env, rules, reasons, _payload_digest(input_msg))

    # Default unknown method
    decision = "DENY"
    reasons.append("unhandled_method")
    env["policy"]["decision_reason"] = "method_not_mapped"
    return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))


# ---------------------------------------------------------------------------
# Budget validation (Probe C)
# ---------------------------------------------------------------------------

def _validate_budget(budget: dict, reasons: list) -> dict:
    """Validate budget conservation. Returns a normalized budget dict.
    Any violation appends to reasons but does NOT fail here — the caller
    decides. The key invariant: child reservations + consumed <= parent_total,
    no negative/overflow, same currency/unit."""
    result = {
        "currency": budget.get("currency", ""),
        "unit": budget.get("unit", ""),
        "parent_total": budget.get("parent_total", 0),
        "reserved": budget.get("reserved", 0),
        "consumed": budget.get("consumed", 0),
        "remaining": 0,
        "child_reservation_ids": budget.get("child_reservation_ids", []),
    }
    # Integer check: booleans are NOT integers
    for field in ("parent_total", "reserved", "consumed"):
        val = result[field]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            reasons.append(f"budget_{field}_not_numeric")
            result[field] = 0
        elif val < 0:
            reasons.append(f"budget_{field}_negative")
            result[field] = 0

    # Unit/currency consistency (Probe C)
    if result["currency"] == "" or result["unit"] == "":
        reasons.append("budget_missing_currency_or_unit")

    # Conservation
    allocated = result["reserved"] + result["consumed"]
    if allocated > result["parent_total"]:
        reasons.append("budget_overflow_child_split_or_aggregation")
        # Clamp but flag
    result["remaining"] = max(0, result["parent_total"] - allocated)
    return result


# ---------------------------------------------------------------------------
# Schema matching (simplified)
# ---------------------------------------------------------------------------

def _matches_schema(obj: dict, schema: dict) -> bool:
    """Simplified schema validation: check required keys exist and types match.
    Booleans are not integers."""
    if not isinstance(obj, dict) or not isinstance(schema, dict):
        return False
    required = schema.get("required", [])
    for key in required:
        if key not in obj:
            return False
    properties = schema.get("properties", {})
    for key, val in obj.items():
        if key in properties:
            expected_type = properties[key].get("type")
            if expected_type and not _type_matches(val, expected_type):
                return False
    return True


def _type_matches(val, expected: str) -> bool:
    if expected == "string":
        return isinstance(val, str)
    if expected == "integer":
        return isinstance(val, int) and not isinstance(val, bool)
    if expected == "number":
        return isinstance(val, (int, float)) and not isinstance(val, bool)
    if expected == "boolean":
        return isinstance(val, bool)
    if expected == "object":
        return isinstance(val, dict)
    if expected == "array":
        return isinstance(val, list)
    return True


# ---------------------------------------------------------------------------
# Finalize + evaluate
# ---------------------------------------------------------------------------

def _finalize(decision: str, env: dict, rules: list[str], reasons: list[str],
              payload_digest: str) -> dict:
    env["artifacts"]["protocol_payload_digest"] = payload_digest
    env["operation"]["correlation_id"] = env["operation"]["correlation_id"] or env["operation"]["operation_id"]
    return {
        "decision": decision,
        "envelope": env,
        "rules_triggered": rules,
        "reasons": reasons,
        "payload_digest": payload_digest,
    }


def evaluate_case(case: dict) -> dict:
    """Translate one case and compare with the frozen oracle expectation.

    Expected outcomes are taken ONLY from the case's 'expected' field
    (host-owned frozen fixture), never from producer output.
    """
    case_id = case.get("case_id", "")
    protocol = case.get("protocol", "cross")
    input_msg = case.get("input", {})
    hub_ctx = case.get("hub_context", {})

    # Dispatch
    if protocol == "MCP":
        result = translate_mcp(input_msg, hub_ctx)
    elif protocol == "A2A":
        result = translate_a2a(input_msg, hub_ctx)
    elif protocol == "cross":
        # Cross-protocol: run through both, check both deny correctly
        result = _translate_cross(input_msg, hub_ctx)
    else:
        result = {"decision": "DENY", "envelope": _empty_envelope(protocol, "unknown", "inbound"),
                  "rules_triggered": [], "reasons": ["unknown_protocol"], "payload_digest": ""}

    expected = case.get("expected", None)
    # FAIL-CLOSED: missing or malformed oracle must NOT default to ACCEPT.
    if expected is None or not isinstance(expected, dict):
        return _case_result(case, result, "FAIL", "MISSING_ORACLE", False, {},
                            ["missing_oracle"])
    if "decision" not in expected:
        return _case_result(case, result, "FAIL", "MISSING_DECISION_FIELD", False, {},
                            ["missing_oracle_decision"])
    expected_decision = expected["decision"]
    expected_assertions = expected.get("envelope_assertions", {})

    # Compare decisions
    decision_ok = result["decision"] == expected_decision

    # Compare key envelope assertions
    assertion_results = {}
    for path, expected_val in expected_assertions.items():
        actual_val = _get_path(result["envelope"], path)
        assertion_results[path] = {
            "expected": expected_val,
            "actual": actual_val,
            "matched": actual_val == expected_val,
        }

    all_assertions_ok = all(a["matched"] for a in assertion_results.values())

    verdict = "PASS" if (decision_ok and all_assertions_ok) else "FAIL"

    return _case_result(case, result, verdict, expected_decision, decision_ok,
                        assertion_results, result["reasons"])


def _translate_cross(input_msg: dict, hub_ctx: dict) -> dict:
    """Cross-protocol evaluation: applies hub-level hard rules that span both
    protocols (budget conservation, ownership/replay, knowledge governance,
    version safety). These rules are protocol-agnostic."""
    env = _empty_envelope("CROSS", hub_ctx.get("protocol_version", "1.0"), "inbound")
    rules: list[str] = []
    reasons: list[str] = []
    decision = "ACCEPT"

    method = input_msg.get("method", "")
    params = input_msg.get("params", {})
    msg_id = input_msg.get("id", "")

    # Version/extension safety (Probe F) — check before any acceptance
    input_pv = params.get("protocol_version", "") if isinstance(params, dict) else ""
    if input_pv and input_pv not in _MCP_SUPPORTED_VERSIONS | _A2A_SUPPORTED_VERSIONS:
        env["extensions"]["quarantined"].append({
            "name": "protocol_version",
            "reason": "unsupported_version",
            "provenance": f"pv={input_pv}",
        })
        env["policy"]["decision_reason"] = "unsupported_protocol_version"
        return _finalize("QUARANTINE", env, ["XPROTO-IN-05"],
                         ["unknown_protocol_version"], _payload_digest(input_msg))

    # Budget conservation (Probe C) — only check when a budget is provided
    budget = hub_ctx.get("budget", {})
    if budget:
        budget_reasons_before = len(reasons)
        env["budget"] = _validate_budget(budget, reasons)
        budget_reasons_after = len(reasons)
        allocated = env["budget"]["reserved"] + env["budget"]["consumed"]
        # Any budget malformation (overflow, negative, unit mismatch, non-numeric,
        # missing currency/unit) is a fail-closed condition for Probe C
        if allocated > env["budget"]["parent_total"] or budget_reasons_after > budget_reasons_before:
            decision = "DENY"
            if allocated > env["budget"]["parent_total"]:
                reasons.append("budget_overflow_child_split_or_aggregation")
            env["policy"]["decision_reason"] = "budget_conservation_violation"
            return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

    # Fencing / replay (Probe D)
    provided_fence = params.get("fencing_token", "")
    expected_fence = hub_ctx.get("fencing_token", "")
    if provided_fence and provided_fence != expected_fence:
        decision = "DENY"
        reasons.append("stale_fencing_token")
        env["policy"]["decision_reason"] = "stale_fencing_token"
        return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

    provided_epoch = params.get("revocation_epoch", "")
    expected_epoch = hub_ctx.get("revocation_epoch", "")
    if provided_epoch and provided_epoch != expected_epoch:
        decision = "DENY"
        reasons.append("stale_revocation_epoch")
        env["policy"]["decision_reason"] = "stale_revocation_epoch"
        return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

    # Duplicate effect (Probe D)
    idempotency_key = params.get("idempotency_key", "")
    seen_keys = hub_ctx.get("seen_idempotency_keys", [])
    if idempotency_key and idempotency_key in seen_keys:
        decision = "DENY"
        reasons.append("duplicate_effect_receipt")
        env["policy"]["decision_reason"] = "duplicate_effect_rejected"
        return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

    env["authorization"]["grant_present"] = hub_ctx.get("grants", {}).get("grant_present", False)
    env["authorization"]["fencing_token"] = expected_fence
    env["authorization"]["revocation_epoch"] = expected_epoch
    env["effect"]["idempotency_key"] = idempotency_key or f"hub-idem-{sha256_text(msg_id)[:16]}"
    env["knowledge"]["status"] = "proposal"

    # Knowledge promotion + auth claims (Probe A, Probe E)
    # rule_1: protocol payload is never authority for grant/approval/knowledge
    # promotion. Any auth claim in the payload is denied.
    text_blob = json.dumps(params)
    auth_claims = _scan_for_auth_claims(text_blob)

    # Knowledge promotion/verification claims: status stays proposal, event null
    if "promotion" in auth_claims or "verified" in auth_claims:
        env["knowledge"]["status"] = "proposal"
        env["knowledge"]["promotion_event_id"] = None

    # Any auth claim in protocol payload -> DENY (Probe A/E, rule_1)
    if auth_claims:
        decision = "DENY"
        reasons.append("protocol_task_is_not_a_grant")
        env["authorization"]["grant_present"] = False
        env["policy"]["decision_reason"] = "protocol_task_is_not_a_grant"
        # For knowledge promotion without source provenance, add the specific reason
        if ("promotion" in auth_claims or "verified" in auth_claims) and \
           "source" not in text_blob.lower():
            reasons.append("knowledge_provenance_loss")
        return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

    # Version/extension safety (Probe F)
    unknown_ext = params.get("unknown_extension", "")
    if unknown_ext:
        decision = "QUARANTINE"
        reasons.append("unknown_extension_quarantined")
        env["extensions"]["quarantined"].append({
            "name": unknown_ext,
            "reason": "unknown_extension",
            "provenance": "protocol_payload",
        })
        env["policy"]["decision_reason"] = "unknown_extension_quarantined"
        return _finalize(decision, env, rules, reasons, _payload_digest(input_msg))

    env["policy"]["decision_reason"] = "accepted_cross_protocol"
    return _finalize("ACCEPT", env, rules, reasons, _payload_digest(input_msg))


def _get_path(obj: dict, path: str) -> Any:
    """Get a nested value from a dict using dot notation."""
    keys = path.split(".")
    val = obj
    for key in keys:
        if isinstance(val, dict) and key in val:
            val = val[key]
        else:
            return None
    return val


def _case_result(case: dict, result: dict, verdict: str,
                 decision_expected: str, decision_matched: bool,
                 assertion_results: dict, reasons: list[str]) -> dict:
    """Build the auditable, content-addressed record for one case.

    The result deliberately carries the canonical envelope and a digest of the
    raw fixture input.  This makes A/B comparison independent of display-only
    fields and prevents a result file from being mistaken for evidence when it
    is not bound to the exact fixture bytes.
    """
    record = {
        "case_id": case.get("case_id", ""),
        "protocol": case.get("protocol", ""),
        "category": case.get("category", ""),
        "mapping_category": case.get("mapping_category", ""),
        "capability_row": case.get("capability_row", ""),
        "mapping_rule_ids": list(case.get("mapping_rule_ids", [])),
        "title": case.get("title", ""),
        "probe_id": case.get("probe_id", ""),
        "verdict": verdict,
        "decision_matched": bool(decision_matched),
        "decision_actual": result.get("decision", ""),
        "decision_expected": decision_expected,
        "assertion_results": assertion_results,
        "rules_triggered": list(result.get("rules_triggered", [])),
        "reasons": list(reasons),
        "raw_input_digest": _payload_digest(case.get("input", {})),
        "canonical_envelope": result.get("envelope", {}),
    }
    record["envel_hash"] = sha256_text(canonical_json(record["canonical_envelope"]))
    record["output_digest"] = sha256_text(canonical_json(record))
    return record


# ---------------------------------------------------------------------------
# Corpus runner
# ---------------------------------------------------------------------------

def _safe_manifest_file(root: Path, entry: dict, label: str) -> Path:
    """Resolve a manifest file while rejecting absolute/traversal paths."""
    rel = entry.get("file", "") if isinstance(entry, dict) else ""
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        raise RuntimeError(f"{label} has unsafe relative path")
    candidate = (root / Path(*rel.replace("\\", "/").split("/"))).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"{label} escapes corpus root") from exc
    if not candidate.is_file():
        raise RuntimeError(f"{label} file is missing: {rel}")
    return candidate


def _validate_corpus(corpus: dict, corpus_path: Path) -> dict[str, Any]:
    """Validate every frozen input before creating an output directory.

    Evidence runs are fail-closed: the manifest, all authority files, source
    snapshots, capability mappings, and the exact case set must agree with
    bytes on disk.  Returning the validated manifest also lets the summary
    bind the manifest hash rather than merely repeating a filename.
    """
    root = corpus_path.parent.resolve()
    manifest_path = root / "corpus-manifest.json"
    errors: list[str] = []
    manifest: dict[str, Any] = {}

    if not manifest_path.is_file():
        errors.append(f"corpus-manifest.json not found at {manifest_path}; refusing to run")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"corpus-manifest.json is unreadable: {exc}")

    frozen = manifest.get("frozen_artifacts", {}) if isinstance(manifest, dict) else {}
    required_files = {
        "cases": corpus_path,
        "adapter_contract": root / "adapter-contract.json",
        "canonical_envelope_schema": root / "canonical-envelope.schema.json",
        "rubric": root / "rubric.json",
    }
    # The evaluator itself is an authority input and is checked separately so
    # a stale saved summary cannot survive a code change.
    expected_cases_sha = frozen.get("cases", {}).get("sha256", "")
    actual_cases_sha = sha256_file(corpus_path) if corpus_path.is_file() else ""
    if not expected_cases_sha:
        errors.append("corpus-manifest.json missing cases sha256")
    elif actual_cases_sha != expected_cases_sha:
        # Keep this prefix stable for mutation tests and operator diagnostics.
        errors.append(f"corpus sha256 mismatch: manifest={expected_cases_sha} actual={actual_cases_sha}")

    for key, path in required_files.items():
        entry = frozen.get(key, {})
        expected = entry.get("sha256", "") if isinstance(entry, dict) else ""
        actual = sha256_file(path) if path.is_file() else ""
        if not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
            errors.append(f"{key} missing real sha256")
        elif actual != expected:
            errors.append(f"{key} sha256 mismatch: manifest={expected} actual={actual}")

    evaluator_sha = manifest.get("evaluator_sha256", "")
    actual_evaluator_sha = sha256_file(Path(__file__))
    if evaluator_sha != actual_evaluator_sha:
        errors.append(f"evaluator sha256 mismatch: manifest={evaluator_sha} actual={actual_evaluator_sha}")
    runner_path = root / "runner.py"
    runner_sha = manifest.get("runner_sha256", "")
    actual_runner_sha = sha256_file(runner_path) if runner_path.is_file() else ""
    if not re.fullmatch(r"[0-9a-f]{64}", str(runner_sha)):
        errors.append("runner sha256 missing real sha256")
    elif actual_runner_sha != runner_sha:
        errors.append(f"runner sha256 mismatch: manifest={runner_sha} actual={actual_runner_sha}")

    # Validate the source archive manifest and local snapshot bytes.  A source
    # without a real file binding is not evidence even when its metadata looks
    # plausible.
    source_manifest_path = root / "protocol-snapshot-manifest.json"
    try:
        source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"protocol snapshot manifest unreadable: {exc}")
        source_manifest = {}
    for source in source_manifest.get("sources", []):
        if not isinstance(source, dict):
            errors.append("protocol snapshot manifest contains malformed source")
            continue
        source_type = str(source.get("source_type", "")).lower()
        prov = source.get("verifier_provenance", {})
        if "local" in source_type:
            path = root.parent.parent.parent.parent / Path(*str(prov.get("path", "")).replace("\\", "/").split("/"))
            expected = prov.get("file_sha256", "")
        else:
            rel = source.get("snapshot_path", "")
            path = REPO_ROOT / Path(*str(rel).replace("\\", "/").split("/"))
            expected = source.get("snapshot_sha256", "")
            if source.get("snapshot_sha256_method") != "sha256(snapshot_file_bytes)":
                errors.append(f"{source.get('id', '?')} lacks byte-hash method")
            if not source.get("tag_commit_release"):
                errors.append(f"{source.get('id', '?')} lacks tag/commit/release provenance")
        try:
            path = path.resolve()
            path.relative_to(REPO_ROOT.resolve())
            actual = sha256_file(path)
        except (OSError, ValueError):
            actual = ""
        if not re.fullmatch(r"[0-9a-f]{64}", str(expected)) or actual != expected:
            errors.append(f"{source.get('id', '?')} snapshot hash mismatch or missing bytes")

    # Case shape and oracle integrity.
    cases = corpus.get("cases", []) if isinstance(corpus, dict) else []
    if not isinstance(cases, list):
        errors.append("cases must be a list")
        cases = []
    seen_ids: set[str] = set()
    allowed_protocols = {"MCP", "A2A", "cross"}
    allowed_decisions = {"ACCEPT", "DENY", "QUARANTINE"}
    for case in cases:
        if not isinstance(case, dict):
            errors.append("case is not an object")
            continue
        cid = case.get("case_id", "")
        if cid in seen_ids:
            errors.append(f"duplicate case_id: {cid}")
        seen_ids.add(cid)
        for field in ("case_id", "protocol", "category", "probe_id", "capability_row",
                      "title", "input", "expected", "hub_context"):
            if field not in case:
                errors.append(f"case {cid or '?'} missing field: {field}")
        if case.get("protocol") not in allowed_protocols:
            errors.append(f"case {cid} has invalid protocol")
        expected = case.get("expected")
        if not isinstance(expected, dict) or expected.get("decision") not in allowed_decisions:
            errors.append(f"case {cid} has invalid expected decision")

    manifest_count = manifest.get("corpus", {}).get("total_cases", 0)
    if manifest_count != len(cases):
        errors.append(f"case count mismatch: manifest={manifest_count} actual={len(cases)}")

    # Capability mappings are a runtime claim, not a prose count.  Exactly the
    # supported rows must be represented by explicit mapping cases.
    matrix_path = root / "capability-matrix.json"
    matrix_entry = frozen.get("capability_matrix", {})
    matrix_sha = matrix_entry.get("sha256", "") if isinstance(matrix_entry, dict) else ""
    if matrix_path.is_file() and matrix_sha and sha256_file(matrix_path) != matrix_sha:
        errors.append("capability matrix sha256 mismatch")
    try:
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"capability matrix unreadable: {exc}")
        matrix = {}
    supported = {
        row.get("surface_id") for row in matrix.get("matrix", [])
        if isinstance(row, dict) and row.get("loss_class") != "unsupported"
    }
    mapping_cases = [c for c in cases if isinstance(c, dict) and
                     (c.get("mapping_category") == "capability_mapping" or
                      c.get("category") == "capability_mapping")]
    mapping_rows = {c.get("capability_row") for c in mapping_cases}
    if not supported.issubset(mapping_rows):
        errors.append(f"capability mapping rows missing: {sorted(supported - mapping_rows)}")
    for case in mapping_cases:
        if case.get("capability_row") not in supported:
            errors.append(f"unsupported capability mapping case: {case.get('case_id')}")
        if not case.get("mapping_rule_ids"):
            errors.append(f"capability mapping case lacks mapping_rule_ids: {case.get('case_id')}")

    declared_rows = set((manifest.get("corpus", {}).get("capability_row_coverage") or {}).keys())
    if declared_rows and not mapping_rows.issubset(declared_rows):
        errors.append("manifest capability coverage does not include runtime mappings")

    if errors:
        raise RuntimeError("corpus validation failed: " + "; ".join(errors))
    return {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_sha256": sha256_file(manifest_path),
        "source_manifest": source_manifest,
        "capability_matrix": matrix,
        "supported_capability_rows": sorted(supported),
    }


def run_corpus(corpus_path: str | Path, output_dir: str | Path,
               executor_id: str, nonce: str) -> dict:
    """Run all corpus cases through the evaluator and produce a result bundle.

    The executor_id and nonce ensure process-separated identity. Two runs
    with different executors and nonces over the same clean corpus must
    produce identical envelope hashes and verdicts.
    """
    corpus_path = Path(corpus_path).resolve()
    output_dir = Path(output_dir)

    with open(corpus_path, encoding="utf-8") as f:
        corpus = json.load(f)

    cases = corpus["cases"]

    # FAIL-CLOSED: validate corpus manifest binding and case set integrity
    validation = _validate_corpus(corpus, corpus_path)
    manifest_path = validation["manifest_path"]
    process_provenance = _git_provenance(manifest_path)
    if process_provenance["dirty"]:
        raise RuntimeError(
            "repository working tree is dirty; refusing evidence run: "
            + ", ".join(process_provenance["dirty_files"][:8])
        )

    # Do not allow an evaluator to write evidence before all frozen inputs and
    # repository provenance have passed.  This is intentionally after git
    # validation and before the first output mkdir.
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    verdict_counts = {"PASS": 0, "FAIL": 0}
    probe_results: dict[str, dict] = {}

    for case in cases:
        result = evaluate_case(case)
        results.append(result)
        verdict_counts[result["verdict"]] = verdict_counts.get(result["verdict"], 0) + 1
        if result["probe_id"]:
            probe_results[result["probe_id"]] = {
                "verdict": result["verdict"],
                "decision": result["decision_actual"],
                "decision_expected": result["decision_expected"],
            }

    # Corpus/manifest/contract hashes (must be identical across runs)
    corpus_bytes = corpus_path.read_bytes()
    corpus_sha = sha256_bytes(corpus_bytes)
    contract_path = corpus_path.parent / "adapter-contract.json"
    rubric_path = corpus_path.parent / "rubric.json"
    schema_path = corpus_path.parent / "canonical-envelope.schema.json"

    hashes = {
        "corpus_sha256": corpus_sha,
        "adapter_contract_sha256": sha256_file(contract_path) if contract_path.exists() else "",
        "rubric_sha256": sha256_file(rubric_path) if rubric_path.exists() else "",
        "envelope_schema_sha256": sha256_file(schema_path) if schema_path.exists() else "",
        "evaluator_sha256": sha256_file(__file__),
    }

    output = {
        "executor_id": executor_id,
        "nonce": nonce,
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "case_count": len(results),
        "verdict_counts": verdict_counts,
        "verdict": "PASS" if verdict_counts.get("FAIL", 0) == 0 else "FAIL",
        "hashes": hashes,
        "input_manifest_sha256": validation["manifest_sha256"],
        "process_provenance": process_provenance,
        "results": results,
        "probe_summary": probe_results,
        "capability_rows_passing": _count_capability_rows(results),
    }

    coverage = output["capability_rows_passing"]
    if not coverage.get("coverage_ok", False):
        output["verdict"] = "FAIL"

    # Write per-case results
    with open(output_dir / "results.json", "w", newline="\n") as f:
        json.dump(results, f, indent=2, sort_keys=True)
    # Write summary
    with open(output_dir / "summary.json", "w", newline="\n") as f:
        summary = {k: v for k, v in output.items() if k != "results"}
        json.dump(summary, f, indent=2, sort_keys=True)

    return output


def _count_capability_rows(results: list) -> dict:
    """Count capability rows that pass (real mappings with correct decisions)."""
    cap_rows = [r for r in results if
                r.get("mapping_category") == "capability_mapping" or
                r.get("category") == "capability_mapping"]
    passing = [r for r in cap_rows if r.get("verdict") == "PASS" and
               r.get("capability_row") and r.get("mapping_rule_ids")]
    row_ids = sorted({r["capability_row"] for r in passing})
    return {
        "total": len(cap_rows),
        "passing": len(passing),
        "ids": [r["case_id"] for r in passing],
        "row_ids": row_ids,
        "distinct_rows": len({r.get("capability_row") for r in cap_rows}),
        "distinct_passing_rows": len(row_ids),
        "coverage_ok": len(row_ids) >= 12,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="S1-009 deterministic evaluator")
    parser.add_argument("--corpus", required=True, help="Path to cases.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--executor", required=True, help="Executor/verifier identity")
    parser.add_argument("--nonce", required=True, help="Fresh run nonce (process-separated identity)")
    args = parser.parse_args()

    output = run_corpus(args.corpus, args.out, args.executor, args.nonce)
    # Print summary to stdout (single JSON doc)
    summary = {k: v for k, v in output.items() if k != "results"}
    print(json.dumps(summary, indent=2, sort_keys=True))

    # Exit code: 0 if all pass, 1 if any fail
    return 0 if output["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
