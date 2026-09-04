"""S1-013 analysis replication (stdlib only).

Runs the importer + scorer twice in separate processes over the same
frozen synthetic data and compares hashes, counts, scores and verdict.
This replicates ANALYSIS, never a human pilot. Any divergence fails
closed (exit 1, no comparison record published).

Usage: py -3.12 replicate.py --src synthetic/sessions --ticket .
         --out results/comparison.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_once(src: Path, ticket: Path, work: Path, tag: str) -> dict:
    env = dict(os.environ)
    pids = []
    for step, argv in (
            ("import", [sys.executable, str(HERE / "runner.py"), "--src",
                        str(src), "--out", str(work / f"imp-{tag}")]),
            ("score", [sys.executable, str(HERE / "evaluator.py"), "--run",
                       str(work / f"imp-{tag}"), "--protocol", str(ticket),
                       "--out", str(work / f"metrics-{tag}.json"),
                       "--probes", str(work / f"probes-{tag}.json")])):
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=env)
        pids.append(proc.pid)
        _, stderr = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"replication {tag}/{step} failed: "
                               f"{stderr[:300]}")
    metrics = json.loads((work / f"metrics-{tag}.json").read_text(
        encoding="utf-8"))
    probes = json.loads((work / f"probes-{tag}.json").read_text(
        encoding="utf-8"))
    observations = json.loads(
        (work / f"imp-{tag}" / "observations.json").read_text(
            encoding="utf-8"))
    return {"metrics": metrics, "probes": probes,
            "observations": observations,
            "pid": pids[-1]}


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1-013 replication")
    parser.add_argument("--src", required=True)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    src = Path(args.src)
    ticket = Path(args.ticket)
    work = Path(tempfile.mkdtemp(prefix="s1013-repl-"))
    first = run_once(src, ticket, work, "a")
    second = run_once(src, ticket, work, "b")
    keys = ("metrics", "probes", "observations")
    digests = {}
    match = True
    for key in keys:
        first_sha = sha(json.dumps(first[key], sort_keys=True).encode())
        second_sha = sha(json.dumps(second[key], sort_keys=True).encode())
        digests[key] = {"a": first_sha, "b": second_sha,
                        "match": first_sha == second_sha}
        match = match and first_sha == second_sha
    doc = {"schema": "agentos.s1-013.comparison/v1",
           "what": "Independent analysis replication over identical "
                   "frozen synthetic data (not a second human pilot).",
           "pids": [first["pid"], second["pid"]],
           "distinct_processes": first["pid"] != second["pid"],
           "digests": digests,
           "replicated": bool(match)}
    Path(args.out).write_text(json.dumps(doc, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    print(f"replicated={match} "
          f"pids={first['pid']},{second['pid']}")
    return 0 if match else 1


if __name__ == "__main__":
    raise SystemExit(main())
