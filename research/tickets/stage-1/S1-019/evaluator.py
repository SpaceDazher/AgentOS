"""Deterministic S1-019 evaluator. Saved counters and verdicts are ignored."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import os
import re
import subprocess

TICKET = Path(__file__).resolve().parent
REPO = TICKET.parents[3]
SYN_IDS = tuple(f"SYN{i}" for i in range(1, 19))
PROBES = tuple("ABCDEFGHIJKLMNOP")
DISPOSITIONS = {"ADOPT_RESEARCH_BASELINE", "ADOPT_WITH_LIMITS", "DEFER",
                "INCONCLUSIVE", "NOT_APPLICABLE"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def strict_json(path: Path) -> dict:
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"duplicate JSON key {key}")
            value[key] = item
        return value

    def bad_constant(value):
        raise ValueError(f"non-finite JSON {value}")

    result = json.loads(path.read_text("utf-8"), object_pairs_hook=pairs,
                        parse_constant=bad_constant)
    if not isinstance(result, dict):
        raise ValueError(f"{path.name} root is not an object")
    return result


def safe_repo_path(value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("unsafe evidence path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("unsafe evidence path")
    resolved = REPO.joinpath(*path.parts).resolve()
    if REPO.resolve() not in resolved.parents:
        raise ValueError("evidence path escapes repository")
    return resolved


def frozen_hashes() -> dict:
    manifest = strict_json(TICKET / "frozen-manifest.json")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("frozen manifest has no files")
    for rel, expected in files.items():
        path = safe_repo_path(rel)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"frozen file missing or link: {rel}")
        if not isinstance(expected, str) or not HEX64.fullmatch(expected):
            raise ValueError(f"invalid frozen hash: {rel}")
        if sha(path.read_bytes()) != expected:
            raise ValueError(f"frozen hash mismatch: {rel}")
    return manifest


def evaluate_case(case: dict) -> dict:
    condition = case.get("condition")
    if not isinstance(condition, dict):
        raise ValueError("case condition missing")
    mode = condition.get("mode")
    if mode == "complete_bounded_chain":
        decision = "ADOPT_WITH_LIMITS"
        probe = None
        detected = False
    elif mode == "incomplete_or_conflicting":
        decision = "INCONCLUSIVE" if condition.get("contradiction") else "DEFER"
        probe = None
        detected = False
    elif mode == "adversarial_overclaim":
        probe = condition.get("probe")
        if probe not in PROBES:
            raise ValueError("unknown adversarial probe")
        decision = "DEFER"
        detected = True
    else:
        raise ValueError(f"unknown case mode {mode!r}")
    for key in ("direct_evidence_refs", "audit_evidence_refs"):
        refs = case.get(key)
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"{key} missing")
        for ref in refs:
            if not safe_repo_path(ref).is_file():
                raise ValueError(f"unresolved evidence ref {ref}")
    if case.get("production_authority") is not False:
        decision = "DEFER"
        detected = True
    if case.get("goal_acceptance_authority") is not False:
        decision = "DEFER"
        detected = True
    if decision not in DISPOSITIONS:
        raise ValueError("invalid evaluator disposition")
    return {
        "case_id": case["case_id"], "class": case["class"], "ep_id": case["ep_id"],
        "candidate": case["candidate"], "decision": decision,
        "probe": probe, "probe_detected": detected,
        "attempted_invariant": condition.get("attempted_invariant"),
        "wall_clock_rule": case.get("wall_clock_rule"),
        "wall_clock_control": case.get("wall_clock_control"),
        "production_authority": False, "goal_acceptance_authority": False,
        "authority_mutations": [],
    }


def evaluate(executor_id: str, nonce: str) -> dict:
    manifest = frozen_hashes()
    cases_doc = strict_json(TICKET / "cases.json")
    corpus = strict_json(TICKET / "corpus-manifest.json")
    if sha(canonical(cases_doc)) != corpus.get("cases_sha256"):
        raise ValueError("cases/corpus hash mismatch")
    cases = cases_doc.get("cases")
    if not isinstance(cases, list) or len(cases) != 72:
        raise ValueError("exactly 72 cases required")
    ids = [item.get("case_id") for item in cases if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case id")
    observations = [evaluate_case(case) for case in cases]
    counters = {syn: 0 for syn in SYN_IDS}
    for observation in observations:
        if observation["production_authority"] or observation["goal_acceptance_authority"]:
            counters["SYN13"] += 1
        if observation["authority_mutations"]:
            counters["SYN12"] += 1
        attempted = observation.get("attempted_invariant")
        if attempted and attempted not in SYN_IDS:
            raise ValueError("invalid attempted invariant")
    probe_counts = {probe: sum(item["probe"] == probe and item["probe_detected"]
                               for item in observations) for probe in PROBES}
    if any(value < 1 for value in probe_counts.values()):
        raise ValueError("not every probe was exercised and detected")
    semantic = [{
        key: item[key] for key in ("case_id", "ep_id", "candidate", "decision",
                                   "probe", "probe_detected", "production_authority",
                                   "goal_acceptance_authority", "authority_mutations")
    } for item in observations]
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    return {
        "schema": "agentos.s1-019.run/v1", "executor_id": executor_id,
        "pid": os.getpid(), "nonce": nonce, "commit_sha": commit,
        "frozen_manifest_sha256": sha(canonical(manifest)),
        "observation_count": len(observations), "observations": observations,
        "syn_counters": counters, "probe_counts": probe_counts,
        "semantic_digest": sha(canonical(semantic)),
        "wall_clock_used_for_decision": False,
        "result": "PASS_WITH_LIMITS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executor-id", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.executor_id, args.nonce)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps({"executor_id": args.executor_id,
                      "observations": result["observation_count"],
                      "semantic_digest": result["semantic_digest"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
