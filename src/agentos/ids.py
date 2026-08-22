"""Canonical id helpers: prefixed, sortable, unique."""
from __future__ import annotations

import os
import time

_ALPH = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32 (no I,L,O,U)


def _ulid() -> str:
    ts = int(time.time() * 1000)
    out = []
    for _ in range(10):
        out.append(_ALPH[ts % 32])
        ts //= 32
    entropy = os.urandom(16)
    for i in range(16):
        out.append(_ALPH[entropy[i] % 32])
    return "".join(reversed(out))


def new_id(kind: str) -> str:
    """kind in {goal, artifact, task, run, activity, evaluation, gate, approval,
    checkpoint, claim, evidence, decision, memory, relation, event, world}"""
    return f"{kind}_{_ulid()}"


def canonical_json(obj) -> str:
    import json
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
