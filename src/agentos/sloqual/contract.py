"""SLO contract freeze/verify. The contract is frozen BEFORE any measurement.

self_hash_sha256 = SHA-256 over the canonical JSON (sorted keys, compact
separators) of the contract object with the `self_hash_sha256` key removed.
`frozen_at_placeholder` is replaced by the real UTC timestamp at freeze time;
afterwards any content change changes the hash and invalidates old runs.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_KEYS = (
    "schema", "slo_id", "version", "extends", "mandatory_scenarios",
    "sli_definitions", "invariants", "slos", "sampling",
    "confidence_intervals", "verdict_rules", "change_policy",
)


def canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_self_hash(contract: dict) -> str:
    payload = {k: v for k, v in contract.items() if k != "self_hash_sha256"}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def load_contract(path: str | Path) -> dict:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise ValueError("slo contract must be a JSON object")
    missing = [k for k in REQUIRED_KEYS if k not in contract]
    if missing:
        raise ValueError(f"slo contract missing required keys: {missing}")
    return contract


def freeze_contract(path: str | Path, *, timestamp: str | None = None) -> str:
    """Replace the placeholder timestamp and stamp the self-hash. Idempotent
    only in the sense that re-freezing unchanged content keeps the hash stable
    only if the timestamp is passed explicitly."""
    contract = load_contract(path)
    if "self_hash_sha256" in contract:
        raise ValueError("contract is already frozen; copy to a new version instead")
    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    contract["frozen_at"] = stamp
    contract.pop("frozen_at_placeholder", None)
    contract["self_hash_sha256"] = compute_self_hash(contract)
    Path(path).write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    return contract["self_hash_sha256"]


class ContractViolation(ValueError):
    pass


def verify_frozen(path: str | Path) -> tuple[dict, str]:
    """Fail-closed verification used before every run and by the comparator."""
    contract = load_contract(path)
    stamped = contract.get("self_hash_sha256")
    if not stamped:
        raise ContractViolation("contract has no self_hash_sha256 (never frozen)")
    actual = compute_self_hash(contract)
    if actual != stamped:
        raise ContractViolation(
            f"contract self-hash mismatch: stamped {stamped} != computed {actual}")
    if contract.get("frozen_at_placeholder") or "frozen_at" not in contract:
        raise ContractViolation("contract was never frozen (placeholder remains)")
    return contract, stamped
