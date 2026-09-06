"""S1-018 dependency gate: S1-007 + S1-008 + S1-009 from immutable bytes.

Discovery-based by ticket contract: no ticket/revision/goal/chain/hash value
is copied from prose or chat. Every binding is read from `origin/main`
tracked bytes (records, packs, frozen artifacts) and cross-checked for
internal consistency plus existence through `git archive`. Caller-supplied
overrides never supply identity values. Any mismatch yields
BLOCKED_DEPENDENCY (exit 1).
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

TICKET = Path(__file__).resolve().parent
OUT = TICKET / "dependency-gate.json"
ORIGIN_MAIN = "origin/main"

DEPS = ("S1-007", "S1-008", "S1-009")
ALLOWED_VERDICTS = {"pass", "pass_with_limits"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
BRANCH = re.compile(r"^[A-Za-z0-9._/-]+$")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def git_run(args: list[str], *, text: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=text,
                          check=False)


def git_show(ref: str, rel: str) -> bytes:
    if not BRANCH.fullmatch(ref or ""):
        raise RuntimeError("invalid Git ref")
    if not rel or "\x00" in rel or rel.startswith("-"):
        raise RuntimeError("invalid Git path")
    proc = git_run(["show", f"{ref}:{rel}"])
    if proc.returncode != 0:
        raise RuntimeError(f"git show {ref}:{rel} failed: "
                           f"{proc.stderr.decode(errors='replace')[:160]}")
    return proc.stdout


def contained(rel: str, ticket: str) -> bool:
    if not isinstance(rel, str) or not rel or "\\" in rel:
        return False
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        return False
    parts = rel.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    prefix = f"research/tickets/stage-1/{ticket}/"
    return rel.startswith(prefix) and len(rel) > len(prefix)


def git_archive_bytes(ref: str, rel: str, ticket: str) -> bytes:
    if not BRANCH.fullmatch(ref or ""):
        raise RuntimeError("invalid archive Git ref")
    if not contained(rel, ticket):
        raise RuntimeError(f"archive path escapes ticket dir: {rel}")
    proc = git_run(["archive", ref, "--", rel])
    if proc.returncode != 0:
        raise RuntimeError(f"git archive {ref} {rel} failed: "
                           f"{proc.stderr.decode(errors='replace')[:160]}")
    try:
        with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:*") as tar:
            member = tar.getmember(rel)
            if member.issym() or member.islnk():
                raise RuntimeError(f"archive member is a link: {rel}")
            handle = tar.extractfile(member)
            if handle is None:
                raise RuntimeError(f"archive member unreadable: {rel}")
            return handle.read()
    except (tarfile.TarError, KeyError) as exc:
        raise RuntimeError(f"git archive parse failed for {rel}: {exc}") from exc


def _check_hash(value, label: str, problems: list[str]) -> None:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        problems.append(f"{label} is not a lowercase SHA-256")


def _resolve_verified(ticket: str, rel: str, expected_sha: str | None,
                      problems: list[str], label: str,
                      require_addressed: bool = True) -> tuple[str | None, bytes | None]:
    """Resolve a record-referenced path against candidate roots.

    Candidates in order: ticket-relative expansion, then repo-root as
    written. A candidate is accepted ONLY if its git-show bytes equal its
    git-archive bytes AND match the record's expected file hash. The hash
    is the arbiter, never the path spelling. Content-addressed filenames
    are required for packs; plain binding files rely on recorded hashes.
    Returns (resolved_rel, bytes).
    """
    if not isinstance(rel, str) or not rel or "\x00" in rel or rel.startswith("-"):
        problems.append(f"{label} path is not a clean relative path: {rel!r}")
        return None, None
    expanded = f"research/tickets/stage-1/{ticket}/{rel}" \
        if not rel.startswith("research/") else rel
    candidates = []
    if contained(expanded, ticket):
        candidates.append(expanded)
    if rel != expanded and not rel.startswith("research/tickets/stage-1/"):
        # Repo-root-relative reference (top-level results/ tree). Accept only
        # with a hash proof below; traversal already excluded by construction.
        if ".." not in rel.split("/") and not rel.startswith("/"):
            candidates.append(rel)
    elif contained(rel, ticket) and rel != expanded:
        candidates.append(rel)
    verified: list[tuple[str, bytes]] = []
    for candidate in candidates:
        try:
            raw_show = git_show(ORIGIN_MAIN, candidate)
            raw_archive = git_archive_bytes_repo_root(ORIGIN_MAIN, candidate)
        except RuntimeError:
            continue
        if raw_show != raw_archive:
            problems.append(f"{label} show/archive bytes differ at {candidate}")
            continue
        if expected_sha is not None and sha(raw_show) != expected_sha:
            problems.append(f"{label} file sha mismatch at {candidate}")
            continue
        if require_addressed and not Path(candidate).stem.endswith(sha(raw_show)):
            problems.append(f"{label} path not content-addressed: {candidate}")
            continue
        verified.append((candidate, raw_show))
    if len(verified) > 1 and verified[0][1] != verified[1][1]:
        problems.append(f"{label} resolves ambiguously with different bytes")
        return None, None
    if not verified:
        problems.append(f"{label} absent from verified commit (tried: {candidates})")
        return None, None
    return verified[0]


def git_archive_bytes_repo_root(ref: str, rel: str) -> bytes:
    """git archive read for a repo-root-relative path (no ticket scoping)."""
    if not BRANCH.fullmatch(ref or ""):
        raise RuntimeError("invalid archive Git ref")
    if not rel or "\x00" in rel or rel.startswith("-") or rel.startswith("/"):
        raise RuntimeError(f"invalid archive path: {rel}")
    if ".." in rel.split("/") or "\\" in rel:
        raise RuntimeError(f"archive path escapes repo root: {rel}")
    proc = git_run(["archive", ref, "--", rel])
    if proc.returncode != 0:
        raise RuntimeError(f"git archive {ref} {rel} failed: "
                           f"{proc.stderr.decode(errors='replace')[:160]}")
    try:
        with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:*") as tar:
            member = tar.getmember(rel)
            if member.issym() or member.islnk():
                raise RuntimeError(f"archive member is a link: {rel}")
            handle = tar.extractfile(member)
            if handle is None:
                raise RuntimeError(f"archive member unreadable: {rel}")
            return handle.read()
    except (tarfile.TarError, KeyError) as exc:
        raise RuntimeError(f"git archive parse failed for {rel}: {exc}") from exc


def _load_record(ticket: str, problems: list[str]) -> dict | None:
    try:
        raw = git_show(ORIGIN_MAIN, f"research/tickets/stage-1/{ticket}/evaluation-record.json")
        record = json.loads(raw.decode("utf-8"))
    except (RuntimeError, UnicodeDecodeError, ValueError) as exc:
        problems.append(f"record unreadable: {exc}")
        return None
    if not isinstance(record, dict):
        problems.append("record is not an object")
        return None
    return record


def _verify_tracked_map(ticket: str, mapping: dict, problems: list[str],
                        label: str) -> dict:
    """Recompute every hash in a tracked map from git archive bytes."""
    verified: dict[str, str] = {}
    if not isinstance(mapping, dict) or not mapping:
        problems.append(f"{label} is empty or not an object")
        return verified
    test_prefix = f"tests/test_{ticket.lower().replace('-', '_')}"
    for rel, expected in sorted(mapping.items()):
        if rel.startswith(test_prefix):
            # Ticket test modules live beside the ticket by repo convention
            # (same allowlist shape as prior tickets); verify bytes directly.
            try:
                actual = sha(git_show(ORIGIN_MAIN, rel))
            except RuntimeError as exc:
                problems.append(f"{label} unreadable {rel}: {exc}")
                continue
            if actual != expected:
                problems.append(f"{label} hash mismatch for {rel}")
                continue
            verified[rel] = actual
            continue
        if not contained(rel, ticket):
            problems.append(f"{label} path escapes ticket dir: {rel}")
            continue
        if not isinstance(expected, str) or not HEX64.fullmatch(expected):
            problems.append(f"{label} hash invalid for {rel}")
            continue
        try:
            actual = sha(git_archive_bytes(ORIGIN_MAIN, rel, ticket))
        except RuntimeError as exc:
            problems.append(f"{label} unreadable {rel}: {exc}")
            continue
        if actual != expected:
            problems.append(f"{label} hash mismatch for {rel}")
            continue
        verified[rel] = actual
    return verified


def _check_v1_record(ticket: str, record: dict, problems: list[str]) -> dict:
    """Shared checks for agentos.ticket-evaluation-record/v1 records."""
    info: dict = {}
    if record.get("ticket_id") != ticket:
        problems.append("record ticket identity mismatch")
    verdict = str(record.get("result", "")).lower()
    if verdict not in ALLOWED_VERDICTS:
        problems.append(f"record verdict {record.get('result')!r} not positive")
    info["verdict"] = verdict
    revision = record.get("research_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        problems.append("record research_revision invalid")
    for key in ("goal_id", "campaign_id", "evaluation_id"):
        value = record.get(key)
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            problems.append(f"record missing binding field {key}")
    _check_hash(record.get("artifact_chain_hash"), "record artifact_chain_hash",
                problems)
    return info


def check_s1_007(problems: list[str]) -> dict:
    ticket = "S1-007"
    record = _load_record(ticket, problems)
    if record is None:
        return {"ticket": ticket, "status": "NOT_PROVEN", "problems": problems}
    info = _check_v1_record(ticket, record, problems)
    entry = record.get("evidence_pack")
    pack_ok = False
    if not isinstance(entry, dict):
        problems.append("record evidence_pack binding missing")
    else:
        pack_rel = entry.get("path")
        if not contained(pack_rel, ticket):
            problems.append(f"evidence pack path escapes ticket dir: {pack_rel}")
        else:
            try:
                raw_show = git_show(ORIGIN_MAIN, pack_rel)
                raw_archive = git_archive_bytes(ORIGIN_MAIN, pack_rel, ticket)
            except RuntimeError as exc:
                problems.append(str(exc))
                raw_show = raw_archive = None
            if raw_show is not None:
                if raw_show != raw_archive:
                    problems.append("evidence pack show/archive bytes differ")
                file_sha = sha(raw_show)
                if file_sha != entry.get("sha256"):
                    problems.append("evidence pack file sha mismatch vs record")
                if not Path(pack_rel).stem.endswith(file_sha):
                    problems.append("evidence pack path not content-addressed")
                try:
                    pack = json.loads(raw_show.decode("utf-8"))
                except (UnicodeDecodeError, ValueError) as exc:
                    problems.append(f"evidence pack is not valid JSON: {exc}")
                    pack = None
                if isinstance(pack, dict):
                    if pack.get("goal", {}).get("id") != record.get("goal_id"):
                        problems.append("evidence pack goal id mismatch")
                    research = pack.get("research", {})
                    if research.get("campaign", {}).get("id") != record.get("campaign_id"):
                        problems.append("evidence pack campaign id mismatch")
                    for key in ("current_chain_hash", "latest_chain_hash"):
                        if research.get(key) != record.get("artifact_chain_hash"):
                            problems.append(f"evidence pack {key} mismatch")
                    if research.get("chain_fresh") is not True:
                        problems.append("evidence pack chain is not fresh")
                    if research.get("latest_evaluation_valid") is not True:
                        problems.append("evidence pack latest evaluation not valid")
                    pack_ok = not any("evidence pack" in p for p in problems)
    # Semantic inheritance: scope isolation decision + QA3 per-scope verdict.
    try:
        contract = json.loads(git_show(
            ORIGIN_MAIN, "research/tickets/stage-1/S1-007/isolation-contract.json"
        ).decode("utf-8"))
    except (RuntimeError, UnicodeDecodeError, ValueError) as exc:
        problems.append(f"isolation contract unavailable: {exc}")
        contract = {}
    scope_tuple = ((contract.get("scope_identity") or {}).get("canonical_scope_id") or {})
    single_scope = scope_tuple.get("composition") == \
        "tenant_id + '/' + workspace_id + '/' + goal_id"
    if not single_scope:
        problems.append("S1-007 canonical scope tuple mismatch")
    for rel in ("research/tickets/stage-1/S1-007/results/run-a/run-manifest.json",
                "research/tickets/stage-1/S1-007/results/run-b/run-manifest.json",
                "research/tickets/stage-1/S1-007/results/decision-matrix.json"):
        try:
            git_show(ORIGIN_MAIN, rel)
        except RuntimeError as exc:
            problems.append(f"S1-007 run evidence missing: {exc}")
    limitations = [x for x in (record.get("limitations") or [])
                   if isinstance(x, str) and x.strip()]
    return {"ticket": ticket, "status": "PROVEN" if not problems else "NOT_PROVEN",
            "schema": record.get("schema"), "verdict": info.get("verdict"),
            "research_revision": record.get("research_revision"),
            "goal_id": record.get("goal_id"), "campaign_id": record.get("campaign_id"),
            "evaluation_id": record.get("evaluation_id"),
            "artifact_chain_hash": record.get("artifact_chain_hash"),
            "evidence_pack_proven": pack_ok, "single_scope_tuple": single_scope,
            "inherited_limits": limitations,
            "canonical_db_recheck_required": True, "problems": problems}


def check_s1_008(problems: list[str]) -> dict:
    ticket = "S1-008"
    record = _load_record(ticket, problems)
    if record is None:
        return {"ticket": ticket, "status": "NOT_PROVEN", "problems": problems}
    if record.get("ticket_id") != ticket:
        problems.append("record ticket identity mismatch")
    verdict = str(record.get("result", "")).lower()
    if verdict not in ALLOWED_VERDICTS:
        problems.append(f"record verdict {record.get('result')!r} not positive")
    revision = record.get("research_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        problems.append("record research_revision invalid")
    for key in ("goal_id", "campaign_id", "evaluation_id"):
        value = record.get(key)
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            problems.append(f"record missing binding field {key}")
    _check_hash(record.get("artifact_chain_hash"), "record artifact_chain_hash",
                problems)
    # Referenced evidence pack: must exist in the verified commit with
    # hash-verified bytes (ticket-relative or repo-root resolution).
    entry = record.get("evidence_pack") or {}
    pack_rel = entry.get("path")
    pack_file_sha = entry.get("pack_sha256") or entry.get("sha256")
    pack_resolved, pack_raw = _resolve_verified(
        ticket, pack_rel, None, problems, "evidence pack")
    pack_doc = None
    if pack_raw is not None:
        try:
            pack_doc = json.loads(pack_raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            problems.append(f"evidence pack is not valid JSON: {exc}")
        if isinstance(pack_doc, dict):
            for key, expected in (("goal_id", record.get("goal_id")),
                                  ("campaign_id", record.get("campaign_id")),
                                  ("evaluation_id", record.get("evaluation_id")),
                                  ("artifact_chain_hash",
                                   record.get("artifact_chain_hash")),
                                  ("result", record.get("result"))):
                if pack_doc.get(key) != expected:
                    problems.append(f"evidence pack binding mismatch: {key}")
    opaque = [k for k in ("pack_sha256", "record_sha256")
              if isinstance((entry if k == "pack_sha256" else record).get(k), str)
              and HEX64.fullmatch((entry if k == "pack_sha256" else record)[k])]
    pack_note = ("opaque self-hash fields recorded but not independently "
                 "reproducible: " + ", ".join(opaque)) if opaque else None
    # Evidence-binding result files resolve the same hash-arbiter way.
    # They carry recorded hashes rather than content-addressed filenames.
    binding = record.get("evidence_binding") or {}
    for key in ("comparison", "evaluation_result"):
        item = binding.get(key) if isinstance(binding, dict) else None
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get("sha256"), str) or \
                not HEX64.fullmatch(item["sha256"]):
            problems.append(f"evidence binding {key} has no valid sha256")
            continue
        _resolve_verified(ticket, item.get("path"), item.get("sha256"),
                          problems, f"evidence binding {key}",
                          require_addressed=False)
    # Frozen artifacts ARE tracked: verify every hash from git archive bytes.
    frozen = record.get("frozen_artifacts")
    verified_frozen: dict[str, str] = {}
    if isinstance(frozen, dict) and frozen:
        for name, expected in sorted(frozen.items()):
            rel = f"research/tickets/stage-1/{ticket}/{name}"
            if not isinstance(expected, str) or not HEX64.fullmatch(expected):
                problems.append(f"frozen artifact hash invalid: {name}")
                continue
            try:
                actual = sha(git_archive_bytes(ORIGIN_MAIN, rel, ticket))
            except RuntimeError as exc:
                problems.append(f"frozen artifact unreadable {name}: {exc}")
                continue
            if actual != expected:
                problems.append(f"frozen artifact hash mismatch: {name}")
                continue
            verified_frozen[name] = actual
    else:
        problems.append("record carries no frozen artifact map")
    # Semantic inheritance from TRACKED files only.
    try:
        contract = json.loads(git_show(
            ORIGIN_MAIN, "research/tickets/stage-1/S1-008/revocation-contract.json"
        ).decode("utf-8"))
    except (RuntimeError, UnicodeDecodeError, ValueError) as exc:
        problems.append(f"revocation contract unavailable: {exc}")
        contract = {}
    limitations = [x for x in (record.get("limitations") or [])
                   if isinstance(x, str) and x.strip()]
    notes = []
    if pack_note:
        notes.append(pack_note)
    if pack_resolved:
        notes.append(f"evidence pack resolved at {pack_resolved}")
    return {"ticket": ticket, "status": "PROVEN" if not problems else "NOT_PROVEN",
            "schema": record.get("schema"), "verdict": verdict,
            "resolution_notes": notes,
            "research_revision": record.get("research_revision"),
            "goal_id": record.get("goal_id"), "campaign_id": record.get("campaign_id"),
            "evaluation_id": record.get("evaluation_id"),
            "artifact_chain_hash": record.get("artifact_chain_hash"),
            "evidence_pack_proven": False,
            "frozen_artifacts_verified": verified_frozen,
            "revocation_contract_present": bool(contract),
            "inherited_limits": limitations,
            "canonical_db_recheck_required": True, "problems": problems}


def check_s1_009(problems: list[str]) -> dict:
    ticket = "S1-009"
    record = _load_record(ticket, problems)
    if record is None:
        return {"ticket": ticket, "status": "NOT_PROVEN", "problems": problems}
    info = _check_v1_record(ticket, record, problems)
    # Tracked content-addressed packs (canonical + ticket) from git archive.
    packs_ok = True
    for key in ("tracked_canonical_pack", "tracked_ticket_pack"):
        entry = record.get(key)
        if not isinstance(entry, dict):
            problems.append(f"record {key} binding missing")
            packs_ok = False
            continue
        pack_rel = entry.get("path")
        if not contained(pack_rel, ticket):
            problems.append(f"{key} path escapes ticket dir: {pack_rel}")
            packs_ok = False
            continue
        try:
            raw_show = git_show(ORIGIN_MAIN, pack_rel)
            raw_archive = git_archive_bytes(ORIGIN_MAIN, pack_rel, ticket)
        except RuntimeError as exc:
            problems.append(f"{key} absent from verified commit: {exc}")
            packs_ok = False
            continue
        if raw_show != raw_archive:
            problems.append(f"{key} show/archive bytes differ")
            packs_ok = False
            continue
        file_sha = sha(raw_show)
        if file_sha != entry.get("file_sha256"):
            problems.append(f"{key} file sha mismatch vs record")
            packs_ok = False
        if not Path(pack_rel).stem.endswith(file_sha):
            problems.append(f"{key} path not content-addressed")
            packs_ok = False
        try:
            pack = json.loads(raw_show.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            problems.append(f"{key} is not valid JSON: {exc}")
            packs_ok = False
            continue
        if not isinstance(pack, dict):
            problems.append(f"{key} root is not an object")
            packs_ok = False
    # Tracked artifact map + adapter boundary + unsupported semantics.
    tracked = record.get("tracked_artifact_hashes")
    verified_tracked = _verify_tracked_map(ticket, tracked, problems, "tracked artifacts")
    for rel in ("research/tickets/stage-1/S1-009/adapter-contract.json",
                "research/tickets/stage-1/S1-009/capability-matrix.json"):
        try:
            git_show(ORIGIN_MAIN, rel)
        except RuntimeError as exc:
            problems.append(f"S1-009 adapter boundary file missing: {exc}")
    try:
        bundle = json.loads(git_show(
            ORIGIN_MAIN, "research/tickets/stage-1/S1-009/bundle.json").decode("utf-8"))
    except (RuntimeError, UnicodeDecodeError, ValueError) as exc:
        problems.append(f"S1-009 bundle unavailable: {exc}")
        bundle = {}
    limitations = [x for x in (record.get("limitations") or [])
                   if isinstance(x, str) and x.strip()]
    return {"ticket": ticket, "status": "PROVEN" if not problems else "NOT_PROVEN",
            "schema": record.get("schema"), "verdict": info.get("verdict"),
            "research_revision": record.get("research_revision"),
            "goal_id": record.get("goal_id"), "campaign_id": record.get("campaign_id"),
            "evaluation_id": record.get("evaluation_id"),
            "artifact_chain_hash": record.get("artifact_chain_hash"),
            "packs_proven": packs_ok,
            "tracked_verified": len(verified_tracked),
            "adapter_boundary_present": bool(bundle),
            "inherited_limits": limitations,
            "canonical_db_recheck_required": True, "problems": problems}


CHECKS = {"S1-007": check_s1_007, "S1-008": check_s1_008, "S1-009": check_s1_009}


def check(ticket: str, rec_override: dict | None = None) -> dict:
    problems: list[str] = []
    if rec_override is not None:
        problems.append("record override never supplies identity values")
        return {"ticket": ticket, "status": "NOT_PROVEN", "problems": problems}
    return CHECKS[ticket](problems)


def main() -> int:
    commit = git_run(["rev-parse", ORIGIN_MAIN], text=True).stdout.strip()
    if not SHA40.fullmatch(commit or ""):
        print("BLOCKED_DEPENDENCY: origin/main is not an immutable commit",
              file=sys.stderr)
        return 1
    results = [check(ticket) for ticket in DEPS]
    proven = all(r["status"] == "PROVEN" for r in results)
    inherited: list[str] = []
    for result in results:
        inherited.extend(f"[{result['ticket']}] {line}"
                         for line in result.get("inherited_limits", []))
    doc = {
        "schema": "agentos.s1-018.dependency-gate/v1",
        "ticket": "S1-018",
        "verified_commit": commit,
        "dependencies": results,
        "dependencies_proven": proven,
        "scope_isolation_baseline_available": proven and any(
            r["ticket"] == "S1-007" and r.get("single_scope_tuple")
            for r in results),
        "revocation_baseline_available": proven and any(
            r["ticket"] == "S1-008" and r.get("revocation_contract_present")
            for r in results),
        "adapter_boundary_available": proven and any(
            r["ticket"] == "S1-009" and r.get("adapter_boundary_present")
            for r in results),
        "inherited_limits": inherited,
        "canonical_db_recheck_required": True,
        "note": ("Discovery-based proof from origin/main bytes incl. git "
                 "archive; no IDs/hashes copied from prose; status is never "
                 "upgraded."),
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in doc.items() if k != "inherited_limits"}, indent=2))
    if not proven:
        print(f"BLOCKED_DEPENDENCY: {[r['ticket'] for r in results if r['status'] != 'PROVEN']}",
              file=sys.stderr)
        return 1
    print("DEPENDENCY GATE: S1-007, S1-008 and S1-009 PROVEN", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
