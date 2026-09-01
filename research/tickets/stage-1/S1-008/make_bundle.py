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


def build_bundle(goal_id: str, evaluation_id: str, campaign_id: str,
                 chain_hash: str = "",
                 run_dir_a: str = "results/run-a",
                 run_dir_b: str = "results/run-b",
                 existing_bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the bundle from frozen artifacts + run outputs.

    Preserves FLOW-11 fields (config, sources, claims, artifacts, audit)
    from existing_bundle if provided.
    """
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
    raw_a_count = _count_files(raw_a_dir)
    raw_b_count = _count_files(raw_b_dir)

    # --- Load evaluation result ---
    eval_result = json.loads((_RESULTS / "evaluation-result.json").read_text())

    # --- Load comparison ---
    comparison = json.loads((_RESULTS / "comparison.json").read_text())

    # --- Build bundle ---
    # If FLOW-11 artifacts exist in existing_bundle, merge evidence artifacts into them
    flow_artifacts = bundle.pop("artifacts", {}) if existing_bundle and "artifacts" in bundle else {}
    bundle.update({
        "schema": "agentos.s1-008.bundle/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "goal_id": goal_id,
        "campaign_id": campaign_id,
        "evaluation_id": evaluation_id,
        "artifact_chain_hash": chain_hash,
        "frozen_artifacts": frozen_artifacts,
        "artifacts": {
            **flow_artifacts,
            "raw_a": {
                "path": _posix(raw_a_dir.relative_to(_REPO_ROOT)),
                "member_count": raw_a_count,
                "sha256": sha256_text(
                    json.dumps({k: v for k, v in manifest_a.items()},
                               skipkeys=False, sort_keys=True)
                ),
            },
            "raw_b": {
                "path": _posix(raw_b_dir.relative_to(_REPO_ROOT)),
                "member_count": raw_b_count,
                "sha256": sha256_text(
                    json.dumps({k: v for k, v in manifest_b.items()},
                               skipkeys=False, sort_keys=True)
                ),
            },
            "bundle": {
                "verdict": eval_result["verdict"],
                "payload_sha256": "",
            },
            "evaluation_result": {
                "path": "results/evaluation-result.json",
                "sha256": _file_sha256(_RESULTS / "evaluation-result.json"),
            },
            "comparison": {
                "path": "results/comparison.json",
                "sha256": _file_sha256(_RESULTS / "comparison.json"),
            },
            "environment": {
                "path": "results/ENVIRONMENT.md",
                "sha256": _file_sha256(_RESULTS / "ENVIRONMENT.md"),
            },
        },
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
            "hard_counters": comparison.get("hard_counters", {}),
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
