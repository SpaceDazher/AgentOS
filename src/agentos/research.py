"""Bounded, offline-first research-to-platform-plan workflow.

This module deliberately treats a research bundle as *data*.  It does not
fetch a URI, execute a string from a bundle, or infer capabilities from
untrusted content.  The planner only persists host-computed hashes and the
metadata needed to reproduce the deterministic checks.
"""
from __future__ import annotations

import hashlib
import json
import re
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from .engine import Engine
from .ids import canonical_json, new_id, sha256_text

FLOW = (
    "research_plan",
    "source_registry",
    "feature_catalog",
    "architecture_models",
    "mental_model",
    "ontology",
    "mathematical_model",
    "synthesis_and_gaps",
    "independent_audit",
    "platform_plan",
    "progress",
)

PLATFORM_SECTIONS = (
    "Scope",
    "Architecture",
    "Workstreams",
    "Milestones",
    "Verification",
    "Risks",
    "Open decisions",
)

# Bounded-input contract.  These limits apply equally to JSON files and
# in-process mappings; they are deliberately plain constants so callers and
# tests can report the active boundary without adding dependencies.
MAX_BUNDLE_FILE_BYTES = 20 * 1024 * 1024
MAX_SOURCES = 1000
MAX_CLAIMS = 5000
MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_URI_CHARS = 2048
MAX_SOURCE_TITLE_CHARS = 512
MAX_SOURCE_TYPE_CHARS = 128
MAX_CLAIM_TEXT_CHARS = 4096

# This is the host-owned v1 authority.  Keep the public object immutable so a
# caller cannot mutate the process-wide defaults between campaigns.
DEFAULT_CONFIG: Mapping[str, Any] = MappingProxyType({
    "min_source_count": 3,
    "min_verified_ratio": 1.0,
    "required_artifacts": tuple(FLOW),
})

_HEX64 = re.compile(r"\A[0-9a-fA-F]{64}\Z")
_URI_SCHEMES = {"http", "https"}


class ResearchValidationError(ValueError):
    """Raised only by the strict helper APIs; the public runner fails closed."""


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple, int, float, bool)):
        return canonical_json(value)
    return "" if value is None else str(value)


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, bytes)):
        return bool(value.strip())
    if isinstance(value, (Mapping, list, tuple, set)):
        return bool(value)
    return bool(_as_text(value).strip())


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _content_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return canonical_json(value).encode("utf-8")


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))


def _canonical_uri(value: Any) -> str:
    """Return a small canonical HTTP(S) URI or ``""`` when invalid."""
    if not isinstance(value, str):
        return ""
    raw = value.strip()
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    if parts.scheme.lower() not in _URI_SCHEMES or not parts.netloc:
        return ""
    if parts.username or parts.password or parts.fragment:
        return ""
    host = parts.hostname
    if not host:
        return ""
    try:
        port = parts.port
    except ValueError:
        return ""
    netloc = host.lower()
    if ":" in netloc and not netloc.startswith("["):
        netloc = f"[{netloc}]"
    if port is not None and not ((parts.scheme.lower() == "http" and port == 80)
                                 or (parts.scheme.lower() == "https" and port == 443)):
        netloc = f"{netloc}:{port}"
    path = parts.path or "/"
    # URI spelling is canonicalized only in stable, non-networking ways.
    while "//" in path:
        path = path.replace("//", "/")
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))


def _threshold(config: Mapping[str, Any], names: tuple[str, ...], default: Any) -> Any:
    for name in names:
        if name in config:
            return config[name]
    return default


def _bundle_config_proposal(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Return bundle config as data only; it is never evaluation authority."""
    proposal: dict[str, Any] = {}
    raw = bundle.get("config")
    if isinstance(raw, Mapping):
        proposal.update(dict(raw))
    thresholds = bundle.get("thresholds")
    if isinstance(thresholds, Mapping):
        proposal.update(dict(thresholds))
    return proposal


def _normalise_config(config: Any, bundle: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Normalize host authority and reject attempts to remove v1 stages.

    Bundle thresholds are retained by the caller as an untrusted proposal,
    but are deliberately not consulted here.  Only the explicit ``config``
    argument is trusted; absent that argument the immutable defaults apply.
    """
    errors: list[str] = []
    proposal = _bundle_config_proposal(bundle)
    for key in ("config", "thresholds"):
        if key in bundle and bundle[key] is not None and not isinstance(bundle[key], Mapping):
            errors.append(f"bundle {key} proposal must be an object")
    if not isinstance(config, Mapping) and config is not None:
        return {}, ["config must be an object"]
    out = dict(DEFAULT_CONFIG)
    # Explicit API config is trusted only for numeric thresholds and an
    # identical required-artifacts declaration.  Arbitrary bundle values are
    # never promoted into authority.
    trusted = dict(config) if isinstance(config, Mapping) else {}
    if "required_artifacts" in trusted:
        out["required_artifacts"] = trusted["required_artifacts"]
    min_count = _threshold(
        trusted, ("min_source_count", "minimum_source_count", "min_sources", "source_minimum"),
        DEFAULT_CONFIG["min_source_count"],
    )
    ratio = _threshold(
        trusted, ("min_verified_ratio", "minimum_verified_ratio", "verified_ratio"),
        DEFAULT_CONFIG["min_verified_ratio"],
    )
    try:
        min_count = int(min_count)
    except (TypeError, ValueError):
        errors.append("config min_source_count must be an integer >= 1")
        min_count = 1
    if min_count < 1:
        errors.append("config min_source_count must be an integer >= 1")
    try:
        ratio = float(ratio)
    except (TypeError, ValueError):
        errors.append("config min_verified_ratio must be a number in [0, 1]")
        ratio = 1.0
    if not 0.0 <= ratio <= 1.0:
        errors.append("config min_verified_ratio must be a number in [0, 1]")
    required = out.get("required_artifacts", list(FLOW))
    if not isinstance(required, (list, tuple)) or not required:
        errors.append("config required_artifacts must be the complete v1 FLOW")
        required = list(FLOW)
    required = [str(x).strip() for x in required if str(x).strip()]
    unknown = [x for x in required if x not in FLOW]
    if unknown:
        errors.append("config required_artifacts contains unknown stages: " + ", ".join(unknown))
    if tuple(required) != FLOW:
        errors.append("config required_artifacts cannot remove v1 FLOW stages")
        required = list(FLOW)
    proposal_required = proposal.get("required_artifacts")
    if proposal_required is not None:
        if not isinstance(proposal_required, (list, tuple)):
            errors.append("bundle required_artifacts proposal must be the complete v1 FLOW")
        else:
            proposed = [str(x).strip() for x in proposal_required if str(x).strip()]
            if tuple(proposed) != FLOW:
                errors.append("bundle required_artifacts proposal cannot remove v1 FLOW stages")
    out["min_source_count"] = min_count
    out["min_verified_ratio"] = ratio
    # Persist a JSON-safe immutable-by-convention representation.  The module
    # constant remains a tuple while DB/config responses use a list.
    out["required_artifacts"] = list(required)
    # A canonical copy is persisted; user extensions remain available as data.
    return out, errors


def _load_bundle(bundle: Any) -> tuple[dict[str, Any] | None, list[str], bool]:
    if bundle is None:
        return None, [], True
    if isinstance(bundle, Mapping):
        try:
            mapping_size = len(canonical_json(dict(bundle)).encode("utf-8"))
        except (TypeError, ValueError, UnicodeError) as exc:
            return None, [f"research bundle mapping is not JSON-serializable: {exc}"], False
        if mapping_size > MAX_BUNDLE_FILE_BYTES:
            return None, [
                f"research bundle mapping exceeds {MAX_BUNDLE_FILE_BYTES} bytes"
            ], False
        return dict(bundle), [], False
    if not isinstance(bundle, (str, os.PathLike)):
        return None, ["research bundle must be an object or JSON file path"], False
    try:
        path = Path(bundle)
    except (TypeError, ValueError):
        return None, ["research bundle must be an object or JSON file path"], False
    if not path.exists():
        return None, [f"research bundle not found: {path}"], True
    try:
        if path.stat().st_size > MAX_BUNDLE_FILE_BYTES:
            return None, [
                f"research bundle file exceeds {MAX_BUNDLE_FILE_BYTES} bytes"
            ], False
        raw = path.read_bytes()
        # Recheck after stat to fail closed on a file that changes between
        # the pre-read bound and the read itself.
        if len(raw) > MAX_BUNDLE_FILE_BYTES:
            return None, [
                f"research bundle file exceeds {MAX_BUNDLE_FILE_BYTES} bytes"
            ], False
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, [f"research bundle is not valid JSON: {exc}"], False
    if not isinstance(value, Mapping):
        return None, ["research bundle root must be a JSON object"], False
    return dict(value), [], False


def _manifest_hash(bundle: Mapping[str, Any], config: Mapping[str, Any]) -> tuple[str, list[str]]:
    # Claimed manifest fields are assertions, not inputs to their own digest.
    # Authority is host-owned and included explicitly in the identity.
    proposal = _bundle_config_proposal(bundle)
    asserted = bundle.get("manifest_sha256", bundle.get("manifest_hash"))
    if asserted is None:
        asserted = proposal.get("manifest_sha256", proposal.get("manifest_hash"))
    canonical_bundle = dict(bundle)
    canonical_bundle.pop("manifest_sha256", None)
    canonical_bundle.pop("manifest_hash", None)
    for key in ("config", "thresholds"):
        nested = canonical_bundle.get(key)
        if isinstance(nested, Mapping):
            nested = dict(nested)
            nested.pop("manifest_sha256", None)
            nested.pop("manifest_hash", None)
            canonical_bundle[key] = nested
    envelope = {"bundle": canonical_bundle, "authority_config": dict(config)}
    host_hash = sha256_text(canonical_json(envelope))
    if asserted is not None:
        if not _valid_sha(asserted):
            return "", ["manifest SHA-256 must be exactly 64 hexadecimal characters"]
        if str(asserted).lower() != host_hash:
            return "", ["manifest SHA-256 assertion does not match host-computed manifest"]
    return host_hash, []


def _source_items(bundle: Mapping[str, Any]) -> list[Any]:
    value = bundle.get("sources", bundle.get("source_registry", []))
    if isinstance(value, Mapping):
        return [dict(item, id=key) if isinstance(item, Mapping) else item
                for key, item in value.items()]
    return list(value) if isinstance(value, (list, tuple)) else []


def _claim_items(bundle: Mapping[str, Any]) -> list[Any]:
    value = bundle.get("claims", [])
    if isinstance(value, Mapping):
        return [dict(item, id=key) if isinstance(item, Mapping) else item
                for key, item in value.items()]
    return list(value) if isinstance(value, (list, tuple)) else []


def _artifact_items(bundle: Mapping[str, Any]) -> dict[str, Any]:
    value = bundle.get("artifacts", {})
    out: dict[str, Any] = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            out[str(key)] = item
    elif isinstance(value, (list, tuple)):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            key = item.get("kind", item.get("name", item.get("artifact_name")))
            if key is not None:
                out[str(key)] = item
    # A compact bundle may put the named artifact objects at its root.  The
    # canonical representation remains the same and no root metadata is
    # interpreted as an instruction.
    for kind in FLOW:
        if kind not in out and kind in bundle:
            out[kind] = bundle[kind]
    return out


def _reference_key(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("id", "source_id", "claim_id", "uri", "canonical_uri", "kind", "name"):
            if key in value:
                return str(value[key])
        return ""
    return str(value)


def _platform_sections(content: Any) -> list[str]:
    missing: list[str] = []
    if isinstance(content, Mapping):
        for section in PLATFORM_SECTIONS:
            value = content.get(section, content.get(section.lower()))
            if len(_as_text(value).strip()) < 12:
                missing.append(section)
        return missing
    text = _as_text(content)
    for section in PLATFORM_SECTIONS:
        # Accept Markdown headings and explicit ``Section: value`` records,
        # while requiring non-empty text after the heading/key.
        pat = re.compile(
            rf"(?im)^\s*(?:#{{1,6}}\s*)?{re.escape(section)}\s*(?:[:\-]|$)"
            rf"[^\n]*?(?:\n|$)"
        )
        match = pat.search(text)
        if not match:
            missing.append(section)
            continue
        tail = text[match.end():]
        next_heading = re.search(r"(?im)^\s*#{1,6}\s+\S", tail)
        section_text = tail[:next_heading.start()] if next_heading else tail
        # For ``Scope: value`` the value is in the matched line itself.
        line = match.group(0).split("\n", 1)[0]
        body = line.split(":", 1)[1].strip() if ":" in line else section_text.strip()
        if len(body) < 12:
            missing.append(section)
    return missing


def _safe_artifact_content(item: Any) -> tuple[Any, bytes, str]:
    if isinstance(item, Mapping):
        for key in ("content", "body", "text", "data"):
            if key in item:
                value = item[key]
                if not _nonempty(value):
                    return value, b"", ".md" if isinstance(value, str) else ".json"
                data = _content_bytes(value)
                return value, data, ".md" if isinstance(value, str) else ".json"
        # Metadata-only records are not artifacts.  Do not serialize claim
        # references or producer fields as if they were substantive content.
        return None, b"", ".json"
    data = _content_bytes(item)
    return item, data, ".md" if isinstance(item, str) else ".json"


def _source_provenance(item: Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
    verification = item.get("verification", {})
    if not isinstance(verification, Mapping):
        verification = {}
    status = str(item.get("verification_status", item.get("status", verification.get("status", "unverified")))).strip().lower()
    if status in ("included", "include"):
        status = "unverified"
    provenance = item.get("verifier_provenance", item.get("provenance", verification.get("provenance", {})))
    if not isinstance(provenance, Mapping):
        provenance = {"value": _as_text(provenance)} if provenance else {}
    verifier = item.get(
        "verifier", verification.get("verifier", verification.get(
            "actor", provenance.get("identity", provenance.get("verifier", "")))))
    method = item.get("verification_method", verification.get(
        "method", provenance.get("method", "")))
    return status, _as_text(verifier).strip(), {"method": _as_text(method).strip(), **dict(provenance)}


def _normalize_bundle(bundle: Mapping[str, Any], config: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Normalize untrusted input and return DB-ready values plus validation errors."""
    errors: list[str] = []
    normalized: dict[str, Any] = {"sources": [], "claims": [], "artifacts": {}, "audit": {}}

    source_aliases: dict[str, str] = {}
    source_items = _source_items(bundle)
    if len(source_items) > MAX_SOURCES:
        errors.append(f"source limit exceeded: at most {MAX_SOURCES} sources are allowed")
    for index, raw in enumerate(source_items[:MAX_SOURCES]):
        if not isinstance(raw, Mapping):
            errors.append(f"source {index} must be an object")
            continue
        uri_raw = raw.get("canonical_uri", raw.get("uri", raw.get("url")))
        if isinstance(uri_raw, str) and len(uri_raw) > MAX_URI_CHARS:
            errors.append(f"source {index} URI exceeds {MAX_URI_CHARS} characters")
            continue
        uri = _canonical_uri(uri_raw)
        if not uri:
            errors.append(f"source {index} canonical URI is invalid")
            continue
        title = _as_text(raw.get("title", "")).strip()
        source_type = _as_text(raw.get("source_type", raw.get("type", raw.get("kind", "")))).strip()
        if not title:
            errors.append(f"source {index} title is required")
        elif len(title) > MAX_SOURCE_TITLE_CHARS:
            errors.append(f"source {index} title exceeds {MAX_SOURCE_TITLE_CHARS} characters")
        if not source_type:
            errors.append(f"source {index} source type is required")
        elif len(source_type) > MAX_SOURCE_TYPE_CHARS:
            errors.append(f"source {index} source type exceeds {MAX_SOURCE_TYPE_CHARS} characters")
        has_content = any(key in raw for key in ("content", "body", "text"))
        content = next((raw[key] for key in ("content", "body", "text") if key in raw), None)
        computed_sha = _sha_bytes(_content_bytes(content)) if has_content else ""
        supplied_sha = raw.get("content_sha256", raw.get("sha256"))
        if has_content:
            content_bytes = _content_bytes(content)
            if len(content_bytes) > MAX_BODY_BYTES:
                errors.append(f"source {index} body exceeds {MAX_BODY_BYTES} bytes")
            if supplied_sha is not None and (not _valid_sha(supplied_sha)
                                              or str(supplied_sha).lower() != computed_sha):
                errors.append(f"source {index} content SHA-256 does not match host-computed content")
            content_sha = computed_sha
        else:
            if not _valid_sha(supplied_sha):
                errors.append(f"source {index} content SHA-256 is invalid or missing")
                content_sha = "0" * 64
            else:
                content_sha = str(supplied_sha).lower()
        status, verifier, provenance = _source_provenance(raw)
        method = provenance.get("method", "")
        if status not in {"verified", "unverified", "excluded"}:
            errors.append(f"source {index} verification status is invalid")
            status = "unverified"
        if status == "verified" and (not verifier or not method):
            errors.append(f"source {index} verified status requires verifier and method provenance")
        # Keep canonical ids compact enough for the vault redactor to retain
        # them as exact frontmatter bindings (long opaque strings are treated
        # as token-like untrusted text by wiki.py).
        internal_id = new_id("rsrc")
        aliases = {
            str(raw.get("id", "")), str(raw.get("source_id", "")), uri,
            str(index), internal_id,
        }
        for alias in aliases:
            if alias:
                if alias in source_aliases:
                    errors.append(f"duplicate canonical source or source reference: {uri}")
                source_aliases[alias] = internal_id
        normalized["sources"].append({
            "id": internal_id,
            "input_id": str(raw.get("id", raw.get("source_id", index))),
            "canonical_uri": uri,
            "title": title,
            "source_type": source_type,
            "content_sha256": content_sha,
            "verification_status": status,
            "verifier": verifier or None,
            "verification_method": method or None,
            "verifier_provenance_json": canonical_json(provenance),
        })

    claim_aliases: dict[str, str] = {}
    claim_items = _claim_items(bundle)
    if len(claim_items) > MAX_CLAIMS:
        errors.append(f"claim limit exceeded: at most {MAX_CLAIMS} claims are allowed")
    for index, raw in enumerate(claim_items[:MAX_CLAIMS]):
        if not isinstance(raw, Mapping):
            errors.append(f"claim {index} must be an object")
            continue
        text = _as_text(raw.get("text", raw.get("claim", raw.get("claim_text", "")))).strip()
        cls = str(raw.get("claim_class", raw.get("class", raw.get("type", "")))).strip().lower()
        if not text:
            errors.append(f"claim {index} text is required")
        elif len(text) > MAX_CLAIM_TEXT_CHARS:
            errors.append(f"claim {index} text exceeds {MAX_CLAIM_TEXT_CHARS} characters")
        if cls not in {"fact", "inference", "assumption", "target"}:
            errors.append(f"claim {index} must declare class fact|inference|assumption|target")
            cls = "assumption"
        internal_id = new_id("rclm")
        aliases = {str(raw.get("id", "")), str(raw.get("claim_id", "")), str(index), internal_id}
        for alias in aliases:
            if alias:
                if alias in claim_aliases:
                    errors.append(f"duplicate claim identifier: {alias}")
                claim_aliases[alias] = internal_id
        refs = raw.get("source_ids", raw.get("sources", raw.get(
            "source_refs", raw.get("support", []))))
        if not isinstance(refs, (list, tuple)):
            refs = [refs] if refs else []
        normalized["claims"].append({
            "id": internal_id,
            "input_id": str(raw.get("id", raw.get("claim_id", index))),
            "text": text,
            "claim_class": cls,
            "source_refs": [_reference_key(ref) for ref in refs if _reference_key(ref)],
        })

    for claim in normalized["claims"]:
        resolved: list[str] = []
        for ref in claim.pop("source_refs"):
            target = source_aliases.get(ref)
            if target is None:
                errors.append(f"claim {claim['id']} references unknown same-goal source: {ref}")
            elif target not in resolved:
                resolved.append(target)
        claim["source_ids"] = resolved

    artifact_aliases: dict[str, str] = {}
    for kind in FLOW:
        if kind not in _artifact_items(bundle):
            continue
        raw = _artifact_items(bundle)[kind]
        value, data, suffix = _safe_artifact_content(raw)
        if len(data) > MAX_BODY_BYTES:
            errors.append(f"artifact {kind} body exceeds {MAX_BODY_BYTES} bytes")
        if not data.strip():
            errors.append(f"artifact {kind} is empty")
        claim_refs: Any = raw.get("claim_refs", raw.get("claims", raw.get(
            "claim_ids", raw.get("claim_references", [])))) if isinstance(raw, Mapping) else []
        if not isinstance(claim_refs, (list, tuple)):
            claim_refs = [claim_refs] if claim_refs else []
        refs: list[str] = []
        for ref in claim_refs:
            key = _reference_key(ref)
            target = claim_aliases.get(key)
            if target is None:
                errors.append(f"artifact {kind} references unknown same-goal claim: {key}")
            elif target not in refs:
                refs.append(target)
        producer = raw.get("producer", bundle.get("producer", "")) if isinstance(raw, Mapping) else bundle.get("producer", "")
        normalized["artifacts"][kind] = {
            "kind": kind,
            "content": value,
            "bytes": data,
            "suffix": suffix,
            "content_sha256": _sha_bytes(data),
            "claim_ids": refs,
            "producer": _as_text(producer).strip() or "",
        }

    audit = bundle.get("audit", bundle.get("independent_audit", {}))
    if (not isinstance(audit, Mapping) or not audit) and isinstance(
            _artifact_items(bundle).get("independent_audit"), Mapping):
        audit = _artifact_items(bundle)["independent_audit"]
    if not isinstance(audit, Mapping):
        audit = {}
    subject_producer = audit.get(
        "subject_producer", audit.get("subject", audit.get(
            "producer", bundle.get("producer", ""))))
    if isinstance(subject_producer, Mapping):
        subject_producer = subject_producer.get(
            "producer", subject_producer.get("id", ""))
    normalized["audit"] = {
        # ``producer`` is retained as a compatibility alias for the audited
        # producer; subject_producer is the explicit contract field.
        "producer": _as_text(subject_producer).strip(),
        "subject_producer": _as_text(subject_producer).strip(),
        "auditor": _as_text(audit.get("auditor", audit.get(
            "independent_auditor", bundle.get("auditor", "")))).strip(),
        "verdict": _as_text(audit.get("verdict", audit.get(
            "audit_verdict", audit.get("result", "")))).strip().lower(),
        "limitations": audit.get("limitations", audit.get("limits", [])),
    }
    return normalized, errors


def _evaluation_checks(normalized: Mapping[str, Any], config: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    next_actions: list[str] = []
    sources = list(normalized["sources"])
    verified = [s for s in sources if s["verification_status"] == "verified"]
    min_count = int(config["min_source_count"])
    ratio = len(verified) / len(sources) if sources else 0.0
    if len(sources) < min_count:
        failures.append(f"source count {len(sources)} is below minimum {min_count}")
        next_actions.append(f"Add at least {min_count - len(sources)} more canonical source(s)")
    if ratio < float(config["min_verified_ratio"]):
        failures.append(f"verified source ratio {ratio:.3f} is below minimum {float(config['min_verified_ratio']):.3f}")
        next_actions.append("Verify additional sources with verifier and method provenance")

    by_source = {s["id"]: s for s in sources}
    claims = list(normalized["claims"])
    if not claims:
        failures.append("research requires non-empty claims")
        next_actions.append("Provide explicit fact, inference, assumption, or target claims")
    if not any(claim.get("claim_class") == "fact" for claim in claims):
        failures.append("research requires at least one factual claim")
        next_actions.append("Provide at least one fact claim with source support")
    for claim in claims:
        if claim["claim_class"] != "fact":
            continue
        supporting = [by_source[sid] for sid in claim["source_ids"] if sid in by_source]
        if not supporting or any(s["verification_status"] != "verified" for s in supporting):
            bad = [s["id"] for s in supporting if s["verification_status"] != "verified"]
            suffix = f" cites unverified/excluded source(s): {', '.join(bad)}" if bad else ""
            failures.append(
                f"fact claim {claim['id']} lacks support from a verified same-goal "
                "source with supports relation")
            if suffix:
                failures[-1] += suffix
            next_actions.append(f"Cite only verified sources for fact claim {claim['id']}")

    required = list(config["required_artifacts"])
    artifacts = normalized["artifacts"]
    missing = [kind for kind in required if kind not in artifacts]
    if missing:
        failures.append("required artifacts missing: " + ", ".join(missing))
        next_actions.append("Provide non-empty artifacts: " + ", ".join(missing))
    for kind, artifact in artifacts.items():
        if not artifact["bytes"].strip():
            failures.append(f"artifact {kind} is empty")
            next_actions.append(f"Populate artifact {kind}")
        if artifact.get("decode_error"):
            failures.append(f"artifact {kind} is not valid UTF-8")
            next_actions.append(f"Restore UTF-8 encoded bytes for artifact {kind}")
        elif artifact.get("content_sha256") and _sha_bytes(artifact["bytes"]) != artifact["content_sha256"]:
            failures.append(f"artifact {kind} host hash does not match stored content hash")
            next_actions.append(f"Restore the immutable bytes for artifact {kind}")

    substantive = {
        "feature_catalog", "architecture_models", "mental_model", "ontology",
        "mathematical_model", "synthesis_and_gaps", "platform_plan",
    }
    claim_ids = {claim["id"] for claim in claims}
    for kind in sorted(substantive):
        artifact = artifacts.get(kind)
        if artifact is None:
            continue
        refs = [ref for ref in artifact.get("claim_ids", []) if ref in claim_ids]
        if not refs:
            failures.append(f"artifact {kind} requires at least one valid same-goal claim reference")
            next_actions.append(f"Add a same-goal claim reference to artifact {kind}")

    audit = normalized["audit"]
    if not audit.get("subject_producer", audit.get("producer")) or not audit["auditor"]:
        failures.append("independent audit requires producer and auditor identities")
        next_actions.append("Record producer and independent auditor identities")
    elif audit.get("subject_producer", audit.get("producer")) == audit["auditor"]:
        failures.append("independent auditor must differ from producer")
        next_actions.append("Use an auditor identity different from the producer")
    if audit["verdict"] not in {"pass", "pass_with_limits"}:
        failures.append("independent audit verdict must be pass or pass_with_limits")
        next_actions.append("Record an independent audit verdict of pass or pass_with_limits")
    if audit["verdict"] == "pass_with_limits" and not _nonempty(audit["limitations"]):
        failures.append("pass_with_limits audit requires explicit limitations")
        next_actions.append("Document limitations for the limited independent-audit pass")

    platform_producer = artifacts.get("platform_plan", {}).get("producer", "")
    audit_artifact_producer = artifacts.get("independent_audit", {}).get("producer", "")
    subject_producer = audit.get("subject_producer", audit.get("producer", ""))
    if not platform_producer or not audit_artifact_producer:
        failures.append("platform_plan and independent_audit artifacts require non-empty producers")
        next_actions.append("Record non-empty producers for platform_plan and independent_audit")
    else:
        if subject_producer != platform_producer:
            failures.append("audit subject producer must match platform_plan producer")
            next_actions.append("Bind audit subject_producer to the platform_plan producer")
        if audit["auditor"] != audit_artifact_producer:
            failures.append("audit auditor must match independent_audit artifact producer")
            next_actions.append("Bind audit auditor to the independent_audit producer")
        if subject_producer == audit_artifact_producer:
            failures.append("independent auditor artifact producer must differ from platform producer")
            next_actions.append("Use a distinct producer for independent_audit")

    platform = artifacts.get("platform_plan")
    if platform is not None:
        missing_sections = _platform_sections(platform["content"])
        if missing_sections:
            failures.append("platform_plan missing required/substantive sections: " + ", ".join(missing_sections))
            next_actions.append("Add concrete platform_plan sections: " + ", ".join(missing_sections))
    return failures, list(dict.fromkeys(next_actions))


def _chain_hash(db, goal_id: str) -> str:
    c = db.conn
    campaign = c.execute(
        "SELECT id, goal_id, topic, config_json, thresholds_json, manifest_sha256"
        " FROM research_campaign WHERE goal_id=?", (goal_id,)).fetchone()
    if not campaign:
        return sha256_text("research:none")
    sources = [dict(r) for r in c.execute(
        "SELECT id, goal_id, canonical_uri, title, source_type, content_sha256,"
        " verification_status, verifier, verification_method, verifier_provenance_json"
        " FROM research_source WHERE goal_id=? ORDER BY id", (goal_id,))]
    claims = [dict(r) for r in c.execute(
        "SELECT id, goal_id, text, claim_class FROM research_claim"
        " WHERE goal_id=? ORDER BY id", (goal_id,))]
    links = [dict(r) for r in c.execute(
        "SELECT claim_id, source_id, goal_id, relation FROM research_claim_source"
        " WHERE goal_id=? ORDER BY claim_id, source_id", (goal_id,))]
    artifacts = [dict(r) for r in c.execute(
        "SELECT id, goal_id, kind, artifact_name, version, content_sha256,"
        " storage_path, claim_refs_json, producer FROM research_artifact"
        " WHERE goal_id=? ORDER BY kind, version, id", (goal_id,))]
    # Stored hashes are immutable metadata, but the filesystem is an external
    # boundary.  Include the host-observed state so tampering, deletion, and
    # replacement produce a new chain identity on the next evaluation.
    for artifact in artifacts:
        path = Path(artifact["storage_path"])
        try:
            exists = path.is_file()
            actual_sha = _sha_bytes(path.read_bytes()) if exists else None
        except OSError:
            exists = False
            actual_sha = None
        artifact["host_file_exists"] = exists
        artifact["host_file_sha256"] = actual_sha
    artifact_claims = [dict(r) for r in c.execute(
        "SELECT artifact_id, claim_id, goal_id FROM research_artifact_claim"
        " WHERE goal_id=? ORDER BY artifact_id, claim_id", (goal_id,))]
    payload = {
        "campaign": dict(campaign),
        "sources": sources,
        "claims": claims,
        "claim_sources": links,
        "artifacts": artifacts,
        "artifact_claims": artifact_claims,
    }
    return sha256_text(canonical_json(payload))


def research_chain_hash(db, goal_id: str) -> str:
    """Return the recomputed canonical chain hash for a research goal."""
    return _chain_hash(db, goal_id)


def _persist_campaign(db, root: Path, topic: str, config: Mapping[str, Any], manifest: str,
                      normalized: Mapping[str, Any],
                      bundle_proposal: Mapping[str, Any] | None = None
                      ) -> tuple[str, list[dict[str, Any]]]:
    campaign_id = new_id("rcamp")
    engine = Engine(db, root)
    goal_id = engine.create_goal(
        topic,
        actor="research-planner",
        constraints={"research_workflow": "agentos.research.v1", "topic": topic},
    )
    engine.refine_spec(
        goal_id,
        "Bounded provider-neutral research-to-platform-plan workflow. "
        "External bundle values are untrusted data; deterministic checks govern completion.",
        criteria=[{"criterion_id": "research_deterministic", "kind": "invariant",
                    "params": {"workflow": "research-to-platform-plan"}}],
        actor="research-planner",
    )
    # Goal state-machine transitions intentionally allow only the existing
    # requester/system authorities; the workflow identity is retained in
    # journal payloads rather than widening that policy surface.
    engine.activate_goal(goal_id, actor="system")
    tasks: list[dict[str, Any]] = []
    previous: str | None = None
    for kind in FLOW:
        task: dict[str, Any] = {
            "key": kind,
            "title": kind,
            "definition_of_done": f"deterministic research artifact {kind} recorded",
            "expected_outputs": [kind],
            "inputs": {"workflow": "research-to-platform-plan"},
            "retry_budget": 0,
        }
        if previous:
            task["depends_on"] = [previous]
        tasks.append(task)
        previous = kind
    engine.plan_tasks(goal_id, tasks, actor="research-planner")

    persisted_config = dict(config)
    if bundle_proposal:
        # Keep the proposal auditable without allowing it to become authority.
        persisted_config["untrusted_bundle_proposal"] = dict(bundle_proposal)
    with db.tx() as c:
        c.execute(
            "INSERT INTO research_campaign(id, goal_id, topic, config_json,"
            " thresholds_json, manifest_sha256) VALUES (?,?,?,?,?,?)",
            (campaign_id, goal_id, topic, canonical_json(persisted_config),
             canonical_json({"min_source_count": config["min_source_count"],
                             "min_verified_ratio": config["min_verified_ratio"],
                             "required_artifacts": config["required_artifacts"]}),
             manifest),
        )
        c.execute(
            "INSERT INTO research_campaign_config(campaign_id, goal_id, topic,"
            " thresholds_json, manifest_sha256, config_json) VALUES (?,?,?,?,?,?)",
            (campaign_id, goal_id, topic,
             canonical_json({"min_source_count": config["min_source_count"],
                             "min_verified_ratio": config["min_verified_ratio"],
                             "required_artifacts": config["required_artifacts"]}),
             manifest, canonical_json(persisted_config)),
        )
        for source in normalized["sources"]:
            c.execute(
                "INSERT INTO research_source(id, campaign_id, goal_id,"
                " canonical_uri, title, source_type, content_sha256,"
                " verification_status, verifier, verification_method,"
                " verifier_provenance_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (source["id"], campaign_id, goal_id, source["canonical_uri"],
                 source["title"], source["source_type"], source["content_sha256"],
                 source["verification_status"], source["verifier"],
                 source["verification_method"], source["verifier_provenance_json"]),
            )
        for claim in normalized["claims"]:
            c.execute(
                "INSERT INTO research_claim(id, campaign_id, goal_id, text,"
                " claim_class) VALUES (?,?,?,?,?)",
                (claim["id"], campaign_id, goal_id, claim["text"], claim["claim_class"]),
            )
        for claim in normalized["claims"]:
            for source_id in claim["source_ids"]:
                c.execute(
                    "INSERT INTO research_claim_source(claim_id, source_id, goal_id, relation)"
                    " VALUES (?,?,?,'supports')", (claim["id"], source_id, goal_id))

        artifact_rows: list[dict[str, Any]] = []
        research_root = root / "goals" / goal_id / "research"
        research_root.mkdir(parents=True, exist_ok=True)
        for kind in FLOW:
            artifact = normalized["artifacts"].get(kind)
            if artifact is None:
                continue
            version = c.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM research_artifact"
                " WHERE goal_id=? AND kind=?", (goal_id, kind)).fetchone()[0]
            suffix = artifact["suffix"]
            path = research_root / f"{kind}-v{version}{suffix}"
            # The path is constructed solely from a fixed stage name and host
            # goal id; user-provided storage paths are never honored.
            path.write_bytes(artifact["bytes"])
            artifact_id = new_id("rart")
            claim_refs_json = canonical_json(artifact["claim_ids"])
            c.execute(
                "INSERT INTO research_artifact(id, campaign_id, goal_id, kind,"
                " artifact_name, version, content_sha256, storage_path,"
                " claim_refs_json, producer) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (artifact_id, campaign_id, goal_id, kind, kind, version,
                 artifact["content_sha256"], str(path), claim_refs_json,
                 artifact["producer"] or "system"),
            )
            for claim_id in artifact["claim_ids"]:
                c.execute(
                    "INSERT INTO research_artifact_claim(artifact_id, claim_id, goal_id)"
                    " VALUES (?,?,?)", (artifact_id, claim_id, goal_id))
            artifact_rows.append({
                "id": artifact_id, "kind": kind, "artifact_name": kind,
                "version": version, "content_sha256": artifact["content_sha256"],
                "storage_path": str(path), "claim_refs": list(artifact["claim_ids"]),
                "producer": artifact["producer"] or "system",
            })
    return goal_id, artifact_rows


def _store_evaluation(db, goal_id: str, result: str, failures: list[str],
                      limitations: Any, details: Mapping[str, Any]) -> dict[str, Any]:
    chain = _chain_hash(db, goal_id)
    campaign_id = db.conn.execute(
        "SELECT id FROM research_campaign WHERE goal_id=?", (goal_id,)).fetchone()[0]
    version = db.conn.execute(
        "SELECT COALESCE(MAX(evaluation_version),0)+1 FROM research_evaluation"
        " WHERE campaign_id=?", (campaign_id,)).fetchone()[0]
    limits = limitations if isinstance(limitations, (list, tuple)) else ([limitations] if _nonempty(limitations) else [])
    with db.tx() as c:
        evaluation_id = new_id("reval")
        c.execute(
            "INSERT INTO research_evaluation(id, campaign_id, goal_id,"
            " evaluation_version, result, artifact_chain_hash, reasons_json,"
            " limitations_json, details_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (evaluation_id, campaign_id, goal_id, version, result, chain,
             canonical_json(failures), canonical_json(list(limits)),
             canonical_json(dict(details))),
        )
    return {
        "id": evaluation_id,
        "campaign_id": campaign_id,
        "goal_id": goal_id,
        "evaluation_version": version,
        "result": result,
        "artifact_chain_hash": chain,
        "reasons": list(failures),
        "limitations": list(limits),
        "details": dict(details),
    }


def evaluate_research(db, goal_id: str) -> dict[str, Any]:
    """Re-evaluate persisted research state and append a deterministic result."""
    campaign = db.conn.execute(
        "SELECT thresholds_json FROM research_campaign WHERE goal_id=?", (goal_id,)).fetchone()
    if not campaign:
        raise ResearchValidationError(f"no research campaign for goal {goal_id}")
    config = json.loads(campaign[0])
    source_rows = [dict(r) for r in db.conn.execute(
        "SELECT * FROM research_source WHERE goal_id=? ORDER BY id", (goal_id,))]
    claim_rows = [dict(r) for r in db.conn.execute(
        "SELECT id,text,claim_class FROM research_claim WHERE goal_id=? ORDER BY id", (goal_id,))]
    links = [dict(r) for r in db.conn.execute(
        "SELECT claim_id, source_id, goal_id, relation FROM research_claim_source"
        " WHERE goal_id=?",
        (goal_id,))]
    artifact_rows = [dict(r) for r in db.conn.execute(
        "SELECT id,kind,version,content_sha256,storage_path,claim_refs_json,producer"
        " FROM research_artifact WHERE goal_id=? ORDER BY kind,version", (goal_id,))]
    normalized = {
        "sources": source_rows,
        "claims": [],
        "artifacts": {},
        "audit": {},
    }
    source_by_claim: dict[str, list[str]] = {}
    for link in links:
        if link.get("relation", "supports") == "supports":
            source_by_claim.setdefault(link["claim_id"], []).append(link["source_id"])
    for row in claim_rows:
        normalized["claims"].append({
            **row, "source_ids": source_by_claim.get(row["id"], []),
        })
    for row in artifact_rows:
        try:
            artifact_bytes = (Path(row["storage_path"]).read_bytes()
                              if Path(row["storage_path"]).is_file() else b"")
        except OSError:
            artifact_bytes = b""
        content = ""
        decode_error = False
        if row["kind"] == "platform_plan":
            try:
                content = artifact_bytes.decode("utf-8")
            except UnicodeDecodeError:
                decode_error = True
        normalized["artifacts"][row["kind"]] = {
            **row,
            "bytes": artifact_bytes,
            "content": content,
            "decode_error": decode_error,
            "claim_ids": json.loads(row["claim_refs_json"] or "[]"),
        }
    latest_audit = db.conn.execute(
        "SELECT details_json FROM research_evaluation WHERE goal_id=?"
        " ORDER BY evaluation_version DESC LIMIT 1", (goal_id,)).fetchone()
    if latest_audit:
        details = json.loads(latest_audit[0] or "{}")
        normalized["audit"] = details.get("audit", {})
    failures, actions = _evaluation_checks(normalized, config)
    result = (normalized["audit"].get("verdict")
              if not failures and normalized["audit"].get("verdict") == "pass_with_limits"
              else ("pass" if not failures else "fail"))
    evaluation = _store_evaluation(
        db, goal_id, result, failures, normalized["audit"].get("limitations", []),
        {"audit": normalized["audit"], "next_actions": actions},
    )
    return evaluation


def _attach_research_outputs(db, root: Path, goal_id: str,
                             result: Mapping[str, Any]) -> dict[str, Any]:
    """Build the durable human/machine projections for a persisted campaign.

    The research evaluation remains distinct from software release acceptance,
    but a successful one-command run is not complete until both its Obsidian
    projection and evidence pack are observable and internally consistent.
    """
    output = dict(result)
    output["next_actions"] = list(result.get("next_actions", []))
    try:
        # Local imports avoid a module cycle: evidence_pack lazily imports the
        # research chain verifier when it encounters a v3 campaign.
        from .evidence_pack import build as build_evidence
        from .wiki import WikiBuilder

        wiki = WikiBuilder(db, root)
        wiki_build = wiki.build()
        wiki_check = wiki.check()
        evidence = build_evidence(db, root, goal_id)
        research_pack = evidence["pack"].get("research", {})
        output["wiki"] = {"build": wiki_build, "check": wiki_check}
        output["evidence_pack"] = {
            "path": evidence["path"],
            "sha256": evidence["sha256"],
            "schema": evidence["pack"]["schema"],
            "chain_fresh": research_pack.get("chain_fresh", False),
            "latest_evaluation_valid": research_pack.get(
                "latest_evaluation_valid", False),
        }
        if not wiki_check["ok"]:
            output["status"] = "fail"
            output["summary"] = "research evaluation recorded but wiki projection failed"
            output["next_actions"].append(
                "Repair wiki projection issues before treating the run as operationally complete")
    except Exception as exc:  # projection/evidence boundary must fail closed
        output["status"] = "fail"
        output["summary"] = "research evaluation recorded but output emission failed"
        output["next_actions"].append(
            f"Repair research evidence/wiki emission: {type(exc).__name__}: {exc}")
    return output


def run_research_plan(db, root_dir: str | Path, topic: str,
                      bundle: Any = None, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Run one bounded research campaign and return a JSON-safe result.

    ``db`` may be an open :class:`agentos.db.Database`; callers needing a
    path-level API can use :func:`research_plan`, which owns the connection.
    """
    root = Path(root_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    topic_text = _as_text(topic).strip()
    topic_errors: list[str] = []
    if not topic_text:
        topic_errors.append("topic must be a non-empty string")
    if len(topic_text) > 5000:
        topic_errors.append("topic must be at most 5000 characters")
    if topic_errors:
        return {"status": "fail", "summary": "research input validation failed",
                "next_actions": topic_errors, "artifacts": []}
    loaded, load_errors, missing = _load_bundle(bundle)
    if missing:
        # A scaffold is useful for a caller preparing input, but it never
        # writes a completion evaluation and explicitly remains needs_input.
        loaded = {"sources": [], "claims": [], "artifacts": {}, "config": config or {}}
        config_norm, cfg_errors = _normalise_config(config, loaded)
        if cfg_errors:
            return {"status": "fail", "summary": "invalid research configuration",
                    "next_actions": cfg_errors, "artifacts": []}
        manifest, manifest_errors = _manifest_hash(loaded, config_norm)
        if manifest_errors:
            return {"status": "fail", "summary": "invalid research manifest",
                    "next_actions": manifest_errors, "artifacts": []}
        try:
            goal_id, artifact_rows = _persist_campaign(db, root, topic_text,
                                                       config_norm, manifest,
                                                       {"sources": [], "claims": [],
                                                        "artifacts": {}, "audit": {}},
                                                       _bundle_config_proposal(loaded))
        except Exception as exc:
            return {"status": "fail", "summary": "research scaffold failed",
                    "next_actions": [f"repair scaffold persistence: {exc}"],
                    "artifacts": []}
        return {
            "status": "needs_input",
            "summary": "research bundle is missing; scaffold created without claiming completion",
            "next_actions": ["Provide a structured offline research bundle JSON at --bundle"],
            "artifacts": artifact_rows,
            "goal_id": goal_id,
            "campaign_id": db.conn.execute(
                "SELECT id FROM research_campaign WHERE goal_id=?", (goal_id,)).fetchone()[0],
        }

    errors = list(load_errors)
    config_norm, config_errors = _normalise_config(config, loaded or {})
    errors.extend(config_errors)
    if errors:
        return {"status": "fail", "summary": "research input validation failed",
                "next_actions": list(dict.fromkeys(errors)), "artifacts": []}
    manifest, manifest_errors = _manifest_hash(loaded or {}, config_norm)
    errors.extend(manifest_errors)
    normalized, bundle_errors = _normalize_bundle(loaded or {}, config_norm)
    errors.extend(bundle_errors)
    if errors:
        return {"status": "fail", "summary": "research bundle validation failed",
                "next_actions": list(dict.fromkeys(errors)), "artifacts": []}

    try:
        goal_id, artifact_rows = _persist_campaign(
            db, root, topic_text, config_norm, manifest, normalized,
            _bundle_config_proposal(loaded or {}))
    except Exception as exc:
        return {"status": "fail", "summary": "research persistence failed",
                "next_actions": [f"repair research persistence: {type(exc).__name__}: {exc}"],
                "artifacts": []}

    failures, next_actions = _evaluation_checks(normalized, config_norm)
    result_kind = ("pass_with_limits"
                   if not failures and normalized["audit"].get("verdict") == "pass_with_limits"
                   else ("pass" if not failures else "fail"))
    evaluation = _store_evaluation(
        db, goal_id, result_kind, failures,
        normalized["audit"].get("limitations", []),
        {"audit": normalized["audit"], "config": dict(config_norm),
         "next_actions": next_actions},
    )
    artifacts = [dict(row) for row in artifact_rows]
    sources = [{k: s[k] for k in (
        "id", "canonical_uri", "title", "source_type", "content_sha256",
        "verification_status", "verifier", "verification_method")}
               for s in normalized["sources"]]
    claims = [{k: c[k] for k in ("id", "text", "claim_class", "source_ids")}
              for c in normalized["claims"]]
    campaign_id = evaluation["campaign_id"]
    result = {
        "status": evaluation["result"],
        "summary": ("deterministic research evaluation passed with limits"
                     if result_kind == "pass_with_limits" else
                     "deterministic research evaluation passed"
                     if not failures else
                     "deterministic research evaluation failed"),
        "next_actions": next_actions,
        "goal_id": goal_id,
        "campaign_id": campaign_id,
        "sources": sources,
        "claims": claims,
        "artifacts": artifacts,
        "evaluation": evaluation,
        "artifact_chain_hash": evaluation["artifact_chain_hash"],
        "goal_status": db.conn.execute(
            "SELECT status FROM goal WHERE id=?", (goal_id,)).fetchone()[0],
        "release_accepted": False,
        "thresholds": {
            "min_source_count": config_norm["min_source_count"],
            "min_verified_ratio": config_norm["min_verified_ratio"],
        },
    }
    return _attach_research_outputs(db, root, goal_id, result)


class ResearchPlanner:
    """Small object API for hosts that prefer dependency injection."""

    def __init__(self, db, root_dir: str | Path, config: Mapping[str, Any] | None = None):
        self.db = db
        self.root_dir = Path(root_dir)
        self.config = dict(config or {})

    def run(self, topic: str, bundle: Any = None,
            config: Mapping[str, Any] | None = None) -> dict[str, Any]:
        merged = dict(self.config)
        if config:
            merged.update(dict(config))
        return run_research_plan(self.db, self.root_dir, topic, bundle,
                                 merged if merged else None)

    plan = run


ResearchWorkflow = ResearchPlanner


def research_plan(topic: str, bundle: Any = None, *, db=None,
                  db_path: str | Path | None = None,
                  root_dir: str | Path | None = None,
                  config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Path-level convenience API usable without invoking the CLI."""
    owned = None
    if db is None:
        from .db import open_db
        root = Path(root_dir or db_path or ".agentos-research").resolve()
        db_file = root / "agentos.db"
        owned = open_db(db_file)
        db = owned
    else:
        root = Path(root_dir or getattr(db, "path", ".")).resolve()
        if root.suffix:
            root = root.parent
    try:
        return run_research_plan(db, root, topic, bundle, config)
    finally:
        if owned is not None:
            owned.conn.close()


def fixture_bundle(topic: str = "offline fixture") -> dict[str, Any]:
    """Return a deterministic offline drill bundle; this is not live research."""
    sources = []
    for i in range(3):
        content = f"Offline fixture source {i + 1} for {topic}."
        sources.append({
            "id": f"fixture-source-{i + 1}",
            "canonical_uri": f"https://offline.example.test/{i + 1}",
            "title": f"Offline fixture source {i + 1}",
            "source_type": "fixture",
            "content": content,
            "verification_status": "verified",
            "verifier": "offline-fixture-verifier",
            "verification_method": "deterministic-fixture-check",
        })
    claims = [
        {"id": "fixture-fact", "text": "The fixture has three sources.",
         "claim_class": "fact", "source_ids": ["fixture-source-1"]},
        {"id": "fixture-inference", "text": "The source set is internally coherent.",
         "claim_class": "inference", "source_ids": ["fixture-source-2"]},
        {"id": "fixture-assumption", "text": "The deployment team can review changes.",
         "claim_class": "assumption"},
        {"id": "fixture-target", "text": "Produce a verified platform plan.",
         "claim_class": "target"},
    ]
    artifacts: dict[str, Any] = {}
    for kind in FLOW:
        if kind == "platform_plan":
            content = "\n".join(
                [f"# {section}\nConcrete offline fixture entry for {section}."
                 for section in PLATFORM_SECTIONS])
        elif kind == "independent_audit":
            content = "# Independent audit\nPass with no live retrieval claims."
        else:
            content = f"# {kind}\nOffline fixture artifact for {topic}."
        artifacts[kind] = {
            "content": content,
            "claim_refs": ["fixture-fact", "fixture-target"],
            "producer": ("offline-fixture-subject" if kind == "platform_plan"
                          else "offline-fixture-auditor" if kind == "independent_audit"
                          else "offline-fixture-producer"),
        }
    return {
        "config": {"min_source_count": 3, "min_verified_ratio": 1.0,
                   "required_artifacts": list(FLOW)},
        "sources": sources,
        "claims": claims,
        "artifacts": artifacts,
        "audit": {"producer": "offline-fixture-subject",
                   "auditor": "offline-fixture-auditor", "verdict": "pass",
                   "limitations": []},
        "fixture_notice": "offline deterministic drill; not real research",
    }


offline_fixture_bundle = fixture_bundle
build_offline_fixture_bundle = fixture_bundle


__all__ = [
    "FLOW", "PLATFORM_SECTIONS", "MAX_BUNDLE_FILE_BYTES", "MAX_SOURCES",
    "MAX_CLAIMS", "MAX_BODY_BYTES", "MAX_URI_CHARS",
    "MAX_SOURCE_TITLE_CHARS", "MAX_SOURCE_TYPE_CHARS", "MAX_CLAIM_TEXT_CHARS",
    "ResearchValidationError", "evaluate_research",
    "ResearchPlanner", "ResearchWorkflow", "research_chain_hash", "research_plan",
    "run_research_plan", "fixture_bundle",
    "offline_fixture_bundle", "build_offline_fixture_bundle",
]
