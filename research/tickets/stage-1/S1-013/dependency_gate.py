"""S1-013 dependency gate for the S1-011 and S1-012 evidence chains.

The gate is deliberately a verifier, not a record normaliser.  A record read
from a caller (``rec_override`` is used by adversarial tests) never supplies
identity, status, or chain values.  The authoritative record and its packs are
read from an immutable, portable Git ref and all of the nested bindings are
cross-checked before ``PROVEN`` can be returned.

Only tracked bytes are checked here.  A later local operator pass still has to
recheck the canonical database; that fact is carried in the generated gate.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

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
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
BRANCH = re.compile(r"^[A-Za-z0-9._/-]+$")
RECORD_SCHEMA = "agentos.ticket-evaluation-record/v2"
EVIDENCE_SCHEMA = "agentos.evidence-pack/v3"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def git_run(args: list[str], *, text: bool = False) -> subprocess.CompletedProcess:
    """Run a bounded Git read with no shell interpolation."""
    return subprocess.run(["git", *args], capture_output=True, text=text,
                          check=False)


def git_show(branch: str, rel: str) -> bytes:
    if not BRANCH.fullmatch(branch or ""):
        raise RuntimeError("invalid dependency Git ref")
    if not rel or "\x00" in rel or rel.startswith("-"):
        raise RuntimeError("invalid dependency Git path")
    proc = git_run(["show", f"{branch}:{rel}"])
    if proc.returncode != 0:
        raise RuntimeError(f"git show {branch}:{rel} failed: "
                           f"{proc.stderr.decode(errors='replace')[:200]}")
    return proc.stdout


def _rev(ref: str) -> str | None:
    if not BRANCH.fullmatch(ref or ""):
        return None
    proc = git_run(["rev-parse", "--verify", ref], text=True)
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip().lower()
    return value if SHA40.fullmatch(value) else None


def branch_head(branch: str) -> str:
    """Return a portable immutable head, refusing local-only refs.

    A local branch can be recreated or silently advanced by a caller.  The
    dependency must therefore have a matching ``origin/<branch>`` ref and the
    two refs must resolve to the same commit object.
    """
    local = _rev(f"refs/heads/{branch}")
    remote = _rev(f"refs/remotes/origin/{branch}")
    if not remote:
        raise RuntimeError(f"dependency branch {branch} has no portable "
                           "origin ref")
    if local and local != remote:
        raise RuntimeError(f"dependency branch {branch} diverges from its "
                           "portable origin ref")
    proc = git_run(["cat-file", "-t", remote], text=True)
    if proc.returncode != 0 or proc.stdout.strip() != "commit":
        raise RuntimeError(f"dependency ref {branch} is not an immutable "
                           "commit")
    return remote


def payload_sha(pack: dict) -> str:
    payload = {key: value for key, value in pack.items() if key != "sha256"}
    return sha(canonical(payload))


def contained(rel: str, ticket: str) -> bool:
    """Return true only for a canonical repo-relative POSIX ticket path."""
    if not isinstance(rel, str) or not rel or "\\" in rel:
        return False
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        return False
    parts = rel.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    prefix = f"research/tickets/stage-1/{ticket}/"
    return rel.startswith(prefix) and len(rel) > len(prefix)


def docs_segment(branch: str, ticket: str) -> str:
    docs = git_show(branch, DOCS).decode("utf-8")
    marker = f"### {ticket} "
    start = docs.find(marker)
    if start < 0:
        raise RuntimeError(f"missing {ticket} section")
    segment = docs[start:]
    end = segment.find("### ", len(marker))
    return segment[:end] if end != -1 else segment


def _record_id(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\x00" not in value


def _check_hash(value: Any, label: str, problems: list[str]) -> None:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        problems.append(f"{label} is not a lowercase SHA-256")


def _pack_path_ok(pack_rel: Any, ticket: str, label: str,
                  problems: list[str]) -> bool:
    if not contained(pack_rel, ticket):
        problems.append(f"{label} path escapes ticket dir: {pack_rel}")
        return False
    return True


def check_pack(branch: str, ticket: str, label: str, entry: dict,
               problems: list[str]) -> dict:
    """Verify file, filename, JSON and payload digests for one pack.

    The returned ``document`` is intentionally retained for the caller's
    schema-specific binding checks; it is not copied into the public gate.
    """
    if not isinstance(entry, dict):
        problems.append(f"{label} entry is not an object")
        return {"label": label, "path": None, "proven": False,
                "document": None}
    pack_rel = entry.get("path")
    info: dict[str, Any] = {"label": label, "path": pack_rel,
                            "proven": False, "document": None}
    if not _pack_path_ok(pack_rel, ticket, label, problems):
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
    stem = Path(pack_rel).stem
    if not (stem == f"evidence-pack-{file_sha}" or
            stem == f"ticket-pack-{file_sha}" or stem.endswith(file_sha)):
        problems.append(f"{label} path not content-addressed by file sha")
    try:
        pack = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        problems.append(f"{label} is not valid UTF-8 JSON: {exc}")
        return info
    if not isinstance(pack, dict):
        problems.append(f"{label} root is not an object")
        return info
    info["document"] = pack
    if "payload" in pack:
        if set(pack) != {"payload", "payload_sha256"}:
            problems.append(f"{label} wrapper has unexpected fields")
        payload = pack.get("payload")
        if not isinstance(payload, dict):
            problems.append(f"{label} payload is not an object")
        else:
            computed = sha(canonical(payload))
            if computed != entry.get("payload_sha256"):
                problems.append(f"{label} payload bytes mismatch")
            if pack.get("payload_sha256") != entry.get("payload_sha256"):
                problems.append(f"{label} payload sha field mismatch")
            info["payload_sha256"] = computed
    else:
        computed = payload_sha(pack)
        if pack.get("sha256") != entry.get("payload_sha256"):
            problems.append(f"{label} payload sha field mismatch")
        if computed != entry.get("payload_sha256"):
            problems.append(f"{label} payload bytes mismatch")
        info["payload_sha256"] = computed
    info["proven"] = not any(
        p.startswith(label) or f"{label} " in p for p in problems)
    return info


def _compare_override(actual: dict, override: dict,
                      problems: list[str]) -> None:
    if not isinstance(override, dict):
        problems.append("record override is not an object")
        return
    if canonical(actual) != canonical(override):
        problems.append("record override differs from authoritative Git record")


def _check_tracked_artifacts(branch: str, ticket: str, rec: dict,
                             problems: list[str]) -> None:
    entries = rec.get("tracked_artifact_hashes")
    if entries is None:
        entries = rec.get("tracked_artifacts")
    if not isinstance(entries, dict) or not entries:
        problems.append("record has no tracked artifact hash map")
        return
    for rel, expected in sorted(entries.items()):
        label = f"tracked artifact {rel}"
        test_path = f"tests/test_{ticket.lower().replace('-', '_')}_regressions.py"
        if not contained(rel, ticket) and rel != test_path:
            problems.append(f"{label} escapes ticket dir")
            continue
        if not isinstance(expected, str) or not HEX64.fullmatch(expected):
            problems.append(f"{label} has invalid hash")
            continue
        try:
            actual = sha(git_show(branch, rel))
        except RuntimeError as exc:
            problems.append(str(exc))
            continue
        if actual != expected:
            problems.append(f"{label} hash mismatch")


def _check_canonical_dependencies(rec: dict, ticket: str,
                                  problems: list[str]) -> None:
    deps = rec.get("canonical_dependencies")
    if not isinstance(deps, list) or not deps:
        problems.append("record has no canonical dependency chain")
        return
    for index, item in enumerate(deps):
        label = f"canonical dependency {index}"
        if not isinstance(item, dict):
            problems.append(f"{label} is not an object")
            continue
        for key in ("ticket_id", "goal_id", "evaluation_id",
                    "research_revision", "result", "artifact_chain_hash"):
            if key not in item:
                problems.append(f"{label} missing {key}")
        if item.get("ticket_id") == ticket:
            problems.append(f"{label} self-references {ticket}")
        if item.get("result") not in ALLOWED_VERDICTS:
            problems.append(f"{label} has non-positive verdict")
        if item.get("chain_recomputed_from_disk") is not True:
            problems.append(f"{label} chain is not recomputed from disk")
        _check_hash(item.get("artifact_chain_hash"),
                    f"{label} artifact_chain_hash", problems)


def _check_pack_bindings(ticket: str, rec: dict, packs: dict,
                         problems: list[str]) -> None:
    evidence = packs.get("evidence-pack", {}).get("document")
    ticket_doc = packs.get("ticket-pack", {}).get("document")
    if not isinstance(evidence, dict) or not isinstance(ticket_doc, dict):
        return
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        problems.append("evidence-pack schema is not v3")
    goal = evidence.get("goal")
    if not isinstance(goal, dict) or goal.get("id") != rec.get("goal_id"):
        problems.append("evidence-pack goal id mismatch")
    research = evidence.get("research")
    if not isinstance(research, dict):
        problems.append("evidence-pack research section missing")
    else:
        campaign = research.get("campaign")
        if not isinstance(campaign, dict):
            problems.append("evidence-pack campaign binding missing")
        else:
            for key, expected in (("id", rec.get("campaign_id")),
                                  ("goal_id", rec.get("goal_id")),
                                  ("revision", rec.get("research_revision")),
                                  ("manifest_sha256", rec.get("manifest_sha256"))):
                if campaign.get(key) != expected:
                    problems.append(f"evidence-pack campaign {key} mismatch")
            if campaign.get("research_key") != ticket:
                problems.append("evidence-pack research key mismatch")
        for key in ("current_chain_hash", "latest_chain_hash"):
            if research.get(key) != rec.get("artifact_chain_hash"):
                problems.append(f"evidence-pack {key} mismatch")
        if research.get("chain_fresh") is not True:
            problems.append("evidence-pack chain is not fresh")
        if research.get("latest_evaluation_valid") is not True:
            problems.append("evidence-pack latest evaluation is not valid")
        evaluations = research.get("evaluations")
        if not isinstance(evaluations, list):
            problems.append("evidence-pack evaluations missing")
        else:
            matching = [e for e in evaluations if isinstance(e, dict) and
                        e.get("id") == rec.get("evaluation_id")]
            if len(matching) != 1:
                problems.append("evidence-pack evaluation identity mismatch")
            else:
                evaluation = matching[0]
                for key, expected in (("goal_id", rec.get("goal_id")),
                                      ("campaign_id", rec.get("campaign_id")),
                                      ("result", rec.get("result")),
                                      ("artifact_chain_hash",
                                       rec.get("artifact_chain_hash"))):
                    if evaluation.get(key) != expected:
                        problems.append(f"evidence-pack evaluation {key} mismatch")

    if set(ticket_doc) != {"payload", "payload_sha256"}:
        problems.append("ticket-pack wrapper schema mismatch")
        return
    payload = ticket_doc.get("payload")
    if not isinstance(payload, dict):
        problems.append("ticket-pack payload missing")
        return
    if payload.get("ticket_id") != ticket:
        problems.append("ticket-pack ticket id mismatch")
    if not isinstance(payload.get("schema"), str) or \
            not payload["schema"].endswith(".ticket-evidence/v1"):
        problems.append("ticket-pack payload schema mismatch")
    series = payload.get("series")
    if not isinstance(series, dict):
        problems.append("ticket-pack series binding missing")
    else:
        for key, expected in (("campaign_id", rec.get("campaign_id")),
                              ("goal_id", rec.get("goal_id")),
                              ("revision", rec.get("research_revision")),
                              ("manifest_sha256", rec.get("manifest_sha256"))):
            if series.get(key) != expected:
                problems.append(f"ticket-pack series {key} mismatch")
    evaluation = payload.get("evaluation")
    if not isinstance(evaluation, dict):
        problems.append("ticket-pack evaluation binding missing")
    else:
        for key, expected in (("id", rec.get("evaluation_id")),
                              ("goal_id", rec.get("goal_id")),
                              ("campaign_id", rec.get("campaign_id")),
                              ("result", rec.get("result")),
                              ("artifact_chain_hash",
                               rec.get("artifact_chain_hash"))):
            if evaluation.get(key) != expected:
                problems.append(f"ticket-pack evaluation {key} mismatch")
    canonical_pack = payload.get("canonical_pack")
    evidence_entry = rec.get("evidence_pack")
    if isinstance(canonical_pack, dict) and isinstance(evidence_entry, dict):
        for key in ("path", "sha256", "payload_sha256"):
            if canonical_pack.get(key) != evidence_entry.get(key):
                problems.append(f"ticket-pack canonical pack {key} mismatch")
    tracked = rec.get("tracked_artifact_hashes")
    if tracked is None:
        tracked = rec.get("tracked_artifacts")
    payload_tracked = payload.get("tracked_artifact_hashes")
    if payload_tracked is None:
        payload_tracked = payload.get("tracked_artifacts")
    if payload_tracked != tracked:
        problems.append("ticket-pack tracked artifact map mismatch")
    if payload.get("canonical_dependencies") != rec.get("canonical_dependencies"):
        problems.append("ticket-pack canonical dependency chain mismatch")


def _authoritative_record(dep: dict) -> dict:
    raw = git_show(dep["branch"], dep["record"])
    record = json.loads(raw.decode("utf-8"))
    if not isinstance(record, dict):
        raise RuntimeError("authoritative dependency record is not an object")
    return record


def check(dep: dict, rec_override: dict | None = None,
          docs_override: str | None = None) -> dict:
    """Verify one dependency; only authoritative Git bytes can be PROVEN."""
    ticket, branch = dep.get("ticket"), dep.get("branch")
    problems: list[str] = []
    if not isinstance(ticket, str) or not isinstance(branch, str):
        return {"ticket": ticket, "status": "NOT_PROVEN",
                "problems": ["malformed dependency descriptor"]}
    try:
        head = branch_head(branch)
        authoritative = _authoritative_record(dep)
    except (RuntimeError, UnicodeDecodeError, ValueError) as exc:
        return {"ticket": ticket, "branch": branch, "status": "NOT_PROVEN",
                "problems": [str(exc)]}
    if rec_override is not None:
        _compare_override(authoritative, rec_override, problems)
    rec = authoritative
    if rec.get("schema") != RECORD_SCHEMA:
        problems.append("record schema mismatch")
    if rec.get("ticket_id") != ticket:
        problems.append("record ticket identity mismatch")
    if rec.get("result") not in ALLOWED_VERDICTS:
        problems.append(f"dependency verdict {rec.get('result')!r} not in "
                       "positive allowlist")
    for key in ("goal_id", "campaign_id", "evaluation_id"):
        if not _record_id(rec.get(key)):
            problems.append(f"record missing binding field {key}")
    for key in ("artifact_chain_hash", "manifest_sha256", "bundle_sha256"):
        _check_hash(rec.get(key), f"record {key}", problems)
    revision = rec.get("research_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        problems.append("record research_revision is invalid")
    evidence_entry = rec.get("evidence_pack")
    ticket_entry = rec.get("ticket_pack")
    packs_list = []
    for label, entry in (("evidence-pack", evidence_entry),
                         ("ticket-pack", ticket_entry)):
        if not isinstance(entry, dict):
            problems.append(f"record {label} binding missing")
            continue
        _check_hash(entry.get("sha256"), f"record {label} file sha", problems)
        _check_hash(entry.get("payload_sha256"),
                    f"record {label} payload sha", problems)
        packs_list.append(check_pack(branch, ticket, label, entry, problems))
    packs = {item["label"]: item for item in packs_list}
    _check_tracked_artifacts(branch, ticket, rec, problems)
    _check_canonical_dependencies(rec, ticket, problems)
    try:
        segment = docs_override if docs_override is not None \
            else docs_segment(branch, ticket)
        lines = [line for line in segment.splitlines()
                 if line.startswith("- **Status:**")]
        if not lines:
            raise RuntimeError("no Status line in docs segment")
        verdict = rec.get("result")
        if f"`{str(verdict).upper()}`" not in lines[0]:
            problems.append("docs status does not match authoritative verdict")
        mentioned = set(re.findall(r"[Rr]evision\s+(\d+)", segment))
        if str(revision) not in mentioned:
            problems.append("research revision is not bound to docs segment")
    except (RuntimeError, ValueError, UnicodeDecodeError) as exc:
        problems.append(f"docs status check failed: {exc}")
    _check_pack_bindings(ticket, rec, packs, problems)
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
        "packs": [{k: v for k, v in item.items() if k != "document"}
                  for item in packs_list],
        "canonical_db_recheck_required": True,
        "problems": problems,
        "status": "PROVEN" if not problems else "NOT_PROVEN",
    }


def main() -> int:
    results = [check(dep) for dep in DEPS]
    doc = {
        "schema": "agentos.s1-013.dependency-gate/v2",
        "ticket": "S1-013",
        "dependencies": results,
        "all_proven": all(r["status"] == "PROVEN" for r in results),
        "canonical_db_recheck_required": True,
        "note": ("Cross-branch tracked-Git evidence only; each dependency "
                 "was read from a matching immutable origin ref. Live DB "
                 "consistency remains a Phase B operator check."),
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8",
                   newline="\n")
    print(json.dumps(doc, indent=2))
    if not doc["all_proven"]:
        failed = [r["ticket"] for r in results if r["status"] != "PROVEN"]
        print(f"BLOCKED_DEPENDENCY: evidence not proven for {failed}",
              file=sys.stderr)
        return 1
    print("DEPENDENCY GATE: S1-011 and S1-012 PROVEN (portable tracked Git)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
