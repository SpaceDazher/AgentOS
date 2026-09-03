#!/usr/bin/env python3
"""Publish S1-009 tracked evidence packs and bind the exact latest DB rows.

The canonical SQLite database is the authority for revision/goal/evaluation
IDs.  This publisher never accepts IDs on the command line and never writes to
the database.  It creates two small content-addressed JSON wrappers: the
ticket evidence pack and a canonical DB-binding pack suitable for an archive
without the ignored runtime database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[3]
DEFAULT_DB_ROOT = REPO_ROOT / ".agentos-research" / "platform-stage-1"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def repo_relative(path: Path) -> str:
    return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")


def latest_db_rows(db_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    db_path = db_root / "agentos.db"
    if not db_path.is_file():
        raise RuntimeError(f"canonical database is missing: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        series = conn.execute(
            "SELECT * FROM research_series WHERE research_key=? "
            "ORDER BY revision DESC, id DESC LIMIT 1", ("S1-009",)
        ).fetchone()
        if series is None:
            raise RuntimeError("canonical database has no S1-009 research series")
        evaluation = conn.execute(
            "SELECT * FROM research_evaluation WHERE goal_id=? "
            "ORDER BY evaluation_version DESC, id DESC LIMIT 1",
            (series["goal_id"],),
        ).fetchone()
        if evaluation is None:
            raise RuntimeError("canonical database has no latest S1-009 evaluation")
        return dict(series), dict(evaluation)
    finally:
        conn.close()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def measurement_summary(name: str) -> dict[str, Any]:
    path = ROOT / "results" / name / "summary.json"
    summary = load_json(path)
    return {
        "executor_id": summary.get("executor_id"),
        "nonce": summary.get("nonce"),
        "output_root": summary.get("output_root"),
        "results_path": f"research/tickets/stage-1/S1-009/results/{name}/results.json",
        "verdict": summary.get("verdict"),
        "case_count": summary.get("case_count"),
        "verdict_counts": summary.get("verdict_counts"),
        "hashes": summary.get("hashes"),
        "input_manifest_sha256": summary.get("input_manifest_sha256"),
        "process_provenance": summary.get("process_provenance"),
        "invocation_digest": summary.get("invocation_digest"),
        "capability_rows_passing": summary.get("capability_rows_passing"),
    }


def source_snapshot_bindings() -> list[dict[str, Any]]:
    manifest = load_json(ROOT / "protocol-snapshot-manifest.json")
    result = []
    for source in manifest.get("sources", []):
        if not isinstance(source, dict):
            continue
        provenance = source.get("verifier_provenance", {})
        if "local" in str(source.get("source_type", "")).lower():
            rel = provenance.get("path", "")
            digest = provenance.get("file_sha256", "")
        else:
            rel = source.get("snapshot_path", "")
            digest = source.get("snapshot_sha256", "")
        path = (REPO_ROOT / Path(*str(rel).replace("\\", "/").split("/"))).resolve()
        result.append({
            "id": source.get("id"),
            "canonical_uri": source.get("canonical_uri"),
            "version": source.get("version"),
            "tag_commit_release": source.get("tag_commit_release"),
            "path": str(rel).replace("\\", "/"),
            "declared_sha256": digest,
            "file_sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        })
    return result


def tracked_artifacts() -> dict[str, str]:
    paths = [
        "cases.json", "evaluator.py", "runner.py", "adapter-contract.json",
        "canonical-envelope.schema.json", "rubric.json", "capability-matrix.json",
        "semantic-model.json", "corpus-manifest.json",
        "protocol-snapshot-manifest.json", "bundle.json",
        "make_bundle.py", "freeze_manifest.py",
        "S1-009-FU-01-delegation-grant-contract.md",
        "S1-009-FU-02-budget-conservation-contract.md",
        "results/run-a/results.json", "results/run-a/summary.json",
        "results/run-b/results.json", "results/run-b/summary.json",
        "results/comparison.json", "results/adapter-roadmap.md",
        "results/ENVIRONMENT.md", "results/probes.json", "results/version-skew.json",
        "tests/test_s1_009_regressions.py",
    ]
    result = {}
    for rel in paths:
        path = ROOT / rel if not rel.startswith("tests/") else REPO_ROOT / rel
        if path.is_file():
            result[repo_relative(path)] = sha256_file(path)
    return result


def build_payload(kind: str, series: dict[str, Any], evaluation: dict[str, Any],
                  runtime_pack: dict[str, Any], runtime_path: Path) -> dict[str, Any]:
    comparison = load_json(ROOT / "results" / "comparison.json")
    run_a = measurement_summary("run-a")
    run_b = measurement_summary("run-b")
    runtime_research = runtime_pack.get("research", {})
    return {
        "schema": "agentos.s1-009.evidence-payload/v1",
        "ticket_id": "S1-009",
        "pack_kind": kind,
        "record_binding": {
            "research_key": series["research_key"],
            "research_series_id": series["id"],
            "research_revision": series["revision"],
            "campaign_id": series["campaign_id"],
            "goal_id": series["goal_id"],
            "manifest_sha256": series["manifest_sha256"],
            "evaluation_id": evaluation["id"],
            "evaluation_version": evaluation["evaluation_version"],
            "result": evaluation["result"],
            "artifact_chain_hash": evaluation["artifact_chain_hash"],
        },
        "canonical_db_rows": {
            "research_series": series,
            "research_evaluation": evaluation,
        },
        "runtime_evidence_pack": {
            "path": repo_relative(runtime_path),
            "file_sha256": sha256_file(runtime_path),
            "payload_sha256": runtime_pack.get("payload_sha256", runtime_pack.get("sha256")),
            "schema": runtime_pack.get("schema"),
            "chain_fresh": runtime_research.get("chain_fresh"),
            "latest_evaluation_valid": runtime_research.get("latest_evaluation_valid"),
        },
        "measurement": {
            "run_a": run_a,
            "run_b": run_b,
            "comparison": comparison,
            "commit_sha": run_a.get("process_provenance", {}).get("commit_sha"),
            "tree_sha": run_a.get("process_provenance", {}).get("tree_sha"),
            "input_manifest_sha256": run_a.get("input_manifest_sha256"),
        },
        "source_snapshots": source_snapshot_bindings(),
        "tracked_artifacts": tracked_artifacts(),
    }


def write_pack(kind: str, payload: dict[str, Any]) -> dict[str, str]:
    payload_sha = sha256_bytes(canonical_bytes(payload))
    pack = {
        "schema": "agentos.s1-009.tracked-evidence-pack/v1",
        "ticket_id": "S1-009",
        "pack_kind": kind,
        "payload": payload,
        "payload_sha256": payload_sha,
        "pack_sha256": "",
    }
    pack["pack_sha256"] = sha256_bytes(canonical_bytes(pack))
    data = json.dumps(pack, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    file_sha = sha256_bytes(data)
    directory = ROOT / "tracked-packs" / kind
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{file_sha}.json"
    path.write_bytes(data)
    return {
        "path": repo_relative(path),
        "file_sha256": file_sha,
        "payload_sha256": payload_sha,
        "pack_sha256": pack["pack_sha256"],
    }


def build_record(series: dict[str, Any], evaluation: dict[str, Any],
                 runtime_pack: dict[str, Any], runtime_path: Path,
                 ticket_pack: dict[str, str], canonical_pack: dict[str, str]) -> dict[str, Any]:
    old_path = ROOT / "evaluation-record.json"
    old = load_json(old_path) if old_path.is_file() else {}
    comparison = load_json(ROOT / "results" / "comparison.json")
    run_a = measurement_summary("run-a")
    run_b = measurement_summary("run-b")
    limitations = json.loads(evaluation.get("limitations_json", "[]"))
    runtime_research = runtime_pack.get("research", {})
    record = dict(old)
    record.update({
        "schema": "agentos.ticket-evaluation-record/v2",
        "ticket_id": "S1-009",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "db_root": ".agentos-research/platform-stage-1",
        "research_key": series["research_key"],
        "research_revision": series["revision"],
        "research_series_id": series["id"],
        "campaign_id": series["campaign_id"],
        "goal_id": series["goal_id"],
        "evaluation_id": evaluation["id"],
        "evaluation_version": evaluation["evaluation_version"],
        "result": evaluation["result"],
        "artifact_chain_hash": evaluation["artifact_chain_hash"],
        "manifest_sha256": series["manifest_sha256"],
        "supersedes_campaign_id": series.get("supersedes_campaign_id"),
        "limitations": limitations,
        "research_revision_source": "canonical DB research_series.revision",
        "canonical_db_binding": {
            "research_series": series,
            "research_evaluation": evaluation,
        },
        "evidence_pack": {
            "schema": runtime_pack.get("schema"),
            "path": repo_relative(runtime_path),
            "sha256": runtime_pack.get("sha256"),
            "file_sha256": sha256_file(runtime_path),
            "payload_sha256": runtime_pack.get("payload_sha256", runtime_pack.get("sha256")),
            "chain_fresh": runtime_research.get("chain_fresh"),
            "latest_evaluation_valid": runtime_research.get("latest_evaluation_valid"),
        },
        "tracked_ticket_pack": ticket_pack,
        "tracked_canonical_pack": canonical_pack,
        "evaluation_artifacts": {
            "run_a": run_a,
            "run_b": run_b,
            "comparison": comparison,
        },
        "source_snapshots": source_snapshot_bindings(),
        "tracked_artifact_hashes": tracked_artifacts(),
        "measurement_provenance": {
            "commit_sha": run_a["process_provenance"]["commit_sha"],
            "tree_sha": run_a["process_provenance"]["tree_sha"],
            "input_manifest_sha256": run_a["input_manifest_sha256"],
            "clean": run_a["process_provenance"]["clean"] and run_b["process_provenance"]["clean"],
            "process_separation_verified": comparison.get("process_separation_verified", False),
        },
        "archive_reproducibility": {
            "required_paths": [ticket_pack["path"], canonical_pack["path"]],
            "verification_command": "git archive HEAD -> clean temporary directory; verify both content-addressed paths",
            "verified": False,
        },
        "decision": {
            "question": "Which delegation/ownership/budget/provenance/knowledge-promotion semantics are absent or insufficiently normative in current MCP/A2A surfaces, and what versioned adapter contract preserves canonical AgentOS hub envelope provider-neutral without changing authorization meaning?",
            "answer": "Three semantics are ABSENT/UNDERSPECIFIED in both MCP 2026-07-28 and A2A 1.0.0: exact-action delegation grants and child scope (SM6), budget reservation/consumption/aggregation (SM8), and knowledge promotion/challenge/rejection/revocation (SM11). The remaining 12 of 15 capability rows have explicit lossless or lossy-safe mappings. The adapter preserves the provider-neutral hub boundary by enforcing eight hard rules.",
            "verdict": evaluation["result"],
            "research_revision": series["revision"],
            "limits": limitations,
        },
        "note": "All revision IDs, evaluation IDs, chain hashes, and manifest hashes are extracted from the exact latest canonical SQLite rows; tracked packs bind those rows and the clean process-separated measurement.",
    })
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish S1-009 tracked evidence packs")
    parser.add_argument("--db", default=str(DEFAULT_DB_ROOT), help="canonical DB root")
    args = parser.parse_args()
    db_root = Path(args.db).resolve()
    series, evaluation = latest_db_rows(db_root)
    runtime_path = db_root / "goals" / series["goal_id"] / "evidence-pack.json"
    if not runtime_path.is_file():
        raise RuntimeError(f"canonical runtime evidence pack is missing: {runtime_path}")
    runtime_pack = load_json(runtime_path)
    ticket_payload = build_payload("ticket", series, evaluation, runtime_pack, runtime_path)
    canonical_payload = build_payload("canonical", series, evaluation, runtime_pack, runtime_path)
    ticket_pack = write_pack("ticket", ticket_payload)
    canonical_pack = write_pack("canonical", canonical_payload)
    record = build_record(series, evaluation, runtime_pack, runtime_path,
                          ticket_pack, canonical_pack)
    (ROOT / "evaluation-record.json").write_bytes(
        (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        .encode("utf-8")
    )
    print(json.dumps({
        "research_series_id": series["id"],
        "revision": series["revision"],
        "goal_id": series["goal_id"],
        "evaluation_id": evaluation["id"],
        "artifact_chain_hash": evaluation["artifact_chain_hash"],
        "tracked_ticket_pack": ticket_pack,
        "tracked_canonical_pack": canonical_pack,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
