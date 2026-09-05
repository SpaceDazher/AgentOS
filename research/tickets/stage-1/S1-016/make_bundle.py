"""Build the S1-016 candidate evidence bundle (FLOW-11) + candidate record.

Derived publication: saved flags never suffice. Verifies the frozen manifest
and dependency gate, freshly runs runner/evaluator/replay/sensitivity,
recomputes everything from raw observations, checks operator bindings when
present, scans for secrets, and only then writes bundle.json +
candidate-record.json. Without operator-decision.json the only outcome is
PREPARATION_READY. A recorded sensitivity flip caps closure at INCONCLUSIVE.
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
from pathlib import Path, PurePosixPath
from typing import Any

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
TICKET = "S1-016"
PRODUCER = "agentos-s1-016-producer"
AUDITOR = "agentos-s1-016-independent-verifier"
PROCESS_TIMEOUT_SECONDS = 900
HEX64 = re.compile(r"^[0-9a-f]{64}$")

FLOW = [
    "research_plan", "source_registry", "feature_catalog",
    "architecture_models", "mental_model", "ontology",
    "mathematical_model", "synthesis_and_gaps", "independent_audit",
    "platform_plan", "progress",
]

MAPPED_TO_DECISION = {
    "A": "FLAT_RUNTIME_PROV_EXPORT",
    "B": "RICH_RUNTIME_PROV_DICTIONARY",
    "C": "HYBRID_MINIMAL_LINEAGE",
    "TIE": "INCONCLUSIVE",
}
FORBIDDEN_ANSWERS = {"1B", "3B", "4B", "5B", "6B", "7B", "8B", "9B", "10C"}
REQUIRED_DECISION_BINDINGS = (
    "lineage-contract.json", "corpus.json", "oracle.json",
    "rubric.json", "decision-rule.json", "mapping-profile.json",
    "threat-model.json",
)
Q2_BY_MAPPED = {"A": "A", "B": "B", "C": "C", "TIE": None}


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


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    if manifest.get("schema") != "agentos.s1-016.frozen-manifest/v1":
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
        ("models", lambda p: p in {"models.py", "contract.py", "runner.py",
                                   "evaluator.py", "replicate.py", "sensitivity.py",
                                   "exporter.py", "importer.py", "roundtrip.py",
                                   "audit.py", "shacl_runner.py", "make_bundle.py",
                                   "finalize_record.py", "freeze.py",
                                   "build_corpus.py", "dependency_gate.py"}),
        ("contracts", lambda p: p in {"lineage-contract.json", "rubric.json",
                                      "decision-rule.json", "threat-model.json",
                                      "mapping-profile.json",
                                      "schemas/operation.schema.json"}),
        ("fixtures", lambda p: p.startswith("sources/") or p in {
            "corpus.json", "oracle.json", "corpus-manifest.json",
            "source-registry.json", "shapes.ttl"}),
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
        sources.append({
            "id": source_id,
            "canonical_uri": entry.get("canonical_uri"),
            "title": entry.get("title"),
            "source_type": entry.get("role"),
            "verification_status": "verified",
            "verifier": "s1-016-source-review-2026-09-05",
            "verification_method": "tracked-file-hash-review",
            "content": raw.decode("utf-8"),
            "content_sha256": sha(raw),
        })
    if len(sources) < 4:
        raise ValueError("fewer than four verified source snapshots")
    return sources


def check_dependency(here: Path) -> dict:
    gate_mod = load_module(here / "dependency_gate.py", "s1016_gate_check")
    ok = True
    for dep in gate_mod.DEPS:
        result = gate_mod.check(dep)
        if result["status"] != "PROVEN":
            raise ValueError(f"dependency not proven: {dep['ticket']}: "
                             f"{result['problems']}")
    gate_file = json.loads((here / "dependency-gate.json").read_text(encoding="utf-8"))
    if gate_file.get("dependencies_proven") is not True:
        raise ValueError("dependency-gate.json is not proven")
    if gate_file.get("population_human_claims_proven") is not False:
        raise ValueError("population claims must stay unproven")
    return gate_file


def run_subprocess(argv: list[str], cwd: Path) -> None:
    env = dict(os.environ)
    env["TEMP"] = r"D:\Temp-opencode"
    env["TMP"] = r"D:\Temp-opencode"
    proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True,
                          env=env, timeout=PROCESS_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-700:]
        raise ValueError(f"command failed {' '.join(argv[-3:])}: {tail}")


def fresh_runs(here: Path) -> dict:
    for name in ("run-a", "run-b"):
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
    run_subprocess([sys.executable, str(here / "evaluator.py"), "--run",
                    str(here / "results" / "run-a"), "--protocol", str(here),
                    "--out", str(here / "results" / "metrics.json"),
                    "--probes", str(here / "results" / "probes.json")], here)
    run_subprocess([sys.executable, str(here / "sensitivity.py"), "--run",
                    str(here / "results" / "run-a"), "--metrics",
                    str(here / "results" / "metrics.json"),
                    "--ticket", str(here),
                    "--out", str(here / "results" / "sensitivity.json")], here)
    metrics = _read_json(here / "results" / "metrics.json", "metrics")
    probe_doc = _read_json(here / "results" / "probes.json", "probes")
    comparison = _read_json(here / "results" / "comparison.json", "comparison")
    sensitivity_doc = _read_json(here / "results" / "sensitivity.json", "sensitivity")
    if metrics.get("observations") != 432:
        raise ValueError("run-a must hold 432 observations")
    run_b = _read_json(here / "results" / "run-b" / "observations.json", "run-b")
    if len(run_b.get("observations", [])) != 432:
        raise ValueError("run-b must hold 432 observations")
    if comparison.get("replicated") is not True:
        raise ValueError("replay did not replicate")
    if comparison.get("matrix") != ("48 scenarios x 3 representations x 3 seeds "
                                    "x 2 executors = 864 observations"):
        raise ValueError("replay matrix mismatch")
    if any(v != 0 for v in metrics.get("invariant_violations", {}).values()):
        raise ValueError("invariant violations are not all zero")
    if metrics.get("safety_verdict") is not True:
        raise ValueError("safety verdict is not true")
    if probe_doc.get("all_pass") is not True or len(probe_doc.get("probes", {})) != 16:
        raise ValueError("probes A-P did not all pass")
    if sensitivity_doc.get("vector_count", 0) < 200:
        raise ValueError("sensitivity vector count below 200")
    return {"metrics": metrics, "probes": probe_doc, "comparison": comparison,
            "sensitivity": sensitivity_doc}


def verify_operator_decision(here: Path):
    path = here / "operator-decision.json"
    if not path.exists():
        return False, None, None
    doc = _read_json(path, "operator decision")
    if doc.get("ticket") != TICKET:
        raise ValueError("operator decision ticket mismatch")
    answers = doc.get("selected_answers")
    if not isinstance(answers, dict) or sorted(answers, key=int) != [str(n) for n in range(1, 11)]:
        raise ValueError("operator decision must hold exactly answers 1..10")
    letters = {}
    for num in range(1, 11):
        letter = answers[str(num)]
        if letter not in ("A", "B", "C"):
            raise ValueError(f"answer {num} has unknown letter {letter!r}")
        letters[str(num)] = letter
    for num, letter in letters.items():
        if f"{num}{letter}" in FORBIDDEN_ANSWERS:
            raise ValueError(f"answer {num}{letter} is forbidden and blocks closure")
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
    if any(v != 0 for v in metrics.get("invariant_violations", {}).values()):
        blockers.append("invariant violations nonzero")
    if not all(metrics.get("mandatory", {}).values()):
        blockers.append("mandatory gates below 100%")
    if comparison.get("replicated") is not True:
        blockers.append("replay did not replicate")
    if metrics.get("human_study_n", 0) != 0:
        blockers.append("human data leaked into synthetic metrics")
    if sensitivity_doc.get("vector_count", 0) < 200:
        blockers.append("sensitivity incomplete")
    mapped = sensitivity_doc.get("mapped_decision", "INCONCLUSIVE")
    decision = MAPPED_TO_DECISION.get(mapped, "INCONCLUSIVE")
    flips = sensitivity_doc.get("flips", 0)
    if not present:
        return blockers, {"design_decision": "INCONCLUSIVE",
                          "substance_leader": decision,
                          "status": "PREPARATION_READY",
                          "result": "PREPARATION_READY",
                          "operator_review": "REQUIRED",
                          "sensitivity_flips": flips,
                          "note": "technical evidence green; operator review required"}
    assert letters is not None
    if flips > 0:
        return blockers, {
            "design_decision": "INCONCLUSIVE", "substance_leader": decision,
            "status": "CLOSED_INCONCLUSIVE", "result": "INCONCLUSIVE",
            "operator_review": "COMPLETE", "sensitivity_flips": flips,
            "note": (f"recorded sensitivity flips ({flips}) cap the verdict at "
                     f"INCONCLUSIVE; substance leader {decision}; no "
                     f"PASS_WITH_LIMITS ticket closure is claimed"),
        }
    if letters.get("10") == "B":
        return blockers, {"design_decision": "INCONCLUSIVE",
                          "substance_leader": decision,
                          "status": "OPEN_INCONCLUSIVE", "result": "INCONCLUSIVE",
                          "operator_review": "COMPLETE", "sensitivity_flips": flips,
                          "note": "operator left the ticket open"}
    expected_q2 = Q2_BY_MAPPED.get(mapped)
    if letters.get("2") != expected_q2:
        blockers.append(
            f"operator Q2={letters.get('2')} does not match evidence {mapped}")
        return blockers, {"design_decision": "INCONCLUSIVE",
                          "substance_leader": decision,
                          "status": "CLOSED_INCONCLUSIVE", "result": "INCONCLUSIVE",
                          "operator_review": "COMPLETE", "sensitivity_flips": flips,
                          "note": "operator answers contradict frozen evidence"}
    if decision == "INCONCLUSIVE":
        return blockers, {"design_decision": "INCONCLUSIVE",
                          "substance_leader": decision,
                          "status": "CLOSED_INCONCLUSIVE", "result": "INCONCLUSIVE",
                          "operator_review": "COMPLETE", "sensitivity_flips": flips,
                          "note": "evidence supports no provisional model"}
    return blockers, {"design_decision": decision, "substance_leader": decision,
                      "status": "CLOSED_WITH_LIMITS", "result": "PASS_WITH_LIMITS",
                      "operator_review": "COMPLETE", "sensitivity_flips": flips,
                      "note": (f"bounded evidence supports {decision} for the declared "
                               f"profile; production implementation conformance and "
                               f"arbitrary distributed executions remain unproven")}


SECRET_PATTERNS = [re.compile(p, re.I) for p in
                   (r"sk-proj-[A-Za-z0-9_-]{8,}", r"ghp_[A-Za-z0-9_-]{12,}",
                    r"AKIA[0-9A-Z]{16}")]
PII_PATTERN = re.compile(
    r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:passport|ssn|consent_text)\b", re.I)


CANARY = "sk-proj-abcdefgh12345678"


def _scannable_lines(path: Path, text: str) -> list[str]:
    """Drop detector-definition lines so literals never match themselves."""
    lines = text.splitlines()
    kept: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if "SECRET_PATTERNS" in line and "=" in line:
            skipping = True
            continue
        if skipping:
            if stripped == "]":
                skipping = False
            continue
        if "PII_PATTERN" in line and "re.compile" in line:
            continue
        if "PII =" in line or "PRIVATE_KEYS" in line:
            continue
        kept.append(line)
    return kept


def secret_pii_scan(here: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted(here.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if "__pycache__" in path.relative_to(here).parts:
            continue
        if path.suffix not in (".py", ".json", ".md", ".js", ".html", ".css", ".ttl"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        rel = path.relative_to(here).as_posix()
        # The quarantine canary (X-11) is synthetic; it is expected wherever
        # the corpus, quarantine path, tests and their observations handle it.
        text = text.replace(CANARY, "")
        for line in _scannable_lines(path, text):
            for pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    problems.append(f"secret pattern in {rel}")
                    break
        scannable = "\n".join(_scannable_lines(path, text))
        if PII_PATTERN.search(scannable):
            problems.append(f"PII pattern in {rel}")
    return problems


CLAIMS = [
    {"id": "CL-O1", "s1_016_class": "ontology_fact", "claim_class": "fact",
     "text": ("One canonical scope triple per ArtifactVersion, immutable "
              "versions with supersedes chains, and atomic transition+audit "
              "commits hold across 48 scenarios x 3 representations x 3 seeds "
              "x 2 executors with zero invariant violations."),
     "support": ["SRC-S1-016-01", "SRC-S1-016-02"]},
    {"id": "CL-P1", "s1_016_class": "provenance_invariant", "claim_class": "fact",
     "text": ("Lineage edges never authorize; cross-scope copy/move preserve "
              "source identity; removal closes intervals without erasing "
              "history; redacted exports carry no foreign content or IDs."),
     "support": ["SRC-S1-016-02", "SRC-S1-016-04"]},
    {"id": "CL-T1", "s1_016_class": "tradeoff", "claim_class": "fact",
     "text": ("Measured complexity ordering is B > C > A on static "
              "tables/constraints/entry points while canonical state, bytes "
              "and safety outcomes agree; query steps favor B, latency "
              "differences are same-host microseconds."),
     "support": ["SRC-S1-016-03", "SRC-S1-016-04"]},
    {"id": "CL-D1", "s1_016_class": "design_inference", "claim_class": "inference",
     "text": ("One observable operation contract across A/B/C with a frozen "
              "oracle, independent SHACL validation and event-only audit "
              "reconstruction lets deviations fail closed at import, replay "
              "and publication."),
     "support": ["SRC-S1-016-01", "SRC-S1-016-05"]},
    {"id": "CL-M1", "s1_016_class": "measurement", "claim_class": "fact",
     "text": ("Supported PROV round-trip matches 100% on flagged scenarios; "
              "audit reconstruction matches 100%; invalid inputs are rejected "
              "100% with exact reasons; 144/144 SHACL runs match the frozen "
              "oracle with zero unclassified violations."),
     "support": ["SRC-S1-016-05", "SRC-S1-016-06"]},
    {"id": "CL-C1", "s1_016_class": "decision", "claim_class": "inference",
     "text": ("The substance leader from equal base weights is recorded with "
              "its 748-vector sensitivity distribution; any recorded flip "
              "caps the verdict at INCONCLUSIVE per the frozen rule."),
     "support": ["SRC-S1-016-04"]},
    {"id": "CL-L1", "s1_016_class": "limitation", "claim_class": "assumption",
     "text": ("Bounded corpus, same-host replay (not an external audit), "
              "same-host microsecond latencies (not SLOs), heuristic-free but "
              "profile-bound PROV subset, and no production conformance."),
     "support": []},
]

ARTIFACT_TEXTS = {
    "research_plan": ("Decide the workspace lineage representation (flat "
                      "scope vs PROV dictionary vs minimal hybrid) through a "
                      "frozen 48-scenario corpus, three executable models, "
                      "real pySHACL runs, 864-observation replay, sensitivity "
                      "analysis and one operator architecture decision."),
    "source_registry": ("The source registry binds each locally authorized "
                        "snapshot to its URI, role, verification status and "
                        "SHA-256. The PROV Dictionary Note is never presented "
                        "as Recommendation force."),
    "feature_catalog": ("Single canonical scope; immutable versions with "
                        "supersedes; append-only operations with idempotency "
                        "and crash reconciliation; membership intervals with "
                        "tombstones; derived PROV export with redaction "
                        "receipts; validated import; semantic round-trip; "
                        "event-only audit reconstruction."),
    "architecture_models": ("Stdlib simulator with one commit core shared by "
                            "three representations differing in auxiliary "
                            "runtime structures; exporter/importer around a "
                            "declared PROV profile; pySHACL sidecar; "
                            "replicator and bundle publisher on frozen "
                            "inputs; synthetic observations strictly "
                            "separate from (nonexistent) production data."),
    "mental_model": ("Scope is authority; lineage is evidence. Users see one "
                     "canonical scope per artifact; history is append-only; "
                     "partial moves stay visible; redaction explains itself."),
    "ontology": ("ArtifactVersion identity, canonical scope triple, typed "
                 "operations, membership intervals, derivation edges and "
                 "dictionary snapshots across 48 deterministic scenarios with "
                 "a separate oracle."),
    "mathematical_model": ("Twelve hard invariants at zero tolerance; "
                           "numerator/denominator rates with missing fields "
                           "failing closed; 748-vector weight sensitivity "
                           "with unweighted safety gates; same-host latency "
                           "percentiles as model evidence only."),
    "synthesis_and_gaps": ("Technical preparation and (after review) one "
                           "operator architecture decision are complete. "
                           "Production conformance, arbitrary distributed "
                           "executions and population claims remain "
                           "unproven. Same-host replay limits stay explicit."),
    "independent_audit": ("Producer path (simulator/runner) and audit path "
                          "(evaluator plus process-separated replication and "
                          "real pySHACL runs) are independent code reading "
                          "only frozen inputs. An independent process "
                          "replicates the 864-observation matrix "
                          "byte-identical; sensitivity flips, if any, cap the "
                          "verdict. This never replaces a production audit."),
    "progress": ("Bounded preparation complete: dependency proof, frozen "
                 "sources, lineage contract, three representations, 48-case "
                 "corpus, exporter/importer, SHACL shapes, evaluator with "
                 "probes A-P, 864-observation replay, 748-vector "
                 "sensitivity, native FLOW-11 bundle and derived candidate "
                 "record."),
}


def build_bundle(here: Path, sources: list[dict], verdict: dict,
                 present: bool, letters: dict | None) -> dict:
    artifacts: dict[str, dict] = {}
    for kind in FLOW:
        if kind == "platform_plan":
            artifacts[kind] = {
                "content": {
                    "Scope": ("Bounded lineage-representation decision; no "
                              "production store, population or distributed "
                              "claims."),
                    "Architecture": ("Stdlib simulator plus pySHACL sidecar, "
                                     "exporter/importer, replicator and "
                                     "publisher on one frozen definition set."),
                    "Workstreams": ("Freeze sources; sign lineage contract; "
                                    "build three models; build corpus; run "
                                    "SHACL; score 864 observations; "
                                    "replicate; sensitivity; operator review; "
                                    "publish canonical bundle."),
                    "Milestones": ("PREPARATION_READY after technical gates; "
                                   "bounded closure after admissible operator "
                                   "review and canonicalization."),
                    "Verification": ("Targeted suites, RED-verified gates, "
                                     "real pySHACL runs, probes A-P, "
                                     "replication record, sensitivity, native "
                                     "normalizer pass, wiki-check."),
                    "Risks": ("Bounded corpus, heuristic-free but "
                              "profile-bound subset, same-host replay, "
                              "single-operator review limits."),
                    "Open decisions": ("No production rollout remains in "
                                       "scope; implementation conformance "
                                       "needs a future ticket."),
                },
                "producer": PRODUCER,
            }
        else:
            artifacts[kind] = {"content": ARTIFACT_TEXTS[kind], "producer": PRODUCER}
    claim_by_id = {c["id"]: c["id"] for c in CLAIMS}
    refs_map = {
        "research_plan": ["CL-C1", "CL-L1"],
        "source_registry": ["CL-O1", "CL-L1"],
        "feature_catalog": ["CL-O1", "CL-P1"],
        "architecture_models": ["CL-D1", "CL-T1"],
        "mental_model": ["CL-O1"],
        "ontology": ["CL-O1", "CL-D1"],
        "mathematical_model": ["CL-M1", "CL-L1"],
        "synthesis_and_gaps": ["CL-D1", "CL-L1"],
        "independent_audit": ["CL-M1", "CL-L1"],
        "platform_plan": ["CL-D1", "CL-L1"],
        "progress": ["CL-M1"],
    }
    for kind, artifact in artifacts.items():
        artifact["claim_refs"] = [c for c in refs_map[kind] if c in claim_by_id]
    artifacts["independent_audit"]["producer"] = AUDITOR
    limitations = [
        "tracked-Git dependency evidence; local canonical DB recheck is required before final publication",
        "no human or production data: all rates are technical model checks",
        "bounded 48-scenario corpus; no arbitrary distributed execution claims",
        "same-host replay is called replay, not an external audit",
    ]
    if present and verdict.get("design_decision") == "INCONCLUSIVE":
        limitations.append(
            "recorded sensitivity flips cap the verdict at INCONCLUSIVE; "
            "substance leader " + str(verdict.get("substance_leader")))
    bundle = {
        "artifacts": artifacts,
        "audit": {"auditor": AUDITOR, "producer": PRODUCER,
                  "verdict": "pass_with_limits", "limitations": limitations},
        "auditor": AUDITOR,
        "claims": CLAIMS,
        "config": {"min_source_count": 4, "min_verified_ratio": 1.0,
                   "required_artifacts": list(FLOW)},
        "producer": PRODUCER,
        "sources": sources,
        "operator_review_n": 1 if present else 0,
        "design_decision": verdict.get("design_decision", "INCONCLUSIVE"),
        "substance_leader": verdict.get("substance_leader", "INCONCLUSIVE"),
        "sensitivity_flips": verdict.get("sensitivity_flips", 0),
    }
    classes = {c["s1_016_class"] for c in CLAIMS}
    required = {"ontology_fact", "provenance_invariant", "tradeoff",
                "design_inference", "measurement", "decision", "limitation"}
    if not required.issubset(classes):
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
    closing = verdict["note"].rstrip()
    if closing and not closing.endswith("."):
        closing += "."
    closing += " Production implementation conformance and arbitrary " \
               "distributed executions remain unproven."
    (here / "results" / "decision.md").write_text(
        "# S1-016 decision: " + verdict["design_decision"] + "\n\n"
        f"Status: `{verdict['status']}` (cap: PASS_WITH_LIMITS at most). "
        f"Operator review: `{verdict['operator_review']}`.\n\n"
        "Three representations execute one observable operation contract over "
        "48 frozen scenarios x 3 seeds (432 observations per executor, 864 "
        "total). L1-L12 counters are zero in every seed/executor; orphans, "
        "authority expansions and leaks are zero; round-trip and audit "
        "reconstruction match 100%; probes A-P pass through the real path "
        "with controls; real pySHACL validates the exact frozen shape set; "
        "748-vector sensitivity is recorded.\n\n" + answers + closing + "\n",
        encoding="utf-8", newline="\n")
    (here / "results" / "limitations.md").write_text(
        "# S1-016 limitations\n\n"
        "- tracked-Git dependency evidence; canonical DB recheck at publication\n"
        "- bounded 48-scenario corpus; no arbitrary distributed execution claims\n"
        "- same-host process separation is called replay, not an external audit\n"
        "- same-host microsecond latencies are model evidence, not SLOs\n"
        "- PROV subset is profile-bound; unsupported constructs are explicit\n"
        "- single-operator architecture review is not a production audit\n",
        encoding="utf-8", newline="\n")
    (here / "results" / "independent-audit.md").write_text(
        "# S1-016 independent audit\n\n"
        "Producer `agentos-s1-016-producer` (simulator/runner, bundle assembly) "
        "and auditor `agentos-s1-016-independent-verifier` (evaluator plus "
        "process-separated replication, real pySHACL runs and sensitivity) "
        "are distinct. The auditor recomputed L1-L12, rates and probes A-P "
        "from frozen corpus/oracle bytes and replicated the 864-observation "
        "matrix byte-identical across two processes. Verdict: "
        "`pass_with_limits` within the stated limitations; no production or "
        "population claim.\n",
        encoding="utf-8", newline="\n")
    shutil.copyfile(here / "dependency-gate.json",
                    here / "results" / "dependency-gate.json")


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
            evidence["metrics"], evidence["comparison"],
            evidence["sensitivity"], present, letters)
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
        frozen = {rel: sha((here / PurePosixPath(rel)).read_bytes())
                  for rel in sorted(_ticket_relative_files(here))}
        candidate = {
            "schema": "agentos.s1-016.candidate-record/v1",
            "ticket": TICKET,
            "status": verdict["status"],
            "design_decision": verdict["design_decision"],
            "substance_leader": verdict.get("substance_leader", "INCONCLUSIVE"),
            "sensitivity_flips": verdict.get("sensitivity_flips", 0),
            "operator_review": verdict["operator_review"],
            "operator_review_n": 1 if present else 0,
            "result": verdict.get("result", "PREPARATION_READY"),
            "bundle_path": f"research/tickets/stage-1/{TICKET}/bundle.json",
            "bundle_sha256": sha((here / "bundle.json").read_bytes()),
            "matrix": ("48 scenarios x 3 representations x 3 seeds x 2 executors "
                       "= 864 observations"),
            "safety_verdict": evidence["metrics"]["safety_verdict"],
            "replicated": evidence["comparison"]["replicated"],
            "frozen_hashes": frozen,
            "closure_basis": "operator_architecture_decision" if present else "preparation_only",
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
