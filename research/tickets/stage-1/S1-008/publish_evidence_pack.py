"""S1-008 content-addressed evidence-pack publisher.

The publisher creates one byte-preserving raw archive for each independent
run. The archive and pack file names are hashes of their final bytes; the
pack also carries the trace-set digest and every member digest so a verifier
can detect tampering without trusting producer summaries.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from agentos.ids import canonical_json, sha256_text  # noqa: E402


def _canonical_pack_json(pack: dict[str, Any]) -> str:
    return json.dumps(pack, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _file_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    return _file_sha256_bytes(path.read_bytes())


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value.lower())


def _resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _REPO_ROOT / path


def _trace_members(raw_dir: Path) -> list[dict[str, Any]]:
    if not raw_dir.is_dir():
        raise FileNotFoundError(f"raw traces dir not found: {raw_dir}")
    members: list[dict[str, Any]] = []
    for path in sorted(raw_dir.rglob("*.json")):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid raw trace {path}") from exc
        canonical = canonical_json(parsed).encode("utf-8")
        members.append({
            "path": path.relative_to(raw_dir).as_posix(),
            "size": len(raw),
            "sha256": _file_sha256_bytes(raw),
            "canonical_sha256": _file_sha256_bytes(canonical),
            "content_base64": base64.b64encode(raw).decode("ascii"),
        })
    return members


def _trace_set_digest(members: list[dict[str, Any]]) -> str:
    digest_members = [
        {key: member[key] for key in ("path", "size", "sha256", "canonical_sha256")}
        for member in members
    ]
    payload = {
        "algorithm": "sha256(path,size,bytes,canonical-json)",
        "members": digest_members,
    }
    return sha256_text(canonical_json(payload))


def raw_trace_digest(raw_dir: str | Path) -> dict[str, Any]:
    """Return the canonical content digest and per-member evidence metadata."""
    members = _trace_members(_resolve_repo_path(raw_dir))
    return {
        "algorithm": "sha256(path,size,bytes,canonical-json)",
        "member_count": len(members),
        "members": [
            {key: member[key] for key in ("path", "size", "sha256", "canonical_sha256")}
            for member in members
        ],
        "sha256": _trace_set_digest(members),
    }


def _load_raw_observations(raw_dir: Path) -> dict[str, Any]:
    """Compatibility helper returning parsed observations keyed by path."""
    observations: dict[str, Any] = {}
    for member in _trace_members(raw_dir):
        raw = base64.b64decode(member["content_base64"])
        observations[member["path"]] = json.loads(raw.decode("utf-8"))
    return observations


def _archive_payload(run_label: str, raw_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    members = _trace_members(raw_dir)
    trace_binding = {
        "algorithm": "sha256(path,size,bytes,canonical-json)",
        "member_count": len(members),
        "members": [
            {key: member[key] for key in ("path", "size", "sha256", "canonical_sha256")}
            for member in members
        ],
        "sha256": _trace_set_digest(members),
    }
    payload = {
        "schema": "agentos.s1-008.raw-observations/v2",
        "run_label": run_label,
        "member_count": len(members),
        "trace_set_sha256": trace_binding["sha256"],
        "members": {member["path"]: member for member in members},
    }
    return payload, trace_binding


def _write_archive(run_label: str, raw_dir: Path, out_dir: Path,
                   expected: dict[str, Any]) -> dict[str, Any]:
    payload, trace_binding = _archive_payload(run_label, raw_dir)
    if expected.get("member_count") != trace_binding["member_count"]:
        raise ValueError(f"{run_label} raw member count differs from bundle")
    if expected.get("sha256") != trace_binding["sha256"]:
        raise ValueError(f"{run_label} raw content digest differs from bundle")
    raw_bytes = _canonical_pack_json(payload).encode("utf-8")
    file_sha = _file_sha256_bytes(raw_bytes)
    archive_path = out_dir / f"raw-observations-{run_label}-{file_sha}.json"
    archive_path.write_bytes(raw_bytes)
    if _file_sha256(archive_path) != file_sha:
        raise ValueError(f"{run_label} raw archive file hash mismatch")
    return {
        "path": archive_path.relative_to(_REPO_ROOT).as_posix(),
        "sha256": file_sha,
        "trace_set_sha256": trace_binding["sha256"],
        "member_count": trace_binding["member_count"],
        "member_digests": trace_binding["members"],
        "run_label": run_label,
    }


def verify_raw_archive(path: str | Path, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    """Verify archive filename, bytes, member count, and every member digest."""
    archive_path = _resolve_repo_path(path)
    if not archive_path.is_file():
        raise FileNotFoundError(f"raw archive not found: {archive_path}")
    file_sha = _file_sha256(archive_path)
    payload = json.loads(archive_path.read_text(encoding="utf-8"))
    run_label = payload.get("run_label")
    if archive_path.stem != f"raw-observations-{run_label}-{file_sha}":
        raise ValueError(f"raw archive filename is not content-addressed: {archive_path.name}")
    members = payload.get("members")
    if not isinstance(members, dict) or payload.get("member_count") != len(members):
        raise ValueError("raw archive member count mismatch")
    normalized: list[dict[str, Any]] = []
    for member_path, member in sorted(members.items()):
        if not isinstance(member, dict) or member.get("path") != member_path:
            raise ValueError(f"raw archive path binding mismatch: {member_path}")
        try:
            raw = base64.b64decode(member["content_base64"], validate=True)
        except Exception as exc:
            raise ValueError(f"invalid raw archive bytes: {member_path}") from exc
        if member.get("size") != len(raw) or member.get("sha256") != _file_sha256_bytes(raw):
            raise ValueError(f"raw archive member byte hash mismatch: {member_path}")
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid archived JSON: {member_path}") from exc
        canonical = canonical_json(parsed).encode("utf-8")
        if member.get("canonical_sha256") != _file_sha256_bytes(canonical):
            raise ValueError(f"raw archive member canonical hash mismatch: {member_path}")
        normalized.append({key: member[key] for key in ("path", "size", "sha256", "canonical_sha256")})
    trace_sha = _trace_set_digest(normalized)
    if payload.get("trace_set_sha256") != trace_sha:
        raise ValueError("raw archive trace-set digest mismatch")
    metadata = {
        "path": archive_path.relative_to(_REPO_ROOT).as_posix(),
        "sha256": file_sha,
        "trace_set_sha256": trace_sha,
        "member_count": len(members),
        "member_digests": normalized,
        "run_label": run_label,
    }
    if expected is not None:
        for key in ("sha256", "trace_set_sha256", "member_count"):
            if expected.get(key) != metadata[key]:
                raise ValueError(f"raw archive {key} does not match expected binding")
    return metadata


def build_evidence_pack(bundle: dict[str, Any], out_dir: str | Path) -> tuple[Path, dict[str, Any]]:
    """Publish and verify both raw archives and the final content-addressed pack."""
    if not isinstance(bundle, dict):
        raise ValueError("bundle must be an object")
    required = ("goal_id", "campaign_id", "evaluation_id", "artifact_chain_hash", "bundle_sha256")
    if any(not isinstance(bundle.get(key), str) or not bundle[key] for key in required):
        raise ValueError("bundle is missing an immutable identity binding")
    evaluation = bundle.get("evaluation")
    comparison = bundle.get("comparison")
    if not isinstance(evaluation, dict) or evaluation.get("verdict") not in {"PASS", "PASS_WITH_LIMITS"}:
        raise ValueError("evaluation is not positive")
    if evaluation.get("failures"):
        raise ValueError("evaluation contains failures")
    if not isinstance(comparison, dict) or comparison.get("verdict") not in {"PASS", "PASS_WITH_LIMITS"}:
        raise ValueError("comparison is not positive")
    if comparison.get("failures"):
        raise ValueError("comparison contains failures")
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("bundle artifacts missing")
    raw_a = artifacts.get("raw_a")
    raw_b = artifacts.get("raw_b")
    if not isinstance(raw_a, dict) or not isinstance(raw_b, dict):
        raise ValueError("bundle raw A/B bindings missing")
    output_dir = _resolve_repo_path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_a = _write_archive("run-a", _resolve_repo_path(raw_a["path"]), output_dir, raw_a)
    archive_b = _write_archive("run-b", _resolve_repo_path(raw_b["path"]), output_dir, raw_b)
    archive_a = verify_raw_archive(archive_a["path"], archive_a)
    archive_b = verify_raw_archive(archive_b["path"], archive_b)
    now = datetime.now(timezone.utc).isoformat()
    pack: dict[str, Any] = {
        "schema": "agentos.s1-008.evidence-pack/v2",
        "created_at_utc": now,
        "goal_id": bundle["goal_id"],
        "campaign_id": bundle["campaign_id"],
        "evaluation_id": bundle["evaluation_id"],
        "artifact_chain_hash": bundle["artifact_chain_hash"],
        "bundle_sha256": bundle["bundle_sha256"],
        "bundle_payload_sha256": sha256_text(canonical_json({
            key: value for key, value in bundle.items() if key != "bundle_sha256"
        })),
        "raw_archives": {"a": archive_a, "b": archive_b},
        "raw_archive_a": archive_a,
        "raw_archive_b": archive_b,
        "raw_observations_archive": archive_a,
        "run_a": bundle["run_a"],
        "run_b": bundle["run_b"],
        "evaluation": evaluation,
        "comparison": comparison,
        "verdict": "PASS_WITH_LIMITS",
        "comparison_verdict": comparison["verdict"],
        "result": "PASS_WITH_LIMITS",
        "pack_sha256": "",
    }
    pack["pack_sha256"] = sha256_text(_canonical_pack_json(pack))
    final_bytes = _canonical_pack_json(pack).encode("utf-8")
    file_sha = _file_sha256_bytes(final_bytes)
    pack_path = output_dir / f"evidence-pack-{file_sha}.json"
    pack_path.write_bytes(final_bytes)
    if _file_sha256(pack_path) != file_sha:
        raise ValueError("evidence pack file hash mismatch")
    written = json.loads(pack_path.read_text(encoding="utf-8"))
    self_hash = written.pop("pack_sha256", None)
    if self_hash != sha256_text(_canonical_pack_json({**written, "pack_sha256": ""})):
        raise ValueError("evidence pack self-hash mismatch")
    return pack_path, {
        "path": pack_path.relative_to(_REPO_ROOT).as_posix(),
        "sha256": file_sha,
        "pack_sha256": self_hash,
        "raw_archive_a": archive_a,
        "raw_archive_b": archive_b,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish S1-008 evidence pack")
    parser.add_argument("--bundle", required=True, help="Path to bundle.json")
    parser.add_argument("--output-dir", required=True, help="Output directory for evidence pack")
    args = parser.parse_args()
    try:
        bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
        _pack_path, metadata = build_evidence_pack(bundle, args.output_dir)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "evidence_pack": metadata["path"],
        "pack_file_sha256": metadata["sha256"],
        "pack_self_sha256": metadata["pack_sha256"],
        "raw_archive_a": metadata["raw_archive_a"],
        "raw_archive_b": metadata["raw_archive_b"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
