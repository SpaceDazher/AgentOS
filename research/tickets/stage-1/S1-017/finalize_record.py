"""Publish S1-017 canonical evidence from trusted local SQLite state."""
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
    if gate.get("dependencies_proven") is not True:
        raise ValueError("dependency gate is not proven")
    proofs = []
    for key, item in gate.get("dependencies", {}).items():
        if item.get("problems"):
            raise ValueError(f"dependency proof is not positive: {key}")
        record = item["record"]
        proofs.append({
            "ticket_id": record["ticket_id"],
            "research_revision": record["research_revision"],
            "goal_id": record["goal_id"],
            "evaluation_id": record["evaluation_id"],
            "result": record["result"],
            "artifact_chain_hash": record["artifact_chain_hash"],
            "verified_from": gate["verified_ref"],
            "verified_commit": gate["verified_commit"],
            "chain_recomputed_from_git": True,
        })
    if {item["ticket_id"] for item in proofs} != {"S1-004", "S1-016"}:
        raise ValueError("canonical dependency set is incomplete")
    return proofs


def verify_binding(series: dict, evaluation: dict, pack: dict) -> None:
    if evaluation.get("result") not in ("pass_with_limits", "inconclusive"):
        raise ValueError("canonical evaluation is not a limited result")
    if evaluation.get("result") == "pass":
        raise ValueError("PASS is out of scope for S1-017")
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


def _remove_if_present(path: Path) -> None:
    if path.is_file() or path.is_symlink():
        path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args(argv)

    evidence_dir = HERE / "results" / "evidence"
    pre_existing = set(p.name for p in evidence_dir.glob("*.json")) \
        if evidence_dir.is_dir() else set()
    record_existed = (HERE / "evaluation-record.json").exists()
    try:
        return _publish(args)
    except (OSError, ValueError) as exc:
        if evidence_dir.is_dir():
            for path in evidence_dir.glob("*.json"):
                if path.name not in pre_existing:
                    path.unlink()
        if not record_existed:
            _remove_if_present(HERE / "evaluation-record.json")
        print(f"publication blocked: {exc}", file=sys.stderr)
        return 1


def _publish(args) -> int:
    publisher = load_module(HERE / "make_bundle.py", "s1017_publication_gate")
    problems, _ = publisher.verify_frozen_manifest(HERE)
    if problems:
        raise ValueError("frozen manifest invalid: " + "; ".join(problems[:4]))
    metrics = publisher._read_json(HERE / "results" / "metrics.json", "metrics")
    comparison = publisher._read_json(HERE / "results" / "comparison.json", "comparison")
    sensitivity_doc = publisher._read_json(HERE / "results" / "sensitivity.json",
                                           "sensitivity")
    blockers, verdict = publisher.derive_verdict(metrics, comparison,
                                                 sensitivity_doc, False, None)
    if blockers:
        raise ValueError("current ticket evidence is invalid: " + "; ".join(blockers))
    present, letters, _ = publisher.verify_operator_decision(HERE)
    if not present:
        raise ValueError("operator decision required for final publication")
    blockers, verdict = publisher.derive_verdict(metrics, comparison,
                                                 sensitivity_doc, present, letters)
    if blockers:
        raise ValueError("current ticket evidence is invalid: " + "; ".join(blockers))
    if verdict["status"] not in ("CLOSED_WITH_LIMITS", "CLOSED_INCONCLUSIVE"):
        raise ValueError("candidate is not in a closed state")

    db_root = Path(args.db).resolve()
    db_file = db_root / "agentos.db"
    with sqlite3.connect(db_file.as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        series_row = conn.execute(
            "SELECT * FROM research_series WHERE research_key=? "
            "ORDER BY revision DESC LIMIT 1", ("S1-017",)).fetchone()
        if series_row is None:
            raise ValueError("no canonical S1-017 series")
        series = dict(series_row)
        evaluation_row = conn.execute(
            "SELECT * FROM research_evaluation WHERE goal_id=? "
            "ORDER BY evaluation_version DESC, id DESC LIMIT 1",
            (series["goal_id"],)).fetchone()
        if evaluation_row is None:
            raise ValueError("no canonical S1-017 evaluation")
        evaluation = dict(evaluation_row)
        if research_chain_hash(SimpleNamespace(conn=conn), series["goal_id"]) != \
                evaluation["artifact_chain_hash"]:
            raise ValueError("canonical artifact chain is stale")

    bundle = json.loads((HERE / "bundle.json").read_text(encoding="utf-8"))
    config, config_errors = _normalise_config(None, bundle)
    manifest, manifest_errors = _manifest_hash(bundle, config)
    if config_errors or manifest_errors or manifest != series["manifest_sha256"]:
        raise ValueError("bundle is not the canonical revision input")
    candidate = json.loads((HERE / "candidate-record.json").read_text(encoding="utf-8"))
    if candidate.get("status") not in ("CLOSED_WITH_LIMITS", "CLOSED_INCONCLUSIVE") or \
            candidate.get("design_decision") not in (
                "OFFLINE_ANALYTICS", "DERIVED_EXPORT_ANNOTATION",
                "BOUNDED_RUNTIME_ANNOTATION", "INCONCLUSIVE") or \
            candidate.get("operator_review_n") not in (0, 1) or \
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
    tests = sorted((REPO / "tests").glob("test_s1_017*.py"))
    hashes.update({path.relative_to(REPO).as_posix(): sha(path.read_bytes())
                   for path in tests})
    dependencies = canonical_dependencies()
    operator = json.loads((HERE / "operator-decision.json").read_text(encoding="utf-8"))
    payload = {
        "schema": "agentos.s1-017.ticket-evidence/v1",
        "ticket_id": "S1-017",
        "series": series,
        "evaluation": evaluation,
        "canonical_dependencies": dependencies,
        "canonical_pack": canonical_pack,
        "closure": {"design_decision": candidate["design_decision"],
                    "placement": candidate.get("placement"),
                    "operator_review_n": candidate["operator_review_n"],
                    "selected_answers": operator.get("selected_answers"),
                    "operator_id": operator.get("operator_id"),
                    "legal_moral_blame": "OUT_OF_SCOPE",
                    "runtime_authority": False},
        "tracked_artifact_hashes": hashes,
    }
    payload_hash = sha(canonical(payload))
    ticket_pack = publish(
        canonical({"payload": payload, "payload_sha256": payload_hash}) + b"\n",
        "ticket-pack")
    record = {
        "schema": "agentos.ticket-evaluation-record/v2",
        "ticket_id": "S1-017",
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
