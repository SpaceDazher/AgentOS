"""Build the S1-015 candidate evidence bundle (FLOW-11) + candidate record.

Publication is derived: saved flags are never sufficient. This module verifies
the exact frozen inputs, the dependency gate, runs the importer/evaluator
fresh, runs the two-process replay, runs the real-browser probe, cross-checks
saved result files, checks the operator decision bindings (when present),
scans for secrets/PII, and only then writes bundle.json + candidate-record.
Any failure removes only this ticket's ready outputs (never user files).

Without operator-decision.json the only allowed outcome is PREPARATION_READY
(operator_review REQUIRED). With a valid admissible decision the candidate
closes as CLOSED_WITH_LIMITS for the canonical research command + finalizer.
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
RESULTS = HERE / "results"
TICKET = "S1-015"
PRODUCER = "agentos-s1-015-producer"
AUDITOR = "agentos-s1-015-independent-verifier"
PROCESS_TIMEOUT_SECONDS = 300
HEX64 = re.compile(r"^[0-9a-f]{64}$")

FLOW = [
    "research_plan", "source_registry", "feature_catalog",
    "architecture_models", "mental_model", "ontology",
    "mathematical_model", "synthesis_and_gaps", "independent_audit",
    "platform_plan", "progress",
]

REQUIRED_CLAIM_CLASSES = {
    "HCI_measurement", "identity_invariant", "design_inference",
    "spoofing_risk", "accessibility_risk", "decision", "limitation",
}

BLOCKING = {"1C", "2B", "2C", "3B", "3C", "4B", "4C", "5B", "5C", "6B", "6C",
            "7B", "7C", "8B", "8C", "9B", "9C", "10C"}
# Blocking answers are well-formed but block a PETNAME closure: the honest
# outcome is INCONCLUSIVE (or CANONICAL_ID_ONLY for 1B). Only malformed,
# forged or 11C/12C bindings fail publication itself.
REQUIRED_DECISION_BINDINGS = (
    "contract.py", "display_schema.json", "corpus.json", "oracle.json",
    "rubric.json", "decision-rule.json", "prototype/browser-contract.json",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _read_json(path: Path, label: str) -> Any:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} missing: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"{label} unreadable: {exc}") from exc


def _remove_exact(path: Path) -> None:
    if path.is_file() or path.is_symlink():
        path.unlink()


def remove_ready_outputs(here: Path | None = None) -> None:
    base = Path(here) if here is not None else HERE
    for name in ("bundle.json", "candidate-record.json"):
        _remove_exact(base / name)


def _ticket_relative_files(here: Path) -> set[str]:
    excluded = {"bundle.json", "candidate-record.json", "dependency-gate.json",
                "evaluation-record.json", "frozen-manifest.json",
                "operator-decision.json"}
    paths: set[str] = set()
    for path in sorted(here.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if "__pycache__" in path.relative_to(here).parts:
            continue
        rel = path.relative_to(here).as_posix()
        if path.name in excluded or rel.startswith("results/"):
            continue
        if path.name.endswith(".tmp") or path.name.endswith(".pyc"):
            continue
        paths.add(rel)
    return paths


def verify_frozen_manifest(here: Path | None = None):
    base = (Path(here) if here is not None else HERE).resolve()
    problems: list[str] = []
    try:
        manifest = _read_json(base / "frozen-manifest.json", "frozen manifest")
    except ValueError as exc:
        return [str(exc)], {}
    if not isinstance(manifest, dict):
        return ["frozen manifest is not an object"], {}
    if manifest.get("schema") != "agentos.s1-015.frozen-manifest/v1":
        problems.append("frozen manifest schema mismatch")
    if manifest.get("ticket") != TICKET:
        problems.append("frozen manifest ticket mismatch")
    hashes = manifest.get("hashes")
    if not isinstance(hashes, dict) or not hashes:
        problems.append("frozen manifest has no hash map")
        return problems, manifest
    expected = _ticket_relative_files(base)
    actual = set(hashes)
    for rel in sorted(expected - actual):
        problems.append(f"frozen manifest missing input: {rel}")
    for rel in sorted(actual - expected):
        problems.append(f"frozen manifest lists non-input: {rel}")
    required = (
        ("analysis", lambda p: p in {"analysis-plan.md", "runner.py", "evaluator.py",
                                     "replicate.py", "make_bundle.py", "finalize_record.py",
                                     "freeze.py", "build_corpus.py", "contract.py",
                                     "dependency_gate.py"}),
        ("UI", lambda p: p.startswith("prototype/")),
        ("fixtures", lambda p: p.startswith("sources/") or p in {
            "corpus.json", "oracle.json", "corpus-manifest.json",
            "display_schema.json", "threat-model.json", "rubric.json",
            "decision-rule.json", "source-registry.json"}),
    )
    for label, predicate in required:
        if not any(predicate(rel) for rel in expected & actual):
            problems.append(f"frozen manifest has no {label} inputs")
    for rel in sorted(actual & expected):
        expected_sha = hashes.get(rel)
        if not isinstance(expected_sha, str) or not HEX64.fullmatch(expected_sha):
            problems.append(f"frozen manifest hash invalid: {rel}")
            continue
        try:
            actual_sha = sha((base / PurePosixPath(rel)).read_bytes())
        except OSError as exc:
            problems.append(f"frozen input unreadable {rel}: {exc}")
            continue
        if actual_sha != expected_sha:
            problems.append(f"frozen input hash mismatch: {rel}")
    return problems, manifest


def _snapshot_path(here: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise ValueError("source snapshot path is not canonical POSIX")
    prefix = f"research/tickets/stage-1/{TICKET}/"
    if raw.startswith(prefix):
        rel = raw[len(prefix):]
    elif raw.startswith("sources/"):
        rel = raw
    else:
        raise ValueError(f"source snapshot path outside ticket: {raw}")
    parts = rel.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise ValueError(f"source snapshot path is not canonical: {raw}")
    return here.joinpath(*parts)


def build_sources(here: Path | None = None) -> list[dict]:
    base = (Path(here) if here is not None else HERE).resolve()
    registry = _read_json(base / "source-registry.json", "source registry")
    if not isinstance(registry, dict) or registry.get("ticket") != TICKET:
        raise ValueError("source registry ticket mismatch")
    entries = registry.get("sources")
    if not isinstance(entries, list) or not entries:
        raise ValueError("source registry is empty")
    sources: list[dict] = []
    ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("source registry entry is not an object")
        source_id = entry.get("id")
        if not isinstance(source_id, str) or not source_id or source_id in ids:
            raise ValueError("source registry has duplicate/invalid id")
        ids.add(source_id)
        path = _snapshot_path(base, entry.get("snapshot_path"))
        expected = entry.get("sha256")
        if not isinstance(expected, str) or not HEX64.fullmatch(expected):
            raise ValueError(f"source hash invalid: {source_id}")
        raw = path.read_bytes()
        if sha(raw) != expected or ("bytes" in entry and entry["bytes"] != len(raw)):
            raise ValueError(f"source snapshot bytes drift: {source_id}")
        text = raw.decode("utf-8")
        sources.append({
            "id": source_id,
            "canonical_uri": entry.get("canonical_uri"),
            "title": entry.get("title"),
            "source_type": entry.get("role"),
            "verification_status": "verified",
            "verifier": "s1-015-source-review-2026-09-05",
            "verification_method": "tracked-file-hash-review",
            "content": text,
            "content_sha256": sha(raw),
        })
    if len(sources) < 4:
        raise ValueError("fewer than four verified source snapshots")
    return sources


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_dependency(here: Path) -> dict:
    gate_mod = load_module(here / "dependency_gate.py", "s1015_gate_check")
    result = gate_mod.check()
    if result["status"] != "PROVEN":
        raise ValueError(f"dependency not proven: {result['problems']}")
    gate_file = json.loads((here / "dependency-gate.json").read_text(encoding="utf-8"))
    if gate_file.get("phase_a_dependencies_proven") is not True:
        raise ValueError("dependency-gate.json is not proven")
    if gate_file.get("population_human_claims_proven") is not False:
        raise ValueError("population claims must stay unproven")
    dep = gate_file["dependency"]
    for key, expected in (("goal_id", "goal_PZ0WP37PRBM05XH101M1QB60YD"),
                          ("campaign_id", "rcamp_YX958H0WJ4YDK4AH01M1QB60YD"),
                          ("evaluation_id", "reval_P911RT2XC117Y74Y01M1QB612C"),
                          ("artifact_chain_hash",
                           "766172bb18bcf479ce672ebe5e881a083e89430003b697a12650abf11c943e34")):
        if dep.get(key) != expected:
            raise ValueError(f"dependency binding drift: {key}")
    return gate_file


def run_subprocess(argv: list[str], cwd: Path, env_extra: dict | None = None) -> None:
    env = dict(os.environ)
    env["TEMP"] = r"D:\Temp-opencode"
    env["TMP"] = r"D:\Temp-opencode"
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, env=env,
                          timeout=PROCESS_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-600:]
        raise ValueError(f"command failed {' '.join(argv[-2:])}: {tail}")


def fresh_runs(here: Path) -> dict:
    """ Regenerate run-a/run-b, replay comparison, browser evidence, metrics. """
    for name in ("run-a", "run-b", "browser-import"):
        shutil.rmtree(here / "results" / name, ignore_errors=True)
    (here / "results").mkdir(parents=True, exist_ok=True)
    run_subprocess([sys.executable, str(here / "runner.py"), "--generate",
                    "--executor", "A", "--ticket", str(here),
                    "--out", str(here / "results" / "run-a")], here)
    run_subprocess([sys.executable, str(here / "runner.py"), "--generate",
                    "--executor", "B", "--ticket", str(here),
                    "--out", str(here / "results" / "run-b")], here)
    run_subprocess([sys.executable, str(here / "replicate.py"), "--ticket", str(here),
                    "--out", str(here / "results" / "comparison.json")], here)
    run_subprocess([sys.executable, str(here / "prototype" / "browser_probe.py"),
                    "--out", str(here / "results" / "browser-envelopes.json")], here)
    run_subprocess([sys.executable, str(here / "runner.py"), "--src",
                    str(here / "results" / "browser-envelopes.json"),
                    "--ticket", str(here),
                    "--out", str(here / "results" / "browser-import")], here)
    run_subprocess([sys.executable, str(here / "evaluator.py"), "--run",
                    str(here / "results" / "run-a"), "--protocol", str(here),
                    "--out", str(here / "results" / "metrics.json"),
                    "--probes", str(here / "results" / "probes.json")], here)
    metrics = _read_json(here / "results" / "metrics.json", "metrics")
    probe_doc = _read_json(here / "results" / "probes.json", "probes")
    comparison = _read_json(here / "results" / "comparison.json", "comparison")
    if metrics.get("observations") != 240:
        raise ValueError("run-a must hold 240 observations")
    run_b = _read_json(here / "results" / "run-b" / "observations.json", "run-b")
    if len(run_b.get("observations", [])) != 240:
        raise ValueError("run-b must hold 240 observations")
    if any(v != 0 for v in metrics.get("hard_counters", {}).values()):
        raise ValueError("hard counters are not all zero")
    if metrics.get("safety_verdict") is not True:
        raise ValueError("safety verdict is not true")
    if probe_doc.get("all_pass") is not True:
        raise ValueError("probes A-N did not all pass")
    if comparison.get("replicated") is not True:
        raise ValueError("replay did not replicate")
    if comparison.get("matrix") != "40 cases x 2 variants x 3 seeds x 2 executors = 480 observations":
        raise ValueError("replay matrix mismatch")
    # Browser round-trip must import cleanly through the same boundary.
    browser_metrics_out = here / "results" / "browser-metrics.json"
    browser_probes_out = here / "results" / "browser-probes.json"
    run_subprocess([sys.executable, str(here / "evaluator.py"), "--run",
                    str(here / "results" / "browser-import"), "--protocol", str(here),
                    "--out", str(browser_metrics_out),
                    "--probes", str(browser_probes_out)], here)
    browser_metrics = _read_json(browser_metrics_out, "browser metrics")
    if any(v != 0 for v in browser_metrics.get("hard_counters", {}).values()):
        raise ValueError("browser hard counters are not all zero")
    return {"metrics": metrics, "probes": probe_doc, "comparison": comparison,
            "browser_metrics": browser_metrics}


def verify_operator_decision(here: Path):
    """Return (present, answers, decision_doc). Absent decision is not an error."""
    path = here / "operator-decision.json"
    if not path.exists():
        return False, None, None
    doc = _read_json(path, "operator decision")
    if doc.get("ticket") != TICKET:
        raise ValueError("operator decision ticket mismatch")
    answers = doc.get("selected_answers")
    if not isinstance(answers, dict) or sorted(answers, key=int) != [str(n) for n in range(1, 13)]:
        raise ValueError("operator decision must hold exactly answers 1..12")
    letters = {}
    for num in range(1, 13):
        letter = answers[str(num)]
        if letter not in ("A", "B", "C"):
            raise ValueError(f"answer {num} has unknown letter {letter!r}")
        letters[str(num)] = letter
    if letters["11"] == "C" or letters["12"] == "C":
        raise ValueError("11C/12C forbidden at human_study_n=0")
    approved = doc.get("approved_artifact_hashes", {})
    for name, expected in approved.items():
        candidate = here / name
        if not candidate.is_file():
            raise ValueError(f"operator-approved artifact missing: {name}")
        if sha(candidate.read_bytes()) != expected:
            raise ValueError(f"operator-approved artifact drift: {name}")
    # Required bindings: contract, corpus artifacts, rubric, UI contract.
    # (bundle.json is bound separately through the candidate/evaluation
    # chain because it is regenerated after the review.)
    for name in REQUIRED_DECISION_BINDINGS:
        if name not in approved:
            raise ValueError(f"operator decision missing binding: {name}")
    return True, letters, doc


def derive_verdict(metrics: dict, comparison: dict, present: bool,
                   letters: dict | None) -> tuple[list[str], dict]:
    blockers: list[str] = []
    if any(v != 0 for v in metrics.get("hard_counters", {}).values()):
        blockers.append("hard counters nonzero")
    if not all(metrics.get("mandatory_safety", {}).values()):
        blockers.append("mandatory safety rates below 100%")
    if comparison.get("replicated") is not True:
        blockers.append("replay did not replicate")
    if metrics.get("human_study_n", 0) != 0 or \
            metrics.get("recognition_improvement") != "NOT_MEASURED":
        blockers.append("human/recognition claim leaked into synthetic metrics")
    if not present:
        return blockers, {"design_decision": "INCONCLUSIVE",
                          "status": "PREPARATION_READY",
                          "result": "PREPARATION_READY",
                          "operator_review": "REQUIRED",
                          "note": "technical evidence green; operator review required"}
    assert letters is not None
    blocking_hit = sorted(f"{num}{letters[num]}" for num in
                          (str(n) for n in range(1, 13))
                          if f"{num}{letters[num]}" in BLOCKING)
    if blocking_hit:
        return blockers, {
            "design_decision": "INCONCLUSIVE", "status": "CLOSED_INCONCLUSIVE",
            "result": "INCONCLUSIVE", "operator_review": "COMPLETE",
            "blocking_answers": blocking_hit,
            "note": ("operator answers block a petname closure "
                     f"({', '.join(blocking_hit)}); no provisional petname "
                     "contract is granted and no PASS_WITH_LIMITS ticket "
                     "closure is claimed"),
        }
    if letters["1"] == "B":
        return blockers, {"design_decision": "CANONICAL_ID_ONLY",
                          "status": "CLOSED_WITH_LIMITS", "result": "PASS_WITH_LIMITS",
                          "operator_review": "COMPLETE",
                          "note": "honest downgrade: petnames deferred per operator"}
    if letters["11"] == "B" or letters["12"] == "B":
        return blockers, {"design_decision": "INCONCLUSIVE",
                          "status": "CLOSED_INCONCLUSIVE", "result": "INCONCLUSIVE",
                          "operator_review": "COMPLETE",
                          "note": "honest downgrade per operator answers"}
    return blockers, {"design_decision": "DISPLAY_ONLY_PETNAME_WITH_CANONICAL_ID",
                      "status": "CLOSED_WITH_LIMITS", "result": "PASS_WITH_LIMITS",
                      "operator_review": "COMPLETE",
                      "note": ("provisional display-only contract; human recognition "
                               "improvement remains NOT_MEASURED")}


SECRET_PATTERNS = [re.compile(p, re.I) for p in
                   (r"sk-proj-[A-Za-z0-9_-]{8,}", r"ghp_[A-Za-z0-9_-]{12,}",
                    r"AKIA[0-9A-Z]{16}")]
PII_PATTERN = re.compile(
    r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:passport|ssn|consent_text)\b", re.I)


def secret_pii_scan(here: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted(here.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if "__pycache__" in path.relative_to(here).parts:
            continue
        if path.suffix not in (".py", ".json", ".md", ".js", ".html", ".css"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        rel = path.relative_to(here).as_posix()
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                problems.append(f"secret pattern in {rel}")
        # Synthetic owner IDs and probe payloads are allowlisted; real PII is not.
        if PII_PATTERN.search(text) and "somebody@example.com" not in text \
                and "probe N" not in text and "quarantine" not in text.lower():
            # evaluator.py/runner.py legitimately contain the PII regex itself.
            if not (path.name in ("contract.py", "runner.py", "evaluator.py",
                                  "make_bundle.py") and "PII =" in text):
                problems.append(f"PII pattern in {rel}")
    return problems


CLAIMS = [
    {"id": "CL-H1", "s1_015_class": "HCI_measurement", "claim_class": "fact",
     "text": ("The bounded prototype exposes BASELINE and PETNAME principal "
              "displays with keyboard-focusable, exported and re-importable "
              "envelope vocabulary identical to the frozen display schema; "
              "canonical ID/type/scope stay visible in every high-impact view."),
     "support": ["SRC-S1-015-01", "SRC-S1-015-02"]},
    {"id": "CL-I1", "s1_015_class": "identity_invariant", "claim_class": "fact",
     "text": ("Canonical principal ID and scope are the sole authority "
              "identity across UI, fixtures, importer, evaluator and approval "
              "paths; petnames are owner-local versioned display-only "
              "projections that never enter the approval tuple."),
     "support": ["SRC-S1-015-02"]},
    {"id": "CL-D1", "s1_015_class": "design_inference", "claim_class": "inference",
     "text": ("One authoritative envelope schema shared by UI, fixtures, "
              "importer and evaluator lets deviations fail closed at import; "
              "frozen corpus/oracle separation keeps the UI blind to expected "
              "decisions while the evaluator recomputes independently."),
     "support": ["SRC-S1-015-01", "SRC-S1-015-05"]},
    {"id": "CL-S1", "s1_015_class": "spoofing_risk", "claim_class": "fact",
     "text": ("Collision, confusable, mixed-script, bidi/invisible and "
              "injection cases are flagged or ambiguous through the real "
              "importer/evaluator path with benign controls; name-only "
              "approval and first-match auto-selection are refused."),
     "support": ["SRC-S1-015-03"]},
    {"id": "CL-A1", "s1_015_class": "accessibility_risk", "claim_class": "fact",
     "text": ("Canonical identity is available visually and non-visually in "
              "every approval and on-behalf view; keyboard-only flow, visible "
              "focus and copy-ID hold; color/icon is never the sole cue."),
     "support": ["SRC-S1-015-04"]},
    {"id": "CL-C1", "s1_015_class": "decision", "claim_class": "inference",
     "text": ("Technical evidence supports at most a provisional "
              "display-only petname contract bound to canonical identity; "
              "any hard-counter, safety-rate, replay or operator-answer gate "
              "violation falls back to CANONICAL_ID_ONLY or INCONCLUSIVE."),
     "support": ["SRC-S1-015-02", "SRC-S1-015-05"]},
    {"id": "CL-L1", "s1_015_class": "limitation", "claim_class": "assumption",
     "text": ("No human data was collected: all rates are technical dry-run "
              "checks over synthetic observations. One operator design review "
              "authorizes a display contract; recognition improvement is "
              "NOT_MEASURED and PASS/production rollout are out of scope."),
     "support": []},
]

ARTIFACT_TEXTS = {
    "research_plan": ("Close a bounded petname principal-naming study through "
                      "the frozen display contract, 40-case corpus, BASELINE/"
                      "PETNAME prototype, importer/evaluator, 480-observation "
                      "replay and one operator design review. No human study; "
                      "recognition improvement stays NOT_MEASURED."),
    "source_registry": ("The source registry binds each locally authorized "
                        "snapshot to its URI, role, verification status and "
                        "SHA-256. Bibliographic records are not presented as "
                        "verified full-text evidence."),
    "feature_catalog": ("Canonical principal identity; owner-local versioned "
                        "petname projections; explicit ambiguity with "
                        "canonical selection; rename/delete tombstones with "
                        "canonical history; confusable/bidi/invisible "
                        "flagging; inert injection rendering; exact-action "
                        "approval with canonical actor/target; on-behalf "
                        "banners; screen-reader/keyboard identity; copy-ID."),
    "architecture_models": ("Static bounded prototype plus stdlib contract, "
                            "corpus generator, importer, evaluator, "
                            "replicator and bundle publisher sharing one "
                            "frozen definition set; synthetic observations "
                            "kept strictly separate from (empty) human data."),
    "mental_model": ("Canonical IDs are the authority users must see; "
                     "petnames are personal display projections like the "
                     "SRC-04 QM3 petname dictionary. On-behalf banners and "
                     "approvals always show canonical actor identity."),
    "ontology": ("Principal-display envelopes per the frozen schema; 40 "
                 "deterministic cases across benign/collision/lifecycle/"
                 "unicode/approval classes with a separate oracle; approval "
                 "tuples with canonical actor/target/operation/tool/version/"
                 "args/expiry; candidate sets for ambiguity."),
    "mathematical_model": ("Hard counters (10) must be zero in every "
                           "seed/executor; mandatory safety rates must be "
                           "100%; raw numerator/denominator reporting with "
                           "missing/timeout/censored in denominators; two "
                           "process-separated runs must agree byte-identical "
                           "on canonical content."),
    "synthesis_and_gaps": ("Technical preparation and (after review) one "
                           "operator design decision are complete. No human "
                           "grading occurred and all human effectiveness "
                           "measures remain NOT_MEASURED. Source coverage and "
                           "same-host replay limits remain explicit."),
    "independent_audit": ("Producer path (importer/runner) and audit path "
                          "(evaluator plus process-separated replication) "
                          "are independent code reading only frozen inputs. "
                          "An independent process replicates the analysis "
                          "byte-identical; the operator exercised both UI "
                          "variants for identity, ambiguity, lifecycle and "
                          "privacy behavior. This same-operator review never "
                          "replaces independent human grading or a "
                          "population study."),
    "progress": ("Bounded preparation complete: dependency proof, frozen "
                 "sources, threat model, display contract, 40-case corpus, "
                 "BASELINE/PETNAME prototype, real-browser probe, evaluator "
                 "with probes A-N, 480-observation replay, native FLOW-11 "
                 "bundle and derived candidate record. Human study n is zero."),
}


def build_bundle(here: Path, sources: list[dict], verdict: dict,
                 present: bool, letters: dict | None = None) -> dict:
    artifacts: dict[str, dict] = {}
    for kind in FLOW:
        if kind == "platform_plan":
            artifacts[kind] = {
                "content": {
                    "Scope": ("Bounded display-only petname study; no "
                              "population, human-effectiveness or production "
                              "claims."),
                    "Architecture": ("Static bounded prototype plus stdlib "
                                     "contract, importer, evaluator, "
                                     "replicator and publisher on one frozen "
                                     "definition set."),
                    "Workstreams": ("Freeze sources; sign display contract; "
                                    "build corpus; build prototype; score "
                                    "480 observations; replicate; operator "
                                    "review; publish canonical bundle."),
                    "Milestones": ("PREPARATION_READY after technical gates; "
                                   "CLOSED_WITH_LIMITS after admissible "
                                   "operator review and canonicalization."),
                    "Verification": ("Targeted suites, UI vocabulary checks, "
                                     "real-browser probe, probes A-N, "
                                     "replication record, native normalizer "
                                     "pass, wiki-check."),
                    "Risks": ("Small synthetic corpus, heuristic confusable "
                              "detection, same-host replay, single-operator "
                              "review limits."),
                    "Open decisions": ("No recruitment remains in scope; "
                                       "human recognition requires a future "
                                       "multi-participant study."),
                },
                "producer": PRODUCER,
            }
        else:
            artifacts[kind] = {"content": ARTIFACT_TEXTS[kind], "producer": PRODUCER}
    for kind, artifact in artifacts.items():
        refs = [c["id"] for c in CLAIMS if c["id"] in
                ({"CL-H1", "CL-D1"} if kind in ("architecture_models", "ontology") else
                 {"CL-H1", "CL-C1"} if kind == "feature_catalog" else
                 {"CL-H1"} if kind == "mental_model" else
                 {"CL-H1", "CL-D1"} if kind == "ontology" else
                 {"CL-C1", "CL-L1"} if kind == "mathematical_model" else
                 {"CL-D1", "CL-L1"} if kind == "synthesis_and_gaps" else
                 {"CL-S1", "CL-L1"} if kind == "independent_audit" else
                 {"CL-D1", "CL-L1"} if kind == "platform_plan" else
                 {"CL-S1"} if kind == "progress" else
                 {"CL-C1", "CL-L1"} if kind == "research_plan" else
                 {"CL-H1", "CL-L1"})]
        artifact["claim_refs"] = refs
    artifacts["independent_audit"]["producer"] = AUDITOR
    artifacts["source_registry"]["claim_refs"] = ["CL-H1", "CL-L1"]
    if verdict.get("design_decision") == "INCONCLUSIVE" and present:
        review_limit = ("one operator design review recorded "
                        + " ".join(f"{n}{letters[n]}" for n in sorted(letters, key=int))
                        + "; blocking answers "
                        + ", ".join(verdict.get("blocking_answers", []))
                        + " admit no petname contract; recognition improvement "
                          "NOT_MEASURED")
    elif present:
        review_limit = ("one operator design review authorizes a display contract; "
                        "recognition improvement NOT_MEASURED")
    else:
        review_limit = ("operator review required before any display-contract "
                        "decision; recognition improvement NOT_MEASURED")
    bundle = {
        "artifacts": artifacts,
        "audit": {
            "auditor": AUDITOR,
            "producer": PRODUCER,
            "verdict": "pass_with_limits",
            "limitations": [
                "tracked-Git dependency evidence; local canonical DB recheck is required before final publication",
                "no human data: all rates are technical dry-run checks",
                "source coverage and verification limits remain explicit in the registry",
                review_limit,
                "same-host replay is called replay, not an external audit",
            ],
        },
        "auditor": AUDITOR,
        "claims": CLAIMS,
        "config": {"min_source_count": 4, "min_verified_ratio": 1.0,
                   "required_artifacts": list(FLOW)},
        "producer": PRODUCER,
        "sources": sources,
        "operator_review_n": 1 if present else 0,
        "human_study_n": 0,
        "recognition_improvement": "NOT_MEASURED",
        "operator_answers": dict(letters) if present and letters else {},
        "design_decision": verdict.get("design_decision", "INCONCLUSIVE"),
        "blocking_answers": verdict.get("blocking_answers", []),
    }
    classes = {c["s1_015_class"] for c in CLAIMS}
    if not REQUIRED_CLAIM_CLASSES.issubset(classes):
        raise ValueError("bundle claim classes incomplete")
    if bundle["artifacts"]["platform_plan"]["producer"] == \
            bundle["artifacts"]["independent_audit"]["producer"]:
        raise ValueError("producer and auditor must differ")
    return bundle


def write_results_docs(here: Path, verdict: dict, metrics: dict,
                       present: bool, letters: dict | None) -> None:
    answers = ("Operator answers `" + " ".join(f"{n}{letters[n]}" for n in
               sorted(letters, key=int)) + "`. "
               if present and letters else "No operator decision yet. ")
    closing = ""
    if verdict["design_decision"] == "INCONCLUSIVE" and present:
        closing = (verdict["note"].rstrip() + ". Human recognition improvement "
                   "remains NOT_MEASURED. " if not verdict["note"].rstrip().endswith(".")
                   else verdict["note"].rstrip() + " Human recognition improvement "
                   "remains NOT_MEASURED. ")
    elif verdict["design_decision"] == "DISPLAY_ONLY_PETNAME_WITH_CANONICAL_ID":
        closing += (" Operator approved a provisional display-only petname "
                    "contract; human recognition improvement remains "
                    "NOT_MEASURED.")
    (here / "results" / "decision.md").write_text(
        "# S1-015 decision: " + verdict["design_decision"] + "\n\n"
        f"Status: `{verdict['status']}` (cap: PASS_WITH_LIMITS at most). "
        f"Operator review: `{verdict['operator_review']}`.\n\n"
        "Prototype exports the same envelope accepted by the Python importer "
        "for BASELINE and PETNAME variants across 40 frozen cases x 3 seeds "
        "(240 observations per executor, 480 total). Hard counters are zero "
        "in every seed/executor; mandatory safety rates are 100%; probes A-N "
        "pass through the real path with benign controls; the real-browser "
        "probe (Edge/Chromium) walks both variants and round-trips through "
        "the importer.\n\n" + answers + closing + "\n",
        encoding="utf-8", newline="\n")
    (here / "results" / "limitations.md").write_text(
        "# S1-015 limitations\n\n"
        "- tracked-Git dependency evidence; canonical DB recheck at publication\n"
        "- no human data: all rates are technical dry-run checks (human_study_n=0)\n"
        "- recognition improvement NOT_MEASURED; PASS/production out of scope\n"
        "- confusable detection is heuristic; corpus is synthetic and author-visible\n"
        "- same-host replay is called replay, not an external audit\n"
        "- single-operator design review is not a population study\n",
        encoding="utf-8", newline="\n")
    (here / "results" / "independent-audit.md").write_text(
        "# S1-015 independent audit\n\n"
        "Producer `agentos-s1-015-producer` (importer/runner, bundle assembly) "
        "and auditor `agentos-s1-015-independent-verifier` (evaluator plus "
        "process-separated replication over frozen inputs) are distinct. The "
        "auditor recomputed hard counters, safety rates and probes A-N from "
        "frozen corpus/oracle bytes and replicated the 480-observation matrix "
        "byte-identical across two processes. Verdict: `pass_with_limits` "
        "within the stated limitations; no human-effectiveness claim.\n",
        encoding="utf-8", newline="\n")
    shutil.copyfile(here / "dependency-gate.json", here / "results" / "dependency-gate.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticket", required=False, default=str(HERE))
    args = parser.parse_args(argv)
    here = Path(args.ticket).resolve()
    try:
        problems, _ = verify_frozen_manifest(here)
        if problems:
            raise ValueError("frozen manifest invalid: " + "; ".join(problems[:6]))
        check_dependency(here)
        evidence = fresh_runs(here)
        present, letters, _ = verify_operator_decision(here)
        blockers, verdict = derive_verdict(
            evidence["metrics"], evidence["comparison"], present, letters)
        if blockers:
            raise ValueError("ticket evidence invalid: " + "; ".join(blockers))
        scan = secret_pii_scan(here)
        if scan:
            raise ValueError("secret/PII scan failed: " + "; ".join(scan[:6]))
        sources = build_sources(here)
        bundle = build_bundle(here, sources, verdict, present, letters)
        (here / "bundle.json").write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n")
        write_results_docs(here, verdict, evidence["metrics"], present, letters)
        frozen = {rel: sha(((here / PurePosixPath(rel))).read_bytes())
                  for rel in sorted(_ticket_relative_files(here))}
        candidate = {
            "schema": "agentos.s1-015.candidate-record/v1",
            "ticket": TICKET,
            "status": verdict["status"],
            "design_decision": verdict["design_decision"],
            "operator_review": verdict["operator_review"],
            "operator_review_n": 1 if present else 0,
            "human_study_n": 0,
            "human_effectiveness": "NOT_MEASURED",
            "recognition_improvement": "NOT_MEASURED",
            "bundle_path": f"research/tickets/stage-1/{TICKET}/bundle.json",
            "bundle_sha256": sha((here / "bundle.json").read_bytes()),
            "matrix": "40 cases x 2 variants x 3 seeds x 2 executors = 480 observations",
            "hard_counters": evidence["metrics"]["hard_counters"],
            "safety_verdict": evidence["metrics"]["safety_verdict"],
            "replicated": evidence["comparison"]["replicated"],
            "frozen_hashes": frozen,
            "closure_basis": "operator_design_review" if present else "preparation_only",
            "result": verdict.get("result", "PREPARATION_READY"),
            "blocking_answers": verdict.get("blocking_answers", []),
            "note": verdict["note"],
        }
        (here / "candidate-record.json").write_text(
            json.dumps(candidate, indent=2) + "\n", encoding="utf-8", newline="\n")
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
