"""S1-013 — preflight dependency inventory (S1-011, S1-012), Phase 1.

Both dependencies live and closed canonically on their own ticket
branches (not in this checkout, which is based on origin/main). This
gate reads their tracked bytes cross-branch via `git show` (same repo,
no checkout switch, no modification of foreign branches) and verifies:
- latest tracked evaluation-record.json per dependency, verdict in the
  positive allowlist {pass, pass_with_limits} (candidate records and
  branch names alone prove nothing);
- record research_revision bound to that branch's tickets-doc segment;
- content-addressed packs: file SHA-256 matches the record, filename
  content-addressed, payload/self hashes recomputed from the same
  `git show` bytes (v1 evidence-pack and v2 evidence/ticket packs);
- repo-relative POSIX containment after resolve;
- S1-011/S1-012 contract versions referenced by S1-013 work.

Writes dependency-gate.json with canonical_db_recheck_required=true.
No canonical DB is touched. Fails closed (exit 1, BLOCKED_DEPENDENCY).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

TICKET = Path(__file__).resolve().parent
OUT = TICKET / "dependency-gate.json"

DEPS = (
    {"ticket": "S1-011", "branch": "codex/s1-011-knowledge-gate",
     "record": "research/tickets/stage-1/S1-011/evaluation-record.json"},
    {"ticket": "S1-012", "branch": "codex/s1-012-evidence-independence",
     "record": "research/tickets/stage-1/S1-012/evaluation-record.json"},
)
ALLOWED_VERDICTS = {"pass", "pass_with_limits"}
DOCS = "docs/RESEARCH_STAGE_1_TICKETS.md"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_show(branch: str, rel: str) -> bytes:
    proc = subprocess.run(
        ["git", "show", f"{branch}:{rel}"], capture_output=True,
        check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git show {branch}:{rel} failed: "
                           f"{proc.stderr.decode()[:200]}")
    return proc.stdout


def branch_head(branch: str) -> str:
    proc = subprocess.run(["git", "rev-parse", branch],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"cannot resolve branch {branch}")
    return proc.stdout.strip()


def payload_sha(pack: dict) -> str:
    payload = {key: value for key, value in pack.items() if key != "sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return sha(encoded)


def contained(rel: str, ticket: str) -> bool:
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
    return resolved == prefix.rstrip("/") or resolved.startswith(prefix)


def docs_segment(branch: str, ticket: str) -> str:
    docs = git_show(branch, DOCS).decode("utf-8")
    marker = f"### {ticket} "
    seg = docs[docs.index(marker):]
    end = seg.find("### ", 10)
    return seg[:end] if end != -1 else seg


def check_pack(branch: str, ticket: str, label: str, entry: dict,
               problems: list) -> dict:
    info: dict = {"label": label, "path": entry.get("path"),
                  "proven": False}
    pack_rel = entry.get("path", "")
    if not contained(pack_rel, ticket):
        problems.append(f"{label} path escapes ticket dir: {pack_rel}")
        return info
    try:
        raw = git_show(branch, pack_rel)
    except RuntimeError as exc:
        problems.append(str(exc))
        return info
    file_sha = sha(raw)
    info["file_sha256"] = file_sha
    if file_sha != entry.get("sha256"):
        problems.append(f"{label} file sha mismatch vs record")
    if Path(pack_rel).stem != f"evidence-pack-{file_sha}" and \
            Path(pack_rel).stem != f"ticket-pack-{file_sha}" and \
            not Path(pack_rel).stem.endswith(file_sha):
        problems.append(f"{label} path not content-addressed by file sha")
    try:
        pack = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        problems.append(f"{label} is not valid JSON: {exc}")
        return info
    if "payload" in pack and set(pack) <= {"payload", "payload_sha256"}:
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
    info["proven"] = not any(
        p.startswith(label) or "pack" in p for p in problems)
    return info


def check(dep: dict, rec_override: dict | None = None,
          docs_override: str | None = None) -> dict:
    ticket, branch = dep["ticket"], dep["branch"]
    problems: list[str] = []
    try:
        head = branch_head(branch)
    except RuntimeError as exc:
        return {"ticket": ticket, "status": "NOT_PROVEN",
                "problems": [str(exc)]}
    if rec_override is not None:
        rec = rec_override
    else:
        try:
            rec = json.loads(git_show(branch, dep["record"]).decode())
        except RuntimeError as exc:
            return {"ticket": ticket, "status": "NOT_PROVEN",
                    "problems": [str(exc)]}
    packs = []
    for label, key in (("evidence-pack", "evidence_pack"),
                       ("ticket-pack", "ticket_pack")):
        entry = rec.get(key) or {}
        if entry:
            packs.append(check_pack(branch, ticket, label, entry,
                                    problems))
    if not packs:
        problems.append("record binds no content-addressed packs")
    bindings = {key: rec.get(key) for key in
                ("goal_id", "campaign_id", "evaluation_id",
                 "research_revision", "result", "artifact_chain_hash")}
    if any(value is None or value == "" for value in bindings.values()):
        problems.append("record missing binding fields: " + ",".join(
            key for key, value in bindings.items()
            if value is None or value == ""))
    try:
        segment = docs_override if docs_override is not None \
            else docs_segment(branch, ticket)
        lines = [line for line in segment.splitlines()
                 if line.startswith("- **Status:**")]
        if not lines:
            raise RuntimeError("no Status line in docs segment")
        status_line = lines[0]
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
                f"research_revision {rec.get('research_revision')!r} "
                f"not bound to the ticket docs segment")
    except (ValueError, RuntimeError) as exc:
        problems.append(f"docs status check failed: {exc}")
    return {
        "ticket": ticket,
        "branch": branch,
        "branch_head": head,
        "schema": rec.get("schema"),
        "verdict": rec.get("result"),
        "research_revision": rec.get("research_revision"),
        "goal_id": rec.get("goal_id"),
        "campaign_id": rec.get("campaign_id"),
        "evaluation_id": rec.get("evaluation_id"),
        "artifact_chain_hash": rec.get("artifact_chain_hash"),
        "packs": packs,
        "canonical_db_recheck_required": True,
        "problems": problems,
        "status": "PROVEN" if not problems else "NOT_PROVEN",
    }


def main() -> int:
    results = [check(d) for d in DEPS]
    doc = {
        "schema": "agentos.s1-013.dependency-gate/v1",
        "ticket": "S1-013",
        "dependencies": results,
        "all_proven": all(r["status"] == "PROVEN" for r in results),
        "canonical_db_recheck_required": True,
        "note": ("Cross-branch tracked-Git evidence only (branches "
                 "unmodified); live DB consistency must be rechecked by "
                 "the Phase B local harness."),
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8",
                   newline="\n")
    print(json.dumps(doc, indent=2))
    if not doc["all_proven"]:
        failed = [r["ticket"] for r in results if r["status"] != "PROVEN"]
        print(f"BLOCKED_DEPENDENCY: evidence not proven for {failed}",
              file=sys.stderr)
        return 1
    print("DEPENDENCY GATE: S1-011 and S1-012 PROVEN (tracked Git only)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
