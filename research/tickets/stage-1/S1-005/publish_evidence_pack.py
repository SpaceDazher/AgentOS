"""Publish tracked, content-addressed evidence packs for a ticket.

Review R1 finding 3: evaluation records reference evidence packs inside the
gitignored `.agentos-research/` tree, so an auditor working from a Git
clone cannot verify them. This script copies the canonical pack into the
ticket's tracked `results/evidence/` directory under its content-addressed
name (evidence-pack-<file_sha256>.json) and reports both digests:

- file_sha256   : SHA-256 of the pack file bytes (content address);
- payload_sha256: SHA-256 of the normalized payload with the self-hash
                  field removed (the pack's own "sha256" field).

Usage:
    py publish_evidence_pack.py --goal goal_XXX --ticket \
        research/tickets/stage-1/S1-005
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def payload_sha(pack: dict) -> str:
    payload = {k: v for k, v in pack.items() if k != "sha256"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode()
    return hashlib.sha256(canonical).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--db", default=".agentos-research/platform-stage-1")
    parser.add_argument("--ticket", required=True)
    args = parser.parse_args(argv)

    canonical = (Path(args.db) / "goals" / args.goal / "evidence-pack.json")
    if not canonical.is_file():
        raise SystemExit(f"canonical pack missing: {canonical}")
    raw = canonical.read_bytes()
    pack = json.loads(raw.decode("utf-8"))
    file_sha = sha256_bytes(raw)
    payload = payload_sha(pack)
    if pack.get("sha256") not in (payload,):
        # the runtime's payload digest is authoritative; ours must match
        raise SystemExit(
            f"payload digest mismatch: pack self-hash {pack.get('sha256')} "
            f"!= recomputed {payload}")

    evidence_dir = Path(args.ticket) / "results" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    target = evidence_dir / f"evidence-pack-{file_sha}.json"
    target.write_bytes(raw)

    print(json.dumps({
        "canonical_runtime_path": canonical.as_posix(),
        "tracked_path": target.as_posix(),
        "sha256": file_sha,
        "payload_sha256": payload,
        "chain_fresh": pack.get("research", {}).get("chain_fresh"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
