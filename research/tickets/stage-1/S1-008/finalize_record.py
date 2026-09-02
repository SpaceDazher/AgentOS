"""Fail-closed S1-008 evaluation-record finalizer.

The finalizer is intentionally the last gate: it derives the public outcome
from evaluator/comparison state, verifies exact DB ownership, validates the
content-addressed pack and both raw archives, then writes a record whose
self-hash covers the DB verification result and exact pack binding.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
if not (_REPO_ROOT / "src").exists():
    _REPO_ROOT = Path.cwd()
sys.path.insert(0, str(_REPO_ROOT / "src"))

from agentos.ids import canonical_json, sha256_text  # noqa: E402


class FinalizationError(ValueError):
    """Raised whenever immutable evidence is missing, stale, or inconsistent."""


def _file_sha256(path: str | Path) -> str:
    path_obj = Path(path)
    if not path_obj.is_file():
        raise FinalizationError(f"file not found: {path_obj}")
    return hashlib.sha256(path_obj.read_bytes()).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value.lower())


def _status(value: Any) -> str:
    if not isinstance(value, str):
        raise FinalizationError("verdict/result must be a string")
    normalized = value.strip().upper()
    if normalized not in {"PASS", "PASS_WITH_LIMITS", "FAIL", "BLOCKED"}:
        raise FinalizationError(f"unknown evaluator status: {value!r}")
    return normalized


def derive_outcome(bundle: dict[str, Any]) -> dict[str, str]:
    """Derive the only publishable outcome from evaluator and comparison.

    FAIL, BLOCKED, missing, malformed, or unknown input is never upgraded to a
    positive final record. PASS and PASS_WITH_LIMITS are deliberately capped at
    PASS_WITH_LIMITS because S1-008 is a same-host model-only measurement.
    """
    if not isinstance(bundle, dict):
        raise FinalizationError("bundle must be an object")
    evaluation = bundle.get("evaluation")
    comparison = bundle.get("comparison")
    if not isinstance(evaluation, dict) or not isinstance(comparison, dict):
        raise FinalizationError("evaluation and comparison objects are required")
    evaluation_status = _status(evaluation.get("verdict"))
    comparison_status = _status(comparison.get("verdict"))
    if evaluation_status in {"FAIL", "BLOCKED"}:
        raise FinalizationError(f"evaluation is not publishable: {evaluation_status}")
    if comparison_status in {"FAIL", "BLOCKED"}:
        raise FinalizationError(f"comparison is not publishable: {comparison_status}")
    for label, value in (("evaluation", evaluation), ("comparison", comparison)):
        if "failures" not in value or "warnings" not in value:
            raise FinalizationError(f"{label} is missing failure/warning state")
        failures = value.get("failures")
        if not isinstance(failures, list):
            raise FinalizationError(f"{label}.failures must be a list")
        if failures:
            raise FinalizationError(f"{label} contains failures")
        warnings = value.get("warnings")
        if not isinstance(warnings, list):
            raise FinalizationError(f"{label}.warnings must be a list")
        if "result" in value and _status(value["result"]) != _status(value["verdict"]):
            raise FinalizationError(f"{label} result/verdict mismatch")
    return {
        "result": "PASS_WITH_LIMITS",
        "verdict": "PASS_WITH_LIMITS",
        "target_disposition": "target_met_with_limits",
        "evaluation_verdict": evaluation_status,
        "comparison_verdict": comparison_status,
    }


def _resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _REPO_ROOT / path


def _trace_set_digest(members: list[dict[str, Any]]) -> str:
    normalized = [
        {key: member[key] for key in ("path", "size", "sha256", "canonical_sha256")}
        for member in members
    ]
    return sha256_text(canonical_json({
        "algorithm": "sha256(path,size,bytes,canonical-json)",
        "members": normalized,
    }))


def _verify_archive(path: str | Path, expected: dict[str, Any]) -> dict[str, Any]:
    """Verify an embedded raw archive and return its exact metadata."""
    archive_path = _resolve_repo_path(path)
    if not archive_path.is_file():
        raise FinalizationError(f"raw archive not found: {archive_path}")
    file_sha = _file_sha256(archive_path)
    try:
        payload = json.loads(archive_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FinalizationError(f"invalid raw archive: {archive_path}") from exc
    run_label = payload.get("run_label")
    if archive_path.stem != f"raw-observations-{run_label}-{file_sha}":
        raise FinalizationError(f"raw archive filename is not content-addressed: {archive_path.name}")
    members = payload.get("members")
    if not isinstance(members, dict) or payload.get("member_count") != len(members):
        raise FinalizationError("raw archive member count mismatch")
    normalized: list[dict[str, Any]] = []
    for member_path, member in sorted(members.items()):
        if not isinstance(member, dict) or member.get("path") != member_path:
            raise FinalizationError(f"raw archive path mismatch: {member_path}")
        try:
            raw = base64.b64decode(member["content_base64"], validate=True)
        except Exception as exc:
            raise FinalizationError(f"raw archive bytes invalid: {member_path}") from exc
        if member.get("size") != len(raw) or member.get("sha256") != hashlib.sha256(raw).hexdigest():
            raise FinalizationError(f"raw archive byte digest mismatch: {member_path}")
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FinalizationError(f"raw archive JSON invalid: {member_path}") from exc
        canonical = canonical_json(parsed).encode("utf-8")
        if member.get("canonical_sha256") != hashlib.sha256(canonical).hexdigest():
            raise FinalizationError(f"raw archive canonical digest mismatch: {member_path}")
        normalized.append({key: member[key] for key in ("path", "size", "sha256", "canonical_sha256")})
    trace_sha = _trace_set_digest(normalized)
    if payload.get("trace_set_sha256") != trace_sha:
        raise FinalizationError("raw archive trace-set digest mismatch")
    metadata = {
        "path": archive_path.resolve().as_posix(),
        "sha256": file_sha,
        "trace_set_sha256": trace_sha,
        "member_count": len(members),
        "member_digests": normalized,
        "run_label": run_label,
    }
    for key in ("sha256", "trace_set_sha256", "member_count"):
        if expected.get(key) != metadata[key]:
            raise FinalizationError(f"raw archive {key} does not match pack")
    return metadata


def _load_and_verify_pack(bundle: dict[str, Any], evidence_pack_path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    pack_path = _resolve_repo_path(evidence_pack_path)
    if not pack_path.is_file():
        raise FinalizationError(f"evidence pack not found: {pack_path}")
    file_sha = _file_sha256(pack_path)
    try:
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FinalizationError("evidence pack is not valid JSON") from exc
    if pack_path.stem != f"evidence-pack-{file_sha}":
        raise FinalizationError("evidence pack filename does not match file SHA-256")
    if pack.get("pack_sha256") != sha256_text(canonical_json({**pack, "pack_sha256": ""})):
        raise FinalizationError("evidence pack self-hash mismatch")
    bundle_hash = bundle.get("bundle_sha256")
    if not _valid_sha(bundle_hash):
        raise FinalizationError("bundle self-hash is missing or malformed")
    if bundle_hash != sha256_text(canonical_json({**bundle, "bundle_sha256": ""})):
        raise FinalizationError("bundle self-hash mismatch")
    expected_payload_hash = sha256_text(canonical_json({
        key: value for key, value in bundle.items() if key != "bundle_sha256"
    }))
    if pack.get("bundle_sha256") != bundle_hash:
        raise FinalizationError("evidence pack bundle self-hash binding mismatch")
    if pack.get("bundle_payload_sha256") != expected_payload_hash:
        raise FinalizationError("evidence pack bundle payload binding mismatch")
    if pack.get("evidence_binding") != bundle.get("evidence_binding"):
        raise FinalizationError("evidence pack evidence binding mismatch")
    bundle_binding = bundle.get("bundle_binding")
    if not isinstance(bundle_binding, dict) or not _valid_sha(bundle_binding.get("sha256")):
        raise FinalizationError("bundle immutable binding missing")
    if (pack.get("bundle_binding") != bundle_binding or
            sha256_text(canonical_json({
                key: value for key, value in bundle_binding.items()
                if key != "sha256"
            })) != bundle_binding["sha256"] or
            bundle_binding.get("evidence_binding_sha256") != bundle.get(
                "evidence_binding", {}).get("sha256")):
        raise FinalizationError("evidence pack immutable bundle binding mismatch")
    for key in ("goal_id", "campaign_id", "evaluation_id", "artifact_chain_hash"):
        if not isinstance(bundle.get(key), str) or not bundle[key]:
            raise FinalizationError(f"bundle missing {key}")
        if pack.get(key) != bundle[key]:
            raise FinalizationError(f"evidence pack {key} mismatch")
    outcome = derive_outcome(bundle)
    if pack.get("verdict") != outcome["verdict"]:
        raise FinalizationError("evidence pack verdict mismatch")
    if _status(pack.get("result")) != outcome["result"]:
        raise FinalizationError("evidence pack result mismatch")
    if _status(pack.get("comparison_verdict")) != outcome["comparison_verdict"]:
        raise FinalizationError("evidence pack comparison verdict mismatch")
    pack_evaluation = pack.get("evaluation")
    pack_comparison = pack.get("comparison")
    if not isinstance(pack_evaluation, dict) or not isinstance(pack_comparison, dict):
        raise FinalizationError("evidence pack evaluation/comparison missing")
    if _status(pack_evaluation.get("verdict")) != outcome["evaluation_verdict"]:
        raise FinalizationError("pack evaluation verdict mismatch")
    if _status(pack_comparison.get("verdict")) != outcome["comparison_verdict"]:
        raise FinalizationError("pack comparison verdict mismatch")
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, dict):
        raise FinalizationError("bundle artifacts missing")
    archives = pack.get("raw_archives")
    if not isinstance(archives, dict):
        archives = {"a": pack.get("raw_archive_a"), "b": pack.get("raw_archive_b")}
    archive_info: dict[str, Any] = {}
    for label in ("a", "b"):
        archive = archives.get(label)
        expected = artifacts.get("raw_a" if label == "a" else "raw_b")
        if not isinstance(archive, dict) or not isinstance(expected, dict):
            raise FinalizationError(f"raw archive {label.upper()} binding missing")
        if archive.get("run_label") != f"run-{label}":
            raise FinalizationError(f"raw archive {label.upper()} label mismatch")
        actual = _verify_archive(archive.get("path", ""), archive)
        if actual["trace_set_sha256"] != expected.get("sha256"):
            raise FinalizationError(f"raw archive {label.upper()} is not bound to bundle traces")
        if expected.get("member_count") != actual["member_count"]:
            raise FinalizationError(f"raw archive {label.upper()} member count mismatch")
        expected_members = expected.get("members")
        if isinstance(expected_members, list) and expected_members != actual["member_digests"]:
            raise FinalizationError(f"raw archive {label.upper()} member list mismatch")
        archive_info[label] = actual
    return pack, {
        "path": pack_path.resolve().as_posix(),
        "sha256": file_sha,
        "pack_sha256": pack["pack_sha256"],
        "raw_archives": archive_info,
    }


def _require_identity(bundle: dict[str, Any]) -> None:
    for key in ("goal_id", "campaign_id", "evaluation_id", "artifact_chain_hash"):
        value = bundle.get(key)
        if not isinstance(value, str) or not value.strip():
            raise FinalizationError(f"missing immutable identity: {key}")
    id_patterns = {
        "goal_id": r"^goal_[A-Z0-9]{26}$",
        "campaign_id": r"^rcamp_[A-Z0-9]{26}$",
        "evaluation_id": r"^reval_[A-Z0-9]{26}$",
    }
    for key, pattern in id_patterns.items():
        if not re.fullmatch(pattern, bundle[key]):
            raise FinalizationError(f"malformed immutable identity: {key}")
    if not _valid_sha(bundle["artifact_chain_hash"]):
        raise FinalizationError("malformed artifact_chain_hash")
    if re.search(r"(?:s1-008_revocation_latency|default|unknown)",
                 " ".join(str(bundle[key]) for key in ("goal_id", "campaign_id", "evaluation_id")).lower()):
        raise FinalizationError("fabricated/default identity is not publishable")


def _validate_run_provenance(run_a: dict[str, Any], run_b: dict[str, Any]) -> None:
    """Require independently observed process evidence in both run summaries."""
    process_a = run_a.get("process_evidence")
    process_b = run_b.get("process_evidence")
    if not isinstance(process_a, dict) or not isinstance(process_b, dict):
        raise FinalizationError("run A/B process evidence is required")
    for label, process in (("A", process_a), ("B", process_b)):
        pid = process.get("pid")
        parent_pid = process.get("parent_pid")
        argv = process.get("argv")
        digest = process.get("invocation_digest")
        if (isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0 or
                isinstance(parent_pid, bool) or not isinstance(parent_pid, int) or parent_pid <= 0 or
                not isinstance(argv, list) or not argv or
                not all(isinstance(item, str) and item for item in argv) or
                not _valid_sha(digest)):
            raise FinalizationError(f"run {label} process evidence is malformed")
        if sha256_text(canonical_json({
            key: value for key, value in process.items() if key != "invocation_digest"
        })) != digest:
            raise FinalizationError(f"run {label} invocation digest mismatch")
        descriptor = process.get("launch_descriptor")
        if (not isinstance(descriptor, dict) or descriptor.get("argv") != argv or
                descriptor.get("cwd") != process.get("cwd") or
                descriptor.get("executable") != process.get("executable") or
                descriptor.get("output_dir") != process.get("output_dir")):
            raise FinalizationError(f"run {label} launch descriptor mismatch")
    if process_a["pid"] == process_b["pid"]:
        raise FinalizationError("run A/B must have different process IDs")
    if process_a["invocation_digest"] == process_b["invocation_digest"]:
        raise FinalizationError("run A/B must have different invocation digests")


def finalize_record(bundle: dict[str, Any], *, evidence_pack_path: str | Path | None = None,
                    db_verified: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a validated record; no positive record is returned for bad input."""
    _require_identity(bundle)
    outcome = derive_outcome(bundle)
    if evidence_pack_path is None:
        raise FinalizationError("exact evidence_pack_path is required")
    _pack, pack_info = _load_and_verify_pack(bundle, evidence_pack_path)
    run_a = bundle.get("run_a")
    run_b = bundle.get("run_b")
    if not isinstance(run_a, dict) or not isinstance(run_b, dict):
        raise FinalizationError("run A/B summaries are required")
    if run_a.get("dirty") is not False or run_b.get("dirty") is not False:
        raise FinalizationError("run A/B must both be clean")
    _validate_run_provenance(run_a, run_b)
    if not isinstance(db_verified, dict) or db_verified.get("fully_verified") is not True:
        raise FinalizationError("fully verified DB binding is required")
    record: dict[str, Any] = {
        "schema": "agentos.s1-008.evaluation-record/v2",
        "ticket_id": "S1-008",
        "ticket_title": "Revocation latency validation (<=5 seconds)",
        "research_revision": bundle.get("research_revision", 2),
        "research_phase": "stage-1",
        "campaign_id": bundle["campaign_id"],
        "goal_id": bundle["goal_id"],
        "evaluation_id": bundle["evaluation_id"],
        "result": outcome["result"],
        "verdict": outcome["verdict"],
        "target_disposition": outcome["target_disposition"],
        "target_ms": 5000,
        "comparison_verdict": outcome["comparison_verdict"],
        "evaluation_verdict": outcome["evaluation_verdict"],
        "artifact_chain_hash": bundle["artifact_chain_hash"],
        "evidence_binding": bundle.get("evidence_binding"),
        "bundle_binding": bundle.get("bundle_binding"),
        "evidence_pack": {
            "path": pack_info["path"],
            "sha256": pack_info["sha256"],
            "pack_sha256": pack_info["pack_sha256"],
            "raw_archives": pack_info["raw_archives"],
        },
        "hard_counters": bundle["comparison"].get("hard_counters", {}),
        "probe_results": bundle["evaluation"].get("probe_results", {}),
        "latency_ms": {"run_a": run_a.get("latency_ms", {}), "run_b": run_b.get("latency_ms", {})},
        "per_component_latency_ms": run_a.get("per_component_latency_ms", {}),
        "run_a": run_a,
        "run_b": run_b,
        "comparison": bundle["comparison"],
        "evaluation": bundle["evaluation"],
        "frozen_artifacts": bundle.get("frozen_artifacts", {}),
        "dependencies": bundle.get("dependencies", []),
        "limitations": bundle.get("limitations", []),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "db_verified": db_verified or {},
    }
    record["record_sha256"] = ""
    record["record_sha256"] = sha256_text(canonical_json(record))
    return record


def verify_db(goal_id: str, campaign_id: str, evaluation_id: str,
              eval_result: str, bundle_chain: str, db_path: Path,
              *, expected_verdict: str | None = None) -> dict[str, Any]:
    """Verify exact goal/campaign/evaluation ownership and immutable values."""
    keys = {
        "goal_present": False,
        "campaign_present": False,
        "evaluation_present": False,
        "evaluation_id_match": False,
        "campaign_id_match": False,
        "evaluation_campaign_match": False,
        "goal_id_match": False,
        "campaign_goal_match": False,
        "verdict_match": False,
        "result_match": False,
        "chain_hash_match": False,
        "fully_verified": False,
    }
    if not all(isinstance(value, str) and value.strip() for value in
               (goal_id, campaign_id, evaluation_id, eval_result, bundle_chain)):
        keys["error"] = "all exact DB identity/value arguments are required"
        return keys
    db = Path(db_path)
    if not db.is_file():
        keys["error"] = f"DB not found: {db}"
        return keys
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        goal = conn.execute("SELECT id FROM goal WHERE id=?", (goal_id,)).fetchone()
        campaign = conn.execute(
            "SELECT id, goal_id FROM research_campaign WHERE id=?", (campaign_id,)
        ).fetchone()
        evaluation = conn.execute(
            "SELECT id, campaign_id, goal_id, result, artifact_chain_hash "
            "FROM research_evaluation WHERE id=?", (evaluation_id,)
        ).fetchone()
        keys["goal_present"] = goal is not None
        keys["campaign_present"] = campaign is not None
        keys["evaluation_present"] = evaluation is not None
        if campaign is not None:
            keys["campaign_id_match"] = campaign["id"] == campaign_id
            keys["campaign_goal_match"] = campaign["goal_id"] == goal_id
            keys["campaign_db_goal_id"] = campaign["goal_id"]
        if evaluation is not None:
            keys["evaluation_id_match"] = evaluation["id"] == evaluation_id
            keys["goal_id_match"] = evaluation["goal_id"] == goal_id
            keys["evaluation_campaign_id"] = evaluation["campaign_id"]
            keys["evaluation_db_goal_id"] = evaluation["goal_id"]
            keys["evaluation_campaign_match"] = evaluation["campaign_id"] == campaign_id
            keys["db_result"] = evaluation["result"]
            keys["db_artifact_chain_hash"] = evaluation["artifact_chain_hash"] or ""
            keys["result_match"] = str(evaluation["result"]).strip().upper() == eval_result.strip().upper()
            keys["verdict_match"] = keys["result_match"]
            keys["chain_hash_match"] = evaluation["artifact_chain_hash"] == bundle_chain
        if expected_verdict is not None:
            keys["expected_verdict_match"] = (
                evaluation is not None and
                str(evaluation["result"]).strip().upper() == expected_verdict.strip().upper())
        keys["fully_verified"] = all(keys[key] for key in (
            "goal_present", "campaign_present", "evaluation_present",
            "evaluation_id_match", "campaign_id_match", "goal_id_match",
            "campaign_goal_match", "evaluation_campaign_match", "result_match", "verdict_match",
            "chain_hash_match",
        )) and (expected_verdict is None or keys.get("expected_verdict_match", False))
    except (OSError, sqlite3.Error) as exc:
        keys["error"] = str(exc)
    finally:
        if conn is not None:
            conn.close()
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description="S1-008 evaluation record finalizer")
    parser.add_argument("--bundle", required=True, help="Path to bundle.json")
    parser.add_argument("--output", required=True, help="Path to evaluation-record.json")
    parser.add_argument("--db", default=".agentos-research/platform-stage-1/agentos.db", help="Path to agentos DB")
    parser.add_argument("--evidence-pack", required=True, help="Exact content-addressed evidence-pack path")
    args = parser.parse_args()
    try:
        bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
        outcome = derive_outcome(bundle)
        db_verified = verify_db(
            bundle["goal_id"], bundle["campaign_id"], bundle["evaluation_id"],
            outcome["result"], bundle["artifact_chain_hash"], Path(args.db),
            expected_verdict=outcome["result"],
        )
        if not db_verified.get("fully_verified"):
            raise FinalizationError(f"canonical DB verification failed: {db_verified}")
        record = finalize_record(bundle, evidence_pack_path=args.evidence_pack,
                                 db_verified=db_verified)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "result": record["result"],
        "verdict": record["verdict"],
        "target_disposition": record["target_disposition"],
        "goal_id": record["goal_id"],
        "campaign_id": record["campaign_id"],
        "evaluation_id": record["evaluation_id"],
        "evidence_pack": record["evidence_pack"],
        "db_verified": record["db_verified"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
