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
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from agentos.ids import sha256_text  # noqa: E402


def _canonical_pack_json(pack: dict) -> str:
    """Serialize pack as canonical JSON (sorted, compact, no trailing newline)."""
    return json.dumps(pack, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _file_sha256(path: Path) -> str:
    """Compute SHA-256 of raw file bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _dir_sha256(path: Path) -> str:
    """Compute SHA-256 over all files in a directory tree (sorted paths)."""
    h = hashlib.sha256()
    files = sorted(path.rglob("*.json"))
    for f in files:
        rel = f.relative_to(path)
        h.update(str(rel).encode("utf-8"))
        h.update(b"\x00")
        content = f.read_text(encoding="utf-8")
        h.update(_canonical_pack_json(json.loads(content)).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _count_trace_files(trace_dir: Path) -> int:
    """Count JSON files in a trace directory."""
    return len(list(trace_dir.glob("*.json")))


def build_evidence_pack(bundle: dict) -> dict:
    """Build the machine-readable evidence pack from the bundle.

    The pack's pack_sha256 is computed over the canonical (minified, sorted)
    JSON representation that is EXACTLY what gets written to disk.
    """
    raw_a = bundle.get("artifacts", {}).get("raw_a", {})
    raw_b = bundle.get("artifacts", {}).get("raw_b", {})

    # Resolve actual trace directories and compute real SHAs
    run_a_manifest = bundle.get("run_a", {})
    run_b_manifest = bundle.get("run_b", {})

    raw_a_path = raw_a.get("path", "")
    raw_b_path = raw_b.get("path", "")

    # Compute actual SHA from raw-traces directory if it exists
    raw_a_sha = raw_a.get("sha256", "")
    raw_b_sha = raw_b.get("sha256", "")
    raw_a_members = raw_a.get("member_count", 0)
    raw_b_members = raw_b.get("member_count", 0)

    if raw_a_path and Path(raw_a_path).exists():
        raw_a_sha = _dir_sha256(Path(raw_a_path))
        raw_a_members = _count_trace_files(Path(raw_a_path))

    if raw_b_path and Path(raw_b_path).exists():
        raw_b_sha = _dir_sha256(Path(raw_b_path))
        raw_b_members = _count_trace_files(Path(raw_b_path))

    pack = {
        "schema": "agentos.s1-008.evidence-pack/v1",
        "goal_id": bundle.get("goal_id", ""),
        "campaign_id": bundle.get("campaign_id", ""),
        "evaluation_id": bundle.get("evaluation_id", ""),
        "ticket_id": "S1-008",
        "verdict": bundle.get("comparison", {}).get("verdict",
                   bundle.get("evaluation", {}).get("verdict", "")),
        "target_ms": 5000,
        "artifact_chain_hash": bundle.get("artifact_chain_hash", ""),
        "frozen_artifact_hashes": bundle.get("frozen_artifacts", {}),
        "raw_archive_a": {
            "path": raw_a_path,
            "sha256": raw_a_sha,
            "member_count": raw_a_members,
        },
        "raw_archive_b": {
            "path": raw_b_path,
            "sha256": raw_b_sha,
            "member_count": raw_b_members,
        },
        "run_a": {
            "executor_id": run_a_manifest.get("executor_id", ""),
            "git_commit": run_a_manifest.get("git_commit", ""),
            "hard_counters": run_a_manifest.get("hard_counters", {}),
            "latency_ms": run_a_manifest.get("latency_ms", {}),
        },
        "run_b": {
            "executor_id": run_b_manifest.get("executor_id", ""),
            "git_commit": run_b_manifest.get("git_commit", ""),
            "hard_counters": run_b_manifest.get("hard_counters", {}),
            "latency_ms": run_b_manifest.get("latency_ms", {}),
        },
        "hard_counters": bundle.get("evaluation", {}).get("hard_counters", {}),
        "probe_results": bundle.get("evaluation", {}).get("probe_results", {}),
        "comparison": bundle.get("comparison", {}),
    }

    # Compute pack_sha256: hash the canonical JSON with pack_sha256 as ""
    # (self-hash — pack_sha256 field carries its own value, not the hash
    # of the bytes that include it). The file name IS pack_sha256.
    pack["pack_sha256"] = ""
    canonical = _canonical_pack_json(pack)
    pack["pack_sha256"] = sha256_text(canonical)

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

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # The pack_sha256 was computed over canonical JSON with pack_sha256="".
    # File name is content-addressed by pack_sha256.
    pack_hash = pack["pack_sha256"]
    pack_path = out_dir / f"evidence-pack-{pack_hash}.json"

    # Serialize pack WITH pack_sha256 set (same canonical format)
    pack_json_bytes = _canonical_pack_json(pack).encode("utf-8")
    pack_path.write_bytes(pack_json_bytes)

    # Self-hash verification: strip pack_sha256, recompute, compare
    written_pack = json.loads(pack_path.read_text(encoding="utf-8"))
    written_pack["pack_sha256"] = ""
    written_canonical = _canonical_pack_json(written_pack)
    written_hash = sha256_text(written_canonical)
    if written_hash != pack_hash:
        print(f"ERROR: pack self-hash mismatch: file={written_hash} recorded={pack_hash}",
              file=sys.stderr)
        return 1

    # Also write raw observations archive (content-addressed by its own SHA)
    raw_a_dir = Path(bundle.get("artifacts", {}).get("raw_a", {}).get("path", ""))
    if not raw_a_dir.is_absolute():
        raw_a_dir = _REPO_ROOT / raw_a_dir
    all_observations: dict = {}
    if raw_a_dir.exists():
        for f in sorted(raw_a_dir.rglob("*.json")):
            all_observations[str(f.relative_to(_REPO_ROOT))] = json.loads(
                f.read_text(encoding="utf-8")
            )

    raw_obs_json = _canonical_pack_json(all_observations)
    raw_obs_hash = sha256_text(raw_obs_json)
    raw_obs_path = out_dir / f"raw-observations-{raw_obs_hash}.json"
    raw_obs_path.write_bytes(raw_obs_json.encode("utf-8"))

    # Verify raw observations hash
    if _file_sha256(raw_obs_path) != raw_obs_hash:
        print(f"ERROR: raw observations hash mismatch", file=sys.stderr)
        return 1

    print(f"Evidence pack: {pack_path}")
    print(f"Raw observations: {raw_obs_path}")
    print(f"Pack SHA-256: {pack_hash}")
    print(f"Raw observations SHA-256: {raw_obs_hash}")
    print(f"Members (Run A traces): {pack['raw_archive_a']['member_count']}")
    print(f"Members (Run B traces): {pack['raw_archive_b']['member_count']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
