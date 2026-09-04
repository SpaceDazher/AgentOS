"""Publish S1-013 canonical evidence from trusted local SQLite state."""
from __future__ import annotations

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

from agentos.research import _manifest_hash, _normalise_config, research_chain_hash


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def publish(data: bytes, prefix: str) -> dict[str, str]:
    digest = sha(data)
    target = HERE / "results" / "evidence" / f"{prefix}-{digest}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != data:
        raise ValueError("content-address collision")
    target.write_bytes(data)
    return {"path": target.relative_to(REPO).as_posix(), "sha256": digest}


def canonical_dependencies() -> list[dict]:
    gate = json.loads((HERE / "results" / "dependency-gate.json").read_text(
        encoding="utf-8"))
    if gate.get("all_proven") is not True:
        raise ValueError("dependency gate is not proven")
    proofs = []
    for item in gate.get("dependencies", []):
        if item.get("status") != "PROVEN" or item.get("problems"):
            raise ValueError("dependency proof is not positive")
        proofs.append({
            "ticket_id": item["ticket"],
            "research_revision": item["research_revision"],
            "goal_id": item["goal_id"],
            "evaluation_id": item["evaluation_id"],
            "result": item["verdict"],
            "artifact_chain_hash": item["artifact_chain_hash"],
            "chain_recomputed_from_disk": True,
        })
    if {item["ticket_id"] for item in proofs} != {"S1-011", "S1-012"}:
        raise ValueError("canonical dependency set is incomplete")
    return proofs


def verify_binding(series: dict, evaluation: dict, pack: dict) -> None:
    if evaluation.get("result") != "pass_with_limits":
        raise ValueError("canonical evaluation is not pass_with_limits")
    research = pack.get("research", {})
    chain = evaluation.get("artifact_chain_hash")
    latest = max(research.get("evaluations", []),
                 key=lambda row: (row.get("evaluation_version", 0),
                                  row.get("id", "")), default={})
    checks = (
        isinstance(chain, str) and len(chain) == 64,
        evaluation.get("goal_id") == series.get("goal_id"),
        pack.get("goal", {}).get("id") == series.get("goal_id"),
        research.get("campaign", {}).get("id") == series.get("campaign_id"),
        research.get("current_chain_hash") == chain,
        research.get("latest_chain_hash") == chain,
        research.get("chain_fresh") is True,
        research.get("latest_evaluation_valid") is True,
        latest.get("id") == evaluation.get("id"),
        latest.get("artifact_chain_hash") == chain,
        latest.get("result") == evaluation.get("result"),
    )
    if not all(checks):
        raise ValueError("stale or mismatched canonical binding")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args(argv)

    publisher = load_module(HERE / "make_bundle.py", "s1013_publication_gate")
    blockers, _ = publisher.derive_verdict()
    if blockers:
        raise ValueError("current ticket evidence is invalid: " + "; ".join(blockers))
    publisher.verified_solo_closure(HERE)

    db_root = Path(args.db).resolve()
    db_file = db_root / "agentos.db"
    with sqlite3.connect(db_file.as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        series_row = conn.execute(
            "SELECT * FROM research_series WHERE research_key=? "
            "ORDER BY revision DESC LIMIT 1", ("S1-013",)).fetchone()
        if series_row is None:
            raise ValueError("no canonical S1-013 series")
        series = dict(series_row)
        evaluation_row = conn.execute(
            "SELECT * FROM research_evaluation WHERE goal_id=? "
            "ORDER BY evaluation_version DESC, id DESC LIMIT 1",
            (series["goal_id"],)).fetchone()
        if evaluation_row is None:
            raise ValueError("no canonical S1-013 evaluation")
        evaluation = dict(evaluation_row)
        if research_chain_hash(SimpleNamespace(conn=conn), series["goal_id"]) != \
                evaluation["artifact_chain_hash"]:
            raise ValueError("canonical artifact chain is stale")

    bundle = json.loads((HERE / "bundle.json").read_text(encoding="utf-8"))
    config, config_errors = _normalise_config(None, bundle)
    manifest, manifest_errors = _manifest_hash(bundle, config)
    if config_errors or manifest_errors or manifest != series["manifest_sha256"]:
        raise ValueError("bundle is not the canonical revision input")
    candidate = json.loads((HERE / "candidate-record.json").read_text(
        encoding="utf-8"))
    if candidate.get("status") != "CLOSED_WITH_LIMITS" or \
            candidate.get("human_n") != 0 or \
            candidate.get("bundle_sha256") != sha((HERE / "bundle.json").read_bytes()):
        raise ValueError("candidate closure binding is stale")

    raw = (db_root / "goals" / series["goal_id"] / "evidence-pack.json").read_bytes()
    pack = json.loads(raw)
    if sha(canonical({key: value for key, value in pack.items()
                      if key != "sha256"})) != pack.get("sha256"):
        raise ValueError("canonical pack self-hash mismatch")
    verify_binding(series, evaluation, pack)
    canonical_pack = publish(raw, "evidence-pack")
    canonical_pack.update(payload_sha256=pack["sha256"], chain_fresh=True,
                          latest_evaluation_valid=True)

    excluded = {"evaluation-record.json", "candidate-record.json"}
    files = [path for path in HERE.rglob("*") if path.is_file() and
             "__pycache__" not in path.parts and
             "evidence" not in path.relative_to(HERE).parts and
             path.name not in excluded]
    hashes = {path.relative_to(REPO).as_posix(): sha(path.read_bytes())
              for path in sorted(files)}
    tests = sorted((REPO / "tests").glob("test_s1_013*.py"))
    hashes.update({path.relative_to(REPO).as_posix(): sha(path.read_bytes())
                   for path in tests})
    dependencies = canonical_dependencies()
    payload = {
        "schema": "agentos.s1-013.ticket-evidence/v1",
        "ticket_id": "S1-013",
        "series": series,
        "evaluation": evaluation,
        "canonical_dependencies": dependencies,
        "canonical_pack": canonical_pack,
        "closure": candidate["solo_review"],
        "tracked_artifact_hashes": hashes,
    }
    payload_hash = sha(canonical(payload))
    ticket_pack = publish(
        canonical({"payload": payload, "payload_sha256": payload_hash}) + b"\n",
        "ticket-pack")
    record = {
        "schema": "agentos.ticket-evaluation-record/v2",
        "ticket_id": "S1-013",
        "research_revision": series["revision"],
        "goal_id": series["goal_id"],
        "campaign_id": series["campaign_id"],
        "evaluation_id": evaluation["id"],
        "artifact_chain_hash": evaluation["artifact_chain_hash"],
        "result": evaluation["result"],
        "manifest_sha256": manifest,
        "canonical_dependencies": dependencies,
        "bundle_sha256": candidate["bundle_sha256"],
        "evidence_pack": canonical_pack,
        "ticket_pack": {**ticket_pack, "payload_sha256": payload_hash},
        "limitations": json.loads(evaluation["limitations_json"]),
        "tracked_artifact_hashes": hashes,
    }
    (HERE / "evaluation-record.json").write_bytes(
        json.dumps(record, indent=2, sort_keys=True,
                   ensure_ascii=False).encode("utf-8") + b"\n")
    print(json.dumps({key: value for key, value in record.items()
                      if key != "tracked_artifact_hashes"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
