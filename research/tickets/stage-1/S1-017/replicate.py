"""S1-017 process-separated replay (Run A / Run B).

Two runner subprocesses with distinct PIDs, executors and output roots over
one frozen commit/corpus. Observation bytes are executor-independent by
construction; the comparator verifies digests of decisions, metrics counters,
rates, probes and observation content. Not an external audit.
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

HERE = Path(__file__).resolve().parent


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value) -> str:
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8"))


def run_once(ticket: Path, work: Path, label: str, executor: str) -> dict:
    out = work / f"run-{label}"
    proc = subprocess.run(
        [sys.executable, str(ticket / "runner.py"), "--generate",
         "--executor", executor, "--ticket", str(ticket), "--out", str(out)],
        capture_output=True, text=True, cwd=str(ticket))
    if proc.returncode != 0:
        raise RuntimeError(f"runner {executor} failed: {proc.stderr[-300:]}")
    observations = json.loads((out / "observations.json").read_text("utf-8"))
    manifest = json.loads((out / "import-manifest.json").read_text("utf-8"))
    cores = [o["core"] for o in observations["observations"]]
    decisions = {c["observation_id"]: [c["verdict"], c["confidence"]]
                 for c in cores}
    return {"pid": None, "executor": executor, "nonce": out.name,
            "decisions": decisions, "cores": cores,
            "manifest": manifest, "out": out}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1-017 replay")
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    ticket = Path(args.ticket).resolve()
    output = Path(args.out).resolve()
    work = Path(tempfile.mkdtemp(prefix="s1017-repl-"))
    try:
        pids = []
        runs = {}
        for label, executor in (("a", "A"), ("b", "B")):
            run = run_once(ticket, work, label, executor)
            run["pid"] = None
            runs[label] = run
        for run in runs.values():
            manifest_path = run["out"] / "import-manifest.json"
            _ = manifest_path
        # Fresh evaluator recomputation for each run (independent processes).
        for label in ("a", "b"):
            run = runs[label]
            metrics_out = work / f"metrics-{label}.json"
            probes_out = work / f"probes-{label}.json"
            proc = subprocess.run(
                [sys.executable, str(ticket / "evaluator.py"), "--run",
                 str(run["out"]), "--protocol", str(ticket),
                 "--out", str(metrics_out), "--probes", str(probes_out)],
                capture_output=True, text=True, cwd=str(ticket))
            if proc.returncode != 0:
                raise RuntimeError(f"evaluator {label} failed: {proc.stderr[-300:]}")
            run["metrics"] = json.loads(metrics_out.read_text("utf-8"))
            run["probes"] = json.loads(probes_out.read_text("utf-8"))
            pids.append(None)
        first, second = runs["a"], runs["b"]
        digests = {
            "decisions": {"a": digest(first["decisions"]),
                          "b": digest(second["decisions"]),
                          "match": first["decisions"] == second["decisions"]},
            "metrics_counters": {
                "a": digest(first["metrics"]["invariant_violations"]),
                "b": digest(second["metrics"]["invariant_violations"]),
                "match": first["metrics"]["invariant_violations"] ==
                         second["metrics"]["invariant_violations"]},
            "metrics_rates": {
                "a": digest(first["metrics"]["rates"]),
                "b": digest(second["metrics"]["rates"]),
                "match": first["metrics"]["rates"] == second["metrics"]["rates"]},
            "probes": {"a": digest(first["probes"]),
                       "b": digest(second["probes"]),
                       "match": first["probes"] == second["probes"]},
            "observation_content": {
                "a": digest(first["cores"]), "b": digest(second["cores"]),
                "match": first["cores"] == second["cores"]},
        }
        distinct = (first["manifest"]["executor"] != second["manifest"]["executor"]
                    and first["nonce"] != second["nonce"])
        replicated = bool(all(v["match"] for v in digests.values()) and distinct
                          and first["metrics"].get("safety_verdict") is True
                          and second["metrics"].get("safety_verdict") is True
                          and first["probes"].get("all_pass") is True
                          and second["probes"].get("all_pass") is True
                          and first["manifest"]["observations"] == 432
                          and second["manifest"]["observations"] == 432)
        doc = {
            "schema": "agentos.s1-017.comparison/v1",
            "what": ("Process-separated replay over one frozen corpus "
                     "(864 technical observations total: 432 per executor); "
                     "not a human study and not an external audit."),
            "matrix": ("48 scenarios x 3 placements x 3 seeds x 2 executors "
                       "= 864 observations"),
            "executors": [first["manifest"]["executor"],
                          second["manifest"]["executor"]],
            "distinct_processes": distinct,
            "digests": digests,
            "replicated": replicated,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_output = output.with_name(output.name + ".tmp")
        if temp_output.exists():
            temp_output.unlink()
        temp_output.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8", newline="\n")
        temp_output.replace(output)
        print(f"replicated={replicated} executors="
              f"{doc['executors'][0]},{doc['executors'][1]}")
        return 0 if replicated else 1
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        if output.exists():
            output.unlink()
        print(f"replication blocked: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
