#!/usr/bin/env python3
"""S1-010 process-separated evaluation runner (stdlib only, offline).

Default mode runs TWO independent evaluator child processes (Run A and Run B)
with distinct executor identities, nonces, PIDs, and output roots, on the same
clean Git commit and identical frozen inputs; it then compares them
fail-closed, recomputes metrics from raw records, extracts probe outcomes, and
writes results/comparison.json, results/metrics.json, results/probes.json, and
results/ENVIRONMENT.md.

Child outputs are produced in per-run temporary directories outside the
repository and transplanted byte-identically into results/run-{a,b}/, so child
provenance always observes a clean tree.

CLI:
  python runner.py                       # full Run A + Run B + comparison
  python runner.py --single --out DIR --executor ID --nonce N
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
from datetime import datetime, timezone
from pathlib import Path

TICKET_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TICKET_ROOT.parents[3]
RESULTS = TICKET_ROOT / "results"

IDENTITY_FIELDS = ("executor_id", "nonce", "output_root")
BINDING_FIELDS = ("commit_sha", "tree_sha", "evaluator_sha256", "runner_sha256",
                  "cases_sha256", "contract_sha256", "rubric_sha256",
                  "input_manifest_sha256", "decision_count", "decision_digest",
                  "reason_digest")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git_value(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(REPO_ROOT),
                            capture_output=True, text=True, check=False,
                            timeout=30)
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        raise RuntimeError(f"git provenance failed ({' '.join(args)}): "
                           f"{result.stderr.strip() or result.returncode}")
    return value


def gather_provenance() -> dict:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
        timeout=30)
    if status.returncode != 0:
        raise RuntimeError(f"git status failed: {status.stderr.strip()}")
    dirty = [line for line in status.stdout.splitlines() if line.strip()]
    return {
        "runner_pid": os.getpid(),
        "runner_ppid": os.getppid(),
        "commit_sha": _git_value("rev-parse", "HEAD"),
        "tree_sha": _git_value("rev-parse", "HEAD^{tree}"),
        "branch": _git_value("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(dirty),
        "clean": not dirty,
        "dirty_files": dirty[:50],
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
    }


def invocation_digest(corpus: str, executor: str, nonce: str,
                      provenance: dict, output_root: str) -> str:
    payload = {
        "corpus_path": str(Path(corpus).resolve()),
        "executor": executor,
        "nonce": nonce,
        "output_root": output_root,
        "runner_pid": provenance.get("runner_pid"),
        "commit_sha": provenance.get("commit_sha"),
        "tree_sha": provenance.get("tree_sha"),
        "dirty": provenance.get("dirty"),
        "input_manifest_sha256": provenance.get("input_manifest_sha256"),
    }
    return sha256_text(json.dumps(payload, sort_keys=True,
                                  separators=(",", ":")))


def run_single(corpus: Path, out_dir: Path, executor: str, nonce: str,
               provenance: dict) -> dict:
    """One evaluator child process; verify provenance binding fail-closed."""
    if provenance["dirty"] or provenance["clean"] is not True:
        raise RuntimeError("repository tree is dirty; refusing evidence run: "
                           + ", ".join(provenance["dirty_files"][:8]))
    child_out = Path(tempfile.mkdtemp(prefix=f"s1-010-child-{executor}-"))
    try:
        result = subprocess.run(
            [sys.executable, str(TICKET_ROOT / "evaluator.py"),
             "--corpus", str(corpus.resolve()),
             "--out", str(child_out),
             "--executor", executor,
             "--nonce", nonce,
             "--repo-root", str(REPO_ROOT)],
            capture_output=True, text=True, check=False, timeout=900,
            cwd=str(REPO_ROOT))
    finally:
        pass
    if result.returncode != 0:
        raise RuntimeError(
            f"evaluator process failed with {result.returncode}: "
            f"{result.stderr.strip() or result.stdout.strip()}")
    try:
        summary = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise RuntimeError("evaluator produced invalid JSON summary") from exc
    eval_prov = summary.get("process_provenance", {})
    for field in ("clean", "commit_sha", "tree_sha"):
        if field not in eval_prov:
            raise RuntimeError(f"evaluator omitted provenance field: {field}")
    if eval_prov.get("clean") is not True:
        raise RuntimeError("evaluator child reports a dirty tree")
    for field in ("commit_sha", "tree_sha"):
        if eval_prov.get(field) != provenance.get(field):
            raise RuntimeError(f"evaluator provenance mismatch on {field}")
    summary["process_provenance"] = {
        **provenance,
        "evaluator_pid": eval_prov.get("evaluator_pid"),
        "evaluator_ppid": eval_prov.get("evaluator_ppid"),
        "evaluator_clean": eval_prov.get("clean"),
        "child_output_root": str(child_out),
    }
    summary["executor_id"] = executor
    summary["nonce"] = nonce
    summary["pid"] = os.getpid()
    # transplant child outputs byte-identically into the requested out dir
    out_dir.mkdir(parents=True, exist_ok=True)
    copied = {}
    for name in ("evaluator-decisions.json", "evaluator-metrics.json",
                 "evaluator-summary.json"):
        src = child_out / name
        dst = out_dir / name
        shutil.copyfile(src, dst)
        if sha256_file(dst) != sha256_file(src):
            raise RuntimeError(f"output transplant mismatch for {name}")
        copied[name] = sha256_file(dst)
    summary["transplanted_outputs"] = copied
    decisions_path = out_dir / "evaluator-decisions.json"
    decisions_doc = json.loads(decisions_path.read_text(encoding="utf-8"))
    records = decisions_doc["decisions"]
    summary["decision_count"] = len(records)
    # hash of the decision content only (executor/nonce live at doc level)
    summary["decisions_sha256"] = sha256_text(json.dumps(
        records, sort_keys=True, separators=(",", ":")))
    summary["decision_digest"] = sha256_text(json.dumps(
        [(r["case_id"], r["decision"]) for r in records],
        sort_keys=True, separators=(",", ":")))
    summary["reason_digest"] = sha256_text(json.dumps(
        [(r["case_id"], r["reason_codes"]) for r in records],
        sort_keys=True, separators=(",", ":")))
    summary["decision_verdict"] = decisions_doc["hard_gates"]["verdict"]
    summary["output_root"] = str(out_dir)
    summary["invocation_digest"] = invocation_digest(
        str(corpus), executor, nonce, provenance, str(out_dir))
    shutil.rmtree(child_out, ignore_errors=True)
    (out_dir / "run-summary.json").write_bytes(
        json.dumps(summary, indent=1, sort_keys=True,
                   ensure_ascii=False).encode("utf-8") + b"\n")
    return summary


def compare_runs(run_a: dict, run_b: dict) -> dict:
    violations = []
    for field in BINDING_FIELDS:
        if run_a.get(field) != run_b.get(field):
            violations.append(f"binding mismatch: {field}")
    for field in IDENTITY_FIELDS:
        if run_a.get(field) == run_b.get(field):
            violations.append(f"identity collision: {field}")
    if run_a.get("pid") == run_b.get("pid"):
        violations.append("pid collision across runs")
    pid_a = run_a.get("process_provenance", {}).get("evaluator_pid")
    pid_b = run_b.get("process_provenance", {}).get("evaluator_pid")
    if pid_a is not None and pid_b is not None and pid_a == pid_b:
        violations.append("evaluator pid collision across runs")
    return {
        "identical": not violations,
        "violations": violations,
        "decision_digest_match": run_a.get("decision_digest") ==
                                 run_b.get("decision_digest"),
        "reason_digest_match": run_a.get("reason_digest") ==
                               run_b.get("reason_digest"),
        "run_a_executor": run_a.get("executor_id"),
        "run_b_executor": run_b.get("executor_id"),
        "run_a_nonce": run_a.get("nonce"),
        "run_b_nonce": run_b.get("nonce"),
        "run_a_output_root": run_a.get("output_root"),
        "run_b_output_root": run_b.get("output_root"),
        "run_a_pid": run_a.get("pid"),
        "run_b_pid": run_b.get("pid"),
        "run_a_evaluator_pid": pid_a,
        "run_b_evaluator_pid": pid_b,
        "commit_sha": run_a.get("commit_sha"),
        "tree_sha": run_a.get("tree_sha"),
        "process_separation_verified": not any("collision" in v for v in violations),
    }


def recompute_and_compare_metrics(run_a: dict, run_b: dict) -> dict:
    """Runner-side independent recomputation from raw records (no trust in
    producer metric summaries)."""
    sys.path.insert(0, str(TICKET_ROOT))
    try:
        import evaluator as ev
        rubric = ev.load_rubric()
        cases = json.loads((TICKET_ROOT / "cases.json").read_text("utf-8"))
        metrics_by_run = {}
        for label, summary in (("run_a", run_a), ("run_b", run_b)):
            decisions_doc = json.loads(
                Path(summary["output_root"], "evaluator-decisions.json")
                .read_text("utf-8"))
            recomputed = ev.grade(decisions_doc["decisions"], cases, rubric)
            producer = decisions_doc["metrics"]
            if json.dumps(recomputed, sort_keys=True) != \
                    json.dumps(producer, sort_keys=True):
                raise RuntimeError(
                    f"{label}: runner recomputation differs from producer metrics")
            gates = ev.evaluate_hard_gates(decisions_doc["decisions"],
                                           recomputed, rubric)
            metrics_by_run[label] = {"metrics": recomputed, "gates": gates,
                                     "decision_count": len(decisions_doc["decisions"])}
    finally:
        sys.path.pop(0)
    if json.dumps(metrics_by_run["run_a"]["metrics"], sort_keys=True) != \
            json.dumps(metrics_by_run["run_b"]["metrics"], sort_keys=True):
        raise RuntimeError("Run A and Run B metrics diverge")
    return metrics_by_run


def extract_probes(run_a: dict) -> dict:
    decisions_doc = json.loads(
        Path(run_a["output_root"], "evaluator-decisions.json").read_text("utf-8"))
    cases = {c["id"]: c for c in json.loads(
        (TICKET_ROOT / "cases.json").read_text("utf-8"))}
    by_id = {d["case_id"]: d for d in decisions_doc["decisions"]}
    probes = {}
    for letter, marker in (("A", "probe-A"), ("B", "probe-B"), ("C", "probe-C"),
                           ("D", "probe-D"), ("E", "probe-E"), ("F", "probe-F")):
        entries = []
        for cid, case in cases.items():
            if marker in case["subtype"]:
                d = by_id[cid]
                entries.append({
                    "case_id": cid,
                    "subtype": case["subtype"],
                    "decision": d["decision"],
                    "expected_decision": case["expected_decision"],
                    "reason_codes": d["reason_codes"],
                    "authority_mutations": d["authority_mutations"],
                    "blocked": d["decision"] in ("DENY", "QUARANTINE",
                                                 "HUMAN_REVIEW", "UNSUPPORTED"),
                    "pass": d["decision"] == case["expected_decision"],
                })
        probes[letter] = {
            "entries": entries,
            "all_pass": all(e["pass"] for e in entries),
            "all_blocked": all(e["blocked"] for e in entries),
        }
    return probes


def write_environment_md(provenance: dict, run_a: dict, run_b: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    lines = [
        "# S1-010 Run Environment",
        "",
        "## Host",
        f"- python: {provenance['python_version']}",
        f"- platform: {provenance['platform']}",
        f"- runner_pid: {provenance['runner_pid']}",
        "",
        "## Git provenance (identical for both runs)",
        f"- branch: {provenance['branch']}",
        f"- commit_sha: {provenance['commit_sha']}",
        f"- tree_sha: {provenance['tree_sha']}",
        f"- clean: {provenance['clean']}",
        "",
        "## Process separation",
        f"- run-a: executor={run_a['executor_id']} nonce={run_a['nonce']} "
        f"pid={run_a['pid']} evaluator_pid={run_a['process_provenance']['evaluator_pid']} "
        f"output_root={run_a['output_root']}",
        f"- run-b: executor={run_b['executor_id']} nonce={run_b['nonce']} "
        f"pid={run_b['pid']} evaluator_pid={run_b['process_provenance']['evaluator_pid']} "
        f"output_root={run_b['output_root']}",
        f"- invocation_digest_a: {run_a['invocation_digest']}",
        f"- invocation_digest_b: {run_b['invocation_digest']}",
        "",
        "Child outputs were produced in per-run temp directories outside the "
        "repository (so the child provenance observes a clean tree) and "
        "transplanted byte-identically into results/run-a and results/run-b.",
        "",
    ]
    (RESULTS / "ENVIRONMENT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--single", action="store_true")
    parser.add_argument("--out")
    parser.add_argument("--executor")
    parser.add_argument("--nonce")
    args = parser.parse_args()
    corpus = TICKET_ROOT / "cases.json"
    provenance = gather_provenance()
    provenance["input_manifest_sha256"] = sha256_file(
        TICKET_ROOT / "corpus-manifest.json")

    if args.single:
        if not all((args.out, args.executor, args.nonce)):
            parser.error("--single requires --out, --executor, and --nonce")
        summary = run_single(corpus, Path(args.out), args.executor,
                             args.nonce, provenance)
        print(json.dumps(summary, sort_keys=True))
        return 0 if summary["decision_verdict"] == "PASS" else 1

    RESULTS.mkdir(parents=True, exist_ok=True)
    run_a = run_single(corpus, RESULTS / "run-a", "verifier-A",
                       "s1-010-run-a-nonce", provenance)
    run_b = run_single(corpus, RESULTS / "run-b", "verifier-B",
                       "s1-010-run-b-nonce", provenance)
    comparison = compare_runs(run_a, run_b)
    if not comparison["identical"]:
        (RESULTS / "comparison.json").write_bytes(
            json.dumps(comparison, indent=1, sort_keys=True,
                       ensure_ascii=False).encode("utf-8") + b"\n")
        raise RuntimeError(f"run comparison failed: {comparison['violations']}")
    metrics_by_run = recompute_and_compare_metrics(run_a, run_b)
    comparison.update({
        "case_count": run_a["decision_count"],
        "exact_case_set": True,
        "decision_identical": True,
        "hash_match": True,
        "mismatches": [],
        "verdict": "PASS",
    })
    (RESULTS / "comparison.json").write_bytes(
        json.dumps(comparison, indent=1, sort_keys=True,
                   ensure_ascii=False).encode("utf-8") + b"\n")
    (RESULTS / "metrics.json").write_bytes(
        json.dumps(metrics_by_run, indent=1, sort_keys=True,
                   ensure_ascii=False).encode("utf-8") + b"\n")
    probes = extract_probes(run_a)
    probes_doc = {
        "schema": "agentos.s1-010.probes/v1",
        "probes": probes,
        "all_probes_pass": all(p["all_pass"] for p in probes.values()),
        "path": "production evaluator path (same as ordinary corpus cases)",
    }
    (RESULTS / "probes.json").write_bytes(
        json.dumps(probes_doc, indent=1, sort_keys=True,
                   ensure_ascii=False).encode("utf-8") + b"\n")
    write_environment_md(provenance, run_a, run_b)
    print(json.dumps({
        "verdict": metrics_by_run["run_a"]["gates"]["verdict"],
        "comparison": comparison["verdict"],
        "all_probes_pass": probes_doc["all_probes_pass"],
        "run_a_pid": run_a["pid"],
        "run_b_pid": run_b["pid"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail-closed
        print(f"runner failed: {exc}", file=sys.stderr)
        sys.exit(1)
