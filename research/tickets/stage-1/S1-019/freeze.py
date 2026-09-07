"""Freeze every S1-019 technical input by repository-relative SHA-256."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

TICKET = Path(__file__).resolve().parent
REPO = TICKET.parents[3]

FILES = (
    "research/tickets/stage-1/S1-019/build_inputs.py",
    "research/tickets/stage-1/S1-019/freeze.py",
    "research/tickets/stage-1/S1-019/decision-input-policy.json",
    "research/tickets/stage-1/S1-019/dependency_gate.py",
    "research/tickets/stage-1/S1-019/preflight_wall_clock.py",
    "research/tickets/stage-1/S1-019/results/dependency-gate.json",
    "research/tickets/stage-1/S1-019/results/wall-clock-preflight.json",
    "research/tickets/stage-1/S1-019/source-registry.json",
    "research/tickets/stage-1/S1-019/synthesis-contract.json",
    "research/tickets/stage-1/S1-019/schemas/synthesis-contract.schema.json",
    "research/tickets/stage-1/S1-019/schemas/decision-matrix.schema.json",
    "research/tickets/stage-1/S1-019/normalization-policy.json",
    "research/tickets/stage-1/S1-019/precedence-policy.json",
    "research/tickets/stage-1/S1-019/assumption-ledger.json",
    "research/tickets/stage-1/S1-019/limitation-ledger.json",
    "research/tickets/stage-1/S1-019/contradiction-ledger.json",
    "research/tickets/stage-1/S1-019/risk-ledger.json",
    "research/tickets/stage-1/S1-019/decision-matrix.json",
    "research/tickets/stage-1/S1-019/reverse-traceability.json",
    "research/tickets/stage-1/S1-019/prototype-contract.json",
    "research/tickets/stage-1/S1-019/cases.json",
    "research/tickets/stage-1/S1-019/oracle.json",
    "research/tickets/stage-1/S1-019/corpus-manifest.json",
    "research/tickets/stage-1/S1-019/rubric.json",
    "research/tickets/stage-1/S1-019/decision-rule.json",
    "research/tickets/stage-1/S1-019/evaluator.py",
    "research/tickets/stage-1/S1-019/comparator.py",
    "research/tickets/stage-1/S1-019/sensitivity.py",
    "research/tickets/stage-1/S1-019/runner.py",
    "research/tickets/stage-1/S1-019/operator-questionnaire.md",
)


def main() -> int:
    files = {}
    for rel in FILES:
        path = REPO / rel
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"missing/link frozen file: {rel}")
        files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    registry = json.loads((TICKET / "source-registry.json").read_text("utf-8"))
    for source in registry["sources"]:
        rel = source["canonical_path"]
        path = REPO / rel
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != source["sha256"]:
            raise RuntimeError(f"source snapshot hash mismatch: {rel}")
        files[rel] = actual
    manifest = {
        "schema": "agentos.s1-019.frozen-manifest/v1",
        "version": "1.0.0", "frozen_at": "2026-09-06T00:00:00Z",
        "dependency_commit": "19ff320adfe7153267fb634268038ae16ba25a16",
        "files": dict(sorted(files.items())), "file_count": len(files),
        "network_required_for_evaluation": False,
    }
    (TICKET / "frozen-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({"files": len(files), "status": "FROZEN"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
