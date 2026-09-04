"""Explicit input freeze followed by reproducible synthetic evidence generation.

Use --freeze-inputs only after reviewing a protocol/code change. Normal replay
never updates expected hashes. Human collection and canonicalization are absent.
"""
import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
                    + "\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-inputs", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("s1013_publisher_prepare", HERE / "make_bundle.py")
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    if args.freeze_inputs:
        write(HERE / "frozen-manifest.json", {
            "schema": "agentos.s1-013.frozen-manifest/v1", "ticket": "S1-013",
            "protocol_version": publisher.load("pilot-protocol.json")["protocol_version"],
            "hashes": {p: publisher.sha((HERE / p).read_bytes())
                       for p in sorted(publisher._ticket_relative_files(HERE))}})
    errors, _ = publisher.verify_frozen_manifest(HERE)
    if errors:
        raise SystemExit("Frozen inputs invalid: " + "; ".join(errors))
    result = HERE / "results"
    result.mkdir(exist_ok=True)
    commands = [
        ["dependency_gate.py"],
        ["runner.py", "--src", "synthetic/sessions", "--out", "results/import"],
        ["evaluator.py", "--run", "results/import", "--protocol", ".",
         "--out", "results/metrics.json", "--probes", "results/probes.json"],
        ["replicate.py", "--src", "synthetic/sessions", "--ticket", ".",
         "--out", "results/comparison.json"],
    ]
    for command in commands:
        subprocess.run([sys.executable, *command], cwd=HERE, check=True, timeout=180)
    write(result / "dependency-gate.json", publisher.load("dependency-gate.json"))
    return publisher.main([])


if __name__ == "__main__":
    raise SystemExit(main())
