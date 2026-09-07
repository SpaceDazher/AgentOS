"""Freeze S1-020 evaluator inputs and code by SHA-256."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
BASE_COMMIT = "78a4218606212c4f65642fe8dbf9c6a808209cfb"
FILES = [
    "research/tickets/stage-1/S1-020/closure-contract.json",
    "research/tickets/stage-1/S1-020/source-registry.json",
    "research/tickets/stage-1/S1-020/probe-registry.json",
    "research/tickets/stage-1/S1-020/coverage-matrix.json",
    "research/tickets/stage-1/S1-020/cases.json",
    "research/tickets/stage-1/S1-020/oracle.json",
    "research/tickets/stage-1/S1-020/rubric.json",
    "research/tickets/stage-1/S1-020/dependency-gate.json",
    "research/tickets/stage-1/S1-020/dependency_gate.py",
    "research/tickets/stage-1/S1-020/evaluator.py",
    "research/tickets/stage-1/S1-020/comparator.py",
    "research/tickets/stage-1/S1-020/sensitivity.py",
    "research/tickets/stage-1/S1-020/runner.py",
    "tests/test_s1_020_regressions.py",
]


def main() -> int:
    hashes = {}
    for rel in FILES:
        path = ROOT / rel
        if not path.is_file():
            raise SystemExit(f"missing frozen file: {rel}")
        hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"schema": "agentos.s1-020.frozen-manifest/v1",
                "base_commit": BASE_COMMIT, "files": hashes,
                "decision_inputs_exclude_wall_clock": True}
    (HERE / "frozen-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(hashes), "base_commit": BASE_COMMIT}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
