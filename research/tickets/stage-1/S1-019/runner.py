"""Run the frozen S1-019 corpus in two distinct child processes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

TICKET = Path(__file__).resolve().parent
REPO = TICKET.parents[3]


def clean_tree() -> bool:
    proc = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain=v1",
                           "--untracked-files=all"], capture_output=True, text=True,
                          check=True)
    return not proc.stdout.strip()


def run() -> dict:
    if not clean_tree():
        raise RuntimeError("runner requires a clean tracked and untracked tree")
    with tempfile.TemporaryDirectory(prefix="agentos-s1019-") as temp:
        root = Path(temp)
        outputs = []
        for label, executor, nonce in (
                ("run-a", "agentos-s1-019-producer", "s1019-A-001"),
                ("run-b", "agentos-s1-019-independent-verifier", "s1019-B-001")):
            out = root / label / "observations.json"
            proc = subprocess.run([
                sys.executable, str(TICKET / "evaluator.py"),
                "--executor-id", executor, "--nonce", nonce, "--out", str(out),
            ], cwd=REPO, capture_output=True, text=True)
            if proc.returncode:
                raise RuntimeError(f"{label} evaluator failed: {proc.stderr}")
            outputs.append((label, out))
        first = json.loads(outputs[0][1].read_text("utf-8"))
        second = json.loads(outputs[1][1].read_text("utf-8"))
        if first["pid"] == second["pid"]:
            raise RuntimeError("evaluator processes reused PID")
        result_root = TICKET / "results"
        for label, source in outputs:
            destination = result_root / label / "observations.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    sensitivity = subprocess.run([sys.executable, str(TICKET / "sensitivity.py")],
                                 cwd=REPO, capture_output=True, text=True)
    if sensitivity.returncode:
        raise RuntimeError(f"sensitivity failed: {sensitivity.stderr}")
    comparison = subprocess.run([
        sys.executable, str(TICKET / "comparator.py"),
        "--run-a", str(TICKET / "results/run-a/observations.json"),
        "--run-b", str(TICKET / "results/run-b/observations.json"),
        "--out", str(TICKET / "results/comparison.json"),
    ], cwd=REPO, capture_output=True, text=True)
    if comparison.returncode:
        raise RuntimeError(f"comparison failed: {comparison.stdout} {comparison.stderr}")
    result = json.loads((TICKET / "results/comparison.json").read_text("utf-8"))
    print(json.dumps({"verdict": result["verdict"],
                      "observations": result["observation_count"]}))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
