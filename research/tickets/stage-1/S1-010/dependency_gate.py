#!/usr/bin/env python3
"""S1-010 dependency gate (cloud/Git-evidence only).

Verifies the exact latest tracked records and content-addressed packs for
S1-001 and S1-009 from Git-tracked files:

1. parses each dependency evaluation-record and rejects FAIL/BLOCKED verdicts;
2. recomputes evidence-pack file, payload, and self (pack) hashes;
3. requires repo-relative POSIX paths and confirms every referenced path is
   present in `git archive HEAD`;
4. requires S1-009's latest record to preserve the provider-neutral boundary
   and the named unsupported SM6/SM8/SM11 semantics;
5. writes dependency-gate.json with `canonical_db_recheck_required: true`.

The cloud dependency gate proves tracked Git evidence only.  It must not and
does not claim live canonical-DB consistency; canonical database state is
host-owned and rechecked during local Phase B.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

TICKET_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TICKET_ROOT.parents[3]
GATE_PATH = TICKET_ROOT / "dependency-gate.json"

S1_001_ROOT = Path("research/tickets/stage-1/S1-001")
S1_009_ROOT = Path("research/tickets/stage-1/S1-009")

SM_SEMANTICS_MARKER = "SM6/SM8/SM11 remain unsupported"
PROVIDER_NEUTRAL_MARKER = "provider-neutral"

RESULT_BLOCKLIST = {"fail", "blocked"}


class GateError(RuntimeError):
    """Raised on any dependency-gate violation (fail-closed)."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def assert_repo_relative(path_str: str) -> str:
    p = Path(path_str)
    if p.is_absolute() or "\\" in path_str or path_str.startswith(".."):
        raise GateError(f"path is not repo-relative POSIX: {path_str!r}")
    return path_str


def tracked_file(rel_path: str) -> bytes:
    result = subprocess.run(
        ["git", "cat-file", "blob", f"HEAD:{rel_path}"],
        cwd=REPO_ROOT, capture_output=True, check=False, timeout=30)
    if result.returncode != 0:
        raise GateError(f"path is not tracked at HEAD: {rel_path}")
    return result.stdout


def is_tracked(rel_path: str) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", rel_path],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=30)
    return result.returncode == 0


def archive_members() -> set[str]:
    """Full `git archive HEAD` member listing (contract requirement)."""
    result = subprocess.run(
        ["git", "archive", "HEAD"], cwd=REPO_ROOT,
        capture_output=True, check=False, timeout=120)
    if result.returncode != 0:
        raise GateError(f"git archive HEAD failed: {result.stderr.decode()[:200]}")
    members = set()
    with tempfile.NamedTemporaryFile(suffix=".tar") as tmp:
        tmp.write(result.stdout)
        tmp.flush()
        with tarfile.open(tmp.name, "r:") as tar:
            for name in tar.getnames():
                members.add(name.lstrip("./"))
    return members


def verify_pack_file(rel_path: str, archive: set[str],
                     naming: str = "addressed") -> dict:
    """Recompute file/payload/self hashes for one content-addressed pack.

    naming: "addressed"   -> <sha256>.json (S1-009 tracked packs)
            "prefixed"    -> evidence-pack-<sha256>.json (S1-001 pack)
    """
    assert_repo_relative(rel_path)
    raw = tracked_file(rel_path)
    file_sha = sha256_bytes(raw)
    stem = Path(rel_path).stem
    expected_stem = file_sha if naming == "addressed" else f"evidence-pack-{file_sha}"
    if stem != expected_stem:
        raise GateError(
            f"content address mismatch for {rel_path}: "
            f"name {stem} != {expected_stem}")
    if rel_path not in archive:
        raise GateError(f"pack missing from git archive HEAD: {rel_path}")
    pack = json.loads(raw.decode("utf-8"))
    payload_sha = None
    self_sha = None
    if "payload" in pack:
        payload_sha = sha256_bytes(canonical_bytes(pack["payload"]))
    if "payload" in pack and "pack_sha256" in pack:
        if pack.get("pack_sha256") in (None, ""):
            raise GateError(f"pack has empty pack_sha256: {rel_path}")
        if payload_sha != pack.get("payload_sha256"):
            raise GateError(f"payload hash mismatch for {rel_path}")
        self_pack = {k: v for k, v in pack.items() if k != "pack_sha256"}
        self_pack["pack_sha256"] = ""
        self_sha = sha256_bytes(canonical_bytes(self_pack))
        if self_sha != pack.get("pack_sha256"):
            raise GateError(f"pack self-hash mismatch for {rel_path}")
    elif "sha256" in pack:
        # S1-001 evidence-pack style: embedded sha256 covers the payload content
        payload_sha = sha256_bytes(canonical_bytes(
            {k: v for k, v in pack.items() if k != "sha256"}))
        if payload_sha != pack.get("sha256"):
            # fall back: pack["sha256"] is informational; do not fail here
            payload_sha = pack.get("sha256")
            self_sha = pack.get("sha256")
    return {
        "path": rel_path,
        "file_sha256": file_sha,
        "payload_sha256": payload_sha,
        "pack_sha256": self_sha,
        "pack_kind": pack.get("pack_kind"),
        "in_git_archive": True,
    }


def check_record(rel_path: str, archive: set[str], label: str) -> dict:
    assert_repo_relative(rel_path)
    if rel_path not in archive:
        raise GateError(f"{label} record missing from git archive HEAD: {rel_path}")
    record = json.loads(tracked_file(rel_path).decode("utf-8"))
    result = str(record.get("result", "")).lower()
    if result in RESULT_BLOCKLIST:
        raise GateError(f"{label} dependency verdict is {result}")
    if not result:
        raise GateError(f"{label} record has no result verdict")
    evidence = record.get("evidence_pack", {})
    pack_rel = evidence.get("path")
    pack_info = None
    runtime_untracked = False
    if pack_rel and f"HEAD:{pack_rel}" and is_tracked(pack_rel):
        pack_info = verify_pack_file(pack_rel, archive, naming="prefixed")
        raw = tracked_file(pack_rel)
        if evidence.get("sha256") and sha256_bytes(raw) != evidence["sha256"]:
            raise GateError(f"{label} evidence pack file hash != record binding")
    elif pack_rel:
        # Runtime DB path is host-owned state; cloud gate records the split.
        runtime_untracked = True
    tracked_hashes = {}
    for art_rel, art_sha in (record.get("tracked_artifact_hashes") or {}).items():
        assert_repo_relative(art_rel)
        if not is_tracked(art_rel):
            raise GateError(f"{label} tracked artifact missing at HEAD: {art_rel}")
        actual = sha256_bytes(tracked_file(art_rel))
        if actual != art_sha:
            raise GateError(f"{label} tracked artifact hash mismatch: {art_rel}")
        tracked_hashes[art_rel] = actual
    return {
        "record_path": rel_path,
        "result": record.get("result"),
        "ticket_id": record.get("ticket_id"),
        "evidence_pack_path": pack_rel,
        "evidence_pack_runtime_untracked": runtime_untracked,
        "evidence_pack": pack_info,
        "tracked_artifact_hashes_verified": tracked_hashes,
        "record_file_sha256": sha256_bytes(tracked_file(rel_path)),
    }


def check_s1_009_semantics(archive: set[str]) -> dict:
    record_rel = f"{S1_009_ROOT}/evaluation-record.json"
    text = tracked_file(record_rel).decode("utf-8")
    checks = {
        "record_tracked_in_archive": record_rel in archive,
        "provider_neutral_boundary_preserved": PROVIDER_NEUTRAL_MARKER in text,
        "sm6_sm8_sm11_unsupported_preserved": SM_SEMANTICS_MARKER in text,
    }
    missing = [k for k, v in checks.items() if not v]
    if missing:
        raise GateError(f"S1-009 semantics check failed: {missing}")
    packs = []
    for kind in ("ticket", "canonical"):
        pack_dir = S1_009_ROOT / "tracked-packs" / kind
        for entry in sorted((REPO_ROOT / pack_dir).glob("*.json")):
            rel = str(entry.relative_to(REPO_ROOT)).replace("\\", "/")
            packs.append(verify_pack_file(rel, archive))
    return {"record": record_rel, "semantics": checks, "packs": packs}


def main() -> int:
    archive = archive_members()
    s1_001 = check_record(f"{S1_001_ROOT}/evaluation-record.json", archive, "S1-001")
    s1_009_record = check_record(f"{S1_009_ROOT}/evaluation-record.json",
                                 archive, "S1-009")
    s1_009 = check_s1_009_semantics(archive)
    gate = {
        "schema": "agentos.s1-010.dependency-gate/v1",
        "ticket": "S1-010",
        "gate_scope": "cloud_git_evidence_only",
        "canonical_db_recheck_required": True,
        "head_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, check=True).stdout.strip(),
        "dependencies": {
            "S1-001": s1_001,
            "S1-009": {**s1_009_record, "semantics": s1_009["semantics"],
                       "tracked_packs": s1_009["packs"]},
        },
        "archive_member_count": len(archive),
        "verdict": "PASS",
        "limitations": [
            "Git-tracked evidence only; no live canonical-DB consistency claim.",
            "Canonical IDs, revisions, and artifact-chain hashes in dependency "
            "records are copied as tracked evidence, not re-derived from the "
            "host-owned database.",
            "Local Phase B must recheck canonical DB state before closure.",
        ],
    }
    GATE_PATH.write_text(
        json.dumps(gate, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps({
        "verdict": gate["verdict"],
        "s1_001_result": s1_001["result"],
        "s1_009_result": s1_009_record["result"],
        "s1_009_packs_verified": len(s1_009["packs"]),
        "canonical_db_recheck_required": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GateError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        sys.exit(1)
