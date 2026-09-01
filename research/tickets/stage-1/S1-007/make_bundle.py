"""AgentOS S1-007 — bundle orchestration (FLOW-11 v1).

Pipeline (fail-closed, review culture):
  dependency gate (S1-003, S1-005) -> fresh main matrix (producer,
  separate subprocess) -> independent rerun (separate executor identity,
  separate process, separate output directory) -> adversarial probes
  through the same runner paths -> evaluator over BOTH manifests (nonce
  and digest bound; independent ISO derivation) -> probe detection check
  -> FLOW-11 bundle with the verdict DERIVED from the evaluator output.

Run from the repository root:
    py research/tickets/stage-1/S1-007/make_bundle.py
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

PRODUCER = "agentos-s1-007-producer"
AUDITOR = "agentos-s1-007-independent-verifier"


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


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dependency_gate() -> dict:
    out = sh([sys.executable, str((TICKET / "dependency_gate.py").resolve())])
    return json.loads(out)


def run_matrix(mode: str, out_dir: Path, executor_id: str) -> dict:
    if out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, AGENTOS_EXECUTOR_ID=executor_id)
    sh([sys.executable, str((TICKET / "runner.py").resolve()), "--mode", mode,
        "--out", str(out_dir)], env=env)
    return load(out_dir / "run-manifest.json")


def _read_raw(path: Path) -> str:
    """Read file content WITHOUT newline translation so archive members
    stay byte-identical to the on-disk artifacts that the run manifests
    digest."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def build_raw_archive(manifest_a: dict, manifest_b: dict) -> dict:
    """Finding 1 correction: preserve the EXACT raw observations in a
    tracked, content-addressed archive so a clean-clone auditor can
    re-verify every run digest and recompute every derived statistic.
    Members are byte-copies of the on-disk run records plus both timing
    artifacts; the archive name carries its own sha256."""
    members = {}
    for which in ("run-a", "run-b"):
        base = RESULTS / which
        members[f"{which}/run-manifest.json"] = _read_raw(
            base / "run-manifest.json")
        members[f"{which}/timing.json"] = _read_raw(base / "timing.json")
        for run_file in sorted((base / "run_records").glob("*.json")):
            members[f"{which}/run_records/{run_file.name}"] = \
                _read_raw(run_file)
    archive = {
        "schema": "agentos.s1-007.raw-observations/v1",
        "note": "byte-exact copies of the executed run records and timing "
                "artifacts for both executors; sha256 of this archive file "
                "is recorded in evaluation-record.json and re-verified by "
                "the clean-clone probe",
        "member_count": len(members),
        "member_sha256": {name: _sha_text(v)
                          for name, v in sorted(members.items())},
        "members": members,
    }
    raw = json.dumps(archive, indent=2, sort_keys=True,
                     ensure_ascii=False).encode("utf-8") + b"\n"
    digest = hashlib.sha256(raw).hexdigest()
    evidence_dir = RESULTS / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / f"raw-observations-{digest}.json").write_bytes(raw)
    return {"sha256": digest, "member_count": len(members),
            "path": f"research/tickets/stage-1/S1-007/results/evidence/"
                    f"raw-observations-{digest}.json"}


def run_probes() -> dict:
    env = dict(os.environ, AGENTOS_EXECUTOR_ID=PRODUCER)
    sh([sys.executable, str((TICKET / "runner.py").resolve()), "--mode",
        "probes", "--out", str(RESULTS)], env=env)
    return load(RESULTS / "probes.json")


def run_evaluator(manifest_a: Path, manifest_b: Path, *,
                  expected_commit: str, run_nonce: str, out_path: Path,
                  probes_path: Path, probes_sha: str) -> dict:
    """Fresh-write semantics: the saved evaluation output is removed first
    and the fresh file must carry this invocation's nonce."""
    if out_path.exists():
        out_path.unlink()
    env = dict(os.environ, AGENTOS_RUN_NONCE=run_nonce)
    proc = subprocess.run(
        [sys.executable, str((TICKET / "evaluator.py").resolve()),
         "--runs-manifest", str(manifest_a),
         "--rerun-manifest", str(manifest_b),
         "--expected-commit", expected_commit,
         "--probes-path", str(probes_path),
         "--probes-sha", probes_sha,
         "--out", str(out_path)],
        capture_output=True, text=True, timeout=1800, env=env, cwd=str(ROOT))
    if proc.returncode != 0:
        raise SystemExit(
            f"evaluator failed (exit {proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}")
    if not out_path.is_file():
        raise SystemExit(
            "evaluator did not produce a fresh evaluation; a stale saved "
            "verdict cannot be published")
    result = load(out_path)
    if result.get("schema") != "agentos.s1-007.evaluation/v1":
        raise SystemExit("evaluator output schema mismatch")
    if result.get("run_nonce") != run_nonce:
        raise SystemExit(
            "evaluator output nonce mismatch: the published verdict is not "
            "from this fresh run")
    return result


def verify_probes(evaluation: dict, probes: dict) -> dict:
    """Probes must be detected through the evaluator's own ISO rules."""
    detected = evaluation.get("probe_rejections", {})
    required = {"A_existence_oracle": "FAIL",
                "B_stale_cache": "FAIL",
                "C_postfilter": "FAIL",
                "D_forged_scope_provenance_loss": "FAIL+INCOMPARABLE"}
    out = {}
    runs = {p["probe"]: p for p in probes.get("probes", [])}
    for pid, expect in required.items():
        got = detected.get(pid, {}).get("detected")
        if got != expect:
            raise SystemExit(
                f"probe {pid} not detected as {expect}: {got!r}")
        run = runs.get(pid)
        out[pid] = {"expected": expect, "detected": got,
                    "runs": len(run["runs"]) if run else 0,
                    "iso": detected.get(pid, {}).get("iso")}
    return out


def derive_result_files(evaluation: dict) -> None:
    """Write the required per-topic result files as deterministic
    projections of the single evaluator output."""
    (RESULTS / "decision-matrix.json").write_text(
        json.dumps({
            "schema": "agentos.s1-007.decision-matrix/v1",
            "winner": evaluation["winner"],
            "scores_normalized": evaluation["scores_normalized"],
            "score_margin": evaluation["score_margin"],
            "near_tie": evaluation["near_tie"],
            "scores_per_dimension": evaluation["scores_per_dimension"],
            "decision_matrix": evaluation["decision_matrix"],
            "fault_injection": evaluation["fault_injection"],
            "sensitivity": {
                "base_scores": evaluation["sensitivity"]["base_scores"],
                "flip_count": evaluation["sensitivity"]["flip_count"],
                "winner_stable": evaluation["sensitivity"]["winner_stable"],
                "flips": evaluation["sensitivity"]["flips"][:50]},
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (RESULTS / "isolation-cases.json").write_text(
        json.dumps({
            "schema": "agentos.s1-007.isolation-cases/v1",
            "iso_counters_main": evaluation["iso_counters_main"],
            "iso_counters_rerun": evaluation["iso_counters_rerun"],
            "cases": evaluation["isolation_cases"],
            "metrics": evaluation["metrics"],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (RESULTS / "timing-analysis.json").write_text(
        json.dumps({
            "schema": "agentos.s1-007.timing-analysis/v1",
            **evaluation["timing_analysis"]}, indent=2, sort_keys=True) +
        "\n", encoding="utf-8")
    (RESULTS / "sensitivity-analysis.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


def write_environment(manifest_a: dict, manifest_b: dict,
                      evaluation: dict) -> None:
    prov = manifest_a["provenance"]
    lines = [
        "# S1-007 — execution environment",
        "",
        "- Main executor: `" + prov["executor_id"] + "`",
        "- Rerun executor: `" + manifest_b["provenance"]["executor_id"] +
        "` (separate subprocess and output directory)",
        "- Python: " + prov["python"],
        "- Platform: " + prov["platform"],
        "- Commit: " + prov["commit"],
        "- Tree SHA: " + prov["tree_sha"],
        "- Dirty tree: " + str(prov["dirty"]),
        "- Environment hash (main): " + prov["environment_hash"],
        "- Environment hash (rerun): " +
        manifest_b["provenance"]["environment_hash"],
        "",
        "## Frozen input hashes (SHA-256)",
        "",
    ]
    for name, digest in sorted(manifest_a["contract_hashes"].items()):
        lines.append(f"- {name}: {digest}")
    lines += ["", "## Executed script hashes (SHA-256)", ""]
    for name, digest in sorted(prov["script_hashes"].items()):
        lines.append(f"- {name}: {digest}")
    lines += [
        "",
        "## Commands",
        "",
        "```",
        "py research/tickets/stage-1/S1-007/dependency_gate.py",
        "AGENTOS_EXECUTOR_ID=" + prov["executor_id"] +
        " py research/tickets/stage-1/S1-007/runner.py --mode main --out "
        "results/run-a   # exit 0",
        "AGENTOS_EXECUTOR_ID=" + manifest_b["provenance"]["executor_id"] +
        " py research/tickets/stage-1/S1-007/runner.py --mode rerun --out "
        "results/run-b   # exit 0",
        "py research/tickets/stage-1/S1-007/runner.py --mode probes --out "
        "results   # exit 0",
        "AGENTOS_RUN_NONCE=" + evaluation["run_nonce"] +
        " py research/tickets/stage-1/S1-007/evaluator.py ...   # exit 0",
        "py research/tickets/stage-1/S1-007/make_bundle.py   # orchestrates "
        "the above with exact-argument invocations",
        "```",
        "",
        "## Timing note",
        "",
        "The timing probe is a bounded same-host wall-clock measurement "
        "(perf_counter_ns) of a microsecond-scale in-process path; "
        "cross-executor medians vary with OS scheduling. Timing never "
        "gates the safety verdict and is never a production SLO.",
        "",
    ]
    (RESULTS / "ENVIRONMENT.md").write_text("\n".join(lines),
                                            encoding="utf-8")


def _commit() -> str:
    out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                         text=True, timeout=30, cwd=str(ROOT))
    if out.returncode != 0:
        raise SystemExit(
            f"git rev-parse HEAD failed ({out.returncode}): {out.stderr}")
    commit = out.stdout.strip()
    if len(commit) != 40:
        raise SystemExit("git rev-parse HEAD returned malformed commit")
    return commit


def main() -> None:
    gate = dependency_gate()
    print("[gate] S1-003 and S1-005 PROVEN")

    manifest_a = run_matrix("main", RESULTS / "run-a", PRODUCER)
    print(f"[runner] main: {len(manifest_a['runs'])} runs, "
          f"commit {manifest_a['provenance']['commit'][:12]}, "
          f"dirty={manifest_a['provenance']['dirty']}")
    if manifest_a["provenance"]["dirty"]:
        raise SystemExit("experiments must run on a clean committed tree")
    if manifest_a["provenance"]["commit"] != _commit():
        raise SystemExit("recorded commit does not match the current HEAD")

    manifest_b = run_matrix("rerun", RESULTS / "run-b", AUDITOR)
    print(f"[runner] rerun: {len(manifest_b['runs'])} runs in a separate "
          f"process, output directory and executor identity")
    if manifest_b["provenance"]["dirty"]:
        raise SystemExit("rerun experiments must run on a clean tree")
    if manifest_b["provenance"]["commit"] != \
            manifest_a["provenance"]["commit"]:
        raise SystemExit("main/rerun commits diverge")
    if manifest_b["provenance"]["executor_id"] == \
            manifest_a["provenance"]["executor_id"]:
        raise SystemExit("main/rerun executor identities must differ")

    probes = run_probes()
    probes_sha = sha_file(RESULTS / "probes.json")

    run_nonce = "s1-007-" + manifest_a["provenance"]["commit"][:12] + "-" + \
        hashlib.sha256(
            (sha_file(RESULTS / "run-a" / "run-manifest.json") +
             sha_file(RESULTS / "run-b" / "run-manifest.json")).encode()
        ).hexdigest()[:12]
    evaluation = run_evaluator(
        RESULTS / "run-a" / "run-manifest.json",
        RESULTS / "run-b" / "run-manifest.json",
        expected_commit=manifest_a["provenance"]["commit"],
        run_nonce=run_nonce,
        out_path=RESULTS / "sensitivity-analysis.json",
        probes_path=RESULTS / "probes.json",
        probes_sha=probes_sha)
    print(f"[evaluator] verdict={evaluation['verdict']} "
          f"winner={evaluation['winner']} "
          f"scores={evaluation['scores_normalized']}")

    probe_evidence = verify_probes(evaluation, probes)
    derive_result_files(evaluation)
    write_environment(manifest_a, manifest_b, evaluation)
    raw_archive = build_raw_archive(manifest_a, manifest_b)
    print(f"[archive] raw observations: {raw_archive['member_count']} "
          f"members, sha256 {raw_archive['sha256'][:16]}...")

    from bundle_content import build
    bundle = build(gate, evaluation, probe_evidence,
                   manifest_a["provenance"], raw_archive)
    out = TICKET / "bundle.json"
    out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"[bundle] written: {out}")
    print(f"[bundle] verdict: {bundle['audit']['verdict']}")


if __name__ == "__main__":
    main()
