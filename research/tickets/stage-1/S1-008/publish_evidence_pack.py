"""S1-008 evidence pack publisher.

Creates a content-addressed evidence pack that structurally links:
  - raw archive path/SHA/member count
  - goal/campaign/evaluation IDs
  - full artifact-chain hash

The pack file name IS its SHA-256 (content addressing).
The raw-observations file name IS its SHA-256.

Usage:
    python publish_evidence_pack.py --bundle bundle.json --output-dir results/evidence
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from agentos.ids import canonical_json, sha256_text  # noqa: E402


def _canonical_pack_json(pack: dict) -> str:
    """Serialize pack as canonical JSON (sorted, compact, no trailing newline)."""
    return json.dumps(pack, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _file_sha256_bytes(data: bytes) -> str:
    """Compute SHA-256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def _load_raw_observations(raw_dir: Path) -> dict[str, Any]:
    """Load all raw trace JSON files, keyed by repo-relative path."""
    all_observations: dict[str, Any] = {}
    if raw_dir.exists():
        for f in sorted(raw_dir.rglob("*.json")):
            # Use path relative to _REPO_ROOT for stable, portable addressing
            try:
                rel = str(f.relative_to(_REPO_ROOT)).replace("\\", "/")
            except ValueError:
                rel = str(f).replace("\\", "/")
            all_observations[rel] = json.loads(f.read_text(encoding="utf-8"))
    return all_observations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish S1-008 evidence pack"
    )
    parser.add_argument("--bundle", required=True,
                        help="Path to bundle.json")
    parser.add_argument("--output-dir", required=True,
                        help="Output directory for evidence pack")
    args = parser.parse_args()

    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    # --- Raw observations archive (content-addressed) ---
    raw_a_dir = Path(bundle["artifacts"]["raw_a"]["path"])
    if not raw_a_dir.is_absolute():
        raw_a_dir = _REPO_ROOT / raw_a_dir
    all_observations = _load_raw_observations(raw_a_dir)

    raw_obs_json = _canonical_pack_json(all_observations)
    raw_obs_bytes = raw_obs_json.encode("utf-8")
    raw_obs_hash = _file_sha256_bytes(raw_obs_bytes)
    raw_obs_path = out_dir / f"raw-observations-{raw_obs_hash}.json"
    raw_obs_path.write_bytes(raw_obs_bytes)

    # Verify raw observations hash
    if _file_sha256_bytes(raw_obs_path.read_bytes()) != raw_obs_hash:
        print("ERROR: raw observations hash mismatch", file=sys.stderr)
        return 1

    # --- Evidence pack ---
    # pack_sha256 is computed as self-hash: hash of canonical JSON with
    # pack_sha256="" (empty placeholder). This is a well-defined, stable
    # value because pack_sha256 is set AFTER the hash is computed.
    pack: dict[str, Any] = {
        "schema": "agentos.s1-008.evidence-pack/v1",
        "created_at_utc": now,
        "goal_id": bundle["goal_id"],
        "campaign_id": bundle["campaign_id"],
        "evaluation_id": bundle["evaluation_id"],
        "artifact_chain_hash": bundle["artifact_chain_hash"],
        "bundle_sha256": bundle["bundle_sha256"],
        "raw_archive": {
            "path": bundle["artifacts"]["raw_a"]["path"],
            "sha256": bundle["artifacts"]["raw_a"]["sha256"],
            "member_count": bundle["artifacts"]["raw_a"]["member_count"],
        },
        "run_a": {
            "executor_id": bundle["run_a"]["executor_id"],
            "git_commit": bundle["run_a"]["git_commit"],
            "dirty": bundle["run_a"]["dirty"],
            "raw_trace_count": bundle["run_a"]["raw_traces"],
        },
        "run_b": {
            "executor_id": bundle["run_b"]["executor_id"],
            "git_commit": bundle["run_b"]["git_commit"],
            "dirty": bundle["run_b"]["dirty"],
            "raw_trace_count": bundle["run_b"]["raw_traces"],
        },
        "raw_observations_archive": {
            "sha256": raw_obs_hash,
            "member_count": len(all_observations),
        },
        "evaluation": {
            "verdict": bundle["evaluation"]["verdict"],
            "hard_counters": bundle["evaluation"]["hard_counters"],
            "probe_results": bundle["evaluation"]["probe_results"],
        },
        "comparison": {
            "verdict": bundle["comparison"]["verdict"],
        },
        "verdict": bundle["evaluation"]["verdict"],
        "comparison_verdict": bundle["comparison"]["verdict"],
        "result": "PASS_WITH_LIMITS",
        "pack_sha256": "",  # placeholder for self-hash computation
    }

    # Compute pack_sha256: hash of canonical JSON with pack_sha256="" (self-hash)
    pack_json = _canonical_pack_json(pack)
    pack["pack_sha256"] = sha256_text(pack_json)

    # Write pack as canonical JSON (final bytes for content-addressed filename)
    final_json = _canonical_pack_json(pack)
    final_bytes = final_json.encode("utf-8")
    file_hash = _file_sha256_bytes(final_bytes)
    pack_path = out_dir / f"evidence-pack-{file_hash}.json"
    pack_path.write_bytes(final_bytes)

    # --- Verification ---

    # Verify file hash matches filename
    actual_file_hash = _file_sha256_bytes(pack_path.read_bytes())
    if actual_file_hash != file_hash:
        print(f"ERROR: pack file hash mismatch: filename={file_hash} actual={actual_file_hash}",
              file=sys.stderr)
        return 1

    # Verify self-hash: pack["pack_sha256"] must equal hash of pack with
    # pack_sha256=""
    written = json.loads(pack_path.read_text(encoding="utf-8"))
    recorded_pack_sha = written["pack_sha256"]
    written["pack_sha256"] = ""
    recomputed = sha256_text(_canonical_pack_json(written))
    if recomputed != recorded_pack_sha:
        print(f"ERROR: pack self-hash mismatch: recomputed={recomputed} recorded={recorded_pack_sha}",
              file=sys.stderr)
        return 1

    # Verify raw observations archive hash
    if _file_sha256_bytes(raw_obs_path.read_bytes()) != raw_obs_hash:
        print("ERROR: raw observations archive hash mismatch", file=sys.stderr)
        return 1

    print(f"Evidence pack: {pack_path}")
    print(f"Raw observations: {raw_obs_path}")
    print(f"Pack file SHA-256: {file_hash}")
    print(f"Pack self SHA-256: {pack['pack_sha256']}")
    print(f"Raw observations SHA-256: {raw_obs_hash}")
    print(f"Members (Run A traces): {bundle['artifacts']['raw_a']['member_count']}")
    print(f"Members (Run B traces): {bundle['artifacts']['raw_b']['member_count']}")
    print(f"Observation entries: {len(all_observations)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
