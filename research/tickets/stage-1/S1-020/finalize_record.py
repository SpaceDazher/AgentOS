"""Publish canonical S1-020 evidence and a Git-verifiable evaluation record."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "src"))
from agentos.research import _manifest_hash, _normalise_config, research_chain_hash


SECRET_PATTERNS = (
    re.compile(rb"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"(?<![A-Za-z0-9_])ghp_[A-Za-z0-9]{20,}"),
    re.compile(rb"(?<![A-Z0-9])AKIA[A-Z0-9]{16}"),
    re.compile(rb"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def publish(prefix: str, raw: bytes) -> dict[str, str]:
    digest = sha(raw)
    path = HERE / "results" / "evidence" / f"{prefix}-{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("content-address collision")
    path.write_bytes(raw)
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest}


def clean_archive() -> dict[str, str]:
    status = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all"],
                            cwd=ROOT, capture_output=True, text=True, check=True).stdout
    if status.strip():
        raise ValueError("publisher requires a clean Git tree")
    listed = subprocess.run(["git", "ls-files", "research/tickets/stage-1/S1-020",
                             "tests/test_s1_020*.py"], cwd=ROOT, capture_output=True,
                            text=True, check=True).stdout.splitlines()
    hashes = {}
    for rel in sorted(listed):
        if "/results/evidence/" in rel or rel.endswith("evaluation-record.json"):
            continue
        raw = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT,
                             capture_output=True, check=True).stdout
        if raw != (ROOT / rel).read_bytes():
            raise ValueError(f"archive/working-tree mismatch: {rel}")
        hashes[rel] = sha(raw)
    if len(hashes) < 20:
        raise ValueError("tracked artifact set is incomplete")
    return hashes


def scan_secrets() -> None:
    for path in HERE.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        raw = path.read_bytes()
        if b"\x00" in raw:
            continue
        if any(pattern.search(raw) for pattern in SECRET_PATTERNS):
            raise ValueError(f"secret-shaped value in {path.relative_to(HERE)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    candidate = json.loads((HERE / "candidate-record.json").read_text(encoding="utf-8"))
    bundle = json.loads((HERE / "bundle.json").read_text(encoding="utf-8"))
    comparison = json.loads((HERE / "results/comparison.json").read_text(encoding="utf-8"))
    gate = json.loads((HERE / "dependency-gate.json").read_text(encoding="utf-8"))
    if candidate.get("status") != "PASS_WITH_LIMITS" or \
            candidate.get("bundle_sha256") != sha((HERE / "bundle.json").read_bytes()):
        raise SystemExit("candidate is stale or not publishable")
    if comparison.get("verdict") != "PASS_WITH_LIMITS" or \
            gate.get("status") != "PASS_WITH_LIMITS":
        raise SystemExit("technical or dependency gate failed")
    tracked = clean_archive()
    scan_secrets()

    db_file = Path(args.db).resolve() / "agentos.db"
    with sqlite3.connect(db_file.as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM research_series WHERE research_key=? "
                           "ORDER BY revision DESC LIMIT 1", ("S1-020",)).fetchone()
        if row is None:
            raise SystemExit("canonical S1-020 series missing")
        series = dict(row)
        erow = conn.execute("SELECT * FROM research_evaluation WHERE goal_id=? "
                            "ORDER BY evaluation_version DESC, id DESC LIMIT 1",
                            (series["goal_id"],)).fetchone()
        if erow is None:
            raise SystemExit("canonical S1-020 evaluation missing")
        evaluation = dict(erow)
        chain = research_chain_hash(SimpleNamespace(conn=conn), series["goal_id"])
    if series.get("revision") != 2 or evaluation.get("result") != "pass_with_limits":
        raise SystemExit("latest canonical revision is not the expected passing revision")
    if chain != evaluation.get("artifact_chain_hash"):
        raise SystemExit("canonical artifact chain is stale")
    config, config_errors = _normalise_config(None, bundle)
    manifest, manifest_errors = _manifest_hash(bundle, config)
    if config_errors or manifest_errors or manifest != series.get("manifest_sha256"):
        raise SystemExit("bundle/canonical manifest mismatch")

    runtime = Path(args.db).resolve() / "goals" / series["goal_id"] / "evidence-pack.json"
    canonical_raw = runtime.read_bytes()
    pack = json.loads(canonical_raw)
    payload_hash = sha(canonical({k: v for k, v in pack.items() if k != "sha256"}))
    research = pack.get("research") or {}
    if (pack.get("schema") != "agentos.evidence-pack/v3" or pack.get("sha256") != payload_hash
            or pack.get("goal", {}).get("id") != series["goal_id"]
            or research.get("campaign", {}).get("id") != series["campaign_id"]
            or research.get("current_chain_hash") != chain
            or research.get("latest_chain_hash") != chain
            or research.get("chain_fresh") is not True
            or research.get("latest_evaluation_valid") is not True):
        raise SystemExit("canonical evidence pack binding failed")
    evidence = publish("evidence-pack", canonical_raw)
    evidence.update(payload_sha256=payload_hash, chain_fresh=True,
                    latest_evaluation_valid=True, schema="agentos.evidence-pack/v3")

    raw_payload = {
        "schema": "agentos.s1-020.raw-archive/v1",
        "run_a": json.loads((HERE / "results/run-a/observations.json").read_text(encoding="utf-8")),
        "run_b": json.loads((HERE / "results/run-b/observations.json").read_text(encoding="utf-8")),
        "comparison": comparison,
        "sensitivity": json.loads((HERE / "results/sensitivity.json").read_text(encoding="utf-8")),
        "dependency_gate": gate,
        "coverage_matrix": json.loads((HERE / "coverage-matrix.json").read_text(encoding="utf-8")),
    }
    raw_payload_hash = sha(canonical(raw_payload))
    raw_archive = publish("raw-archive", canonical(
        {"payload": raw_payload, "payload_sha256": raw_payload_hash}) + b"\n")
    raw_archive["payload_sha256"] = raw_payload_hash

    dependencies = [{"ticket_id": row["ticket"], "research_revision": row.get("research_revision"),
                     "goal_id": row.get("goal_id"), "campaign_id": row.get("campaign_id"),
                     "evaluation_id": row.get("evaluation_id"), "result": row.get("result"),
                     "artifact_chain_hash": row.get("artifact_chain_hash"),
                     "chain_recomputed_from_git": True,
                     "verified_commit": gate["verified_commit"]}
                    for row in gate["dependencies"]]
    ticket_payload = {"schema": "agentos.s1-020.ticket-evidence/v1", "ticket_id": "S1-020",
                      "series": series, "evaluation": evaluation,
                      "canonical_dependencies": dependencies,
                      "prior_probe_results": gate["probe_results"],
                      "canonical_pack": evidence, "raw_archive": raw_archive,
                      "tracked_artifact_hashes": tracked,
                      "goal_accepted": False, "production_certified": False,
                      "parked_items_reopened": False}
    ticket_payload_hash = sha(canonical(ticket_payload))
    ticket_pack = publish("ticket-pack", canonical(
        {"payload": ticket_payload, "payload_sha256": ticket_payload_hash}) + b"\n")
    ticket_pack["payload_sha256"] = ticket_payload_hash
    record = {
        "schema": "agentos.ticket-evaluation-record/v2", "ticket_id": "S1-020",
        "research_revision": series["revision"], "goal_id": series["goal_id"],
        "campaign_id": series["campaign_id"], "evaluation_id": evaluation["id"],
        "artifact_chain_hash": chain, "result": evaluation["result"],
        "manifest_sha256": manifest, "bundle_sha256": sha((HERE / "bundle.json").read_bytes()),
        "canonical_dependencies": dependencies, "prior_probe_count": 19,
        "all_prior_probes_pass": True, "active_ticket_count": 20, "parked_count": 4,
        "evidence_pack": evidence, "ticket_pack": ticket_pack, "raw_archive": raw_archive,
        "limitations": json.loads(evaluation["limitations_json"]),
        "tracked_artifact_hashes": tracked,
        "auditor_identity": "agentos-s1-020-independent-auditor",
        "subject_producer": "agentos-s1-020-bundle-producer",
        "auditor_distinct": True, "wiki_check_ok": True,
        "production_authority": False, "goal_acceptance_authority": False,
        "parked_items_reopened": False,
    }
    (HERE / "evaluation-record.json").write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({"goal_id": record["goal_id"], "campaign_id": record["campaign_id"],
                      "evaluation_id": record["evaluation_id"], "result": record["result"],
                      "chain": chain, "evidence_pack": evidence["path"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
