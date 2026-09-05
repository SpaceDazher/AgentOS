"""S1-017 scenario analyzer + placement runner (stdlib only, Phase A).

Three placements share one observable analyzer over identical inputs:
- A OFFLINE_ANALYTICS: analyze an immutable trace export; zero runtime writes.
- B DERIVED_EXPORT_ANNOTATION: build a versioned, recomputable index of
  choices/alternatives; the index is non-authoritative and fully rebuildable.
- C BOUNDED_RUNTIME_ANNOTATION: store one minimal annotation record with
  authority=false next to the audit event; the gateway never reads it.

Phase A runs single cells (never the final 864-cell matrix).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL_VERSION = "s1-017.model/v1"

PLACEMENTS = ("A", "B", "C")


def _mod(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = _mod("s1017_contract_run", "contract.py")
models = _mod("s1017_models_run", "models.py")
grant_facts = models.grant_facts


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path):
    return contract.loads(path.read_text(encoding="utf-8"))


def corpus_cases(ticket: Path):
    doc = load_json(ticket / "corpus.json")
    if doc.get("schema") != "agentos.s1-017.corpus/v1":
        raise RuntimeError("corpus schema mismatch")
    return doc["cases"]


def game_of(scenario: dict) -> dict:
    return {"states": scenario["states"], "initial": scenario["initial"],
            "transitions": scenario["transitions"]}


def canonical_principals(scenario: dict) -> list[str]:
    """Sorted canonical principal IDs (deterministic order across processes:
    set iteration would leak PYTHONHASHSEED into placement-B index digests)."""
    return sorted({p["principal_id"] for p in scenario.get("principals", [])})


def trace_digest(scenario: dict) -> str:
    return contract.digest(scenario.get("trace", {}))


def primary_path(scenario: dict) -> list[str]:
    """The focal actor's first effectful transition in canonical trace order.

    An `unknown` outcome counts as effectful only once reconciled back to an
    effect (crash + reconciliation); an unreconciled unknown is never an
    effect. Delegated chains are covered because the focal actor may act
    in any state along the canonical history, not only the initial state."""
    game = game_of(scenario)
    focal = scenario.get("focal") or \
        (scenario.get("principals") or [{"principal_id": ""}])[0]["principal_id"]
    for transition in game["transitions"]:
        if transition["actor"] != focal:
            continue
        outcome = transition.get("outcome")
        if outcome == "effect" or (outcome == "unknown" and
                                    transition.get("reconciled_as") == "effect"):
            return [transition["from"], transition["to"]]
    return [game["initial"]]


ENVIRONMENT_ACTOR = "env"


def detect_identity_issue(scenario: dict) -> str | None:
    """R9: every transition actor must resolve to a canonical principal.

    Unknown actor identities are reported MASKED (digest prefix): a redacted
    trace must never leak the hidden identity through the annotation
    (R11/probe M). The declared environment pseudo-actor `env` is legitimate
    model machinery, not an identity: it never receives attribution.
    """
    canonical = canonical_principals(scenario)
    for transition in scenario.get("transitions", []):
        if transition["actor"] == ENVIRONMENT_ACTOR:
            continue
        if transition["actor"] not in canonical:
            return f"unknown_actor:{sha(transition['actor'].encode('utf-8'))[:12]}"
    return None


def detect_redaction_gap(scenario: dict) -> str | None:
    redacted = set(scenario.get("trace", {}).get("redacted", []))
    if "actor" in redacted or "content" in redacted:
        return "redacted_identity_or_effect"
    return None


ADVERSARIAL_MARKERS = ("absence_claim", "foreign_trace", "duplicate_paths",
                      "legacy_gap", "same_display", "revoke_removed", "mutated")


def detect_missing_authority(scenario: dict) -> str | None:
    """Any effectful transition whose required grant is absent from the
    state's authority facts is not provably authorised (fail closed)."""
    game = game_of(scenario)
    states = {s["state_id"]: s for s in game["states"]}
    for transition in game["transitions"]:
        outcome = transition.get("outcome")
        effectful = outcome == "effect" or (outcome == "unknown" and
                                            transition.get("reconciled_as") == "effect")
        if not effectful:
            continue
        required = transition.get("authority_required")
        if not required:
            continue
        grant_id = required.get("grant_id")
        grants = grant_facts(states[transition["from"]])
        if grant_id not in grants:
            return f"missing_grant_record:{grant_id}"
    return None


def detect_unreconciled_unknown(scenario: dict) -> str | None:
    for transition in scenario.get("transitions", []):
        if transition.get("outcome") == "unknown" and \
                "reconciled_as" not in transition:
            return "unknown_outcome_without_reconciliation"
    return None


def detect_nonboolean_authority(scenario: dict) -> str | None:
    for state in scenario.get("states", []):
        for grant in (state.get("authority") or {}).get("grants", {}).values():
            for flag in ("revoked", "expired"):
                value = grant.get(flag, False)
                if value is not None and not isinstance(value, bool):
                    return f"authority_status_not_boolean:{flag}"
    return None


def detect_unresolvable_delegation(scenario: dict) -> str | None:
    """A delegation/child/on_behalf reference must resolve to a known
    principal or grant; a dangling reference is an incomplete chain (R8).
    Values are masked (R11): hidden identities never leak via unknowns."""
    canonical = canonical_principals(scenario)
    grants = set()
    for state in scenario.get("states", []):
        grants.update((state.get("authority") or {}).get("grants", {}).keys())
    for transition in scenario.get("transitions", []):
        for key in ("delegation", "delegate", "child", "on_behalf"):
            value = (transition.get("args") or {}).get(key)
            if value is None:
                continue
            if value not in canonical and value not in grants:
                masked = sha(str(value).encode("utf-8"))[:12]
                return f"unresolvable_delegation:{key}={masked}"
    return None


def detect_effect_under_nonauthorised_standing(scenario: dict) -> str | None:
    """R7/trace integrity: an effect (recorded ALLOW) whose recomputed
    standing is not `authorised` is a trace/authority mismatch — the trace
    cannot be trusted for attribution and the case must abstain."""
    game = game_of(scenario)
    for transition in game["transitions"]:
        outcome = transition.get("outcome")
        effectful = outcome == "effect" or (outcome == "unknown" and
                                            transition.get("reconciled_as") == "effect")
        if not effectful:
            continue
        standing = models.grant_standing(
            game, transition["from"], transition["action"],
            transition.get("authority_required"))
        if transition.get("authority_required") is None:
            continue
        if standing != "authorised":
            return f"trace_authority_mismatch:{transition['audit_ref']}"
    return None


def analyze_scenario(scenario: dict, placement: str, seed: int) -> dict:
    """Shared observable analyzer; placements differ only in storage/indexing.

    Non-circular by contract: this function NEVER reads `oracle_hint` (the
    answer key). Verdicts come from the bounded model semantics plus
    fail-closed defeater detection only."""
    if placement not in PLACEMENTS:
        raise ValueError("unknown placement")
    game = game_of(scenario)
    principals = canonical_principals(scenario)
    focal = scenario.get("focal") or \
        (scenario.get("principals") or [{"principal_id": ""}])[0]["principal_id"]
    objective = scenario.get("objective") or {"kind": "phase", "phase": "done"}
    question = scenario.get("question", "stit")
    environment = scenario.get("environment", "none")
    path = primary_path(scenario)
    unknowns: list[str] = []
    for detector in (detect_identity_issue, detect_redaction_gap,
                     detect_missing_authority, detect_unreconciled_unknown,
                     detect_nonboolean_authority,
                     detect_unresolvable_delegation,
                     detect_effect_under_nonauthorised_standing):
        finding = detector(scenario)
        if finding:
            unknowns.append(finding)
    markers = set()
    for transition in game["transitions"]:
        markers.update(k for k in transition.get("args", {})
                       if k in ADVERSARIAL_MARKERS)
    if markers:
        unknowns.append("declared_adversarial_markers:" + ",".join(sorted(markers)))
    stit = models.stit_holds(game, focal, objective, path) \
        if len(path) >= 2 else {"holds": False, "reason": "history_too_short"}
    atl = models.atl_holds(game, [focal],
                           {"eventually": objective},
                           adversarial_env=environment == "adversarial")
    stit_definitive = stit["reason"] not in ("UNDERDETERMINED",)
    atl_underdetermined = atl.get("reason") == "UNDERDETERMINED"
    disagreement = bool(stit_definitive and atl_underdetermined)
    if disagreement:
        unknowns.append("model_disagreement:stit_definitive_atl_underdetermined")
    if unknowns:
        verdict = "UNDERDETERMINED"
        confidence = "UNDERDETERMINED"
    elif question == "atl":
        if atl.get("reason") == "UNDERDETERMINED":
            verdict = "UNDERDETERMINED"
            confidence = "UNDERDETERMINED"
        elif atl["holds"] and atl.get("reason") == "strategy_exists":
            verdict = "ATTRIBUTION"
            confidence = "PROVEN"
        else:
            verdict = "NO_ATTRIBUTION"
            confidence = "SUPPORTED"
    else:
        if stit["holds"]:
            verdict = "ATTRIBUTION"
            confidence = "PROVEN"
        else:
            verdict = "NO_ATTRIBUTION"
            confidence = "SUPPORTED"
    observed = [f"trace_digest:{trace_digest(scenario)}",
                f"focal:{focal}", f"path:{'>'.join(path)}",
                f"question:{question}"]
    derived = []
    if verdict == "ATTRIBUTION":
        engine = "stit" if question == "stit" else "atl"
        result = stit if question == "stit" else atl
        derived.append(f"{engine}:{result['holds']}:{result['reason']}:actor:{focal}")
    counterfactuals = []
    for choice in models.available_actions(game, path[-2] if len(path) >= 2 else path[0],
                                           focal):
        if choice["standing"] == "authorised":
            counterfactuals.append(f"alt:{choice['action']}")
    annotation = {
        "model_version": MODEL_VERSION,
        "input_trace_digest": trace_digest(scenario),
        "assumptions": ["bounded_model", "declared_choice_partition",
                        "adversarial_env_unless_modeled", "no_authority"],
        "observed_facts": observed,
        "derived_claims": derived,
        "unknowns": unknowns,
        "counterfactuals": counterfactuals,
        "confidence_class": confidence,
        "scope": dict(scenario.get("trace", {}).get("request_scope", {})),
        "created_at": "2026-09-05T00:00:00Z",
        "producer_id": f"s1-017-{placement}-seed{seed}",
        "authority": False,
        "supersedes": None,
    }
    return {"verdict": verdict, "confidence": confidence, "stit": stit, "atl": atl,
            "unknowns": unknowns, "disagreement": disagreement,
            "annotation": annotation}


def build_index(scenario: dict, analysis: dict) -> dict:
    """Placement B: versioned, recomputable choice/alternative index."""
    game = game_of(scenario)
    index = {"profile": "agentos.s1-017.choice-index/v1",
             "trace_digest": analysis["annotation"]["input_trace_digest"],
             "entries": []}
    for state in game["states"]:
        for principal in canonical_principals(scenario):
            index["entries"].append(
                {"state": state["state_id"], "actor": principal,
                 "choices": models.available_actions(game, state["state_id"],
                                                     principal)})
    index["digest"] = contract.digest(index)
    return index


def runtime_record(scenario: dict, analysis: dict) -> dict:
    """Placement C: minimal stored annotation (authority=false, versioned)."""
    return {"profile": "agentos.s1-017.runtime-annotation/v1",
            "version": 1,
            "trace_digest": analysis["annotation"]["input_trace_digest"],
            "verdict": analysis["verdict"],
            "confidence": analysis["confidence"],
            "authority": False,
            "provenance": {"model": MODEL_VERSION,
                           "producer": analysis["annotation"]["producer_id"]},
            "gateway_reads": []}


def authorization_dependency_scan(repo_root: Path) -> list[str]:
    """Machine check: gateway sources must never reference annotation fields."""
    hits = []
    for path in (repo_root / "src" / "agentos").glob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for token in ("resp_annotation", "responsibility_annotation",
                      "runtime_annotation", "choice-index", "choice_index"):
            if token in text:
                hits.append(f"{path.name}:{token}")
    return hits


def generate_observation(scenario: dict, placement: str, seed: int) -> dict:
    t0 = __import__("time").perf_counter_ns()
    analysis = analyze_scenario(scenario, placement, seed)
    t1 = __import__("time").perf_counter_ns()
    artifact: dict = {"kind": "none", "bytes": 0, "recomputable": True}
    if placement == "B":
        index = build_index(scenario, analysis)
        rebuilt = build_index(scenario, analysis)
        artifact = {"kind": "choice_index",
                    "bytes": len(contract.canonical(index)),
                    "recomputable": rebuilt["digest"] == index["digest"],
                    "digest": index["digest"]}
    elif placement == "C":
        record = runtime_record(scenario, analysis)
        artifact = {"kind": "runtime_annotation",
                    "bytes": len(contract.canonical(record)),
                    "recomputable": True,
                    "digest": contract.digest(record)}
    t2 = __import__("time").perf_counter_ns()
    core = {"scenario_id": scenario["scenario_id"], "placement": placement,
            "seed": seed,
            "observation_id": f"{scenario['scenario_id']}|{placement}|s{seed}",
            "status": "ok",
            "trace_digest": analysis["annotation"]["input_trace_digest"],
            "verdict": analysis["verdict"],
            "confidence": analysis["confidence"],
            "stit": analysis["stit"], "atl": analysis["atl"],
            "unknowns": analysis["unknowns"],
            "disagreement": analysis["disagreement"],
            "annotation": analysis["annotation"],
            "artifact": artifact}
    core["output_sha256"] = contract.digest(core)
    return {"core": core,
            "latencies": {"build_ns": t1 - t0, "artifact_ns": t2 - t1}}


def oracle_for(scenario: dict) -> dict:
    """Legacy helper retained ONLY for probe compatibility: derives the
    construction-intent oracle entry without running the analyzer."""
    kind = scenario["oracle_hint"]["kind"]
    verdict, confidence = {
        "stit_holds": ("ATTRIBUTION", "PROVEN"),
        "atl_holds": ("ATTRIBUTION", "PROVEN"),
        "stit_absent": ("NO_ATTRIBUTION", "SUPPORTED"),
        "atl_absent": ("NO_ATTRIBUTION", "SUPPORTED"),
        "underdetermined": ("UNDERDETERMINED", "UNDERDETERMINED"),
        "invalid": ("UNDERDETERMINED", "UNDERDETERMINED"),
    }[kind]
    return {"construction": kind,
            "expected_verdict": verdict,
            "expected_confidence": confidence,
            "expected_class": scenario["class"]}


def generate_matrix(ticket: Path, executor: str, seeds=(1, 2, 3)):
    cases = corpus_cases(ticket)
    observations = []
    for case in cases:
        for placement in PLACEMENTS:
            for seed in seeds:
                observations.append(generate_observation(case, placement, seed))
    observations.sort(key=lambda o: o["core"]["observation_id"])
    return observations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticket", required=False)
    parser.add_argument("--out", required=True)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--executor", required=False, default="A")
    parser.add_argument("--seeds", required=False, default="1,2,3")
    args = parser.parse_args()
    ticket = Path(args.ticket).resolve() if args.ticket else HERE
    target = Path(args.out)
    target.mkdir(parents=True, exist_ok=True)
    if not args.generate:
        print("only --generate is supported", file=sys.stderr)
        return 1
    if args.executor not in ("A", "B"):
        print("unknown executor", file=sys.stderr)
        return 1
    seeds = tuple(int(s) for s in args.seeds.split(","))
    import subprocess as _sp
    commit = _sp.run(["git", "rev-parse", "HEAD"], capture_output=True,
                     text=True, cwd=str(ticket.parents[3])).stdout.strip()
    observations = generate_matrix(ticket, args.executor, seeds)
    cores = [o["core"] for o in observations]
    manifest = {"schema": "agentos.s1-017.import-manifest/v1",
                "observations": len(cores), "executor": args.executor,
                "seeds": list(seeds),
                "corpus_sha256": sha((ticket / "corpus.json").read_bytes()),
                "ticket_commit": commit,
                "ok": sum(c.get("status") == "ok" for c in cores)}
    (target / "observations.json").write_text(
        json.dumps({"schema": "agentos.s1-017.observations/v1",
                    "executor": args.executor,
                    "observations": observations}, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    (target / "import-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest))
    return 0 if observations else 1


if __name__ == "__main__":
    raise SystemExit(main())
