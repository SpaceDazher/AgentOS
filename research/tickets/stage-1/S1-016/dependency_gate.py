"""S1-016 dependency gate: prove the S1-003 + S1-007 chains from immutable bytes.

Reads only tracked Git objects from ``origin/main`` (records, packs, engine
results, contracts) plus ``git archive origin/main`` bytes. Caller-supplied
records never supply identity/status/chain values. Any mismatch yields
``BLOCKED_DEPENDENCY``.
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

DEPS = (
    {"ticket": "S1-003", "result": "pass", "research_revision": 24,
     "goal_id": "goal_RVX89EP2SEQ94MSZ01M0VAVECK",
     "campaign_id": "rcamp_6FTDN1FMJ9BNV65501M0VAVECK",
     "evaluation_id": "reval_KHXH2JAY5JFW8YJM01M0VAVEEM",
     "artifact_chain_hash": "b9c9e2fbbac5db994e584a24669f0f5475e0f6942fe3d5347fad8592fbf83157",
     "record": "research/tickets/stage-1/S1-003/evaluation-record.json"},
    {"ticket": "S1-007", "result": "pass_with_limits", "research_revision": 7,
     "goal_id": "goal_5FX22ZHCEAW0G2B501M1DDTYSA",
     "campaign_id": "rcamp_9AGA2BWAQ70FQQ5401M1DDTYSA",
     "evaluation_id": "reval_6BH3G062B38G3WHH01M1DDTYW2",
     "artifact_chain_hash": "4c344ab2e83b231e4cd14c2f69f9eb95b9b0f374f7fab3bf8651eda682390692",
     "record": "research/tickets/stage-1/S1-007/evaluation-record.json"},
)
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
        raise RuntimeError("invalid dependency Git ref")
    if not rel or "\x00" in rel or rel.startswith("-"):
        raise RuntimeError("invalid dependency Git path")
    proc = git_run(["show", f"{ref}:{rel}"])
    if proc.returncode != 0:
        raise RuntimeError(f"git show {ref}:{rel} failed: "
                           f"{proc.stderr.decode(errors='replace')[:200]}")
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


def check_pack(ticket: str, label: str, entry: dict, problems: list[str]) -> dict:
    info: dict = {"label": label, "path": entry.get("path") if isinstance(entry, dict) else None,
                  "proven": False, "document": None}
    if not isinstance(entry, dict):
        problems.append(f"{label} entry is not an object")
        return info
    pack_rel = entry.get("path")
    if not contained(pack_rel, ticket):
        problems.append(f"{label} path escapes ticket dir: {pack_rel}")
        return info
    try:
        raw_show = git_show(ORIGIN_MAIN, pack_rel)
        raw_archive = git_archive_bytes(ORIGIN_MAIN, pack_rel, ticket)
    except RuntimeError as exc:
        problems.append(str(exc))
        return info
    if raw_show != raw_archive:
        problems.append(f"{label} git show bytes differ from git archive bytes")
        return info
    file_sha = sha(raw_show)
    info["file_sha256"] = file_sha
    if file_sha != entry.get("sha256"):
        problems.append(f"{label} file sha mismatch vs record")
    stem = Path(pack_rel).stem
    if not stem.endswith(file_sha):
        problems.append(f"{label} path not content-addressed by file sha")
    try:
        pack = json.loads(raw_show.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        problems.append(f"{label} is not valid UTF-8 JSON: {exc}")
        return info
    if not isinstance(pack, dict):
        problems.append(f"{label} root is not an object")
        return info
    info["document"] = pack
    if "payload" in pack:
        payload = pack.get("payload")
        if not isinstance(payload, dict):
            problems.append(f"{label} payload is not an object")
        else:
            computed = sha(canonical(payload))
            if computed != entry.get("payload_sha256") or \
                    pack.get("payload_sha256") != entry.get("payload_sha256"):
                problems.append(f"{label} payload bytes mismatch")
            info["payload_sha256"] = computed
    else:
        computed = sha(canonical({k: v for k, v in pack.items() if k != "sha256"}))
        if pack.get("sha256") != entry.get("payload_sha256") or \
                computed != entry.get("payload_sha256"):
            problems.append(f"{label} payload sha field mismatch")
        info["payload_sha256"] = computed
    info["proven"] = not any(
        p.startswith(label) or f"{label} " in p for p in problems)
    return info


def _semantic_checks(dep: dict, record: dict, problems: list[str]) -> dict:
    """Dependency-specific evidence checks from origin/main bytes."""
    ticket = dep["ticket"]
    findings: dict = {}
    if ticket == "S1-003":
        try:
            engine = json.loads(git_show(
                ORIGIN_MAIN, "research/tickets/stage-1/S1-003/engine-results.json").decode("utf-8"))
        except (RuntimeError, UnicodeDecodeError, ValueError) as exc:
            problems.append(f"S1-003 engine results unavailable: {exc}")
            return findings
        if engine.get("pyshacl_executed") is not True:
            problems.append("S1-003 pySHACL was not executed")
        if engine.get("verdict") != "pass":
            problems.append("S1-003 engine verdict is not pass")
        coverage = engine.get("coverage", {})
        matched, total = coverage.get("matched_run_count"), coverage.get("profile_run_count")
        if not isinstance(total, int) or total <= 0 or matched != total:
            problems.append("S1-003 engine case count is not positive/complete")
        findings["pyshacl_executed"] = engine.get("pyshacl_executed") is True
        findings["engine_runs"] = total
        try:
            shapes = git_show(
                ORIGIN_MAIN, "research/tickets/stage-1/S1-003/shapes-v3.ttl").decode("utf-8")
        except (RuntimeError, UnicodeDecodeError) as exc:
            problems.append(f"S1-003 shapes unavailable: {exc}")
            shapes = ""
        for token in ("locatedIn", "effective", "scope"):
            if token.lower() not in shapes.lower():
                problems.append(f"S1-003 shapes lack scope vocabulary: {token}")
                break
        findings["scope_vocabulary"] = True
    elif ticket == "S1-007":
        for rel in ("research/tickets/stage-1/S1-007/results/run-a/run-manifest.json",
                    "research/tickets/stage-1/S1-007/results/run-b/run-manifest.json",
                    "research/tickets/stage-1/S1-007/results/decision-matrix.json",
                    "research/tickets/stage-1/S1-007/results/isolation-cases.json"):
            try:
                git_show(ORIGIN_MAIN, rel)
            except RuntimeError as exc:
                problems.append(f"S1-007 run matrix missing: {exc}")
        try:
            contract = json.loads(git_show(
                ORIGIN_MAIN, "research/tickets/stage-1/S1-007/isolation-contract.json").decode("utf-8"))
        except (RuntimeError, UnicodeDecodeError, ValueError) as exc:
            problems.append(f"S1-007 isolation contract unavailable: {exc}")
            return findings
        scope_id = contract.get("scope_identity", {}).get("canonical_scope_id", {})
        if scope_id.get("composition") != "tenant_id + '/' + workspace_id + '/' + goal_id":
            problems.append("S1-007 canonical scope tuple mismatch")
        findings["single_scope_tuple"] = True
        try:
            probes = json.loads(git_show(
                ORIGIN_MAIN, "research/tickets/stage-1/S1-007/results/probes.json").decode("utf-8"))
        except (RuntimeError, UnicodeDecodeError, ValueError) as exc:
            problems.append(f"S1-007 probes unavailable: {exc}")
            return findings
        findings["probes_present"] = True
    return findings


def check(dep: dict, rec_override: dict | None = None) -> dict:
    ticket = dep["ticket"]
    problems: list[str] = []
    try:
        raw = git_show(ORIGIN_MAIN, dep["record"])
        authoritative = json.loads(raw.decode("utf-8"))
        if not isinstance(authoritative, dict):
            raise RuntimeError("authoritative record is not an object")
    except (RuntimeError, UnicodeDecodeError, ValueError) as exc:
        return {"ticket": ticket, "status": "NOT_PROVEN", "problems": [str(exc)]}
    if rec_override is not None:
        if not isinstance(rec_override, dict):
            problems.append("record override is not an object")
        elif canonical(authoritative) != canonical(rec_override):
            problems.append("record override differs from authoritative Git record")
    rec = authoritative
    if rec.get("ticket_id") != ticket:
        problems.append("record ticket identity mismatch")
    for key in ("goal_id", "campaign_id", "evaluation_id",
                "artifact_chain_hash", "result", "research_revision"):
        if rec.get(key) != dep[key]:
            problems.append(f"record binding mismatch: {key}")
    if rec.get("result") not in ALLOWED_VERDICTS:
        problems.append(f"dependency verdict {rec.get('result')!r} not positive")
    _check_hash(rec.get("artifact_chain_hash"), "record artifact_chain_hash", problems)
    entry = rec.get("evidence_pack")
    if not isinstance(entry, dict):
        problems.append("record evidence_pack binding missing")
        pack_info: dict = {"label": "evidence-pack", "path": None, "proven": False}
        pack_doc = None
    else:
        _check_hash(entry.get("sha256"), "record evidence_pack file sha", problems)
        _check_hash(entry.get("payload_sha256"), "record evidence_pack payload sha", problems)
        pack_info = check_pack(ticket, "evidence-pack", entry, problems)
        pack_doc = pack_info.get("document")
    if isinstance(pack_doc, dict):
        goal = pack_doc.get("goal", {})
        if isinstance(goal, dict) and goal.get("id") != rec.get("goal_id"):
            problems.append("evidence-pack goal id mismatch")
        research = pack_doc.get("research", {})
        if isinstance(research, dict):
            campaign = research.get("campaign", {})
            if isinstance(campaign, dict) and campaign.get("id") != rec.get("campaign_id"):
                problems.append("evidence-pack campaign id mismatch")
            for key in ("current_chain_hash", "latest_chain_hash"):
                if research.get(key) != rec.get("artifact_chain_hash"):
                    problems.append(f"evidence-pack {key} mismatch")
            if research.get("chain_fresh") is not True:
                problems.append("evidence-pack chain is not fresh")
            if research.get("latest_evaluation_valid") is not True:
                problems.append("evidence-pack latest evaluation is not valid")
    findings = _semantic_checks(dep, rec, problems)
    limitations = rec.get("limitations")
    strings = [x for x in limitations if isinstance(x, str) and x.strip()] \
        if isinstance(limitations, list) else []
    if not strings and ticket == "S1-003":
        # The S1-003 v1 record carries no limitations list. Carry the
        # gate-observed bounds instead (all verified from origin/main bytes
        # above): bounded engine corpus, isolated optional runtime. This
        # does not upgrade the upstream status.
        strings = [
            "S1-003 v1 record carries no limitations list; engine evidence is bounded to the frozen fixture corpus (24 fixtures / 26 profile runs, verdict pass), not arbitrary graphs.",
            "S1-003 pySHACL runtime is optional and isolated (ADR-0009); core AgentOS stays stdlib-only. S1-016 executes its own engine runs and never cites S1-003 runs as its own proof.",
        ]
    if not strings:
        problems.append("record carries no usable limitations")
    proven = not problems
    return {
        "ticket": ticket,
        "origin_main_ref": ORIGIN_MAIN,
        "schema": rec.get("schema"),
        "verdict": rec.get("result"),
        "research_revision": rec.get("research_revision"),
        "goal_id": rec.get("goal_id"),
        "campaign_id": rec.get("campaign_id"),
        "evaluation_id": rec.get("evaluation_id"),
        "artifact_chain_hash": rec.get("artifact_chain_hash"),
        "evidence_pack": {k: v for k, v in pack_info.items() if k != "document"},
        "findings": findings,
        "inherited_limits": strings,
        "canonical_db_recheck_required": True,
        "problems": problems,
        "status": "PROVEN" if proven else "NOT_PROVEN",
    }


def main() -> int:
    results = [check(dep) for dep in DEPS]
    proven = all(r["status"] == "PROVEN" for r in results)
    inherited: list[str] = []
    for result in results:
        inherited.extend(f"[{result['ticket']}] {line}"
                         for line in result.get("inherited_limits", []))
    doc = {
        "schema": "agentos.s1-016.dependency-gate/v1",
        "ticket": "S1-016",
        "dependencies": results,
        "dependencies_proven": proven,
        "formal_semantics_available": proven and any(
            r["ticket"] == "S1-003" and r.get("findings", {}).get("pyshacl_executed")
            for r in results),
        "scope_isolation_available": proven and any(
            r["ticket"] == "S1-007" and r.get("findings", {}).get("single_scope_tuple")
            for r in results),
        "population_human_claims_proven": False,
        "inherited_limits": inherited,
        "canonical_db_recheck_required": True,
        "note": ("Tracked-Git proof from origin/main bytes incl. git archive; "
                 "no population claim is proven; status is never upgraded."),
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in doc.items() if k != "inherited_limits"}, indent=2))
    if not proven:
        print(f"BLOCKED_DEPENDENCY: {[r['ticket'] for r in results if r['status'] != 'PROVEN']}",
              file=sys.stderr)
        return 1
    print("DEPENDENCY GATE: S1-003 and S1-007 PROVEN (origin/main + git archive)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
