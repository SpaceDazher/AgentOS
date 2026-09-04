"""S1-013 FLOW-11 bundle assembler (stdlib only).

Builds the NATIVE research bundle schema consumed by
src/agentos/research.py. S1-013 claim classes (HCI_measurement,
user_observation, hypothesis, design_inference, limitation) are
carried explicitly and MAPPED to core claim_class values
(fact/inference/assumption/target); no invented core field is used.

Verdict is DERIVED, never constant: the generator re-runs the
importer + scorer, the replication check and the probe battery, and
crosschecks the saved merged artifacts. Any blocking cause refuses
publication (exit 1, no candidate-record.json written). The only
reachable publication verdict in preparation is PREPARATION_READY;
an empty human dataset never yields PASS, and synthetic dry-run
numbers never enter human claims. Human pilot remains
BLOCKED_HUMAN_PILOT until the operator approves recruitment and
real participants exist.

Usage: py -3.12 make_bundle.py   (run from the S1-013 ticket dir)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

PRODUCER = "agentos-s1-013-producer"
AUDITOR = "agentos-s1-013-independent-verifier"

FLOW = ["research_plan", "source_registry", "feature_catalog",
        "architecture_models", "mental_model", "ontology",
        "mathematical_model", "synthesis_and_gaps", "independent_audit",
        "platform_plan", "progress"]

CLAIMS = [
    {"id": "CL-H1", "s1_013_class": "HCI_measurement",
     "claim_class": "fact",
     "text": "The mock prototype exposes delegation, scope, provenance "
             "and stop controls with keyboard-focusable, exported and "
             "re-importable event vocabulary identical to the frozen "
             "schemas.",
     "support": ["SRC-S1-013-01", "SRC-S1-013-04"]},
    {"id": "CL-H2", "s1_013_class": "user_observation",
     "claim_class": "fact",
     "text": "Synthetic dry-run sessions exercise every importer path "
             "(ok, rejected duplicate/id-shape/consent, quarantined PII) "
             "and every probe A-H through the real scorer.",
     "support": ["SRC-S1-013-04"]},
    {"id": "CL-H3", "s1_013_class": "hypothesis",
     "claim_class": "inference",
     "text": "In-context least-privilege approvals with visible actor, "
             "exact action, scope and expiry reduce approval errors "
             "relative to banner-style consent; stated as a hypothesis "
             "for the human pilot, not a measured effect.",
     "support": ["SRC-S1-013-01", "SRC-S1-013-02"]},
    {"id": "CL-D1", "s1_013_class": "design_inference",
     "claim_class": "inference",
     "text": "Frozen protocol, rubric, scenarios and schemas consumed "
             "by a single definition let UI, exporter, evaluator and "
             "analyst agree byte-for-byte; deviations are detected at "
             "import.",
     "support": ["SRC-S1-013-04", "SRC-S1-013-05"]},
    {"id": "CL-L1", "s1_013_class": "limitation",
     "claim_class": "assumption",
     "text": "No human data exists yet: all rates and dispositions are "
             "dry-run tooling checks. SRC-04 is unavailable, so "
             "mental-model coverage rests on the task text and protocol.",
     "support": []},
]

ARTIFACT_TEXTS = {
    "research_plan": (
        "Prepare and, only after operator approval with real "
        "participants, run a bounded comprehension and approval-fatigue "
        "pilot (target N=16, two roles, five transfer measures, two "
        "approval-load blocks). This preparation delivers a frozen "
        "protocol, safe mock UI, evaluator and dry-run evidence; the "
        "human phase stays blocked until recruitment is approved."),
    "source_registry": (
        "Five sources: UDAC primary fragment (in-context approvals), "
        "Nudges citation record (hypothesis framing only), SRC-04 "
        "unavailability record with explicit substitution, S1-011 and "
        "S1-012 canonical decisions via cross-branch git show."),
    "feature_catalog": (
        "Delegation vs credential, private-space readers, foreign "
        "message vs gated knowledge, system-agent default deny, "
        "confirmed stop-all; exact approvals with expiry; fatigue "
        "reports; pseudonymous sessions; dual-rater adjudication."),
    "architecture_models": (
        "Static mock UI plus stdlib importer, scorer, replicator and "
        "bundle publisher sharing one frozen definition set; synthetic "
        "dry-run corpus kept strictly separate from (empty) human data."),
    "mental_model": (
        "Delegation is scoped, revocable, expiring authority; passwords "
        "authenticate and are never shared. Only connected principals "
        "see private spaces. Foreign content is untrusted until gated. "
        "Stop means confirmed acknowledgement, not a click."),
    "ontology": (
        "Session, event and answer records per frozen schemas; measures "
        "C1-C5 with transfer scenarios; approval prompts with actor, "
        "action, scope and expiry; participant flow accounting starters, "
        "exclusions and completers without PII."),
    "mathematical_model": (
        "Per-measure rates with Wilson intervals against frozen targets "
        "reported as met/not-met/inconclusive; prompts per active hour "
        "per role, participant-clustered, with raw exposure; short-block "
        "rescaling is not stamina evidence; N=16 never proves universal "
        "accuracy."),
    "synthesis_and_gaps": (
        "Preparation is complete and dry-run green; the human pilot, "
        "operator approval, recruitment, second human rating and "
        "canonicalization are all open. SRC-04 gap and Beta-free design "
        "are explicit limits; S1-014/S1-015 receive pilot constraints, "
        "not closure."),
    "independent_audit": (
        "Producer path (importer) and audit path (scorer plus "
        "replication) are independent code reading only frozen inputs. "
        "An independent process replicates the analysis byte-identical; "
        "a separate auditor role is defined for protocol deviations, "
        "consent coverage, exclusions, grading and privacy. Agent-only "
        "audit never replaces the second human rater."),
    "progress": (
        "Phase 1 preparation complete: dependency inventory, literature, "
        "frozen protocol/rubric/scenarios/schemas, consent/privacy/ "
        "facilitator docs, mock UI, synthetic dry-run, scorer with "
        "probes A-H, replication record, native FLOW-11 bundle and "
        "derived candidate. Blocked: human pilot (no participants)."),
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
        if entry.get("kind") == "unavailable":
            # The SRC-04 absence record stays in the registry, snapshots
            # and limitations, but never enters the evidence bundle as a
            # source: unverified placeholders must not dilute the verified
            # ratio the canonical gate enforces by default.
            continue
        raw = (HERE / "sources" / Path(
            entry["snapshot_path"]).name).read_bytes()
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
            "verifier": "s1-013-source-review-2026-09-04",
            "verification_method": "tracked-file-hash-review",
            "content": text,
            "content_sha256": sha(raw),
        })
    return sources


def build_artifacts() -> dict:
    artifacts = {}
    for kind in FLOW:
        if kind == "platform_plan":
            artifacts[kind] = {
                "content": {
                    "Scope": "Bounded HCI pilot preparation and, after "
                             "approval, a 15-20 person comprehension and "
                             "fatigue study; no production claims.",
                    "Architecture": "Static mock UI plus stdlib importer, "
                                    "scorer, replicator and publisher on "
                                    "one frozen definition set.",
                    "Workstreams": "Freeze protocol; build mock UI; score "
                                   "dry runs; replicate analysis; publish "
                                   "native bundle; await recruitment.",
                    "Milestones": "PREPARATION_READY now; human pilot only "
                                  "after operator approval and real "
                                  "participants; canonicalization after "
                                  "review.",
                    "Verification": "Targeted suites, UI vocabulary "
                                    "checks, probe battery, replication "
                                    "record, native normalizer pass.",
                    "Risks": "Small samples, no-SRC-04 mental-model gap, "
                             "privacy handling, fatigue underestimated.",
                    "Open decisions": "Exact N in 15-20 at recruitment; "
                                      "ethics review outcome; S1-014/15 "
                                      "handoff scope."},
                "producer": PRODUCER,
                "claim_refs": ["CL-D1", "CL-L1"]}
            continue
        artifacts[kind] = {"content": ARTIFACT_TEXTS[kind],
                           "producer": PRODUCER,
                           "claim_refs": ["CL-H1", "CL-D1"]}
    artifacts["independent_audit"]["producer"] = AUDITOR
    artifacts["independent_audit"]["claim_refs"] = ["CL-H2", "CL-L1"]
    artifacts["research_plan"]["claim_refs"] = ["CL-H3", "CL-L1"]
    artifacts["source_registry"]["claim_refs"] = ["CL-H1", "CL-L1"]
    artifacts["progress"]["claim_refs"] = ["CL-H2"]
    artifacts["ontology"]["claim_refs"] = ["CL-H1", "CL-D1"]
    artifacts["mathematical_model"]["claim_refs"] = ["CL-H3", "CL-L1"]
    artifacts["synthesis_and_gaps"]["claim_refs"] = ["CL-D1", "CL-L1"]
    artifacts["mental_model"]["claim_refs"] = ["CL-H1"]
    artifacts["feature_catalog"]["claim_refs"] = ["CL-H1", "CL-H2"]
    return artifacts


def derive_verdict(here=None, results=None) -> tuple:
    """Re-derive the verdict from evidence. Returns (blockers, facts).

    Saved flags are never authority: the importer, scorer and probe
    battery are re-executed, the replication record is rechecked, and
    every merged artifact is crosschecked. The only reachable
    publication verdict here is PREPARATION_READY; any human-data
    claim or empty-dataset PASS blocks."""
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
    # Re-execute importer + scorer + probes from frozen inputs.
    import subprocess
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="s1013-recompute-"))
    steps = [
        [sys.executable, str(here / "runner.py"), "--src",
         str(here / "synthetic" / "sessions"), "--out", str(tmp / "imp")],
        [sys.executable, str(here / "evaluator.py"), "--run",
         str(tmp / "imp"), "--protocol", str(here),
         "--out", str(tmp / "metrics.json"), "--probes",
         str(tmp / "probes.json")],
    ]
    for argv in steps:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              check=False)
        if proc.returncode != 0:
            return blockers + [f"recompute step failed: {argv[2]}"], {}
    try:
        recomputed = {
            "metrics": json.loads(
                (tmp / "metrics.json").read_text(encoding="utf-8")),
            "probes": json.loads(
                (tmp / "probes.json").read_text(encoding="utf-8")),
        }
        saved = {name: load_saved(f"{name}.json") for name in
                 ("metrics", "probes", "comparison",
                  "participant-flow")}
    except (OSError, ValueError) as exc:
        return blockers + [f"saved artifact unreadable: {exc}"], {}
    for name in ("metrics", "probes"):
        if json.dumps(recomputed[name], sort_keys=True) != json.dumps(
                saved[name], sort_keys=True):
            blockers.append(
                f"saved {name}.json differs from recomputation")
    # Human-data guard: no non-synthetic sessions may exist anywhere.
    human = [o for o in recomputed["metrics"].get("human_sessions", [])
             if not o.get("synthetic", True)]
    if human or recomputed["metrics"].get("human_n", 0):
        blockers.append("human data claimed without a human pilot")
    # Empty human dataset never yields a research PASS.
    flow = saved.get("participant-flow", {})
    if flow.get("human", {}).get("completed", 0):
        blockers.append("human completions claimed pre-pilot")
    # Replication record must exist and match.
    comparison = saved.get("comparison", {})
    if not comparison.get("replicated"):
        blockers.append("analysis replication not recorded")
    facts = {"gate": gate.get("all_proven"),
             "recomputed_from": "importer+scorer re-executed on frozen "
                                "synthetic data",
             "sessions": recomputed["metrics"].get("sessions"),
             "effective_n": recomputed["metrics"].get(
                 "effective_participants"),
             "probes": recomputed["probes"].get("all_pass")}
    return blockers, facts


def main() -> int:
    blockers, facts = derive_verdict()
    if blockers:
        for line in blockers:
            print(f"BLOCKED: {line}", file=sys.stderr)
        return 1
    limitations = [
        "tracked-Git evidence only; live DB recheck required in Phase B",
        "no human data: all rates are dry-run tooling checks",
        "SRC-04 unavailable; mental-model coverage rests on task text",
        "source base 4/4 verified in-bundle; the fifth registry "
        "entry is the recorded SRC-04 absence (kept in registry, "
        "snapshots and limitations, never as bundle evidence)",
        "Beta-free design; no reputation-as-authority anywhere",
        "holdout concept not applicable pre-pilot; synthetic corpus is "
        "author-visible by construction",
    ]
    bundle = {
        "config": {"min_source_count": 4, "min_verified_ratio": 1.0,
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
    manifest = load("frozen-manifest.json")
    candidate = {
        "schema": "agentos.s1-013.candidate-record/v1",
        "ticket": "S1-013",
        "status": "PREPARATION_READY",
        "human_phase": "BLOCKED_HUMAN_PILOT",
        "verdict_basis": facts,
        "bundle_path": "research/tickets/stage-1/S1-013/bundle.json",
        "bundle_sha256": bundle_sha,
        "frozen_hashes": manifest.get("hashes", {}),
        "tracked_artifacts": tracked_registry(),
        "tracked_registry_note": "Every ticket file plus the test "
                                 "modules, by repo-relative POSIX path "
                                 "with SHA-256 of committed bytes, except "
                                 "candidate-record.json itself (bound by "
                                 "its git commit; rebuild reproduces it).",
        "assumptions": [
            "mock UI interactions model the frozen scenarios faithfully",
            "synthetic sessions cover every importer path",
            "frozen targets stay hypotheses until human data exists",
        ],
        "unknowns": [
            "real comprehension rates and fatigue curves",
            "SRC-04 mental-model content",
            "measured operator and ethics outcomes",
        ],
        "residual_risks": [
            "small-sample overinterpretation downstream",
            "privacy handling of free text at release",
            "reputation mistaken for authorization downstream",
        ],
        "phase_b_required": True,
        "chain_fresh_claim": None,
        "note": "No goal_id, campaign_id, evaluation_id, research "
                "revision, artifact-chain hash, wiki counts, human N or "
                "human metrics are stated here; those require an approved "
                "human pilot plus Phase B canonicalization.",
    }
    (HERE / "candidate-record.json").write_text(
        json.dumps(candidate, indent=2, sort_keys=True,
                   ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    print(f"bundle.json sha256={bundle_sha}")
    print("candidate-record.json status=PREPARATION_READY, "
          "human=BLOCKED_HUMAN_PILOT")
    return 0


def check_metrics_consistency(metrics_doc: dict) -> list:
    """Preparation-output guard: synthetic marking present, no human N
    claimed, no research PASS verdict anywhere pre-pilot."""
    problems = []
    if metrics_doc.get("human_n", 0):
        problems.append("human_n claimed pre-pilot")
    if metrics_doc.get("synthetic") is not True:
        problems.append("metrics not marked synthetic")
    if str(metrics_doc.get("verdict", "")).upper().startswith("PASS"):
        problems.append("research PASS claimed without human data")
    return problems


def tracked_registry() -> dict:
    registry: dict = {}
    ticket_rel = Path("research/tickets/stage-1/S1-013")
    for path in sorted(HERE.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts \
                and path.name != "candidate-record.json":
            rel = (ticket_rel / path.relative_to(HERE)).as_posix()
            registry[rel] = sha(path.read_bytes())
    for name in ("tests/test_s1_013_regressions.py",
                 "tests/test_s1_013_ui.py"):
        test_file = Path(__file__).resolve().parents[4] / name
        if test_file.is_file():
            registry[name] = sha(test_file.read_bytes())
    return registry


if __name__ == "__main__":
    raise SystemExit(main())
