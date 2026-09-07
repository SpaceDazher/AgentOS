"""Run two process-separated S1-020 audits and compare them fail-closed."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
BASE_COMMIT = "78a4218606212c4f65642fe8dbf9c6a808209cfb"


def clean_tree() -> bool:
    proc = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                          cwd=ROOT, capture_output=True, text=True, check=True)
    return proc.stdout == ""


def _module(name: str):
    spec = importlib.util.spec_from_file_location(f"s1020_runner_{name}", HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run() -> dict:
    if not clean_tree():
        raise RuntimeError("runner requires a clean Git tree")
    execution_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                      capture_output=True, text=True, check=True).stdout.strip()
    temp = Path(tempfile.mkdtemp(prefix="agentos-s1-020-"))
    try:
        outputs = []
        for suffix, executor in (("a", "agentos-s1-020-auditor-A"),
                                 ("b", "agentos-s1-020-auditor-B")):
            path = temp / f"run-{suffix}.json"
            proc = subprocess.run([
                sys.executable, str(HERE / "evaluator.py"), "--executor-id", executor,
                "--nonce", f"s1-020-{suffix}-nonce", "--verified-commit", BASE_COMMIT,
                "--out", str(path),
            ], cwd=ROOT, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                raise RuntimeError(f"run-{suffix} failed: {proc.stdout}\n{proc.stderr}")
            outputs.append(json.loads(path.read_text(encoding="utf-8")))
        comparator = _module("comparator")
        comparison = comparator.compare(outputs[0], outputs[1], True)
        sensitivity = _module("sensitivity").run()
        if comparison["verdict"] != "PASS_WITH_LIMITS" or not sensitivity["all_stable"]:
            raise RuntimeError("comparison or sensitivity gate failed")
        results = HERE / "results"
        for suffix, output in zip(("a", "b"), outputs):
            target = results / f"run-{suffix}" / "observations.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(output, indent=2, sort_keys=True,
                                          ensure_ascii=False) + "\n", encoding="utf-8",
                              newline="\n")
        (results / "comparison.json").write_text(
            json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8",
            newline="\n")
        (results / "sensitivity.json").write_text(
            json.dumps(sensitivity, indent=2, sort_keys=True) + "\n", encoding="utf-8",
            newline="\n")
        summary = {"schema": "agentos.s1-020.run-summary/v1",
                   "verdict": comparison["verdict"], "verified_commit": BASE_COMMIT,
                   "execution_commit": execution_commit, "runs": 2, "cases_per_run": 60,
                   "observations": 120, "sensitivity_runs": sensitivity["runs"],
                   "process_separation_verified": comparison["process_separation_verified"],
                   "all_prior_dependencies": 19, "all_prior_probes": 19,
                   "goal_accepted": False, "production_certified": False}
        (results / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8",
            newline="\n")
        return summary
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    try:
        result = run()
    except Exception as exc:
        print(json.dumps({"verdict": "FAIL", "error": str(exc)}))
        raise SystemExit(2)
    print(json.dumps(result, sort_keys=True))
