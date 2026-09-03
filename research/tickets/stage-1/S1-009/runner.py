#!/usr/bin/env python3
"""S1-009 process-separated deterministic evaluation runner.

The two measurements are deliberately top-level child-process invocations.
Each child captures git/input provenance before the evaluator writes anything;
the parent only materialises the saved evidence after both clean measurements
have completed.
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
from pathlib import Path
from typing import Any


TICKET_ROOT = Path(__file__).resolve().parent
# S1-009 -> stage-1 -> tickets -> research -> repo root
REPO_ROOT = TICKET_ROOT.parents[3]
REQUIRED_HASH_KEYS = {
    "evaluator_sha256",
    "adapter_contract_sha256",
    "corpus_sha256",
    "envelope_schema_sha256",
    "rubric_sha256",
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True,
        check=False, timeout=10,
    )
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        raise RuntimeError(
            f"git provenance failed ({' '.join(args)}): "
            f"{result.stderr.strip() or result.returncode}"
        )
    return value


def _manifest_for_corpus(corpus: str | Path) -> Path:
    path = Path(corpus).resolve().parent / "corpus-manifest.json"
    if not path.is_file():
        raise RuntimeError(f"frozen input manifest is missing: {path}")
    return path


def _gather_process_provenance(corpus: str | Path | None = None) -> dict[str, Any]:
    """Capture complete, fail-closed provenance for one runner invocation."""
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=10,
    )
    if status.returncode != 0:
        raise RuntimeError(f"git status failed: {status.stderr.strip() or status.returncode}")
    dirty_files = [line for line in status.stdout.splitlines() if line.strip()]
    manifest = _manifest_for_corpus(corpus) if corpus is not None else None
    return {
        "runner_pid": os.getpid(),
        "runner_ppid": os.getppid(),
        "runner_cwd": str(Path.cwd()),
        "commit_sha": _git_value("rev-parse", "HEAD"),
        "tree_sha": _git_value("rev-parse", "HEAD^{tree}"),
        "branch": _git_value("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(dirty_files),
        "clean": not dirty_files,
        "dirty_files": dirty_files[:50],
        "input_manifest_sha256": sha256_file(manifest) if manifest else "",
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
    }


def _invocation_digest(corpus: str, executor: str, nonce: str,
                       proc_prov: dict, output_root: str = "") -> str:
    """Bind identity, exact frozen inputs, and output namespace."""
    payload = {
        "corpus_path": str(Path(corpus).resolve()),
        "executor": executor,
        "nonce": nonce,
        "output_root": output_root,
        "runner_pid": proc_prov.get("runner_pid"),
        "runner_ppid": proc_prov.get("runner_ppid"),
        "commit_sha": proc_prov.get("commit_sha"),
        "tree_sha": proc_prov.get("tree_sha"),
        "dirty": proc_prov.get("dirty"),
        "input_manifest_sha256": proc_prov.get("input_manifest_sha256"),
    }
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def run_evaluator(corpus: str, out_dir: str, executor: str, nonce: str,
                  proc_prov: dict | None = None,
                  output_root: str = "") -> dict:
    """Run exactly one evaluator subprocess and return its summary."""
    if proc_prov is None:
        proc_prov = _gather_process_provenance(corpus)
    if proc_prov.get("dirty") or proc_prov.get("clean") is not True:
        raise RuntimeError("runner invocation is dirty; refusing evidence run")
    result = subprocess.run(
        [sys.executable, str(TICKET_ROOT / "evaluator.py"),
         "--corpus", str(Path(corpus).resolve()),
         "--out", str(Path(out_dir).resolve()),
         "--executor", executor,
         "--nonce", nonce],
        capture_output=True, text=True, check=False, cwd=str(REPO_ROOT),
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"evaluator process failed with {result.returncode}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    try:
        summary = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"evaluator produced invalid JSON: {result.stdout[-500:]}") from exc
    eval_prov = summary.get("process_provenance", {})
    for field in ("clean", "commit_sha", "tree_sha", "input_manifest_sha256"):
        if field not in eval_prov:
            raise RuntimeError(f"evaluator omitted process provenance: {field}")
    if eval_prov.get("clean") is not True:
        raise RuntimeError("evaluator process reports a dirty tree")
    for field in ("commit_sha", "tree_sha", "input_manifest_sha256"):
        if eval_prov.get(field) != proc_prov.get(field):
            raise RuntimeError(f"evaluator provenance changed during run: {field}")
    merged = dict(proc_prov)
    merged["evaluator_pid"] = eval_prov.get("evaluator_pid")
    merged["evaluator_ppid"] = eval_prov.get("evaluator_ppid")
    merged["evaluator_clean"] = eval_prov.get("clean")
    merged["evaluator_commit_sha"] = eval_prov.get("commit_sha")
    merged["evaluator_tree_sha"] = eval_prov.get("tree_sha")
    merged["evaluator_input_manifest_sha256"] = eval_prov.get("input_manifest_sha256")
    summary["process_provenance"] = merged
    summary["input_manifest_sha256"] = (
        summary.get("input_manifest_sha256") or merged.get("input_manifest_sha256")
    )
    summary["output_root"] = output_root or str(Path(out_dir).resolve())
    summary["invocation_digest"] = _invocation_digest(
        corpus, executor, nonce, merged, summary["output_root"]
    )
    return summary


def _load_results(run: dict) -> list[dict]:
    path = Path(run["results_path"])
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"results is not a list: {path}")
    return data


def _provenance_value(run: dict, key: str) -> Any:
    prov = run.get("process_provenance") or {}
    if key in run:
        return run.get(key)
    return prov.get(key)


def compare_runs(run_a: dict, run_b: dict) -> dict:
    """Compare exact cases and all evidence-chain provenance fields."""
    a_results = _load_results(run_a)
    b_results = _load_results(run_b)
    a_ids = [r.get("case_id") for r in a_results]
    b_ids = [r.get("case_id") for r in b_results]
    mismatches: list[dict[str, Any]] = []

    a_dups = sorted({cid for cid in a_ids if a_ids.count(cid) > 1})
    b_dups = sorted({cid for cid in b_ids if b_ids.count(cid) > 1})
    for cid in a_dups:
        mismatches.append({"case_id": cid, "type": "duplicate_in_a"})
    for cid in b_dups:
        mismatches.append({"case_id": cid, "type": "duplicate_in_b"})
    a_set, b_set = set(a_ids), set(b_ids)
    for cid in sorted(a_set - b_set):
        mismatches.append({"case_id": cid, "type": "missing_in_b"})
    for cid in sorted(b_set - a_set):
        mismatches.append({"case_id": cid, "type": "extra_in_b"})
    if len(a_results) != len(b_results):
        mismatches.append({"type": "result_count_mismatch",
                           "a_count": len(a_results), "b_count": len(b_results)})

    a_by_id: dict[str, dict] = {}
    b_by_id: dict[str, dict] = {}
    for row in a_results:
        a_by_id.setdefault(row.get("case_id"), row)
    for row in b_results:
        b_by_id.setdefault(row.get("case_id"), row)
    for cid in sorted(a_set & b_set):
        a, b = a_by_id[cid], b_by_id[cid]
        for field, mismatch_type in (
            ("decision_actual", "decision_mismatch"),
            ("verdict", "verdict_mismatch"),
            ("envel_hash", "envelope_hash_mismatch"),
            ("raw_input_digest", "raw_input_digest_mismatch"),
            ("output_digest", "output_digest_mismatch"),
        ):
            if field in a or field in b:
                if a.get(field) != b.get(field):
                    mismatches.append({"case_id": cid, "type": mismatch_type,
                                       "a": a.get(field), "b": b.get(field)})
        if ("canonical_envelope" in a or "canonical_envelope" in b) and \
                a.get("canonical_envelope") != b.get("canonical_envelope"):
            mismatches.append({"case_id": cid, "type": "envelope_mismatch"})

    a_hashes = run_a.get("hashes", {})
    b_hashes = run_b.get("hashes", {})
    hash_match = a_hashes == b_hashes
    if a_hashes or b_hashes:
        if set(a_hashes) != REQUIRED_HASH_KEYS or set(b_hashes) != REQUIRED_HASH_KEYS:
            mismatches.append({"type": "incomplete_frozen_hashes"})
        if not hash_match:
            mismatches.append({"type": "frozen_hash_mismatch"})

    a_prov = run_a.get("process_provenance") or {}
    b_prov = run_b.get("process_provenance") or {}
    provenance_complete = True
    if a_prov or b_prov:
        required_prov = ("runner_pid", "evaluator_pid", "commit_sha", "tree_sha",
                         "input_manifest_sha256", "evaluator_commit_sha",
                         "evaluator_tree_sha", "evaluator_input_manifest_sha256")
        for label, prov in (("a", a_prov), ("b", b_prov)):
            for field in required_prov:
                if not prov.get(field):
                    provenance_complete = False
                    mismatches.append({"type": "missing_provenance",
                                       "run": label, "field": field})
        for label, prov in (("a", a_prov), ("b", b_prov)):
            if prov.get("dirty") is True or prov.get("clean") is not True:
                mismatches.append({"type": "dirty_run", "run": label})
            if prov.get("evaluator_clean") is not True:
                mismatches.append({"type": "dirty_evaluator", "run": label})
        for field, mismatch_type in (
            ("commit_sha", "mixed_commit"),
            ("tree_sha", "mixed_tree"),
            ("input_manifest_sha256", "mixed_input_manifest"),
            ("evaluator_commit_sha", "mixed_evaluator_commit"),
            ("evaluator_tree_sha", "mixed_evaluator_tree"),
            ("evaluator_input_manifest_sha256", "mixed_evaluator_input_manifest"),
        ):
            av, bv = _provenance_value(run_a, field), _provenance_value(run_b, field)
            if av and bv and av != bv:
                mismatches.append({"type": mismatch_type, "a": av, "b": bv})
        if a_prov.get("dirty") or b_prov.get("dirty"):
            # A dirty worktree makes the HEAD tree an incomplete description of
            # the executed source, so it is also a mixed-tree failure.
            if not any(m.get("type") == "mixed_tree" for m in mismatches):
                mismatches.append({"type": "mixed_tree", "detail": "dirty tree is not frozen"})
        if a_prov.get("runner_pid") and a_prov.get("runner_pid") == b_prov.get("runner_pid"):
            mismatches.append({"type": "same_runner_pid"})
        if a_prov.get("evaluator_pid") and a_prov.get("evaluator_pid") == b_prov.get("evaluator_pid"):
            mismatches.append({"type": "same_evaluator_pid"})
    else:
        provenance_complete = False

    a_digest, b_digest = run_a.get("invocation_digest"), run_b.get("invocation_digest")
    if a_digest and b_digest and a_digest == b_digest:
        mismatches.append({"type": "same_invocation_digest"})
    a_root, b_root = run_a.get("output_root"), run_b.get("output_root")
    if a_root and b_root and a_root == b_root:
        mismatches.append({"type": "same_output_root"})

    exact_cases = (len(a_results) == len(b_results) and a_set == b_set and
                   not a_dups and not b_dups)
    separation = (
        provenance_complete and
        bool(a_prov.get("clean") is True and b_prov.get("clean") is True) and
        a_prov.get("runner_pid") != b_prov.get("runner_pid") and
        a_prov.get("evaluator_pid") != b_prov.get("evaluator_pid") and
        bool(a_digest and b_digest and a_digest != b_digest) and
        bool(a_root and b_root and a_root != b_root) and
        _provenance_value(run_a, "commit_sha") == _provenance_value(run_b, "commit_sha") and
        _provenance_value(run_a, "tree_sha") == _provenance_value(run_b, "tree_sha") and
        _provenance_value(run_a, "input_manifest_sha256") ==
        _provenance_value(run_b, "input_manifest_sha256") and
        _provenance_value(run_a, "evaluator_commit_sha") ==
        _provenance_value(run_b, "evaluator_commit_sha") and
        _provenance_value(run_a, "evaluator_tree_sha") ==
        _provenance_value(run_b, "evaluator_tree_sha") and
        _provenance_value(run_a, "evaluator_input_manifest_sha256") ==
        _provenance_value(run_b, "evaluator_input_manifest_sha256") and
        a_prov.get("evaluator_clean") is True and b_prov.get("evaluator_clean") is True
    )
    if not separation and (a_prov or b_prov):
        mismatches.append({"type": "process_separation_unverified"})
    comparison = {
        "schema": "agentos.s1-009.comparison/v2",
        "run_a_executor": run_a.get("executor_id"),
        "run_b_executor": run_b.get("executor_id"),
        "run_a_nonce": run_a.get("nonce"),
        "run_b_nonce": run_b.get("nonce"),
        "run_a_invocation_digest": a_digest,
        "run_b_invocation_digest": b_digest,
        "run_a_process_provenance": a_prov,
        "run_b_process_provenance": b_prov,
        "run_a_output_root": a_root,
        "run_b_output_root": b_root,
        "case_count": len(a_by_id),
        "exact_case_set": exact_cases,
        "process_separation_verified": separation,
        "hash_match": hash_match,
        "decision_identical": not any(m["type"] == "decision_mismatch" for m in mismatches),
        "verdict_identical": not any(m["type"] == "verdict_mismatch" for m in mismatches),
        "envelope_hash_identical": not any(m["type"] == "envelope_hash_mismatch" for m in mismatches),
        "duplicate_or_count_mismatch": not exact_cases,
        "mismatches": mismatches,
    }
    comparison["verdict"] = "PASS" if (
        hash_match and exact_cases and separation and not mismatches
    ) else "FAIL"
    return comparison


def _child_once(args: argparse.Namespace) -> int:
    provenance = _gather_process_provenance(args.corpus)
    if provenance["dirty"]:
        raise RuntimeError("child runner sees a dirty repository; refusing evidence run")
    summary = run_evaluator(
        args.corpus, args.out, args.executor, args.nonce, provenance,
        args.logical_output_root,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary.get("verdict") == "PASS" else 1


def _run_child(corpus: Path, out: Path, executor: str, nonce: str,
               logical_root: str) -> dict:
    command = [sys.executable, str(Path(__file__).resolve()), "--single",
               "--corpus", str(corpus), "--out", str(out),
               "--executor", executor, "--nonce", nonce,
               "--logical-output-root", logical_root]
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True,
                            text=True, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    try:
        summary = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"child runner produced invalid JSON: {result.stdout[-500:]}") from exc
    if summary.get("verdict") != "PASS":
        raise RuntimeError(f"{executor} evidence run failed: {summary.get('verdict')}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="S1-009 adversarial evaluation runner")
    parser.add_argument("--single", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--corpus", required=True, help="Path to cases.json")
    parser.add_argument("--out", help="Single-run output directory")
    parser.add_argument("--executor", help="Single-run executor identity")
    parser.add_argument("--nonce", help="Single-run nonce")
    parser.add_argument("--logical-output-root", default="", help=argparse.SUPPRESS)
    parser.add_argument("--workdir", help="Saved A/B output directory")
    args = parser.parse_args()
    if args.single:
        if not all((args.out, args.executor, args.nonce)):
            parser.error("--single requires --out, --executor, and --nonce")
        return _child_once(args)
    if not args.workdir:
        parser.error("top-level invocation requires --workdir")

    corpus = Path(args.corpus).resolve()
    workdir = Path(args.workdir).resolve()
    # Do not touch workdir before the child captures clean git provenance.
    with tempfile.TemporaryDirectory(prefix="s1-009-independent-") as temp:
        temp_root = Path(temp)
        summary_a = _run_child(corpus, temp_root / "run-a", "verifier-A",
                               "run-a-nonce", "results/run-a")
        summary_b = _run_child(corpus, temp_root / "run-b", "verifier-B",
                               "run-b-nonce", "results/run-b")

        for label, summary in (("run-a", summary_a), ("run-b", summary_b)):
            final_dir = workdir / label
            if final_dir.exists():
                shutil.rmtree(final_dir)
            final_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(temp_root / label / "results.json", final_dir / "results.json")
            summary["results_path"] = str((final_dir / "results.json").resolve())
            (final_dir / "summary.json").write_bytes(
                (json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
                .encode("utf-8")
            )
        comparison = compare_runs(summary_a, summary_b)
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "comparison.json").write_bytes(
            (json.dumps(comparison, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
            .encode("utf-8")
        )
    print(json.dumps({
        "verdict": comparison["verdict"],
        "hash_match": comparison["hash_match"],
        "process_separation_verified": comparison["process_separation_verified"],
        "mismatches": len(comparison["mismatches"]),
    }, indent=2, sort_keys=True))
    return 0 if comparison["verdict"] == "PASS" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"runner failed closed: {exc}", file=sys.stderr)
        sys.exit(2)
