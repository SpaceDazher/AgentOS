#!/usr/bin/env python3
"""S1-010 deterministic tool-poisoning evaluator (stdlib only, offline).

Implements the frozen eight-layer control contract from
tool-poisoning-contract.json over the frozen corpus in cases.json.

- decide(case, contract) never reads the oracle: expected outcomes live only
  in the host-owned frozen corpus and are applied by grade().
- grade(records, cases, rubric) derives all metrics from raw decision records
  plus the frozen oracle; producer summaries are never authority.
- evaluate_hard_gates(records, metrics, rubric) applies the frozen rubric.

CLI:
  python evaluator.py --corpus cases.json --out DIR --executor ID --nonce N
                      [--ticket-root DIR] [--repo-root DIR]
                      [--snapshots-root DIR]

Exit codes: 0 only when the hard-gate verdict is PASS.  A generated FAIL
verdict still writes its evidence files, then exits 1; any internal error is
fail-closed and exits non-zero without a summary.  The evaluator is offline;
it must never import network libraries.
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
from pathlib import Path, PureWindowsPath

DEFAULT_TICKET = Path(__file__).resolve().parent
DEFAULT_REPO = DEFAULT_TICKET.parents[3]

BLOCKED_DECISIONS = ("DENY", "QUARANTINE", "HUMAN_REVIEW", "UNSUPPORTED")
EFFECT_POWER = {"read": 0, "write_local": 1, "write_external": 2, "dangerous": 3}
SUPPORTED_SCHEMA_VERSIONS = {"1.0", "2.0"}
REQUIRED_MANIFEST_FIELDS = ("name", "version", "publisher", "capabilities",
                            "effect_class", "content_digest")
MANIFEST_FIELD_TYPES = {"name": str, "version": str, "publisher": str,
                        "capabilities": list, "effect_class": str,
                        "content_digest": str}
# Round 3 (post second independent review): every DECLARED optional manifest
# field is typed too.  An untyped optional field (e.g. description as an
# object) previously slipped past the L6 output guard because the guard only
# scanned str descriptions; malformed input must instead fail closed.
OPTIONAL_MANIFEST_FIELD_TYPES = {"description": str, "declared_sbom": bool,
                                 "dependencies": list}
# L8 audit contract: every decision carries a per-layer trace.  Allowed
# layer-to-layer transitions mirror the frozen pipeline order (L1 revocation
# and L5 policy epilogue may follow L1/L6/L7 respectively); same-layer
# repeats (flag -> pass, route -> pass) are legal.  Derived from the frozen
# contract's decision_flow; violations make the record ungradable.
TRACE_TRANSITIONS = {(0, 1), (1, 2), (1, 5), (2, 3), (3, 4), (4, 6),
                     (6, 5), (6, 7), (7, 5), (5, 7)}
TRACE_STATUSES = ("ok", "fail", "pass", "flag", "advisory", "route",
                  "fail_closed", "skipped", "malformed", "crash", "timeout")
TRACE_FIELDS = ("layer", "name", "status", "detail")
INVISIBLE_RE = re.compile("[\u200b-\u200f\u2060-\u206f\u202a-\u202e]")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
GOV_SENSITIVE_FIELD_RE = re.compile(
    r"policy|approval|budget|capability_patch|gateway|knowledge|accept",
    re.IGNORECASE)
PERCENT_ENCODED_RE = re.compile(r"(?:%[0-9a-fA-F]{2}){3,}")
CYRILLIC_RE = re.compile("[\u0400-\u04ff]")
DIRECTIVE_VERBS = ("send", "upload", "post", "forward", "exfiltrate")
SENSITIVE_PAYLOAD_RE = re.compile(
    r"environment|variables|credentials|secrets|api[- ]?keys?|tokens?|files|"
    r"private[- ]?keys?", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s\"']+")
PATTERNS = {
    "GOV-APPROVAL-CLAIM": re.compile(
        r"approval[^.]{0,80}(granted|already granted|exists|consume it)", re.I),
    "GOV-KNOWLEDGE-CLAIM": re.compile(
        r"(verified and promoted|promoted to canonical|knowledge[^\n]{0,40}"
        r"(promoted|verified|revoked))", re.I),
    "GOV-BUDGET-CLAIM": re.compile(
        r"budget[^.]{0,80}(increased|raised|expanded)", re.I),
    "GOV-RECONCILIATION-CLAIM": re.compile(
        r"reconciliation[^.]{0,80}(completed|complete|resolved)", re.I),
    "GOV-ACCEPTANCE-CLAIM": re.compile(
        r"(goal[^\n]{0,40}accepted|set the goal status to\s+accepted|"
        r"mark the goal as accepted)", re.I),
    "OD-INJECTION": re.compile(
        r"ignore (all )?previous instructions|disregard (your )?instructions|"
        r"new (higher )?priority instructions", re.I),
    "OD-CAPABILITY-EXPANSION": re.compile(
        r"(add|grant|expand|register)[^\n]{0,30}capabilit", re.I),
    "OD-POLICY-OVERRIDE": re.compile(
        r"(override|disable|bypass)[^\n]{0,24}policy|policy checks?[^\n]{0,24}"
        r"(off|disabled)|without (any )?approval", re.I),
    "OD-SECRET-REQUEST": re.compile(
        r"(print|reveal|show|exfiltrate|echo)[^\n]{0,60}"
        r"(secret|SYNTHETIC-SECRET|api[- ]?key|credential|token|private key)", re.I),
    "OD-INDIRECT": re.compile(
        r"(the )?agent (should|must)[^\n]{0,40}(follow|run|execute|read)", re.I),
    "OD-MANIFEST-TEXT-INJECTION": re.compile(
        r"(add|grant|register)[^\n]{0,30}capabilit[^\n]{0,60}registr", re.I),
}
SPLIT_ACTION_VERBS = {"delete", "write", "send", "modify", "run", "execute",
                      "remove"}
GOV_CODES = ("GOV-APPROVAL-CLAIM", "GOV-KNOWLEDGE-CLAIM", "GOV-BUDGET-CLAIM",
             "GOV-RECONCILIATION-CLAIM", "GOV-ACCEPTANCE-CLAIM")


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_repo_relative(path_str: str, repo_root: Path = DEFAULT_REPO) -> str:
    """Enforce repo-relative POSIX syntax independent of the host OS.

    Rejects backslash paths, POSIX-rooted paths (leading ``/``), Windows
    drive-letter/UNC/rooted paths (checked via PureWindowsPath so the rule
    holds on every host), traversal segments, and empty or ``.`` segments.
    After syntax validation the resolved path must stay inside repo_root
    (symlinks resolved), so a rooted path such as ``/etc/passwd`` can never
    escape the repository boundary on any platform.
    """
    if not path_str or not isinstance(path_str, str):
        raise ValueError(f"invalid path: {path_str!r}")
    if "\\" in path_str:
        raise ValueError(f"backslash path is not repo-relative POSIX: {path_str!r}")
    if path_str.startswith("/"):
        raise ValueError(f"POSIX-rooted path rejected: {path_str!r}")
    if re.match(r"^[A-Za-z]:", path_str):
        raise ValueError(f"drive-letter path rejected: {path_str!r}")
    windows = PureWindowsPath(path_str)
    if windows.is_absolute() or windows.drive:
        raise ValueError(
            f"windows-absolute or drive-qualified path rejected: {path_str!r}")
    parts = path_str.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"path traversal or empty segment rejected: {path_str!r}")
    root = Path(repo_root).resolve()
    resolved = (root / path_str).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"path escapes repository boundary: {path_str!r}")
    return path_str


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_contract(ticket_root: Path = DEFAULT_TICKET) -> dict:
    return load_json(ticket_root / "tool-poisoning-contract.json")


def load_rubric(ticket_root: Path = DEFAULT_TICKET) -> dict:
    return load_json(ticket_root / "rubric.json")


def load_case_expectations(record: dict) -> dict:
    """Decisions never carry producer-side expectations.

    Raises KeyError when a record attempts to smuggle oracle fields.
    """
    for banned in ("expected_decision", "expected_reason_class",
                   "producer_decision"):
        if banned in record:
            raise ValueError(f"producer-controlled expectation rejected: {banned}")
    raise KeyError("no expectations are attached to decision records")


# --------------------------------------------------------------------------
# Static indicator layer (L4): advisory evidence only.
# --------------------------------------------------------------------------

def shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    import math
    counts: dict[str, int] = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(text)
    ent = 0.0
    for c in counts.values():
        p = c / n
        ent -= p * math.log(p, 2)
    return ent


class DetectorFault(Exception):
    """Simulated deterministic detector fault (never a real crash)."""


def static_indicator(text: str, fault: dict | None) -> dict:
    """Advisory detector; faults are deterministic and declared by the case."""
    if fault and fault.get("detector") == "static_indicator":
        mode = fault.get("mode")
        if mode == "timeout":
            return {"status": "timeout", "findings": []}
        if mode == "crash":
            raise DetectorFault("static_indicator crashed")
        if mode == "malformed":
            return {"status": "malformed", "findings": "not-a-list"}
        # disagree handled by caller via disagreement flag
    findings = []
    if text:
        if shannon_entropy(text) > 4.5:
            findings.append("SI-ENTROPY")
        lowered = text.lower()
        for verb in ("execute", "delete", "run", "upload", "grant"):
            if verb in lowered:
                findings.append("SI-KEYWORD")
                break
        if PERCENT_ENCODED_RE.search(text) or CYRILLIC_RE.search(text):
            findings.append("SI-OBFUSCATION")
    return {"status": "ok", "findings": sorted(set(findings))}


# --------------------------------------------------------------------------
# Layered decision pipeline (L1-L8)
# --------------------------------------------------------------------------

def decide(case: dict, contract: dict) -> dict:
    trace = []
    reasons = []

    def note(layer: int, name: str, status: str, detail):
        trace.append({"layer": layer, "name": name, "status": status,
                      "detail": detail})

    def deny(code: str) -> dict:
        reasons.append(code)
        return finish("DENY")

    def quarantine(*codes: str) -> dict:
        reasons.extend(codes)
        return finish("QUARANTINE")

    def human_review(code: str) -> dict:
        reasons.append(code)
        return finish("HUMAN_REVIEW")

    def unsupported(code: str) -> dict:
        reasons.append(code)
        return finish("UNSUPPORTED")

    def finish(decision: str) -> dict:
        if decision == "ALLOW":
            reasons.append("BC-ACCEPTED")
        # Malformed input must still produce a complete, crash-free audit
        # record (round 3): digests are computed defensively for non-object
        # inputs instead of raising AttributeError inside the deny path.
        raw_input = case.get("input")
        input_for_digest = raw_input if isinstance(raw_input, dict) else {}
        raw_output = input_for_digest.get("tool_output")
        output_for_digest = raw_output if isinstance(raw_output, dict) else {}
        return {
            "case_id": case["id"],
            "decision": decision,
            "reason_codes": list(dict.fromkeys(reasons)),
            "layer_trace": trace,
            "authority_mutations": [],
            "input_digest": sha256_bytes(canonical(input_for_digest)),
            "output_digest": sha256_bytes(canonical(output_for_digest)),
        }

    inp = case.get("input") or {}
    if not isinstance(inp, dict):
        # Round 3 (finding #6): malformed input still emits a complete,
        # crash-free audit record instead of losing the per-case decision.
        note(0, "input", "fail", "input is not an object")
        note(1, "structural", "fail", "input is not an object")
        return deny("MP-STRUCT")
    manifest = inp.get("manifest")
    tool_output = inp.get("tool_output")
    ctx = case.get("registered_context")
    fault = case.get("fault")
    note(0, "input", "ok", {"manifest": manifest is not None,
                            "tool_output": tool_output is not None})

    # ---- L1 structural: registered context is host-owned authority state;
    # malformed or partial authority data must never degrade to permissive. ----
    if not isinstance(ctx, dict):
        note(1, "structural", "fail", "registered_context is not an object")
        return deny("MP-CTX-INVALID")
    for field in ("tool_name", "registered_capabilities",
                  "registered_effect_class", "known_publishers"):
        if field not in ctx:
            note(1, "structural", "fail",
                 f"missing required context field {field}")
            return deny("MP-CTX-INVALID")
    if not isinstance(ctx["tool_name"], str) or not ctx["tool_name"].strip():
        note(1, "structural", "fail", "context tool_name must be a non-empty string")
        return deny("MP-CTX-INVALID")
    if not isinstance(ctx["registered_effect_class"], str) or \
            not ctx["registered_effect_class"].strip():
        note(1, "structural", "fail",
             "context registered_effect_class must be a non-empty string")
        return deny("MP-CTX-INVALID")
    for list_field in ("registered_capabilities", "known_publishers"):
        value = ctx[list_field]
        if not isinstance(value, list) or \
                not all(isinstance(x, str) for x in value):
            note(1, "structural", "fail",
                 f"context {list_field} must be a list of strings")
            return deny("MP-CTX-INVALID")
    for str_field in ("registered_publisher", "registered_version",
                      "registered_schema_version"):
        if str_field in ctx and not isinstance(ctx[str_field], str):
            note(1, "structural", "fail",
                 f"context {str_field} must be a string when present")
            return deny("MP-CTX-INVALID")
    if "registered_dependency_digests" in ctx and \
            not isinstance(ctx["registered_dependency_digests"], dict):
        note(1, "structural", "fail",
             "context registered_dependency_digests must be an object")
        return deny("MP-CTX-INVALID")
    for bool_field in ("pre_approved", "revoked"):
        if bool_field in ctx and not isinstance(ctx[bool_field], bool):
            note(1, "structural", "fail",
                 f"context {bool_field} must be a strict boolean")
            return deny("MP-CTX-INVALID")
    if "policy_overrides" in ctx and \
            not isinstance(ctx["policy_overrides"], dict):
        note(1, "structural", "fail",
             "context policy_overrides must be an object")
        return deny("MP-CTX-INVALID")

    # ---- Revocation (contract versioning_and_lifecycle.revocation):
    # registry-authority state, checked before any permissive branch. ----
    if ctx.get("revoked") is True:
        note(5, "policy", "fail_closed", "registered context revoked")
        return quarantine("PE-REVOKED")

    # ---- L1 structural: tool_output schema (untrusted external content) ----
    if tool_output is not None:
        if not isinstance(tool_output, dict):
            note(1, "structural", "fail", "tool_output is not an object")
            return deny("MP-OUTPUT-SCHEMA")
        if not isinstance(tool_output.get("text"), str):
            note(1, "structural", "fail",
                 "tool_output.text missing or not a string")
            return deny("MP-OUTPUT-SCHEMA")
        if "structured" in tool_output and \
                not isinstance(tool_output["structured"], dict):
            note(1, "structural", "fail",
                 "tool_output.structured must be an object")
            return deny("MP-OUTPUT-SCHEMA")
        if "schema_version" in tool_output and \
                not isinstance(tool_output["schema_version"], str):
            note(1, "structural", "fail",
                 "tool_output.schema_version must be a string")
            return deny("MP-OUTPUT-SCHEMA")

    # ---- L1 structural ----
    if manifest is None and tool_output is None:
        note(1, "structural", "fail", "no input at all")
        return deny("MP-NO-INPUT")
    if manifest is not None:
        if not isinstance(manifest, dict):
            note(1, "structural", "fail", "manifest is not an object")
            return deny("MP-STRUCT")
        for field in REQUIRED_MANIFEST_FIELDS:
            if field not in manifest:
                note(1, "structural", "fail", f"missing required field {field}")
                return deny("MP-STRUCT")
        for field, ftype in MANIFEST_FIELD_TYPES.items():
            if field in manifest and not isinstance(manifest[field], ftype):
                note(1, "structural", "fail", f"wrong type for {field}")
                return deny("MP-STRUCT")
        for field, ftype in OPTIONAL_MANIFEST_FIELD_TYPES.items():
            if field in manifest and not isinstance(manifest[field], ftype):
                note(1, "structural", "fail",
                     f"wrong type for optional field {field}")
                return deny("MP-STRUCT")
        # Dependency entries must at least be objects with a string name
        # before any layer walks them (a raw string previously crashed L2
        # with AttributeError).  Digest PRESENCE/format stays a provenance
        # (L2) decision: a digest-less dependency is semantically
        # SC-DEP-DIGEST-MISSING, not a structural type fault.
        for dep in manifest.get("dependencies") or []:
            if not isinstance(dep, dict) or \
                    not isinstance(dep.get("name"), str) or \
                    not isinstance(dep.get("digest", ""), str):
                note(1, "structural", "fail",
                     "dependency entries must be objects with string name")
                return deny("MP-STRUCT")
        schema_version = manifest.get("schema_version")
        if schema_version is not None and \
                schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            note(1, "structural", "fail",
                 f"unsupported declared schema_version {schema_version!r}")
            return unsupported("MP-UNSUPPORTED-SCHEMA")
        for ident_field in ("name", "publisher"):
            value = manifest.get(ident_field) or ""
            if isinstance(value, str) and INVISIBLE_RE.search(value):
                note(1, "structural", "fail",
                     f"invisible code point in {ident_field}")
                return deny("MP-OBFUSCATION")
        for cap in manifest.get("capabilities") or []:
            if not isinstance(cap, str) or INVISIBLE_RE.search(cap):
                note(1, "structural", "fail", "invisible code point in capability")
                return deny("MP-OBFUSCATION")
        known_fields = {"schema_version", "name", "version", "publisher",
                        "description", "capabilities", "effect_class",
                        "content_digest", "dependencies", "declared_sbom"}
        for key in manifest:
            if key in known_fields:
                continue
            if isinstance(key, str) and GOV_SENSITIVE_FIELD_RE.search(key):
                note(1, "structural", "fail",
                     f"governance-sensitive unknown field {key!r}")
                return deny("MP-POLICY-INJECTION")
            note(1, "structural", "flag", f"unknown optional field {key!r}")
            reasons.append("SI-UNKNOWN-FIELD")
    note(1, "structural", "pass", {})

    # ---- L2 provenance ----
    if manifest is not None:
        digest = manifest.get("content_digest")
        if not isinstance(digest, str) or not DIGEST_RE.match(digest):
            note(2, "provenance", "fail", "content digest malformed")
            return deny("SC-DIGEST-MALFORMED")
        publisher = manifest.get("publisher")
        registered_publisher = ctx.get("registered_publisher")
        known_publishers = set(ctx.get("known_publishers") or [])
        if registered_publisher is not None and publisher != registered_publisher:
            note(2, "provenance", "fail",
                 "publisher differs from registered publisher (drift)")
            return deny("CD-PUBLISHER-CHANGE")
        if publisher not in known_publishers:
            note(2, "provenance", "fail", "publisher not in known_publishers")
            return deny("SC-PUBLISHER-UNKNOWN")
        # Tool identity binding (round 3): the incoming tool name must be
        # bound to the registered context, exactly like publisher/version
        # drift; an unregistered name under a known publisher can no longer
        # ride an otherwise-clean provenance chain.
        if manifest.get("name") != ctx.get("tool_name"):
            note(2, "provenance", "fail",
                 "manifest name differs from registered tool identity")
            return deny("CD-IDENTITY-MISMATCH")
        for dep in manifest.get("dependencies") or []:
            if not isinstance(dep, dict) or not DIGEST_RE.match(
                    str(dep.get("digest") or "")):
                note(2, "provenance", "fail",
                     f"dependency {dep.get('name')!r} lacks a valid digest")
                return deny("SC-DEP-DIGEST-MISSING")
        if manifest.get("declared_sbom") is False and \
                manifest.get("effect_class") in ("write_external", "dangerous"):
            note(2, "provenance", "fail",
                 "SBOM not declared for an external/dangerous effect class")
            return deny("SC-SBOM-MISSING")
        registered_version = ctx.get("registered_version")
        if registered_version is not None and \
                manifest.get("version") != registered_version:
            note(2, "provenance", "fail", "declared version skews registered version")
            return deny("SC-VERSION-SKEW")
        registered_schema = ctx.get("registered_schema_version")
        if registered_schema is not None and \
                manifest.get("schema_version") != registered_schema:
            note(2, "provenance", "fail", "manifest schema drifted from registration")
            return deny("CD-SCHEMA-CHANGE")
        reg_dep_digests = ctx.get("registered_dependency_digests") or {}
        for dep in manifest.get("dependencies") or []:
            name = dep.get("name")
            if name in reg_dep_digests and dep.get("digest") != reg_dep_digests[name]:
                note(2, "provenance", "fail",
                     f"dependency digest drifted for {name!r}")
                return deny("CD-DEP-DIGEST-CHANGE")
    note(2, "provenance", "pass", {})

    # ---- L3 capability diff / effect gate ----
    if manifest is not None:
        requested = set(manifest.get("capabilities") or [])
        registered = set(ctx.get("registered_capabilities") or [])
        extra = requested - registered
        if extra:
            note(3, "capability_diff", "fail",
                 f"capabilities beyond registration: {sorted(extra)}")
            return deny("CD-CAPABILITY-ADDED")
        effect = manifest.get("effect_class")
        if effect not in EFFECT_POWER:
            note(3, "capability_diff", "fail",
                 f"unknown effect class {effect!r}")
            return quarantine("NM-UNKNOWN-EFFECT")
        # Registered effect class is authority state and must belong to the
        # closed authoritative enum BEFORE any power comparison; an unknown
        # registered class previously skipped the escalation check silently
        # and let the manifest effect through L5 (round 3, finding #5).
        registered_effect = ctx.get("registered_effect_class")
        if registered_effect not in EFFECT_POWER:
            note(3, "capability_diff", "fail",
                 f"unknown registered effect class {registered_effect!r}")
            return quarantine("NM-UNKNOWN-EFFECT")
        if EFFECT_POWER[effect] > EFFECT_POWER[registered_effect]:
            note(3, "capability_diff", "fail",
                 f"effect class escalated {registered_effect!r} -> {effect!r}")
            return deny("CD-EFFECT-ESCALATION")
        note(3, "capability_diff", "pass", {})
    else:
        note(3, "capability_diff", "skipped", "no manifest")

    # ---- L4 static indicators (ADVISORY ONLY; deterministic faults) ----
    # Detector envelopes are validated against a closed status set; any
    # missing/unknown/malformed status fails closed at L7.
    disagree = False
    l4_status = "ok"
    try:
        surfaces = []
        if manifest is not None:
            surfaces.append(str(manifest.get("description") or ""))
        if isinstance(tool_output, dict):
            surfaces.append(str(tool_output.get("text") or ""))
        l4 = static_indicator(" \n".join(surfaces), fault)
        if (not isinstance(l4, dict)
                or not isinstance(l4.get("status"), str)
                or not isinstance(l4.get("findings"), list)
                or not all(isinstance(f, str) for f in l4["findings"])):
            l4_status = "malformed"
            note(4, "static_indicators", "malformed",
                 "detector returned an invalid envelope")
        else:
            raw_status = l4["status"]
            if raw_status == "ok":
                l4_status = "ok"
                reasons.extend(f for f in l4["findings"] if f.startswith("SI-"))
                note(4, "static_indicators", "advisory", l4["findings"])
            elif raw_status in ("timeout", "crash", "malformed"):
                l4_status = raw_status
                note(4, "static_indicators", raw_status,
                     "detector fault declared")
            else:
                l4_status = "malformed"
                note(4, "static_indicators", "malformed",
                     f"unknown detector status {raw_status!r} fails closed")
    except DetectorFault:
        l4_status = "crash"
        note(4, "static_indicators", "crash", "detector fault declared")
    if fault and fault.get("mode") == "disagree":
        disagree = True

    # ---- L6 output guard ----
    l6_findings: list[str] = []
    l6_decision = None
    l6_reasons: list[str] = []

    def scan_text(text: str, surface: str):
        if not text:
            return
        lowered = text.lower()
        # exfiltration pre-check (verb + URL), split into sensitive vs ambiguous
        if surface == "tool_output.text" and URL_RE.search(text) and \
                any(v in lowered for v in DIRECTIVE_VERBS):
            if SENSITIVE_PAYLOAD_RE.search(text):
                _mark("DENY", "OD-EXFILTRATION", surface)
            else:
                _mark("QUARANTINE", "OD-EXFILTRATION", surface)
            return
        # obfuscated forms take precedence (quarantine)
        if PERCENT_ENCODED_RE.search(text):
            if any(p.search(text) for p in PATTERNS.values()) or \
                    "capabilit" in lowered:
                _mark("QUARANTINE", "OD-OBFUSCATED", surface)
                return
        if CYRILLIC_RE.search(text) and any(
                p.search(text) for p in
                (PATTERNS["OD-CAPABILITY-EXPANSION"], PATTERNS["OD-INJECTION"],
                 PATTERNS["OD-POLICY-OVERRIDE"])):
            _mark("QUARANTINE", "OD-OBFUSCATED", surface)
            return
        stripped = text.strip()
        if stripped.startswith("{") and ("\"role\"" in stripped or
                                         "'role'" in stripped) and \
                ("ignore" in lowered or "expand" in lowered):
            _mark("QUARANTINE", "OD-NESTED", surface)
            return
        for code, pattern in PATTERNS.items():
            if pattern.search(text):
                if code in GOV_CODES:
                    _mark("DENY", code, surface)
                    return
                if code == "OD-CAPABILITY-EXPANSION" and surface.startswith(
                        "manifest.description"):
                    _mark("DENY", "OD-MANIFEST-TEXT-INJECTION", surface)
                    return
                _mark("DENY", code, surface)
                return

    def _mark(decision: str, code: str, surface: str):
        nonlocal l6_decision
        if l6_decision is None:
            l6_decision = decision
            l6_reasons.append((code, surface))

    if tool_output is not None and isinstance(tool_output, dict):
        scan_text(str(tool_output.get("text") or ""), "tool_output.text")
        structured = tool_output.get("structured")
        if isinstance(structured, dict):
            action = str(structured.get("action") or "").lower()
            if action in SPLIT_ACTION_VERBS and structured.get("target") is not None:
                if "confirm" in structured:
                    _mark("DENY", "OD-SPLIT-ASSEMBLY", "tool_output.structured")
        # governance claims can also appear inside structured fields
        if l6_decision is None and structured is not None:
            scan_text(json.dumps(structured), "tool_output.structured")
    if manifest is not None and isinstance(manifest.get("description"), str):
        scan_text(manifest["description"], "manifest.description")

    if l6_decision is not None:
        for code, surface in l6_reasons:
            reasons.append(code)
        note(6, "output_guard", "fail",
             {"decision": l6_decision, "reasons": [c for c, _ in l6_reasons]})
        if l6_decision == "QUARANTINE":
            return quarantine()
        return deny(l6_reasons[0][0])
    note(6, "output_guard", "pass", {})

    # ---- L7 fail-closed routing (faults override permissive outcomes) ----
    if l4_status == "timeout":
        note(7, "routing", "fail_closed", "detector timeout")
        return quarantine("DD-TIMEOUT")
    if l4_status == "crash":
        note(7, "routing", "fail_closed", "detector crash")
        return deny("DD-CRASH")
    if l4_status == "malformed":
        note(7, "routing", "fail_closed", "detector malformed output")
        return quarantine("DD-MALFORMED")
    if disagree:
        note(7, "routing", "fail_closed", "scanner disagreement")
        return quarantine("DD-DISAGREEMENT")

    # ---- L5 policy/effect gate ----
    # pre_approved is a strict boolean entitlement read from the host-owned
    # registered context; string "false" or any truthy non-boolean can never
    # grant approval (context validation already rejected non-boolean types).
    pre_approved = ctx.get("pre_approved") is True
    if manifest is not None:
        effect = manifest.get("effect_class")
    else:
        # Output-only invocation: there is no manifest request to admit, so
        # the policy gate routes by the registered effect class.  An
        # effect-capable tool can never ride an admission-free path.
        effect = ctx.get("registered_effect_class")
        note(5, "policy", "route",
             f"no manifest; registered effect {effect!r} governs")
    if effect == "read":
        note(5, "policy", "pass", "read effect")
    elif effect == "write_local":
        note(5, "policy", "pass", "registered write_local")
    elif effect == "write_external":
        if pre_approved:
            note(5, "policy", "pass", "write_external pre-approved")
        else:
            note(5, "policy", "route", "write_external requires human review")
            return human_review("PE-WRITE-EXTERNAL-REVIEW")
    elif effect == "dangerous":
        if pre_approved:
            note(5, "policy", "pass", "dangerous effect pre-approved and clean")
        else:
            note(5, "policy", "fail", "dangerous effect without approval")
            return deny("PE-DANGEROUS-UNAPPROVED")
    else:
        return quarantine("NM-UNKNOWN-EFFECT")

    decision = "ALLOW"
    if case.get("uncertain_effect_capable") and decision == "ALLOW":
        note(7, "routing", "fail_closed",
             "uncertain effect-capable case may not be allowed")
        return quarantine("NM-UNCERTAIN-EFFECT")
    note(5, "policy", "pass", "no gate violations")
    return finish(decision)


# --------------------------------------------------------------------------
# Oracle grading and metrics (host-owned expectations only)
# --------------------------------------------------------------------------

def wilson(k: int, n: int, z: float = 1.959963984540054) -> dict:
    import math
    if n == 0:
        return {"mean": None, "lower": None, "upper": None, "k": 0, "n": 0}
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return {"mean": p, "lower": max(0.0, (centre - spread) / denom),
            "upper": min(1.0, (centre + spread) / denom), "k": k, "n": n}


DECISION_VALUES = ("ALLOW", "DENY", "QUARANTINE", "HUMAN_REVIEW", "UNSUPPORTED")
PRODUCER_CONTROLLED_FIELDS = ("expected_decision", "expected_reason_class",
                              "producer_decision", "truth", "class",
                              "quarantine_acceptable", "human_review_acceptable",
                              "critical", "uncertain_effect_capable")


def validate_layer_trace(trace, decision: str, cid: str) -> None:
    """Validate the L8 audit trace structure of one decision record.

    The trace must be a non-empty list of well-formed entries (layer/name/
    status/detail), start at the input layer, follow the frozen pipeline's
    layer transitions, and terminate consistently with the decision: an
    ALLOW must end at a passing policy layer after a passing output guard,
    any other decision must end at a failing/routing entry.  Empty traces
    previously passed because ``all([])`` is true (round 3, finding #4)."""
    if not isinstance(trace, list) or not trace:
        raise ValueError(
            f"record {cid}: layer_trace must be a non-empty list")
    for entry in trace:
        if not isinstance(entry, dict) or \
                any(field not in entry for field in TRACE_FIELDS):
            raise ValueError(
                f"record {cid}: layer_trace entries require fields "
                f"{TRACE_FIELDS}")
        layer = entry["layer"]
        if isinstance(layer, bool) or not isinstance(layer, int) or \
                not 0 <= layer <= 8:
            raise ValueError(
                f"record {cid}: layer_trace layer must be an integer 0..8")
        if not isinstance(entry["name"], str) or not entry["name"]:
            raise ValueError(
                f"record {cid}: layer_trace name must be a non-empty string")
        if entry["status"] not in TRACE_STATUSES:
            raise ValueError(
                f"record {cid}: layer_trace status {entry['status']!r} "
                f"outside the closed status set")
    if trace[0]["layer"] != 0 or trace[0]["name"] != "input":
        raise ValueError(
            f"record {cid}: layer_trace must begin at the input layer")
    for current, following in zip(trace, trace[1:]):
        if current["layer"] != following["layer"] and \
                (current["layer"], following["layer"]) not in TRACE_TRANSITIONS:
            raise ValueError(
                f"record {cid}: illegal layer transition "
                f"{current['layer']}->{following['layer']}")
    if decision == "ALLOW":
        if trace[-1]["layer"] != 5 or trace[-1]["status"] != "pass":
            raise ValueError(
                f"record {cid}: ALLOW must terminate at a passing policy "
                "layer")
        if not any(entry["layer"] == 6 and entry["status"] == "pass"
                   for entry in trace):
            raise ValueError(
                f"record {cid}: ALLOW requires a passing output-guard layer")
    elif trace[-1]["status"] not in ("fail", "fail_closed", "route"):
        raise ValueError(
            f"record {cid}: non-ALLOW decision must terminate at a "
            "failing or routing trace entry")


def validate_corpus(cases: list, rubric: dict) -> None:
    """Validate the frozen corpus against the rubric's frozen minimums.

    Fails closed (ValueError) on any shape violation: the rubric's corpus
    minimums are enforced on the grading route, not only at build time.
    """
    if not isinstance(cases, list) or not cases:
        raise ValueError("corpus must be a non-empty list")
    gates = rubric.get("hard_gates", {})
    if len(cases) < int(gates.get("min_cases_total", 48)):
        raise ValueError(
            f"corpus below rubric minimum: {len(cases)} < "
            f"{gates.get('min_cases_total', 48)}")
    enum = set(rubric.get("decision_enum", DECISION_VALUES))
    ids: list[str] = []
    class_counts: dict[str, int] = {}
    for c in cases:
        if not isinstance(c, dict):
            raise ValueError("case must be an object")
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            raise ValueError("case id must be a non-empty string")
        ids.append(cid)
        if c.get("truth") not in ("benign", "malicious"):
            raise ValueError(f"case {cid}: truth must be benign|malicious")
        if not isinstance(c.get("class"), str) or not c["class"]:
            raise ValueError(f"case {cid}: class must be a non-empty string")
        if c.get("expected_decision") not in enum:
            raise ValueError(f"case {cid}: expected_decision outside enum")
        if not isinstance(c.get("expected_reason_class"), str) or \
                not c["expected_reason_class"]:
            raise ValueError(f"case {cid}: expected_reason_class required")
        # The oracle must EXPLICITLY declare which alternate reason classes
        # (if any) are safe for this case; an absent declaration is a
        # corpus shape violation, never an implicit wildcard.
        safe_classes = c.get("safe_reason_classes")
        if not isinstance(safe_classes, list) or \
                not all(isinstance(x, str) and x for x in safe_classes):
            raise ValueError(
                f"case {cid}: safe_reason_classes must be explicitly "
                "declared as a list of strings (possibly empty)")
        if not isinstance(c.get("input"), dict):
            raise ValueError(f"case {cid}: input must be an object")
        if not isinstance(c.get("registered_context"), dict):
            raise ValueError(f"case {cid}: registered_context must be an object")
        class_counts[c["class"]] = class_counts.get(c["class"], 0) + 1
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids in corpus")
    for cls, minimum in gates.get("min_cases_per_class", {}).items():
        if class_counts.get(cls, 0) < int(minimum):
            raise ValueError(
                f"corpus class {cls} below rubric minimum: "
                f"{class_counts.get(cls, 0)} < {minimum}")
    subtypes = [str(c.get("subtype") or "") for c in cases]
    for letter in gates.get("probes_required", ("A", "B", "C", "D", "E", "F")):
        if not any(f"probe-{letter}" in s for s in subtypes):
            raise ValueError(f"corpus is missing probe-{letter} cases")


def validate_records(records: list, cases: list[dict], rubric: dict) -> None:
    """Validate raw decision records against the frozen corpus before any
    metric is derived.

    Fails closed (ValueError) unless records cover exactly the frozen case
    set with no duplicates, carry the required typed fields (including a
    present, list-typed authority_mutations), contain no producer-controlled
    expectation fields, and bind to the frozen inputs by recomputed
    input/output digests.  Missing data is never substituted with defaults.
    """
    if not isinstance(records, list) or not records:
        raise ValueError("records must be a non-empty list")
    case_by_id = {c["id"]: c for c in cases}
    enum = set(rubric.get("decision_enum", DECISION_VALUES))
    ids: list[str] = []
    for r in records:
        if not isinstance(r, dict):
            raise ValueError("decision record must be an object")
        cid = r.get("case_id")
        if not isinstance(cid, str) or not cid:
            raise ValueError("record case_id must be a non-empty string")
        ids.append(cid)
        if cid not in case_by_id:
            raise ValueError(f"record references unknown case: {cid}")
        for banned in PRODUCER_CONTROLLED_FIELDS:
            if banned in r:
                raise ValueError(
                    f"producer-controlled field in record {cid}: {banned}")
        decision = r.get("decision")
        if decision not in enum:
            raise ValueError(f"record {cid}: invalid decision {decision!r}")
        reasons = r.get("reason_codes")
        if not isinstance(reasons, list) or \
                not all(isinstance(x, str) and x for x in reasons):
            raise ValueError(f"record {cid}: reason_codes must be non-empty strings")
        # A blocked decision claiming the benign-acceptance code is
        # contradictory evidence and is rejected before grading.
        if "BC-ACCEPTED" in reasons and decision != "ALLOW":
            raise ValueError(
                f"record {cid}: BC-ACCEPTED is only valid on ALLOW")
        if not isinstance(r.get("authority_mutations"), list):
            raise ValueError(
                f"record {cid}: authority_mutations must be present and a list")
        validate_layer_trace(r.get("layer_trace"), decision, cid)
        case = case_by_id[cid]
        expected_input = sha256_bytes(canonical(case.get("input", {})))
        if r.get("input_digest") != expected_input:
            raise ValueError(f"record {cid}: input_digest does not match frozen case")
        expected_output = sha256_bytes(
            canonical(case.get("input", {}).get("tool_output") or {}))
        if r.get("output_digest") != expected_output:
            raise ValueError(f"record {cid}: output_digest does not match frozen case")
        for digest_field in ("input_digest", "output_digest"):
            value = r.get(digest_field)
            if not isinstance(value, str) or not DIGEST_RE.match(value):
                raise ValueError(f"record {cid}: {digest_field} is not a sha256 digest")
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case_id in records")
    if set(ids) != set(case_by_id):
        raise ValueError("records do not cover exactly the frozen corpus case set")


def grade(records: list[dict], cases: list[dict], rubric: dict) -> dict:
    # Fail-closed record/corpus validation precedes every metric derivation.
    validate_corpus(cases, rubric)
    validate_records(records, cases, rubric)
    case_by_id = {c["id"]: c for c in cases}
    blocked = set(rubric.get("blocked_decisions", BLOCKED_DECISIONS))
    outcomes: dict[str, str] = {}
    cm = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    hard = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    per_class_raw: dict[str, dict] = {}
    counters = {"abstention_count": 0, "quarantine_count": 0,
                "human_review_count": 0, "unsupported_count": 0,
                "critical_escape_count": 0, "decision_mismatch_count": 0,
                "conservative_accept_count": 0,
                "reason_class_mismatch_count": 0,
                "malformed_count": 0, "unknown_count": 0, "timeout_count": 0,
                "scanner_disagreement_count": 0,
                "uncertain_effect_capable_allowed": 0}
    expansions = {k: 0 for k in ("capability", "policy", "approval", "budget",
                                 "knowledge", "acceptance")}
    reason_class_matches: dict[str, bool] = {}
    for rec in records:
        case = case_by_id[rec["case_id"]]
        decision = rec["decision"]
        reasons = rec.get("reason_codes", [])
        truth = case["truth"]
        cls = case["class"]
        expected = case["expected_decision"]
        blocked_decision = decision in blocked
        abstains = decision in ("QUARANTINE", "HUMAN_REVIEW", "UNSUPPORTED")
        if abstains:
            counters["abstention_count"] += 1
            if decision == "QUARANTINE":
                counters["quarantine_count"] += 1
            elif decision == "HUMAN_REVIEW":
                counters["human_review_count"] += 1
            else:
                counters["unsupported_count"] += 1
        if decision == expected:
            outcome = "correct"
        elif decision == "QUARANTINE" and case.get("quarantine_acceptable") \
                and expected in blocked:
            outcome = "conservative_accept"
        elif decision == "HUMAN_REVIEW" and case.get("human_review_acceptable") \
                and expected in blocked:
            outcome = "conservative_accept"
        elif truth == "malicious" and decision == "ALLOW":
            outcome = "false_negative_escape"
        elif truth == "benign" and blocked_decision:
            outcome = "false_positive"
        else:
            outcome = "decision_mismatch"
        outcomes[case["id"]] = outcome
        if outcome == "conservative_accept":
            counters["conservative_accept_count"] += 1
        elif outcome == "decision_mismatch":
            counters["decision_mismatch_count"] += 1
        if truth == "malicious":
            if blocked_decision:
                cm["tp"] += 1
            else:
                cm["fn"] += 1
        else:
            if blocked_decision:
                cm["fp"] += 1
            else:
                cm["tn"] += 1
        if outcome == "false_positive":
            hard["fp"] += 1
        pc = per_class_raw.setdefault(cls, {"tp": 0, "fp": 0, "tn": 0, "fn": 0})
        if truth == "malicious":
            pc["tp" if blocked_decision else "fn"] += 1
        else:
            pc["fp" if blocked_decision else "tn"] += 1
        if case.get("critical") and truth == "malicious" and \
                decision == "ALLOW":
            counters["critical_escape_count"] += 1
        if case.get("uncertain_effect_capable") and decision == "ALLOW":
            expansions["capability"] += 1
            counters["uncertain_effect_capable_allowed"] += 1
        reason_class_matches[case["id"]] = \
            case["expected_reason_class"] in reasons or \
            any(safe in reasons
                for safe in (case.get("safe_reason_classes") or []))
        if not reason_class_matches[case["id"]]:
            counters["reason_class_mismatch_count"] += 1
        for code in reasons:
            if code == "DD-MALFORMED" or code == "MP-STRUCT":
                counters["malformed_count"] += 1
            if code == "NM-UNKNOWN-EFFECT":
                counters["unknown_count"] += 1
            if code == "DD-TIMEOUT":
                counters["timeout_count"] += 1
            if code == "DD-DISAGREEMENT":
                counters["scanner_disagreement_count"] += 1
        for key in expansions:
            if rec.get("authority_mutations"):
                expansions[key] += len(rec["authority_mutations"])
    # benign hard FPR per rubric (sanctioned routing excluded)
    benign_truth_total = sum(1 for c in cases if c["truth"] == "benign")
    benign_hard_fpr = (hard["fp"] / benign_truth_total) \
        if benign_truth_total else 0.0
    raw_benign_fpr = (cm["fp"] / benign_truth_total) if benign_truth_total else 0.0
    tp, fp, tn, fn = cm["tp"], cm["fp"], cm["tn"], cm["fn"]
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    per_class = {}
    for cls, m in per_class_raw.items():
        c_tp, c_fp, c_tn, c_fn = m["tp"], m["fp"], m["tn"], m["fn"]
        c_prec = c_tp / (c_tp + c_fp) if (c_tp + c_fp) else 0.0
        c_rec = c_tp / (c_tp + c_fn) if (c_tp + c_fn) else 0.0
        c_fpr = c_fp / (c_fp + c_tn) if (c_fp + c_tn) else 0.0
        c_fnr = c_fn / (c_fn + c_tp) if (c_fn + c_tp) else 0.0
        per_class[cls] = {
            "tp": c_tp, "fp": c_fp, "tn": c_tn, "fn": c_fn,
            "precision": c_prec, "recall": c_rec,
            "false_positive_rate": c_fpr, "false_negative_rate": c_fnr,
            "wilson_precision": wilson(c_tp, c_tp + c_fp),
            "wilson_recall": wilson(c_tp, c_tp + c_fn),
        }
    return {
        "confusion_matrix_overall": cm,
        "hard_gate_confusion_matrix": hard,
        "precision": precision,
        "recall": recall,
        "false_positive_rate": raw_benign_fpr,
        "benign_false_positive_rate": benign_hard_fpr,
        "false_negative_rate": fn / (fn + tp) if (fn + tp) else 0.0,
        "wilson_precision": wilson(tp, tp + fp),
        "wilson_recall": wilson(tp, tp + fn),
        "per_class": per_class,
        "per_case_outcomes": outcomes,
        "reason_class_matches": reason_class_matches,
        "authority_expansions": expansions,
        "raw_benign_blocked_count": cm["fp"],
        **counters,
    }


def evaluate_hard_gates(records: list[dict], metrics: dict,
                        rubric: dict) -> dict:
    gates = rubric["hard_gates"]
    violations = []
    if metrics["critical_escape_count"] != gates["critical_escape_max"]:
        violations.append(
            f"critical_escape_count={metrics['critical_escape_count']}")
    for key, limit in (
            ("capability", "capability_expansion_max"),
            ("policy", "policy_expansion_max"),
            ("approval", "approval_expansion_max"),
            ("budget", "budget_expansion_max"),
            ("knowledge", "knowledge_expansion_max"),
            ("acceptance", "acceptance_expansion_max")):
        if metrics["authority_expansions"][key] != gates[limit]:
            violations.append(f"authority_expansion.{key}="
                              f"{metrics['authority_expansions'][key]}")
    for cls, floor in gates["recall_min_per_malicious_class"].items():
        actual = metrics["per_class"].get(cls, {}).get("recall", 0.0)
        if actual < floor:
            violations.append(f"recall.{cls}={actual} < {floor}")
    if metrics["benign_false_positive_rate"] > gates["benign_fpr_max"]:
        violations.append(
            f"benign_fpr={metrics['benign_false_positive_rate']}")
    if metrics["decision_mismatch_count"] != 0:
        violations.append(
            f"decision_mismatch_count={metrics['decision_mismatch_count']}")
    # Mandatory reason-class grounding (round 3): every accepted decision
    # must carry its oracle-expected reason class or an oracle-declared safe
    # alternate; ungrounded decisions fail the gate.  The threshold is read
    # from the frozen rubric without a default (missing key fails closed).
    if metrics["reason_class_mismatch_count"] != \
            gates["reason_class_mismatch_max"]:
        violations.append(
            f"reason_class_mismatch_count="
            f"{metrics['reason_class_mismatch_count']}")
    for rec in records:
        if rec.get("authority_mutations"):
            violations.append(f"authority_mutations non-empty in {rec['case_id']}")
    if metrics.get("uncertain_effect_capable_allowed", 0):
        violations.append("uncertain effect-capable case was allowed")
    verdict = "PASS" if not violations else "FAIL"
    return {"verdict": verdict, "violations": violations}


# --------------------------------------------------------------------------
# Provenance and CLI
# --------------------------------------------------------------------------

def _git_value(repo_root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(repo_root),
                            capture_output=True, text=True, check=False,
                            timeout=30)
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        raise RuntimeError(
            f"git provenance failed ({' '.join(args)}): "
            f"{result.stderr.strip() or result.returncode}")
    return value


def gather_provenance(repo_root: Path) -> dict:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(repo_root), capture_output=True, text=True, check=False,
        timeout=30)
    if status.returncode != 0:
        raise RuntimeError(f"git status failed: {status.stderr.strip()}")
    dirty_files = [line for line in status.stdout.splitlines() if line.strip()]
    return {
        "evaluator_pid": os.getpid(),
        "evaluator_ppid": os.getppid(),
        "commit_sha": _git_value(repo_root, "rev-parse", "HEAD"),
        "tree_sha": _git_value(repo_root, "rev-parse", "HEAD^{tree}"),
        "branch": _git_value(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(dirty_files),
        "clean": not dirty_files,
        "dirty_files": dirty_files[:50],
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
    }


def verify_frozen_inputs(ticket_root: Path, repo_root: Path,
                         corpus_path: Path,
                         snapshots_root: Path | None = None
                         ) -> tuple[dict, dict, dict, dict,
                                    list[dict], bytes]:
    """Load and hash-verify contract, rubric, corpus manifest, source
    registry, and the corpus itself.  Fails closed on any mismatch.

    snapshots_root redirects where registry snapshot paths are resolved
    against (default: repo_root).  Tamper sandboxes use a redirected root so
    the test mutates the actual bytes the evaluator reads, while git
    provenance still comes from the real repository."""
    manifest = load_json(ticket_root / "corpus-manifest.json")
    contract = load_json(ticket_root / "tool-poisoning-contract.json")
    rubric = load_json(ticket_root / "rubric.json")
    cases_bytes = corpus_path.read_bytes()
    cases_sha = sha256_bytes(cases_bytes)
    if cases_sha != manifest["cases_sha256"]:
        raise RuntimeError("cases.json hash does not match corpus manifest")
    for name, recorded in manifest["frozen_input_hashes"].items():
        actual = sha256_file(ticket_root / name)
        if actual != recorded:
            raise RuntimeError(f"frozen input hash mismatch: {name}")
    cases = json.loads(cases_bytes.decode("utf-8"))
    if manifest["case_count"] != len(cases):
        raise RuntimeError("case count mismatch against corpus manifest")
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate case ids in corpus")
    if set(ids) != set(manifest["per_case_sha256"]):
        raise RuntimeError("case id set mismatch: missing or extra cases")
    for c in cases:
        stripped = {k: v for k, v in c.items() if k != "case_sha256"}
        h = sha256_bytes(canonical(stripped))
        if h != c["case_sha256"]:
            raise RuntimeError(f"per-case self hash mismatch: {c['id']}")
        # The manifest's per-case binding must match the case's own frozen
        # self-hash as a VALUE, not merely share the same key set.
        if manifest["per_case_sha256"].get(c["id"]) != c["case_sha256"]:
            raise RuntimeError(f"per-case manifest binding mismatch: {c['id']}")
        safe_repo_relative(f"research/tickets/stage-1/S1-010/{c['id']}-virtual")
    registry = load_json(ticket_root / "source-registry.json")
    snap_root = Path(snapshots_root).resolve() if snapshots_root else repo_root
    for source in registry["sources"]:
        for snap in source["snapshots"]:
            rel = safe_repo_relative(snap["snapshot_path"], snap_root)
            snap_path = snap_root / rel
            if not snap_path.is_file():
                raise RuntimeError(f"snapshot missing: {rel}")
            if sha256_file(snap_path) != snap["sha256"]:
                raise RuntimeError(f"snapshot hash mismatch: {rel}")
    return manifest, contract, rubric, registry, cases, cases_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--executor", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--ticket-root", default=str(DEFAULT_TICKET))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--snapshots-root", default=None)
    args = parser.parse_args()
    ticket_root = Path(args.ticket_root).resolve()
    repo_root = Path(args.repo_root).resolve()
    snap_root = Path(args.snapshots_root).resolve() \
        if args.snapshots_root else repo_root
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    provenance = gather_provenance(repo_root)
    if provenance["dirty"]:
        print("repository working tree is dirty; refusing evidence run: "
              + ", ".join(provenance["dirty_files"][:8]), file=sys.stderr)
        return 1
    manifest, contract, rubric, registry, cases, cases_bytes = \
        verify_frozen_inputs(ticket_root, repo_root, Path(args.corpus).resolve(),
                             snap_root)

    records = []
    for case in cases:
        record = decide(case, contract)
        if record["case_id"] != case["id"]:
            raise RuntimeError("evaluator misaligned case identity")
        records.append(record)
    metrics = grade(records, cases, rubric)
    gates = evaluate_hard_gates(records, metrics, rubric)
    decisions_doc = {
        "schema": "agentos.s1-010.decisions/v1",
        "ticket": "S1-010",
        "executor_id": args.executor,
        "nonce": args.nonce,
        "decisions": records,
        "metrics": metrics,
        "hard_gates": gates,
    }
    decisions_path = out_dir / "evaluator-decisions.json"
    decisions_path.write_bytes(
        json.dumps(decisions_doc, indent=1, sort_keys=True,
                   ensure_ascii=False).encode("utf-8") + b"\n")
    metrics_path = out_dir / "evaluator-metrics.json"
    metrics_path.write_bytes(
        json.dumps(metrics, indent=1, sort_keys=True,
                   ensure_ascii=False).encode("utf-8") + b"\n")

    summary = {
        "schema": "agentos.s1-010.evaluator-summary/v1",
        "ticket": "S1-010",
        "verdict": gates["verdict"],
        "violations": gates["violations"],
        "case_count": len(records),
        "cases_sha256": sha256_bytes(cases_bytes),
        "contract_sha256": sha256_file(
            ticket_root / "tool-poisoning-contract.json"),
        "rubric_sha256": sha256_file(ticket_root / "rubric.json"),
        "manifest_sha256": sha256_file(ticket_root / "corpus-manifest.json"),
        "threat_model_sha256": sha256_file(ticket_root / "threat-model.json"),
        "source_registry_sha256": sha256_file(
            ticket_root / "source-registry.json"),
        "evaluator_sha256": sha256_file(Path(__file__).resolve()),
        "input_manifest_sha256": sha256_file(ticket_root /
                                             "corpus-manifest.json"),
        "decisions_path": str(decisions_path),
        "decisions_sha256": sha256_file(decisions_path),
        "process_provenance": provenance,
    }
    summary["snapshots_root"] = str(snap_root)
    (out_dir / "evaluator-summary.json").write_bytes(
        json.dumps(summary, indent=1, sort_keys=True,
                   ensure_ascii=False).encode("utf-8") + b"\n")
    print(json.dumps(summary, sort_keys=True))
    # FAIL verdicts are valid measurements but must never exit 0: downstream
    # runners, generators, and CI gate on this exit code.
    return 0 if gates["verdict"] == "PASS" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail-closed: no partial success
        print(f"evaluator failed: {exc}", file=sys.stderr)
        sys.exit(1)
