"""AgentOS S1-006 — bundle orchestration (FLOW-11 v1).

Pipeline (fail-closed, review culture):
  dependency gate -> fresh experiments (main) -> independent rerun
  (separate process, separate output directory) -> probes through the
  same simulation paths -> evaluator against both run manifests (nonce
  and digest bound) -> rerun comparison within frozen tolerance ->
  FLOW-11 bundle with the verdict DERIVED from the evaluator output.

Run from the repository root:
    py research/tickets/stage-1/S1-006/make_bundle.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TICKET = Path(__file__).resolve().parents[0]
RESULTS = TICKET / "results"

PRODUCER = "agentos-s1-006-producer"
AUDITOR = "agentos-s1-006-independent-verifier"

_LAST_RUN_NONCE = None


def sh(args: list, *, timeout: int = 3600, env: dict | None = None) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True,
                              timeout=timeout, cwd=str(ROOT), env=env)
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"command timed out after {timeout}s: "
                         f"{' '.join(args)}") from exc
    if proc.returncode != 0:
        raise SystemExit(
            f"command failed (exit {proc.returncode}): {' '.join(args)}\n"
            f"{proc.stdout}\n{proc.stderr}")
    return proc.stdout


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dependency_gate() -> dict:
    out = sh([sys.executable, str((TICKET / "dependency_gate.py").resolve())])
    return json.loads(out)


def run_experiments(mode: str, out_dir: Path) -> dict:
    if out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sh([sys.executable, str((TICKET / "runner.py").resolve()), "--mode", mode,
        "--out", str(out_dir)])
    return load(out_dir / "run-manifest.json")


def run_probes() -> dict:
    sh([sys.executable, str((TICKET / "runner.py").resolve()), "--mode", "probes",
        "--out", str(RESULTS)])
    return load(RESULTS / "probes.json")


def run_evaluator(runs_manifest: Path, *, expected_commit: str,
                  run_nonce: str) -> dict:
    """Production evaluator invocation with mandatory fresh-write
    semantics: the saved sensitivity output is removed first and the
    fresh file must carry this run's nonce (review R3 finding 2)."""
    sensitivity = RESULTS / "sensitivity-analysis.json"
    if sensitivity.exists():
        sensitivity.unlink()
    env = dict(os.environ, AGENTOS_RUN_NONCE=run_nonce)
    proc = subprocess.run(
        [sys.executable, str((TICKET / "evaluator.py").resolve()),
         "--runs-manifest", str(runs_manifest),
         "--runs-manifest-sha", sha_file(runs_manifest),
         "--expected-commit", expected_commit],
        capture_output=True, text=True, timeout=900, env=env, cwd=str(ROOT))
    if proc.returncode != 0:
        raise SystemExit(
            f"evaluator failed (exit {proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}")
    if not sensitivity.is_file():
        raise SystemExit(
            "evaluator did not produce a fresh sensitivity result; a stale "
            "saved verdict cannot be published")
    result = load(sensitivity)
    if result.get("schema") != "agentos.s1-006.evaluation/v1":
        raise SystemExit("evaluator output schema mismatch")
    if result.get("run_nonce") != run_nonce:
        raise SystemExit(
            "evaluator output nonce mismatch: the published verdict is not "
            "from this fresh run")
    return result


def verify_probes(evaluation: dict, probes: dict) -> dict:
    """Probes must be detected through the evaluator's own rules."""
    detected = evaluation.get("probe_rejections", {})
    required = {"A_unsafe_resume": "FAIL",
                "B_incomparable": "INCOMPARABLE/NO_DATA",
                "C_blind_retry": "FAIL"}
    out = {}
    runs = {p["probe"]: p for p in probes.get("probes", [])}
    for pid, expect in required.items():
        if detected.get(pid) != expect:
            raise SystemExit(
                f"probe {pid} not detected as {expect}: "
                f"{detected.get(pid)!r}")
        run = runs.get(pid)
        out[pid] = {"expected": expect,
                    "safety_counters": run["safety_counters"] if run else None,
                    "detected": True}
    return out


def compare_rerun(evaluation: dict, rerun: dict) -> dict:
    if rerun.get("verdict") != evaluation.get("verdict"):
        raise SystemExit("rerun safety verdict diverged from the main run")
    base_a = evaluation["sensitivity"]["base_scores"]
    base_b = rerun["sensitivity"]["base_scores"]
    deltas = {}
    for backend, sc in base_a.items():
        other = base_b.get(backend)
        delta = abs(sc - (other or 0))
        deltas[backend] = round(delta, 4)
        if delta > 2.0:
            raise SystemExit(
                f"rerun score delta beyond the frozen 2x tolerance for "
                f"{backend}: {delta}")
    return {"verdict_equal": True, "score_deltas": deltas,
            "rerun_nonce": rerun.get("run_nonce")}


def _main() -> None:
    gate = dependency_gate()
    print("[gate] both dependencies PROVEN")

    manifest_a = run_experiments("main", RESULTS / "run-a")
    print(f"[runner] main: {len(manifest_a['runs'])} runs, "
          f"commit {manifest_a['provenance']['commit'][:12]}, "
          f"dirty={manifest_a['provenance']['dirty']}")
    if manifest_a["provenance"]["dirty"]:
        raise SystemExit("experiments must run on a clean committed tree")
    if manifest_a["provenance"]["commit"] != _commit():
        raise SystemExit("recorded commit does not match the current HEAD")

    manifest_b = run_experiments("rerun", RESULTS / "run-b")
    print(f"[runner] rerun: {len(manifest_b['runs'])} runs in a separate "
          f"process and output directory")

    probes = run_probes()

    run_nonce = "s1-006-" + manifest_a["provenance"]["commit"][:12] + "-" + \
        hashlib.sha256(
            (str(sha_file(RESULTS / "run-a" / "run-manifest.json"))
             + str(sha_file(RESULTS / "run-b" / "run-manifest.json")))
            .encode()).hexdigest()[:12]
    evaluation = run_evaluator(
        RESULTS / "run-a" / "run-manifest.json",
        expected_commit=manifest_a["provenance"]["commit"],
        run_nonce=run_nonce)
    rerun = run_evaluator(
        RESULTS / "run-b" / "run-manifest.json",
        expected_commit=manifest_b["provenance"]["commit"],
        run_nonce=run_nonce + "-rerun")
    probe_evidence = verify_probes(evaluation, probes)
    rerun_comparison = compare_rerun(evaluation, rerun)

    (RESULTS / "rerun-comparison.json").write_text(
        json.dumps({"schema": "agentos.s1-006.rerun-comparison/v1",
                    **rerun_comparison}, indent=2) + "\n", encoding="utf-8")

    bundle = build_bundle(gate, evaluation, rerun_comparison,
                          probe_evidence, manifest_a["provenance"])
    out = TICKET / "bundle.json"
    out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"[bundle] written: {out}")
    print(f"[bundle] verdict: {bundle['audit']['verdict']}")


def _commit() -> str | None:
    out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                         text=True, timeout=30, cwd=str(ROOT))
    return out.stdout.strip() or None


def build_bundle(gate: dict, evaluation: dict, rerun_comparison: dict,
                 probe_evidence: dict, experiments_provenance: dict) -> dict:
    from bundle_content import build
    return build(gate, evaluation, rerun_comparison, probe_evidence,
                 experiments_provenance)


if __name__ == "__main__":
    _main()
