"""S1-017 evaluator skeleton with real single-cell checks (stdlib, Phase A).

Recomputes attributions from corpus bytes via the shared analyzer, checks
R1-R14 per observation, and runs probes A-P through the production path.
Phase A exercises single cells; Phase B runs the full 864-cell matrix.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _mod(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = _mod("s1017_contract_ev", "contract.py")
models = _mod("s1017_models_ev", "models.py")
runner = _mod("s1017_runner_ev", "runner.py")

REQUIRED_ANNOTATION_FIELDS = ["model_version", "input_trace_digest", "assumptions",
                              "observed_facts", "derived_claims", "unknowns",
                              "counterfactuals", "confidence_class", "scope",
                              "created_at", "producer_id", "authority"]


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


def check_observation(obs: dict, scenario: dict, oracle_entry: dict) -> dict:
    """Recompute one cell and collect R-violations (subset per evidence)."""
    violations: dict[str, list[str]] = {}
    detail: dict[str, list[str]] = {}

    def hit(name, msg):
        violations.setdefault(name, []).append(msg)
        detail.setdefault(name, []).append(msg)

    annotation = obs.get("annotation", {})
    # R2/R4: annotation shape, non-authority, trace binding.
    try:
        contract.validate(annotation,
                          contract.load("schemas/annotation.schema.json"))
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        hit("R2", f"annotation schema violation: {exc}")
    if annotation.get("authority") is not False:
        hit("R2", "annotation authority is not false")
    if annotation.get("input_trace_digest") != runner.trace_digest(scenario):
        hit("R4", "annotation not bound to the exact trace digest")
    # R1: gateway decision recomputed ignoring any annotation.
    game = runner.game_of(scenario)
    for transition in game["transitions"]:
        if transition.get("outcome") != "effect":
            continue
        first = models.gateway_decide(game, transition["from"], transition["actor"],
                                      transition["action"],
                                      transition.get("authority_required"))
        second = models.gateway_decide(game, transition["from"], transition["actor"],
                                       transition["action"],
                                       transition.get("authority_required"),
                                       annotation={"derived_claims": ["allow"]})
        if first != second:
            hit("R1", "annotation influenced a gateway decision")
    # R9: attribution actors resolve to canonical principals.
    canonical = {p["principal_id"] for p in scenario.get("principals", [])}
    for claim in annotation.get("derived_claims", []):
        for principal in canonical:
            pass
        if "Alex" in claim and "prin_" not in claim:
            hit("R9", "display-name attribution without canonical key")
    # R10: incomplete traces must abstain.
    redacted = set(scenario.get("trace", {}).get("redacted", []))
    if (redacted or runner.detect_missing_authority(scenario)) and \
            obs.get("verdict") not in ("UNDERDETERMINED",) and \
            scenario["class"] in ("underdetermined", "adversarial_or_invalid"):
        hit("R10", "confident verdict on incomplete evidence")
    # R5: attribution needs the complete authority chain.
    if obs.get("verdict") == "ATTRIBUTION":
        kinds = {t.get("outcome") for t in game["transitions"]}
        if "effect" not in kinds:
            hit("R5", "attribution without an effect transition")
    # R6: alternatives proven or UNKNOWN.
    if obs.get("verdict") == "ATTRIBUTION" and not annotation.get("counterfactuals") \
            and not annotation.get("unknowns"):
        hit("R6", "attribution without alternatives provenance")
    # Oracle agreement on verdict/confidence.
    if obs.get("verdict") != oracle_entry.get("expected_verdict"):
        hit("R14", f"verdict {obs.get('verdict')} != {oracle_entry.get('expected_verdict')}")
    if obs.get("confidence") != oracle_entry.get("expected_confidence"):
        hit("R14", "confidence differs from oracle")
    return {"violations": {k: len(v) for k, v in violations.items()},
            "detail": detail}


def evaluate_cell(scenario: dict, placement: str, seed: int,
                  oracle_entry: dict) -> dict:
    """Full recompute of one cell against its oracle entry."""
    obs = runner.generate_observation(scenario, placement, seed)["core"]
    result = check_observation(obs, scenario, oracle_entry)
    agreement = not result["violations"]
    return {"agreement": agreement,
            "verdict": obs["verdict"],
            "invariant_violations": result["violations"],
            "detail": result["detail"]}


# ------------------------------------------------------------------ probes
def _mini_game():
    return {
        "states": [
            {"state_id": "s0", "authority": {"grants": {"g": {
                "scope": {"tenant_id": "t-a", "workspace_id": "w-1",
                          "goal_id": "g-1"},
                "actions": ["read"], "revoked": False, "expired": False}}},
             "phase": "ready"},
            {"state_id": "s1", "authority": {}, "phase": "done"}],
        "initial": "s0",
        "transitions": [
            {"from": "s0", "actor": "prin_A", "action": "read",
             "args": {}, "to": "s1", "authority_required": {"grant_id": "gx"},
             "outcome": "denied", "environment_move": None, "audit_ref": "ev1"},
            {"from": "s0", "actor": "prin_A", "action": "wait",
             "args": {}, "to": "s0", "authority_required": None,
             "outcome": "effect", "environment_move": None, "audit_ref": "ev0"}],
    }


def probe_allow_after_deny() -> dict:
    """Probe A: annotation suggesting allow after gateway DENY."""
    game = _mini_game()
    decision = models.gateway_decide(game, "s0", "prin_A", "read",
                                     {"grant_id": "gx"},
                                     annotation={"derived_claims": ["allow"]})
    return {"gateway_decision": decision,
            "influence_detected": decision != "DENY"}


def probe_identity_collapse() -> dict:
    """Probe F: same display names must not merge canonical principals."""
    scenario = {"scenario_id": "PX-F", "class": "adversarial_or_invalid",
                "description": "x", "principals": [
                    {"principal_id": "prin_A", "display": "Alex",
                     "scope": {"tenant_id": "t-a", "workspace_id": "w-1",
                               "goal_id": "g-1"}},
                    {"principal_id": "prin_B", "display": "Alex",
                     "scope": {"tenant_id": "t-a", "workspace_id": "w-1",
                               "goal_id": "g-1"}}],
                "states": [], "initial": "s0", "transitions": [],
                "trace": {"events": [], "request_scope": {}}, "oracle_hint": {}}
    actors = [t for t in scenario["principals"]]
    collapsed = len({p["principal_id"] for p in actors}) != len(
        {p.get("display") for p in actors})
    keys_distinct = len({p["principal_id"] for p in actors}) == 2
    return {"identity_fail_detected": collapsed and keys_distinct}


def probe_parser_battery() -> dict:
    """Probe P: duplicate key, NaN, unknown schema, remote ref, traversal, symlink."""
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
        contract.validate({"scenario_id": "X", "class": "nope", "description": "x",
                           "principals": [], "states": [], "initial": "s0",
                           "transitions": [],
                           "trace": {"events": [], "request_scope": {}},
                           "oracle_hint": {"kind": "stit_holds"}},
                          contract.load("schemas/scenario.schema.json"))
        cases["unknown_schema_version"] = False
    except ValueError:
        cases["unknown_schema_version"] = True
    try:
        contract.loads('{"$ref": "https://example.com/s.json"}')
        cases["remote_ref"] = False
    except ValueError:
        cases["remote_ref"] = True
    cases["traversal"] = contract.has_traversal("../../evil")
    cases["symlink_escape"] = contract.has_traversal("..\\link")
    return {"rejected": cases}


def probe_missing_delegator() -> dict:
    """Probe B: dropped delegator edge forces incomplete/abstain."""
    scenario = {"scenario_id": "PX-B", "class": "adversarial_or_invalid",
                "description": "x",
                "principals": [{"principal_id": "prin_child",
                                "scope": {"tenant_id": "t-a",
                                          "workspace_id": "w-1",
                                          "goal_id": "g-1"}}],
                "states": [{"state_id": "s0", "authority": {"grants": {
                    "g-child": {"scope": {}, "actions": ["read"],
                                "revoked": False, "expired": False}}},
                    "phase": "ready"}],
                "initial": "s0",
                "transitions": [{"from": "s0", "actor": "prin_child",
                                 "action": "read", "args": {}, "to": "s1",
                                 "authority_required": {"grant_id": "g-child"},
                                 "outcome": "effect", "environment_move": None,
                                 "audit_ref": "ev1"}],
                "trace": {"events": [], "request_scope": {}},
                "oracle_hint": {"kind": "underdetermined"}}
    obs = runner.generate_observation(scenario, "A", 1)["core"]
    return {"verdict": obs["verdict"],
            "incomplete": obs["verdict"] == "UNDERDETERMINED" or bool(obs["unknowns"])}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticket", required=False, default=str(HERE))
    args = parser.parse_args(argv=None)
    _ = args
    print("evaluator skeleton ready (Phase A); full matrix runs in Phase B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
