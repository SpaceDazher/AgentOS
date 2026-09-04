"""Strict, offline contract checks shared by the preparation tools.

This is a validator for the explicitly used JSON Schema subset, not a general
JSON Schema engine. Unsupported validation keywords fail closed.
"""
import hashlib
import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


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
    return json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite)


def load(name):
    return loads((HERE / name).read_text(encoding="utf-8"))


def validate(value, schema, path="record"):
    annotations = {"$id", "$schema", "title", "description", "default"}
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


PII = re.compile(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:passport|ssn|consent_text)\b|"
                 r"\b(?:sk-proj-|ghp_)[A-Za-z0-9_-]{12,}", re.I)
PRIVATE_KEYS = {"contact", "email", "phone", "full_name", "consent_text", "address"}


def has_private(value):
    if isinstance(value, dict):
        return any(k.lower() in PRIVATE_KEYS or has_private(v) for k, v in value.items())
    if isinstance(value, list):
        return any(has_private(v) for v in value)
    return isinstance(value, str) and bool(PII.search(value))
