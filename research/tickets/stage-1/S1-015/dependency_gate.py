"""S1-015 dependency gate: prove the S1-013 chain from immutable Git bytes.

Only tracked Git objects can PROVE the dependency. Caller-supplied records
(``rec_override``) never supply identity/status/chain values; they are compared
byte-identically against the authoritative ``git show`` bytes and any drift is
a failure. Pack bytes are additionally verified through ``git archive`` (not
only the worktree or ``git show``) and filenames must be content-addressed.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

TICKET = Path(__file__).resolve().parent
OUT = TICKET / "dependency-gate.json"

DEP_BRANCH = "codex/s1-013-comprehension-pilot"
DEP_RECORD = "research/tickets/stage-1/S1-013/evaluation-record.json"
DEP_OPERATOR_DECISION = "research/tickets/stage-1/S1-013/operator-decision.json"
ANCHOR_COMMIT = "091ade232ba7f3dd8a0063285977c1705c571d62"

EXPECTED = {
    "ticket_id": "S1-013",
    "goal_id": "goal_PZ0WP37PRBM05XH101M1QB60YD",
    "campaign_id": "rcamp_YX958H0WJ4YDK4AH01M1QB60YD",
    "evaluation_id": "reval_P911RT2XC117Y74Y01M1QB612C",
    "artifact_chain_hash": "766172bb18bcf479ce672ebe5e881a083e89430003b697a12650abf11c943e34",
    "result": "pass_with_limits",
    "research_revision": 1,
}

ALLOWED_VERDICTS = {"pass", "pass_with_limits"}
RECORD_SCHEMA = "agentos.ticket-evaluation-record/v2"
EVIDENCE_SCHEMA = "agentos.evidence-pack/v3"
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
    local = _rev(f"refs/heads/{branch}")
    remote = _rev(f"refs/remotes/origin/{branch}")
    if not remote:
        raise RuntimeError(f"dependency branch {branch} has no portable origin ref")
    if local and local != remote:
        raise RuntimeError(f"dependency branch {branch} diverges from its portable origin ref")
    proc = git_run(["cat-file", "-t", remote], text=True)
    if proc.returncode != 0 or proc.stdout.strip() != "commit":
        raise RuntimeError(f"dependency ref {branch} is not an immutable commit")
    return remote


def contains_ancestor(ref: str, commit: str) -> bool:
    if not SHA40.fullmatch(commit or ""):
        return False
    proc = git_run(["merge-base", "--is-ancestor", commit, ref])
    return proc.returncode == 0


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


def payload_sha(pack: dict) -> str:
    payload = {k: v for k, v in pack.items() if k != "sha256"}
    return sha(canonical(payload))


def git_archive_bytes(branch: str, rel: str) -> bytes:
    """Read one tracked file through `git archive` (tar) instead of worktree."""
    if not BRANCH.fullmatch(branch or ""):
        raise RuntimeError("invalid archive Git ref")
    if not contained(rel, "S1-013"):
        raise RuntimeError(f"archive path escapes ticket dir: {rel}")
    proc = git_run(["archive", branch, "--", rel])
    if proc.returncode != 0:
        raise RuntimeError(f"git archive {branch} {rel} failed: "
                           f"{proc.stderr.decode(errors='replace')[:200]}")
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


def _pack_path_ok(pack_rel, ticket: str, label: str, problems: list[str]) -> bool:
    if not contained(pack_rel, ticket):
        problems.append(f"{label} path escapes ticket dir: {pack_rel}")
        return False
    return True


def check_pack(branch: str, ticket: str, label: str, entry: dict,
               problems: list[str]) -> dict:
    if not isinstance(entry, dict):
        problems.append(f"{label} entry is not an object")
        return {"label": label, "path": None, "proven": False, "document": None}
    pack_rel = entry.get("path")
    info: dict = {"label": label, "path": pack_rel, "proven": False, "document": None}
    if not _pack_path_ok(pack_rel, ticket, label, problems):
        return info
    try:
        raw_show = git_show(branch, pack_rel)
        raw_archive = git_archive_bytes(branch, pack_rel)
    except RuntimeError as exc:
        problems.append(str(exc))
        return info
    if raw_show != raw_archive:
        problems.append(f"{label} git show bytes differ from git archive bytes")
        return info
    raw = raw_show
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


def _check_tracked(branch: str, ticket: str, rec: dict, problems: list[str]) -> None:
    entries = rec.get("tracked_artifact_hashes")
    if entries is None:
        entries = rec.get("tracked_artifacts")
    if not isinstance(entries, dict) or not entries:
        problems.append("record has no tracked artifact hash map")
        return
    for rel, expected in sorted(entries.items()):
        label = f"tracked artifact {rel}"
        if not contained(rel, ticket):
            # Allowlist: ticket test modules may live outside ticket dir.
            test_path = "tests/test_s1_013_regressions.py"
            alternates = {test_path, "tests/test_s1_013_solo_closure.py",
                          "tests/test_s1_013_ui.py", "tests/test_s1_013_boundary_r1.py",
                          "tests/test_s1_013_publication_r1.py"}
            if rel not in alternates:
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


def _check_canonical_deps(rec: dict, ticket: str, problems: list[str]) -> None:
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


def _check_pack_bindings(ticket: str, rec: dict, packs: dict, problems: list[str]) -> None:
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
    evaluation = payload.get("evaluation")
    if not isinstance(evaluation, dict):
        problems.append("ticket-pack evaluation binding missing")
    else:
        for key, expected in (("id", rec.get("evaluation_id")),
                              ("goal_id", rec.get("goal_id")),
                              ("campaign_id", rec.get("campaign_id")),
                              ("result", rec.get("result")),
                              ("artifact_chain_hash", rec.get("artifact_chain_hash"))):
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


def check(rec_override: dict | None = None) -> dict:
    ticket, branch = EXPECTED["ticket_id"], DEP_BRANCH
    problems: list[str] = []
    # 1. Anchor commit must be reachable from both portable refs.
    for ref in ("origin/main", f"origin/{DEP_BRANCH}"):
        head = _rev(f"refs/remotes/{ref}" if not ref.startswith("refs/") else ref)
        if not head:
            # Fall back to direct ref name resolution for origin/* names.
            proc = git_run(["rev-parse", "--verify", ref], text=True)
            head = proc.stdout.strip().lower() if proc.returncode == 0 else None
            if not head or not SHA40.fullmatch(head or ""):
                problems.append(f"portable ref {ref} missing")
                continue
        if not contains_ancestor(ref, ANCHOR_COMMIT):
            problems.append(f"anchor {ANCHOR_COMMIT[:7]} not reachable from {ref}")
    try:
        head = branch_head(branch)
        raw = git_show(branch, DEP_RECORD)
        authoritative = json.loads(raw.decode("utf-8"))
        if not isinstance(authoritative, dict):
            raise RuntimeError("authoritative dependency record is not an object")
    except (RuntimeError, UnicodeDecodeError, ValueError) as exc:
        return {"ticket": ticket, "branch": branch, "status": "NOT_PROVEN",
                "problems": [str(exc)] + problems}
    if rec_override is not None:
        if not isinstance(rec_override, dict):
            problems.append("record override is not an object")
        elif canonical(authoritative) != canonical(rec_override):
            problems.append("record override differs from authoritative Git record")
    rec = authoritative
    if rec.get("schema") != RECORD_SCHEMA:
        problems.append("record schema mismatch")
    if rec.get("ticket_id") != EXPECTED["ticket_id"]:
        problems.append("record ticket identity mismatch")
    for key in ("goal_id", "campaign_id", "evaluation_id",
                "artifact_chain_hash", "result", "research_revision"):
        if rec.get(key) != EXPECTED[key]:
            problems.append(f"record binding mismatch: {key}")
    if rec.get("result") not in ALLOWED_VERDICTS:
        problems.append(f"dependency verdict {rec.get('result')!r} not in positive allowlist")
    for key in ("artifact_chain_hash", "manifest_sha256", "bundle_sha256"):
        _check_hash(rec.get(key), f"record {key}", problems)
    evidence_entry = rec.get("evidence_pack")
    ticket_entry = rec.get("ticket_pack")
    packs_list = []
    for label, entry in (("evidence-pack", evidence_entry),
                         ("ticket-pack", ticket_entry)):
        if not isinstance(entry, dict):
            problems.append(f"record {label} binding missing")
            continue
        _check_hash(entry.get("sha256"), f"record {label} file sha", problems)
        _check_hash(entry.get("payload_sha256"), f"record {label} payload sha", problems)
        packs_list.append(check_pack(branch, ticket, label, entry, problems))
    packs = {item["label"]: item for item in packs_list}
    _check_tracked(branch, ticket, rec, problems)
    _check_canonical_deps(rec, ticket, problems)
    # Operator decision cross-check (structured, no raw identity in gate).
    try:
        op_raw = git_show(branch, DEP_OPERATOR_DECISION)
        op_doc = json.loads(op_raw.decode("utf-8"))
        if not isinstance(op_doc, dict) or op_doc.get("ticket") != ticket:
            problems.append("operator-decision ticket mismatch")
    except (RuntimeError, UnicodeDecodeError, ValueError) as exc:
        problems.append(f"operator-decision check failed: {exc}")
    _check_pack_bindings(ticket, rec, packs, problems)
    # Inherited limits: solo expert conformance, human_n=0 semantics, raw deleted.
    limitations = rec.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        problems.append("record has no limitations")
    else:
        text = "\n".join(str(x) for x in limitations).lower()
        for needle in ("no human data", "not_measured"):
            if needle not in text:
                problems.append(f"inherited limit not carried: {needle}")
        if "expert review" not in text and "independent human grading" not in text:
            problems.append("inherited limit not carried: solo expert conformance")
        # Raw-deletion is recorded in the S1-013 decision (transient envelopes
        # deleted after aggregate verification), not in the limitations list.
        try:
            decision_raw = git_show(
                branch, "research/tickets/stage-1/S1-013/results/decision.md"
            ).decode("utf-8").lower()
        except (RuntimeError, UnicodeDecodeError) as exc:
            problems.append(f"S1-013 decision unavailable: {exc}")
            decision_raw = ""
        if "raw" not in decision_raw or "delet" not in decision_raw:
            problems.append("inherited raw-deletion limit not carried")
    proven = not problems
    return {
        "ticket": ticket,
        "branch": branch,
        "branch_head": head,
        "anchor_commit": ANCHOR_COMMIT,
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
        "inherited_limits": [
            "solo expert conformance only (no independent human grading)",
            "human_n=0",
            "human comprehension/fatigue/effectiveness NOT_MEASURED",
            "raw operator/human data deleted after aggregate verification",
        ],
        "problems": problems,
        "status": "PROVEN" if proven else "NOT_PROVEN",
    }


def main() -> int:
    result = check()
    doc = {
        "schema": "agentos.s1-015.dependency-gate/v1",
        "ticket": "S1-015",
        "dependency": result,
        "phase_a_dependencies_proven": result["status"] == "PROVEN",
        "operator_review_dependencies_proven": result["status"] == "PROVEN",
        "population_human_claims_proven": False,
        "inherited_limits": result.get("inherited_limits", []),
        "canonical_db_recheck_required": True,
        "note": ("Tracked-Git proof only; S1-013 canonical DB consistency is "
                 "rechecked at publication. No population/human claim is proven."),
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(doc, indent=2))
    if result["status"] != "PROVEN":
        print(f"BLOCKED_DEPENDENCY: {result['problems']}", file=sys.stderr)
        return 1
    print("DEPENDENCY GATE: S1-013 PROVEN (immutable Git bytes + git archive)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
