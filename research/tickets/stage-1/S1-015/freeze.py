"""Explicit freeze command for S1-015 (run before measurement, never inside evaluator).

Covers the dependency result code, source registry/snapshots, threat model,
schemas, contract, rubric, decision rule, corpus/oracle/generator, UI assets,
evaluator, runner, publisher and test fixtures. Replay rejects any changed,
removed or added input. Usage: py -3.12 freeze.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent

EXCLUDED_NAMES = {
    "bundle.json",
    "candidate-record.json",
    "dependency-gate.json",
    "evaluation-record.json",
    "frozen-manifest.json",
    "operator-decision.json",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ticket_inputs(here: Path) -> set[str]:
    paths: set[str] = set()
    for path in sorted(here.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if "__pycache__" in path.relative_to(here).parts:
            continue
        rel = path.relative_to(here).as_posix()
        if path.name in EXCLUDED_NAMES or rel.startswith("results/"):
            continue
        if path.name.endswith(".tmp") or path.name.endswith(".pyc"):
            continue
        paths.add(rel)
    return paths


def main() -> int:
    paths = ticket_inputs(HERE)
    hashes = {rel: sha((HERE / PurePosixPath(rel)).read_bytes())
              for rel in sorted(paths)}
    manifest = {
        "schema": "agentos.s1-015.frozen-manifest/v1",
        "ticket": "S1-015",
        "hashes": hashes,
        "input_count": len(hashes),
        "note": ("Freeze covers dependency code+result inputs, sources, threat "
                 "model, schema/contract, rubric/decision rule, corpus/oracle, "
                 "UI assets, importer/evaluator/runner/publisher and test "
                 "fixtures. Generated outputs (bundle/candidate/evaluation "
                 "records, operator decision, results/) are not inputs."),
    }
    (HERE / "frozen-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"inputs": len(hashes)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
