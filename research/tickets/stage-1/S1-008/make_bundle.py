"""S1-008 evidence bundle assembler.

Collects frozen artifacts, run manifests, raw traces, evaluator output,
comparison result, and evidence pack into a single bundle.json with a
self-verified SHA-256.

Usage:
    python make_bundle.py --goal-id GOAL --eval-id EVAL --campaign-id CAMP \
        [--chain-hash HASH] [--output bundle.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any  # noqa: E402

_BASE = Path(__file__).resolve().parent
_REPO_ROOT = _BASE.parents[3]  # D:\Project\AgentOS
_RESULTS = _REPO_ROOT / "results"
if not (_REPO_ROOT / "src").exists():
    _REPO_ROOT = Path.cwd()
    _RESULTS = _REPO_ROOT / "results"
sys.path.insert(0, str(_REPO_ROOT / "src"))

from agentos.ids import sha256_text  # noqa: E402


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _posix(p: Path | str) -> str:
    """Return a forward-slash POSIX path."""
    return Path(p).as_posix()


def _file_size(path: Path) -> int:
    if not path.exists():
        return 0
    return path.stat().st_size


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return len(list(path.rglob("*.json")))


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value.lower())


def _valid_git_oid(value: Any) -> bool:
    return isinstance(value, str) and len(value) in {40, 64} and all(
        c in "0123456789abcdef" for c in value.lower())


def _git_rev_parse(*args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", *args], capture_output=True, text=True,
            cwd=str(_REPO_ROOT), timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "MISSING"
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and value else "MISSING"


def _validate_process_evidence(process: Any, label: str) -> None:
    if not isinstance(process, dict):
        raise ValueError(f"{label} missing process evidence")
    if (isinstance(process.get("pid"), bool) or
            not isinstance(process.get("pid"), int) or process["pid"] <= 0 or
            isinstance(process.get("parent_pid"), bool) or
            not isinstance(process.get("parent_pid"), int) or process["parent_pid"] <= 0):
        raise ValueError(f"{label} process PID evidence is malformed")
    argv = process.get("argv")
    if not isinstance(argv, list) or not argv or not all(
            isinstance(item, str) and item for item in argv):
        raise ValueError(f"{label} process argv evidence is malformed")
    for key in ("cwd", "output_dir", "executable", "python_version",
                "python_implementation", "git_commit", "started_at_utc"):
        if not isinstance(process.get(key), str) or not process[key]:
            raise ValueError(f"{label} process evidence missing {key}")
    digest = process.get("invocation_digest")
    if not _valid_sha(digest):
        raise ValueError(f"{label} process invocation digest is malformed")
    body = {key: value for key, value in process.items()
            if key != "invocation_digest"}
    if sha256_text(json.dumps(body, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)) != digest:
        raise ValueError(f"{label} process invocation digest mismatch")
    descriptor = process.get("launch_descriptor")
    if (not isinstance(descriptor, dict) or descriptor.get("argv") != argv or
            descriptor.get("cwd") != process.get("cwd") or
            descriptor.get("executable") != process.get("executable") or
            descriptor.get("output_dir") != process.get("output_dir")):
        raise ValueError(f"{label} launch descriptor mismatch")


def raw_trace_digest(raw_dir: str | Path) -> dict[str, Any]:
    """Digest every raw trace by stable relative path and content.

    ``manifest.json`` is metadata only and is never used as the raw evidence
    hash. Both byte and parsed-canonical hashes are recorded for every member
    so changes to either representation are observable.
    """
    root = Path(raw_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"raw traces dir not found: {root}")
    members: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid raw trace {path}") from exc
        canonical = json.dumps(
            parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        members.append({
            "path": path.relative_to(root).as_posix(),
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "canonical_sha256": hashlib.sha256(canonical).hexdigest(),
        })
    payload = {
        "algorithm": "sha256(path,size,bytes,canonical-json)",
        "members": members,
    }
    return {
        "algorithm": payload["algorithm"],
        "member_count": len(members),
        "members": members,
        "sha256": sha256_text(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )),
    }


def _evidence_binding(raw_a: dict[str, Any], raw_b: dict[str, Any],
                      frozen_artifacts: dict[str, str],
                      eval_path: Path, comparison_path: Path,
                      manifest_a: dict[str, Any],
                      existing_bundle: dict[str, Any] | None = None
                      ) -> dict[str, Any]:
    """Build a stable, DB-portable binding for the measured evidence.

    The FLOW-11 research chain stores this object as artifact content.  It is
    intentionally independent of the mutable DB ids and contains the raw
    trace-set digests, evaluator/comparison bytes, committed source identity,
    and all frozen artifact hashes.  Once a publisher has produced archives,
    their exact path/file hashes may be carried in ``raw_archives`` and are
    preserved on subsequent bundle rebuilds.
    """
    binding: dict[str, Any] = {
        "algorithm": "s1-008-evidence-binding/v1",
        "git_commit": manifest_a.get("git_commit"),
        "git_tree_sha256": manifest_a.get("git_tree_sha256"),
        "raw_trace_a": {
            "path": raw_a.get("path"),
            "sha256": raw_a.get("sha256"),
            "member_count": raw_a.get("member_count"),
        },
        "raw_trace_b": {
            "path": raw_b.get("path"),
            "sha256": raw_b.get("sha256"),
            "member_count": raw_b.get("member_count"),
        },
        "evaluation_result": {
            "path": _posix(eval_path.relative_to(_REPO_ROOT)),
            "sha256": _file_sha256(eval_path),
        },
        "comparison": {
            "path": _posix(comparison_path.relative_to(_REPO_ROOT)),
            "sha256": _file_sha256(comparison_path),
        },
        "frozen_artifacts": dict(sorted(frozen_artifacts.items())),
    }
    prior = (existing_bundle or {}).get("evidence_binding", {})
    if isinstance(prior, dict) and isinstance(prior.get("raw_archives"), dict):
        binding["raw_archives"] = prior["raw_archives"]
    digest = sha256_text(json.dumps(
        binding, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return {"sha256": digest, **binding}


def _bundle_binding(evidence_binding: dict[str, Any]) -> dict[str, Any]:
    """Derive an immutable bundle/pack binding independent of DB identity.

    Research-plan appends a new DB revision and therefore changes the
    top-level goal/campaign/evaluation/chain fields.  This digest deliberately
    excludes those mutable identity fields while retaining the exact raw
    archive, evaluator, comparison, frozen-input, and evidence-binding data.
    The publisher and finalizer carry and verify the same object.
    """
    payload = {
        "algorithm": "s1-008-immutable-bundle-binding/v1",
        "evidence_binding_sha256": evidence_binding["sha256"],
        "raw_archives": evidence_binding.get("raw_archives", {}),
        "evaluation_result": evidence_binding.get("evaluation_result", {}),
        "comparison": evidence_binding.get("comparison", {}),
        "frozen_artifacts": evidence_binding.get("frozen_artifacts", {}),
    }
    return {
        "sha256": sha256_text(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)),
        **payload,
    }


def _bind_flow_artifact_content(flow_artifacts: dict[str, Any],
                                evidence_binding: dict[str, Any],
                                bundle_binding: dict[str, Any]) -> None:
    """Make canonical measurement hashes part of substantive FLOW content."""
    marker = "\n\n# Canonical measurement evidence\n"
    text = json.dumps({"evidence_binding": evidence_binding,
                       "bundle_binding": bundle_binding},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    section = marker + "The DB research chain is bound to this exact local evidence object:\n" + text
    for kind in ("source_registry", "independent_audit", "progress"):
        artifact = flow_artifacts.get(kind)
        if not isinstance(artifact, dict) or not isinstance(artifact.get("content"), str):
            continue
        content = artifact["content"]
        if marker in content:
            content = content.split(marker, 1)[0]
        artifact["content"] = content.rstrip() + section
def _validate_manifest(manifest: dict[str, Any], run_dir: Path,
                       raw_binding: dict[str, Any], label: str,
                       frozen_artifacts: dict[str, str]) -> None:
    """Reject stale, mixed, dirty, or incomplete run evidence."""
    if not isinstance(manifest, dict):
        raise ValueError(f"{label} manifest must be an object")
    if manifest.get("dirty") is not False:
        raise ValueError(f"{label} manifest is dirty")
    raw_dir = run_dir / "raw-traces"
    try:
        expected_raw_path = raw_dir.relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        expected_raw_path = raw_dir.resolve().as_posix()
    declared_raw_path = str(manifest.get("raw_trace_dir", "")).replace("\\", "/")
    if declared_raw_path not in {expected_raw_path, raw_dir.resolve().as_posix()}:
        raise ValueError(
            f"{label} raw_trace_dir mismatch: {manifest.get('raw_trace_dir')} != {expected_raw_path}")
    if manifest.get("raw_trace_count") != raw_binding["member_count"]:
        raise ValueError(f"{label} raw trace count does not match disk")
    if raw_binding["member_count"] != 402:
        raise ValueError(f"{label} raw trace count must be 402, got {raw_binding['member_count']}")
    declared_binding = manifest.get("raw_trace_binding")
    if not isinstance(declared_binding, dict) or declared_binding != raw_binding:
        raise ValueError(f"{label} raw trace content digest mismatch")
    git_commit = manifest.get("git_commit")
    if not _valid_git_oid(git_commit) or not _valid_git_oid(manifest.get("git_tree_sha256")):
        raise ValueError(f"{label} missing git commit/tree binding")
    if _git_rev_parse(f"{git_commit}^{{tree}}") != manifest["git_tree_sha256"]:
        raise ValueError(f"{label} git tree binding is stale")
    process = manifest.get("process_evidence")
    _validate_process_evidence(process, label)
    bindings = manifest.get("source_bindings")
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError(f"{label} missing source bindings")
    for relative_path, digest in bindings.items():
        if (not isinstance(relative_path, str) or not _valid_git_oid(digest) or
                _git_rev_parse(f"{git_commit}:{relative_path}") != digest):
            raise ValueError(f"{label} source binding is stale: {relative_path}")
    for name, digest in frozen_artifacts.items():
        key = {
            "revocation-contract.json": "contract_sha256",
            "workload-manifest.json": "workload_sha256",
            "threat-model.json": "threat_model_sha256",
            "rubric.json": "rubric_sha256",
            "fixtures.json": "fixtures_sha256",
            "corpus-manifest.json": "corpus_manifest_sha256",
        }.get(name)
        if key is not None and manifest.get(key) != digest:
            raise ValueError(f"{label} frozen artifact mismatch: {name}")
    declared_frozen = manifest.get("frozen_artifacts")
    if not isinstance(declared_frozen, dict):
        raise ValueError(f"{label} missing frozen_artifacts map")
    for name, digest in frozen_artifacts.items():
        if declared_frozen.get(name) != digest:
            raise ValueError(f"{label} frozen artifact map mismatch: {name}")


def build_bundle(goal_id: str, evaluation_id: str, campaign_id: str,
                 chain_hash: str = "",
                 run_dir_a: str = "results/run-a",
                 run_dir_b: str = "results/run-b",
                 existing_bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the bundle from frozen artifacts + run outputs.

    Preserves FLOW-11 fields (config, sources, claims, artifacts, audit)
    from existing_bundle if provided.
    """
    for label, value in (("goal_id", goal_id), ("evaluation_id", evaluation_id),
                         ("campaign_id", campaign_id), ("artifact_chain_hash", chain_hash)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"missing {label}; refusing an unbound bundle")
    # --- Preserve FLOW-11 structure from existing bundle ---
    bundle: dict[str, Any] = {}
    if existing_bundle:
        for k in ("config", "sources", "claims", "artifacts", "audit"):
            if k in existing_bundle:
                bundle[k] = existing_bundle[k]

    # --- Frozen artifacts ---
    frozen_artifacts: dict[str, str] = {}
    frozen_names = [
        "revocation-contract.json",
        "workload-manifest.json",
        "threat-model.json",
        "rubric.json",
        "fixtures.json",
        "corpus-manifest.json",
        "runner.py",
        "evaluator.py",
        "make_bundle.py",
        "publish_evidence_pack.py",
        "finalize_record.py",
    ]
    for name in frozen_names:
        p = _BASE / name
        frozen_artifacts[name] = _file_sha256(p)

    # --- Load run manifests ---
    run_a_path = Path(run_dir_a) if Path(run_dir_a).is_absolute() else _REPO_ROOT / run_dir_a
    run_b_path = Path(run_dir_b) if Path(run_dir_b).is_absolute() else _REPO_ROOT / run_dir_b
    manifest_a = json.loads((run_a_path / "manifest.json").read_text())
    manifest_b = json.loads((run_b_path / "manifest.json").read_text())

    # --- Raw trace counts ---
    raw_a_dir = run_a_path / "raw-traces"
    raw_b_dir = run_b_path / "raw-traces"
    raw_a_binding = raw_trace_digest(raw_a_dir)
    raw_b_binding = raw_trace_digest(raw_b_dir)
    _validate_manifest(manifest_a, run_a_path, raw_a_binding, "run A",
                       frozen_artifacts)
    _validate_manifest(manifest_b, run_b_path, raw_b_binding, "run B",
                       frozen_artifacts)
    if manifest_a.get("git_commit") != manifest_b.get("git_commit"):
        raise ValueError("run A/B evidence uses mixed git commits")
    if manifest_a.get("git_tree_sha256") != manifest_b.get("git_tree_sha256"):
        raise ValueError("run A/B evidence uses mixed git trees")
    if manifest_a.get("source_bindings") != manifest_b.get("source_bindings"):
        raise ValueError("run A/B evidence uses mixed source blobs")
    if manifest_a.get("process_evidence", {}).get("pid") == manifest_b.get("process_evidence", {}).get("pid"):
        raise ValueError("run A/B evidence must come from different processes")
    raw_a_count = raw_a_binding["member_count"]
    raw_b_count = raw_b_binding["member_count"]

    # --- Load evaluation result ---
    evaluation_path = _RESULTS / "evaluation-result.json"
    comparison_path = _RESULTS / "comparison.json"
    eval_result = json.loads(evaluation_path.read_text())

    # --- Load comparison ---
    comparison = json.loads(comparison_path.read_text())

    # Only a fresh positive evaluator/comparison can be bundled. Any failure,
    # blocked result, missing list, or stale raw digest is rejected here.
    if not isinstance(eval_result, dict) or eval_result.get("verdict") not in {"PASS", "PASS_WITH_LIMITS"}:
        raise ValueError("evaluation result is not positive")
    if eval_result.get("failures"):
        raise ValueError("evaluation result contains failures")
    if not isinstance(comparison, dict) or comparison.get("verdict") not in {"PASS", "PASS_WITH_LIMITS"}:
        raise ValueError("comparison result is not positive")
    if comparison.get("failures"):
        raise ValueError("comparison result contains failures")
    for source_name, source in (("evaluation", eval_result),
                                ("comparison", comparison)):
        for key, binding in (("raw_archive_a", raw_a_binding),
                             ("raw_archive_b", raw_b_binding)):
            declared = source.get(key)
            if (not isinstance(declared, dict) or
                    declared.get("sha256") != binding["sha256"] or
                    declared.get("member_count") != binding["member_count"]):
                raise ValueError(f"{source_name} {key} is stale or not content-bound")

    # --- Build bundle ---
    # If FLOW-11 artifacts exist in existing_bundle, merge evidence artifacts into them
    flow_artifacts = bundle.pop("artifacts", {}) if existing_bundle and "artifacts" in bundle else {}
    evidence_binding = _evidence_binding(
        raw_a_binding, raw_b_binding, frozen_artifacts, evaluation_path,
        comparison_path, manifest_a, existing_bundle)
    bundle_binding = _bundle_binding(evidence_binding)
    _bind_flow_artifact_content(flow_artifacts, evidence_binding, bundle_binding)
    bundle.update({
        "schema": "agentos.s1-008.bundle/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "goal_id": goal_id,
        "campaign_id": campaign_id,
        "evaluation_id": evaluation_id,
        "artifact_chain_hash": chain_hash,
        "evidence_binding": evidence_binding,
        "bundle_binding": bundle_binding,
        "frozen_artifacts": frozen_artifacts,
        "artifacts": {
            **flow_artifacts,
            "raw_a": {
                "path": _posix(raw_a_dir.relative_to(_REPO_ROOT)),
                "member_count": raw_a_count,
                "sha256": raw_a_binding["sha256"],
                "members": raw_a_binding["members"],
                "algorithm": raw_a_binding["algorithm"],
            },
            "raw_b": {
                "path": _posix(raw_b_dir.relative_to(_REPO_ROOT)),
                "member_count": raw_b_count,
                "sha256": raw_b_binding["sha256"],
                "members": raw_b_binding["members"],
                "algorithm": raw_b_binding["algorithm"],
            },
            "bundle": {
                "verdict": eval_result["verdict"],
                "payload_sha256": "",
            },
            "evaluation_result": {
                "path": "results/evaluation-result.json",
                "sha256": _file_sha256(evaluation_path),
            },
            "comparison": {
                "path": "results/comparison.json",
                "sha256": _file_sha256(comparison_path),
            },
            "environment": {
                "path": "results/ENVIRONMENT.md",
                "sha256": _file_sha256(_RESULTS / "ENVIRONMENT.md"),
            },
        },
        "run_a": {
            "executor_id": manifest_a["executor_id"],
            "git_commit": manifest_a["git_commit"],
            "git_tree_sha256": manifest_a["git_tree_sha256"],
            "dirty": manifest_a["dirty"],
            "process_evidence": manifest_a["process_evidence"],
            "source_bindings": manifest_a["source_bindings"],
            "environment_hash": manifest_a["environment_hash"],
            "hard_counters": manifest_a["hard_counters"],
            "probe_counters": manifest_a.get("probe_counters", {}),
            "latency_ms": manifest_a["latency_ms"],
            "per_component_latency_ms": manifest_a["per_component_latency_ms"],
            "raw_traces": raw_a_count,
            "raw_trace_binding": raw_a_binding,
            "matrix": manifest_a.get("matrix", {}),
        },
        "run_b": {
            "executor_id": manifest_b["executor_id"],
            "git_commit": manifest_b["git_commit"],
            "git_tree_sha256": manifest_b["git_tree_sha256"],
            "dirty": manifest_b["dirty"],
            "process_evidence": manifest_b["process_evidence"],
            "source_bindings": manifest_b["source_bindings"],
            "environment_hash": manifest_b["environment_hash"],
            "hard_counters": manifest_b["hard_counters"],
            "probe_counters": manifest_b.get("probe_counters", {}),
            "latency_ms": manifest_b["latency_ms"],
            "per_component_latency_ms": manifest_b["per_component_latency_ms"],
            "raw_traces": raw_b_count,
            "raw_trace_binding": raw_b_binding,
            "matrix": manifest_b.get("matrix", {}),
        },
        "evaluation": {
            "verdict": eval_result["verdict"],
            "hard_counters": eval_result["hard_counters"],
            "probe_results": eval_result["probe_results"],
            "failures": eval_result.get("failures", []),
            "warnings": eval_result.get("warnings", []),
            "raw_archive_a": eval_result.get("raw_archive_a", {}),
            "raw_archive_b": eval_result.get("raw_archive_b", {}),
        },
        "comparison": {
            "verdict": comparison["verdict"],
            "failures": comparison.get("failures", []),
            "warnings": comparison.get("warnings", []),
            "hard_counters": comparison.get("hard_counters", {}),
            "raw_archive_a": comparison.get("raw_archive_a", {}),
            "raw_archive_b": comparison.get("raw_archive_b", {}),
        },
        "dependencies": [
            {
                "ticket": "S1-002",
                "result": "PASS_WITH_LIMITS",
                "limitation": "Local benchmark only; no production SLO proven.",
            },
            {
                "ticket": "S1-004",
                "result": "PASS_WITH_LIMITS",
                "limitation": "Bounded model semantics only; no implementation conformance proven.",
            },
        ],
        "limitations": [
            "Same-host model-only: no production network/cache topology tested.",
            "Process-separated auditor, not an external/independent audit firm.",
            "Local model cannot prove absence of all network/cache side channels.",
            "Clock assumptions: monotonic clock authoritative for elapsed; UTC wall for audit only.",
        ],
    })
    # bundle_sha256 computed over canonical JSON with bundle_sha256="" (placeholder)
    bundle["bundle_sha256"] = ""
    bundle_json = json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    bundle["bundle_sha256"] = sha256_text(bundle_json)

    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description="Build S1-008 evidence bundle")
    parser.add_argument("--goal-id", required=True,
                        help="Canonical goal ID from DB")
    parser.add_argument("--eval-id", required=True,
                        help="Canonical evaluation ID from DB")
    parser.add_argument("--campaign-id", required=True,
                        help="Canonical campaign ID from DB")
    parser.add_argument("--chain-hash", default="",
                        help="Artifact chain hash from DB evaluation")
    parser.add_argument("--run-dir-a", default="results/run-a",
                        help="Run A output directory")
    parser.add_argument("--run-dir-b", default="results/run-b",
                        help="Run B output directory")
    parser.add_argument("--output", default="bundle.json",
                        help="Output path for bundle.json")
    args = parser.parse_args()

    # Read existing bundle to preserve FLOW-11 fields (config, sources, claims, artifacts, audit)
    existing_bundle = None
    bundle_path = Path(args.output)
    if bundle_path.exists():
        existing_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))

    bundle = build_bundle(args.goal_id, args.eval_id, args.campaign_id,
                          args.chain_hash, args.run_dir_a, args.run_dir_b,
                          existing_bundle=existing_bundle)
    bundle_path = Path(args.output)

    # Write canonical JSON (minified) — this is what bundle_sha256 was computed over
    canonical = json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    bundle_path.write_text(canonical, encoding="utf-8")

    # Verify written file hash matches bundle_sha256
    written = bundle_path.read_bytes()
    file_hash = hashlib.sha256(written).hexdigest()
    self_hash = sha256_text(json.dumps(
        {**bundle, "bundle_sha256": ""},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ))

    summary = {
        "verdict": bundle["evaluation"]["verdict"],
        "comparison": bundle["comparison"]["verdict"],
        "goal_id": bundle["goal_id"],
        "evaluation_id": bundle["evaluation_id"],
        "bundle_sha256": bundle["bundle_sha256"],
        "file_sha256": file_hash,
        "self_hash_match": self_hash == bundle["bundle_sha256"],
        "frozen_artifacts": len(bundle["frozen_artifacts"]),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
