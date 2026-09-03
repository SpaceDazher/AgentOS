#!/usr/bin/env python3
"""S1-010 process-separated evaluation runner (stdlib only, offline).

Architecture (post-review round 2):

- The default ORCHESTRATOR mode spawns TWO independent runner child
  processes (--run A and --run B).  Each child runner spawns its own
  evaluator grandchild.  Runs therefore differ in runner PID, evaluator PID,
  executor ID, nonce, and output root, on the same clean Git commit and
  identical frozen inputs.
- Each child runner stages its evaluator outputs byte-identically into its
  private --out directory (outside the repository) and writes a
  run-summary.json carrying the FULL binding set, including runner_sha256.
- The orchestrator transplants the staged outputs into results/run-{a,b},
  validates each run summary against a mandatory schema (missing fields are
  violations, not silent matches), verifies the claimed decision digests
  against the staged files, compares the runs fail-closed, recomputes
  metrics from raw records, extracts probe outcomes, and derives ONE final
  verdict from all mandatory gates.  FAIL/BLOCKED propagates to the exit
  code: the orchestrator returns 0 only when every gate passes.

CLI:
  python runner.py                                  # orchestrate A + B
  python runner.py --run A --out DIR --executor ID --nonce N
  python runner.py --single --out DIR --executor ID --nonce N   (legacy alias)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

TICKET_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TICKET_ROOT.parents[3]
RESULTS = TICKET_ROOT / "results"

IDENTITY_FIELDS = ("executor_id", "nonce", "output_root")
BINDING_FIELDS = ("commit_sha", "tree_sha", "evaluator_sha256", "runner_sha256",
                  "cases_sha256", "contract_sha256", "rubric_sha256",
                  "input_manifest_sha256", "decision_count", "decision_digest",
                  "reason_digest")
RUN_SUMMARY_SCHEMA = "agentos.s1-010.run-summary/v1"
DECISION_VALUES = ("ALLOW", "DENY", "QUARANTINE", "HUMAN_REVIEW", "UNSUPPORTED")
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_HEX40 = re.compile(r"\A[0-9a-f]{40}\Z")


class RunnerError(RuntimeError):
    """Raised on any runner violation (fail-closed)."""


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
        raise RunnerError(f"git provenance failed ({' '.join(args)}): "
                          f"{result.stderr.strip() or result.returncode}")
    return value


def gather_provenance() -> dict:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
        timeout=30)
    if status.returncode != 0:
        raise RunnerError(f"git status failed: {status.stderr.strip()}")
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


def _parse_child_summary(proc_text: str, child_out: Path) -> dict:
    try:
        return json.loads(proc_text.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise RunnerError(
            f"evaluator child produced invalid JSON summary "
            f"(out={child_out})") from exc


def run_child(corpus: Path, out_dir: Path, executor: str, nonce: str,
              label: str) -> tuple[dict, int]:
    """Child-runner mode: run one evaluator grandchild process into a
    private temp dir, stage outputs into out_dir, and return
    (run summary, exit code).  Exit code is 0 iff the decision verdict is
    PASS; a FAIL verdict is a valid measurement that still exits 1."""
    provenance = gather_provenance()
    provenance["input_manifest_sha256"] = sha256_file(
        TICKET_ROOT / "corpus-manifest.json")
    if provenance["dirty"] or provenance["clean"] is not True:
        raise RunnerError("repository tree is dirty; refusing evidence run: "
                          + ", ".join(provenance["dirty_files"][:8]))
    child_out = Path(tempfile.mkdtemp(prefix=f"s1-010-evaluator-{executor}-"))
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
        if result.returncode not in (0, 1):
            raise RunnerError(
                f"evaluator process crashed with {result.returncode}: "
                f"{result.stderr.strip() or result.stdout.strip()}")
        eval_summary = _parse_child_summary(result.stdout, child_out)
    except RunnerError:
        shutil.rmtree(child_out, ignore_errors=True)
        raise
    eval_prov = eval_summary.get("process_provenance", {})
    for field in ("clean", "commit_sha", "tree_sha", "evaluator_pid"):
        if field not in eval_prov:
            shutil.rmtree(child_out, ignore_errors=True)
            raise RunnerError(f"evaluator omitted provenance field: {field}")
    if eval_prov.get("clean") is not True:
        shutil.rmtree(child_out, ignore_errors=True)
        raise RunnerError("evaluator child reports a dirty tree")
    for field in ("commit_sha", "tree_sha"):
        if eval_prov.get(field) != provenance.get(field):
            shutil.rmtree(child_out, ignore_errors=True)
            raise RunnerError(f"evaluator provenance mismatch on {field}")
    try:
        decisions_doc = json.loads(
            (child_out / "evaluator-decisions.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        shutil.rmtree(child_out, ignore_errors=True)
        raise RunnerError("evaluator decisions file unreadable") from exc
    records = decisions_doc["decisions"]
    records_digest = sha256_text(json.dumps(
        records, sort_keys=True, separators=(",", ":")))

    # Stage evaluator outputs into out_dir with byte-identity verification.
    out_dir.mkdir(parents=True, exist_ok=True)
    copied = {}
    try:
        for name in ("evaluator-decisions.json", "evaluator-metrics.json",
                     "evaluator-summary.json"):
            shutil.copyfile(child_out / name, out_dir / name)
            digest = sha256_file(out_dir / name)
            if digest != sha256_file(child_out / name):
                raise RunnerError(f"output transplant mismatch for {name}")
            copied[name] = digest
    finally:
        shutil.rmtree(child_out, ignore_errors=True)

    summary = {
        "schema": RUN_SUMMARY_SCHEMA,
        "ticket": "S1-010",
        "run": label,
        # The run's process identity is THIS runner child process; the
        # evaluator grandchild identity is recorded separately.
        "pid": provenance["runner_pid"],
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "evaluator_sha256": eval_summary.get("evaluator_sha256"),
        "executor_id": executor,
        "nonce": nonce,
        "output_root": str(out_dir),
        "commit_sha": provenance["commit_sha"],
        "tree_sha": provenance["tree_sha"],
        "branch": provenance["branch"],
        "clean": provenance["clean"],
        "dirty": provenance["dirty"],
        "decision_count": len(records),
        "decisions_sha256": records_digest,
        "decision_digest": sha256_text(json.dumps(
            [(r["case_id"], r["decision"]) for r in records],
            sort_keys=True, separators=(",", ":"))),
        "reason_digest": sha256_text(json.dumps(
            [(r["case_id"], r["reason_codes"]) for r in records],
            sort_keys=True, separators=(",", ":"))),
        "decision_verdict": decisions_doc["hard_gates"]["verdict"],
        "cases_sha256": eval_summary.get("cases_sha256"),
        "contract_sha256": eval_summary.get("contract_sha256"),
        "rubric_sha256": eval_summary.get("rubric_sha256"),
        "input_manifest_sha256": provenance["input_manifest_sha256"],
        "transplanted_outputs": copied,
        "invocation_digest": invocation_digest(
            str(corpus), executor, nonce, provenance, str(out_dir)),
        "process_provenance": {
            **provenance,
            "evaluator_pid": eval_prov.get("evaluator_pid"),
            "evaluator_ppid": eval_prov.get("evaluator_ppid"),
            "evaluator_clean": eval_prov.get("clean"),
            "evaluator_snapshots_root": eval_summary.get("snapshots_root"),
        },
    }
    (out_dir / "run-summary.json").write_bytes(
        json.dumps(summary, indent=1, sort_keys=True,
                   ensure_ascii=False).encode("utf-8") + b"\n")
    violations = validate_run_summary(summary)
    if violations:
        raise RunnerError(f"run summary failed schema validation: {violations}")
    print(json.dumps(summary, sort_keys=True))
    return summary, 0 if summary["decision_verdict"] == "PASS" else 1


def validate_run_summary(summary: dict) -> list[str]:
    """Mandatory schema for run summaries.  Every binding must be PRESENT
    with the right type: equality of absent values is never a match."""
    violations: list[str] = []
    if not isinstance(summary, dict):
        return ["run summary is not an object"]
    if summary.get("schema") != RUN_SUMMARY_SCHEMA:
        violations.append("schema is not " + RUN_SUMMARY_SCHEMA)
    for field in BINDING_FIELDS:
        if field not in summary:
            violations.append(f"missing binding: {field}")
    for field, pattern in (("commit_sha", _HEX40), ("tree_sha", _HEX40),
                           ("evaluator_sha256", _HEX64),
                           ("runner_sha256", _HEX64),
                           ("cases_sha256", _HEX64),
                           ("contract_sha256", _HEX64),
                           ("rubric_sha256", _HEX64),
                           ("input_manifest_sha256", _HEX64),
                           ("decision_digest", _HEX64),
                           ("reason_digest", _HEX64),
                           ("decisions_sha256", _HEX64),
                           ("invocation_digest", _HEX64)):
        value = summary.get(field)
        if value is not None and (not isinstance(value, str)
                                  or not pattern.match(value)):
            violations.append(f"malformed digest binding: {field}")
    count = summary.get("decision_count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        violations.append("decision_count must be a positive integer")
    for field in IDENTITY_FIELDS:
        value = summary.get(field)
        if not isinstance(value, str) or not value:
            violations.append(f"missing identity: {field}")
    verdict = summary.get("decision_verdict")
    if verdict not in ("PASS", "FAIL"):
        violations.append("decision_verdict must be PASS or FAIL")
    if summary.get("clean") is not True or summary.get("dirty") is not False:
        violations.append("run provenance is not clean")
    prov = summary.get("process_provenance")
    if not isinstance(prov, dict):
        violations.append("missing process_provenance")
    else:
        for field in ("runner_pid", "evaluator_pid"):
            value = prov.get(field)
            if not isinstance(value, int) or isinstance(value, bool) \
                    or value <= 0:
                violations.append(f"process_provenance.{field} must be a "
                                  "positive integer")
        if prov.get("clean") is not True:
            violations.append("process_provenance.clean is not true")
    staged = summary.get("transplanted_outputs")
    if not isinstance(staged, dict) or not staged:
        violations.append("missing transplanted_outputs")
    else:
        for name, digest in staged.items():
            if not isinstance(digest, str) or not _HEX64.match(digest):
                violations.append(f"transplanted_outputs[{name}] not a sha256")
    return violations


def verify_staged_outputs(summary: dict, run_dir: Path) -> list[str]:
    """Bind the claimed digests to the actual staged files: the recorded
    transplanted_outputs and the raw decision content must match the files
    in run_dir.  Equality of absent values is not proof."""
    violations: list[str] = []
    staged = summary.get("transplanted_outputs") or {}
    for name, claimed in sorted(staged.items()):
        path = run_dir / name
        if not path.is_file():
            violations.append(f"staged file missing: {name}")
            continue
        actual = sha256_file(path)
        if actual != claimed:
            violations.append(
                f"staged file digest mismatch: {name} ({actual} != {claimed})")
    decisions_path = run_dir / "evaluator-decisions.json"
    if decisions_path.is_file():
        try:
            records = json.loads(decisions_path.read_text("utf-8"))["decisions"]
        except (OSError, json.JSONDecodeError, KeyError):
            violations.append("staged evaluator-decisions.json unreadable")
        else:
            actual = sha256_text(json.dumps(records, sort_keys=True,
                                            separators=(",", ":")))
            if summary.get("decisions_sha256") != actual:
                violations.append(
                    "decisions_sha256 does not bind the staged decisions file")
    else:
        violations.append("staged evaluator-decisions.json missing")
    return violations


def compare_runs(run_a: dict, run_b: dict) -> dict:
    """Fail-closed A/B comparison.  Missing or malformed fields are
    violations; only after full presence does equality become meaningful."""
    violations = []
    violations += [f"run A: {v}" for v in validate_run_summary(run_a)]
    violations += [f"run B: {v}" for v in validate_run_summary(run_b)]
    for field in BINDING_FIELDS:
        if field in run_a and field in run_b and run_a[field] != run_b[field]:
            violations.append(f"binding mismatch: {field}")
    for field in IDENTITY_FIELDS:
        if run_a.get(field) == run_b.get(field):
            violations.append(f"identity collision: {field}")
    pid_a = run_a.get("pid")
    pid_b = run_b.get("pid")
    if isinstance(pid_a, int) and pid_a == pid_b:
        violations.append("runner pid collision across runs")
    prov_a = run_a.get("process_provenance", {}) or {}
    prov_b = run_b.get("process_provenance", {}) or {}
    epid_a = prov_a.get("evaluator_pid")
    epid_b = prov_b.get("evaluator_pid")
    if isinstance(epid_a, int) and isinstance(epid_b, int) and epid_a == epid_b:
        violations.append("evaluator pid collision across runs")
    if not run_a.get("commit_sha") or not run_a.get("tree_sha"):
        violations.append("run A lacks commit/tree binding")
    if not run_b.get("commit_sha") or not run_b.get("tree_sha"):
        violations.append("run B lacks commit/tree binding")
    # Process separation must be POSITIVELY established: distinct runner
    # processes, distinct evaluator processes, and distinct identities.
    separation = (
        isinstance(pid_a, int) and isinstance(pid_b, int) and pid_a != pid_b
        and isinstance(epid_a, int) and isinstance(epid_b, int)
        and epid_a != epid_b
        and run_a.get("executor_id") not in (None, run_b.get("executor_id"))
        and run_a.get("nonce") not in (None, run_b.get("nonce"))
        and run_a.get("output_root") not in (None, run_b.get("output_root")))
    if not separation:
        violations.append("process separation not positively established")
    return {
        "identical": not violations,
        "violations": violations,
        "process_separation_verified": separation and not violations,
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
        "run_a_pid": pid_a,
        "run_b_pid": pid_b,
        "run_a_runner_pid": pid_a,
        "run_b_runner_pid": pid_b,
        "run_a_evaluator_pid": epid_a,
        "run_b_evaluator_pid": epid_b,
        "commit_sha": run_a.get("commit_sha"),
        "tree_sha": run_a.get("tree_sha"),
    }


def recompute_and_compare_metrics(run_a: dict, run_b: dict) -> dict:
    """Runner-side independent recomputation from raw records (no trust in
    producer metric summaries).  grade() validates records and corpus
    fail-closed before deriving anything."""
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
                raise RunnerError(
                    f"{label}: runner recomputation differs from producer metrics")
            gates = ev.evaluate_hard_gates(decisions_doc["decisions"],
                                           recomputed, rubric)
            metrics_by_run[label] = {"metrics": recomputed, "gates": gates,
                                     "decision_count": len(decisions_doc["decisions"])}
    finally:
        sys.path.pop(0)
    if json.dumps(metrics_by_run["run_a"]["metrics"], sort_keys=True) != \
            json.dumps(metrics_by_run["run_b"]["metrics"], sort_keys=True):
        raise RunnerError("Run A and Run B metrics diverge")
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
            "all_pass": bool(entries) and all(e["pass"] for e in entries),
            "all_blocked": bool(entries) and all(e["blocked"] for e in entries),
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
        f"- orchestrator_pid: {provenance['runner_pid']}",
        "",
        "## Git provenance (identical for both runs)",
        f"- branch: {provenance['branch']}",
        f"- commit_sha: {provenance['commit_sha']}",
        f"- tree_sha: {provenance['tree_sha']}",
        f"- clean: {provenance['clean']}",
        "",
        "## Process separation",
        f"- run-a: executor={run_a['executor_id']} nonce={run_a['nonce']} "
        f"runner_pid={run_a['pid']} "
        f"evaluator_pid={run_a['process_provenance']['evaluator_pid']} "
        f"output_root={run_a['output_root']}",
        f"- run-b: executor={run_b['executor_id']} nonce={run_b['nonce']} "
        f"runner_pid={run_b['pid']} "
        f"evaluator_pid={run_b['process_provenance']['evaluator_pid']} "
        f"output_root={run_b['output_root']}",
        f"- runner_sha256: {run_a['runner_sha256']}",
        f"- evaluator_sha256: {run_a['evaluator_sha256']}",
        f"- invocation_digest_a: {run_a['invocation_digest']}",
        f"- invocation_digest_b: {run_b['invocation_digest']}",
        "",
        "Each run executed as an independent runner child process (distinct "
        "runner PID), each spawning its own evaluator grandchild process "
        "(distinct evaluator PID), with distinct executor IDs, nonces, and "
        "output roots.  Child outputs were produced in per-run temp "
        "directories outside the repository (so every process observes a "
        "clean tree) and transplanted byte-identically into results/run-a "
        "and results/run-b.",
        "",
    ]
    (RESULTS / "ENVIRONMENT.md").write_text("\n".join(lines), encoding="utf-8")


def _transplant_staged(staged_dir: Path, results_dir: Path) -> None:
    """Copy the child runner's staged outputs into the repository results
    tree byte-identically."""
    results_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(staged_dir.iterdir()):
        if not src.is_file():
            continue
        dst = results_dir / src.name
        shutil.copyfile(src, dst)
        if sha256_file(dst) != sha256_file(src):
            raise RunnerError(f"transplant mismatch: {src.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", choices=("A", "B"),
                        help="child-runner mode for one labelled run")
    parser.add_argument("--single", action="store_true",
                        help="legacy alias for one unlabelled child run")
    parser.add_argument("--out")
    parser.add_argument("--executor")
    parser.add_argument("--nonce")
    args = parser.parse_args()
    corpus = TICKET_ROOT / "cases.json"

    if args.run or args.single:
        label = args.run or "single"
        if not all((args.out, args.executor, args.nonce)):
            parser.error("--run/--single require --out, --executor, --nonce")
        _, exit_code = run_child(corpus, Path(args.out).resolve(),
                                 args.executor, args.nonce, label)
        return exit_code

    provenance = gather_provenance()
    if provenance["dirty"] or provenance["clean"] is not True:
        raise RunnerError("repository tree is dirty; refusing evidence run: "
                          + ", ".join(provenance["dirty_files"][:8]))
    RESULTS.mkdir(parents=True, exist_ok=True)
    # Two independent RUNNER child processes; each spawns its own evaluator
    # grandchild.  Both children complete BEFORE anything is written into
    # the repository, so every process observes a clean tree.
    tmp_a = Path(tempfile.mkdtemp(prefix="s1-010-runner-a-"))
    tmp_b = Path(tempfile.mkdtemp(prefix="s1-010-runner-b-"))
    try:
        children = []
        for label, tmp, executor in (("A", tmp_a, "verifier-A"),
                                     ("B", tmp_b, "verifier-B")):
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()),
                 "--run", label, "--out", str(tmp),
                 "--executor", executor,
                 "--nonce", uuid.uuid4().hex],
                capture_output=True, text=True, check=False, timeout=1200,
                cwd=str(REPO_ROOT))
            children.append((label, proc))
        run_summaries = {}
        for label, proc, tmp in (("A", children[0][1], tmp_a),
                                 ("B", children[1][1], tmp_b)):
            if proc.returncode not in (0, 1):
                raise RunnerError(
                    f"runner child {label} crashed with "
                    f"{proc.returncode}: {proc.stderr.strip()[:400]}")
            summary_path = tmp / "run-summary.json"
            try:
                run_summaries[label] = json.loads(
                    summary_path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RunnerError(
                    f"runner child {label} produced no readable "
                    f"run-summary.json") from exc
    finally:
        pass
    run_a, run_b = run_summaries["A"], run_summaries["B"]
    _transplant_staged(tmp_a, RESULTS / "run-a")
    _transplant_staged(tmp_b, RESULTS / "run-b")
    shutil.rmtree(tmp_a, ignore_errors=True)
    shutil.rmtree(tmp_b, ignore_errors=True)

    comparison = compare_runs(run_a, run_b)
    # Bind claimed digests to the staged files inside the repository.
    staging_violations = (verify_staged_outputs(run_a, RESULTS / "run-a")
                          + verify_staged_outputs(run_b, RESULTS / "run-b"))
    comparison["violations"] += [f"staging: {v}" for v in staging_violations]
    comparison["identical"] = not comparison["violations"]
    comparison["process_separation_verified"] = \
        comparison["process_separation_verified"] and not staging_violations

    metrics_by_run = recompute_and_compare_metrics(run_a, run_b)
    cases = json.loads((TICKET_ROOT / "cases.json").read_text("utf-8"))
    decisions_a = json.loads(
        (RESULTS / "run-a" / "evaluator-decisions.json").read_text("utf-8"))
    decisions_b = json.loads(
        (RESULTS / "run-b" / "evaluator-decisions.json").read_text("utf-8"))
    exact_case_set = (
        {d["case_id"] for d in decisions_a["decisions"]} ==
        {c["id"] for c in cases}
        and len(decisions_a["decisions"]) == len(cases))
    gates_pass = (metrics_by_run["run_a"]["gates"]["verdict"] == "PASS"
                  and metrics_by_run["run_b"]["gates"]["verdict"] == "PASS")
    probes = extract_probes(run_a)
    probes_doc = {
        "schema": "agentos.s1-010.probes/v1",
        "probes": probes,
        "all_probes_pass": all(p["all_pass"] for p in probes.values()),
        "path": "production evaluator path (same as ordinary corpus cases)",
    }
    final_verdict = "PASS" if (
        comparison["identical"]
        and comparison["process_separation_verified"]
        and gates_pass
        and probes_doc["all_probes_pass"]
        and exact_case_set
    ) else "FAIL"
    comparison.update({
        "case_count": run_a["decision_count"],
        "exact_case_set": exact_case_set,
        "decision_identical": run_a["decision_digest"] == run_b["decision_digest"],
        "hash_match": run_a["decisions_sha256"] == run_b["decisions_sha256"],
        "mismatches": comparison["violations"],
        "run_a_verdict": run_a["decision_verdict"],
        "run_b_verdict": run_b["decision_verdict"],
        "gates_verdict": metrics_by_run["run_a"]["gates"]["verdict"],
        "all_probes_pass": probes_doc["all_probes_pass"],
        "verdict": final_verdict,
    })
    (RESULTS / "comparison.json").write_bytes(
        json.dumps(comparison, indent=1, sort_keys=True,
                   ensure_ascii=False).encode("utf-8") + b"\n")
    (RESULTS / "metrics.json").write_bytes(
        json.dumps(metrics_by_run, indent=1, sort_keys=True,
                   ensure_ascii=False).encode("utf-8") + b"\n")
    (RESULTS / "probes.json").write_bytes(
        json.dumps(probes_doc, indent=1, sort_keys=True,
                   ensure_ascii=False).encode("utf-8") + b"\n")
    write_environment_md(provenance, run_a, run_b)
    print(json.dumps({
        "verdict": metrics_by_run["run_a"]["gates"]["verdict"],
        "final_verdict": final_verdict,
        "comparison": comparison["verdict"],
        "all_probes_pass": probes_doc["all_probes_pass"],
        "run_a_runner_pid": run_a["pid"],
        "run_b_runner_pid": run_b["pid"],
        "run_a_evaluator_pid": run_a["process_provenance"]["evaluator_pid"],
        "run_b_evaluator_pid": run_b["process_provenance"]["evaluator_pid"],
    }, sort_keys=True))
    return 0 if final_verdict == "PASS" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail-closed
        print(f"runner failed: {exc}", file=sys.stderr)
        sys.exit(1)
