"""S1-015 process-separated replay (Run A / Run B).

Both runs use one frozen ticket tree, execute the ticket's current runner.py
and evaluator.py in fresh child processes with distinct PID/executor/nonce and
output roots, then compare canonical decisions, hard counters, observation
hashes and probe outcomes. Same-host replay is called replay, never an
external audit.

Usage: replicate.py --ticket . --out results/comparison.json
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
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROCESS_TIMEOUT_SECONDS = 180


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


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


def run_once(ticket: Path, work: Path, tag: str, executor: str) -> dict[str, Any]:
    if not ticket.is_dir() or ticket.is_symlink():
        raise ValueError(f"ticket is not a regular directory: {ticket}")
    nonce = uuid.uuid4().hex
    imp = work / f"imp-{tag}"
    imp.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["S1015_EXECUTOR"] = executor
    env["S1015_NONCE"] = nonce
    # Temp redirection to D: when the system TEMP is small (see task note).
    pids: list[int] = []
    commands = (
        ("import", [sys.executable, str(ticket / "runner.py"), "--generate",
                    "--executor", executor, "--ticket", str(ticket),
                    "--out", str(imp)]),
        ("score", [sys.executable, str(ticket / "evaluator.py"), "--run", str(imp),
                   "--protocol", str(ticket),
                   "--out", str(work / f"metrics-{tag}.json"),
                   "--probes", str(work / f"probes-{tag}.json")]),
    )
    for step, argv in commands:
        try:
            proc = subprocess.Popen(argv, cwd=str(ticket), stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, env=env)
            pids.append(proc.pid)
            _, stderr = proc.communicate(timeout=PROCESS_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            proc.communicate()
            raise RuntimeError(f"replication {tag}/{step} timed out") from exc
        if proc.returncode != 0:
            detail = (stderr or "").replace("\r", " ").replace("\n", " ")
            raise RuntimeError(f"replication {tag}/{step} failed: {detail[:400]}")
    metrics = _read_json(work / f"metrics-{tag}.json", "metrics")
    probe_doc = _read_json(work / f"probes-{tag}.json", "probes")
    observations = _read_json(imp / "observations.json", "observations")
    if metrics.get("schema") != "agentos.s1-015.metrics/v1":
        raise ValueError("metrics schema mismatch")
    if metrics.get("synthetic") is not True or metrics.get("human_study_n", 0) != 0:
        raise ValueError("human data appeared in synthetic replication")
    if probe_doc.get("schema") != "agentos.s1-015.probes/v1":
        raise ValueError("probes schema mismatch")
    if not isinstance(probe_doc.get("all_pass"), bool):
        raise ValueError("probe result has no boolean all_pass")
    if not isinstance(observations.get("observations"), list) or not observations["observations"]:
        raise ValueError("observations empty")
    if len(observations["observations"]) != 240:
        raise ValueError(f"expected 240 observations per executor, got {len(observations['observations'])}")
    decisions = sorted((o.get("case_id"), o.get("variant"), o.get("seed"),
                        o.get("canonical_decision")) for o in observations["observations"])
    hashes = sorted(o.get("output_sha256") for o in observations["observations"])
    return {"metrics": metrics, "probes": probe_doc, "observations": observations,
            "decisions": decisions, "hashes": hashes, "pid": pids[-1],
            "stage_pids": pids, "executor": executor, "nonce": nonce}


def _digest(value: Any) -> str:
    return sha(canonical_json(value))


def _remove_file(path: Path) -> None:
    if path.is_file() or path.is_symlink():
        path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1-015 replay")
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    ticket = Path(args.ticket).resolve()
    output = Path(args.out).resolve()
    tmp_base = Path(os.environ.get("TMP", "")) or Path(tempfile.gettempdir())
    work = Path(tempfile.mkdtemp(prefix="s1015-repl-", dir=str(_writable_tmp())))
    try:
        first = run_once(ticket, work, "a", "A")
        second = run_once(ticket, work, "b", "B")
        # Observation bytes are executor-independent by construction
        # (executor lives only in the manifest); both runs must be identical.
        content_match = (first["observations"] == second["observations"])
        digests = {
            "decisions": {"a": _digest(first["decisions"]), "b": _digest(second["decisions"]),
                          "match": first["decisions"] == second["decisions"]},
            "metrics_counters": {
                "a": _digest(first["metrics"]["hard_counters"]),
                "b": _digest(second["metrics"]["hard_counters"]),
                "match": first["metrics"]["hard_counters"] == second["metrics"]["hard_counters"]},
            "metrics_rates": {
                "a": _digest(first["metrics"]["rates"]),
                "b": _digest(second["metrics"]["rates"]),
                "match": first["metrics"]["rates"] == second["metrics"]["rates"]},
            "probes": {"a": _digest(first["probes"]), "b": _digest(second["probes"]),
                       "match": first["probes"] == second["probes"]},
            "observation_content": {
                "a": _digest(first["observations"]),
                "b": _digest(second["observations"]),
                "match": content_match},
        }
        distinct = (first["pid"] != second["pid"]
                    and first["nonce"] != second["nonce"]
                    and first["executor"] != second["executor"])
        replicated = bool(all(v["match"] for v in digests.values()) and distinct
                          and first["metrics"].get("safety_verdict") is True
                          and second["metrics"].get("safety_verdict") is True
                          and first["probes"].get("all_pass") is True
                          and second["probes"].get("all_pass") is True)
        doc = {
            "schema": "agentos.s1-015.comparison/v1",
            "what": ("Process-separated replay over one frozen corpus "
                     "(480 technical observations total: 240 per executor); "
                     "not a second human study."),
            "matrix": "40 cases x 2 variants x 3 seeds x 2 executors = 480 observations",
            "pids": [first["pid"], second["pid"]],
            "executors": [first["executor"], second["executor"]],
            "distinct_processes": distinct,
            "digests": digests,
            "replicated": replicated,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_output = output.with_name(output.name + ".tmp")
        _remove_file(temp_output)
        temp_output.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8", newline="\n")
        temp_output.replace(output)
        print(f"replicated={replicated} pids={first['pid']},{second['pid']}")
        return 0 if replicated else 1
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        _remove_file(output)
        print(f"replication blocked: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _writable_tmp() -> Path:
    for candidate in (os.environ.get("TMP"), os.environ.get("TEMP"), r"D:\Temp-opencode"):
        if candidate and Path(candidate).is_dir():
            try:
                probe = Path(candidate) / ".s1015-write-test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
                return Path(candidate)
            except OSError:
                continue
    return Path(tempfile.gettempdir())


if __name__ == "__main__":
    raise SystemExit(main())
