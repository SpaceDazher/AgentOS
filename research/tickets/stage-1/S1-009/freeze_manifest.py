#!/usr/bin/env python3
"""Recompute S1-009 authority hashes from local bytes.

This maintenance command never retrieves network content.  It updates only
the byte-bound hash fields and derived case coverage in corpus-manifest.json;
the protocol-snapshot-manifest remains the source of truth for remote bytes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    path = ROOT / "corpus-manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    files = {
        "canonical_envelope_schema": "canonical-envelope.schema.json",
        "adapter_contract": "adapter-contract.json",
        "capability_matrix": "capability-matrix.json",
        "rubric": "rubric.json",
        "semantic_model": "semantic-model.json",
        "protocol_snapshot": "protocol-snapshot-manifest.json",
        "dependency_gate": "dependency-gate.json",
        "cases": "cases.json",
    }
    frozen = data.setdefault("frozen_artifacts", {})
    for key, filename in files.items():
        entry = frozen.setdefault(key, {})
        entry["file"] = filename
        entry["sha256"] = sha256(ROOT / filename)
    data["evaluator_sha256"] = sha256(ROOT / "evaluator.py")
    data["runner_sha256"] = sha256(ROOT / "runner.py")

    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]
    groups: dict[str, dict[str, int]] = {}
    for case in cases:
        group = groups.setdefault(case["protocol"], {"count": 0})
        group["count"] += 1
        category = case.get("category", "")
        group[category] = group.get(category, 0) + 1
    data.setdefault("corpus", {})["total_cases"] = len(cases)
    data["corpus"]["groups"] = groups
    coverage: dict[str, list[str]] = {}
    for case in cases:
        if case.get("mapping_category") == "capability_mapping":
            coverage.setdefault(case["capability_row"], []).append(case["case_id"])
    data["corpus"]["capability_row_coverage"] = coverage
    matrix = json.loads((ROOT / "capability-matrix.json").read_text(encoding="utf-8"))
    supported = [row["surface_id"] for row in matrix["matrix"]
                 if row.get("loss_class") != "unsupported"]
    data["corpus"]["passing_capability_rows"] = len(supported)
    data["corpus"]["unsupported_capability_rows"] = [row["surface_id"] for row in matrix["matrix"]
                                                        if row.get("loss_class") == "unsupported"]
    path.write_bytes((json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
