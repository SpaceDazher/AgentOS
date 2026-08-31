"""S1-006 — preflight dependency gate (S1-002, S1-005).

Verifies, from actual bytes rather than narrative:
- tracked content-addressed evidence pack exists and its file SHA-256
  matches the evaluation record;
- the pack's payload self-hash matches the record's payload_sha256;
- goal/evaluation ids and the artifact chain hash agree between the
  record and the canonical DB;
- chain_fresh=true and latest_evaluation_valid=true are recorded;
- the docs status matches the canonical verdict.

Fails closed with BLOCKED on any mismatch.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DB = ROOT / ".agentos-research" / "platform-stage-1" / "agentos.db"
DOCS = ROOT / "docs" / "RESEARCH_STAGE_1_TICKETS.md"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def payload_sha(pack: dict) -> str:
    payload = {key: value for key, value in pack.items() if key != "sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return sha(encoded)


def validate_dependency_binding(rec: dict, pack: dict, db_eval,
                                revision_in_db: int | None) -> list[str]:
    """Validate the complete record -> pack -> canonical evaluation binding."""
    problems = []
    evidence = rec.get("evidence_pack") or {}
    research = pack.get("research") or {}
    campaign = research.get("campaign") or {}
    evaluations = research.get("evaluations") or []
    goal = pack.get("goal") or {}

    if evidence.get("chain_fresh") is not True or \
            research.get("chain_fresh") is not True:
        problems.append("chain_fresh is not true")
    if evidence.get("latest_evaluation_valid") is not True or \
            research.get("latest_evaluation_valid") is not True:
        problems.append("latest_evaluation_valid is not true")
    expected_chain = rec.get("artifact_chain_hash")
    if research.get("current_chain_hash") != expected_chain:
        problems.append("pack current chain mismatch")
    if research.get("latest_chain_hash") != expected_chain:
        problems.append("pack latest chain mismatch")
    if goal.get("id") != rec.get("goal_id"):
        problems.append("pack goal id mismatch")
    if campaign.get("id") != rec.get("campaign_id") or \
            campaign.get("goal_id") != rec.get("goal_id"):
        problems.append("pack campaign binding mismatch")
    if campaign.get("revision") is not None and \
            campaign.get("revision") != rec.get("research_revision"):
        problems.append("pack research revision mismatch")

    matches = [item for item in evaluations
               if item.get("id") == rec.get("evaluation_id")]
    if len(matches) != 1:
        problems.append("pack evaluation id missing or duplicated")
    else:
        packed_eval = matches[0]
        for key in ("result", "artifact_chain_hash", "campaign_id", "goal_id"):
            if packed_eval.get(key) != rec.get(
                    "artifact_chain_hash" if key == "artifact_chain_hash" else key):
                problems.append(f"pack evaluation {key} mismatch")

    if db_eval is None:
        problems.append("evaluation id not in canonical DB")
    else:
        for key in ("id", "result", "artifact_chain_hash", "campaign_id",
                    "goal_id"):
            if db_eval[key] != rec.get(
                    "evaluation_id" if key == "id" else key):
                problems.append(f"{key} mismatch vs canonical DB")
    if revision_in_db != rec.get("research_revision"):
        problems.append(
            f"research_revision mismatch: record={rec.get('research_revision')} "
            f"db={revision_in_db}")
    if pack.get("sha256") != evidence.get("payload_sha256"):
        problems.append("pack payload sha field mismatch")
    if payload_sha(pack) != evidence.get("payload_sha256"):
        problems.append("pack payload bytes mismatch")
    return problems


def check(ticket: str) -> dict:
    rec_path = ROOT / "research/tickets/stage-1" / ticket / "evaluation-record.json"
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    problems = []

    pack_path = ROOT / rec["evidence_pack"]["path"]
    if not pack_path.is_file():
        problems.append(f"tracked pack missing: {pack_path}")
    else:
        file_sha = sha(pack_path.read_bytes())
        if file_sha != rec["evidence_pack"]["sha256"]:
            problems.append("pack file sha mismatch")
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        if pack_path.name != \
                f"evidence-pack-{rec['evidence_pack']['sha256']}.json":
            problems.append("pack path is not content-addressed by file sha")

    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    ev = c.execute(
        "SELECT id, result, artifact_chain_hash, campaign_id, goal_id"
        " FROM research_evaluation WHERE id=?",
        (rec["evaluation_id"],)).fetchone()
    series = c.execute(
        "SELECT revision FROM research_series WHERE research_key=? AND goal_id=?",
        (ticket, rec["goal_id"])).fetchone()
    revision_in_db = series["revision"] if series else None
    if pack_path.is_file():
        problems.extend(validate_dependency_binding(
            rec, pack, dict(ev) if ev is not None else None, revision_in_db))

    docs = DOCS.read_text(encoding="utf-8")
    marker = f"### {ticket} "
    seg = docs[docs.index(marker):]
    seg = seg[:seg.index("### ", 10)]
    expected = rec["result"].upper()
    if f"`{expected}`" not in seg.split("- **Priority:**")[0]:
        problems.append(f"docs status does not record {expected}")

    return {
        "ticket": ticket,
        "verdict": rec["result"],
        "research_revision": rec.get("research_revision"),
        "evaluation_id": rec["evaluation_id"],
        "goal_id": rec["goal_id"],
        "artifact_chain_hash": rec["artifact_chain_hash"][:16] + "...",
        "pack_sha256": rec["evidence_pack"]["sha256"][:16] + "...",
        "payload_sha256": rec["evidence_pack"]["payload_sha256"][:16] + "...",
        "problems": problems,
        "status": "PROVEN" if not problems else "NOT_PROVEN",
    }


def main() -> int:
    results = [check(t) for t in ("S1-002", "S1-005")]
    print(json.dumps({"schema": "agentos.s1-006.dependency-gate/v1",
                      "dependencies": results}, indent=2))
    failed = [r for r in results if r["status"] != "PROVEN"]
    if failed:
        print(f"BLOCKED: dependency evidence not proven for "
              f"{[r['ticket'] for r in failed]}", file=sys.stderr)
        return 1
    print("DEPENDENCY GATE: both dependencies PROVEN", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
