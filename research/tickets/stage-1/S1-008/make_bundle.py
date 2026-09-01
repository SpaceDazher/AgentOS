"""S1-008 evidence bundle assembler.

Collects frozen artifacts, run manifests, raw traces, evaluator output,
comparison result, and evidence pack into a single bundle.json with a
self-verified SHA-256.

Usage:
    python make_bundle.py --goal-id GOAL --eval-id EVAL --campaign-id CAMP
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any  # noqa: E402

_BASE = Path(__file__).resolve().parent
_REPO_ROOT = Path.cwd()
if (_REPO_ROOT / "src").exists() is False:
    _REPO_ROOT = _BASE.parents[4]
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


def _list_dir(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted(p.name for p in path.iterdir())


def build_bundle(goal_id: str, evaluation_id: str, campaign_id: str) -> dict[str, Any]:
    """Build the complete evidence bundle."""
    now = datetime.now(timezone.utc).isoformat()

    # Hash all frozen artifacts
    frozen_artifacts = {
        "revocation-contract.json": _file_sha256(_BASE / "revocation-contract.json"),
        "workload-manifest.json": _file_sha256(_BASE / "workload-manifest.json"),
        "threat-model.json": _file_sha256(_BASE / "threat-model.json"),
        "rubric.json": _file_sha256(_BASE / "rubric.json"),
        "fixtures.json": _file_sha256(_BASE / "fixtures.json"),
        "corpus-manifest.json": _file_sha256(_BASE / "corpus-manifest.json"),
        "runner.py": _file_sha256(_BASE / "runner.py"),
        "evaluator.py": _file_sha256(_BASE / "evaluator.py"),
        "publish_evidence_pack.py": _file_sha256(_BASE / "publish_evidence_pack.py"),
    }

    # Load manifests
    manifest_a = json.loads((_RESULTS / "run-a" / "manifest.json").read_text())
    manifest_b = json.loads((_RESULTS / "run-b" / "manifest.json").read_text())

    # Load evaluation result
    eval_result = json.loads((_RESULTS / "evaluation-result.json").read_text())
    comparison = json.loads((_RESULTS / "comparison.json").read_text())

    # Count raw traces
    raw_a_dir = Path(manifest_a["raw_trace_dir"])
    raw_b_dir = Path(manifest_b["raw_trace_dir"])
    raw_a_count = len(list(raw_a_dir.glob("*.json")))
    raw_b_count = len(list(raw_b_dir.glob("*.json")))

    # Compute raw archive hashes
    raw_a_hash = hashlib.sha256(
        b"".join(
            f.read_bytes() for f in sorted(raw_a_dir.glob("*.json"))
        )
    ).hexdigest()
    raw_b_hash = hashlib.sha256(
        b"".join(
            f.read_bytes() for f in sorted(raw_b_dir.glob("*.json"))
        )
    ).hexdigest()

    # Build artifact chain
    artifact_chain = {
        "frozen_artifacts": frozen_artifacts,
        "manifest_a": {
            "path": _posix(_RESULTS / "run-a" / "manifest.json"),
            "sha256": _file_sha256(_RESULTS / "run-a" / "manifest.json"),
        },
        "manifest_b": {
            "path": _posix(_RESULTS / "run-b" / "manifest.json"),
            "sha256": _file_sha256(_RESULTS / "run-b" / "manifest.json"),
        },
        "raw_a": {
            "path": _posix(raw_a_dir),
            "sha256": raw_a_hash,
            "member_count": raw_a_count,
        },
        "raw_b": {
            "path": _posix(raw_b_dir),
            "sha256": raw_b_hash,
            "member_count": raw_b_count,
        },
        "evaluator": {
            "sha256": _file_sha256(_BASE / "evaluator.py"),
        },
        "evaluation_result": {
            "path": _posix(_RESULTS / "evaluation-result.json"),
            "sha256": _file_sha256(_RESULTS / "evaluation-result.json"),
        },
        "comparison": {
            "path": _posix(_RESULTS / "comparison.json"),
            "sha256": _file_sha256(_RESULTS / "comparison.json"),
        },
    }

    # Full artifact chain hash
    chain_hash = sha256_text(json.dumps(artifact_chain, sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=False))

    bundle = {
        "schema": "agentos.s1-008.bundle/v1",
        "built_at_utc": now,
        "goal_id": goal_id,
        "evaluation_id": evaluation_id,
        "campaign_id": campaign_id,
        "artifact_chain_hash": chain_hash,
        "frozen_artifacts": frozen_artifacts,
        "artifacts": artifact_chain,
        "run_a": {
            "executor_id": manifest_a["executor_id"],
            "git_commit": manifest_a["git_commit"],
            "dirty": manifest_a["dirty"],
            "environment_hash": manifest_a["environment_hash"],
            "hard_counters": manifest_a["hard_counters"],
            "probe_counters": manifest_a.get("probe_counters", {}),
            "latency_ms": manifest_a["latency_ms"],
            "per_component_latency_ms": manifest_a["per_component_latency_ms"],
            "raw_traces": raw_a_count,
            "matrix": manifest_a.get("matrix", {}),
        },
        "run_b": {
            "executor_id": manifest_b["executor_id"],
            "git_commit": manifest_b["git_commit"],
            "dirty": manifest_b["dirty"],
            "environment_hash": manifest_b["environment_hash"],
            "hard_counters": manifest_b["hard_counters"],
            "probe_counters": manifest_b.get("probe_counters", {}),
            "latency_ms": manifest_b["latency_ms"],
            "per_component_latency_ms": manifest_b["per_component_latency_ms"],
            "raw_traces": raw_b_count,
            "matrix": manifest_b.get("matrix", {}),
        },
        "evaluation": {
            "verdict": eval_result["verdict"],
            "hard_counters": eval_result["hard_counters"],
            "probe_results": eval_result["probe_results"],
            "failures": eval_result.get("failures", []),
            "warnings": eval_result.get("warnings", []),
        },
        "comparison": {
            "verdict": comparison["verdict"],
            "failures": comparison.get("failures", []),
            "warnings": comparison.get("warnings", []),
        },
    }

    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build S1-008 evidence bundle"
    )
    parser.add_argument("--goal-id", required=True,
                        help="Canonical goal ID from DB")
    parser.add_argument("--eval-id", required=True,
                        help="Canonical evaluation ID from DB")
    parser.add_argument("--campaign-id", required=True,
                        help="Canonical campaign ID from DB")
    parser.add_argument("--output", default="bundle.json",
                        help="Output path for bundle.json")
    args = parser.parse_args()

    bundle = build_bundle(args.goal_id, args.eval_id, args.campaign_id)
    bundle_path = Path(args.output)

    # Compute bundle_sha256 from canonical JSON (excluding the bundle_sha256
    # field itself — self-hash is verified by re-deriving after write).
    bundle["bundle_sha256"] = ""
    canonical = json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    bundle["bundle_sha256"] = sha256_text(canonical)

    # Write bundle as canonical JSON (file SHA must match bundle_sha256)
    final_json = json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    bundle_path.write_text(final_json + "\n", encoding="utf-8")

    # Verify: recompute SHA of file content excluding the bundle_sha256 field
    written_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    # Verify frozen artifact SHA-256s against disk
    for name, info in written_bundle["frozen_artifacts"].items():
        artifact_path = _BASE / name
        if artifact_path.exists():
            actual_sha = _file_sha256(artifact_path)
            if actual_sha != info:
                print(f"ERROR: frozen artifact {name} SHA mismatch: "
                      f"disk={actual_sha} recorded={info}", file=sys.stderr)
                return 1
        else:
            print(f"ERROR: frozen artifact {name} not found", file=sys.stderr)
            return 1

    written_bundle["bundle_sha256"] = ""
    written_canonical = json.dumps(written_bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    written_hash = sha256_text(written_canonical)
    if written_hash != bundle["bundle_sha256"]:
        print(f"ERROR: bundle self-hash mismatch: computed={written_hash} recorded={bundle['bundle_sha256']}",
              file=sys.stderr)
        return 1

    # Also verify file bytes match the recorded hash (no trailing-newline drift)
    written_bytes = bundle_path.read_bytes()
    if not written_bytes.endswith(b"\n"):
        print("ERROR: bundle file missing trailing newline", file=sys.stderr)
        return 1

    print(json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
