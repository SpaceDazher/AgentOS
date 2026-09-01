"""S1-008 evidence bundle builder.

Assembles bundle.json from frozen artifacts, runner manifests, raw traces,
evaluator results, and comparison output. The bundle is content-addressed
and reproducible from a clean clone.

Usage:
    python make_bundle.py --output bundle.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT / "src"))
os.environ.setdefault("PYTHONPATH", str(_REPO_ROOT / "src"))

from agentos.ids import canonical_json, sha256_text  # noqa: E402

_BASE = Path(__file__).resolve().parent
_RESULTS = _REPO_ROOT / "results"


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_size(path: Path) -> int:
    if not path.exists():
        return 0
    return path.stat().st_size


def _list_dir(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted(p.name for p in path.iterdir())


def build_bundle() -> dict[str, Any]:
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
        "make_bundle.py": _file_sha256(_BASE / "make_bundle.py"),
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
            "path": str(_RESULTS / "run-a" / "manifest.json"),
            "sha256": _file_sha256(_RESULTS / "run-a" / "manifest.json"),
        },
        "manifest_b": {
            "path": str(_RESULTS / "run-b" / "manifest.json"),
            "sha256": _file_sha256(_RESULTS / "run-b" / "manifest.json"),
        },
        "raw_a": {
            "path": str(raw_a_dir),
            "sha256": raw_a_hash,
            "member_count": raw_a_count,
        },
        "raw_b": {
            "path": str(raw_b_dir),
            "sha256": raw_b_hash,
            "member_count": raw_b_count,
        },
        "evaluator": {
            "sha256": _file_sha256(_BASE / "evaluator.py"),
        },
        "evaluation_result": {
            "path": str(_RESULTS / "evaluation-result.json"),
            "sha256": _file_sha256(_RESULTS / "evaluation-result.json"),
        },
        "comparison": {
            "path": str(_RESULTS / "comparison.json"),
            "sha256": _file_sha256(_RESULTS / "comparison.json"),
        },
    }

    # Full artifact chain hash
    chain_hash = sha256_text(canonical_json(artifact_chain))

    bundle = {
        "schema": "agentos.s1-008.bundle/v1",
        "built_at_utc": now,
        "goal_id": "goal_S1-008_REVOCATION_LATENCY",
        "evaluation_id": "reval_S1-008_REVOCATION_LATENCY",
        "campaign_id": "rcamp_S1-008_REVOCATION_LATENCY",
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
        },
        "evaluation": {
            "verdict": eval_result["verdict"],
            "hard_counters": eval_result["hard_counters"],
            "probe_results": eval_result["probe_results"],
        },
        "comparison": {
            "verdict": comparison["verdict"],
            "failures": comparison["failures"],
            "warnings": comparison["warnings"],
        },
    }

    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build S1-008 evidence bundle"
    )
    parser.add_argument("--output", default="bundle.json",
                        help="Output path for bundle.json")
    args = parser.parse_args()

    bundle = build_bundle()
    bundle_path = Path(args.output)
    bundle_path.write_text(
        json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

    # Verify bundle file hash
    bundle["bundle_sha256"] = sha256_text(bundle_path.read_text(encoding="utf-8"))
    bundle_path.write_text(
        json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

    print(json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
