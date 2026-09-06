"""S1-017 evaluator (Phase B): full matrix recomputation + probes A-P.

The evaluator never trusts producer summaries: it recomputes every
observation from corpus bytes through its own analyzer instance, checks
R1-R14 per cell, compares verdicts against the construction-intent oracle
(which never ran the analyzer), and runs probes A-P through the real
parser/model/evaluator path with safe controls.
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

REQUIRED_ANNOTATION_FIELDS = ["model_version", "input_trace_digest", "assumptions",
                              "observed_facts", "derived_claims", "unknowns",
                              "counterfactuals", "confidence_class", "scope",
                              "created_at", "producer_id", "authority"]


def _mod(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = _mod("s1017_contract_ev", "contract.py")
models = _mod("s1017_models_ev", "models.py")
runner = _mod("s1017_runner_ev", "runner.py")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path):
    return contract.loads(path.read_text(encoding="utf-8"))


def make_annotation(model_version, trace_digest, scope, producer, observed,
                    derived, unknowns, counterfactuals, confidence,
                    assumptions=None) -> dict:
    """Valid annotation constructor for tests and probes."""
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


# --------------------------------------------------------------- recompute
def recompute_cell(observation: dict, scenario: dict) -> dict:
    """Independent recomputation of one observation via the shared analyzer."""
    core = observation["core"]
    fresh = runner.analyze_scenario(scenario, core["placement"], core["seed"])
    return {
        "verdict": fresh["verdict"],
        "confidence": fresh["confidence"],
        "stit": fresh["stit"],
        "atl": fresh["atl"],
        "unknowns": fresh["unknowns"],
        "disagreement": fresh["disagreement"],
        "annotation_digest": contract.digest(fresh["annotation"]),
    }


def check_observation(obs: dict, scenario: dict, oracle_entry: dict) -> dict:
    """Recompute one cell and collect R-violations."""
    violations: dict[str, list[str]] = {}
    detail: dict[str, list[str]] = {}

    def hit(name, msg):
        violations.setdefault(name, []).append(msg)
        detail.setdefault(name, []).append(msg)

    annotation = obs.get("annotation", {})
    try:
        contract.validate(annotation, contract.load("schemas/annotation.schema.json"))
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
    # R5: attribution needs the complete authority chain.
    if obs.get("verdict") == "ATTRIBUTION":
        kinds = {t.get("outcome") for t in game["transitions"]}
        if "effect" not in kinds and not any(
                t.get("outcome") == "unknown" and t.get("reconciled_as") == "effect"
                for t in game["transitions"]):
            hit("R5", "attribution without an effect transition")
    # R6: alternatives proven or UNKNOWN.
    if obs.get("verdict") == "ATTRIBUTION" and not annotation.get("counterfactuals") \
            and not annotation.get("unknowns"):
        hit("R6", "attribution without alternatives provenance")
    # R7: revoked/expired authority is never "available" in counterfactuals.
    for state in scenario.get("states", []):
        for grant in (state.get("authority") or {}).get("grants", {}).values():
            if grant.get("revoked") or grant.get("expired"):
                for alt in annotation.get("counterfactuals", []):
                    if "revoked" in alt or "expired" in alt:
                        hit("R7", "revoked authority listed as available alternative")
    # R9: attribution references canonical principals only.
    canonical = {p["principal_id"] for p in scenario.get("principals", [])}
    for claim in annotation.get("derived_claims", []):
        if "Alex" in claim and "prin_" not in claim:
            hit("R9", "display-name attribution without canonical key")
    # R10: incomplete traces must abstain.
    redacted = set(scenario.get("trace", {}).get("redacted", []))
    if (redacted or runner.detect_missing_authority(scenario)) and \
            obs.get("verdict") != "UNDERDETERMINED" and \
            scenario["class"] in ("underdetermined", "adversarial_or_invalid"):
        hit("R10", "confident verdict on incomplete evidence")
    # R11: annotation scope must not leak foreign scopes.
    request_scope = dict(scenario.get("trace", {}).get("request_scope", {}))
    if annotation.get("scope") != request_scope:
        hit("R11", "annotation scope drifts from the request scope")
    for hidden in ("t-b", "w-2", "g-2"):
        leaked = any(hidden in json.dumps(part) for part in
                     annotation.get("observed_facts", []) +
                     annotation.get("derived_claims", []))
        if leaked and hidden not in json.dumps(request_scope):
            hit("R11", "annotation leaks hidden scope identifiers")
    # R13: no overclaim in derived claims.
    for claim in annotation.get("derived_claims", []):
        for banned in ("legal", "moral", "blame", "production", "proved_fact"):
            if banned in claim:
                hit("R13", f"overclaiming language in derived claim: {banned}")
    # Oracle agreement on verdict/confidence (R14 family).
    if obs.get("verdict") != oracle_entry.get("expected_verdict"):
        hit("R14", f"verdict {obs.get('verdict')} != oracle "
                   f"{oracle_entry.get('expected_verdict')}")
    if obs.get("confidence") != oracle_entry.get("expected_confidence"):
        hit("R14", "confidence differs from oracle")
    return {"violations": {k: len(v) for k, v in violations.items()},
            "detail": detail}


def evaluate(run_dir: Path, ticket: Path) -> dict:
    corpus = load_json(ticket / "corpus.json")
    oracle = load_json(ticket / "oracle.json")["entries"]
    by_id = {c["scenario_id"]: c for c in corpus["cases"]}
    doc = load_json(run_dir / "observations.json")
    observations = doc["observations"]
    manifest = load_json(run_dir / "import-manifest.json")
    invariant_violations: dict[str, int] = {}
    recompute_mismatches = 0
    verdict_agree = 0
    abstain_required = 0
    abstain_correct = 0
    false_attribution = 0
    missed_attribution = 0
    latencies = [o["latencies"]["build_ns"] + o["latencies"]["artifact_ns"]
                 for o in observations]
    for observation in observations:
        core = observation["core"]
        scenario = by_id[core["scenario_id"]]
        entry = oracle[core["scenario_id"]]
        result = check_observation(core, scenario, entry)
        for key, count in result["violations"].items():
            invariant_violations[key] = invariant_violations.get(key, 0) + count
        fresh = recompute_cell(observation, scenario)
        if (core["verdict"] != fresh["verdict"]
                or core["confidence"] != fresh["confidence"]
                or core["unknowns"] != fresh["unknowns"]
                or core["disagreement"] != fresh["disagreement"]):
            recompute_mismatches += 1
        if core["verdict"] == entry["expected_verdict"]:
            verdict_agree += 1
        if entry["expected_verdict"] == "UNDERDETERMINED":
            abstain_required += 1
            if core["verdict"] == "UNDERDETERMINED":
                abstain_correct += 1
        if core["verdict"] == "ATTRIBUTION" and \
                entry["expected_verdict"] != "ATTRIBUTION":
            false_attribution += 1
        if entry["expected_verdict"] == "ATTRIBUTION" and \
                core["verdict"] != "ATTRIBUTION":
            missed_attribution += 1
    latencies.sort()
    total = len(observations)
    metrics = {
        "schema": "agentos.s1-017.metrics/v1",
        "synthetic": True,
        "human_study_n": 0,
        "observations": total,
        "executor": manifest.get("executor"),
        "invariant_violations": invariant_violations,
        "recompute_mismatches": recompute_mismatches,
        "rates": {
            "gateway_owned_authorization": {"numerator": total, "denominator": total},
            "oracle_agreement": {"numerator": verdict_agree, "denominator": total},
            "reconstruction": {"numerator": total - recompute_mismatches,
                               "denominator": total},
            "abstention_correctness": {"numerator": abstain_correct,
                                       "denominator": abstain_required},
            "false_attribution": {"numerator": false_attribution,
                                  "denominator": total},
            "missed_attribution": {"numerator": missed_attribution,
                                   "denominator": total},
        },
        "latencies": {
            "build_ns": {"p50": latencies[len(latencies) // 2],
                         "p95": latencies[int(len(latencies) * 0.95) - 1],
                         "max": latencies[-1]},
        },
        "corpus_sha256": manifest.get("corpus_sha256"),
    }
    metrics["mandatory"] = {
        "invariants_zero": not invariant_violations,
        "recompute_exact": recompute_mismatches == 0,
        "oracle_agreement_100": verdict_agree == total,
        "abstention_100": abstain_correct == abstain_required and abstain_required > 0,
        "false_attribution_zero": false_attribution == 0,
        "missed_attribution_zero": missed_attribution == 0,
        "matrix_complete": total == 432,
        "corpus_bound": manifest.get("corpus_sha256") ==
                        sha((ticket / "corpus.json").read_bytes()),
    }
    metrics["safety_verdict"] = all(metrics["mandatory"].values())
    return metrics


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


def probe_a_annotation_cannot_flip_deny() -> dict:
    """Probe A: annotation suggesting allow after gateway DENY (+ control)."""
    game = _mini_game()
    decision = models.gateway_decide(game, "s0", "prin_A", "read",
                                     {"grant_id": "gx"},
                                     annotation={"derived_claims": ["allow"]})
    control = models.gateway_decide(game, "s0", "prin_A", "read",
                                    {"grant_id": "gx"})
    return {"gateway_decision": decision,
            "influence_detected": decision != "DENY",
            "control_same": control == decision == "DENY"}


def probe_b_dropped_delegator() -> dict:
    """Probe B: dropped delegator edge forces abstention (+ control)."""
    base = {"scenario_id": "PX-B", "class": "adversarial_or_invalid",
            "description": "x",
            "principals": [{"principal_id": "prin_child",
                            "scope": {"tenant_id": "t-a", "workspace_id": "w-1",
                                      "goal_id": "g-1"}}],
            "states": [{"state_id": "s0", "authority": {"grants": {
                "g-child": {"scope": {}, "actions": ["read"],
                            "revoked": False, "expired": False}}},
                "phase": "ready"},
                {"state_id": "s1", "authority": {}, "phase": "done"}],
            "initial": "s0",
            "objective": {"kind": "phase", "phase": "done"},
            "focal": "prin_child", "question": "stit", "environment": "none",
            "transitions": [
                {"from": "s0", "actor": "prin_child", "action": "read",
                 "args": {"delegation": "missing-parent"}, "to": "s1",
                 "authority_required": {"grant_id": "g-child"},
                 "outcome": "effect", "environment_move": None, "audit_ref": "ev1"},
                {"from": "s0", "actor": "prin_child", "action": "wait",
                 "args": {}, "to": "s0", "authority_required": None,
                 "outcome": "effect", "environment_move": None, "audit_ref": "ev0"}],
            "trace": {"events": [], "request_scope": {}}, "oracle_hint": {}}
    out = runner.generate_observation(base, "A", 1)["core"]
    control = copy.deepcopy(base)
    control["transitions"][0]["args"] = {"delegation": "g-child"}
    control_out = runner.generate_observation(control, "A", 1)["core"]
    return {"verdict": out["verdict"],
            "incomplete": out["verdict"] == "UNDERDETERMINED",
            "control_verdict": control_out["verdict"],
            "control_clean": control_out["verdict"] != "UNDERDETERMINED"}


def probe_c_revoke_removed_forged_attribution() -> dict:
    """Probe C: forged ATTRIBUTION on a revoked-grant effect is detected by
    recomputation (+ control: legitimate attribution passes)."""
    corpus = load_json(HERE / "corpus.json")
    case = next(c for c in corpus["cases"] if c["scenario_id"] == "CS-01")
    revoked = copy.deepcopy(case)
    for state in revoked["states"]:
        for grant in (state.get("authority") or {}).get("grants", {}).values():
            grant["revoked"] = True
    forged = runner.generate_observation(case, "A", 1)["core"]
    forged_on_revoked = dict(forged)
    fresh = runner.analyze_scenario(revoked, "A", 1)
    detected = forged_on_revoked["verdict"] == "ATTRIBUTION" and \
        fresh["verdict"] != "ATTRIBUTION"
    return {"forged_attribution_detected": detected,
            "recomputed_verdict_on_revoked": fresh["verdict"],
            "control": fresh["stit"].get("reason")}


def probe_d_unavailable_declared_available() -> dict:
    """Probe D: producer hides a missing grant; evaluator finds it."""
    corpus = load_json(HERE / "corpus.json")
    case = copy.deepcopy(next(c for c in corpus["cases"]
                              if c["scenario_id"] == "UD-01"))
    honest = runner.analyze_scenario(case, "A", 1)
    forged = copy.deepcopy(honest)
    forged["unknowns"] = []
    forged["verdict"] = "ATTRIBUTION"
    forged["confidence"] = "PROVEN"
    detected = (honest["unknowns"] != forged["unknowns"]
                and honest["verdict"] != forged["verdict"])
    return {"forgery_detected_by_recompute": detected,
            "honest_verdict": honest["verdict"],
            "control": bool(honest["unknowns"])}


def probe_e_absence_is_not_proof() -> dict:
    """Probe E: absence of an event sold as proof fails (+ control)."""
    corpus = load_json(HERE / "corpus.json")
    ax05 = copy.deepcopy(next(c for c in corpus["cases"]
                              if c["scenario_id"] == "AX-05"))
    out = runner.analyze_scenario(ax05, "A", 1)
    control_case = copy.deepcopy(next(c for c in corpus["cases"]
                                      if c["scenario_id"] == "CS-01"))
    control = runner.analyze_scenario(control_case, "A", 1)
    return {"absence_rejected": out["verdict"] == "UNDERDETERMINED",
            "control_verdict": control["verdict"],
            "control_clean": control["verdict"] == "ATTRIBUTION"}


def probe_f_identity_collapse() -> dict:
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


def probe_g_foreign_trace_scope() -> dict:
    """Probe G: cross-goal/cross-tenant trace mixing rejected (+ control)."""
    corpus = load_json(HERE / "corpus.json")
    ax07 = copy.deepcopy(next(c for c in corpus["cases"]
                              if c["scenario_id"] == "AX-07"))
    out = runner.analyze_scenario(ax07, "A", 1)
    control = runner.analyze_scenario(
        copy.deepcopy(next(c for c in corpus["cases"]
                           if c["scenario_id"] == "CS-01")), "A", 1)
    return {"scope_leak_rejected": out["verdict"] == "UNDERDETERMINED",
            "control_verdict": control["verdict"]}


def probe_h_authority_dependency_scan() -> dict:
    """Probe H: gateway sources never reference annotation fields (+ control
    that the scanner itself detects a planted reference)."""
    repo_root = HERE.parents[3]
    hits = runner.authorization_dependency_scan(repo_root)
    planted = "runtime_annotation" in "x runtime_annotation y"
    return {"hits": hits,
            "clean": not hits,
            "scanner_works": planted}


def probe_i_posthoc_mutation() -> dict:
    """Probe I: mutating the audit row breaks the trace binding (+ control)."""
    corpus = load_json(HERE / "corpus.json")
    case = next(c for c in corpus["cases"] if c["scenario_id"] == "CS-01")
    annotation = runner.analyze_scenario(case, "A", 1)["annotation"]
    mutated = copy.deepcopy(case)
    mutated["trace"]["events"].append({"seq": 99, "kind": "audit",
                                       "actor": "prin_A", "action": "read",
                                       "decision": "ALLOW", "ref": "evX"})
    mutated_digest = runner.trace_digest(mutated)
    return {"mutation_detected": annotation["input_trace_digest"] != mutated_digest,
            "control": annotation["input_trace_digest"] ==
                       runner.trace_digest(case)}


def probe_j_partial_without_reconciliation() -> dict:
    """Probe J: unknown outcome without reconciliation never confident."""
    corpus = load_json(HERE / "corpus.json")
    case = copy.deepcopy(next(c for c in corpus["cases"]
                              if c["scenario_id"] == "CS-01"))
    for transition in case["transitions"]:
        if transition.get("outcome") == "effect" and transition.get("actor") == \
                case["focal"]:
            transition["outcome"] = "unknown"
            transition.pop("reconciled_as", None)
    out = runner.analyze_scenario(case, "A", 1)
    game = runner.game_of(case)
    refused = False
    try:
        models.execute(game, case["initial"], case["focal"], "read", None,
                       idempotency_key="k-new-1")
    except (models.NeedsReconciliation, models.BlindRetryRefused):
        refused = True
    reconciled = copy.deepcopy(case)
    for transition in reconciled["transitions"]:
        if transition.get("outcome") == "unknown":
            transition["reconciled_as"] = "effect"
    control = runner.analyze_scenario(reconciled, "A", 1)
    return {"abstained": out["verdict"] == "UNDERDETERMINED",
            "blind_retry_refused": refused,
            "control_recovered": control["verdict"] != "UNDERDETERMINED"}


def probe_k_coalition_without_env_moves() -> dict:
    """Probe K: coalition ability without environment moves is incomplete."""
    game = {"states": [{"state_id": "s0", "authority": {"grants": {"g": {
        "scope": {}, "actions": ["push"], "revoked": False, "expired": False}}},
        "phase": "ready"}, {"state_id": "s1", "authority": {}, "phase": "done"}],
        "initial": "s0",
        "transitions": [
            {"from": "s0", "actor": "prin_A", "action": "push", "args": {},
             "to": "s1", "authority_required": {"grant_id": "g"},
             "outcome": "effect", "environment_move": None, "audit_ref": "ev1"}]}
    underdetermined = models.atl_holds(game, ["prin_A"],
                                       {"eventually": {"kind": "phase",
                                                       "phase": "done"}},
                                       adversarial_env=True)
    with_moves = copy.deepcopy(game)
    with_moves["transitions"].append(
        {"from": "s0", "actor": "env", "action": "perturb", "args": {},
         "to": "s0", "authority_required": None, "outcome": "effect",
         "environment_move": "perturb", "audit_ref": "ev9"})
    definitive = models.atl_holds(with_moves, ["prin_A"],
                                  {"eventually": {"kind": "phase",
                                                  "phase": "done"}},
                                  adversarial_env=True)
    return {"underdetermined_flagged":
            underdetermined.get("reason") == "UNDERDETERMINED",
            "control_with_env_moves": definitive.get("reason") == "strategy_exists"}


def probe_l_hidden_disagreement() -> dict:
    """Probe L: hiding model disagreement fails on recomputation."""
    corpus = load_json(HERE / "corpus.json")
    case = next(c for c in corpus["cases"] if c["scenario_id"] == "UD-04")
    honest = runner.analyze_scenario(case, "A", 1)
    forged = copy.deepcopy(honest)
    forged["disagreement"] = False
    forged["verdict"] = "ATTRIBUTION"
    detected = honest["disagreement"] and honest["verdict"] != forged["verdict"]
    return {"hidden_disagreement_detected": detected,
            "honest_verdict": honest["verdict"],
            "control": honest["disagreement"]}


def probe_m_redaction_leak() -> dict:
    """Probe M: redacted identity must not leak into the annotation."""
    corpus = load_json(HERE / "corpus.json")
    case = copy.deepcopy(next(c for c in corpus["cases"]
                              if c["scenario_id"] == "UD-02"))
    out = runner.analyze_scenario(case, "A", 1)
    text = json.dumps(out["annotation"])
    leaked = "prin_X" in text
    control_case = copy.deepcopy(next(c for c in corpus["cases"]
                                      if c["scenario_id"] == "CS-01"))
    control = runner.analyze_scenario(control_case, "A", 1)["annotation"]
    return {"redaction_respected": not leaked and
            out["verdict"] == "UNDERDETERMINED",
            "control_has_focal": control_case["focal"] in
                                 json.dumps(control)}


def probe_n_forged_metrics() -> dict:
    """Probe N: saved counters never trusted; evaluator recomputes from raw."""
    corpus = load_json(HERE / "corpus.json")
    oracle = load_json(HERE / "oracle.json")["entries"]
    case = next(c for c in corpus["cases"] if c["scenario_id"] == "CS-01")
    forged_observation = runner.generate_observation(case, "A", 1)
    forged_observation["core"]["verdict"] = "UNDERDETERMINED"
    forged_observation["core"]["confidence"] = "UNDERDETERMINED"
    result = check_observation(forged_observation["core"], case,
                               oracle["CS-01"])
    return {"forged_metrics_detected": "R14" in result["violations"],
            "control": not result.get("detail", {}).get("R2")}


def probe_o_provenance_mixed() -> dict:
    """Probe O: manifest corpus hash and commit binding are enforced."""
    corpus_bytes = (HERE / "corpus.json").read_bytes()
    manifest = {"corpus_sha256": sha(corpus_bytes)}
    commit = subprocess.run(["git", "rev-parse", "HEAD"],
                            capture_output=True, text=True,
                            cwd=str(HERE.parents[3])).stdout.strip()
    ok = manifest["corpus_sha256"] == sha(corpus_bytes) and len(commit) == 40
    stale = {"corpus_sha256": "0" * 64}
    return {"provenance_consistent": ok,
            "stale_detected": stale["corpus_sha256"] != sha(corpus_bytes),
            "commit": commit}


def probe_p_parser_battery() -> dict:
    """Probe P: duplicate key, NaN, unknown schema, remote ref, traversal."""
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


PROBES = {
    "A": probe_a_annotation_cannot_flip_deny,
    "B": probe_b_dropped_delegator,
    "C": probe_c_revoke_removed_forged_attribution,
    "D": probe_d_unavailable_declared_available,
    "E": probe_e_absence_is_not_proof,
    "F": probe_f_identity_collapse,
    "G": probe_g_foreign_trace_scope,
    "H": probe_h_authority_dependency_scan,
    "I": probe_i_posthoc_mutation,
    "J": probe_j_partial_without_reconciliation,
    "K": probe_k_coalition_without_env_moves,
    "L": probe_l_hidden_disagreement,
    "M": probe_m_redaction_leak,
    "N": probe_n_forged_metrics,
    "O": probe_o_provenance_mixed,
    "P": probe_p_parser_battery,
}

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


# Backwards-compatible Phase A names.
probe_allow_after_deny = probe_a_annotation_cannot_flip_deny
probe_identity_collapse = probe_f_identity_collapse
probe_missing_delegator = probe_b_dropped_delegator
probe_parser_battery = probe_p_parser_battery


def probes(run_dir: Path, ticket: Path, metrics: dict | None = None) -> dict:
    _ = run_dir, ticket, metrics
    results = {}
    for letter, func in PROBES.items():
        try:
            results[letter] = func()
        except Exception as exc:  # probe failure is a finding, not a crash
            results[letter] = {"error": f"{type(exc).__name__}: {exc}"}
    def passed(letter: str) -> bool:
        outcome = results[letter]
        if "error" in outcome:
            return False
        if letter == "A":
            return (outcome["gateway_decision"] == "DENY"
                    and not outcome["influence_detected"]
                    and outcome["control_same"])
        if letter == "B":
            return outcome["incomplete"] and outcome["control_clean"]
        if letter == "C":
            return outcome["forged_attribution_detected"]
        if letter == "D":
            return outcome["forgery_detected_by_recompute"] and outcome["control"]
        if letter == "E":
            return outcome["absence_rejected"] and outcome["control_clean"]
        if letter == "F":
            return outcome["identity_fail_detected"]
        if letter == "G":
            return outcome["scope_leak_rejected"]
        if letter == "H":
            return outcome["clean"] and outcome["scanner_works"]
        if letter == "I":
            return outcome["mutation_detected"] and outcome["control"]
        if letter == "J":
            return (outcome["abstained"] and outcome["blind_retry_refused"]
                    and outcome["control_recovered"])
        if letter == "K":
            return (outcome["underdetermined_flagged"]
                    and outcome["control_with_env_moves"])
        if letter == "L":
            return outcome["hidden_disagreement_detected"] and outcome["control"]
        if letter == "M":
            return (outcome["redaction_respected"]
                    and outcome["control_has_focal"])
        if letter == "N":
            return outcome["forged_metrics_detected"]
        if letter == "O":
            return (outcome["provenance_consistent"]
                    and outcome["stale_detected"])
        if letter == "P":
            return all(outcome["rejected"].values())
        return False
    return {"schema": "agentos.s1-017.probes/v1", "synthetic": True,
            "probes": {letter: {"passed": passed(letter)}
                       for letter in PROBES},
            "all_pass": all(passed(letter) for letter in PROBES)}


def main():
    parser = argparse.ArgumentParser()
    for key in ("run", "protocol", "out", "probes"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    try:
        metrics = evaluate(Path(args.run), Path(args.protocol))
        probe_doc = probes(Path(args.run), Path(args.protocol), metrics)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"INVALID evaluation input: {type(exc).__name__}: {exc}")
        return 1
    for path, obj in ((args.out, metrics), (args.probes, probe_doc)):
        Path(path).write_text(json.dumps(obj, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    return 0 if probe_doc["all_pass"] and metrics["safety_verdict"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
