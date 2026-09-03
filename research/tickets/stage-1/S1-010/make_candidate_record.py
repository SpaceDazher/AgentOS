#!/usr/bin/env python3
"""Generate the S1-010 Phase A candidate record (READY_FOR_CANONICALIZATION).

The record contains NO canonical database IDs, no research revision, no
artifact-chain hash, and no chain_fresh claim: those are host-owned Phase B
state.  It records the cloud evidence: frozen hashes, run provenance, verdict
proposal, limitations, and the exact local Phase B command.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

TICKET_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TICKET_ROOT.parents[3]

TRACKED_FILES = [
    "TASK_FOR_CLOUD_GLM.md",
    "dependency_gate.py",
    "dependency-gate.json",
    "fetch_sources.py",
    "source-registry.json",
    "threat-model.json",
    "tool-poisoning-contract.json",
    "rubric.json",
    "build_corpus.py",
    "cases.json",
    "corpus-manifest.json",
    "runner.py",
    "evaluator.py",
    "make_bundle.py",
    "make_candidate_record.py",
    "bundle.json",
    "results/comparison.json",
    "results/metrics.json",
    "results/probes.json",
    "results/ENVIRONMENT.md",
    "results/control-decision.md",
    "results/roadmap.md",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    snap_dir = TICKET_ROOT / "snapshots"
    snapshot_hashes = {
        f"research/tickets/stage-1/S1-010/snapshots/{p.name}": sha256_file(p)
        for p in sorted(snap_dir.glob("*")) if p.is_file()
    }
    tracked = {}
    for rel in TRACKED_FILES:
        path = TICKET_ROOT / rel
        if not path.is_file():
            raise RuntimeError(f"tracked artifact missing: {rel}")
        tracked[f"research/tickets/stage-1/S1-010/{rel}"] = sha256_file(path)
    tracked["tests/test_s1_010_regressions.py"] = sha256_file(
        REPO_ROOT / "tests/test_s1_010_regressions.py")

    comparison = json.loads((TICKET_ROOT / "results" / "comparison.json")
                            .read_text(encoding="utf-8"))
    probes = json.loads((TICKET_ROOT / "results" / "probes.json")
                        .read_text(encoding="utf-8"))
    manifest = json.loads((TICKET_ROOT / "corpus-manifest.json")
                          .read_text(encoding="utf-8"))
    gate = json.loads((TICKET_ROOT / "dependency-gate.json")
                      .read_text(encoding="utf-8"))
    run_a = json.loads((TICKET_ROOT / "results/run-a/run-summary.json")
                       .read_text(encoding="utf-8"))
    run_b = json.loads((TICKET_ROOT / "results/run-b/run-summary.json")
                       .read_text(encoding="utf-8"))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT),
                          capture_output=True, text=True, check=True).stdout.strip()

    record = {
        "schema": "agentos.s1-010.candidate-record/v1",
        "ticket": "S1-010",
        "phase": "A (cloud branch work)",
        "status": "READY_FOR_CANONICALIZATION",
        "proposed_result": "PASS",
        "proposed_result_caveat": "subject to local canonical Phase B; the "
                                  "branch remains IN_REVIEW and the ticket "
                                  "status stays READY/IN_REVIEW",
        "head_commit_at_generation": head,
        "base_commit": "a0116167e0351beb1eef804d83845890be7253c9",
        "canonical_state": {
            "goal_id": None,
            "campaign_id": None,
            "evaluation_id": None,
            "research_revision": None,
            "artifact_chain_hash": None,
            "wiki_files": None,
            "wiki_links_checked": None,
            "chain_fresh": None,
            "note": "host-owned canonical state is intentionally absent in the "
                    "cloud record; never fabricated",
            "canonical_db_recheck_required": True,
        },
        "dependency_gate": {
            "verdict": gate["verdict"],
            "s1_001_result": gate["dependencies"]["S1-001"]["result"],
            "s1_009_result": gate["dependencies"]["S1-009"]["result"],
            "s1_009_semantics": gate["dependencies"]["S1-009"]["semantics"],
            "scope": gate["gate_scope"],
        },
        "frozen_inputs": manifest["frozen_input_hashes"],
        "corpus": {
            "case_count": manifest["case_count"],
            "class_counts": manifest["class_counts"],
            "truth_counts": manifest["truth_counts"],
            "critical_count": manifest["critical_count"],
            "probes": {k: len(v) for k, v in manifest["probes"].items()},
            "cases_sha256": manifest["cases_sha256"],
        },
        "runs": {
            "comparison_verdict": comparison["verdict"],
            "identical": comparison["identical"],
            "process_separation_verified":
                comparison["process_separation_verified"],
            "commit_sha": comparison["commit_sha"],
            "tree_sha": comparison["tree_sha"],
            "run_a": {"executor_id": run_a["executor_id"],
                      "nonce": run_a["nonce"],
                      "pid": run_a["pid"],
                      "evaluator_pid": run_a["process_provenance"]["evaluator_pid"],
                      "output_root": run_a["output_root"],
                      "decisions_sha256": run_a["decisions_sha256"],
                      "verdict": run_a["decision_verdict"]},
            "run_b": {"executor_id": run_b["executor_id"],
                      "nonce": run_b["nonce"],
                      "pid": run_b["pid"],
                      "evaluator_pid": run_b["process_provenance"]["evaluator_pid"],
                      "output_root": run_b["output_root"],
                      "decisions_sha256": run_b["decisions_sha256"],
                      "verdict": run_b["decision_verdict"]},
        },
        "probes_all_pass": probes["all_probes_pass"],
        "source_snapshot_hashes": snapshot_hashes,
        "tracked_artifact_hashes": tracked,
        "limitations": [
            "Cloud gate proves tracked Git evidence only; no live canonical-DB "
            "consistency claim.",
            "Same-host process separation (verifier-A/verifier-B), not an "
            "external human auditor or independently implemented auditor.",
            "Deterministic stdlib detectors cover declared pattern families; "
            "unseen obfuscation relies on quarantine/human-review routing.",
            "The frozen 56-case corpus measures declared classes only; no "
            "production or universal-detection claim is licensed.",
            "Scanner disagreement and detector faults are deterministic "
            "declared faults exercising the aggregation path.",
        ],
        "phase_b_command": {
            "shell": "powershell",
            "commands": [
                "$env:PYTHONPATH = \"src\"",
                "py -3.12 -m agentos.cli research-plan --topic \"S1-010 tool "
                "poisoning detection evaluation\" --bundle "
                "\"research/tickets/stage-1/S1-010/bundle.json\" --db "
                "\".agentos-research/platform-stage-1\"",
                "py -3.12 -m agentos.cli wiki-check --db "
                "\".agentos-research/platform-stage-1\"",
            ],
        },
    }
    (TICKET_ROOT / "candidate-record.json").write_bytes(
        json.dumps(record, indent=1, sort_keys=True, ensure_ascii=False)
        .encode("utf-8") + b"\n")
    print(json.dumps({"status": record["status"],
                      "tracked_artifacts": len(tracked),
                      "snapshots": len(snapshot_hashes)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
