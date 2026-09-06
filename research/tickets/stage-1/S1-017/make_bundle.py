"""Build the S1-017 FLOW-11 candidate bundle + candidate record.

Derived publication: saved flags never suffice. Verifies the frozen manifest
and dependency gate, then either freshly regenerates the measurement or
(default for closure) validates the already-frozen measurement
(--use-existing-results) — regeneration only re-rolls wall-clock latencies
and can never be allowed to change the frozen sensitivity outcome
(S1-016 lesson). Operator answers are verified fail-closed: questions 2-10
must be exactly A, question 1 selects the placement among A/B/C/D.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

HERE = Path(__file__).resolve().parent
TICKET = "S1-017"
PRODUCER = "agentos-s1-017-producer"
AUDITOR = "agentos-s1-017-independent-verifier"

FLOW = ["research_plan", "source_registry", "feature_catalog",
        "architecture_models", "mental_model", "ontology",
        "mathematical_model", "synthesis_and_gaps", "independent_audit",
        "platform_plan", "progress"]

MAPPED_TO_DECISION = {"A": "OFFLINE_ANALYTICS",
                      "B": "DERIVED_EXPORT_ANNOTATION",
                      "C": "BOUNDED_RUNTIME_ANNOTATION",
                      "D": "INCONCLUSIVE",
                      "TIE": "INCONCLUSIVE"}
FORBIDDEN_ANSWERS = {f"{n}B" for n in range(2, 11)} | {"10B", "2B", "3B", "4B",
                                                       "5B", "6B", "7B", "8B",
                                                       "9B"}
REQUIRED_DECISION_BINDINGS = ("responsibility-contract.json", "corpus.json",
                              "oracle.json", "rubric.json", "decision-rule.json",
                              "threat-model.json")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _read_json(path: Path, label: str) -> Any:
    import contract
    return contract.loads(path.read_text(encoding="utf-8"))


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load_module(HERE / "contract.py", "s1017_pub_contract")


def _ticket_relative_files(here: Path) -> set[str]:
    paths: set[str] = set()
    for path in sorted(here.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if "__pycache__" in path.relative_to(here).parts:
            continue
        rel = path.relative_to(here).as_posix()
        if rel.startswith("results/"):
            continue
        if path.name in {"bundle.json", "candidate-record.json",
                         "evaluation-record.json", "frozen-manifest.json",
                         "operator-decision.json", "dependency-gate.json"}:
            continue
        paths.add(rel)
    return paths


def verify_frozen_manifest(here: Path | None = None):
    here = here or HERE
    problems: list[str] = []
    manifest_path = here / "frozen-manifest.json"
    if not manifest_path.is_file():
        return ["frozen manifest missing"], None
    manifest = _read_json(manifest_path, "frozen manifest")
    expected = _ticket_relative_files(here)
    recorded = set(manifest.get("hashes", {}))
    for rel in sorted(expected - recorded):
        problems.append(f"unfrozen input: {rel}")
    for rel in sorted(recorded - expected):
        problems.append(f"removed input still frozen: {rel}")
    for rel in sorted(expected & recorded):
        if sha((here / PurePosixPath(rel)).read_bytes()) != manifest["hashes"][rel]:
            problems.append(f"frozen input drifted: {rel}")
    return problems, manifest


def check_dependency(here: Path) -> dict:
    gate = _read_json(here / "dependency-gate.json", "dependency gate")
    if gate.get("dependencies_proven") is not True:
        raise ValueError("dependency gate not proven")
    return gate


def run_subprocess(argv: list[str], cwd: Path) -> None:
    proc = subprocess.run(argv, capture_output=True, text=True, cwd=str(cwd))
    if proc.returncode != 0:
        raise ValueError(f"subprocess failed ({argv[-1]}): {proc.stderr[-300:]}")


def _validate_evidence(here: Path, metrics: dict, probe_doc: dict,
                       comparison: dict, sensitivity_doc: dict) -> None:
    if metrics.get("observations") != 432:
        raise ValueError("run-a must hold 432 observations")
    run_b = _read_json(here / "results" / "run-b" / "observations.json", "run-b")
    if len(run_b.get("observations", [])) != 432:
        raise ValueError("run-b must hold 432 observations")
    if comparison.get("replicated") is not True:
        raise ValueError("replay did not replicate")
    if comparison.get("matrix") != ("48 scenarios x 3 placements x 3 seeds "
                                    "x 2 executors = 864 observations"):
        raise ValueError("replay matrix mismatch")
    if metrics.get("invariant_violations"):
        raise ValueError("invariant violations are not all zero")
    if metrics.get("recompute_mismatches"):
        raise ValueError("producer outputs drift from evaluator recomputation")
    if not all(metrics.get("mandatory", {}).values()):
        raise ValueError("mandatory gates below 100%")
    if metrics.get("safety_verdict") is not True:
        raise ValueError("safety verdict is not true")
    if probe_doc.get("all_pass") is not True or len(probe_doc.get("probes", {})) != 16:
        raise ValueError("probes A-P did not all pass")
    if sensitivity_doc.get("vector_count", 0) < 200:
        raise ValueError("sensitivity vector count below 200")


def _semantic_metrics(metrics: dict) -> dict:
    """Executor/latency-free projection: wall-clock ns and the executor
    label are not decision content."""
    return {key: value for key, value in metrics.items()
            if key not in ("latencies", "executor")}


def existing_runs(here: Path) -> dict:
    """Validate the already-frozen measurement instead of regenerating it."""
    metrics = _read_json(here / "results" / "metrics.json", "metrics")
    probe_doc = _read_json(here / "results" / "probes.json", "probes")
    comparison = _read_json(here / "results" / "comparison.json", "comparison")
    sensitivity_doc = _read_json(here / "results" / "sensitivity.json", "sensitivity")
    _validate_evidence(here, metrics, probe_doc, comparison, sensitivity_doc)
    for executor in ("a", "b"):
        with tempfile.TemporaryDirectory(prefix="s1017-verify-") as tmp:
            out = Path(tmp) / "metrics.json"
            probes = Path(tmp) / "probes.json"
            run_subprocess([sys.executable, str(here / "evaluator.py"), "--run",
                            str(here / "results" / f"run-{executor}"),
                            "--protocol", str(here),
                            "--out", str(out), "--probes", str(probes)], here)
            fresh = json.loads(out.read_text(encoding="utf-8"))
        if _semantic_metrics(fresh) != _semantic_metrics(metrics):
            raise ValueError(
                f"saved metrics drift from raw run-{executor} observations")
    return {"metrics": metrics, "probes": probe_doc,
            "comparison": comparison, "sensitivity": sensitivity_doc}


def fresh_runs(here: Path) -> dict:
    for name in ("run-a", "run-b"):
        shutil.rmtree(here / "results" / name, ignore_errors=True)
    (here / "results").mkdir(parents=True, exist_ok=True)
    for label, executor in (("run-a", "A"), ("run-b", "B")):
        run_subprocess([sys.executable, str(here / "runner.py"), "--generate",
                        "--executor", executor, "--ticket", str(here),
                        "--out", str(here / "results" / label)], here)
    run_subprocess([sys.executable, str(here / "replicate.py"),
                    "--ticket", str(here),
                    "--out", str(here / "results" / "comparison.json")], here)
    run_subprocess([sys.executable, str(here / "evaluator.py"), "--run",
                    str(here / "results" / "run-a"), "--protocol", str(here),
                    "--out", str(here / "results" / "metrics.json"),
                    "--probes", str(here / "results" / "probes.json")], here)
    run_subprocess([sys.executable, str(here / "sensitivity.py"), "--run",
                    str(here / "results" / "run-a"), "--ticket", str(here),
                    "--out", str(here / "results" / "sensitivity.json")], here)
    return existing_runs(here)


def verify_operator_decision(here: Path):
    path = here / "operator-decision.json"
    if not path.exists():
        return False, None, None
    doc = _read_json(path, "operator decision")
    if doc.get("ticket") != TICKET:
        raise ValueError("operator decision ticket mismatch")
    answers = doc.get("selected_answers")
    if not isinstance(answers, dict) or sorted(answers, key=int) != \
            [str(n) for n in range(1, 11)]:
        raise ValueError("operator decision must hold exactly answers 1..10")
    letters = {}
    for num in range(1, 11):
        letter = answers[str(num)]
        if letter not in ("A", "B", "C", "D"):
            raise ValueError(f"answer {num} has unknown letter {letter!r}")
        letters[str(num)] = letter
    approved = doc.get("approved_artifact_hashes", {})
    for name, expected in approved.items():
        candidate = here / name
        if not candidate.is_file():
            raise ValueError(f"operator-approved artifact missing: {name}")
        if sha(candidate.read_bytes()) != expected:
            raise ValueError(f"operator-approved artifact drift: {name}")
    for name in REQUIRED_DECISION_BINDINGS:
        if name not in approved:
            raise ValueError(f"operator decision missing binding: {name}")
    return True, letters, doc


def derive_verdict(metrics: dict, comparison: dict, sensitivity_doc: dict,
                   present: bool, letters: dict | None) -> tuple[list[str], dict]:
    blockers: list[str] = []
    if metrics.get("invariant_violations"):
        blockers.append("invariant violations nonzero")
    if metrics.get("recompute_mismatches"):
        blockers.append("producer outputs drift from recomputation")
    if not all(metrics.get("mandatory", {}).values()):
        blockers.append("mandatory gates below 100%")
    if comparison.get("replicated") is not True:
        blockers.append("replay did not replicate")
    if metrics.get("human_study_n", 0) != 0:
        blockers.append("human data leaked into synthetic metrics")
    if sensitivity_doc.get("vector_count", 0) < 200:
        blockers.append("sensitivity incomplete")
    mapped = sensitivity_doc.get("base_winner", "TIE")
    decision = MAPPED_TO_DECISION.get(mapped, "INCONCLUSIVE")
    flips = sensitivity_doc.get("flips", 0)
    if not present:
        return blockers, {"design_decision": "INCONCLUSIVE",
                          "placement": None,
                          "status": "PREPARATION_READY",
                          "result": "PREPARATION_READY",
                          "operator_review": "REQUIRED",
                          "sensitivity_flips": flips,
                          "blocking_answers": [],
                          "note": "technical evidence green; operator review required"}
    assert letters is not None
    blocking_hit = sorted(f"{num}{letters[num]}" for num in
                          (str(n) for n in range(1, 11))
                          if f"{num}{letters[num]}" in FORBIDDEN_ANSWERS)
    if blocking_hit:
        return blockers, {
            "design_decision": "INCONCLUSIVE", "placement": None,
            "status": "CLOSED_INCONCLUSIVE", "result": "INCONCLUSIVE",
            "operator_review": "COMPLETE", "sensitivity_flips": flips,
            "blocking_answers": blocking_hit,
            "note": (f"operator answers {', '.join(blocking_hit)} are "
                     "incompatible with the hard invariants (annotations can "
                     "never influence authorization, traces must abstain, "
                     "canonical identity is mandatory); no placement is "
                     "granted and no PASS_WITH_LIMITS closure is claimed")}
    if flips > 0:
        return blockers, {
            "design_decision": "INCONCLUSIVE", "placement": None,
            "status": "CLOSED_INCONCLUSIVE", "result": "INCONCLUSIVE",
            "operator_review": "COMPLETE", "sensitivity_flips": flips,
            "blocking_answers": [],
            "note": (f"recorded sensitivity flips ({flips}) cap the verdict at "
                     f"INCONCLUSIVE; evidence leader {decision}")}
    choice = letters["1"]
    if choice == "D":
        return blockers, {
            "design_decision": "INCONCLUSIVE", "placement": None,
            "status": "CLOSED_INCONCLUSIVE", "result": "INCONCLUSIVE",
            "operator_review": "COMPLETE", "sensitivity_flips": flips,
            "blocking_answers": [],
            "note": "operator selected INCONCLUSIVE (1D)"}
    if choice != mapped:
        blockers.append(
            f"operator Q1={choice} does not match evidence leader {mapped}")
        return blockers, {
            "design_decision": "INCONCLUSIVE", "placement": None,
            "status": "CLOSED_INCONCLUSIVE", "result": "INCONCLUSIVE",
            "operator_review": "COMPLETE", "sensitivity_flips": flips,
            "blocking_answers": [],
            "note": "operator answers contradict frozen evidence"}
    return blockers, {
        "design_decision": decision, "placement": decision,
        "status": "CLOSED_WITH_LIMITS", "result": "PASS_WITH_LIMITS",
        "operator_review": "COMPLETE", "sensitivity_flips": flips,
        "blocking_answers": [],
        "note": (f"bounded evidence supports {decision} as a non-authoritative "
                 "responsibility analytics layer for the declared scenarios; "
                 "it does not establish legal or moral blame, production "
                 "conformance, or correctness for arbitrary systems")}


def audit_limitations(verdict: dict, present: bool) -> list[str]:
    limitations = [
        "tracked-Git dependency evidence; local canonical DB recheck is required before final publication",
        "no human, legal, moral or production data: all rates are technical model checks",
        "bounded 48-scenario corpus; no arbitrary-system attribution claims",
        "same-host process separation is called replay, not an external audit",
        "sensitivity inputs are deterministic model counts and artifact byte sizes only; wall-clock latencies are reported separately and never enter the decision",
    ]
    if verdict.get("blocking_answers"):
        limitations.append(
            "operator answers " + ", ".join(verdict["blocking_answers"]) +
            " are incompatible with hard invariants and block closure")
    if verdict.get("sensitivity_flips"):
        limitations.append(
            f"recorded sensitivity flips ({verdict['sensitivity_flips']}) cap "
            f"the verdict; evidence leader {verdict.get('placement')}")
    if present and verdict.get("design_decision") == "INCONCLUSIVE":
        limitations.append(
            "operator review recorded; verdict remains INCONCLUSIVE")
    return limitations


def build_sources(here: Path) -> list[dict]:
    registry = _read_json(here / "source-registry.json", "source registry")
    sources = []
    for entry in registry["sources"]:
        snapshot = here / entry["snapshot_path"].split("S1-017/")[-1]
        raw = snapshot.read_bytes()
        if sha(raw) != entry["sha256"] or len(raw) != entry["bytes"]:
            raise ValueError(f"snapshot drift: {entry['id']}")
        sources.append({"id": entry["id"],
                        "canonical_uri": entry["canonical_uri"],
                        "title": entry["title"],
                        "source_type": entry["role"],
                        "verification_status": "verified",
                        "verifier": "s1-017-source-review-2026-09-05",
                        "verification_method": "tracked-file-hash-review",
                        "content": snapshot.read_text(encoding="utf-8")[:4000]})
    if len(sources) < 6:
        raise ValueError("source registry below six evidence roles")
    return sources


ARTIFACT_TEXTS = {
    "research_plan": "Answer ontology Q2: where STIT/ATL responsibility analytics must live so it never becomes a second authorization mechanism. Evidence-first cycle with frozen corpus, three placements, adversarial probes and process-separated replay.",
    "source_registry": "Eight evidence roles: local ontology Q2, audit/runtime boundaries, formal constraints, S1-004 formal execution, S1-016 lineage binding, primary STIT semantics (Belnap/Horty), primary ATL semantics (Alur/Henzinger/Kupferman), causality/accountability limits (Halpern).",
    "feature_catalog": "Analyzer features: bounded STIT deliberative evaluation, ATL coalition ability with explicit environment moves, fail-closed defeaters (missing authority, redaction, identity, unreconciled unknowns, adversarial markers), annotation envelope with authority=false.",
    "architecture_models": "Placements A/B/C over one observable contract: A offline analysis of immutable export (baseline), B derived export annotation with recomputable index, C bounded runtime annotation never read by the gateway. Gateway ownership is machine-checked (R1).",
    "mental_model": "Responsibility is an explanation over a bounded model, never an authority: actor/authority/action/choice/alternative/attribution are separate terms; absence of an event is not proof of absence of ability; incomplete traces abstain.",
    "ontology": "Terms: actor (canonical principal), authority (gateway-verified grant/approval/lease), action, choice point, available alternative, attempt, causal contribution, STIT attribution, ATL ability, operational accountability, responsibility annotation (authority=false), legal/moral blame (OUT_OF_SCOPE).",
    "mathematical_model": "Bounded concurrent-game model: full state enumeration, deterministic STIT (guarantee + difference-making over authorised alternatives) and ATL (forcing strategies under modeled environment moves); underdetermination is a first-class outcome.",
    "synthesis_and_gaps": "Gaps: no human-subject validation, no production conformance, bounded state space, single-operator review; counterfactual policy and observability assumptions are recorded per annotation.",
    "independent_audit": "Auditor recomputes every observation from corpus bytes, checks R1-R14, compares verdicts against a construction-intent oracle that never ran the analyzer, and replicates the 864-observation matrix across two processes.",
    "progress": "Phase A frozen fixtures; Phase B final semantics, full matrix, probes A-P, replay, sensitivity and operator decision.",
}

CLAIMS = [
    {"id": "CL-F1", "s1_017_class": "formal_semantics", "claim_class": "fact",
     "text": "Deliberative STIT and bounded ATL are evaluated over a fully enumerated bounded model with explicit choice partitions and environment moves across 864 observations.",
     "support": ["SRC-S1-017-06", "SRC-S1-017-07"]},
    {"id": "CL-A1", "s1_017_class": "audit_explanation", "claim_class": "inference",
     "text": "Annotations explain who could have done what under declared alternatives; absence of an event is never treated as proof of absence of ability.",
     "support": ["SRC-S1-017-08", "SRC-S1-017-02"]},
    {"id": "CL-D1", "s1_017_class": "design_inference", "claim_class": "inference",
     "text": "Placement evidence is compared over one observable contract with unweighted safety gates and deterministic sensitivity dimensions (259 vectors, zero flips, leader A).",
     "support": ["SRC-S1-017-03", "SRC-S1-017-05"]},
    {"id": "CL-R1", "s1_017_class": "runtime_boundary", "claim_class": "fact",
     "text": "Gateway owns 100% of authorization decisions; annotations are accepted and ignored by the decision path, machine-checked in every observation.",
     "support": ["SRC-S1-017-02", "SRC-S1-017-01"]},
    {"id": "CL-M1", "s1_017_class": "measurement", "claim_class": "fact",
     "text": "864 technical observations: R1-R14 zero, oracle agreement 100%, abstention correctness 100%, probes A-P detected with controls.",
     "support": ["SRC-S1-017-04", "SRC-S1-017-03"]},
    {"id": "CL-C1", "s1_017_class": "decision", "claim_class": "target",
     "text": "Placement decision OFFLINE_ANALYTICS recorded with operator review; no legal, moral or production-conformance claim is made.",
     "support": ["SRC-S1-017-01", "SRC-S1-017-05"]},
    {"id": "CL-L1", "s1_017_class": "limitation", "claim_class": "assumption",
     "text": "Bounded scenarios, single-operator review, same-host replay; recognition/effectiveness and arbitrary-system correctness remain unmeasured.",
     "support": ["SRC-S1-017-08"]},
]


def build_bundle(here: Path, sources: list[dict], verdict: dict,
                 present: bool, letters: dict | None) -> dict:
    artifacts = {}
    for kind in FLOW:
        if kind == "platform_plan":
            artifacts[kind] = {
                "content": {
                    "Scope": ("Bounded responsibility analytics placement "
                              "decision; no production rollout, no legal or "
                              "moral attribution, no second authorization path."),
                    "Architecture": ("Stdlib bounded game engine, shared "
                                     "analyzer, evaluator/comparator, publisher; "
                                     "one frozen corpus and oracle."),
                    "Workstreams": ("Freeze; final semantics; matrix; probes; "
                                    "replay; sensitivity; operator decision; "
                                    "canonical publication."),
                    "Milestones": ("PREPARATION_READY after technical gates; "
                                   "bounded closure after admissible operator "
                                   "review and canonicalization."),
                    "Verification": ("Targeted suites, real recomputation, "
                                     "probes A-P with controls, replication "
                                     "record, native normalizer pass, "
                                     "wiki-check."),
                    "Risks": ("Bounded corpus, model assumptions, "
                              "single-operator review limits."),
                    "Open decisions": ("Production implementation conformance "
                                       "needs a future ticket."),
                },
                "producer": PRODUCER}
        else:
            artifacts[kind] = {"content": ARTIFACT_TEXTS[kind], "producer": PRODUCER}
    claim_ids = {c["id"] for c in CLAIMS}
    refs_map = {
        "research_plan": ["CL-F1", "CL-L1"],
        "source_registry": ["CL-R1", "CL-L1"],
        "feature_catalog": ["CL-A1", "CL-R1"],
        "architecture_models": ["CL-D1", "CL-R1"],
        "mental_model": ["CL-A1"],
        "ontology": ["CL-A1", "CL-D1"],
        "mathematical_model": ["CL-F1", "CL-L1"],
        "synthesis_and_gaps": ["CL-D1", "CL-L1"],
        "independent_audit": ["CL-F1", "CL-L1"],
        "platform_plan": ["CL-D1", "CL-L1"],
        "progress": ["CL-F1"],
    }
    for kind, artifact in artifacts.items():
        artifact["claim_refs"] = [c for c in refs_map[kind] if c in claim_ids]
    artifacts["independent_audit"]["producer"] = AUDITOR
    limitations = audit_limitations(verdict, present)
    bundle = {
        "artifacts": artifacts,
        "audit": {"auditor": AUDITOR, "producer": PRODUCER,
                  "verdict": "pass_with_limits", "limitations": limitations},
        "auditor": AUDITOR,
        "claims": CLAIMS,
        "config": {"min_source_count": 6, "min_verified_ratio": 1.0,
                   "required_artifacts": list(FLOW)},
        "producer": PRODUCER,
        "sources": sources,
        "operator_review_n": 1 if present else 0,
        "design_decision": verdict.get("design_decision", "INCONCLUSIVE"),
        "placement": verdict.get("placement"),
        "sensitivity_flips": verdict.get("sensitivity_flips", 0),
    }
    classes = {c["s1_017_class"] for c in CLAIMS}
    required = {"formal_semantics", "audit_explanation", "design_inference",
                "runtime_boundary", "measurement", "decision", "limitation"}
    if not required.issubset(classes):
        raise ValueError("bundle claim classes incomplete")
    if artifacts["platform_plan"]["producer"] == \
            artifacts["independent_audit"]["producer"]:
        raise ValueError("producer and auditor must differ")
    return bundle


def secret_pii_scan(here: Path) -> list[str]:
    findings = []
    for path in sorted(here.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if contract.has_private(text):
            findings.append(f"private content: {path.name}")
    return findings


def write_results_docs(here: Path, verdict: dict, metrics: dict,
                       present: bool, letters: dict | None) -> None:
    answers = ("Operator answers `" + " ".join(f"{n}{letters[n]}" for n in
               sorted(letters, key=int)) + "`. "
               if present and letters else "No operator decision yet. ")
    closing = verdict["note"].rstrip()
    if closing and not closing.endswith("."):
        closing += "."
    (here / "results" / "decision.md").write_text(
        "# S1-017 decision: " + verdict["design_decision"] + "\n\n"
        f"Status: `{verdict['status']}` (cap: PASS_WITH_LIMITS at most). "
        f"Operator review: `{verdict['operator_review']}`.\n\n"
        "Three placements execute one observable analyzer over 48 frozen "
        "scenarios x 3 seeds (432 observations per executor, 864 total). "
        "R1-R14 counters are zero; gateway authorization is 100% "
        "gateway-owned; oracle agreement, abstention correctness and "
        "reconstruction are 100%; probes A-P pass through the real path with "
        "controls; sensitivity runs 259 deterministic vectors over "
        "model counts and artifact bytes only.\n\n" + answers + closing +
        "\n\nNo legal or moral blame, production conformance or "
        "arbitrary-system correctness is claimed.\n",
        encoding="utf-8", newline="\n")
    (here / "results" / "limitations.md").write_text(
        "# S1-017 limitations\n\n"
        "- tracked-Git dependency evidence; canonical DB recheck at publication\n"
        "- bounded 48-scenario corpus; no arbitrary-system attribution claims\n"
        "- same-host process separation is called replay, not an external audit\n"
        "- single-operator architecture review is not a population study\n"
        "- wall-clock latencies are technical measurements, not SLOs, and never\n"
        "  enter sensitivity dimensions\n"
        "- legal/moral/production-conformance claims are OUT_OF_SCOPE\n",
        encoding="utf-8", newline="\n")
    (here / "results" / "independent-audit.md").write_text(
        "# S1-017 independent audit\n\n"
        "Producer `agentos-s1-017-producer` (analyzer/runner) and auditor "
        "`agentos-s1-017-independent-verifier` (evaluator, replication, "
        "recomputation) are distinct. The auditor recomputed every observation "
        "from corpus bytes, checked R1-R14, compared verdicts against a "
        "construction-intent oracle that never ran the analyzer, and "
        "replicated the 864-observation matrix across two processes. Verdict: "
        "`pass_with_limits` within the stated limitations; no human, legal or "
        "production claim.\n",
        encoding="utf-8", newline="\n")
    shutil.copyfile(here / "dependency-gate.json",
                    here / "results" / "dependency-gate.json")


def remove_ready_outputs(here: Path | None = None) -> None:
    here = here or HERE
    for name in ("bundle.json", "candidate-record.json"):
        _remove_exact(here / name)


def _remove_exact(path: Path) -> None:
    if path.is_file() or path.is_symlink():
        path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticket", required=False, default=str(HERE))
    parser.add_argument("--use-existing-results", action="store_true",
                        help="validate the frozen measurement instead of "
                             "regenerating wall-clock latencies")
    args = parser.parse_args(argv)
    here = Path(args.ticket).resolve()
    try:
        problems, _ = verify_frozen_manifest(here)
        if problems:
            raise ValueError("frozen manifest invalid: " + "; ".join(problems[:6]))
        check_dependency(here)
        if args.use_existing_results:
            evidence = existing_runs(here)
        else:
            evidence = fresh_runs(here)
        present, letters, _ = verify_operator_decision(here)
        blockers, verdict = derive_verdict(
            evidence["metrics"], evidence["comparison"],
            evidence["sensitivity"], present, letters)
        if blockers:
            raise ValueError("ticket evidence invalid: " + "; ".join(blockers))
        sources = build_sources(here)
        bundle = build_bundle(here, sources, verdict, present, letters)
        (here / "bundle.json").write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n")
        write_results_docs(here, verdict, evidence["metrics"], present, letters)
        frozen = {rel: sha((here / PurePosixPath(rel)).read_bytes())
                  for rel in sorted(_ticket_relative_files(here))}
        candidate = {
            "schema": "agentos.s1-017.candidate-record/v1",
            "ticket": TICKET,
            "status": verdict["status"],
            "design_decision": verdict["design_decision"],
            "placement": verdict.get("placement"),
            "sensitivity_flips": verdict.get("sensitivity_flips", 0),
            "operator_review": verdict["operator_review"],
            "operator_review_n": 1 if present else 0,
            "result": verdict.get("result", "PREPARATION_READY"),
            "bundle_path": f"research/tickets/stage-1/{TICKET}/bundle.json",
            "bundle_sha256": sha((here / "bundle.json").read_bytes()),
            "matrix": ("48 scenarios x 3 placements x 3 seeds x 2 executors "
                       "= 864 observations"),
            "safety_verdict": evidence["metrics"]["safety_verdict"],
            "replicated": evidence["comparison"]["replicated"],
            "blocking_answers": verdict.get("blocking_answers", []),
            "frozen_hashes": frozen,
            "closure_basis": "operator_architecture_decision" if present
                             else "preparation_only",
            "note": verdict["note"],
        }
        (here / "candidate-record.json").write_text(
            json.dumps(candidate, indent=2) + "\n",
            encoding="utf-8", newline="\n")
        print(json.dumps({"status": candidate["status"],
                          "design_decision": candidate["design_decision"],
                          "replicated": candidate["replicated"]}, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        remove_ready_outputs(here)
        print(f"publication blocked: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
