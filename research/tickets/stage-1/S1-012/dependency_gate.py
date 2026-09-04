"""S1-012 — preflight dependency gate (S1-001, S1-003, S1-011), Phase A.

Ports the S1-011 gate structure to three dependencies and both record
schemas (v1 evidence-pack-only; v2 evidence-pack + ticket-pack).
Verifies from actual bytes, never narrative:
- latest tracked evaluation-record.json per dependency, verdict in the
  positive allowlist {pass, pass_with_limits};
- record research_revision bound to the ticket's docs segment;
- tracked content-addressed packs: file SHA-256 matches the record,
  filename content-addressed, payload/self hashes recomputed
  (v1: pack minus "sha256"; v2 ticket-pack: canonical "payload");
- repo-relative POSIX paths with containment after resolve (no
  traversal, absolute, drive, UNC or symlink escape);
- same bytes from a clean `git archive HEAD` (no .git, no live DB);
- S1-011 semantic carries present: knowledge-gate-contract.json,
  state-machine.json, knowledge-record.schema.json, results/decision.md,
  results/CORRECTIVE_R3.md, docs/S1-011_CLOSURE.md (consumed, never
  rewritten here).

Phase A proves tracked Git evidence only: canonical_db_recheck_required
is always true; chain_fresh is never asserted. Fails closed (exit 1,
BLOCKED); writes dependency-gate.json.
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
TICKET_REL = Path("research/tickets/stage-1/S1-012")
DOCS = ROOT / "docs" / "RESEARCH_STAGE_1_TICKETS.md"
OUT = TICKET / "dependency-gate.json"

DEPS = ("S1-001", "S1-003", "S1-011")
ALLOWED_VERDICTS = {"pass", "pass_with_limits"}
S1_011_CARRIES = (
    "knowledge-gate-contract.json",
    "state-machine.json",
    "knowledge-record.schema.json",
    "results/decision.md",
    "results/CORRECTIVE_R3.md",
)


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


def contained(rel: str, ticket: str) -> bool:
    """POSIX repo-relative containment after resolve (Windows/UNC/symlink
    safe): rejects absolute, drive-qualified, UNC and escaping paths."""
    if not rel or not isinstance(rel, str):
        return False
    text = rel.replace("\\", "/")
    if text.startswith("/") or text.startswith("//"):
        return False
    if re.match(r"^[A-Za-z]:", text):
        return False
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return False
    prefix = f"research/tickets/stage-1/{ticket}/"
    resolved = "/".join(parts)
    if not (resolved == prefix.rstrip("/") or
            resolved.startswith(prefix)):
        return False
    try:
        root = ROOT.resolve()
        target = (root / Path(*parts)).resolve()
        target.relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def docs_segment(ticket: str) -> str:
    docs = DOCS.read_text(encoding="utf-8")
    marker = f"### {ticket} "
    seg = docs[docs.index(marker):]
    end = seg.find("### ", 10)
    return seg[:end] if end != -1 else seg


def check_pack(ticket: str, label: str, entry: dict,
               problems: list) -> dict:
    """Verify one content-addressed pack entry. Returns proof fields."""
    info: dict = {"label": label, "path": entry.get("path"),
                  "proven": False}
    pack_rel = entry.get("path", "")
    if not contained(pack_rel, ticket):
        problems.append(f"{label} path escapes ticket dir: {pack_rel}")
        return info
    pack_path = ROOT / Path(*pack_rel.replace("\\", "/").split("/"))
    if not pack_path.is_file():
        problems.append(f"tracked pack missing: {pack_rel}")
        return info
    if not git_tracked(pack_rel.replace("\\", "/")):
        problems.append(f"pack not git-tracked: {pack_rel}")
    raw = pack_path.read_bytes()
    file_sha = sha(raw)
    info["file_sha256"] = file_sha
    if file_sha != entry.get("sha256"):
        problems.append(f"{label} file sha mismatch vs record")
    stem = Path(pack_rel).stem
    if not stem.endswith(file_sha):
        problems.append(f"{label} path not content-addressed by file sha")
    try:
        pack = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        problems.append(f"{label} is not valid JSON: {exc}")
        return info
    if "payload" in pack and set(pack) <= {"payload", "payload_sha256"}:
        # v2 ticket-pack shape: payload hash binds canonical payload.
        computed = sha(json.dumps(
            pack["payload"], sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode("utf-8"))
        info["payload_sha256"] = computed
        if computed != entry.get("payload_sha256"):
            problems.append(f"{label} payload bytes mismatch")
        if pack.get("payload_sha256") != entry.get("payload_sha256"):
            problems.append(f"{label} payload sha field mismatch")
    else:
        computed = payload_sha(pack)
        info["payload_sha256"] = computed
        if pack.get("sha256") != entry.get("payload_sha256"):
            problems.append(f"{label} payload sha field mismatch")
        if computed != entry.get("payload_sha256"):
            problems.append(f"{label} payload bytes mismatch")
    try:
        if sha(archive_bytes(pack_rel.replace("\\", "/"))) != file_sha:
            problems.append(f"{label} git archive bytes differ")
        else:
            info["archive_reproducible"] = True
    except RuntimeError as exc:
        problems.append(str(exc))
    info["proven"] = not any(
        p.startswith(label) or "pack" in p for p in problems)
    return info


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

    packs = []
    evidence = rec.get("evidence_pack") or {}
    if evidence:
        packs.append(check_pack(ticket, "evidence-pack", evidence, problems))
    ticket_pack = rec.get("ticket_pack") or {}
    if ticket_pack:
        packs.append(check_pack(ticket, "ticket-pack", ticket_pack, problems))
    if not packs:
        problems.append("record binds no content-addressed packs")

    # goal/campaign/evaluation/revision/result/chain bindings present.
    bindings = {key: rec.get(key) for key in
                ("goal_id", "campaign_id", "evaluation_id",
                 "research_revision", "result", "artifact_chain_hash")}
    if any(value is None or value == "" for value in bindings.values()):
        problems.append("record missing binding fields: " + ",".join(
            key for key, value in bindings.items()
            if value is None or value == ""))

    try:
        if docs_override is not None:
            segment = docs_override
            lines = [line for line in segment.splitlines()
                     if line.startswith("- **Status:**")]
            if not lines:
                raise RuntimeError("no Status line in docs override")
            status_line = lines[0]
        else:
            segment = docs_segment(ticket)
            status_line = next(
                line for line in segment.splitlines()
                if line.startswith("- **Status:**"))
        verdict = rec.get("result") or ""
        if verdict not in ALLOWED_VERDICTS:
            problems.append(
                f"dependency verdict {verdict!r} not in positive "
                f"allowlist; FAIL/BLOCKED can never be PROVEN")
        elif f"`{verdict.upper()}`" not in status_line:
            problems.append(
                f"docs status does not record {verdict.upper()}: "
                f"{status_line[:120]}")
        mentioned = set(re.findall(r"[Rr]evision\s+(\d+)", segment))
        if str(rec.get("research_revision")) not in mentioned:
            problems.append(
                f"research_revision {rec.get('research_revision')!r} not "
                f"bound to the ticket docs segment")
    except (ValueError, RuntimeError) as exc:
        problems.append(f"docs status check failed: {exc}")

    carries: list[str] = []
    if ticket == "S1-011":
        for name in S1_011_CARRIES:
            rel = f"research/tickets/stage-1/S1-011/{name}"
            path = ROOT / rel
            if not path.is_file() or not git_tracked(rel):
                problems.append(f"S1-011 carry missing/untracked: {name}")
            else:
                carries.append(name)
        closure = ROOT / "docs/S1-011_CLOSURE.md"
        if not closure.is_file():
            problems.append("docs/S1-011_CLOSURE.md missing")
        else:
            carries.append("docs/S1-011_CLOSURE.md")
    if ticket == "S1-003" and rec.get("result") != "pass":
        problems.append("S1-003 record verdict is not pass")

    return {
        "ticket": ticket,
        "schema": rec.get("schema"),
        "verdict": rec.get("result"),
        "research_revision": rec.get("research_revision"),
        "goal_id": rec.get("goal_id"),
        "campaign_id": rec.get("campaign_id"),
        "evaluation_id": rec.get("evaluation_id"),
        "artifact_chain_hash": rec.get("artifact_chain_hash"),
        "packs": packs,
        "carries": carries,
        "canonical_db_recheck_required": True,
        "problems": problems,
        "status": "PROVEN" if not problems else "NOT_PROVEN",
    }


def main() -> int:
    results = [check(t) for t in DEPS]
    doc = {
        "schema": "agentos.s1-012.dependency-gate/v1",
        "ticket": "S1-012",
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
    print("DEPENDENCY GATE: S1-001, S1-003 and S1-011 PROVEN "
          "(tracked Git only)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
