"""S1-008 evidence pack publisher.

Creates a content-addressed evidence pack that structurally links:
  - raw archive path/SHA/member count
  - goal/campaign/evaluation IDs
  - full artifact-chain hash

The pack file name IS its SHA-256 (content addressing).

Usage:
    python publish_evidence_pack.py --bundle bundle.json --output-dir results/evidence
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from agentos.ids import canonical_json, sha256_text  # noqa: E402


def build_evidence_pack(bundle: dict) -> dict:
    """Build the machine-readable evidence pack from the bundle."""
    raw_a = bundle.get("artifacts", {}).get("raw_a", {})
    raw_b = bundle.get("artifacts", {}).get("raw_b", {})

    pack = {
        "schema": "agentos.s1-008.evidence-pack/v1",
        "goal_id": bundle.get("goal_id", ""),
        "campaign_id": bundle.get("campaign_id", ""),
        "evaluation_id": bundle.get("evaluation_id", ""),
        "ticket_id": "S1-008",
        "verdict": bundle.get("evaluation", {}).get("verdict", ""),
        "target_ms": 5000,
        "artifact_chain_hash": bundle.get("artifact_chain_hash", ""),
        "frozen_artifact_hashes": bundle.get("frozen_artifacts", {}),
        "raw_archive_a": {
            "path": raw_a.get("path", ""),
            "sha256": raw_a.get("sha256", ""),
            "member_count": raw_a.get("member_count", 0),
        },
        "raw_archive_b": {
            "path": raw_b.get("path", ""),
            "sha256": raw_b.get("sha256", ""),
            "member_count": raw_b.get("member_count", 0),
        },
        "run_a": {
            "executor_id": bundle.get("run_a", {}).get("executor_id", ""),
            "git_commit": bundle.get("run_a", {}).get("git_commit", ""),
            "hard_counters": bundle.get("run_a", {}).get("hard_counters", {}),
            "latency_ms": bundle.get("run_a", {}).get("latency_ms", {}),
        },
        "run_b": {
            "executor_id": bundle.get("run_b", {}).get("executor_id", ""),
            "git_commit": bundle.get("run_b", {}).get("git_commit", ""),
            "hard_counters": bundle.get("run_b", {}).get("hard_counters", {}),
            "latency_ms": bundle.get("run_b", {}).get("latency_ms", {}),
        },
        "hard_counters": bundle.get("evaluation", {}).get("hard_counters", {}),
        "probe_results": bundle.get("evaluation", {}).get("probe_results", {}),
        "comparison": bundle.get("comparison", {}),
    }

    # Compute pack payload hash
    pack_json = json.dumps(pack, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    pack["payload_sha256"] = sha256_text(pack_json)

    # Recompute with payload hash included
    pack_json = json.dumps(pack, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    pack["pack_sha256"] = sha256_text(pack_json)

    return pack


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish S1-008 evidence pack"
    )
    parser.add_argument("--bundle", required=True,
                        help="Path to bundle.json")
    parser.add_argument("--output-dir", default="results/evidence",
                        help="Output directory for evidence pack")
    args = parser.parse_args()

    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    pack = build_evidence_pack(bundle)

    # Compute pack content hash
    pack_json = json.dumps(pack, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    pack_hash = sha256_text(pack_json)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Content-addressed filename — use pack_sha256 from build_evidence_pack
    pack_hash = pack["pack_sha256"]
    pack_path = out_dir / f"evidence-pack-{pack_hash}.json"
    pack_path.write_text(
        json.dumps(pack, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

    # Verify payload_sha256 matches (pack without payload_sha256 and pack_sha256)
    pack_verify = {k: v for k, v in pack.items() if k not in ("pack_sha256", "payload_sha256")}
    pack_verify_json = json.dumps(pack_verify, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if sha256_text(pack_verify_json) != pack["payload_sha256"]:
        print(f"ERROR: payload hash mismatch", file=sys.stderr)
        return 1

    # Also write raw observations archive
    raw_a_dir = Path(bundle.get("artifacts", {}).get("raw_a", {}).get("path", ""))
    all_observations = {}
    if raw_a_dir.exists():
        for f in sorted(raw_a_dir.glob("*.json")):
            all_observations[f.name] = json.loads(f.read_text(encoding="utf-8"))

    raw_obs_json = json.dumps(all_observations, sort_keys=True,
                               separators=(",", ":"), ensure_ascii=False)
    raw_obs_hash = sha256_text(raw_obs_json)
    raw_obs_path = out_dir / f"raw-observations-{raw_obs_hash}.json"
    raw_obs_path.write_text(
        json.dumps(all_observations, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

    print(f"Evidence pack: {pack_path}")
    print(f"Raw observations: {raw_obs_path}")
    print(f"Pack SHA-256: {pack_hash}")
    print(f"Raw observations SHA-256: {raw_obs_hash}")
    print(f"Members: {len(all_observations)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
