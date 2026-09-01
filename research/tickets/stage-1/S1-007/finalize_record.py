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
from datetime import datetime, timezone
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


def _one(items: list[dict], description: str) -> dict:
    if len(items) != 1:
        raise SystemExit(f"expected exactly one {description}, found "
                         f"{len(items)}")
    return items[0]


def _binding(source: dict, description: str) -> dict:
    if source.get("verification_method") != \
            "content-addressed-archive-sha256-binding":
        raise SystemExit(f"{description}: wrong verification method")
    provenance = source.get("verifier_provenance")
    if not isinstance(provenance, dict):
        raise SystemExit(f"{description}: verifier provenance missing")
    path = provenance.get("path")
    digest = provenance.get("file_sha256")
    alias_digest = provenance.get("sha256")
    member_count = provenance.get("member_count")
    if not isinstance(path, str) or not path:
        raise SystemExit(f"{description}: archive path missing")
    if not isinstance(digest, str) or len(digest) != 64 or \
            digest.lower() != digest:
        raise SystemExit(f"{description}: invalid archive sha256")
    if alias_digest != digest:
        raise SystemExit(f"{description}: sha256 aliases disagree")
    if not isinstance(member_count, int) or isinstance(member_count, bool) \
            or member_count <= 0:
        raise SystemExit(f"{description}: invalid member count")
    return {"path": path, "sha256": digest,
            "member_count": member_count}


def resolve_archive_binding(pack: dict, bundle: dict) -> dict:
    """Resolve the archive only through matching structured bindings.

    The local evidence directory is never searched for an arbitrary sole
    archive.  Both the pre-ingestion FLOW-11 bundle and the canonical pack
    must name the same path, SHA-256 and member count, after which the file
    and every member are verified from disk.
    """
    bundle_source = _one(
        [s for s in bundle.get("sources", [])
         if s.get("id") == "RAW-OBSERVATIONS"],
        "bundle RAW-OBSERVATIONS source")
    pack_source = _one(
        [s for s in (pack.get("research") or {}).get("sources", [])
         if s.get("verification_method") ==
         "content-addressed-archive-sha256-binding"],
        "pack raw-observations source")
    bundle_binding = _binding(bundle_source, "bundle archive binding")
    pack_binding = _binding(pack_source, "pack archive binding")
    if bundle_binding != pack_binding:
        raise SystemExit("bundle and pack archive bindings disagree")

    archive = (ROOT / pack_binding["path"]).resolve()
    evidence_dir = (TICKET / "results" / "evidence").resolve()
    if not archive.is_relative_to(evidence_dir) or not archive.is_file():
        raise SystemExit("bound archive path escapes evidence directory or "
                         "does not exist")
    raw = archive.read_bytes()
    actual_sha = sha(raw)
    if actual_sha != pack_binding["sha256"] or \
            archive.name != f"raw-observations-{actual_sha}.json":
        raise SystemExit("bound archive bytes/name do not match sha256")
    archive_doc = json.loads(raw.decode("utf-8"))
    if archive_doc.get("schema") != "agentos.s1-007.raw-observations/v1":
        raise SystemExit("bound archive schema mismatch")
    members = archive_doc.get("members")
    member_hashes = archive_doc.get("member_sha256")
    if not isinstance(members, dict) or not isinstance(member_hashes, dict) \
            or set(members) != set(member_hashes):
        raise SystemExit("archive member/hash key sets disagree")
    if archive_doc.get("member_count") != len(members) or \
            len(members) != pack_binding["member_count"]:
        raise SystemExit("archive member counts disagree")
    for name, member in members.items():
        if not isinstance(member, str) or \
                sha(member.encode("utf-8")) != member_hashes[name]:
            raise SystemExit(f"archive member digest mismatch: {name}")
    return pack_binding


def derive_decision(record: dict, evaluation: dict, pack: dict) -> dict:
    """Build all revision-sensitive decision fields from current evidence."""
    winner = evaluation.get("winner")
    scores = evaluation.get("scores_normalized")
    sensitivity = evaluation.get("sensitivity")
    probes = evaluation.get("probe_rejections")
    if winner not in {"per_scope", "shared_rls"}:
        raise SystemExit("evaluator winner missing or invalid")
    if not isinstance(scores, dict) or set(scores) != \
            {"per_scope", "shared_rls"} or any(
                not isinstance(v, (int, float)) or isinstance(v, bool)
                or not 0 <= v <= 4 for v in scores.values()):
        raise SystemExit("evaluator scores missing or invalid")
    if not isinstance(sensitivity, dict) or \
            sensitivity.get("total_perturbations_executed") != \
            sensitivity.get("oat_perturbations_executed", 0) + \
            sensitivity.get("random_vectors", 0):
        raise SystemExit("evaluator sensitivity counts inconsistent")
    if sensitivity.get("winner_stable") is not \
            (sensitivity.get("flip_count") == 0):
        raise SystemExit("evaluator sensitivity verdict inconsistent")
    expected_probes = {
        "A_existence_oracle", "B_stale_cache", "C_postfilter",
        "D_forged_scope_provenance_loss"}
    if not isinstance(probes, dict) or set(probes) != expected_probes:
        raise SystemExit("evaluator probe result set incomplete")
    for name, result in probes.items():
        if result.get("detected") != result.get("expected"):
            raise SystemExit(f"probe verdict mismatch: {name}")

    decision_claim = _one(
        [c for c in (pack.get("research") or {}).get("claims", [])
         if "QA3 decision:" in c.get("text", "")],
        "pack QA3 decision claim")
    claim_text = decision_claim["text"]
    required_tokens = [winner,
                       f"{scores['per_scope']:.4f}",
                       f"{scores['shared_rls']:.4f}",
                       str(sensitivity["total_perturbations_executed"]),
                       f"{sensitivity['flip_count']} winner flips"]
    missing = [token for token in required_tokens if token not in claim_text]
    if missing:
        raise SystemExit(f"pack decision claim disagrees with evaluator: "
                         f"missing {missing}")

    previous = record.get("decision")
    if not isinstance(previous, dict):
        previous = {}
    decision = {
        "question": previous.get(
            "question", "QA3 retrieval/index isolation: per-scope index "
            "versus shared index with row-level retrieval filtering "
            "(shared-RLS)"),
        "winner": winner,
        "recommendation": (
            "per-scope index projections bound to the canonical "
            "(tenant, workspace, goal) scope with frozen cache/epoch "
            "invalidation semantics" if winner == "per_scope" else
            "shared index with row-level retrieval filtering under the "
            "frozen isolation contract"),
        "scores_normalized": dict(scores),
        "sensitivity": {
            "total_perturbations_executed":
                sensitivity["total_perturbations_executed"],
            "oat_perturbations_executed":
                sensitivity["oat_perturbations_executed"],
            "random_vectors": sensitivity["random_vectors"],
            "random_seed": sensitivity["random_seed"],
            "flip_count": sensitivity["flip_count"],
            "winner_stable": sensitivity["winner_stable"],
            "policy": sensitivity["policy"],
        },
        "probes": {
            name: {"detected": value["detected"],
                   "expected": value["expected"],
                   "iso": value["iso"]}
            for name, value in sorted(probes.items())},
        "per_variant_evidence": previous.get("per_variant_evidence", {}),
        "migration_trigger": previous.get("migration_trigger"),
        "non_goals": previous.get("non_goals"),
        "source": {
            "path": "research/tickets/stage-1/S1-007/results/"
                    "sensitivity-analysis.json",
            "sha256": sha((TICKET / "results" /
                           "sensitivity-analysis.json").read_bytes()),
            "pack_claim_id": decision_claim["id"],
        },
    }
    return decision


def canonical_recorded_at(evaluation_created_at: str,
                          now: datetime | None = None) -> str:
    try:
        evaluated = datetime.fromisoformat(
            evaluation_created_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise SystemExit("canonical evaluation created_at is invalid") from exc
    if evaluated.tzinfo is None:
        raise SystemExit("canonical evaluation created_at lacks timezone")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise SystemExit("record finalization time lacks timezone")
    current = current.astimezone(timezone.utc)
    if current < evaluated.astimezone(timezone.utc):
        raise SystemExit("record finalization time predates evaluation")
    return current.isoformat(timespec="milliseconds").replace("+00:00", "Z")


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
        " evaluation_version, created_at FROM research_evaluation"
        " WHERE campaign_id=?"
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

    bundle = json.loads((TICKET / "bundle.json").read_text(encoding="utf-8"))
    archive_binding = resolve_archive_binding(pack, bundle)
    archive_sha = archive_binding["sha256"]
    member_count = archive_binding["member_count"]

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
    evaluation = json.loads((TICKET / "results" /
                             "sensitivity-analysis.json")
                            .read_text(encoding="utf-8"))
    if evaluation.get("verdict", "").lower() != ev["result"]:
        raise SystemExit("evaluator verdict disagrees with canonical DB")
    decision = derive_decision(record, evaluation, pack)
    finalized_from_commit = git_commit()
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
            "path": archive_binding["path"],
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
        "decision": decision,
        "recorded_at": canonical_recorded_at(ev["created_at"]),
        "recorded_corrective_round": args.corrective_round,
        "executed_at_commit": evaluation["commit"],
        "experiment_commit": evaluation["commit"],
        "record_finalized_from_commit": finalized_from_commit,
        "note": args.supersedes_note,
    })
    record_path = TICKET / "evaluation-record.json"
    record_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    if json.loads(record_path.read_text(encoding="utf-8")) != record:
        raise SystemExit("written evaluation record did not round-trip")
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
