"""Generate evaluation-record.json PROGRAMMATICALLY from canonical state.

REVIEW_R2 finding 1: hand-typed hashes diverged from the canonical chain.
This script eliminates manual hash entry: every value is read from the
canonical DB row, the published evidence pack bytes, the tracked raw
archive file or the live wiki-check output:

- goal/campaign/evaluation ids, result, artifact_chain_hash (FULL 64 hex)
  come from the canonical `research_evaluation` row;
- research_revision comes from the canonical `research_series` row;
- the tracked pack file is (re)published from the canonical runtime pack
  and its file/payload SHA-256 are recomputed from bytes;
- exact record == DB == pack equality is asserted for every shared field;
- the raw-observations archive is located by its content-addressed name
  and its SHA-256 is recomputed from bytes;
- wiki counts come from a live `wiki-check` run.

Fails closed on any mismatch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TICKET = Path(__file__).resolve().parent
DB = ROOT / ".agentos-research" / "platform-stage-1" / "agentos.db"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def payload_sha(pack: dict) -> str:
    payload = {k: v for k, v in pack.items() if k != "sha256"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def git_commit() -> str:
    out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                         text=True, timeout=30, cwd=str(ROOT))
    if out.returncode != 0:
        raise SystemExit(f"git rev-parse HEAD failed: {out.stderr}")
    return out.stdout.strip()


def canonical_row(goal_id: str | None = None) -> dict:
    import sqlite3
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    if goal_id is None:
        row = c.execute(
            "SELECT goal_id, campaign_id, revision FROM research_series"
            " WHERE research_key='S1-007' ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise SystemExit("no S1-007 research series in canonical DB")
        goal_id = row["goal_id"]
        revision = row["revision"]
        campaign_id = row["campaign_id"]
    else:
        row = c.execute(
            "SELECT goal_id, campaign_id, revision FROM research_series"
            " WHERE research_key='S1-007' AND goal_id=?",
            (goal_id,)).fetchone()
        if row is None:
            raise SystemExit(f"no series row for goal {goal_id}")
        goal_id = row["goal_id"]
        revision = row["revision"]
        campaign_id = row["campaign_id"]
    ev = c.execute(
        "SELECT id, result, artifact_chain_hash, campaign_id, goal_id,"
        " evaluation_version FROM research_evaluation WHERE campaign_id=?"
        " ORDER BY evaluation_version DESC LIMIT 1",
        (campaign_id,)).fetchone()
    if ev is None:
        raise SystemExit(f"no evaluation for campaign {campaign_id}")
    c.close()
    return {"goal_id": goal_id, "campaign_id": campaign_id,
            "research_revision": revision, "evaluation": dict(ev)}


def live_wiki_check() -> dict:
    env = {"PYTHONPATH": str(ROOT / "src"), "PATH": ""}
    env.update({k: v for k, v in __import__("os").environ.items()
                if k not in env})
    out = subprocess.run(
        [sys.executable, "-m", "agentos.cli", "wiki-check", "--db",
         ".agentos-research/platform-stage-1"],
        capture_output=True, text=True, timeout=600, cwd=str(ROOT), env=env)
    if out.returncode != 0:
        raise SystemExit(f"wiki-check failed (exit {out.returncode})")
    doc = json.loads(out.stdout)
    if not doc.get("ok"):
        raise SystemExit("live wiki-check reported issues")
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recorded-at", required=True)
    ap.add_argument("--corrective-round", required=True)
    ap.add_argument("--supersedes-note", required=True)
    args = ap.parse_args(argv)

    canon = canonical_row()
    ev = canon["evaluation"]
    goal_id = canon["goal_id"]

    # publish the tracked pack from the canonical runtime pack
    canonical_pack = (DB.parent / "goals" / goal_id / "evidence-pack.json")
    if not canonical_pack.is_file():
        raise SystemExit(f"canonical pack missing: {canonical_pack}")
    raw = canonical_pack.read_bytes()
    pack = json.loads(raw.decode("utf-8"))
    file_sha = sha(raw)
    p_sha = payload_sha(pack)
    if pack.get("sha256") != p_sha:
        raise SystemExit("canonical pack payload self-hash mismatch")
    evidence_dir = TICKET / "results" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    tracked_pack = evidence_dir / f"evidence-pack-{file_sha}.json"
    tracked_pack.write_bytes(raw)

    # locate the tracked raw archive by its content-addressed name
    archives = sorted(evidence_dir.glob("raw-observations-*.json"))
    if len(archives) != 1:
        raise SystemExit(f"expected exactly one raw archive, found "
                         f"{[a.name for a in archives]}")
    archive = archives[0]
    archive_sha = sha(archive.read_bytes())
    if archive.name != f"raw-observations-{archive_sha}.json":
        raise SystemExit("archive name is not content-addressed")
    archive_doc = json.loads(archive.read_text(encoding="utf-8"))
    member_count = archive_doc.get("member_count")
    # every member digest re-verified from bytes
    for name, digest in archive_doc["member_sha256"].items():
        if sha(archive_doc["members"][name].encode("utf-8")) != digest:
            raise SystemExit(f"archive member digest mismatch: {name}")

    # full-hash equality: DB row vs pack-embedded evaluation
    research = pack.get("research") or {}
    packed_evals = [e for e in research.get("evaluations", [])
                    if e.get("id") == ev["id"]]
    if len(packed_evals) != 1:
        raise SystemExit("pack does not embed exactly the canonical "
                         "evaluation")
    pe = packed_evals[0]
    for key in ("result", "artifact_chain_hash", "campaign_id", "goal_id"):
        if pe.get(key) != ev[key]:
            raise SystemExit(f"pack evaluation {key} != canonical DB "
                             f"({pe.get(key)!r} != {ev[key]!r})")
    if research.get("current_chain_hash") != ev["artifact_chain_hash"] or \
            research.get("latest_chain_hash") != ev["artifact_chain_hash"]:
        raise SystemExit("pack chain hashes != canonical chain hash")
    if research.get("chain_fresh") is not True or \
            research.get("latest_evaluation_valid") is not True:
        raise SystemExit("pack chain_fresh/latest_evaluation_valid not true")
    if canon["campaign_id"] != ev["campaign_id"] or \
            goal_id != ev["goal_id"]:
        raise SystemExit("series/campaign/evaluation id triangle mismatch")

    wiki = live_wiki_check()

    record = json.loads((TICKET / "evaluation-record.json")
                        .read_text(encoding="utf-8"))
    record.update({
        "schema": record.get("schema", "agentos.ticket-evaluation-record/v1"),
        "ticket_id": "S1-007",
        "db_root": ".agentos-research/platform-stage-1",
        "research_revision": canon["research_revision"],
        "campaign_id": canon["campaign_id"],
        "goal_id": goal_id,
        "evaluation_id": ev["id"],
        "evaluation_version": ev["evaluation_version"],
        "result": ev["result"],
        # FULL 64-hex chain hash copied programmatically from the DB row
        "artifact_chain_hash": ev["artifact_chain_hash"],
        "evidence_pack": {
            "schema": "agentos.evidence-pack/v3",
            "path": tracked_pack.relative_to(ROOT).as_posix(),
            "canonical_runtime_path":
                (DB.parent / "goals" / goal_id / "evidence-pack.json")
                .as_posix(),
            "sha256": file_sha,
            "payload_sha256": p_sha,
            "chain_fresh": True,
            "latest_evaluation_valid": True,
        },
        "raw_observations_archive": {
            "schema": "agentos.s1-007.raw-observations/v1",
            "path": archive.relative_to(ROOT).as_posix(),
            "sha256": archive_sha,
            "member_count": member_count,
            "note": "byte-exact tracked copies of all run records plus "
                    "both run manifests and both timing artifacts; the "
                    "archive sha256 is also bound into the FLOW-11 bundle "
                    "(source RAW-OBSERVATIONS, claim c8-raw-archive) and "
                    "therefore into the evidence pack",
        },
        "wiki_check": {
            "ok": True,
            "files": wiki["files"],
            "links_checked": wiki["links_checked"],
            "issues": wiki["issues"],
        },
        "recorded_at": args.recorded_at,
        "recorded_corrective_round": args.corrective_round,
        "executed_at_commit": git_commit(),
        "note": args.supersedes_note,
    })
    (TICKET / "evaluation-record.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps({
        "record": "evaluation-record.json",
        "chain_hash_full": ev["artifact_chain_hash"],
        "pack_sha256": file_sha,
        "archive_sha256": archive_sha,
        "wiki_files": wiki["files"],
        "wiki_links": wiki["links_checked"],
        "equality_checks": "record == DB == pack (full 64-hex)",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
