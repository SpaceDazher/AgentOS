"""S1-016 process-separated replay (Run A / Run B, 864 observations).

Both runs use one frozen ticket tree and execute the ticket's current
runner.py + evaluator.py in fresh child processes with distinct PID,
executor ID, nonce and output roots. Canonical terminal states, digests,
invariant counters, round-trip hashes and probe outcomes must match.
Same-host replay is called replay, never an external audit.
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
PROCESS_TIMEOUT_SECONDS = 600


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


def _writable_tmp() -> Path:
    for candidate in (os.environ.get("TMP"), os.environ.get("TEMP"),
                      r"D:\Temp-opencode"):
        if candidate and Path(candidate).is_dir():
            try:
                probe = Path(candidate) / ".s1016-write-test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
                return Path(candidate)
            except OSError:
                continue
    return Path(tempfile.gettempdir())


def run_once(ticket: Path, work: Path, tag: str, executor: str) -> dict[str, Any]:
    if not ticket.is_dir() or ticket.is_symlink():
        raise ValueError(f"ticket is not a regular directory: {ticket}")
    nonce = uuid.uuid4().hex
    imp = work / f"imp-{tag}"
    imp.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["S1016_EXECUTOR"] = executor
    env["S1016_NONCE"] = nonce
    env["TEMP"] = str(_writable_tmp())
    env["TMP"] = str(_writable_tmp())
    pids: list[int] = []
    commands = (
        ("generate", [sys.executable, str(ticket / "runner.py"), "--generate",
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
            raise RuntimeError(f"replication {tag}/{step} failed: {detail[:500]}")
    metrics = _read_json(work / f"metrics-{tag}.json", "metrics")
    probe_doc = _read_json(work / f"probes-{tag}.json", "probes")
    observations = _read_json(imp / "observations.json", "observations")
    manifest = _read_json(imp / "import-manifest.json", "manifest")
    if metrics.get("schema") != "agentos.s1-016.metrics/v1":
        raise ValueError("metrics schema mismatch")
    if metrics.get("human_study_n", 0) != 0:
        raise ValueError("human data appeared in synthetic replication")
    if not isinstance(observations.get("observations"), list):
        raise ValueError("observations has no list")
    if len(observations["observations"]) != 432:
        raise ValueError("expected 432 observations per executor")
    cores = [o["core"] for o in observations["observations"]]
    decisions = sorted((c.get("scenario_id"), c.get("representation"), c.get("seed"),
                        c.get("status"),
                        tuple(o["outcome"] for o in c.get("op_outcomes", [])))
                       for c in cores)
    hashes = sorted(c.get("output_sha256") for c in cores)
    return {"metrics": metrics, "probes": probe_doc, "observations": observations,
            "manifest": manifest, "decisions": decisions, "hashes": hashes,
            "pid": pids[-1], "stage_pids": pids, "executor": executor,
            "nonce": nonce}


def _digest(value: Any) -> str:
    return sha(canonical_json(value))


def _remove_file(path: Path) -> None:
    if path.is_file() or path.is_symlink():
        path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1-016 replay")
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    ticket = Path(args.ticket).resolve()
    output = Path(args.out).resolve()
    work = Path(tempfile.mkdtemp(prefix="s1016-repl-", dir=str(_writable_tmp())))
    try:
        first = run_once(ticket, work, "a", "A")
        second = run_once(ticket, work, "b", "B")
        # Hashed cores must be byte-identical; wall-clock latencies ride
        # alongside as producer-measured same-host evidence and legitimately
        # differ, so they are excluded from the byte comparison.
        first_cores = [o["core"] for o in first["observations"]["observations"]]
        second_cores = [o["core"] for o in second["observations"]["observations"]]
        if first_cores != second_cores:
            raise RuntimeError("observation cores differ across executors")
        digests = {
            "decisions": {"a": _digest(first["decisions"]), "b": _digest(second["decisions"]),
                          "match": first["decisions"] == second["decisions"]},
            "observation_hashes": {
                "a": _digest(first["hashes"]), "b": _digest(second["hashes"]),
                "match": first["hashes"] == second["hashes"]},
            "metrics_counters": {
                "a": _digest(first["metrics"]["invariant_violations"]),
                "b": _digest(second["metrics"]["invariant_violations"]),
                "match": first["metrics"]["invariant_violations"] ==
                second["metrics"]["invariant_violations"]},
            "metrics_rates": {
                "a": _digest(first["metrics"]["rates"]),
                "b": _digest(second["metrics"]["rates"]),
                "match": first["metrics"]["rates"] == second["metrics"]["rates"]},
            "probes": {"a": _digest(first["probes"]), "b": _digest(second["probes"]),
                       "match": first["probes"] == second["probes"]},
            "observation_content": {
                "a": _digest(first_cores),
                "b": _digest(second_cores),
                "match": first_cores == second_cores},
        }
        manifests_match = (
            first["manifest"].get("corpus_sha256") == second["manifest"].get("corpus_sha256")
            and first["manifest"].get("ticket_commit") == second["manifest"].get("ticket_commit"))
        distinct = (first["pid"] != second["pid"]
                    and first["nonce"] != second["nonce"]
                    and first["executor"] != second["executor"])
        replicated = bool(all(v["match"] for v in digests.values()) and manifests_match
                          and distinct
                          and first["metrics"].get("safety_verdict") is True
                          and second["metrics"].get("safety_verdict") is True
                          and first["probes"].get("all_pass") is True
                          and second["probes"].get("all_pass") is True)
        doc = {
            "schema": "agentos.s1-016.comparison/v1",
            "what": ("Process-separated replay over one frozen corpus "
                     "(864 technical observations total: 432 per executor); "
                     "not a second study and not an external audit."),
            "matrix": "48 scenarios x 3 representations x 3 seeds x 2 executors = 864 observations",
            "pids": [first["pid"], second["pid"]],
            "executors": [first["executor"], second["executor"]],
            "distinct_processes": distinct,
            "manifests_match": manifests_match,
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


if __name__ == "__main__":
    raise SystemExit(main())
