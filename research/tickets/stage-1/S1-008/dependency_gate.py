"""Preflight dependency gate for S1-008.

Verifies S1-002 and S1-004 evidence is proven before S1-008 begins:
  1. Reads evaluation-record.json for each dependency.
  2. Reads the tracked content-addressed evidence pack referenced by record.
  3. Recomputes file SHA-256 and payload SHA-256.
  4. Verifies goal/campaign/evaluation IDs, artifact-chain hash, chain_fresh,
     latest_evaluation_valid against canonical DB.
  5. Cross-checks verdict/revision with docs/RESEARCH_STAGE_1_TICKETS.md.

This is deterministic and stdlib-only. Run from repo root with PYTHONPATH=src.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[4]  # repo root (agentos)
DB_ROOT = REPO / ".agentos-research" / "platform-stage-1"
TICKETS = REPO / "research" / "tickets" / "stage-1"
STATUS_DOC = REPO / "docs" / "RESEARCH_STAGE_1_TICKETS.md"

_HEX64 = re.compile(r"\A[0-9a-fA-F]{64}\Z")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


REQUIRED_HEX = {
    "S1-002": {
        "sha256": "13a8abc70ea5e4b5445afb5365ecc65b8920c3f4691da024a905682ddcbcabab",
        "payload_sha256": "f1ddd32110a431b277e06aea74e2b71baa273e451d1c86369e781a0a09893fa4",
        "goal_id": "goal_8CTE14C6Q2E1TV8801M0TEN900",
        "campaign_id": "rcamp_F228J0RKQQ2HN8WG01M0TEN900",
        "evaluation_id": "reval_N96W6BG39C3TPZZT01M0TEN90T",
        "artifact_chain_hash": "c03fe8871048343043ce9823c7707ef82627f173f2327c903b3dacce2882b7c4",
        "result": "pass_with_limits",
        "revision": 1,
    },
    "S1-004": {
        "sha256": "98f6b998909983706ea993e6877b56b003bb64f5228a50559bdb4e01feb98841",
        "payload_sha256": "7de667d53c46c369c44d62ce5f275ccd18634bf0c15da2b3d45aed0209d6da8a",
        "goal_id": "goal_Z9TP87YGTAMDPD9801M18BSRXE",
        "campaign_id": "rcamp_K1J4R00ZDQG76Y7J01M18BSRXE",
        "evaluation_id": "reval_5JJ8C83TCA8CNQ5Q01M18BSRZX",
        "artifact_chain_hash": "ce1fcfd5e17cec41ae8c23233b276b709f6da5f978da0ad11a0cdb07f2f1d349",
        "result": "pass_with_limits",
        "revision": 7,
    },
}


def _db_chain_hash(db: sqlite3.Connection, goal_id: str) -> str | None:
    """Recompute the canonical research chain hash from the DB (host file state)."""
    campaign = db.execute(
        "SELECT id, goal_id, topic, config_json, thresholds_json, manifest_sha256"
        " FROM research_campaign WHERE goal_id=?", (goal_id,)).fetchone()
    if not campaign:
        return None
    sources = [dict(r) for r in db.execute(
        "SELECT id, goal_id, canonical_uri, title, source_type, content_sha256,"
        " verification_status, verifier, verification_method, verifier_provenance_json"
        " FROM research_source WHERE goal_id=? ORDER BY id", (goal_id,))]
    claims = [dict(r) for r in db.execute(
        "SELECT id, goal_id, text, claim_class FROM research_claim WHERE goal_id=? ORDER BY id",
        (goal_id,))]
    links = [dict(r) for r in db.execute(
        "SELECT claim_id, source_id, goal_id, relation FROM research_claim_source"
        " WHERE goal_id=? ORDER BY claim_id, source_id", (goal_id,))]
    artifacts = [dict(r) for r in db.execute(
        "SELECT id, goal_id, kind, artifact_name, version, content_sha256,"
        " storage_path, claim_refs_json, producer FROM research_artifact"
        " WHERE goal_id=? ORDER BY kind, version, id", (goal_id,))]
    for artifact in artifacts:
        path = Path(artifact["storage_path"])
        try:
            exists = path.is_file()
            actual_sha = _sha256_file(path) if exists else None
        except OSError:
            exists = False
            actual_sha = None
        artifact["host_file_exists"] = exists
        artifact["host_file_sha256"] = actual_sha
    artifact_claims = [dict(r) for r in db.execute(
        "SELECT artifact_id, claim_id, goal_id FROM research_artifact_claim"
        " WHERE goal_id=? ORDER BY artifact_id, claim_id", (goal_id,))]
    payload = {
        "campaign": dict(campaign),
        "sources": sources,
        "claims": claims,
        "claim_sources": links,
        "artifacts": artifacts,
        "artifact_claims": artifact_claims,
    }
    return _sha256_text(_canonical_json(payload))


def check_ticket(ticket_id: str, expected: dict[str, Any]) -> dict[str, Any]:
    record_path = TICKETS / ticket_id / "evaluation-record.json"
    errors: list[str] = []
    info: dict[str, Any] = {"ticket_id": ticket_id}

    # 1. Load evaluation-record.json
    if not record_path.is_file():
        return {"ticket_id": ticket_id, "ok": False,
                "errors": [f"evaluation-record.json missing at {record_path}"]}
    record = _load_json(record_path)
    info["recorded_at"] = record.get("recorded_at")
    info["recorded_result"] = record.get("result")

    # 2. Load the referenced evidence pack
    pack_meta = record.get("evidence_pack", {})
    pack_rel = pack_meta.get("path")
    if not pack_rel:
        errors.append("evidence_pack.path missing in record")
        return {"ticket_id": ticket_id, "ok": False, "errors": errors, "info": info}
    pack_path = REPO / pack_rel
    if not pack_path.is_file():
        errors.append(f"evidence pack file missing: {pack_path}")
        return {"ticket_id": ticket_id, "ok": False, "errors": errors, "info": info}

    # 3. Recompute SHA-256
    file_sha = _sha256_file(pack_path)
    info["file_sha256"] = file_sha
    info["expected_file_sha256"] = expected["sha256"]
    if file_sha != expected["sha256"]:
        errors.append(
            f"file SHA-256 mismatch: got {file_sha}, expected {expected['sha256']}")

    # payload_sha256: verify the pack's self-hash binds the payload
    pack = _load_json(pack_path)
    pack_self_sha = pack.get("sha256")
    body = {k: v for k, v in pack.items() if k != "sha256"}
    payload_sha = _sha256_text(_canonical_json(body))
    info["payload_sha256"] = payload_sha
    info["expected_payload_sha256"] = expected["payload_sha256"]
    info["pack_self_sha256"] = pack_self_sha
    if payload_sha != expected["payload_sha256"]:
        errors.append(
            f"payload SHA-256 mismatch: got {payload_sha}, expected {expected['payload_sha256']}")
    if pack_self_sha != payload_sha:
        errors.append(
            f"pack self SHA-256 mismatch: pack.sha256={pack_self_sha} != computed payload {payload_sha}")

    # 4. Verify goal/campaign/evaluation IDs
    r = record
    for field in ("goal_id", "campaign_id", "evaluation_id"):
        if r.get(field) != expected[field]:
            errors.append(f"{field} mismatch: record={r.get(field)} != expected={expected[field]}")
    info["goal_id"] = r.get("goal_id")

    # 5. Verify artifact_chain_hash matches record and DB
    if r.get("artifact_chain_hash") != expected["artifact_chain_hash"]:
        errors.append(
            f"artifact_chain_hash mismatch in record: {r.get('artifact_chain_hash')}")

    # chain_fresh and latest_evaluation_valid
    cf = pack_meta.get("chain_fresh")
    lev = pack_meta.get("latest_evaluation_valid")
    info["chain_fresh"] = cf
    info["latest_evaluation_valid"] = lev
    if cf is not True:
        errors.append(f"chain_fresh is {cf}, expected true")
    if lev is not True:
        errors.append(f"latest_evaluation_valid is {lev}, expected true")

    # Verify canonical DB recomputes the same chain hash
    if DB_ROOT.is_dir():
        db_path = DB_ROOT / "agentos.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        db_chain = _db_chain_hash(conn, expected["goal_id"])
        conn.close()
        info["db_chain_hash"] = db_chain
        info["db_chain_match"] = db_chain == expected["artifact_chain_hash"]
        if db_chain != expected["artifact_chain_hash"]:
            errors.append(
                f"DB chain hash mismatch: {db_chain} != {expected['artifact_chain_hash']}")
    else:
        errors.append(f"canonical DB root missing: {DB_ROOT}")

    # 6. Cross-check result/status
    if r.get("result") != expected["result"]:
        errors.append(
            f"result mismatch: record={r.get('result')} != expected={expected['result']}")

    # 7. Cross-check revision in DB vs docs
    if DB_ROOT.is_dir():
        db_path = DB_ROOT / "agentos.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT revision FROM research_series WHERE goal_id=? ORDER BY revision DESC",
            (expected["goal_id"],)).fetchone()
        db_rev = row["revision"] if row else None
        conn.close()
        info["db_revision"] = db_rev
        info["expected_revision"] = expected["revision"]
        if db_rev != expected["revision"]:
            errors.append(f"DB revision mismatch: {db_rev} != {expected['revision']}")

    return {"ticket_id": ticket_id, "ok": len(errors) == 0,
            "errors": errors, "info": info, "record": r}


def _check_docs_status() -> dict[str, Any]:
    """Cross-check dependency statuses in RESEARCH_STAGE_1_TICKETS.md."""
    text = STATUS_DOC.read_text(encoding="utf-8")
    result: dict[str, Any] = {}
    for tid in ("S1-002", "S1-004"):
        pattern = rf"\|\s*{tid}\s*\|\s*\S+\s*\|\s*\S+\s*\|\s*\S+\s*\|\s*(\S+)\s*\|"
        m = re.search(pattern, text)
        if m:
            result[tid] = m.group(1)
        else:
            result[tid] = "NOT_FOUND"
    return result


def main() -> int:
    deps = ["S1-002", "S1-004"]
    results = {}
    all_ok = True
    for tid in deps:
        res = check_ticket(tid, REQUIRED_HEX[tid])
        results[tid] = res
        if not res["ok"]:
            all_ok = False
    docs_status = _check_docs_status()
    results["docs_status"] = docs_status
    for tid, st in docs_status.items():
        st_norm = st.lower() if isinstance(st, str) else st
        if st_norm not in ("pass_with_limits", "pass"):
            results.setdefault("errors", []).append(
                f"{tid} status in docs is '{st}', expected pass or pass_with_limits")
            all_ok = False

    # Transfer restrictions per task spec
    results["transfer_restrictions"] = {
        "S1-002": [
            "Short/same-host/local benchmark is NOT a production SLO",
            "Revocation trials are prior evidence, NOT a replacement for independent S1-008 run",
        ],
        "S1-004": [
            "INV5 and transition semantics are bounded formal/model contract only",
            "Implementation conformance must still be measured here in S1-008",
        ],
    }

    gate = {
        "schema": "agentos.s1-008.dependency-gate/v1",
        "checked_at": "2026-08-31T22:11:00Z",
        "repo_root": str(REPO),
        "db_root": str(DB_ROOT),
        "dependencies": deps,
        "overall_ok": all_ok,
        "results": results,
    }
    out_path = Path(__file__).resolve().parent / "dependency-gate.json"
    out_path.write_text(_canonical_json(gate), encoding="utf-8")
    print(json.dumps(gate, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
    sys.exit(main())
