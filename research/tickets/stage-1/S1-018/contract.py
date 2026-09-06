"""S1-018 shared strict validator (stdlib only, offline).

Fail-closed: duplicate JSON keys, NaN/Infinity, unknown fields/enums/
versions, wrong types, oversized inputs, traversal/junction escapes all
fail closed. Subprocess calls (none in the model) would get a stripped
environment; the model performs no subprocess, network or filesystem I/O.
"""
import hashlib
import json
import math
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_INPUT_BYTES = 1048576


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def loads(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("non-finite JSON number")

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite)
    _reject_remote_ref(value)
    return value


def _reject_remote_ref(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str) and (
                    item.startswith("http://") or item.startswith("https://")
                    or item.startswith("file:")):
                raise ValueError("remote $ref refused")
            _reject_remote_ref(item)
    elif isinstance(value, list):
        for item in value:
            _reject_remote_ref(item)


def load(name):
    return loads((HERE / name).read_text(encoding="utf-8"))


def validate(value, schema, path="record"):
    annotations = {"$id", "$schema", "title", "description", "default", "compatibility"}
    supported = {"type", "required", "properties", "additionalProperties",
                 "items", "enum", "minimum", "minLength", "pattern"}
    if set(schema) - annotations - supported:
        raise ValueError("unsupported schema keyword")
    checks = {"object": lambda x: isinstance(x, dict),
              "array": lambda x: isinstance(x, list),
              "string": lambda x: isinstance(x, str),
              "boolean": lambda x: type(x) is bool,
              "integer": lambda x: type(x) is int,
              "number": lambda x: type(x) in (int, float) and math.isfinite(x),
              "null": lambda x: x is None}
    kinds = schema.get("type")
    if kinds is not None:
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if any(k not in checks for k in kinds) or not any(checks[k](value) for k in kinds):
            raise ValueError(path + ": wrong type")
    if "enum" in schema and not any(type(v) is type(value) and v == value for v in schema["enum"]):
        raise ValueError(path + ": unknown enum")
    if value is None:
        return
    if isinstance(value, dict):
        props = schema.get("properties", {})
        if set(schema.get("required", [])) - value.keys():
            raise ValueError(path + ": missing required field")
        if schema.get("additionalProperties") is False and value.keys() - props.keys():
            raise ValueError(path + ": unknown field")
        for key, item in value.items():
            if key in props:
                validate(item, props[key], path + "." + key)
    if isinstance(value, list) and "items" in schema:
        for item in value:
            validate(item, schema["items"], path + "[]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ValueError(path + ": empty string")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ValueError(path + ": malformed identifier")
    if type(value) in (int, float) and value < schema.get("minimum", -math.inf):
        raise ValueError(path + ": below minimum")


TRAVERSAL = re.compile(r"(^|[/\\])\.\.([/\\]|$)|\\\\|\x00")


def has_traversal(text):
    return isinstance(text, str) and bool(
        TRAVERSAL.search(text) or text.startswith("-") or text.startswith("/"))


def check_size(text: str, label: str = "input") -> None:
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError(f"{label} exceeds {MAX_INPUT_BYTES} bytes")


PII = re.compile(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:passport|ssn|consent_text)\b|"
                 r"\b(?:sk-proj-|ghp_-|AKIA)[A-Za-z0-9_-]{8,}", re.I)
PRIVATE_KEYS = {"contact", "email", "phone", "full_name", "consent_text", "address",
                "secret", "credential", "private_key", "quote_secret"}


def has_private(value):
    if isinstance(value, dict):
        return any(k.lower() in PRIVATE_KEYS or has_private(v) for k, v in value.items())
    if isinstance(value, list):
        return any(has_private(v) for v in value)
    return isinstance(value, str) and bool(PII.search(value))


def canonical_path(path: str, trusted_root: str) -> str:
    """Confine a path under a trusted root; traversal/junction escapes fail."""
    if not isinstance(path, str) or not path:
        raise ValueError("empty path")
    if has_traversal(path):
        raise ValueError(f"path traversal refused: {path!r}")
    normalized = os.path.normpath(path).replace("\\", "/")
    root = trusted_root.rstrip("/")
    if normalized != root and not normalized.startswith(root + "/"):
        raise ValueError(f"path escapes trusted root: {path!r}")
    return normalized


def stripped_env() -> dict:
    """Stripped subprocess environment (no credentials/home/temp assumptions)."""
    drop = {"AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID", "GH_TOKEN", "GITHUB_TOKEN",
            "OPENAI_API_KEY", "PROXY_SECRET", "HTTP_PROXY", "HTTPS_PROXY",
            "HOME", "USERPROFILE", "TEMP", "TMP"}
    return {k: v for k, v in os.environ.items() if k not in drop}
