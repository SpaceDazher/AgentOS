#!/usr/bin/env python3
"""Generate the S1-010 Phase A candidate record (READY_FOR_CANONICALIZATION).

Round 3 (post second independent review REVISE): the record is only
published when the ENTIRE evidence basis, recomputed from the CURRENT raw
inputs, passes AND the stored evidence artifacts agree with that
recomputation.  The generator:

- rebuilds the evidence basis with runner.recompute_and_verify_evidence:
  schema validation of both run summaries (null/malformed bindings are
  violations), staged digest re-verification, positive Git binding
  verification (objects, cross-layer agreement, blob/file matching),
  fail-closed A/B comparison recomputation, independent regrade of BOTH
  runs through the real evaluator, probe recomputation, exact case set;
- requires runner.crosscheck_stored_evidence: the saved comparison.json,
  metrics.json, and probes.json must agree with the recomputed basis —
  stale stored PASS flags can no longer publish a record (finding #1);
- requires dependency-gate PASS;
- otherwise exits non-zero WITHOUT writing a ready record.

The record contains NO canonical database IDs, no research revision, no
artifact-chain hash, and no chain_fresh claim: those are host-owned Phase B
state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_TICKET = Path(__file__).resolve().parent
DEFAULT_REPO = DEFAULT_TICKET.parents[3]

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


def load_module_by_path(name: str, path: Path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket-root", default=str(DEFAULT_TICKET))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    args = parser.parse_args()
    ticket = Path(args.ticket_root).resolve()
    repo_root = Path(args.repo_root).resolve()

    # --- evidence gate: no ready record is published on any failure ---
    manifest = load_json(ticket / "corpus-manifest.json")
    gate = load_json(ticket / "dependency-gate.json")

    # The generator's OWN code (same directory as this file) is executed;
    # only DATA is taken from --ticket-root, so sandboxed invocations can
    # never accidentally run a different code version.
    code_root = Path(__file__).resolve().parent
    runner_mod = load_module_by_path("s1_010_runner_record",
                                     code_root / "runner.py")
    # --- round 3 (finding #1): rebuild the whole evidence basis from the
    # CURRENT raw inputs and refuse any stored artifact that contradicts it.
    try:
        recomputed = runner_mod.recompute_and_verify_evidence(ticket,
                                                              repo_root)
        runner_mod.crosscheck_stored_evidence(ticket, recomputed)
    except runner_mod.RunnerError as exc:
        print(f"candidate record refused; {exc}", file=sys.stderr)
        return 1
    run_a = recomputed["run_a"]
    run_b = recomputed["run_b"]
    comparison = recomputed["comparison"]

    gate_failures = []
    if gate.get("verdict") != "PASS":
        gate_failures.append("dependency gate")
    if gate_failures:
        print("candidate record refused; failed evidence gates: "
              + ", ".join(gate_failures), file=sys.stderr)
        return 1

    snap_dir = ticket / "snapshots"
    snapshot_hashes = {
        f"research/tickets/stage-1/S1-010/snapshots/{p.name}": sha256_file(p)
        for p in sorted(snap_dir.glob("*")) if p.is_file()
    }
    tracked = {}
    for rel in TRACKED_FILES:
        path = ticket / rel
        if not path.is_file():
            raise RuntimeError(f"tracked artifact missing: {rel}")
        tracked[f"research/tickets/stage-1/S1-010/{rel}"] = sha256_file(path)
    tracked["tests/test_s1_010_regressions.py"] = sha256_file(
        repo_root / "tests/test_s1_010_regressions.py")

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_root),
                          capture_output=True, text=True, check=True).stdout.strip()

    record = {
        "schema": "agentos.s1-010.candidate-record/v1",
        "ticket": "S1-010",
        "phase": "A (cloud branch work; post-review round 3 fixes)",
        "status": "READY_FOR_CANONICALIZATION",
        "proposed_result": "PASS",
        "proposed_result_caveat": "subject to local canonical Phase B; the "
                                  "branch remains IN_REVIEW and the ticket "
                                  "status stays READY/IN_REVIEW",
        "evidence_gates_verified": {
            "run_summaries_schema_valid": True,
            "staged_digests_reverified": True,
            "git_bindings_verified": True,
            "stored_evidence_matches_recomputation": True,
            "independent_regrade_match": True,
            "comparison": comparison["verdict"],
            "process_separation_verified":
                comparison["process_separation_verified"],
            "probes_all_pass": recomputed["all_probes_pass"],
            "dependency_gate": gate["verdict"],
        },
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
                      "runner_pid": run_a["pid"],
                      "evaluator_pid":
                          run_a["process_provenance"]["evaluator_pid"],
                      "runner_sha256": run_a["runner_sha256"],
                      "evaluator_sha256": run_a["evaluator_sha256"],
                      "output_root": run_a["output_root"],
                      "decisions_sha256": run_a["decisions_sha256"],
                      "verdict": run_a["decision_verdict"]},
            "run_b": {"executor_id": run_b["executor_id"],
                      "nonce": run_b["nonce"],
                      "runner_pid": run_b["pid"],
                      "evaluator_pid":
                          run_b["process_provenance"]["evaluator_pid"],
                      "runner_sha256": run_b["runner_sha256"],
                      "evaluator_sha256": run_b["evaluator_sha256"],
                      "output_root": run_b["output_root"],
                      "decisions_sha256": run_b["decisions_sha256"],
                      "verdict": run_b["decision_verdict"]},
        },
        "probes_all_pass": recomputed["all_probes_pass"],
        "source_snapshot_hashes": snapshot_hashes,
        "tracked_artifact_hashes": tracked,
        "limitations": [
            "Cloud gate proves tracked Git evidence only; no live canonical-DB "
            "consistency claim.",
            "Same-host process separation (independent verifier-A/verifier-B "
            "runner processes with distinct evaluator children), not an "
            "external human auditor or independently implemented auditor.",
            "Deterministic stdlib detectors cover declared pattern families; "
            "unseen obfuscation relies on quarantine/human-review routing.",
            "The frozen 56-case corpus measures declared classes only; no "
            "production or universal-detection claim is licensed.",
            "Scanner disagreement and detector faults are deterministic "
            "declared faults exercising the aggregation path.",
            "pre_approved is a boolean entitlement in the evaluated model; "
            "exact-action+operation+expiry approval binding is declared by "
            "the contract but must be enforced by the production gateway.",
        ],
        "phase_b_command": {
            "shell": "powershell",
            "commands": [
                "cd <repo root>  # workspace root for verified local provenance",
                "$env:PYTHONPATH = \"src\"",
                "py -3.12 -m agentos.cli research-plan --topic \"S1-010 tool "
                "poisoning detection evaluation\" --bundle "
                "\"research/tickets/stage-1/S1-010/bundle.json\" --db "
                "\".agentos-research/platform-stage-1\"",
                "py -3.12 -m agentos.cli wiki-check --db "
                "\".agentos-research/platform-stage-1\"",
            ],
            "note": "run from the repository root so verifier_provenance "
                    "snapshot paths resolve; otherwise pass "
                    "--workspace-root <repo root>",
        },
    }
    (ticket / "candidate-record.json").write_bytes(
        json.dumps(record, indent=1, sort_keys=True, ensure_ascii=False)
        .encode("utf-8") + b"\n")
    print(json.dumps({"status": record["status"],
                      "tracked_artifacts": len(tracked),
                      "snapshots": len(snapshot_hashes),
                      "evidence_gates": "verified"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"make_candidate_record failed: {exc}", file=sys.stderr)
        sys.exit(1)
