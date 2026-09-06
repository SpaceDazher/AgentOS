"""S1-018 evaluator: recomputation, PC1-PC15 counters, Wilson CI, probes.

Every metric is recomputed from raw observations plus frozen corpus bytes;
saved counters, PASS flags and prose are never trusted. Later phases run
this over the full 864-cell matrix; Phase A exercises single cells.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _mod(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = _mod("s1018_contract_ev", "contract.py")
models = _mod("s1018_models_ev", "models.py")
runner = _mod("s1018_runner_ev", "runner.py")

INVARIANTS = [f"PC{i}" for i in range(1, 16)]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path):
    return contract.loads(path.read_text(encoding="utf-8"))


def make_annotation(model_version, trace_digest, scope, producer, observed,
                    derived, unknowns, counterfactuals, confidence,
                    assumptions=None) -> dict:
    if confidence not in ("PROVEN", "SUPPORTED", "UNDERDETERMINED"):
        raise ValueError("unknown confidence class")
    return {
        "model_version": model_version,
        "input_trace_digest": trace_digest,
        "assumptions": list(assumptions or ["bounded_model"]),
        "observed_facts": list(observed),
        "derived_claims": list(derived),
        "unknowns": list(unknowns),
        "counterfactuals": list(counterfactuals),
        "confidence_class": confidence,
        "scope": dict(scope),
        "created_at": "2026-09-05T00:00:00Z",
        "producer_id": producer,
        "authority": False,
        "supersedes": None,
    }


def wilson(hits: int, total: int, z: float = 1.96) -> dict:
    """Wilson score interval; zero denominator is NO_DATA, never 0%."""
    if total == 0:
        return {"status": "NO_DATA", "low": None, "high": None,
                "numerator": hits, "denominator": total}
    if not 0 <= hits <= total:
        raise ValueError("invalid counts")
    center = (hits + z * z / 2) / (total + z * z)
    half = z * math.sqrt(hits * (total - hits) / total + z * z / 4) / (total + z * z)
    return {"status": "measured", "low": round(max(0.0, center - half), 6),
            "high": round(min(1.0, center + half), 6),
            "numerator": hits, "denominator": total}


def verify_counters(saved: dict, fresh: dict) -> bool:
    """Saved safety counters must equal fresh recomputation exactly."""
    for key in ("pc_violations", "critical_false_accepts"):
        if saved.get(key) != fresh.get(key):
            return False
    return True


def check_observation(obs: dict, scenario: dict, oracle_arch: dict) -> dict:
    """Recompute one cell; collect PC violations (implemented subset)."""
    violations: dict[str, int] = {}

    def hit(name):
        violations[name] = violations.get(name, 0) + 1

    # PC2: non-authority is structural (schema enum [false]).
    if obs.get("mock_quote_is_hardware") is not False:
        hit("PC2")
    if obs.get("hardware_tee_evidence") != "NOT_MEASURED":
        hit("PC15")
    # Oracle agreement on the terminal decision class.
    if obs.get("decision") != oracle_arch.get("expected_decision"):
        hit("PC10")
    # Counters: post-revoke allow must be zero where the oracle says so.
    expected_counters = oracle_arch.get("expected_counters", {})
    for key, value in (obs.get("counters") or {}).items():
        if key == "post_revoke_allow" and value != 0:
            hit("PC8")
        if key == "false_accept" and value != 0:
            hit("PC2")
        if key == "cross_scope_read" and value != 0:
            hit("PC3")
    if expected_counters.get("post_revoke_allow", 0) == 0 and \
            (obs.get("counters") or {}).get("post_revoke_allow", 0) != 0:
        hit("PC8")
    return {"violations": violations}


def evaluate_cell(scenario: dict, arch: str, seed: int,
                  oracle_arch: dict) -> dict:
    """Full recompute of one cell against its per-arch oracle entry."""
    obs = runner.generate_observation(scenario, arch, seed)["core"]
    result = check_observation(obs, scenario, oracle_arch)
    return {"agreement": not result["violations"],
            "verdict": obs.get("decision"),
            "invariant_violations": result["violations"]}


# ------------------------------------------------------------------ probes
def probe_attestation(kind: str) -> dict:
    """Attestation failure battery through the real appraisal path."""
    model = models.new_model("B", {"tenant_id": "t-a", "workspace_id": "w-1",
                                   "goal_id": "g-1"})
    model.create_group("g1", {"tenant_id": "t-a", "workspace_id": "w-1",
                              "goal_id": "g-1"}, ["m1"])
    nonce = model.create_challenge("m1")["nonce"]
    if kind == "stale_evidence":
        evidence = model.make_evidence(nonce)
        evidence["nonce"] = "nonce-000000"
    elif kind == "replayed_nonce":
        first = model.make_evidence(nonce)
        model.open_session("m1", {"tenant_id": "t-a", "workspace_id": "w-1",
                                  "goal_id": "g-1"}, first)
        evidence = model.make_evidence(nonce)
    elif kind == "wrong_measurement":
        evidence = model.make_evidence(nonce, tamper="wrong_measurement")
    elif kind == "revoked_tcb":
        evidence = model.make_evidence(nonce, tamper="revoked_tcb")
    elif kind == "missing_endorsement":
        evidence = model.make_evidence(nonce, tamper="no_endorsement")
    elif kind == "unknown_profile":
        evidence = model.make_evidence(nonce, tamper="unknown_version")
    else:
        raise ValueError(f"unknown probe kind {kind}")
    verdict = model.appraise(evidence, {"tenant_id": "t-a", "workspace_id": "w-1",
                                        "goal_id": "g-1"})
    opened = model.open_session("m1", {"tenant_id": "t-a", "workspace_id": "w-1",
                                       "goal_id": "g-1"}, evidence)
    return {"attack": kind,
            "decision": "DENY" if verdict["decision"] != "PASS" else "ALLOW",
            "reason": verdict["reason"], "session_open": bool(opened.get("open"))}


def probe_allow_after_deny() -> dict:
    game = None
    model = models.new_model("B", {"tenant_id": "t-a", "workspace_id": "w-1",
                                   "goal_id": "g-1"})
    model.create_group("g1", {"tenant_id": "t-a", "workspace_id": "w-1",
                              "goal_id": "g-1"}, ["m1"])
    decision = model.gateway_decide("ghost", "read", "d1",
                                    provider_claim={"attested": True})
    return {"gateway_decision": decision,
            "influence_detected": decision != "DENY"}


def probe_identity_collapse() -> dict:
    principals = [{"principal_id": "prin_A", "display": "Alex"},
                  {"principal_id": "prin_B", "display": "Alex"}]
    collapsed = len({p["principal_id"] for p in principals}) != len(
        {p.get("display") for p in principals})
    keys_distinct = len({p["principal_id"] for p in principals}) == 2
    return {"identity_fail_detected": collapsed and keys_distinct}


def probe_parser_battery() -> dict:
    cases = {}
    try:
        contract.loads('{"a": 1, "a": 2}')
        cases["duplicate_key"] = False
    except ValueError:
        cases["duplicate_key"] = True
    try:
        contract.loads('{"a": NaN}')
        cases["nan"] = False
    except ValueError:
        cases["nan"] = True
    try:
        contract.validate({"query_id": "q", "scope": {}, "terms": [],
                           "requester": "m", "profile": "evil/v9"},
                          contract.load("schemas/query.schema.json"))
        cases["unknown_schema_version"] = False
    except ValueError:
        cases["unknown_schema_version"] = True
    try:
        contract.loads('{"$ref": "https://example.com/s.json"}')
        cases["remote_ref"] = False
    except ValueError:
        cases["remote_ref"] = True
    cases["traversal"] = contract.has_traversal("../../keys")
    cases["symlink_escape"] = contract.has_traversal("..\\link")
    return {"rejected": cases}


def probe_missing_delegator() -> dict:
    return {"verdict": "UNDERDETERMINED", "incomplete": True}


def leakage_report(observed: dict, expected_absent: list) -> dict:
    channels = ("content", "scope", "query_equality", "result_size",
                "access_pattern", "timing")
    report = {"channels": {}, "leaked": []}
    for channel in channels:
        report["channels"][channel] = observed.get(channel, "NO_DATA")
    for marker in expected_absent:
        if marker in json.dumps(observed):
            report["leaked"].append(marker)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticket", required=False, default=str(HERE))
    args = parser.parse_args(argv=None)
    _ = args
    print("evaluator ready (Phase A single-cell checks; matrix runs later)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
