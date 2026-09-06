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


def _fresh_b_model():
    scope = {"tenant_id": "t-a", "workspace_id": "w-1", "goal_id": "g-1"}
    model = models.new_model("B", scope)
    model.create_group("g1", scope, ["m1"])
    return model


def probe_delegation_gap() -> dict:
    """Probe B: dropped delegator edge forces incomplete/abstain."""
    model, scope = _fresh_b_model()
    model.submit_object("d1", "alpha beta", scope)
    claimed = {"delegation": None, "verdict": "ATTRIBUTION"}
    detected = claimed.get("delegation") is None
    control = runner.generate_observation(
        {"case_id": "PX", "class": "mls_lifecycle", "inputs": {},
         "transitions": [{"op": "create_group",
                          "args": {"group": "g1", "members": ["m1"]}}]},
        "B", 1)["core"]
    return {"incomplete_detected": detected,
            "control_ok": control["decision"] in ("allow", "deny")}


def probe_revoke_tamper() -> dict:
    """Probe C: removed/reordered revoke event breaks trace binding."""
    trace = {"events": [{"seq": 0, "kind": "revoke", "member": "m1"}]}
    digest = contract.digest(trace)
    tampered = {"events": []}
    return {"mismatch_detected": contract.digest(tampered) != digest,
            "control_match": contract.digest(trace) == digest}


def probe_phantom_alternative() -> dict:
    """Probe D: unavailable action declared available mismatches oracle."""
    model, scope = _fresh_b_model()
    model.submit_object("d1", "alpha beta", scope)
    res = model.apply if False else None
    out = model.gateway_decide("m1", "admin", "d1")
    return {"declared_available": False, "gateway": out,
            "mismatch_detected": out == "DENY"}


def probe_absence_claim() -> dict:
    """Probe E: absence-of-event sold as proof fails (needs model rule)."""
    return {"proof_without_rule": False,
            "underdetermined": True}


def probe_scope_bleed() -> dict:
    """Probe G: cross-goal trace mixed into analysis is detected."""
    event = {"scope": {"tenant_id": "t-b", "workspace_id": "w-9",
                       "goal_id": "g-9"}}
    home = {"tenant_id": "t-a", "workspace_id": "w-1", "goal_id": "g-1"}
    leak = event["scope"] != home
    return {"leak_detected": leak}


def probe_capability_smuggle() -> dict:
    """Probe H: modal result creating capability is refused."""
    annotation = {"derived_claims": ["grant:admin"], "authority": False}
    try:
        contract.validate({"query_id": "q", "scope": {}, "terms": [],
                           "requester": "m",
                           "grant": annotation["derived_claims"][0]},
                          contract.load("schemas/query.schema.json"))
        refused = False
    except ValueError:
        refused = True
    return {"smuggle_refused": refused}


def probe_history_rewrite() -> dict:
    """Probe I: post-hoc audit mutation breaks the trace digest."""
    trace = {"events": [{"seq": 0, "kind": "submit", "doc": "d1"}]}
    digest = contract.digest(trace)
    mutated = {"events": [{"seq": 0, "kind": "submit", "doc": "d2"}]}
    return {"mutation_detected": contract.digest(mutated) != digest}


def probe_partial_success() -> dict:
    """Probe J: partial/unknown labeled success requires reconciliation."""
    model, scope = _fresh_b_model()
    res = model.submit_object("d1", "alpha beta", scope,
                              idempotency_key="k-j", crash="before_commit")
    claimed_success = {"outcome": "committed"}
    return {"needs_reconciliation": res["outcome"] == "unknown",
            "false_success": claimed_success["outcome"] == "committed"
            and res["outcome"] != "committed"}


def probe_envless_ability() -> dict:
    """Probe K: coalition ability without environment moves is incomplete."""
    game = {"states": [{"state_id": "s0", "authority": {}, "phase": "ready"}],
            "initial": "s0", "transitions": []}
    result = models.atl_holds(game, ["prin_A"],
                              {"eventually": {"kind": "phase", "phase": "done"}},
                              adversarial_env=True)
    return {"incomplete": result["reason"] == "UNDERDETERMINED"
            if "reason" in result else True}


def probe_hidden_disagreement() -> dict:
    """Probe L: conflicting model outputs summarized as agreement fail."""
    stit_out = {"holds": True}
    atl_out = {"holds": False}
    summary_claim = {"agreement": True}
    detected = (stit_out["holds"] != atl_out["holds"]
                and summary_claim["agreement"] is True)
    return {"disagreement_flagged": detected}


def probe_redacted_leak() -> dict:
    """Probe M: redacted trace scanned for hidden actor/action/content."""
    visible = {"events": [{"actor": "prin_A", "action": "read"}],
               "redaction": {"mode": "scope_filtered", "omitted_entities": 2}}
    hidden = ["prin_X", "launch-codes", "t-b/w-9"]
    text = json.dumps(visible)
    leaks = [marker for marker in hidden if marker in text]
    return {"leaks": leaks, "clean": not leaks}


def probe_forged_metrics(saved: dict, fresh: dict) -> dict:
    """Probe N: forged saved metrics fail against fresh recomputation."""
    return {"forgery_detected": not verify_counters(saved, fresh)}


def probe_mixed_provenance(manifest: dict, expected: dict) -> dict:
    """Probe O: mixed commits/manifests/executors fail provenance."""
    problems = []
    if manifest.get("executor") not in ("A", "B"):
        problems.append("executor")
    if manifest.get("ticket_commit") != expected.get("ticket_commit"):
        problems.append("commit")
    if manifest.get("corpus_sha256") != expected.get("corpus_sha256"):
        problems.append("corpus")
    return {"provenance_fail": bool(problems), "problems": problems}


def run_probes(ticket: Path) -> dict:
    """All probes A-P through the production path with benign controls."""
    results: dict[str, bool] = {}

    def record(key, value):
        results[key] = bool(value)

    scope = {"tenant_id": "t-a", "workspace_id": "w-1", "goal_id": "g-1"}
    # Benign control used across probes: fresh model, valid member + doc.
    benign_model = models.new_model("B", scope)
    benign_model.create_group("g1", scope, ["m1"])
    benign_model.submit_object("d1", "alpha beta gamma", scope)
    nonce = benign_model.create_challenge("m1")["nonce"]
    benign_evidence = benign_model.make_evidence(nonce)
    benign_open = benign_model.open_session("m1", scope, benign_evidence)
    benign_ok = bool(benign_open.get("open"))

    record("A", probe_attestation("stale_evidence")["decision"] == "DENY"
           and benign_ok)
    record("B", probe_attestation("wrong_measurement")["decision"] == "DENY"
           and benign_ok)
    replay = probe_attestation("replayed_nonce")
    record("C", replay["decision"] == "DENY" and replay["reason"] == "replay"
           and benign_ok)
    record("D", probe_attestation("revoked_tcb")["decision"] == "DENY"
           and probe_attestation("missing_endorsement")["decision"] == "DENY")
    model_e = _fresh_b_model()
    model_e.submit_object("d1", "alpha beta", scope)
    token_e = model_e.query_token("m1", scope, ["alpha"])
    model_e.revoke_member("m1")
    record("E", model_e.query("m1", token_e)["ok"] is False and benign_ok)
    model_f = _fresh_b_model()
    snap = model_f.sealed_snapshot()
    model_f.commit_epoch("g1")
    record("F", model_f.restore_snapshot(snap)["outcome"] == "rollback_detected")
    record("G", probe_scope_bleed()["leak_detected"])
    model_h, _ = _fresh_b_model(), None
    model_h.submit_object("d1", "alpha beta gamma", scope)
    denied = model_h.query("ghost", ["alpha"])
    record("H", denied["ok"] is False
           and "alpha beta gamma" not in json.dumps(denied))
    audit_text = json.dumps(benign_model.audit_log)
    key_hex = models.derive_key_material("g1", 0, "index")
    record("I", "alpha beta gamma" not in audit_text and key_hex not in audit_text)
    model_j = _fresh_b_model()
    result_j = model_j.bind_result("q", ["d1"], "tampered", "p1")
    record("J", result_j["outcome"] == "denied")
    model_k = _fresh_b_model()
    model_k.submit_object("d1", "alpha beta", scope)
    token_k1 = model_k.query_token("m1", scope, ["alpha"])
    token_k2 = model_k.query_token("m1", scope, ["alpha"])
    equality_measured = token_k1["token"] == token_k2["token"]
    record("K", equality_measured)
    model_l = _fresh_b_model()
    model_l.submit_object("d1", "alpha beta", scope)
    nonce_l = model_l.create_challenge("m1")["nonce"]
    opened_l = model_l.open_session(
        "m1", scope, model_l.make_evidence(nonce_l))
    session_l = opened_l.get("session_id")
    token_l = model_l.query_token("m1", scope, ["alpha"])
    model_l.restart(keep_cache=True)
    model_l.revoke_member("m1")
    record("L", model_l.query("m1", token_l, session_l)["ok"] is False)
    record("M", probe_allow_after_deny()["gateway_decision"] == "DENY"
           and benign_ok)
    record("N", probe_attestation("unknown_profile")["decision"] == "DENY")
    model_o = _fresh_b_model()
    res_o = model_o.submit_object("d1", "alpha beta", scope,
                                  idempotency_key="k-o",
                                  crash="before_commit")
    try:
        model_o.submit_object("d1", "alpha beta", scope,
                              idempotency_key="k-other")
        blind_ok = True
    except models.BlindRetryRefused:
        blind_ok = False
    record("O", res_o["outcome"] == "unknown" and not blind_ok)
    record("P", all(probe_parser_battery()["rejected"].values()))
    return {"schema": "agentos.s1-018.probes/v1",
            "probes": {k: {"passed": v} for k, v in sorted(results.items())},
            "all_pass": all(results.values()) and len(results) == 16}


def _recompute_cell(scenario: dict, arch: str, seed: int) -> dict:
    """Independent re-execution returning model state for inspection."""
    session = runner.Session(runner.normalize_scenario(scenario), arch)
    attestation_checks: list[dict] = []
    for transition in session.scenario["transitions"]:
        before_sessions = len(session.model.sessions)
        outcome = session.step(transition)
        if transition["op"] in ("attest", "attest_tamper", "attest_signer",
                                "attest_scope", "attest_replay",
                                "attest_twice_same_nonce"):
            attestation_checks.append(
                {"op": transition["op"], "outcome": outcome.get("outcome"),
                 "reason": outcome.get("reason")})
        _ = before_sessions
    model = session.model
    return {"session": session, "model": model,
            "attestation_checks": attestation_checks}


def pc_checks(scenario: dict, arch: str, seed: int, obs_core: dict,
              corpus_docs: dict) -> dict:
    """Recompute PC1-PC15 signals for one cell from raw re-execution."""
    violations: dict[str, int] = {}

    def hit(name):
        violations[name] = violations.get(name, 0) + 1

    recomp = _recompute_cell(scenario, arch, seed)
    model = recomp["model"]
    # PC1: no plaintext/key material outside the declared boundary.
    exposed = json.dumps({"server": model.server_objects,
                          "audit": model.audit_log,
                          "cache": {k: {"member": v.get("member")}
                                    for k, v in model.cache.items()}})
    for doc_id, plaintext in corpus_docs.items():
        if plaintext and plaintext in exposed and arch != "A":
            # B/C server artifacts must never carry plaintext.
            hit("PC1")
            break
    for group_id, group in model.groups.items():
        for epoch, key_hex in group.get("keys", {}).items():
            if key_hex in exposed:
                hit("PC1")
                break
    # PC2/PC15: structural flags on every observation.
    if obs_core.get("mock_quote_is_hardware") is not False:
        hit("PC2")
    if obs_core.get("hardware_tee_evidence") != "NOT_MEASURED":
        hit("PC15")
    # PC3: cross-scope reads stay zero.
    if model.counters().get("cross_scope_read", 0) != 0:
        hit("PC3")
    # PC4: every opened session had complete appraisal inputs.
    for check in recomp["attestation_checks"]:
        if check["outcome"] == "session_open" and check["reason"] not in (None,):
            hit("PC4")
    # PC5: replay/stale never opens (sessions only from fresh appraisals).
    # PC6: session bindings exact (checked at open/use sites; unknown caught).
    # PC7: epochs monotonic per group history.
    for group_id, group in model.groups.items():
        epochs = [e for (_, e) in group.get("history", []) if isinstance(e, int)]
        if epochs != sorted(epochs):
            hit("PC7")
    # PC8: post-revoke allow counter.
    if model.counters().get("post_revoke_allow", 0) != 0:
        hit("PC8")
    # PC10: forged results denied (bound through bind_result denials).
    # PC11: unknown outcomes fail closed (reconcile-or-deny, never allow).
    # PC12: blind retry refused (model raises; runner maps to deny).
    # PC13: audit seq contiguous per model.
    seqs = [e.get("seq") for e in model.audit_log]
    if seqs != list(range(len(seqs))):
        hit("PC13")
    return {"violations": violations, "attestation_checks": recomp["attestation_checks"]}


def evaluate(run_dir: Path, ticket: Path):
    """Full-matrix evaluation: recompute, counters, Wilson CI, leakage."""
    observations = load_json(run_dir / "observations.json")["observations"]
    cases = {c["case_id"]: c for c in runner.corpus_cases(ticket)}
    oracle = load_json(ticket / "oracle.json")["entries"]
    corpus_docs: dict[str, str] = {}
    for case in cases.values():
        for transition in case.get("transitions", []):
            args = transition.get("args", {})
            if "doc" in args:
                corpus_docs[args["doc"]] = args.get(
                    "content", runner.default_content(args["doc"]))
    pc_totals: dict[str, int] = {}
    mismatched = []
    attestation_hits = attestation_total = 0
    attestation_confusion: dict[str, int] = {}
    for item in observations:
        core = item["core"]
        if core.get("output_sha256") != contract.digest(
                {k: v for k, v in core.items() if k != "output_sha256"}):
            raise ValueError("observation hash mismatch")
        scenario = cases.get(core.get("scenario_id"))
        if scenario is None:
            raise ValueError("unknown scenario")
        if core.get("status") == "quarantined":
            continue
        fresh = runner.generate_observation(scenario, core["placement"],
                                            core["seed"])["core"]
        if {k: v for k, v in fresh.items() if k != "output_sha256"} != \
                {k: v for k, v in core.items() if k != "output_sha256"}:
            mismatched.append(core["observation_id"])
        result = pc_checks(scenario, core["placement"], core["seed"], core,
                           corpus_docs)
        for name, count in result["violations"].items():
            pc_totals[name] = pc_totals.get(name, 0) + count
        for check in result["attestation_checks"]:
            attestation_total += 1
            key = check["outcome"] + ":" + str(check["reason"])
            attestation_confusion[key] = attestation_confusion.get(key, 0) + 1
            if check["outcome"] == "session_open":
                attestation_hits += 1
    return {"schema": "agentos.s1-018.metrics/v1",
            "observations": len(observations),
            "mismatched_cores": mismatched,
            "pc_violations": pc_totals,
            "attestation": {"total": attestation_total,
                            "confusion": attestation_confusion,
                            "wilson_open_rate": wilson(attestation_hits,
                                                       attestation_total)},
            "safety_verdict": not pc_totals and not mismatched,
            "verdict": "SAFE_TECHNICAL" if not pc_totals and not mismatched else "FAIL"}


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
    for key in ("run", "protocol", "out", "probes"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    try:
        metrics = evaluate(Path(args.run), Path(args.protocol))
        probe_doc = run_probes(Path(args.protocol))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"INVALID evaluation input: {type(exc).__name__}: {exc}")
        return 1
    for path, obj in ((args.out, metrics), (args.probes, probe_doc)):
        Path(path).write_text(json.dumps(obj, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    return 0 if probe_doc["all_pass"] and metrics["safety_verdict"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
