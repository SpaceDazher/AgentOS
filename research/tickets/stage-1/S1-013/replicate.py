"""Re-run and compare the S1-013 synthetic analysis in two processes.

The replication record is evidence about the importer/evaluator execution,
not a readiness flag.  Both runs read the same source tree, execute the
ticket's current ``runner.py`` and ``evaluator.py`` in fresh child processes,
and compare canonical digests of every analysis output.  A malformed or
incomplete run fails closed and does not leave a stale comparison record.

Usage::

    py -3.12 replicate.py --src synthetic/sessions --ticket . \
        --out results/comparison.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROCESS_TIMEOUT_SECONDS = 120


def sha(data: bytes) -> str:
    """Return a content digest for a byte string."""

    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    """Serialize JSON deterministically for equality and evidence hashes."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def source_digest(src: Path) -> tuple[str, dict[str, str]]:
    """Digest all regular source files, including relative names.

    Names are part of the digest so a file swap cannot preserve the same
    byte-only hash.  Symlinks are rejected because the replication must be
    bound to a local frozen corpus rather than an ambient path.
    """

    if not src.is_dir() or src.is_symlink():
        raise ValueError(f"source is not a regular directory: {src}")
    files: dict[str, str] = {}
    for path in sorted(src.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"source symlink is not allowed: {path}")
        if not path.is_file():
            continue
        rel = path.relative_to(src).as_posix()
        files[rel] = sha(path.read_bytes())
    if not files:
        raise ValueError("source corpus is empty")
    return sha(canonical_json(files)), files


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"{label} unreadable: {exc}") from exc
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{label} must be a non-empty JSON object")
    return value


def _validate_run_outputs(work: Path, tag: str) -> dict[str, Any]:
    """Validate the minimum output contract before hashing a run."""

    metrics = _read_json(work / f"metrics-{tag}.json", "metrics")
    probes = _read_json(work / f"probes-{tag}.json", "probes")
    observations = _read_json(
        work / f"imp-{tag}" / "observations.json", "observations")
    if not str(metrics.get("schema", "")).startswith(
            "agentos.s1-013.metrics/"):
        raise ValueError("metrics schema is not an S1-013 metrics schema")
    if metrics.get("synthetic") is not True:
        raise ValueError("metrics are not explicitly synthetic")
    if metrics.get("human_n", 0) != 0:
        raise ValueError("human data appeared in synthetic replication")
    if not str(probes.get("schema", "")).startswith(
            "agentos.s1-013.probes/"):
        raise ValueError("probes schema is not an S1-013 probes schema")
    if not isinstance(probes.get("all_pass"), bool):
        raise ValueError("probe result has no boolean all_pass")
    if not isinstance(observations.get("observations"), list):
        raise ValueError("observations has no list")
    if not observations["observations"]:
        raise ValueError("observations are empty")
    return {"metrics": metrics, "probes": probes,
            "observations": observations}


def run_once(src: Path, ticket: Path, work: Path, tag: str) -> dict[str, Any]:
    """Run importer and evaluator using the supplied ticket directory.

    ``ticket`` is deliberately used instead of this module's directory: it
    keeps tests and publication checks honest when they operate on a copied
    ticket.  Each stage is a separate child process and receives no shell.
    """

    if not ticket.is_dir() or ticket.is_symlink():
        raise ValueError(f"ticket is not a regular directory: {ticket}")
    work.mkdir(parents=True, exist_ok=True)
    source_sha, source_files = source_digest(src)
    env = dict(os.environ)
    pids: list[int] = []
    commands = (
        ("import", [sys.executable, str(ticket / "runner.py"), "--src",
                    str(src), "--out", str(work / f"imp-{tag}")]),
        ("score", [sys.executable, str(ticket / "evaluator.py"), "--run",
                    str(work / f"imp-{tag}"), "--protocol", str(ticket),
                    "--out", str(work / f"metrics-{tag}.json"),
                    "--probes", str(work / f"probes-{tag}.json")]),
    )
    for step, argv in commands:
        try:
            proc = subprocess.Popen(
                argv, cwd=str(ticket), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, env=env)
            pids.append(proc.pid)
            _, stderr = proc.communicate(timeout=PROCESS_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            proc.communicate()
            raise RuntimeError(f"replication {tag}/{step} timed out") from exc
        if proc.returncode != 0:
            detail = (stderr or "").replace("\r", " ").replace("\n", " ")
            raise RuntimeError(
                f"replication {tag}/{step} failed: {detail[:400]}")
    outputs = _validate_run_outputs(work, tag)
    # Recheck after execution, so a concurrently modified corpus cannot be
    # silently treated as the input for both sides of the comparison.
    source_sha_after, source_files_after = source_digest(src)
    if source_sha != source_sha_after or source_files != source_files_after:
        raise RuntimeError("source corpus changed during replication")
    return {**outputs, "source_sha256": source_sha,
            "source_files": source_files, "pid": pids[-1],
            "stage_pids": pids}


def _digest(value: Any) -> str:
    return sha(canonical_json(value))


def _remove_file(path: Path) -> None:
    """Remove only the requested output file, never a containing directory."""

    if path.is_file() or path.is_symlink():
        path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1-013 analysis replication")
    parser.add_argument("--src", required=True)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    src = Path(args.src).resolve()
    ticket = Path(args.ticket).resolve()
    output = Path(args.out).resolve()
    work = Path(tempfile.mkdtemp(prefix="s1013-repl-"))
    try:
        first = run_once(src, ticket, work, "a")
        second = run_once(src, ticket, work, "b")
        keys = ("metrics", "probes", "observations")
        digests: dict[str, dict[str, Any]] = {}
        match = True
        for key in keys:
            first_sha = _digest(first[key])
            second_sha = _digest(second[key])
            equal = first_sha == second_sha
            digests[key] = {"a": first_sha, "b": second_sha,
                            "match": equal}
            match = match and equal
        same_source = (first["source_sha256"] == second["source_sha256"]
                       and first["source_files"] == second["source_files"])
        distinct = first["pid"] != second["pid"]
        replicated = bool(match and same_source and distinct)
        doc = {
            "schema": "agentos.s1-013.comparison/v1",
            "what": "Independent analysis replication over identical "
                    "frozen synthetic data (not a second human pilot).",
            "source": {"sha256": first["source_sha256"],
                       "files": first["source_files"],
                       "match": same_source},
            # PIDs are diagnostic only; publication compares the stable
            # digests and the explicit distinct-processes assertion.
            "pids": [first["pid"], second["pid"]],
            "distinct_processes": distinct,
            "digests": digests,
            "replicated": replicated,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_output = output.with_name(output.name + ".tmp")
        _remove_file(temp_output)
        temp_output.write_text(json.dumps(doc, indent=2, ensure_ascii=False)
                               + "\n", encoding="utf-8", newline="\n")
        temp_output.replace(output)
        print(f"replicated={replicated} pids={first['pid']},{second['pid']}")
        return 0 if replicated else 1
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        _remove_file(output)
        print(f"replication blocked: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
