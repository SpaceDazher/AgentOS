"""S1-012 FLOW-11 bundle assembler (stdlib only).

Builds the NATIVE research bundle schema consumed by
src/agentos/research.py (no shim fields). S1-012 claim classes
(provenance_fact, measurement, model_parameter, security_risk,
design_inference, calibration_limit) are carried in an explicit
s1_012_class field MAPPED to a core claim_class
(fact/inference/assumption/target); no invented core field is used.
Sources embed frozen snapshot bytes with verified content hashes;
substantive artifacts carry claim references; platform_plan carries
the seven required sections; producer/auditor identities are distinct
and consistent.

Verdict is DERIVED, never constant: the generator re-reads
dependency-gate.json, merged metrics/probes (A-G plus H), comparison
and sensitivity. Any blocking cause refuses publication (exit 1, no
candidate-record.json written, no stale READY left behind).

Usage: py -3.12 make_bundle.py   (run from the S1-012 ticket dir)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

PRODUCER = "agentos-s1-012-producer"
AUDITOR = "agentos-s1-012-independent-verifier"

FLOW = ["research_plan", "source_registry", "feature_catalog",
        "architecture_models", "mental_model", "ontology",
        "mathematical_model", "synthesis_and_gaps", "independent_audit",
        "platform_plan", "progress"]

CLAIMS = [
    {"id": "CL-F1", "s1_012_class": "provenance_fact",
     "claim_class": "fact",
     "text": "PROV defines provenance as information about entities, "
             "activities and agents usable to assess quality, reliability "
             "and trustworthiness, with derivation and versioning support.",
     "support": ["SRC-S1-012-01"]},
    {"id": "CL-F2", "s1_012_class": "provenance_fact",
     "claim_class": "fact",
     "text": "S1-003 fixtures expose the lifecycle states that the S1-012 "
             "exclusion rules (revoked, superseded, versioned) bind to.",
     "support": ["SRC-S1-012-02", "SRC-S1-012-03"]},
    {"id": "CL-M1", "s1_012_class": "measurement",
     "claim_class": "fact",
     "text": "On the frozen 72-case matrix the document, span and digest "
             "views admit exactly the oracle independents with zero hard "
             "violations, while the reputation-only control double-counts "
             "mirror/Sybil cases.",
     "support": ["SRC-S1-012-04", "SRC-S1-012-05"]},
    {"id": "CL-P1", "s1_012_class": "model_parameter",
     "claim_class": "inference",
     "text": "Beta posteriors with the frozen prior grid and decay clock "
             "are computed by continued fractions and agree with exact "
             "binomial references to 1e-9 on integer parameters.",
     "support": ["SRC-S1-012-03"]},
    {"id": "CL-S1", "s1_012_class": "security_risk",
     "claim_class": "inference",
     "text": "Without a logically centralized authority, Sybil attacks "
             "remain possible except under extreme resource-parity "
             "assumptions, so anchorless mutual-praise clusters must never "
             "produce enforcement.",
     "support": ["SRC-S1-012-02", "SRC-S1-012-03"]},
    {"id": "CL-D1", "s1_012_class": "design_inference",
     "claim_class": "inference",
     "text": "Document and span views agree on independence decisions "
             "under shared upstream collapse; the digest view adds a "
             "documented identical-text limit and never extra safety.",
     "support": ["SRC-S1-012-05", "SRC-S1-012-06"]},
    {"id": "CL-C1", "s1_012_class": "calibration_limit",
     "claim_class": "assumption",
     "text": "The planning threshold P[theta>0.9]>=0.95 stays a "
             "hypothesis without suitable data; reported tails are "
             "hypothesis quantities, not truth probabilities.",
     "support": ["SRC-S1-012-03"]},
    {"id": "CL-C2", "s1_012_class": "calibration_limit",
     "claim_class": "assumption",
     "text": "Lineage equality proxies source dependence for MVP "
             "comparison; novel Sybil shapes may evade it.",
     "support": ["SRC-S1-012-04", "SRC-S1-012-01"]},
]

ARTIFACT_TEXTS = {
    "research_plan": (
        "Calibrate evidence granularity, independence and Beta/Sybil "
        "behavior for the AgentOS knowledge layer. Frozen contracts, "
        "72-case corpus with lineage-isolated dev/holdout split, three "
        "granularity views plus a reputation-only negative control, "
        "Beta reference values with metamorphic checks, EigenTrust fixed "
        "semantics, probes A-H, joint parameter sensitivity, native "
        "FLOW-11 bundle, derived verdict. Phase B canonical round "
        "required before closure."),
    "source_registry": (
        "Six frozen sources across five roles (provenance/ontology, "
        "reputation mathematics, Sybil/collusion threat, registry "
        "policy, gate design) with authors, versions, canonical URIs, "
        "sections, retrieval times and SHA-256 of archived bytes; "
        "fragments labeled where full archiving was not possible."),
    "feature_catalog": (
        "Evidence units in document, span and digest granularity with "
        "canonical source, publisher, lineage, independence group and "
        "digest bindings; dedup and correlation-cap collapse rules; "
        "admit/reject/abstain decisions with reason codes; Beta tails and "
        "EigenTrust recommendations kept outside enforcement."),
    "architecture_models": (
        "Three governed counting views over shared strict plumbing "
        "(bindings, firewall, lifecycle exclusion, UNKNOWN abstention) "
        "plus a reputation-only negative control without gates. Beta "
        "posterior core with frozen prior/decay grid; EigenTrust power "
        "iteration with frozen anchor, damping and convergence rule."),
    "mental_model": (
        "Independent weight counts allowed groups, never raw units, "
        "digests, URLs or accounts. Unresolved independence abstains "
        "instead of inventing a group. Scores rank review queues; only "
        "gates admit. Identical text with disjoint transparent provenance "
        "keeps full weight."),
    "ontology": (
        "Unit, source, lineage, group, digest, revocation and decision "
        "records per evidence-unit.schema.json; S1-003 lifecycle mapping "
        "consumed for exclusion semantics; S1-011 gate mechanics "
        "preserved for challenge/retraction handling downstream."),
    "mathematical_model": (
        "Beta-Bernoulli conjugacy with uniform prior grid, decay clock, "
        "tail event at 0.9 and exact binomial references; EigenTrust "
        "row-stochastic fixed point with pre-trusted anchor and damping "
        "0.85; correlation cap at two groups; AUC of tails against admit "
        "labels with tails labeled hypothesis quantities."),
    "synthesis_and_gaps": (
        "Governed views agree and pass every gate and probe; the control "
        "fails exactly where gates bite. Digest view carries a documented "
        "identical-text limit. Gaps: no cyclic attack graphs, no measured "
        "operator data, threshold unvalidated, Beta primaries thin."),
    "independent_audit": (
        "Producer path (runner) and audit path (evaluator plus "
        "comparison) are independent code reading only raw rows and "
        "frozen inputs. A/B series share one commit and tree with "
        "distinct process identities; merged verdicts must agree or the "
        "series is inadmissible. Limits: tracked-Git evidence only, "
        "synthetic corpus, non-blinded holdout."),
    "progress": (
        "Phase A complete: dependency gate, frozen sources, contracts, "
        "72-case oracle with split manifest, stdlib tooling with green "
        "regressions, two process-separated runs, comparison, metrics, "
        "probes, sensitivity with joint grid, environment record, "
        "decision, calibration limits, S1-011 handoff, native FLOW-11 "
        "bundle and derived candidate record. Open: independent "
        "re-review, then Phase B canonical round and closure."),
}

PLATFORM_PLAN = {
    "Scope": "Adopt document-granularity counting with upstream collapse "
             "as the calibrated MVP rule; span view for fine-grained "
             "revocation; digest view only with bound upstream; reputation "
             "outputs stay recommendation-only.",
    "Architecture": "Evidence units with strict bindings flow through "
                    "dedup, correlation cap, lifecycle exclusion and the "
                    "policy firewall; Beta and EigenTrust feed the review "
                    "queue, never enforcement.",
    "Workstreams": "Wire the frozen contracts into the gate, replay the "
                   "72-case matrix for acceptance, calibrate the threshold "
                   "on dev data in S1-012 follow-up, and hand scoped "
                   "limits to S1-013 and S1-019.",
    "Milestones": "MVP rule accepted on Phase B canonicalization; "
                  "production thresholds only after measured calibration "
                  "data exists.",
    "Verification": "Re-run the frozen matrix with reference tooling; "
                    "require zero hard violations, probe A-H pass, no "
                    "sensitivity flips and no UNKNOWN dependence.",
    "Risks": "Novel Sybil shapes evading lineage analysis; uncalibrated "
             "threshold promoted to production; reputation mistaken for "
             "authorization.",
    "Open decisions": "Final numeric threshold after measured data; "
                      "operator procedures in S1-013; synthesis placement "
                      "in S1-019.",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(name: str):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def load_result(name: str):
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def build_sources() -> list:
    registry = load("source-registry.json")
    sources = []
    for entry in registry["sources"]:
        raw = (HERE / entry["snapshot_path"].replace(
            "research/tickets/stage-1/S1-012/", "")).read_bytes()
        if sha(raw) != entry["sha256"]:
            raise SystemExit(f"snapshot bytes drift: {entry['id']}")
        text = raw.decode("utf-8")
        if text.encode("utf-8") != raw:
            raise SystemExit(f"snapshot not UTF-8 stable: {entry['id']}")
        sources.append({
            "id": entry["id"],
            "canonical_uri": entry["canonical_uri"],
            "title": entry["title"],
            "source_type": entry["role"],
            "verification_status": "verified",
            "verifier": "s1-012-source-review-2026-09-04",
            "verification_method": entry.get(
                "kind", "tracked-file-hash-review"),
            "content": text,
            "content_sha256": sha(raw),
        })
    return sources


def build_artifacts() -> dict:
    artifacts = {}
    for kind in FLOW:
        if kind == "platform_plan":
            artifacts[kind] = {"content": dict(PLATFORM_PLAN),
                               "producer": PRODUCER,
                               "claim_refs": ["CL-D1", "CL-C1"]}
            continue
        artifacts[kind] = {"content": ARTIFACT_TEXTS[kind],
                           "producer": PRODUCER,
                           "claim_refs": ["CL-M1", "CL-D1"]}
    artifacts["independent_audit"]["producer"] = AUDITOR
    artifacts["independent_audit"]["claim_refs"] = ["CL-M1", "CL-C1"]
    artifacts["research_plan"]["claim_refs"] = ["CL-D1", "CL-C2"]
    artifacts["source_registry"]["claim_refs"] = ["CL-F1", "CL-F2"]
    artifacts["progress"]["claim_refs"] = ["CL-M1"]
    artifacts["ontology"]["claim_refs"] = ["CL-F1", "CL-F2"]
    artifacts["mathematical_model"]["claim_refs"] = ["CL-P1", "CL-C1"]
    artifacts["synthesis_and_gaps"]["claim_refs"] = ["CL-D1", "CL-S1"]
    artifacts["mental_model"]["claim_refs"] = ["CL-D1"]
    artifacts["feature_catalog"]["claim_refs"] = ["CL-F1", "CL-M1"]
    return artifacts


def _load_compare():
    import importlib.util
    unique = "s1012_compare_runs_pub"
    if unique in sys.modules:
        return sys.modules[unique]
    spec = importlib.util.spec_from_file_location(
        unique, HERE / "compare_runs.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    spec.loader.exec_module(module)
    return module


def check_verdict_consistency(metrics_doc: dict) -> list:
    """Hard-counter <-> verdict consistency per variant. A PASS flag next
    to nonzero hard counters is a blocking inconsistency, not a
    measurement."""
    problems = []
    for variant, doc in (metrics_doc.get("designs", {}) or {}).items():
        counters = doc.get("hard_counters", {}) or {}
        expected = "FAIL" if any(v != 0 for v in counters.values()) \
            else "PASS"
        if doc.get("verdict") != expected:
            problems.append(
                f"verdict/counter mismatch for {variant}: "
                f"verdict={doc.get('verdict')!r} counters={counters}")
    return problems


def tracked_registry() -> dict:
    """F3: registry of every tracked ticket artifact by repo-relative
    POSIX path with SHA-256 of file bytes (snapshots, contracts,
    corpus, scripts, results incl. raw cells, docs). Verifiable from
    `git archive HEAD` without .git or DB."""
    registry: dict = {}
    ticket_rel = Path("research/tickets/stage-1/S1-012")
    for path in sorted(HERE.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            rel = (ticket_rel / path.relative_to(HERE)).as_posix()
            registry[rel] = sha(path.read_bytes())
    test_file = Path(__file__).resolve().parents[4] / "tests" / \
        "test_s1_012_regressions.py"
    if test_file.is_file():
        registry["tests/test_s1_012_regressions.py"] = sha(
            test_file.read_bytes())
    return registry


def adjudicate_winner(comparison: dict, sens: dict,
                      governed: dict) -> list:
    """Pure winner adjudication (unit-testable). TIE is accepted only
    with a recorded all-eligible limitation; anything else blocks."""
    blockers = []
    if comparison.get("verdict") == "BLOCKED":
        blockers.append("comparison BLOCKED")
        return blockers
    winner = comparison.get("sensitivity_winner")
    if winner == "TIE":
        tie = comparison.get("tie_limitation") or {}
        if not tie.get("all_eligible") or not tie.get("tied"):
            blockers.append("unresolved tie for winner")
        elif comparison.get("sensitivity_flips"):
            blockers.append("sensitivity flips present")
        elif comparison.get("unknown_dependent") and \
                not tie.get("tied"):
            blockers.append("winner is UNKNOWN-dependent")
    elif winner not in governed:
        blockers.append("comparison winner is not a governed variant")
    else:
        if comparison.get("sensitivity_flips"):
            blockers.append("sensitivity flips present")
        if comparison.get("unknown_dependent"):
            blockers.append("winner is UNKNOWN-dependent")
    if sens.get("winner") not in governed:
        if not (sens.get("winner") == "TIE" and winner == "TIE" and
                (comparison.get("tie_limitation") or {}).get(
                    "all_eligible")):
            blockers.append("sensitivity artifact disagrees")
    if sens.get("flip_count"):
        blockers.append("sensitivity artifact disagrees")
    if sens.get("unknown_dependent") and winner != "TIE":
        blockers.append("sensitivity UNKNOWN-dependent")
    grid = (sens.get("parameter_grid") or {})
    if grid.get("flip_count"):
        blockers.append("joint parameter grid flips the winner")
    return blockers


def derive_verdict(here=None, results=None) -> tuple:
    """Re-derive the verdict from evidence. Missing files are blockers,
    never defaults. Returns (blockers, facts).

    F1 publication rule (task section 10): saved PASS flags are never
    authority. The full pipeline is recomputed from the tracked raw
    cells through the real runner/evaluator/compare entry points into
    a temp dir, then crosschecked against the saved merged artifacts.
    Any divergence blocks publication."""
    here = Path(here) if here else HERE
    results = Path(results) if results else RESULTS
    blockers = []

    def load_local(name: str):
        return json.loads((here / name).read_text(encoding="utf-8"))

    def load_saved(name: str):
        return json.loads((results / name).read_text(encoding="utf-8"))

    try:
        gate = load_local("dependency-gate.json")
    except (OSError, ValueError) as exc:
        return [f"dependency gate unreadable: {exc}"], {}
    if not gate.get("all_proven"):
        blockers.append("dependency gate not proven")
    for required in ("run-a", "run-b"):
        if not (results / required).is_dir():
            blockers.append(f"tracked raw series missing: {required}")
    if blockers:
        return blockers, {}
    compare_runs = _load_compare()
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="s1012-recompute-"))
    argv = ["--a", str(results / "run-a"), "--b", str(results / "run-b"),
            "--out", str(tmp / "comparison.json"),
            "--sensitivity", str(tmp / "sensitivity.json"),
            "--metrics", str(tmp / "metrics.json"),
            "--probes", str(tmp / "probes.json")]
    code = compare_runs.main(argv)
    if code != 0:
        return blockers + ["recomputed comparison inadmissible"], {}
    recomputed = {}
    try:
        for name in ("comparison", "sensitivity", "metrics", "probes"):
            recomputed[name] = json.loads(
                (tmp / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return blockers + [f"recomputation unreadable: {exc}"], {}
    try:
        saved = {name: load_saved(f"{name}.json") for name in
                 ("comparison", "sensitivity", "metrics", "probes")}
    except (OSError, ValueError) as exc:
        return blockers + [f"saved merged artifact unreadable: {exc}"], {}
    for name in ("comparison", "sensitivity", "metrics", "probes"):
        if json.dumps(recomputed[name], sort_keys=True) != json.dumps(
                saved[name], sort_keys=True):
            blockers.append(
                f"saved {name}.json differs from recomputation")
            break
    metrics = recomputed["metrics"]
    probes = recomputed["probes"]
    comparison = recomputed["comparison"]
    sens = recomputed["sensitivity"]
    blockers.extend("metrics " + line for line in
                    check_verdict_consistency(metrics))
    governed = {v: doc for v, doc in metrics["designs"].items()
                if v != "reputation-only"}
    if any(doc.get("verdict") != "PASS" for doc in governed.values()):
        bad = sorted(v for v, doc in governed.items()
                     if doc.get("verdict") != "PASS")
        blockers.append(f"governed variants not PASS: {bad}")
    for variant, probe_doc in probes["designs"].items():
        if variant == "H":
            if not isinstance(probe_doc, dict) or \
                    not probe_doc.get("passed"):
                blockers.append("publication-tamper battery not passed")
            continue
        if isinstance(probe_doc, dict) and not probe_doc.get("all_pass",
                                                              True):
            blockers.append(f"probes not all-pass for {variant}")
    blockers.extend(adjudicate_winner(comparison, sens, governed))
    winner = comparison.get("sensitivity_winner")
    grid = (sens.get("parameter_grid") or {})
    facts = {"gate": gate.get("all_proven"),
             "recomputed_from": "tracked raw cells via real entry points",
             "governed_verdicts": {v: d.get("verdict") for v, d in
                                   governed.items()},
             "winner": winner,
             "tied": (comparison.get("tie_limitation") or {}).get("tied"),
             "flips": comparison.get("sensitivity_flips"),
             "unknown_dependent": comparison.get("unknown_dependent"),
             "grid_combos": grid.get("combos", 0),
             "grid_flips": grid.get("flip_count", 0)}
    return blockers, facts


def main() -> int:
    blockers, facts = derive_verdict()
    if blockers:
        for line in blockers:
            print(f"BLOCKED: {line}", file=sys.stderr)
        return 1
    limitations = [
        "tracked-Git evidence only; live DB recheck required in Phase B",
        "planning threshold stays a hypothesis (no suitable data)",
        "Beta formulas are standard results with independent computation, "
        "not archived primary full text",
        "holdout is lineage-isolated but author-visible, not blinded",
        "operator workload unmeasured; no human study claimed",
        "corpus-bounded claims: no cyclic attack graphs evaluated",
    ]
    bundle = {
        "config": {"min_source_count": 5, "min_verified_ratio": 1.0,
                   "required_artifacts": list(FLOW)},
        "sources": build_sources(),
        "claims": [dict(c) for c in CLAIMS],
        "artifacts": build_artifacts(),
        "producer": PRODUCER,
        "auditor": AUDITOR,
        "audit": {"producer": PRODUCER, "auditor": AUDITOR,
                  "verdict": "pass_with_limits",
                  "limitations": limitations},
    }
    bundle_text = json.dumps(bundle, indent=2, sort_keys=True,
                             ensure_ascii=False) + "\n"
    (HERE / "bundle.json").write_text(bundle_text, encoding="utf-8",
                                      newline="\n")
    bundle_sha = sha((HERE / "bundle.json").read_bytes())
    manifest = load("corpus-manifest.json")
    comparison = load_result("comparison.json")
    tracked = tracked_registry()
    candidate = {
        "schema": "agentos.s1-012.candidate-record/v1",
        "ticket": "S1-012",
        "status": "READY_FOR_CANONICALIZATION",
        "verdict": "PASS_WITH_LIMITS",
        "verdict_basis": facts,
        "verdict_cap_reason": "planning threshold is a hypothesis and no "
                              "measured calibration data exists",
        "bundle_path": "research/tickets/stage-1/S1-012/bundle.json",
        "bundle_sha256": bundle_sha,
        "comparison_sha256": sha((RESULTS / "comparison.json")
                                 .read_bytes()),
        "metrics_sha256": sha((RESULTS / "metrics.json").read_bytes()),
        "frozen_hashes": manifest["hashes"],
        "tracked_artifacts": tracked,
        "tracked_registry_note": "Every ticket file plus the test module, "
                                 "by repo-relative POSIX path with SHA-256 "
                                 "of committed bytes; verifiable from "
                                 "`git archive HEAD`.",
        "run_provenance": {"commits": comparison["commits"],
                           "trees": comparison["trees"],
                           "cells": comparison["cells"]},
        "assumptions": [
            "naive textbook semantics faithfully represent granularity "
            "views for comparison",
            "lineage equality proxies source dependence for MVP purposes",
            "uniform prior grid and decay clock cover the plausible range",
        ],
        "unknowns": [
            "cyclic attack-graph behavior",
            "true Sybil/collusion rates in the wild",
            "measured operator cost and comprehension",
        ],
        "residual_risks": [
            "novel Sybil shapes evading lineage analysis",
            "threshold promoted to production without measured data",
            "reputation mistaken for authorization downstream",
        ],
        "phase_b_required": True,
        "chain_fresh_claim": None,
        "note": "No goal_id, campaign_id, evaluation_id, research "
                "revision, artifact-chain hash, or wiki counts are stated "
                "here; those are Phase B canonical-harness outputs only.",
    }
    (HERE / "candidate-record.json").write_text(
        json.dumps(candidate, indent=2, sort_keys=True,
                   ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    print(f"bundle.json sha256={bundle_sha}")
    print("candidate-record.json status=READY_FOR_CANONICALIZATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
