"""Post-run assembly for SLOQUAL-001:
- copies raw JSONL traces into traces/<run-id>/
- writes artifact-manifest.json (SHA-256 over every raw/trace artifact)
Usage: python -m agentos.sloqual.postprocess --ticket DIR --run-ids A B
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


_SCRATCH_SUFFIXES = (
    ".db", ".db-journal", ".db-shm", ".db-wal", ".wal", ".shm",
    ".bin", ".dat", ".raw", ".tmp",
)


def _is_reproducible_scratch(path: Path) -> bool:
    return path.name.lower().endswith(_SCRATCH_SUFFIXES)


def _files_under(root: Path) -> list[Path]:
    files: list[Path] = []
    for current, directories, filenames in os.walk(root):
        directories.sort()
        filenames.sort()
        files.extend(Path(current) / name for name in filenames)
    return files


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_entry(ticket: Path, path: Path) -> dict:
    before = path.stat()
    digest = sha256_file(path)
    after = path.stat()
    if (before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns):
        raise RuntimeError(f"artifact changed while hashing: {path}")
    key = str(path.relative_to(ticket)).replace("\\", "/")
    return {"path": key, "bytes": after.st_size, "sha256": digest}


def _progress(phase: str, **details) -> None:
    print(json.dumps({"phase": phase, **details}), flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agentos.sloqual.postprocess")
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--run-ids", nargs="+", required=True)
    args = parser.parse_args(argv)

    ticket = Path(args.ticket)
    selected_paths: dict[str, Path] = {}
    trace_pairs: list[tuple[str, str]] = []
    traces_root = ticket / "traces"
    for run_id in args.run_ids:
        run_dir = ticket / "raw" / run_id
        if not run_dir.exists():
            raise SystemExit(f"missing run dir: {run_dir}")
        run_files = _files_under(run_dir)
        _progress("walk", run_id=run_id, files=len(run_files))
        trace_dir = traces_root / run_id
        trace_dir.mkdir(parents=True, exist_ok=True)
        expected_traces: set[Path] = set()
        for jsonl in (path for path in run_files
                      if path.suffix.lower() == ".jsonl"):
            rel = jsonl.relative_to(run_dir)
            dest = trace_dir / rel
            expected_traces.add(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            source_key = str(jsonl.relative_to(ticket)).replace("\\", "/")
            dest_key = str(dest.relative_to(ticket)).replace("\\", "/")
            trace_pairs.append((source_key, dest_key))
            if (dest.exists()
                    and dest.stat().st_size == jsonl.stat().st_size
                    and dest.stat().st_mtime_ns == jsonl.stat().st_mtime_ns):
                continue
            with tempfile.NamedTemporaryFile(
                    dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp",
                    delete=False) as handle:
                staging = Path(handle.name)
            try:
                shutil.copy2(jsonl, staging)
                staging.replace(dest)
            finally:
                staging.unlink(missing_ok=True)
        for stale in _files_under(trace_dir):
            if stale not in expected_traces:
                stale.unlink()
        _progress("trace-sync", run_id=run_id,
                  traces=len(expected_traces))
        candidates = run_files + sorted(expected_traces)
        for path in candidates:
            if _is_reproducible_scratch(path):
                continue  # reproducible scratch, excluded by design
            key = str(path.relative_to(ticket)).replace("\\", "/")
            selected_paths[key] = path
    ordered_paths = [selected_paths[key] for key in sorted(selected_paths)]
    _progress("hash-start", artifacts=len(ordered_paths), workers=8)
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(ordered_paths)))) as pool:
        entries = list(pool.map(
            lambda path: _artifact_entry(ticket, path), ordered_paths))
    _progress("hash-complete", artifacts=len(entries))
    entries_by_path = {entry["path"]: entry for entry in entries}
    for source_key, dest_key in trace_pairs:
        if (entries_by_path[source_key]["sha256"]
                != entries_by_path[dest_key]["sha256"]):
            raise RuntimeError(
                f"trace copy differs from raw source: {source_key} -> {dest_key}")
    manifest = {
        "schema": "agentos.artifact-manifest/v1",
        "generated_at_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "algorithm": "sha256",
        "run_ids": args.run_ids,
        "artifacts": entries,
        "artifact_count": len(entries),
        "note": "covers raw/ result files and traces/ JSONL copies; "
                "SQLite sidecars and load-generator binary/raw/temp files "
                "are reproducible scratch, excluded by design",
    }
    out = ticket / "artifact-manifest.json"
    _progress("publish-start", out=str(out))
    with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=out.parent,
            prefix=f".{out.name}.", suffix=".tmp", delete=False) as handle:
        staging = Path(handle.name)
        handle.write(json.dumps(manifest, indent=2) + "\n")
    try:
        staging.replace(out)
    finally:
        staging.unlink(missing_ok=True)
    _progress("publish-complete", out=str(out))
    print(json.dumps({"out": str(out), "artifacts": len(entries)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
