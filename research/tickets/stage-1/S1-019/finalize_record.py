"""Publish S1-019 packs from canonical SQLite state after operator approval."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tarfile
from types import SimpleNamespace

TICKET = Path(__file__).resolve().parent
REPO = TICKET.parents[3]
sys.path.insert(0, str(REPO / "src"))
from agentos.research import _manifest_hash, _normalise_config, research_chain_hash


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def publish(prefix: str, raw: bytes) -> dict:
    digest = sha(raw)
    path = TICKET / "results/evidence" / f"{prefix}-{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("content-address collision")
    path.write_bytes(raw)
    return {"path": path.relative_to(REPO).as_posix(), "sha256": digest}


def check_clean_archive() -> dict[str, str]:
    status = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain=v1",
                             "--untracked-files=all"], capture_output=True,
                            text=True, check=True).stdout
    if status.strip():
        raise ValueError("publisher requires clean Git tree")
    listed = subprocess.run(["git", "-C", str(REPO), "ls-files",
                             "research/tickets/stage-1/S1-019", "tests/test_s1_019*.py"],
                            capture_output=True, text=True, check=True).stdout.splitlines()
    hashes = {}
    for rel in sorted(listed):
        if "/results/evidence/" in rel or rel.endswith("evaluation-record.json"):
            continue
        raw = subprocess.run(["git", "-C", str(REPO), "show", f"HEAD:{rel}"],
                             capture_output=True, check=True).stdout
        if raw != (REPO / rel).read_bytes():
            raise ValueError(f"working tree/archive mismatch: {rel}")
        hashes[rel] = sha(raw)
    if not hashes:
        raise ValueError("no tracked artifacts")
    return hashes


def secret_scan() -> None:
    patterns = (re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
                re.compile(rb"ghp_[A-Za-z0-9]{20,}"),
                re.compile(rb"AKIA[A-Z0-9]{16}"),
                re.compile(rb"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"))
    for path in TICKET.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        raw = path.read_bytes()
        if b"\x00" in raw:
            continue
        if any(pattern.search(raw) for pattern in patterns):
            raise ValueError(f"secret marker in {path.name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    bundle = json.loads((TICKET / "bundle.json").read_text("utf-8"))
    candidate = json.loads((TICKET / "candidate-record.json").read_text("utf-8"))
    operator = json.loads((TICKET / "operator-decision.json").read_text("utf-8"))
    comparison = json.loads((TICKET / "results/comparison.json").read_text("utf-8"))
    if candidate.get("status") not in {"PASS_WITH_LIMITS", "DEFER"}:
        raise SystemExit("candidate is not publishable")
    if comparison.get("verdict") != "TECHNICAL_CANDIDATE":
        raise SystemExit("technical evidence is not publishable")
    if operator.get("derived_status") != candidate.get("status"):
        raise SystemExit("operator/candidate status mismatch")
    tracked = check_clean_archive()
    secret_scan()
    db_root = Path(args.db).resolve()
    db_file = db_root / "agentos.db"
    with sqlite3.connect(db_file.as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        series_row = conn.execute(
            "SELECT * FROM research_series WHERE research_key=? "
            "ORDER BY revision DESC LIMIT 1", ("S1-019",)).fetchone()
        if series_row is None:
            raise SystemExit("canonical S1-019 series missing")
        series = dict(series_row)
        evaluation_row = conn.execute(
            "SELECT * FROM research_evaluation WHERE goal_id=? "
            "ORDER BY evaluation_version DESC, id DESC LIMIT 1",
            (series["goal_id"],)).fetchone()
        if evaluation_row is None:
            raise SystemExit("canonical S1-019 evaluation missing")
        evaluation = dict(evaluation_row)
        recomputed_chain = research_chain_hash(SimpleNamespace(conn=conn),
                                                series["goal_id"])
    if recomputed_chain != evaluation.get("artifact_chain_hash"):
        raise SystemExit("canonical artifact chain stale")
    config, config_errors = _normalise_config(None, bundle)
    manifest, manifest_errors = _manifest_hash(bundle, config)
    if config_errors or manifest_errors or manifest != series.get("manifest_sha256"):
        raise SystemExit("bundle/canonical manifest mismatch")
    runtime_path = db_root / "goals" / series["goal_id"] / "evidence-pack.json"
    canonical_raw = runtime_path.read_bytes()
    canonical_doc = json.loads(canonical_raw)
    payload_hash = sha(canonical({k: v for k, v in canonical_doc.items() if k != "sha256"}))
    if canonical_doc.get("sha256") != payload_hash:
        raise SystemExit("canonical evidence self-hash mismatch")
    research = canonical_doc.get("research", {})
    if (canonical_doc.get("goal", {}).get("id") != series["goal_id"]
            or research.get("campaign", {}).get("id") != series["campaign_id"]
            or research.get("current_chain_hash") != recomputed_chain
            or research.get("latest_chain_hash") != recomputed_chain
            or research.get("chain_fresh") is not True
            or research.get("latest_evaluation_valid") is not True):
        raise SystemExit("canonical pack binding mismatch")
    evidence_pack = publish("evidence-pack", canonical_raw)
    evidence_pack.update(payload_sha256=payload_hash, chain_fresh=True,
                         latest_evaluation_valid=True)
    raw_payload = {
        "schema": "agentos.s1-019.raw-archive/v1",
        "run_a": json.loads((TICKET / "results/run-a/observations.json").read_text("utf-8")),
        "run_b": json.loads((TICKET / "results/run-b/observations.json").read_text("utf-8")),
        "comparison": comparison,
        "sensitivity": json.loads((TICKET / "results/sensitivity.json").read_text("utf-8")),
    }
    raw_payload_sha = sha(canonical(raw_payload))
    raw_archive = publish("raw-archive", canonical(
        {"payload": raw_payload, "payload_sha256": raw_payload_sha}) + b"\n")
    raw_archive["payload_sha256"] = raw_payload_sha
    gate = json.loads((TICKET / "results/dependency-gate.json").read_text("utf-8"))
    dependencies = [{
        "ticket_id": item["ticket"], "research_revision": item["research_revision"],
        "goal_id": item["goal_id"], "campaign_id": item["campaign_id"],
        "evaluation_id": item["evaluation_id"], "result": item["result"],
        "artifact_chain_hash": item["artifact_chain_hash"],
        "chain_recomputed_from_git": True,
        "verified_commit": gate["verified_commit"],
    } for item in gate["dependencies"]]
    ticket_payload = {
        "schema": "agentos.s1-019.ticket-evidence/v1", "ticket_id": "S1-019",
        "series": series, "evaluation": evaluation,
        "canonical_dependencies": dependencies,
        "canonical_pack": evidence_pack, "raw_archive": raw_archive,
        "operator_decision": operator, "comparison": comparison,
        "tracked_artifact_hashes": tracked,
    }
    ticket_payload_sha = sha(canonical(ticket_payload))
    ticket_pack = publish("ticket-pack", canonical(
        {"payload": ticket_payload, "payload_sha256": ticket_payload_sha}) + b"\n")
    ticket_pack["payload_sha256"] = ticket_payload_sha
    limitations = json.loads(evaluation["limitations_json"])
    record = {
        "schema": "agentos.ticket-evaluation-record/v2", "ticket_id": "S1-019",
        "research_revision": series["revision"], "goal_id": series["goal_id"],
        "campaign_id": series["campaign_id"], "evaluation_id": evaluation["id"],
        "artifact_chain_hash": recomputed_chain, "result": evaluation["result"],
        "manifest_sha256": manifest, "bundle_sha256": sha((TICKET / "bundle.json").read_bytes()),
        "canonical_dependencies": dependencies, "evidence_pack": evidence_pack,
        "ticket_pack": ticket_pack, "raw_archive": raw_archive,
        "operator_decision_sha256": sha((TICKET / "operator-decision.json").read_bytes()),
        "limitations": limitations, "tracked_artifact_hashes": tracked,
        "production_authority": False, "goal_acceptance_authority": False,
    }
    (TICKET / "evaluation-record.json").write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({"goal_id": record["goal_id"], "evaluation_id": record["evaluation_id"],
                      "result": record["result"],
                      "artifact_chain_hash": record["artifact_chain_hash"],
                      "evidence_pack": evidence_pack["path"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
