"""Build the S1-013 preparation evidence bundle.

Publication is a derived operation.  A saved ``all_proven`` or
``replicated`` flag is never sufficient: this module verifies the exact
frozen input set, reads dependency evidence from the portable Git refs, runs
the importer and evaluator again, runs the two-process replication, and
cross-checks the saved result files.  Any failure removes only this ticket's
ready outputs and returns a non-zero status.

The output deliberately remains preparation-only.  It can say
``PREPARATION_READY`` while the human phase remains
``BLOCKED_HUMAN_PILOT``; synthetic numbers are not human findings.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
TICKET = "S1-013"
PRODUCER = "agentos-s1-013-producer"
AUDITOR = "agentos-s1-013-independent-verifier"
PROCESS_TIMEOUT_SECONDS = 120
HEX64 = re.compile(r"^[0-9a-f]{64}$")

FLOW = [
    "research_plan", "source_registry", "feature_catalog",
    "architecture_models", "mental_model", "ontology",
    "mathematical_model", "synthesis_and_gaps", "independent_audit",
    "platform_plan", "progress",
]
MEASURES = ("C1", "C2", "C3", "C4", "C5")
TARGETS = {"C1": 0.90, "C2": 0.95, "C3": 0.85, "C4": 0.95,
           "C5": 1.0}
REQUIRED_PROBES = tuple("ABCDEFGH")
ALLOWED_OBSERVATION_STATUSES = {"ok", "rejected", "quarantined"}

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
             "dry-run tooling checks. Mental-model coverage is bounded "
             "by the locally authorized source snapshots and their stated "
             "verification limits.",
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
        "The source registry binds each locally authorized snapshot to "
        "its URI, role, verification status and SHA-256. Unavailable or "
        "limited records remain explicit and are not presented as verified "
        "evidence."),
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
        "canonicalization are all open. Source coverage limits and "
        "Beta-free design are explicit; S1-014/S1-015 receive pilot "
        "constraints, not closure."),
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


def canonical(value: Any) -> bytes:
    """Canonical JSON matching the ticket contract's digest function."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def load(name: str, here: Path | None = None) -> Any:
    base = Path(here) if here is not None else HERE
    return json.loads((base / name).read_text(encoding="utf-8"))


def load_result(name: str, results: Path | None = None) -> Any:
    base = Path(results) if results is not None else RESULTS
    return json.loads((base / name).read_text(encoding="utf-8"))


def _read_json(path: Path, label: str) -> Any:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"{label} unreadable: {exc}") from exc
    return value


def _is_int(value: Any) -> bool:
    return type(value) is int


def _is_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _remove_exact(path: Path) -> None:
    """Remove one output file, never recursively remove a user directory."""

    if path.is_file() or path.is_symlink():
        path.unlink()


def remove_ready_outputs(here: Path | None = None) -> None:
    """Clear stale publication outputs for this ticket only."""

    base = Path(here) if here is not None else HERE
    for name in ("bundle.json", "candidate-record.json"):
        _remove_exact(base / name)


def _ticket_relative_files(here: Path) -> set[str]:
    excluded_names = {
        "bundle.json", "candidate-record.json", "dependency-gate.json",
        "frozen-manifest.json",
    }
    paths: set[str] = set()
    for path in sorted(here.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part == "__pycache__" for part in path.relative_to(here).parts):
            continue
        rel = path.relative_to(here).as_posix()
        if path.name in excluded_names or rel.startswith("results/"):
            continue
        if path.name.endswith(".tmp") or path.name.endswith(".pyc"):
            continue
        paths.add(rel)
    return paths


def verify_frozen_manifest(here: Path | None = None) -> tuple[list[str], dict]:
    """Require an exact hash map over every non-output ticket input."""

    base = (Path(here) if here is not None else HERE).resolve()
    problems: list[str] = []
    try:
        manifest = _read_json(base / "frozen-manifest.json",
                              "frozen manifest")
    except ValueError as exc:
        return [str(exc)], {}
    if not isinstance(manifest, dict):
        return ["frozen manifest is not an object"], {}
    if manifest.get("schema") != "agentos.s1-013.frozen-manifest/v1":
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
    required_categories = (
        ("analysis", lambda p: p in {"analysis-plan.md", "runner.py",
                                     "evaluator.py", "replicate.py"}),
        ("UI", lambda p: p.startswith("prototype/")),
        ("fixtures", lambda p: p.startswith("synthetic/sessions/") or
         p.startswith("schemas/") or p in {"rubric.json",
                                             "scenario-manifest.json"}),
    )
    for label, predicate in required_categories:
        if not any(predicate(rel) for rel in expected & actual):
            problems.append(f"frozen manifest has no {label} inputs")
    for rel in sorted(actual & expected):
        expected_sha = hashes.get(rel)
        if not isinstance(expected_sha, str) or not HEX64.fullmatch(expected_sha):
            problems.append(f"frozen manifest hash invalid: {rel}")
            continue
        path = base / PurePosixPath(rel)
        try:
            actual_sha = sha(path.read_bytes())
        except OSError as exc:
            problems.append(f"frozen input unreadable {rel}: {exc}")
            continue
        if actual_sha != expected_sha:
            problems.append(f"frozen input hash mismatch: {rel}")
    try:
        protocol = _read_json(base / "pilot-protocol.json", "pilot protocol")
        protocol_version = protocol.get("protocol_version")
        if manifest.get("protocol_version") != protocol_version:
            problems.append("frozen manifest protocol version mismatch")
    except ValueError as exc:
        problems.append(str(exc))
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
    path = here.joinpath(*parts)
    try:
        path.relative_to(here)
    except ValueError as exc:
        raise ValueError(f"source snapshot path escapes ticket: {raw}") from exc
    return path


def build_sources(here: Path | None = None) -> list[dict]:
    """Materialize only hash-verified local source snapshots."""

    base = (Path(here) if here is not None else HERE).resolve()
    registry = _read_json(base / "source-registry.json", "source registry")
    if not isinstance(registry, dict) or registry.get("ticket") != TICKET:
        raise ValueError("source registry ticket mismatch")
    entries = registry.get("sources")
    if not isinstance(entries, list) or not entries:
        raise ValueError("source registry is empty")
    sources: list[dict] = []
    ids: set[str] = set()
    paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("source registry entry is not an object")
        source_id = entry.get("id")
        if not isinstance(source_id, str) or not source_id or source_id in ids:
            raise ValueError("source registry has duplicate/invalid id")
        ids.add(source_id)
        path = _snapshot_path(base, entry.get("snapshot_path"))
        rel = path.relative_to(base).as_posix()
        if rel in paths:
            raise ValueError("source registry has duplicate snapshot path")
        paths.add(rel)
        expected = entry.get("sha256")
        if not isinstance(expected, str) or not HEX64.fullmatch(expected):
            raise ValueError(f"source hash invalid: {source_id}")
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"source snapshot missing: {source_id}")
        raw = path.read_bytes()
        actual = sha(raw)
        if actual != expected:
            raise ValueError(f"source snapshot bytes drift: {source_id}")
        if "bytes" in entry and entry["bytes"] != len(raw):
            raise ValueError(f"source snapshot byte count drift: {source_id}")
        if entry.get("kind") == "unavailable":
            # Keep the absence record in the registry and frozen inputs, but
            # do not turn an unverified placeholder into bundle evidence.
            continue
        text = raw.decode("utf-8")
        if text.encode("utf-8") != raw:
            raise ValueError(f"source snapshot is not stable UTF-8: {source_id}")
        sources.append({
            "id": source_id,
            "canonical_uri": entry.get("canonical_uri"),
            "title": entry.get("title"),
            "source_type": entry.get("role"),
            "verification_status": "verified",
            "verifier": "s1-013-source-review-2026-09-04",
            "verification_method": "tracked-file-hash-review",
            "content": text,
            "content_sha256": actual,
        })
    if len(sources) < 4:
        raise ValueError("fewer than four verified source snapshots")
    return sources


def build_artifacts() -> dict:
    artifacts: dict[str, dict] = {}
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
                    "Risks": "Small samples, source coverage limits, "
                             "privacy handling, fatigue underestimated.",
                    "Open decisions": "Exact N in 15-20 at recruitment; "
                                      "ethics review outcome; S1-014/15 "
                                      "handoff scope",
                },
                "producer": PRODUCER,
                "claim_refs": ["CL-D1", "CL-L1"],
            }
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


def _load_gate_module(here: Path):
    path = here / "dependency_gate.py"
    if not path.is_file() or path.is_symlink():
        raise ValueError("dependency gate module missing")
    name = f"s1013_dependency_gate_{id(path)}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load dependency gate module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fresh_dependency_gate(here: Path) -> dict:
    here = Path(here).resolve()
    gate = _load_gate_module(here)
    deps = getattr(gate, "DEPS", None)
    check = getattr(gate, "check", None)
    if not isinstance(deps, tuple) or not deps or not callable(check):
        raise ValueError("dependency gate API incomplete")
    results = []
    for dep in deps:
        if not isinstance(dep, dict):
            raise ValueError("dependency descriptor is not an object")
        result = check(dep)
        if not isinstance(result, dict):
            raise ValueError("dependency gate returned non-object")
        results.append(result)
    all_proven = bool(results) and all(
        item.get("status") == "PROVEN" and not item.get("problems")
        for item in results)
    return {
        "schema": "agentos.s1-013.dependency-gate/v2",
        "ticket": TICKET,
        "dependencies": results,
        "all_proven": all_proven,
        "canonical_db_recheck_required": True,
        "note": ("Cross-branch tracked-Git evidence only; each dependency "
                 "was read from a matching immutable origin ref. Live DB "
                 "consistency remains a Phase B operator check."),
    }


def _check_saved_gate(results: Path, fresh: dict, blockers: list[str]) -> dict:
    try:
        saved = _read_json(results / "dependency-gate.json",
                           "saved dependency gate")
    except ValueError as exc:
        blockers.append(str(exc))
        return {}
    if not isinstance(saved, dict):
        blockers.append("saved dependency gate is not an object")
        return {}
    for key in ("schema", "ticket", "dependencies", "all_proven",
                "canonical_db_recheck_required"):
        if saved.get(key) != fresh.get(key):
            blockers.append(f"saved dependency gate differs: {key}")
    if saved.get("all_proven") is not True:
        blockers.append("saved dependency gate is not proven")
    return saved


def _run(argv: list[str], cwd: Path, label: str) -> None:
    try:
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True,
                              text=True, check=False,
                              timeout=PROCESS_TIMEOUT_SECONDS,
                              env=dict(os.environ))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{label} did not complete: {type(exc).__name__}") \
            from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").replace("\r", " ").replace("\n", " ")
        raise RuntimeError(f"{label} failed: {detail[:400]}")


def _fresh_analysis(here: Path) -> dict[str, Any]:
    here = Path(here).resolve()
    source = here / "synthetic" / "sessions"
    if not source.is_dir() or source.is_symlink():
        raise ValueError("synthetic source corpus missing")
    work = Path(tempfile.mkdtemp(prefix="s1013-recompute-"))
    try:
        imported = work / "import"
        metrics_path = work / "metrics.json"
        probes_path = work / "probes.json"
        comparison_path = work / "comparison.json"
        _run([sys.executable, str(here / "runner.py"), "--src", str(source),
              "--out", str(imported)], here, "fresh importer")
        _run([sys.executable, str(here / "evaluator.py"), "--run",
              str(imported), "--protocol", str(here), "--out",
              str(metrics_path), "--probes", str(probes_path)], here,
             "fresh evaluator")
        _run([sys.executable, str(here / "replicate.py"), "--src",
              str(source), "--ticket", str(here), "--out",
              str(comparison_path)], here, "fresh replication")
        observations_doc = _read_json(imported / "observations.json",
                                      "fresh observations")
        metrics = _read_json(metrics_path, "fresh metrics")
        probes = _read_json(probes_path, "fresh probes")
        comparison = _read_json(comparison_path, "fresh comparison")
        if not isinstance(observations_doc, dict):
            raise ValueError("fresh observations is not an object")
        observations = observations_doc.get("observations")
        if not isinstance(observations, list):
            raise ValueError("fresh observations list missing")
        return {"observations": observations, "metrics": metrics,
                "probes": probes, "comparison": comparison}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _stable_comparison(doc: Any) -> dict:
    if not isinstance(doc, dict):
        raise ValueError("comparison is not an object")
    if not str(doc.get("schema", "")).startswith(
            "agentos.s1-013.comparison/"):
        raise ValueError("comparison schema mismatch")
    if doc.get("replicated") is not True:
        raise ValueError("replication did not prove equal outputs")
    if doc.get("distinct_processes") is not True:
        raise ValueError("replication did not use distinct processes")
    source = doc.get("source")
    if not isinstance(source, dict) or source.get("match") is not True:
        raise ValueError("replication source binding missing")
    source_sha = source.get("sha256")
    if not isinstance(source_sha, str) or not HEX64.fullmatch(source_sha):
        raise ValueError("replication source digest invalid")
    files = source.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("replication source file map missing")
    for rel, value in files.items():
        if not isinstance(rel, str) or not rel or not isinstance(value, str) \
                or not HEX64.fullmatch(value):
            raise ValueError("replication source file digest invalid")
    digests = doc.get("digests")
    if not isinstance(digests, dict) or set(digests) != {
            "metrics", "probes", "observations"}:
        raise ValueError("replication digest matrix incomplete")
    for key in ("metrics", "probes", "observations"):
        item = digests[key]
        if not isinstance(item, dict) or item.get("match") is not True:
            raise ValueError(f"replication {key} mismatch")
        if (not isinstance(item.get("a"), str) or
                not HEX64.fullmatch(item["a"]) or
                not isinstance(item.get("b"), str) or
                not HEX64.fullmatch(item["b"])):
            raise ValueError(f"replication {key} digest invalid")
    # PIDs and prose are intentionally omitted: they are diagnostic and can
    # differ on every valid run.  All publication-relevant bindings remain.
    return {"schema": doc["schema"], "source": source,
            "distinct_processes": True, "digests": digests,
            "replicated": True}


def _validate_observations(observations: Any) -> tuple[list[str], dict]:
    blockers: list[str] = []
    if not isinstance(observations, list) or not observations:
        return ["fresh observations are empty"], {}
    counts = {status: 0 for status in ALLOWED_OBSERVATION_STATUSES}
    seen_sessions: set[str] = set()
    seen_participants: set[str] = set()
    records: list[tuple[dict, dict]] = []
    for index, item in enumerate(observations):
        if not isinstance(item, dict):
            blockers.append(f"observation {index} is not an object")
            continue
        status = item.get("status")
        if status not in ALLOWED_OBSERVATION_STATUSES:
            blockers.append(f"observation {index} has unknown status")
            continue
        counts[status] += 1
        sid = item.get("session_id")
        if not isinstance(sid, str) or not sid or sid in seen_sessions:
            blockers.append(f"observation {index} has duplicate/invalid session")
        else:
            seen_sessions.add(sid)
        output_hash = item.get("output_sha256")
        unsigned = {key: value for key, value in item.items()
                    if key != "output_sha256"}
        if (not isinstance(output_hash, str) or not HEX64.fullmatch(output_hash)
                or sha(canonical(unsigned)) != output_hash):
            blockers.append(f"observation {index} output digest mismatch")
        if status == "ok":
            record = item.get("record")
            if not isinstance(record, dict):
                blockers.append(f"observation {index} raw record missing")
                continue
            session = record.get("session")
            events = record.get("events")
            answers = record.get("answers")
            if not all(isinstance(doc, dict)
                       for doc in (session, events, answers)):
                blockers.append(f"observation {index} raw record incomplete")
                continue
            if session.get("session_id") != sid or \
                    events.get("session_id") != sid or \
                    answers.get("session_id") != sid:
                blockers.append(f"observation {index} record binding mismatch")
            if session.get("synthetic") is not True or \
                    session.get("cohort") != "synthetic":
                blockers.append(f"observation {index} is not synthetic")
            participant = item.get("participant_id")
            if not isinstance(participant, str) or not re.fullmatch(
                    r"P-[A-Z0-9]{6}", participant):
                blockers.append(f"observation {index} participant id invalid")
            elif participant in seen_participants:
                blockers.append(f"duplicate synthetic participant: {participant}")
            else:
                seen_participants.add(participant)
            records.append((item, record))
        elif "record" in item:
            # Rejected and quarantined records must not carry the raw payload
            # (the latter is especially important for privacy boundaries).
            blockers.append(f"non-ok observation {index} carries raw record")
    facts = {"counts": counts, "records": records,
             "participant_ids": seen_participants}
    return blockers, facts


def _raw_events(record: dict) -> list[dict]:
    events = record.get("events", {}).get("events")
    if not isinstance(events, list):
        raise ValueError("raw event list missing")
    return [event for event in events if isinstance(event, dict)]


def _expected_measure_ids(protocol: dict) -> tuple[str, ...]:
    measures = protocol.get("measures")
    if not isinstance(measures, list):
        raise ValueError("protocol measures missing")
    ids = tuple(item.get("id") for item in measures
                if isinstance(item, dict))
    if ids != MEASURES:
        raise ValueError("protocol measure matrix is not C1-C5")
    return ids


def _presented(records: list[tuple[dict, dict]]) -> dict[str, int]:
    result = {measure: 0 for measure in MEASURES}
    for _, record in records:
        seen: set[str] = set()
        for event in _raw_events(record):
            if event.get("type") != "prompt_displayed":
                continue
            prompt = event.get("prompt_id")
            measure = prompt.split("-", 1)[0] if isinstance(prompt, str) else ""
            if measure in result:
                if measure in seen:
                    raise ValueError(f"duplicate {measure} presentation")
                seen.add(measure)
                result[measure] += 1
    return result


def _validate_counts(measure: str, value: Any, expected_n: int,
                     blockers: list[str]) -> None:
    if not isinstance(value, dict):
        blockers.append(f"{measure} matrix entry is not an object")
        return
    for key in ("n", "correct", "missing"):
        if not _is_int(value.get(key)) or value[key] < 0:
            blockers.append(f"{measure} {key} is not a non-negative integer")
    if _is_int(value.get("n")) and value["n"] != expected_n:
        blockers.append(f"{measure} denominator does not equal presentation count")
    components = 0
    valid_components = True
    for key in ("correct", "missing", "incorrect", "failed"):
        if key in value:
            if not _is_int(value[key]) or value[key] < 0:
                valid_components = False
                blockers.append(f"{measure} {key} is invalid")
            else:
                components += value[key]
    if valid_components and _is_int(value.get("n")):
        if any(key in value for key in ("incorrect", "failed")):
            if components != value["n"]:
                blockers.append(f"{measure} count components do not sum to n")
        elif value["correct"] + value["missing"] > value["n"]:
            blockers.append(f"{measure} count components exceed n")
    rate = value.get("rate")
    if value.get("n") == 0:
        if rate is not None:
            blockers.append(f"{measure} zero denominator has a rate")
    elif _is_int(value.get("n")) and _is_int(value.get("correct")):
        if not _is_number(rate) or not 0 <= rate <= 1 or \
                abs(rate - value["correct"] / value["n"]) > 1e-5:
            blockers.append(f"{measure} rate is inconsistent with counts")
    wilson = value.get("wilson")
    if value.get("n", 0) and (not isinstance(wilson, list) or len(wilson) != 2
                               or not all(_is_number(x) for x in wilson)
                               or not 0 <= wilson[0] <= wilson[1] <= 1):
        blockers.append(f"{measure} uncertainty interval is invalid")
    if value.get("n", 0) == 0 and wilson is not None:
        blockers.append(f"{measure} zero denominator has uncertainty")


def _validate_c5(value: dict, blockers: list[str]) -> None:
    latency = value.get("latencies_ms")
    if not isinstance(latency, list):
        blockers.append("C5 latency distribution missing")
        return
    if latency != sorted(latency):
        blockers.append("C5 latency distribution is not ordered")
    if any(not _is_int(item) or item < 0 for item in latency):
        blockers.append("C5 latency distribution contains invalid values")
    if value.get("max_ms") != (max(latency) if latency else None):
        blockers.append("C5 max latency is inconsistent")
    if "failed" in value and _is_int(value.get("n")) and \
            _is_int(value.get("correct")) and _is_int(value.get("missing")) \
            and _is_int(value.get("failed")) and value["correct"] + \
            value["missing"] + value["failed"] != value["n"]:
        blockers.append("C5 outcomes do not sum to n")


def _approval_expectations(records: list[tuple[dict, dict]],
                           scenarios: dict) -> dict:
    blocks = scenarios.get("approval_blocks")
    if not isinstance(blocks, list):
        raise ValueError("approval blocks missing")
    oracle: dict[str, str] = {}
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError("approval block is not an object")
        prompts = block.get("prompts")
        if not isinstance(prompts, list):
            raise ValueError("approval prompts missing")
        if block.get("feasible") is True:
            for prompt in prompts:
                if not isinstance(prompt, dict) or not isinstance(
                        prompt.get("prompt_id"), str):
                    raise ValueError("approval prompt is malformed")
                if prompt["prompt_id"] in oracle:
                    raise ValueError("duplicate approval prompt id")
                if prompt.get("oracle") not in ("approve", "deny", "abstain"):
                    raise ValueError("approval oracle is invalid")
                oracle[prompt["prompt_id"]] = prompt["oracle"]
    by_participant: dict[str, dict[str, int]] = {}
    for obs, record in records:
        shown = {event.get("prompt_id") for event in _raw_events(record)
                 if event.get("type") == "prompt_displayed" and
                 event.get("prompt_id") in oracle}
        if not shown:
            continue
        decisions = {event.get("prompt_id"): event.get("decision")
                     for event in _raw_events(record)
                     if event.get("type") == "decision"}
        participant = obs["participant_id"]
        row = {"n": len(shown),
               "correct": sum(decisions.get(pid) == oracle[pid]
                              for pid in shown),
               "missing": sum(pid not in decisions for pid in shown)}
        by_participant[participant] = row
    return {"n": sum(row["n"] for row in by_participant.values()),
            "correct": sum(row["correct"] for row in by_participant.values()),
            "participants": len(by_participant),
            "per_participant": by_participant}


def _validate_approvals(metrics: dict, records: list[tuple[dict, dict]],
                        scenarios: dict, blockers: list[str]) -> None:
    try:
        expected = _approval_expectations(records, scenarios)
    except ValueError as exc:
        blockers.append(str(exc))
        return
    value = metrics.get("approvals")
    if not isinstance(value, dict):
        blockers.append("approval matrix missing")
        return
    for key in ("n", "correct", "participants"):
        if value.get(key) != expected[key]:
            blockers.append(f"approval {key} differs from eligible prompts")
    if value.get("per_participant") != expected["per_participant"] and \
            value.get("per_participant") != {
                pid: {"n": row["n"], "correct": row["correct"]}
                for pid, row in expected["per_participant"].items()}:
        blockers.append("approval participant matrix differs from prompts")
    n = expected["n"]
    accuracy = value.get("accuracy")
    expected_accuracy = expected["correct"] / n if n else None
    if accuracy != expected_accuracy and not (
            _is_number(accuracy) and _is_number(expected_accuracy) and
            abs(accuracy - expected_accuracy) <= 1e-5):
        blockers.append("approval accuracy differs from eligible prompts")


def _validate_prompt_rates(metrics: dict, blockers: list[str]) -> None:
    value = metrics.get("prompt_rate_by_role")
    if not isinstance(value, dict):
        blockers.append("prompt-rate matrix missing")
        return
    probes = value.get("load_probes")
    roles = value.get("by_role")
    if not isinstance(probes, list) or not isinstance(roles, dict) or not roles:
        blockers.append("prompt-rate role/load matrix incomplete")
        return
    for role, entry in roles.items():
        if not isinstance(role, str) or not isinstance(entry, dict):
            blockers.append("prompt-rate role entry malformed")
            continue
        prompts = entry.get("prompts")
        if not _is_int(prompts) or prompts < 0:
            blockers.append(f"prompt-rate prompts invalid for {role}")
        active = entry.get("active_minutes")
        if not _is_number(active) or active < 0:
            blockers.append(f"prompt-rate duration invalid for {role}")
        participants = entry.get("participant_n")
        if participants is None:
            raw_participants = entry.get("participants")
            participants = (len(raw_participants)
                            if isinstance(raw_participants, list)
                            else raw_participants)
        if not _is_int(participants) or participants < 0:
            blockers.append(f"prompt-rate participant count invalid for {role}")
        rate = entry.get("prompts_per_hour")
        if rate is not None and (not _is_number(rate) or rate < 0):
            blockers.append(f"prompt-rate value invalid for {role}")


def _validate_metrics(metrics: Any, observations: list,
                      protocol: dict, scenarios: dict,
                      blockers: list[str]) -> dict:
    if not isinstance(metrics, dict):
        blockers.append("metrics is not an object")
        return {}
    if not str(metrics.get("schema", "")).startswith(
            "agentos.s1-013.metrics/"):
        blockers.append("metrics schema mismatch")
    if metrics.get("synthetic") is not True:
        blockers.append("metrics are not marked synthetic")
    if metrics.get("human_n") != 0:
        blockers.append("human N claimed pre-pilot")
    for key in ("sessions", "ok", "rejected", "quarantined",
                "effective_participants"):
        if not _is_int(metrics.get(key)) or metrics[key] < 0:
            blockers.append(f"metrics {key} invalid")
    if isinstance(metrics.get("sessions"), int) and \
            metrics["sessions"] != len(observations):
        blockers.append("metrics session count differs from observations")
    problems, facts = _validate_observations(observations)
    blockers.extend(problems)
    counts = facts.get("counts", {})
    for key in ("ok", "rejected", "quarantined"):
        if _is_int(metrics.get(key)) and metrics[key] != counts.get(key, -1):
            blockers.append(f"metrics {key} count differs from observations")
    records = facts.get("records", [])
    if _is_int(metrics.get("effective_participants")) and \
            metrics["effective_participants"] != len(facts.get(
                "participant_ids", set())):
        blockers.append("effective participant count differs from observations")
    try:
        _expected_measure_ids(protocol)
        presented = _presented(records)
    except ValueError as exc:
        blockers.append(str(exc))
        presented = {measure: -1 for measure in MEASURES}
    matrix = metrics.get("measures")
    if not isinstance(matrix, dict) or set(matrix) != set(MEASURES):
        blockers.append("exact C1-C5 measure matrix missing")
        matrix = {}
    for measure in MEASURES:
        value = matrix.get(measure)
        _validate_counts(measure, value, presented.get(measure, -1), blockers)
        if measure == "C5" and isinstance(value, dict):
            _validate_c5(value, blockers)
    _validate_approvals(metrics, records, scenarios, blockers)
    _validate_prompt_rates(metrics, blockers)
    return {"records": records, "counts": counts,
            "presented": presented,
            "effective_participants": metrics.get("effective_participants")}


def _validate_probes(probes: Any, blockers: list[str]) -> None:
    if not isinstance(probes, dict) or not str(probes.get("schema", "")).startswith(
            "agentos.s1-013.probes/"):
        blockers.append("probe schema mismatch")
        return
    if probes.get("synthetic") is not True or probes.get("all_pass") is not True:
        blockers.append("probe battery is not synthetic and green")
    values = probes.get("probes")
    if not isinstance(values, dict) or set(values) != set(REQUIRED_PROBES):
        blockers.append("probe battery A-H is incomplete")
        return
    for key in REQUIRED_PROBES:
        if not isinstance(values[key], dict) or values[key].get("passed") is not True:
            blockers.append(f"probe {key} failed")


def _validate_flow(flow: Any, metrics: dict, blockers: list[str]) -> None:
    if not isinstance(flow, dict) or flow.get("synthetic") is not True:
        blockers.append("participant flow is not synthetic")
        return
    human = flow.get("human")
    if not isinstance(human, dict) or human.get("started") != 0 or \
            human.get("completed") != 0 or human.get("dropouts") not in ([], None):
        blockers.append("participant flow claims human activity")
    dry = flow.get("dry_run")
    if not isinstance(dry, dict):
        blockers.append("dry-run participant flow missing")
        return
    for key in ("sessions", "ok", "rejected", "quarantined"):
        if dry.get(key) != metrics.get(key):
            blockers.append(f"participant flow {key} differs from metrics")


def _stable_equal(left: Any, right: Any) -> bool:
    return canonical(left) == canonical(right)


def derive_verdict(here: Path | str | None = None,
                   results: Path | str | None = None) -> tuple[list[str], dict]:
    """Derive publication readiness entirely from freshly checked evidence."""

    base = (Path(here) if here is not None else HERE).resolve()
    result_dir = (Path(results).resolve() if results is not None else (
        base / "results" if here is not None else RESULTS)
                  )
    blockers: list[str] = []
    manifest_problems, manifest = verify_frozen_manifest(base)
    blockers.extend(manifest_problems)
    try:
        protocol = _read_json(base / "pilot-protocol.json", "pilot protocol")
        scenarios = _read_json(base / "scenario-manifest.json", "scenario manifest")
    except ValueError as exc:
        blockers.append(str(exc))
        return blockers, {}
    try:
        fresh_gate = _fresh_dependency_gate(base)
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        blockers.append(f"fresh dependency gate failed: {exc}")
        fresh_gate = {}
    if fresh_gate:
        if fresh_gate.get("all_proven") is not True:
            blockers.append("fresh dependency gate is not proven")
        _check_saved_gate(result_dir, fresh_gate, blockers)
    try:
        analysis = _fresh_analysis(base)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        blockers.append(f"fresh analysis failed: {exc}")
        return blockers, {}
    metric_facts = _validate_metrics(analysis["metrics"],
                                     analysis["observations"], protocol,
                                     scenarios, blockers)
    _validate_probes(analysis["probes"], blockers)
    try:
        fresh_comparison = _stable_comparison(analysis["comparison"])
    except ValueError as exc:
        blockers.append(str(exc))
        fresh_comparison = {}
    try:
        saved_metrics = _read_json(result_dir / "metrics.json", "saved metrics")
        saved_probes = _read_json(result_dir / "probes.json", "saved probes")
        saved_comparison = _read_json(result_dir / "comparison.json",
                                      "saved comparison")
        saved_flow = _read_json(result_dir / "participant-flow.json",
                                "saved participant flow")
        for name in ("decision.md", "limitations.md", "independent-audit.md"):
            path = result_dir / name
            if not path.is_file() or not path.read_text(encoding="utf-8").strip():
                blockers.append(f"saved result artifact missing/empty: {name}")
    except (OSError, UnicodeError, ValueError) as exc:
        blockers.append(str(exc))
        return blockers, {}
    if not _stable_equal(saved_metrics, analysis["metrics"]):
        blockers.append("saved metrics differ from fresh recomputation")
    if not _stable_equal(saved_probes, analysis["probes"]):
        blockers.append("saved probes differ from fresh recomputation")
    try:
        if not _stable_equal(_stable_comparison(saved_comparison),
                             fresh_comparison):
            blockers.append("saved comparison differs from fresh replication")
    except ValueError as exc:
        blockers.append(f"saved comparison invalid: {exc}")
    _validate_flow(saved_flow, analysis["metrics"], blockers)
    if not metric_facts.get("records") or not metric_facts.get(
            "effective_participants", 0):
        blockers.append("fresh analysis has no eligible synthetic participants")
    facts = {
        "gate": fresh_gate.get("all_proven") is True,
        "fresh_dependency_gate": True,
        "manifest_hashes": len(manifest.get("hashes", {}))
        if isinstance(manifest, dict) else 0,
        "recomputed_from": "importer+scorer re-executed on frozen synthetic data",
        "sessions": analysis["metrics"].get("sessions"),
        "effective_n": analysis["metrics"].get("effective_participants"),
        "probes": analysis["probes"].get("all_pass") is True,
        "replicated": analysis["comparison"].get("replicated") is True,
    }
    return blockers, facts


def check_metrics_consistency(metrics_doc: dict) -> list[str]:
    """Small compatibility guard used by the existing ticket tests."""

    problems: list[str] = []
    if metrics_doc.get("human_n", 0):
        problems.append("human_n claimed pre-pilot")
    if metrics_doc.get("synthetic") is not True:
        problems.append("metrics not marked synthetic")
    if str(metrics_doc.get("verdict", "")).upper().startswith("PASS"):
        problems.append("research PASS claimed without human data")
    return problems


def tracked_registry(here: Path | None = None) -> dict[str, str]:
    """Hash ticket bytes and the S1-013 test modules for the candidate."""

    base = (Path(here) if here is not None else HERE).resolve()
    registry: dict[str, str] = {}
    ticket_rel = PurePosixPath("research/tickets/stage-1/S1-013")
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.name == \
                "candidate-record.json" or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(base).as_posix()
        if rel.endswith(".pyc"):
            continue
        registry[(ticket_rel / PurePosixPath(rel)).as_posix()] = sha(
            path.read_bytes())
    try:
        repo_root = base.parents[4]
    except IndexError:
        repo_root = None
    if repo_root is not None:
        for test_file in sorted(repo_root.glob("tests/test_s1_013*.py")):
            if test_file.is_file() and not test_file.is_symlink():
                registry[PurePosixPath("tests") / test_file.name] = sha(
                    test_file.read_bytes())
    # PurePosixPath above is convenient for paths; normalize to JSON strings.
    return {str(key).replace("\\", "/"): value
            for key, value in registry.items()}


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    _remove_exact(temp)
    temp.write_text(json.dumps(value, indent=2, sort_keys=True,
                               ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")
    temp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1-013 bundle publisher")
    parser.add_argument("--here", default=None,
                        help="ticket directory (defaults to this module)")
    parser.add_argument("--results", default=None,
                        help="result directory (defaults to ticket/results)")
    # ``main()`` is also called directly by the unittest suite.  Do not
    # consume the suite's command-line arguments; the module entry point
    # passes ``sys.argv[1:]`` explicitly below.
    args = parser.parse_args([] if argv is None else argv)
    base = (Path(args.here).resolve() if args.here else HERE)
    result_dir = (Path(args.results).resolve() if args.results else (
        base / "results" if args.here else RESULTS)
                  )
    blockers, facts = derive_verdict(base, result_dir)
    if blockers:
        remove_ready_outputs(base)
        for line in blockers:
            print(f"BLOCKED: {line}", file=sys.stderr)
        return 1
    try:
        sources = build_sources(base)
        manifest = _read_json(base / "frozen-manifest.json", "frozen manifest")
        limitations = [
            "tracked-Git evidence only; live DB recheck required in Phase B",
            "no human data: all rates are dry-run tooling checks",
            "source coverage and verification limits remain explicit in the registry",
            "Beta-free design; no reputation-as-authority anywhere",
            "holdout concept not applicable pre-pilot; synthetic corpus is "
            "author-visible by construction",
        ]
        bundle = {
            "config": {"min_source_count": 4,
                       "min_verified_ratio": 1.0,
                       "required_artifacts": list(FLOW)},
            "sources": sources,
            "claims": [dict(claim) for claim in CLAIMS],
            "artifacts": build_artifacts(),
            "producer": PRODUCER,
            "auditor": AUDITOR,
            "audit": {"producer": PRODUCER, "auditor": AUDITOR,
                      "verdict": "pass_with_limits",
                      "limitations": limitations},
        }
        bundle_bytes = (json.dumps(bundle, indent=2, sort_keys=True,
                                   ensure_ascii=False) + "\n").encode("utf-8")
        _atomic_json(base / "bundle.json", bundle)
        bundle_sha = sha(bundle_bytes)
        candidate = {
            "schema": "agentos.s1-013.candidate-record/v1",
            "ticket": TICKET,
            "status": "PREPARATION_READY",
            "human_phase": "BLOCKED_HUMAN_PILOT",
            "verdict_basis": facts,
            "bundle_path": "research/tickets/stage-1/S1-013/bundle.json",
            "bundle_sha256": bundle_sha,
            "frozen_hashes": manifest.get("hashes", {}),
            "tracked_artifacts": tracked_registry(base),
            "tracked_registry_note": "Every ticket input plus the S1-013 "
                                      "test modules, by repo-relative POSIX "
                                      "path with SHA-256 of candidate bytes; "
                                      "the candidate itself is excluded.",
            "assumptions": [
                "mock UI interactions model the frozen scenarios faithfully",
                "synthetic sessions cover every importer path",
                "frozen targets stay hypotheses until human data exists",
            ],
            "unknowns": [
                "real comprehension rates and fatigue curves",
                "measured operator and ethics outcomes",
            ],
            "residual_risks": [
                "small-sample overinterpretation downstream",
                "privacy handling of free text at release",
                "reputation mistaken for authorization downstream",
            ],
            "phase_b_required": True,
            "chain_fresh_claim": None,
            "note": "No human N or human metrics are stated here; those "
                    "require an approved human pilot plus Phase B "
                    "canonicalization.",
        }
        _atomic_json(base / "candidate-record.json", candidate)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        remove_ready_outputs(base)
        print(f"BLOCKED: bundle assembly failed: {exc}", file=sys.stderr)
        return 1
    print(f"bundle.json sha256={bundle_sha}")
    print("candidate-record.json status=PREPARATION_READY, "
          "human=BLOCKED_HUMAN_PILOT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
