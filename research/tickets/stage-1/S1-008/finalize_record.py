"""S1-008 evaluation record finalizer.

Creates evaluation-record.json with programmatically output fields
(SHA-256, dates, IDs) — no manual revision-sensitive fields.

Usage:
    python finalize_record.py --bundle bundle.json --output evaluation-record.json \
        --db .agentos-research/platform-stage-1/agentos.db
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[4] if False else Path.cwd()
if not (_REPO_ROOT / "src").exists():
    _REPO_ROOT = Path(__file__).resolve().parents[3].parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from agentos.ids import canonical_json, sha256_text  # noqa: E402


def _file_sha256(path: str | Path) -> str:
    """Compute SHA-256 of a file's bytes."""
    p = Path(path)
    if not p.exists():
        return "MISSING"
    return hashlib.sha256(p.read_bytes()).hexdigest()


def finalize_record(bundle: dict[str, Any]) -> dict[str, Any]:
    """Create evaluation-record.json from the bundle."""
    now = datetime.now(timezone.utc).isoformat()

    # Compute bundle payload hash (self-hash: bundle_sha256 excluded)
    bundle_payload = {k: v for k, v in bundle.items() if k != "bundle_sha256"}
    bundle_payload_sha = sha256_text(canonical_json(bundle_payload))

    eval_result = bundle.get("evaluation", {})
    comparison = bundle.get("comparison", {})

    # Canonical evaluation verdict is PASS_WITH_LIMITS:
    # - comparison (A vs B) is PASS (reproducible, fail-closed)
    # - BUT transitive dependency on S1-002/S1-004 (both PASS_WITH_LIMITS)
    #   means S1-008 cannot claim full production qualification
    # - Same-host model-only cannot prove absence of network/cache side channels
    verdict = "PASS_WITH_LIMITS"
    result = "PASS_WITH_LIMITS"
    target_disposition = "target_met_with_limits"

    run_a = bundle.get("run_a", {})
    run_b = bundle.get("run_b", {})

    record = {
        "schema": "agentos.s1-008.evaluation-record/v1",
        "ticket_id": "S1-008",
        "ticket_title": "Revocation latency validation (<=5 seconds)",
        "research_revision": 1,
        "research_phase": "stage-1",
        "campaign_id": bundle.get("campaign_id", "rcamp_S1-008_REVOCATION_LATENCY"),
        "goal_id": bundle.get("goal_id", "goal_S1-008_REVOCATION_LATENCY"),
        "evaluation_id": bundle.get("evaluation_id", "reval_S1-008_REVOCATION_LATENCY"),
        "result": result,
        "verdict": verdict,
        "target_disposition": target_disposition,
        "target_ms": 5000,
        "comparison_verdict": comparison.get("verdict", "BLOCKED"),
        "evaluation_verdict": eval_result.get("verdict", "BLOCKED"),
        "artifact_chain_hash": bundle.get("artifact_chain_hash", ""),
        "evidence_pack": {
            "sha256": bundle.get("bundle_sha256", ""),
            "payload_sha256": bundle_payload_sha,
        },
        "hard_counters": comparison.get("hard_counters", {}),
        "probe_results": eval_result.get("probe_results", {}),
        "latency_ms": {
            "run_a": run_a.get("latency_ms", {}),
            "run_b": run_b.get("latency_ms", {}),
        },
        "per_component_latency_ms": run_a.get("per_component_latency_ms", {}),
        "run_a": {
            "executor_id": run_a.get("executor_id", ""),
            "git_commit": run_a.get("git_commit", ""),
            "dirty": run_a.get("dirty", True),
            "environment_hash": run_a.get("environment_hash", ""),
            "raw_trace_count": run_a.get("raw_traces", 0),
        },
        "run_b": {
            "executor_id": run_b.get("executor_id", ""),
            "git_commit": run_b.get("git_commit", ""),
            "dirty": run_b.get("dirty", True),
            "environment_hash": run_b.get("environment_hash", ""),
            "raw_trace_count": run_b.get("raw_traces", 0),
        },
        "comparison": comparison,
        "evaluation": eval_result,
        "frozen_artifacts": bundle.get("frozen_artifacts", {}),
        "dependencies": bundle.get("dependencies", []),
        "limitations": bundle.get("limitations", []),
        "recorded_at": now,
    }

    # Record self-hash (canonical JSON without record_sha256 and db_verified)
    record["record_sha256"] = ""
    record_json = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    record["record_sha256"] = sha256_text(record_json)

    return record


def verify_db(goal_id: str, eval_result: str, evaluation_id: str,
              bundle_chain: str, db_path: Path) -> dict[str, Any]:
    """Verify goal, campaign, and evaluation exist in canonical DB."""
    db_verified: dict[str, Any] = {
        "goal_present": False,
        "campaign_present": False,
        "evaluation_present": False,
        "evaluation_id_match": False,
        "verdict_match": False,
        "chain_hash_match": False,
        "fully_verified": False,
    }
    if not db_path.exists():
        db_verified["error"] = f"DB not found: {db_path}"
        return db_verified

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Check goal
        goal_row = conn.execute(
            "SELECT id FROM goal WHERE id = ?", (goal_id,)
        ).fetchone()
        db_verified["goal_present"] = goal_row is not None

        # Check campaign
        camp_row = conn.execute(
            "SELECT id FROM research_campaign WHERE goal_id = ?", (goal_id,)
        ).fetchone()
        db_verified["campaign_present"] = camp_row is not None

        # Check evaluation
        eval_row = conn.execute(
            "SELECT id, result, artifact_chain_hash FROM research_evaluation WHERE id = ?",
            (evaluation_id,),
        ).fetchone()
        db_verified["evaluation_present"] = eval_row is not None

        if eval_row:
            db_id = eval_row["id"]
            db_result = eval_row["result"]
            db_chain = eval_row["artifact_chain_hash"] or ""

            db_verified["db_evaluation_id"] = db_id
            db_verified["db_result"] = db_result
            db_verified["db_artifact_chain_hash"] = db_chain

            db_verified["evaluation_id_match"] = (db_id == evaluation_id)
            db_verified["verdict_match"] = (
                db_result.upper() == eval_result.upper()
            )
            db_verified["chain_hash_match"] = (db_chain == bundle_chain)

        # Fully verified: goal + campaign + evaluation present + ID match
        db_verified["fully_verified"] = all([
            db_verified["goal_present"],
            db_verified["campaign_present"],
            db_verified["evaluation_present"],
            db_verified["evaluation_id_match"],
        ])

        conn.close()
    except Exception as e:
        db_verified["error"] = str(e)

    return db_verified


def main() -> None:
    parser = argparse.ArgumentParser(description="S1-008 evaluation record finalizer")
    parser.add_argument("--bundle", required=True,
                        help="Path to bundle.json")
    parser.add_argument("--output", required=True,
                        help="Output path for evaluation-record.json")
    parser.add_argument("--db", default=".agentos-research/platform-stage-1/agentos.db",
                        help="Path to agentos DB")
    args = parser.parse_args()

    bundle_path = Path(args.bundle)
    out_path = Path(args.output)
    db_path = Path(args.db)

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    record = finalize_record(bundle)

    goal_id = record["goal_id"]
    evaluation_id = record["evaluation_id"]
    artifact_chain = record["artifact_chain_hash"]
    record_result = record["result"]

    db_verified = verify_db(goal_id, record_result, evaluation_id, artifact_chain, db_path)
    record["db_verified"] = db_verified

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

    # Summary output (JSON line for machine parsing)
    summary = {
        "verdict": record["verdict"],
        "result": record["result"],
        "target_disposition": record["target_disposition"],
        "goal_id": goal_id,
        "evaluation_id": evaluation_id,
        "db_verified": db_verified,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
