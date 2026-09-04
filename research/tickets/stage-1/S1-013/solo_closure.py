"""Fail-closed verification for the operator-authorized S1-013 solo closure."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any

EXPECTED_ANSWERS = {
    "1": "A", "2": "A", "3": "B", "4": "A", "5": "A", "6": "A",
    "7": "C", "8": "B", "9": "A", "10": "A", "11": "C", "12": "A",
}
APPROVED_FILES = {
    "pilot-protocol.json", "rubric.json", "scenario-manifest.json",
    "consent-template.md", "privacy-plan.md", "facilitator-guide.md",
    "analysis-plan.md",
}
REQUIRED_BROWSER_CHECKS = {
    "consent", "free-responses", "fatigue-value", "stop-ack", "stop-failure",
    "pause-resume", "36-approvals", "export-import", "invalid-import", "withdraw",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _exact_keys(value: dict, expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} fields mismatch")


def verify_operator_decision(ticket: Path, value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("operator decision must be an object")
    required = {
        "schema", "ticket", "decision_id", "decided_at_utc", "operator_id",
        "scope", "full_human_pilot", "target_status", "selected_answers",
        "interpretation", "approved_commit", "approved_artifact_hashes",
        "limitations",
    }
    _exact_keys(value, required, "operator decision")
    if value["schema"] != "agentos.s1-013.operator-decision/v1" or value["ticket"] != "S1-013":
        raise ValueError("operator decision identity mismatch")
    if value["operator_id"] != "OP-OWNER-01":
        raise ValueError("operator id mismatch")
    if value["selected_answers"] != EXPECTED_ANSWERS:
        raise ValueError("operator answers differ from the authorized response")
    if value["scope"] != "solo_expert_review" or value["full_human_pilot"] != "cancelled_by_operator":
        raise ValueError("operator scope/disposition mismatch")
    if value["target_status"] != "PASS_WITH_LIMITS":
        raise ValueError("operator target status is not bounded")
    if not HEX40.fullmatch(value["approved_commit"]):
        raise ValueError("approved commit invalid")
    expected_interpretation = {
        "mode": "accelerated", "roles": ["owner", "reviewer"],
        "answer_use": "expert_rubric_conformance_only",
        "data": "deidentified_answers_and_timings_no_media",
        "raw_policy": "allowed_by_operator_but_deleted_after_aggregate",
        "repository_policy": "aggregates_only_due_to_immediate_deletion",
        "ethics_determination": "operator_determined_not_required_for_internal_solo_walkthrough",
        "independent_grading": "not_available_not_performed",
        "human_followup": "cancelled_no_followup_ticket",
        "human_effectiveness": "NOT_MEASURED",
    }
    if value["interpretation"] != expected_interpretation:
        raise ValueError("operator interpretation mismatch")
    hashes = value["approved_artifact_hashes"]
    if not isinstance(hashes, dict) or set(hashes) != APPROVED_FILES:
        raise ValueError("approved artifact set mismatch")
    for rel, expected in hashes.items():
        if not isinstance(rel, str) or PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts:
            raise ValueError("approved artifact path invalid")
        if not isinstance(expected, str) or not HEX64.fullmatch(expected):
            raise ValueError("approved artifact hash invalid")
        path = ticket.joinpath(*PurePosixPath(rel).parts)
        if not path.is_file() or path.is_symlink() or _sha(path) != expected:
            raise ValueError(f"approved artifact mismatch: {rel}")
    if not isinstance(value["limitations"], list) or len(value["limitations"]) < 5:
        raise ValueError("operator limitations incomplete")
    return value


def verify_solo_review(ticket: Path, value: Any) -> dict:
    if not isinstance(value, dict) or value.get("schema") != "agentos.s1-013.solo-review/v1":
        raise ValueError("solo review schema mismatch")
    fixed = {
        "ticket": "S1-013", "operator_id": "OP-OWNER-01",
        "mode": "accelerated", "reviewed_roles": ["owner", "reviewer"],
        "classification": "operator_authorized_scripted_expert_conformance",
        "human_n": 0, "independent_grading_performed": False,
        "raw_retained": False, "raw_repository_path": None,
        "result": "PASS_WITH_LIMITS", "human_effectiveness": "NOT_MEASURED",
        "full_human_pilot": "CANCELLED_BY_OPERATOR",
    }
    for key, expected in fixed.items():
        if value.get(key) != expected:
            raise ValueError(f"solo review {key} mismatch")
    executions = value.get("executions")
    if not isinstance(executions, list) or [x.get("role") for x in executions if isinstance(x, dict)] != ["owner", "reviewer"]:
        raise ValueError("solo review role matrix incomplete")
    for execution in executions:
        if not isinstance(execution.get("browser_version"), str) or not execution["browser_version"]:
            raise ValueError("browser version missing")
        if set(execution.get("checks", [])) != REQUIRED_BROWSER_CHECKS:
            raise ValueError("browser check matrix incomplete")
        if execution.get("import_status") != "ok" or execution.get("evaluator_completed") is not True:
            raise ValueError("browser/import/evaluator chain incomplete")
        if execution.get("approval_prompts") != 36 or execution.get("stop_confirmed") != 1:
            raise ValueError("browser event counts mismatch")
        if not HEX64.fullmatch(str(execution.get("transient_envelope_sha256", ""))):
            raise ValueError("transient envelope digest invalid")
    if (ticket / "results" / "solo-raw").exists():
        raise ValueError("raw solo-review data was retained")
    if not isinstance(value.get("limitations"), list) or len(value["limitations"]) < 4:
        raise ValueError("solo review limitations incomplete")
    # Reject non-finite data anywhere in the stored aggregate.
    def walk(item: Any) -> None:
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("non-finite solo review data")
        if isinstance(item, dict):
            for child in item.values(): walk(child)
        elif isinstance(item, list):
            for child in item: walk(child)
    walk(value)
    return value


def load_verified(ticket: Path) -> tuple[dict, dict]:
    decision = json.loads((ticket / "operator-decision.json").read_text(encoding="utf-8"))
    review = json.loads((ticket / "results" / "solo-review.json").read_text(encoding="utf-8"))
    return verify_operator_decision(ticket, decision), verify_solo_review(ticket, review)
