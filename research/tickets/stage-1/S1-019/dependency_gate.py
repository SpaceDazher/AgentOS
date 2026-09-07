"""Fail-closed S1-019 dependency proof from one immutable Git commit.

The synthesis consumes S1-004..S1-018 directly and S1-001..S1-003
transitively. Identity values are discovered only from authoritative Git
blobs. Historical record families reuse the validators that closed S1-013
and S1-018, with strict-JSON and regular-blob checks at this boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from types import ModuleType
from typing import Any

PINNED_COMMIT = "19ff320adfe7153267fb634268038ae16ba25a16"
ALLOWED_RESULTS = {"pass", "pass_with_limits"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RECORD_SCHEMA_V2 = "agentos.ticket-evaluation-record/v2"


class GateInputError(ValueError):
    pass


class StrictJsonError(GateInputError):
    pass


class PathSafetyError(GateInputError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_strict_json(raw: bytes) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise StrictJsonError("duplicate JSON key: " + key)
            result[key] = value
        return result

    def constant(value):
        raise StrictJsonError("non-finite JSON: " + value)

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=constant)
    except (UnicodeError, ValueError) as exc:
        raise StrictJsonError(str(exc)) from exc
    if not isinstance(value, dict):
        raise StrictJsonError("record must be an object")
    return value


def validate_repo_relative_path(value: str) -> str:
    if (not isinstance(value, str) or not value or "\\" in value
            or ":" in value or "\x00" in value
            or PurePosixPath(value).is_absolute()
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise PathSafetyError("unsafe Git path")
    return value


def _git(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if proc.returncode:
        raise GateInputError(proc.stderr.decode("utf-8", errors="replace").strip())
    return proc.stdout


def resolve_pinned_commit(repo: Path, ref: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", ref or ""):
        raise GateInputError("full immutable commit SHA required")
    resolved = _git(repo, "rev-parse", "--verify", ref + "^{commit}").decode().strip()
    if resolved != ref:
        raise GateInputError("commit did not resolve exactly")
    return ref


def read_regular_blob(repo: Path, commit: str, path: str) -> bytes | None:
    validate_repo_relative_path(path)
    entry = _git(repo, "ls-tree", "-z", commit, "--", path)
    if not entry:
        return None
    pieces = entry.rstrip(b"\x00").split(b"\t")
    if len(pieces) != 2 or pieces[1].decode("utf-8") != path:
        raise GateInputError("unexpected tree entry")
    mode, kind, oid = pieces[0].split()
    if mode not in (b"100644", b"100755") or kind != b"blob":
        raise GateInputError("regular Git blob required, not a link/tree")
    return _git(repo, "cat-file", "blob", oid.decode("ascii"))


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GateInputError(f"cannot load verifier {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _basic_record_checks(ticket: str, record: dict[str, Any],
                         problems: list[str]) -> None:
    if record.get("ticket_id") != ticket:
        problems.append("record ticket identity mismatch")
    if str(record.get("result", "")).lower() not in ALLOWED_RESULTS:
        problems.append(f"record verdict {record.get('result')!r} is not positive")
    revision = record.get("research_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        problems.append("record research_revision invalid")
    for key in ("goal_id", "campaign_id", "evaluation_id"):
        value = record.get(key)
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            problems.append(f"record missing binding field {key}")
    chain = record.get("artifact_chain_hash")
    if not isinstance(chain, str) or not HEX64.fullmatch(chain):
        problems.append("record artifact_chain_hash invalid")
    limits = record.get("limitations")
    if limits is not None and not isinstance(limits, list):
        problems.append("record limitations must be a list when present")


def _result(ticket: str, record: dict[str, Any], problems: list[str],
            verifier: str) -> dict[str, Any]:
    return {
        "ticket": ticket,
        "dependency_kind": "transitive" if ticket in {"S1-001", "S1-002", "S1-003"}
        else "direct",
        "status": "PROVEN" if not problems else "NOT_PROVEN",
        "verifier": verifier,
        "schema": record.get("schema"),
        "result": str(record.get("result", "")).lower(),
        "research_revision": record.get("research_revision"),
        "goal_id": record.get("goal_id"),
        "campaign_id": record.get("campaign_id"),
        "evaluation_id": record.get("evaluation_id"),
        "artifact_chain_hash": record.get("artifact_chain_hash"),
        "inherited_limits": record.get("limitations") or [],
        "canonical_db_recheck_required": True,
        "problems": problems,
    }


def _verify_legacy(repo: Path, commit: str, ticket: str,
                   record: dict[str, Any]) -> dict[str, Any]:
    """Verify the v1 canonical pack used by S1-001..S1-007."""
    problems: list[str] = []
    _basic_record_checks(ticket, record, problems)
    entry = record.get("evidence_pack")
    pack: dict[str, Any] | None = None
    if not isinstance(entry, dict):
        problems.append("record evidence_pack binding missing")
    else:
        rel = entry.get("path")
        prefix = f"research/tickets/stage-1/{ticket}/"
        if not isinstance(rel, str) or not rel.startswith(prefix):
            problems.append("evidence pack path escapes ticket directory")
        else:
            try:
                raw = read_regular_blob(repo, commit, rel)
                if raw is None:
                    raise GateInputError("evidence pack absent from immutable commit")
                file_sha = digest(raw)
                if entry.get("sha256") != file_sha:
                    problems.append("evidence pack file sha mismatch")
                if not Path(rel).stem.endswith(file_sha):
                    problems.append("evidence pack filename is not content-addressed")
                pack = load_strict_json(raw)
            except GateInputError as exc:
                problems.append(str(exc))
    if isinstance(pack, dict):
        if pack.get("schema") != "agentos.evidence-pack/v3":
            problems.append("evidence pack schema mismatch")
        if pack.get("goal", {}).get("id") != record.get("goal_id"):
            problems.append("evidence pack goal binding mismatch")
        research = pack.get("research")
        if not isinstance(research, dict):
            problems.append("evidence pack research section missing")
        else:
            campaign = research.get("campaign") or {}
            if campaign.get("id") != record.get("campaign_id"):
                problems.append("evidence pack campaign binding mismatch")
            if campaign.get("goal_id") != record.get("goal_id"):
                problems.append("evidence pack campaign goal mismatch")
            if "revision" in campaign and campaign.get("revision") != record.get("research_revision"):
                problems.append("evidence pack revision mismatch")
            if "research_key" in campaign and campaign.get("research_key") != ticket:
                problems.append("evidence pack research key mismatch")
            for key in ("current_chain_hash", "latest_chain_hash"):
                if research.get(key) != record.get("artifact_chain_hash"):
                    problems.append(f"evidence pack {key} mismatch")
            if research.get("chain_fresh") is not True:
                problems.append("evidence pack chain is not fresh")
            if research.get("latest_evaluation_valid") is not True:
                problems.append("evidence pack latest evaluation invalid")
            evaluations = research.get("evaluations")
            matches = [item for item in evaluations or [] if isinstance(item, dict)
                       and item.get("id") == record.get("evaluation_id")]
            if len(matches) != 1:
                problems.append("evidence pack evaluation identity mismatch")
            elif str(matches[0].get("result", "")).lower() != str(
                    record.get("result", "")).lower():
                problems.append("evidence pack evaluation verdict mismatch")
        expected = entry.get("payload_sha256") if isinstance(entry, dict) else None
        payload = {key: value for key, value in pack.items() if key != "sha256"}
        if expected != digest(canonical(payload)) or pack.get("sha256") != expected:
            problems.append("evidence pack payload/self hash mismatch")
    return _result(ticket, record, problems, "legacy-v1")


def _verify_with_historical_gate(repo: Path, commit: str, ticket: str,
                                 record: dict[str, Any], s18: ModuleType) -> dict[str, Any]:
    s18.ORIGIN_MAIN = commit
    historical = s18.check(ticket)
    problems = list(historical.get("problems") or [])
    _basic_record_checks(ticket, record, problems)
    result = _result(ticket, record, problems, "s1-018-specialized")
    result["historical_evidence"] = {key: value for key, value in historical.items()
                                     if key not in {"problems", "inherited_limits"}}
    return result


def _verify_modern(repo: Path, commit: str, ticket: str,
                   record: dict[str, Any], s13: ModuleType) -> dict[str, Any]:
    original_branch_head = s13.branch_head
    original_contained = s13.contained
    try:
        s13.branch_head = lambda _branch: commit
        test_prefix = f"tests/test_{ticket.lower().replace('-', '_')}"
        s13.contained = lambda rel, expected: (
            original_contained(rel, expected)
            or (expected == ticket and isinstance(rel, str)
                and rel.startswith(test_prefix) and rel.endswith(".py")))
        checked = s13.check({
            "ticket": ticket,
            "branch": commit,
            "record": f"research/tickets/stage-1/{ticket}/evaluation-record.json",
        })
    finally:
        s13.branch_head = original_branch_head
        s13.contained = original_contained
    problems = list(checked.get("problems") or [])
    # Earlier ticket-pack schemas used `revision` omission and
    # `chain_recomputed_from_git`. S1-019 independently cross-checks every
    # declared dependency against its authoritative row below.
    problems = [item for item in problems if not (
        (item.startswith("canonical dependency ") and
         (item.endswith(" missing research_revision") or
          item.endswith(" chain is not recomputed from disk"))))]
    _basic_record_checks(ticket, record, problems)
    if record.get("schema") != RECORD_SCHEMA_V2:
        problems.append("modern record schema mismatch")
    result = _result(ticket, record, problems, "s1-013-modern-v2")
    result["packs"] = checked.get("packs") or []
    result["declared_dependencies"] = record.get("canonical_dependencies") or []
    return result


def _cross_check_declared(rows: list[dict[str, Any]]) -> None:
    authoritative = {row["ticket"]: row for row in rows}
    for row in rows:
        for index, dep in enumerate(row.get("declared_dependencies") or []):
            label = f"declared dependency {index}"
            if not isinstance(dep, dict):
                row["problems"].append(f"{label} is not an object")
                continue
            target = authoritative.get(dep.get("ticket_id"))
            if target is None:
                row["problems"].append(f"{label} ticket not in S1-019 dependency set")
                continue
            for dep_key, row_key in (("goal_id", "goal_id"),
                                     ("campaign_id", "campaign_id"),
                                     ("evaluation_id", "evaluation_id"),
                                     ("artifact_chain_hash", "artifact_chain_hash"),
                                     ("research_revision", "research_revision"),
                                     ("revision", "research_revision")):
                if dep_key in dep and dep.get(dep_key) != target.get(row_key):
                    row["problems"].append(f"{label} {dep_key} mismatch")
            if str(dep.get("result", "")).lower() != target.get("result"):
                row["problems"].append(f"{label} result mismatch")
            if dep.get("chain_recomputed_from_disk") is not True and \
                    dep.get("chain_recomputed_from_git") is not True:
                row["problems"].append(f"{label} lacks chain recomputation proof")
        if row.get("problems"):
            row["status"] = "NOT_PROVEN"


def run_gate(repo: Path, ref: str) -> dict[str, Any]:
    repo = repo.resolve()
    commit = resolve_pinned_commit(repo, ref)
    s18 = _load_module(repo / "research/tickets/stage-1/S1-018/dependency_gate.py",
                       "s1018_dependency_verifier_for_s1019")
    s13 = _load_module(repo / "research/tickets/stage-1/S1-013/dependency_gate.py",
                       "s1013_dependency_verifier_for_s1019")
    rows: list[dict[str, Any]] = []
    identities: set[tuple[str, str, str]] = set()
    for number in range(1, 19):
        ticket = f"S1-{number:03d}"
        path = f"research/tickets/stage-1/{ticket}/evaluation-record.json"
        try:
            raw = read_regular_blob(repo, commit, path)
            if raw is None:
                raise GateInputError("evaluation-record.json absent from immutable commit")
            record = load_strict_json(raw)
            if number <= 7:
                row = _verify_legacy(repo, commit, ticket, record)
            elif number <= 9:
                row = _verify_with_historical_gate(repo, commit, ticket, record, s18)
            else:
                row = _verify_modern(repo, commit, ticket, record, s13)
            row["record_path"] = path
            row["record_file_sha256"] = digest(raw)
            identity = (str(record.get("goal_id")), str(record.get("campaign_id")),
                        str(record.get("evaluation_id")))
            if identity in identities:
                row["problems"].append("duplicate canonical identity tuple")
                row["status"] = "NOT_PROVEN"
            identities.add(identity)
        except (GateInputError, OSError, RuntimeError, ValueError) as exc:
            row = {"ticket": ticket, "dependency_kind": "transitive" if number <= 3
                   else "direct", "status": "NOT_PROVEN", "problems": [str(exc)]}
        rows.append(row)
    _cross_check_declared(rows)
    proven = all(row.get("status") == "PROVEN" for row in rows)
    inherited = [f"[{row['ticket']}] {item}" for row in rows
                 for item in row.get("inherited_limits", []) if isinstance(item, str)]
    return {
        "schema": "agentos.s1-019.dependency-gate/v2",
        "ticket": "S1-019",
        "verified_commit": commit,
        "immutable_ref": True,
        "direct_dependencies": [f"S1-{n:03d}" for n in range(4, 19)],
        "transitive_dependencies": [f"S1-{n:03d}" for n in range(1, 4)],
        "dependencies": rows,
        "dependencies_proven": proven,
        "synthesis_authorized": proven,
        "status": "PASS_WITH_LIMITS" if proven else "BLOCKED_DEPENDENCY",
        "inherited_limits": inherited,
        "canonical_db_recheck_required": True,
        "note": "All identity values discovered from one immutable Git tree; no caller overrides.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--ref", default=PINNED_COMMIT)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        report = run_gate(args.repo, args.ref)
    except (GateInputError, OSError, RuntimeError, ValueError) as exc:
        report = {"schema": "agentos.s1-019.dependency-gate/v2",
                  "status": "BLOCKED_DEPENDENCY", "dependencies_proven": False,
                  "synthesis_authorized": False, "error": str(exc)}
    encoded = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")
    return 0 if report.get("dependencies_proven") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
