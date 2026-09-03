"""Trusted-host publication: exact latest SQLite rows, never CLI-supplied IDs.

Reads the canonical DB read-only; refuses stale bundle/pack/evaluation binding.
Publishes immutable content-addressed canonical and ticket packs plus a record.
"""
import argparse
import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "src"))
from agentos.research import _normalise_config, _manifest_hash, research_chain_hash


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def verify_binding(series, evaluation, pack):
    if evaluation.get("result") not in ("pass", "pass_with_limits"):
        raise ValueError("canonical evaluation is not positive")
    research = pack.get("research", {})
    chain = evaluation.get("artifact_chain_hash")
    if not isinstance(chain, str) or len(chain) != 64 or any(c not in "0123456789abcdef" for c in chain) or \
            evaluation.get("goal_id") != series.get("goal_id") or \
            pack.get("goal", {}).get("id") != series.get("goal_id") or \
            research.get("campaign", {}).get("id") != series.get("campaign_id") or \
            research.get("current_chain_hash") != chain or \
            research.get("latest_chain_hash") != chain or \
            research.get("chain_fresh") is not True or \
            research.get("latest_evaluation_valid") is not True:
        raise ValueError("stale or mismatched canonical binding")
    latest = max(research.get("evaluations", []),
                 key=lambda e: (e.get("evaluation_version", 0), e.get("id", "")), default={})
    if any(latest.get(k) != evaluation.get(k) for k in
           ("id", "artifact_chain_hash", "result")):
        raise ValueError("pack does not carry latest evaluation")


def publish(data, prefix):
    digest = sha(data)
    target = HERE / "results/evidence" / f"{prefix}-{digest}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != data:
        raise ValueError("content-address collision")
    target.write_bytes(data)
    return {"path": target.relative_to(REPO).as_posix(), "sha256": digest}


def canonical_dependencies(conn):
    proofs = []
    for ticket in ("S1-001", "S1-003"):
        record = json.loads((HERE.parent / ticket / "evaluation-record.json").read_text(encoding="utf-8"))
        series = conn.execute("SELECT * FROM research_series WHERE research_key=? ORDER BY revision DESC LIMIT 1", (ticket,)).fetchone()
        if series is None or any(series[k] != record[rk] for k, rk in
                                 (("goal_id", "goal_id"), ("campaign_id", "campaign_id"), ("revision", "research_revision"))):
            raise ValueError(f"{ticket}: tracked record is not current canonical series")
        row = conn.execute("SELECT * FROM research_evaluation WHERE goal_id=? ORDER BY evaluation_version DESC, id DESC LIMIT 1", (series["goal_id"],)).fetchone()
        if row is None or any(row[k] != record[rk] for k, rk in
                              (("id", "evaluation_id"), ("result", "result"), ("artifact_chain_hash", "artifact_chain_hash"))):
            raise ValueError(f"{ticket}: tracked evaluation differs from DB")
        chain = research_chain_hash(SimpleNamespace(conn=conn), series["goal_id"])
        if row["result"] not in ("pass", "pass_with_limits") or chain != row["artifact_chain_hash"]:
            raise ValueError(f"{ticket}: dependency failed or files are stale")
        proofs.append({"ticket_id": ticket, "research_revision": series["revision"],
                       "goal_id": series["goal_id"], "evaluation_id": row["id"],
                       "result": row["result"], "artifact_chain_hash": chain,
                       "chain_recomputed_from_disk": True})
    return proofs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("s1011_publication_gate", HERE / "make_bundle.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    blockers, _ = gate.derive_verdict()
    if blockers:
        raise ValueError("current evidence cannot be published: " + "; ".join(blockers))
    db_root = Path(args.db).resolve()
    with sqlite3.connect((db_root / "agentos.db").as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        dependencies = canonical_dependencies(conn)
        series_row = conn.execute("SELECT * FROM research_series WHERE research_key=? ORDER BY revision DESC LIMIT 1", ("S1-011",)).fetchone()
        if series_row is None:
            raise ValueError("no canonical S1-011 series")
        series = dict(series_row)
        evaluation = dict(conn.execute("SELECT * FROM research_evaluation WHERE goal_id=? ORDER BY evaluation_version DESC, id DESC LIMIT 1", (series["goal_id"],)).fetchone())
        if research_chain_hash(SimpleNamespace(conn=conn), series["goal_id"]) != evaluation["artifact_chain_hash"]:
            raise ValueError("canonical artifact files changed after evaluation")
    bundle = json.loads((HERE / "bundle.json").read_text(encoding="utf-8"))
    config, errors = _normalise_config(None, bundle)
    manifest, manifest_errors = _manifest_hash(bundle, config)
    if errors or manifest_errors or manifest != series["manifest_sha256"]:
        raise ValueError("current bundle is not the canonical revision input")
    candidate = json.loads((HERE / "candidate-record.json").read_text(encoding="utf-8"))
    if candidate["bundle_sha256"] != sha((HERE / "bundle.json").read_bytes()):
        raise ValueError("candidate bundle hash stale")
    raw = (db_root / "goals" / series["goal_id"] / "evidence-pack.json").read_bytes()
    pack = json.loads(raw)
    if sha(canonical({k: v for k, v in pack.items() if k != "sha256"})) != pack.get("sha256"):
        raise ValueError("canonical pack self-hash mismatch")
    verify_binding(series, evaluation, pack)
    canonical_pack = publish(raw, "evidence-pack")
    canonical_pack.update(payload_sha256=pack["sha256"], chain_fresh=True,
                          latest_evaluation_valid=True)
    files = [p for p in HERE.rglob("*") if p.is_file() and
             "__pycache__" not in p.parts and "evidence" not in p.relative_to(HERE).parts and
             p.name != "evaluation-record.json"]
    hashes = {p.relative_to(REPO).as_posix(): sha(p.read_bytes()) for p in sorted(files)}
    payload = {"schema": "agentos.s1-011.ticket-evidence/v1", "ticket_id": "S1-011",
               "series": series, "evaluation": evaluation,
               "canonical_dependencies": dependencies,
               "canonical_pack": canonical_pack, "tracked_artifact_hashes": hashes}
    payload_hash = sha(canonical(payload))
    ticket_pack = publish(canonical({"payload": payload, "payload_sha256": payload_hash}) + b"\n", "ticket-pack")
    record = {"schema": "agentos.ticket-evaluation-record/v2", "ticket_id": "S1-011",
              "research_revision": series["revision"], "goal_id": series["goal_id"],
              "campaign_id": series["campaign_id"], "evaluation_id": evaluation["id"],
              "artifact_chain_hash": evaluation["artifact_chain_hash"],
              "result": evaluation["result"], "manifest_sha256": manifest,
              "canonical_dependencies": dependencies,
              "bundle_sha256": candidate["bundle_sha256"], "evidence_pack": canonical_pack,
              "ticket_pack": {**ticket_pack, "payload_sha256": payload_hash},
              "limitations": json.loads(evaluation["limitations_json"]),
              "tracked_artifact_hashes": hashes}
    (HERE / "evaluation-record.json").write_bytes(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n")
    print(json.dumps({k: v for k, v in record.items() if k != "tracked_artifact_hashes"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
