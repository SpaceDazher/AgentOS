"""Independent immutable dependency and probe gate for S1-020."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any


PINNED_COMMIT = "78a4218606212c4f65642fe8dbf9c6a808209cfb"
HERE = Path(__file__).resolve().parent


class GateInputError(ValueError):
    pass


class StrictJsonError(GateInputError):
    pass


class PathSafetyError(GateInputError):
    pass


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_strict_json(raw: bytes) -> dict[str, Any]:
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise StrictJsonError(f"duplicate key: {key}")
            out[key] = value
        return out

    def reject(value):
        raise StrictJsonError(f"non-finite number: {value}")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StrictJsonError(str(exc)) from exc
    if not isinstance(value, dict):
        raise StrictJsonError("top-level JSON must be an object")
    return value


def validate_repo_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise PathSafetyError("invalid repository-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.parts[0] in {".git", ".hg"}:
        raise PathSafetyError(f"unsafe path: {value}")
    if re.match(r"^[A-Za-z]:", value):
        raise PathSafetyError(f"drive path forbidden: {value}")
    return value


def _git(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)
    if proc.returncode != 0:
        raise GateInputError(proc.stderr.decode("utf-8", errors="replace").strip())
    return proc.stdout


def resolve_pinned_commit(repo: Path, ref: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise GateInputError("audit ref must be an immutable full commit SHA")
    resolved = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    if resolved != ref:
        raise GateInputError("ref did not resolve exactly")
    return resolved


def read_blob(repo: Path, commit: str, path: str) -> bytes:
    validate_repo_relative_path(path)
    return _git(repo, "show", f"{commit}:{path}")


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GateInputError(f"cannot load verifier {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _verify_helper_integrity(repo: Path, commit: str) -> None:
    paths = [
        "research/tickets/stage-1/S1-019/dependency_gate.py",
        "research/tickets/stage-1/S1-018/dependency_gate.py",
        "research/tickets/stage-1/S1-013/dependency_gate.py",
    ]
    for rel in paths:
        if digest((repo / rel).read_bytes()) != digest(read_blob(repo, commit, rel)):
            raise GateInputError(f"mutable verifier helper differs from pinned blob: {rel}")


def _all_true(values: Any, key: str) -> bool:
    if isinstance(values, dict):
        return bool(values) and all(isinstance(v, dict) and v.get(key) is True
                                    for v in values.values())
    if isinstance(values, list):
        return bool(values) and all(isinstance(v, dict) and v.get(key) is True for v in values)
    return False


def probe_pass(ticket: str, doc: dict[str, Any]) -> bool:
    number = int(ticket[-3:])
    if number in (1, 2):
        audit = (doc.get("artifacts") or {}).get("independent_audit") or {}
        text = str(audit.get("content", "")).upper()
        return str((doc.get("audit") or {}).get("verdict", "")).lower() in {
            "pass", "pass_with_limits"} and text.count("PROBE") >= 2 and "PASS" in text
    if number == 3:
        probes = doc.get("probes") or []
        return (doc.get("verdict") == "pass" and doc.get("passed") == doc.get("total_probes")
                and _all_true(probes, "passed"))
    if number == 4:
        return (doc.get("acceptance") or {}).get("verdict") == "PASS" and \
            (doc.get("probes") or {}).get("all_passed") is True
    if number == 5:
        return str(doc.get("verdict", "")).lower() == "pass_with_limits" and \
            len(doc.get("probe_rejections") or {}) >= 2
    if number in (6, 7):
        probes = doc.get("probes") or []
        return isinstance(probes, list) and len(probes) >= (3 if number == 6 else 4)
    if number == 8:
        return _all_true(doc.get("probe_results") or {}, "detected")
    if number == 9:
        probes = doc.get("probes") or {}
        return bool(probes) and all(str(v.get("outcome", "")).upper() == "PASS"
                                    for v in probes.values())
    if number == 10:
        return doc.get("all_probes_pass") is True and \
            _all_true(doc.get("probes") or {}, "all_pass")
    if number == 11:
        design = (doc.get("designs") or {}).get("minimal-gate") or {}
        return _all_true(design.get("probes") or {}, "passed")
    if number == 12:
        designs = doc.get("designs") or {}
        return all(_all_true((designs.get(name) or {}).get("probes") or {}, "passed")
                   for name in ("digest", "document", "span"))
    if number == 13:
        return doc.get("all_pass") is True and _all_true(doc.get("probes") or {}, "passed")
    if number == 14:
        return doc.get("all_detected") is True and doc.get("control_passed") is True and \
            _all_true(doc.get("probes") or [], "detected")
    if 15 <= number <= 18:
        return doc.get("all_pass") is True and _all_true(doc.get("probes") or {}, "passed")
    if number == 19:
        run_a, run_b = doc.get("run_a") or {}, doc.get("run_b") or {}
        return (doc.get("all_detected") is True and doc.get("benign_controls_present") is True
                and doc.get("manual_counter_increment") is False and bool(run_a)
                and set(run_a) == set(run_b) and all(v > 0 for v in run_a.values())
                and all(v > 0 for v in run_b.values()))
    return False


def _verify_s19(repo: Path, commit: str, record: dict[str, Any]) -> dict[str, Any]:
    problems: list[str] = []
    if record.get("schema") != "agentos.ticket-evaluation-record/v2":
        problems.append("record schema mismatch")
    if record.get("ticket_id") != "S1-019":
        problems.append("ticket id mismatch")
    if str(record.get("result", "")).lower() not in {"pass", "pass_with_limits"}:
        problems.append("result is not closable")
    for key in ("goal_id", "campaign_id", "evaluation_id"):
        if not isinstance(record.get(key), str) or not record[key]:
            problems.append(f"missing {key}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("artifact_chain_hash", ""))):
        problems.append("artifact chain hash invalid")
    if record.get("production_authority") is not False:
        problems.append("production authority expanded")
    if record.get("goal_acceptance_authority") is not False:
        problems.append("goal acceptance authority expanded")

    for label in ("evidence_pack", "ticket_pack", "raw_archive"):
        binding = record.get(label) or {}
        try:
            raw = read_blob(repo, commit, binding["path"])
            if digest(raw) != binding.get("sha256"):
                problems.append(f"{label} file hash mismatch")
                continue
            doc = load_strict_json(raw)
            if label == "evidence_pack":
                payload_hash = digest(json.dumps(
                    {k: v for k, v in doc.items() if k != "sha256"}, sort_keys=True,
                    separators=(",", ":"), ensure_ascii=False,
                    allow_nan=False).encode("utf-8"))
                if doc.get("schema") != "agentos.evidence-pack/v3":
                    problems.append("evidence pack schema mismatch")
                if doc.get("sha256") != payload_hash or binding.get("payload_sha256") != payload_hash:
                    problems.append("evidence pack self hash mismatch")
                research = doc.get("research") or {}
                if doc.get("goal", {}).get("id") != record.get("goal_id"):
                    problems.append("evidence pack goal mismatch")
                if research.get("campaign", {}).get("id") != record.get("campaign_id"):
                    problems.append("evidence pack campaign mismatch")
                if research.get("current_chain_hash") != record.get("artifact_chain_hash"):
                    problems.append("evidence pack chain mismatch")
                if research.get("chain_fresh") is not True or \
                        research.get("latest_evaluation_valid") is not True:
                    problems.append("evidence pack freshness false")
            else:
                payload = doc.get("payload")
                payload_hash = digest(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                                 ensure_ascii=False, allow_nan=False).encode("utf-8"))
                if payload_hash != doc.get("payload_sha256") or \
                        payload_hash != binding.get("payload_sha256"):
                    problems.append(f"{label} payload hash mismatch")
        except (KeyError, GateInputError, StrictJsonError, TypeError, ValueError) as exc:
            problems.append(f"{label} invalid: {exc}")

    tracked = record.get("tracked_artifact_hashes") or {}
    if not isinstance(tracked, dict) or len(tracked) < 20:
        problems.append("tracked artifact map incomplete")
    else:
        for rel, expected in tracked.items():
            try:
                if digest(read_blob(repo, commit, rel)) != expected:
                    problems.append(f"tracked hash mismatch: {rel}")
            except (GateInputError, PathSafetyError):
                problems.append(f"tracked path invalid: {rel}")
    bundle_path = "research/tickets/stage-1/S1-019/bundle.json"
    if digest(read_blob(repo, commit, bundle_path)) != record.get("bundle_sha256"):
        problems.append("bundle hash mismatch")
    return {
        "ticket": "S1-019", "status": "PROVEN" if not problems else "NOT_PROVEN",
        "problems": problems, "result": str(record.get("result", "")).lower(),
        "research_revision": record.get("research_revision"),
        "goal_id": record.get("goal_id"), "campaign_id": record.get("campaign_id"),
        "evaluation_id": record.get("evaluation_id"),
        "artifact_chain_hash": record.get("artifact_chain_hash"),
        "inherited_limits": record.get("limitations") or [],
        "dependency_kind": "direct", "verification_profile": "s1-020-independent-v1",
    }


def run_gate(repo: Path, ref: str = PINNED_COMMIT) -> dict[str, Any]:
    repo = repo.resolve()
    commit = resolve_pinned_commit(repo, ref)
    _verify_helper_integrity(repo, commit)
    previous = _load(repo / "research/tickets/stage-1/S1-019/dependency_gate.py",
                     "s1019_gate_for_s1020")
    prior = previous.run_gate(repo, commit)
    dependencies = list(prior.get("dependencies") or [])
    s19_path = "research/tickets/stage-1/S1-019/evaluation-record.json"
    s19_record = load_strict_json(read_blob(repo, commit, s19_path))
    s19 = _verify_s19(repo, commit, s19_record)
    s19["record_path"] = s19_path
    s19["record_file_sha256"] = digest(read_blob(repo, commit, s19_path))
    dependencies.append(s19)

    registry = load_strict_json((HERE / "probe-registry.json").read_bytes())
    entries = registry.get("entries") or []
    if [row.get("ticket_id") for row in entries] != [f"S1-{n:03d}" for n in range(1, 20)]:
        raise GateInputError("probe registry must contain ordered S1-001..S1-019 exactly once")
    probe_results = []
    for entry in entries:
        ticket = entry["ticket_id"]
        path = validate_repo_relative_path(entry["path"])
        raw = read_blob(repo, commit, path)
        hash_ok = digest(raw) == entry.get("sha256")
        semantic_ok = hash_ok and probe_pass(ticket, load_strict_json(raw))
        probe_results.append({"ticket_id": ticket, "path": path, "sha256": digest(raw),
                              "hash_verified": hash_ok, "semantic_verified": semantic_ok,
                              "passed": hash_ok and semantic_ok})
    deps_ok = len(dependencies) == 19 and all(row.get("status") == "PROVEN"
                                               for row in dependencies)
    probes_ok = all(row["passed"] for row in probe_results)
    return {
        "schema": "agentos.s1-020.dependency-gate/v1", "ticket": "S1-020",
        "verified_commit": commit, "immutable_ref": True,
        "dependencies": dependencies, "dependencies_proven": deps_ok,
        "probe_results": probe_results, "all_prior_probes_pass": probes_ok,
        "producer_id": "agentos-stage-1-ticket-producers",
        "auditor_id": "agentos-s1-020-independent-auditor",
        "auditor_distinct": True,
        "status": "PASS_WITH_LIMITS" if deps_ok and probes_ok else "BLOCKED_DEPENDENCY",
        "canonical_db_recheck_required": True,
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--ref", default=PINNED_COMMIT)
    parser.add_argument("--out", type=Path, default=HERE / "dependency-gate.json")
    args = parser.parse_args()
    try:
        result = run_gate(args.repo, args.ref)
    except Exception as exc:
        result = {"schema": "agentos.s1-020.dependency-gate/v1",
                  "status": "BLOCKED_DEPENDENCY", "dependencies_proven": False,
                  "all_prior_probes_pass": False, "error": str(exc)}
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(json.dumps({"status": result["status"],
                      "dependencies": len(result.get("dependencies") or []),
                      "probes": len(result.get("probe_results") or [])}))
    return 0 if result["status"] == "PASS_WITH_LIMITS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
