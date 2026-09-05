"""S1-015 authoritative display-envelope contract (shared by UI, fixtures, importer, evaluator).

Strict offline validator for the explicitly used JSON Schema subset (same
discipline as S1-013 contract.py): unsupported keywords fail closed, unknown
fields/versions/enums fail closed, duplicate JSON keys and NaN/Infinity fail
closed, remote $ref is refused, traversal in identity fields fails closed.
"""
import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_NAME = "display_schema.json"
SCHEMA_VERSION = "s1-015.display-envelope/v1"
NO_AUTHORITY = "petname-display-only-no-authority"


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


TRAVERSAL = re.compile(r"(^|/)\.\.(/|$)|\\\\|\x00")


def _has_traversal(text):
    return isinstance(text, str) and bool(
        TRAVERSAL.search(text) or text.startswith("-") or text.startswith("/"))


def normalize_petname(label):
    """NFC + casefold + trim + single-space collapse for comparison only."""
    if label is None:
        return None
    if not isinstance(label, str):
        raise ValueError("petname must be a string or null")
    collapsed = re.sub(r"\s+", " ", unicodedata.normalize("NFC", label).strip())
    return collapsed.casefold()


_CYRILLIC_LOOKALIKES = {
    "а": "a", "с": "c", "е": "e", "ё": "e", "һ": "h", "і": "i", "ј": "j",
    "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "ѕ": "s", "т": "t",
    "х": "x", "у": "y",
    "А": "a", "В": "b", "С": "c", "Е": "e", "Ё": "e", "Н": "h", "І": "i",
    "Ј": "j", "К": "k", "М": "m", "О": "o", "Р": "p", "Ѕ": "s", "Т": "t",
    "Х": "x", "Ү": "y",
}
_GREEK_LOOKALIKES = {
    "α": "a", "β": "b", "ε": "e", "η": "n", "ι": "i", "κ": "k", "μ": "m",
    "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "ζ": "z",
    "Α": "a", "Β": "b", "Ε": "e", "Η": "n", "Ι": "i", "Κ": "k", "Μ": "m",
    "Ν": "n", "Ο": "o", "Ρ": "p", "Τ": "t", "Υ": "u", "Χ": "x", "Ζ": "z",
}
BIDI_CONTROLS = set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u200e\u200f")
INVISIBLE = set("\u200b\u200c\u200d\ufeff\u00ad")
MARKUP_CHARS = set("<>&")


def _scripts(label):
    scripts = set()
    for char in label:
        code = ord(char)
        if 0x41 <= code <= 0x7A or char.isascii() and char.isalpha():
            scripts.add("latin")
        elif 0x400 <= code <= 0x4FF:
            scripts.add("cyrillic")
        elif 0x370 <= code <= 0x3FF:
            scripts.add("greek")
        elif 0x590 <= code <= 0x5FF:
            scripts.add("hebrew")
        elif 0x600 <= code <= 0x6FF:
            scripts.add("arabic")
        elif 0x4E00 <= code <= 0x9FFF or 0x3040 <= code <= 0x30FF:
            scripts.add("cjk")
        elif char.isalpha():
            scripts.add("other-alpha")
    return scripts


def skeleton(label):
    out = []
    for char in unicodedata.normalize("NFC", label):
        if char in _CYRILLIC_LOOKALIKES:
            out.append(_CYRILLIC_LOOKALIKES[char])
        elif char in _GREEK_LOOKALIKES:
            out.append(_GREEK_LOOKALIKES[char])
        else:
            out.append(char.casefold())
    return "".join(out)


def detect_confusable(label):
    """Return (flag, reason) for a petname label. Never raises on str input."""
    if label is None:
        return False, None
    if not isinstance(label, str):
        raise ValueError("petname must be a string or null")
    if any(c in BIDI_CONTROLS for c in label):
        return True, "bidi-control"
    if any(c in INVISIBLE for c in label):
        return True, "invisible-char"
    if _scripts(label) - {"latin"} and "latin" in _scripts(label):
        return True, "mixed-script"
    if _scripts(label) == {"cyrillic"} or _scripts(label) == {"greek"}:
        # Single non-latin script is valid (see BEN non-Latin case); only flag
        # when the skeleton collides with a latin word is decided by the
        # corpus collision index, not here. Still record script for cues.
        return False, None
    nfc = unicodedata.normalize("NFC", label)
    nfkc = unicodedata.normalize("NFKC", label)
    if nfc != nfkc:
        return True, "normalization-collision"
    if any(c in _CYRILLIC_LOOKALIKES or c in _GREEK_LOOKALIKES for c in label):
        return True, "confusable-skeleton"
    return False, None


def has_markup(label):
    if not isinstance(label, str):
        return False
    low = label.lower()
    return ("<" in label and ">" in label) or any(
        token in low for token in ("javascript:", "onerror", "onload", "onclick", "<script"))


PII = re.compile(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:passport|ssn|consent_text)\b|"
                 r"\b(?:sk-proj-|ghp_)[A-Za-z0-9_-]{12,}", re.I)
PRIVATE_KEYS = {"contact", "email", "phone", "full_name", "consent_text", "address"}


def has_private(value):
    if isinstance(value, dict):
        return any(k.lower() in PRIVATE_KEYS or has_private(v) for k, v in value.items())
    if isinstance(value, list):
        return any(has_private(v) for v in value)
    return isinstance(value, str) and bool(PII.search(value))


def validate_envelope(envelope):
    """Full fail-closed envelope validation incl. cross-field identity rules."""
    schema = load(SCHEMA_NAME)
    validate(envelope, schema)
    if envelope.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unknown schema version")
    if envelope.get("no_authority") != NO_AUTHORITY:
        raise ValueError("no-authority declaration missing")
    for key in ("principal_id", "scope", "tenant", "petname_owner_id"):
        if _has_traversal(envelope.get(key)):
            raise ValueError(f"traversal in {key}")
    principal_id = envelope["principal_id"]
    if envelope["principal_id"] not in envelope["canonical_display"]:
        raise ValueError("canonical_display must contain the canonical principal ID")
    if principal_id not in envelope["accessibility_text"]:
        raise ValueError("accessibility_text must contain the canonical principal ID")
    if envelope["scope"] not in envelope["accessibility_text"] and \
            envelope["tenant"] not in envelope["accessibility_text"]:
        raise ValueError("accessibility_text must carry scope/tenant")
    approval = envelope["approval"]
    # The authoritative approval target is canonical: it must never be the
    # petname and must resolve to the envelope principal (or its scope root).
    petname = envelope.get("petname")
    if petname and approval.get("target") == petname:
        raise ValueError("approval target must be canonical, never the petname")
    if approval.get("target") != principal_id and approval.get("target") != envelope["scope"]:
        # On-behalf and scope-level approvals may target the scope root; any
        # other free-form target (e.g. a petname or foreign ID) fails closed.
        raise ValueError("approval target is not bound to this envelope principal")
    if approval.get("actor") != principal_id and (
            envelope.get("on_behalf") is None or
            approval.get("actor") not in (envelope["on_behalf"].get("actor"),
                                          envelope["on_behalf"].get("beneficiary"))):
        # Actor must be the principal or a declared on-behalf party; anything
        # else is a forged binding.
        raise ValueError("approval actor is not bound to this envelope")
    candidates = envelope.get("candidates", [])
    if envelope["ambiguity"] and not candidates:
        raise ValueError("ambiguous envelope must list candidates")
    if envelope["ambiguity"] and all(
            c.get("principal_id") != principal_id for c in candidates):
        raise ValueError("ambiguous envelope must include the viewed principal")
    collision_like = len(candidates) > 1
    if collision_like and len(candidates) < 2:
        raise ValueError("collision envelope must list >=2 candidates")
    if not envelope["ambiguity"] and any(
            c.get("principal_id") != principal_id for c in envelope.get("candidates", [])):
        raise ValueError("unambiguous envelope lists foreign candidates")
    expected_norm = normalize_petname(petname)
    if envelope.get("petname_normalized") != expected_norm:
        raise ValueError("petname_normalized mismatch")
    flag, _ = detect_confusable(petname) if petname else (False, None)
    if has_markup(petname or ""):
        flag = True
    if flag != envelope.get("confusable_flag") and not (
            envelope.get("confusable_flag") is True):
        # A missed detection fails closed; an extra caution flag is allowed
        # (evaluator recomputes the exact expectation per case).
        raise ValueError("confusable_flag mismatch")
    return True
