"""S1-011 — preflight dependency gate (S1-001, S1-003), Phase A.

Verifies, from actual bytes rather than narrative:
- exact latest tracked evaluation-record.json exists per dependency;
- tracked content-addressed pack exists, is git-tracked, its file SHA-256
  matches the record, and the filename is content-addressed by that hash;
- pack payload self-hash (pack minus "sha256") matches payload_sha256;
- repo-relative paths stay inside the ticket dir (no traversal);
- bytes reproduce from a clean `git archive HEAD` (no .git, no live DB);
- record verdict is in the positive allowlist {pass, pass_with_limits}
  (a FAIL/BLOCKED dependency can never be PROVEN) and matches
  docs/RESEARCH_STAGE_1_TICKETS.md;
- record research_revision is bound to the ticket's docs segment (the
  revision number must be stated there, not just copied from the record);
- S1-003 executable SHACL lifecycle semantics still PASS with the expected
  proposed/promoted/rejected/superseded/revoked fixture states present.

Phase A proves tracked Git evidence only. It never claims live DB
consistency: canonical_db_recheck_required is always true and chain_fresh is
never asserted (Phase B local harness rechecks against the canonical DB).

Fails closed (exit 1, BLOCKED) and stores the machine-readable result in
dependency-gate.json.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TICKET = Path(__file__).resolve().parent
TICKET_REL = Path("research/tickets/stage-1/S1-011")
DOCS = ROOT / "docs" / "RESEARCH_STAGE_1_TICKETS.md"
OUT = TICKET / "dependency-gate.json"

DEPS = ("S1-001", "S1-003")
# Lifecycle states the S1-003 fixtures must expose (dependency gate §4.5).
S1_003_LIFECYCLE_STATES = {
    "proposed", "promoted", "rejected", "superseded", "revoked",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def payload_sha(pack: dict) -> str:
    payload = {key: value for key, value in pack.items() if key != "sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return sha(encoded)


def git_tracked(rel: str) -> bool:
    proc = subprocess.run(
        ["git", "ls-files", "--", rel], cwd=ROOT, capture_output=True,
        text=True, check=False)
    return proc.returncode == 0 and rel in proc.stdout.split()


def archive_bytes(rel: str) -> bytes:
    """Read exact committed bytes of rel from a clean `git archive HEAD`."""
    proc = subprocess.run(
        ["git", "archive", "HEAD", "--", rel], cwd=ROOT, capture_output=True,
        check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git archive failed for {rel}: "
                           f"{proc.stderr.decode()[:200]}")
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
        member = tar.extractfile(rel)
        if member is None:
            raise RuntimeError(f"{rel} missing from git archive HEAD")
        return member.read()


def docs_segment(ticket: str) -> str:
    docs = DOCS.read_text(encoding="utf-8")
    marker = f"### {ticket} "
    seg = docs[docs.index(marker):]
    end = seg.find("### ", 10)
    return seg[:end] if end != -1 else seg


def docs_status(ticket: str) -> str:
    seg = docs_segment(ticket)
    for line in seg.splitlines():
        if line.startswith("- **Status:**"):
            return line
    raise RuntimeError(f"no Status line for {ticket} in tickets doc")


ALLOWED_VERDICTS = {"pass", "pass_with_limits"}


def check(ticket: str, rec_override: dict | None = None,
          docs_override: str | None = None) -> dict:
    problems: list[str] = []
    rec_path = ROOT / "research/tickets/stage-1" / ticket / "evaluation-record.json"
    if rec_override is not None:
        rec = rec_override
    else:
        if not rec_path.is_file():
            return {"ticket": ticket, "status": "NOT_PROVEN",
                    "problems": [f"evaluation-record.json missing: {rec_path}"]}
        if not git_tracked(f"research/tickets/stage-1/{ticket}/evaluation-record.json"):
            problems.append("evaluation-record.json not git-tracked")
        rec = json.loads(rec_path.read_text(encoding="utf-8"))

    evidence = rec.get("evidence_pack") or {}
    pack_rel = evidence.get("path", "")
    pack_path = ROOT / pack_rel if pack_rel else None
    if not pack_rel or pack_path is None or not pack_path.is_file():
        problems.append(f"tracked pack missing: {pack_rel}")
        pack = None
        file_sha = None
    else:
        if ".." in Path(pack_rel).parts or not pack_rel.startswith(
                f"research/tickets/stage-1/{ticket}/"):
            problems.append(f"pack path escapes ticket dir: {pack_rel}")
        if not git_tracked(pack_rel):
            problems.append(f"pack not git-tracked: {pack_rel}")
        raw = pack_path.read_bytes()
        file_sha = sha(raw)
        if file_sha != evidence.get("sha256"):
            problems.append("pack file sha mismatch vs record")
        if Path(pack_rel).name != f"evidence-pack-{evidence.get('sha256')}.json":
            problems.append("pack path is not content-addressed by file sha")
        try:
            pack = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            pack = None
            problems.append(f"pack is not valid JSON: {exc}")
        if pack is not None:
            if pack.get("sha256") != evidence.get("payload_sha256"):
                problems.append("pack payload sha field mismatch")
            if payload_sha(pack) != evidence.get("payload_sha256"):
                problems.append("pack payload bytes mismatch")
        try:
            archived = archive_bytes(pack_rel)
            if sha(archived) != file_sha:
                problems.append("git archive HEAD bytes differ from worktree")
        except RuntimeError as exc:
            problems.append(str(exc))

    try:
        if docs_override is not None:
            segment = docs_override
            status_lines = [line for line in segment.splitlines()
                            if line.startswith("- **Status:**")]
            if not status_lines:
                raise RuntimeError("no Status line in docs override")
            status_line = status_lines[0]
        else:
            status_line = docs_status(ticket)
            segment = docs_segment(ticket)
        verdict = rec.get("result") or ""
        if verdict not in ALLOWED_VERDICTS:
            problems.append(
                f"dependency verdict {verdict!r} not in positive "
                f"allowlist; FAIL/BLOCKED can never be PROVEN")
        elif f"`{verdict.upper()}`" not in status_line:
            problems.append(
                f"docs status does not record {verdict.upper()}: "
                f"{status_line[:120]}")
        revision = rec.get("research_revision")
        mentioned = set(re.findall(r"[Rr]evision\s+(\d+)", segment))
        if str(revision) not in mentioned:
            problems.append(
                f"research_revision {revision!r} not bound to the "
                f"ticket docs segment")
    except (ValueError, RuntimeError) as exc:
        problems.append(f"docs status check failed: {exc}")

    if ticket == "S1-003":
        if rec.get("result") != "pass":
            problems.append("S1-003 record verdict is not pass")
        fixtures_path = ROOT / "research/tickets/stage-1/S1-003/fixtures.json"
        try:
            fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
            lifecycle = fixtures.get("expected_lifecycle_states") or {}
            union = set()
            for states in lifecycle.values():
                union.update(states)
            missing = S1_003_LIFECYCLE_STATES - union
            if missing:
                problems.append(
                    f"S1-003 lifecycle states missing: {sorted(missing)}")
        except (OSError, ValueError) as exc:
            problems.append(f"S1-003 fixtures unreadable: {exc}")

    return {
        "ticket": ticket,
        "verdict": rec.get("result"),
        "research_revision": rec.get("research_revision"),
        "pack_path": pack_rel,
        "pack_sha256": evidence.get("sha256"),
        "payload_sha256": evidence.get("payload_sha256"),
        "self_hash_ok": pack is not None and pack.get("sha256") == evidence.get(
            "payload_sha256") and payload_sha(pack) == evidence.get("payload_sha256"),
        "git_tracked": git_tracked(pack_rel) if pack_rel else False,
        "archive_reproducible": not any(
            "git archive" in p for p in problems),
        "canonical_db_recheck_required": True,
        "problems": problems,
        "status": "PROVEN" if not problems else "NOT_PROVEN",
    }


def main() -> int:
    results = [check(t) for t in DEPS]
    doc = {
        "schema": "agentos.s1-011.dependency-gate/v1",
        "ticket": "S1-011",
        "dependencies": results,
        "all_proven": all(r["status"] == "PROVEN" for r in results),
        "canonical_db_recheck_required": True,
        "note": ("Cloud/worktree gate proves tracked Git evidence only; "
                 "live DB consistency must be rechecked by the Phase B "
                 "local harness."),
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8",
                   newline="\n")
    print(json.dumps(doc, indent=2))
    if not doc["all_proven"]:
        failed = [r["ticket"] for r in results if r["status"] != "PROVEN"]
        print(f"BLOCKED: dependency evidence not proven for {failed}",
              file=sys.stderr)
        return 1
    print("DEPENDENCY GATE: S1-001 and S1-003 PROVEN (tracked Git only)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
