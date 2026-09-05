"""S1-017 dependency gate: prove S1-004 + S1-016 from immutable Git bytes.

S1-004 bindings are fixed by the task text. S1-016 bindings are DISCOVERED
programmatically from `origin/main` (never from the task text, chat or an
unmerged branch) after canonicalization. Pack bytes are verified through
`git archive`, not the working tree. Any mismatch => BLOCKED_DEPENDENCY.
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
REPO = TICKET.parents[3]
OUT = TICKET / "dependency-gate.json"

REF = "origin/main"

# Fixed by TASK_FOR_AGENT.md §2 (allowed: task-stated expectations).
S1_004_EXPECTED = {
    "ticket_id": "S1-004",
    "result": "pass_with_limits",
    "research_revision": 7,
    "goal_id": "goal_Z9TP87YGTAMDPD9801M18BSRXE",
    "evaluation_id": "reval_5JJ8C83TCA8CNQ5Q01M18BSRZX",
    "chain_prefix": "ce1fcfd5",
    "chain_suffix": "1d349",
    "tracked_pack": "research/tickets/stage-1/S1-004/results/evidence/"
                    "evidence-pack-98f6b998909983706ea993e6877b56b003bb64f5228a"
                    "50559bdb4e01feb98841.json",
}

# S1-016 is DISCOVERED from origin/main; only structural expectations here.
S1_016_REQUIRED = {
    "ticket_id": "S1-016",
    "schema": "agentos.ticket-evaluation-record/v2",
    "allowed_results": {"pass_with_limits"},
    "record": "research/tickets/stage-1/S1-016/evaluation-record.json",
    "lineage_contract": "research/tickets/stage-1/S1-016/lineage-contract.json",
    "ticket_pack_glob": "research/tickets/stage-1/S1-016/results/evidence/ticket-pack-*.json",
}

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*argv: str, binary: bool = False):
    proc = subprocess.run(["git", "-C", str(REPO), *argv], capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(argv[:2])} failed: "
                           f"{proc.stderr.decode('utf-8', 'replace')[:200]}")
    return proc.stdout if binary else proc.stdout.decode("utf-8").strip()


def ref_commit() -> str:
    return git("rev-parse", REF)


def show_bytes(path: str) -> bytes:
    return git("show", f"{REF}:{path}", binary=True)


def archive_file(commit: str, path: str) -> bytes:
    proc = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar",
                           commit, "--", path], capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"git archive missing {path}")
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
        member = tar.getmember(path)
        return tar.extractfile(member).read()


def load_ref_json(path: str) -> dict:
    return json.loads(show_bytes(path).decode("utf-8"))


def verify_s1_004() -> dict:
    problems: list[str] = []
    record = load_ref_json("research/tickets/stage-1/S1-004/evaluation-record.json")
    for key, expected in S1_004_EXPECTED.items():
        if key in ("tracked_pack", "chain_prefix", "chain_suffix"):
            continue
        if record.get(key) != expected:
            problems.append(f"S1-004 {key}: {record.get(key)!r} != {expected!r}")
    chain = record.get("artifact_chain_hash", "")
    if not (isinstance(chain, str) and HEX64.match(chain)
            and chain.startswith(S1_004_EXPECTED["chain_prefix"])
            and chain.endswith(S1_004_EXPECTED["chain_suffix"])):
        problems.append("S1-004 chain hash mismatch")
    pack_path = S1_004_EXPECTED["tracked_pack"]
    try:
        raw = archive_file(ref_commit(), pack_path)
    except RuntimeError as exc:
        problems.append(str(exc))
        raw = b""
    if raw and sha(raw) not in pack_path:
        problems.append("S1-004 pack filename is not content-addressed")
    # Formal execution markers (Alloy/TLC evidence must be stated honestly).
    markers = json.dumps(record).lower()
    for marker in ("alloy", "tlc"):
        if marker not in markers:
            problems.append(f"S1-004 formal execution marker missing: {marker}")
    limitations = " ".join(record.get("limitations", [])).lower()
    if "bounded" not in limitations or "no unbounded proof" not in limitations:
        problems.append("S1-004 honest limits not stated")
    return {"record": {k: record.get(k) for k in
                       ("ticket_id", "result", "research_revision", "goal_id",
                        "evaluation_id", "artifact_chain_hash")},
            "pack": {"path": pack_path, "file_sha256": sha(raw) if raw else None,
                     "proven": not problems},
            "problems": problems}


def verify_s1_016() -> dict:
    problems: list[str] = []
    record = load_ref_json(S1_016_REQUIRED["record"])
    for key, expected in (("ticket_id", S1_016_REQUIRED["ticket_id"]),
                          ("schema", S1_016_REQUIRED["schema"])):
        if record.get(key) != expected:
            problems.append(f"S1-016 {key} mismatch: {record.get(key)!r}")
    if record.get("result") not in S1_016_REQUIRED["allowed_results"]:
        problems.append(f"S1-016 result {record.get('result')!r} not allowed")
    for key in ("goal_id", "campaign_id", "evaluation_id", "artifact_chain_hash",
                "research_revision"):
        value = record.get(key)
        if not value:
            problems.append(f"S1-016 {key} missing")
    chain = record.get("artifact_chain_hash", "")
    if not (isinstance(chain, str) and HEX64.match(chain)):
        problems.append("S1-016 chain hash malformed")
    packs = []
    for key in ("evidence_pack", "ticket_pack"):
        info = record.get(key, {})
        path = info.get("path", "")
        try:
            raw = archive_file(ref_commit(), path)
        except RuntimeError as exc:
            problems.append(str(exc))
            continue
        if sha(raw) != info.get("sha256") or sha(raw) not in path:
            problems.append(f"S1-016 {key} not content-addressed/hash mismatch")
        packs.append({"label": key, "path": path,
                      "file_sha256": sha(raw),
                      "payload_sha256": info.get("payload_sha256")})
    # S1-016 must not grant provenance edges any policy authority (L6).
    contract_text = show_bytes(S1_016_REQUIRED["lineage_contract"]).decode("utf-8")
    non_authority_ok = ("never" in contract_text.lower() and
                        ("authoriz" in contract_text.lower()))
    if not non_authority_ok:
        problems.append("S1-016 lineage contract lacks provenance non-authority")
    ticket_pack = next((p for p in packs if p["label"] == "ticket_pack"), None)
    decision = None
    if ticket_pack:
        doc = json.loads(archive_file(ref_commit(), ticket_pack["path"]))
        closure = doc.get("payload", {}).get("closure", {})
        decision = closure.get("design_decision")
        if decision not in ("FLAT_RUNTIME_PROV_EXPORT", "RICH_RUNTIME_PROV_DICTIONARY",
                            "HYBRID_MINIMAL_LINEAGE", "INCONCLUSIVE"):
            problems.append(f"S1-016 closure decision invalid: {decision!r}")
        if closure.get("human_study_n") not in (0, None):
            problems.append("S1-016 closure claims human data")
    return {"record": {k: record.get(k) for k in
                       ("ticket_id", "result", "research_revision", "goal_id",
                        "campaign_id", "evaluation_id", "artifact_chain_hash")},
            "closure_design_decision": decision,
            "packs": packs,
            "provenance_non_authority": non_authority_ok,
            "problems": problems}


def main() -> int:
    commit = ref_commit()
    s004 = verify_s1_004()
    s016 = verify_s1_016()
    problems = s004["problems"] + s016["problems"]
    doc = {
        "schema": "agentos.s1-017.dependency-gate/v1",
        "ticket": "S1-017",
        "verified_ref": REF,
        "verified_commit": commit,
        "dependencies": {"S1-004": s004, "S1-016": s016},
        "dependencies_proven": not problems,
        "formal_semantics_available": not s004["problems"],
        "lineage_baseline_available": not s016["problems"],
        "inherited_limits": [
            "S1-004: bounded Alloy/TLC/simulation evidence, not arbitrary-system proof",
            "S1-016: bounded 48-scenario corpus, same-host replay, profile-bound "
            "PROV subset; design decision INCONCLUSIVE with substance leader "
            "FLAT_RUNTIME_PROV_EXPORT; no provenance authority",
            "no human or production data anywhere in the chain",
        ],
        "problems": problems,
        "status": "PROVEN" if not problems else "BLOCKED_DEPENDENCY",
    }
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"DEPENDENCY GATE: {doc['status']} (ref {REF} = {commit[:12]})")
    for problem in problems:
        print(f"  - {problem}")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
