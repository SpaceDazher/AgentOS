"""Post-run assembly for SLOQUAL-001:
- copies raw JSONL traces into traces/<run-id>/
- writes artifact-manifest.json (SHA-256 over every raw/trace artifact)
Usage: python -m agentos.sloqual.postprocess --ticket DIR --run-ids A B
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agentos.sloqual.postprocess")
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--run-ids", nargs="+", required=True)
    args = parser.parse_args(argv)

    ticket = Path(args.ticket)
    by_path: dict[str, dict] = {}
    traces_root = ticket / "traces"
    for run_id in args.run_ids:
        run_dir = ticket / "raw" / run_id
        if not run_dir.exists():
            raise SystemExit(f"missing run dir: {run_dir}")
        trace_dir = traces_root / run_id
        if trace_dir.exists():
            shutil.rmtree(trace_dir)
        trace_dir.mkdir(parents=True)
        for jsonl in sorted(run_dir.rglob("*.jsonl")):
            rel = jsonl.relative_to(run_dir)
            dest = trace_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(jsonl, dest)
        candidates = [p for p in sorted(run_dir.rglob("*")) if p.is_file()]
        candidates += [p for p in sorted(traces_root.rglob("*"))
                       if p.is_file()]
        for path in candidates:
            if path.suffix.lower() in (".db", ".wal", ".shm"):
                continue  # reproducible scratch, excluded by design
            rel = path.relative_to(ticket)
            key = str(rel).replace("\\", "/")
            by_path[key] = {
                "path": key,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    entries = [by_path[k] for k in sorted(by_path)]
    manifest = {
        "schema": "agentos.artifact-manifest/v1",
        "generated_at_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "algorithm": "sha256",
        "run_ids": args.run_ids,
        "artifacts": entries,
        "artifact_count": len(entries),
        "note": "covers raw/ result files and traces/ JSONL copies; "
                "*.db/*.wal/*.shm workloads are reproducible scratch, "
                "excluded by design",
    }
    out = ticket / "artifact-manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "artifacts": len(entries)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
