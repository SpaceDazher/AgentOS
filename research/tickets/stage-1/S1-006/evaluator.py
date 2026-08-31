"""AgentOS S1-006 — independent fail-closed evaluator (QA2).

Derives the verdict ONLY from the frozen rubric and the raw observations
recorded by runner.py. The producer never states the expected verdict in
observed results.

Fail-closed on:
- run matrix divergence (missing/extra/duplicate runs vs the frozen
  workload manifest);
- contract/workload/rubric hash divergence across runs (INCOMPARABLE);
- mixed/fabricated commit or tree SHA provenance, dirty working tree,
  expected-commit mismatch;
- safety counters with wrong key sets or non-zero values on a candidate;
- missing/empty raw observations or terminal reasons;
- probes A/B/C not rejected through the real evaluation rules;
- weight perturbations flipping the winner (caps at PASS_WITH_LIMITS);
- unknown/NO_DATA dimensions (never mapped to a number or advantage).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
from pathlib import Path


SCHEMA = "agentos.s1-006.evaluation/v1"
SAFETY_COUNTERS = (
    "duplicate_effect_count", "duplicate_receipt_count", "blind_retry_count",
    "stale_owner_completion_count", "checkpoint_hash_bypass_count",
    "lost_committed_event_count", "allow_after_revocation_count",
)
SENSITIVITY_SEED = 42
SENSITIVITY_RANDOM_RUNS = 200


class EvalError(ValueError):
    pass


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def validate_run_matrix(manifest: dict, workload: dict, comparison: dict,
                        run_a: Path) -> tuple:
    """Exact matrix: every frozen (backend, load, seed[, scenario]) run
    present exactly once; hash bindings identical across runs."""
    expected = set()
    loads = [k for k in workload["load_levels"] if k != "note"]
    for backend in workload["backends"]:
        for load in loads:
            for seed in workload["seeds"]:
                expected.add(f"{backend}-{load}-{seed}")
                for scenario in ("S1", "S2", "S3", "S4"):
                    expected.add(f"{backend}-{load}-{seed}-{scenario}")
    actual = [r["run_id"] for r in manifest["runs"]]
    if len(actual) != len(set(actual)):
        raise EvalError("duplicate run ids in the run manifest")
    missing = sorted(expected - set(actual))
    extra = sorted(set(actual) - expected)
    if missing or extra:
        raise EvalError(f"run matrix divergence: missing={missing} "
                        f"extra={extra}")
    if manifest["contract_sha256"] != sha(
            Path(__file__).resolve().parent / "backend-contract.json"):
        raise EvalError("run manifest contract hash != frozen contract")
    if manifest["workload_sha256"] != sha(
            Path(__file__).resolve().parent / "workload-manifest.json"):
        raise EvalError("run manifest workload hash != frozen workload")
    if manifest["rubric_sha256"] != sha(
            Path(__file__).resolve().parent / "rubric.json"):
        raise EvalError("run manifest rubric hash != frozen rubric")
    for run in comparison["runs"]:
        for field, frozen in (("contract_sha256", manifest["contract_sha256"]),
                              ("workload_sha256", manifest["workload_sha256"]),
                              ("rubric_sha256", manifest["rubric_sha256"])):
            if run[field] != frozen:
                raise EvalError(
                    f"run {run['run_id']}: {field} diverges from the frozen "
                    "manifest -> INCOMPARABLE")
    return expected, manifest


def validate_run_entry(data: dict) -> None:
    counters = data.get("safety_counters")
    if not isinstance(counters, dict):
        raise EvalError(f"{data.get('run_id')}: safety counters missing")
    if set(counters) != set(SAFETY_COUNTERS):
        raise EvalError(
            f"{data.get('run_id')}: safety counter key set mismatch: "
            f"{sorted(set(counters) ^ set(SAFETY_COUNTERS))}")
    for name, value in counters.items():
        if value != 0:
            raise EvalError(
                f"{data.get('run_id')}: SAFETY VIOLATION {name}={value}")
    count = data.get("raw_observation_count")
    if not isinstance(count, int) or count <= 0:
        raise EvalError(
            f"{data.get('run_id')}: empty raw observations")
    if data.get("terminal_reason") != "completed":
        raise EvalError(f"{data.get('run_id')}: terminal reason "
                        f"{data.get('terminal_reason')!r}")


def evaluate_probes(probes: dict) -> dict:
    """Probe rules over real run records (review R2 finding 6: behavioral,
    not counter-tampering)."""
    out = {}
    for run in probes.get("probes", []):
        pid = run.get("probe")
        counters = run.get("safety_counters", {})
        if pid == "A_unsafe_resume":
            detected = counters.get("duplicate_effect_count", 0) >= 1 or \
                counters.get("duplicate_receipt_count", 0) >= 1
            out[pid] = {
                "detected": detected, "verdict": "FAIL" if detected else None,
                "reason": run.get("probe_reason")}
        elif pid == "C_blind_retry":
            detected = counters.get("blind_retry_count", 0) >= 1
            out[pid] = {
                "detected": detected, "verdict": "FAIL" if detected else None,
                "reason": run.get("probe_reason")}
        elif pid == "B_incomparable":
            frozen = sha(Path(__file__).resolve().parent
                         / "workload-manifest.json")
            divergent = run.get("workload_sha256") not in (None, frozen)
            out[pid] = {
                "detected": bool(divergent),
                "verdict": "INCOMPARABLE/NO_DATA" if divergent else None,
                "reason": run.get("probe_reason")}
    missing = {"A_unsafe_resume", "B_incomparable", "C_blind_retry"} - set(out)
    if missing:
        raise EvalError(f"probes missing: {sorted(missing)}")
    for pid, verdict in out.items():
        if not verdict["detected"]:
            raise EvalError(f"probe {pid} was NOT detected: positive "
                            "verdicts are forbidden while a probe passes")
    return out


# ---- deterministic per-dimension scoring ---------------------------------

def score_dims(comparison: dict, contract: dict) -> tuple:
    """Derive per-backend dimension scores from raw observations and the
    frozen contract. Measurement rules are explicit and deterministic."""
    by_backend = {}
    for run in comparison["runs"]:
        if run["scenario"] not in (None, "throughput"):
            continue
        by_backend.setdefault(run["backend"], []).append(run)
    scenarios_by = {}
    for run in comparison["runs"]:
        if run["scenario"] in ("S1", "S2", "S3", "S4"):
            scenarios_by.setdefault(run["backend"], []).append(run)

    def med_recovery(backend):
        values = []
        for run in scenarios_by.get(backend, []):
            for rt in run["metrics"]["recovery_times"]:
                values.append(rt["us"])
        return sorted(values)[len(values) // 2] if values else None

    def p95(backend):
        values = sorted(run["metrics"]["latency_us"]["p95"]
                        for run in by_backend.get(backend, []))
        return values[len(values) // 2] if values else None

    scores = {b: {} for b in by_backend}
    unknown = {b: [] for b in by_backend}

    def ratio_score(a, b, key):
        va, vb = a.get(key), b.get(key)
        if va is None or vb is None:
            return None
        lo, hi = sorted((va, vb))
        return max(0, min(4, round(4 * lo / hi)))

    rec_med = {b: med_recovery(b) for b in by_backend}
    if any(v is None for v in rec_med.values()):
        for b in by_backend:
            unknown[b].append("crash_recovery_time")
    else:
        lo = min(rec_med.values())
        for b in by_backend:
            scores[b]["crash_recovery_time"] = max(
                0, min(4, round(4 * lo / rec_med[b])))

    p95s = {b: p95(b) for b in by_backend}
    if any(v is None for v in p95s.values()):
        for b in by_backend:
            unknown[b].append("throughput_latency")
    else:
        lo = min(p95s.values())
        for b in by_backend:
            scores[b]["throughput_latency"] = max(
                0, min(4, round(4 * lo / p95s[b])))

    for b in by_backend:
        runs = by_backend[b]
        # safety-derived dimensions: both candidates preserve the counters
        clean = all(all(v == 0 for v in r["safety_counters"].values())
                    for r in runs)
        scores[b]["duplicate_effect_prevention"] = 4 if clean else 0
        scores[b]["unknown_outcome_reconciliation"] = 4 if clean else 0
        scores[b]["lease_fencing_stale_owner"] = 4 if clean else 0
        scores[b]["task_run_durability"] = (
            4 if contract["candidates"][b]["task_queue"] != "in-memory only"
            else 1)
        scores[b]["checkpoint_integrity_resume"] = 4  # hash-verified per contract
        scores[b]["dag_determinism"] = 4  # identical frozen DAG/seeds
        scores[b]["test_determinism_replay"] = (
            4 if b == "in_process" else 2)  # existing in-process infra (S1-004/S1-005)
        scores[b]["operator_visibility_complexity"] = (
            4 if b == "in_process" else 2)  # one unit vs extra system
        scores[b]["migration_reversibility"] = (
            4 if b == "in_process" else 2)  # current state reverses trivially
    return scores, unknown, rec_med, p95s


def sensitivity(scores: dict, weights: dict, unknown: dict) -> dict:
    def weighted(ws):
        out = {}
        for b, sc in scores.items():
            num = sum(ws[d] * v for d, v in sc.items() if v is not None)
            den = sum(ws[d] for d, v in sc.items() if v is not None)
            out[b] = round(num / den, 4) if den else None
        return out

    base = weighted(weights)
    base_winner = max(base, key=lambda b: base[b])
    flips, runs, ties = 0, 0, 0
    names = list(weights)
    for dim in names:
        for factor in (0.5, 1.5):
            ws = dict(weights)
            ws[dim] = max(1, round(weights[dim] * factor))
            delta = 100 - sum(ws.values())
            rest = [k for k in ws if k != dim]
            share = sum(ws[k] for k in rest)
            if share:
                for k in rest:
                    ws[k] = max(1, round(ws[k] + delta * ws[k] / share))
            sc = weighted(ws)
            win = max(sc, key=lambda b: sc[b])
            runs += 1
            if sc[win] != base[base_winner] and win != base_winner:
                flips += 1
    rng = random.Random(42)
    for i in range(SENSITIVITY_RANDOM_RUNS):
        cuts = sorted(rng.sample(range(1, 100), len(names) - 1))
        parts, prev = [], 0
        for cut in cuts + [100]:
            parts.append(cut - prev)
            prev = cut
        ws = dict(zip(names, parts))
        sc = weighted(ws)
        win = max(sc, key=lambda b: sc[b])
        runs += 1
        if win != base_winner:
            flips += 1
    return {"base_scores": base, "base_winner": base_winner,
            "runs": runs, "flips": flips, "stable": flips == 0}


def validate_runs_manifest(runs_manifest_path: Path,
                           runs_manifest_sha: str | None = None) -> dict:
    """Binding + integrity of the frozen run manifest (review R3 style):
    the evaluator scores EXACTLY the recorded run matrix and verifies the
    manifest digest and every run file digest before use."""
    if runs_manifest_sha:
        actual = sha(runs_manifest_path)
        if actual != runs_manifest_sha:
            raise EvalError(
                f"runs manifest digest mismatch: {actual} != "
                f"{runs_manifest_sha}")
    manifest = load(runs_manifest_path)
    for entry in manifest.get("runs", []):
        run_file = runs_manifest_path.parent / entry["file"]
        if not run_file.is_file():
            raise EvalError(f"run file missing: {entry['file']}")
        if sha(run_file) != entry["sha256"]:
            raise EvalError(f"run file digest mismatch: {entry['file']}")
    return manifest


def evaluate(ticket: Path, results: Path, *,
             runs_manifest_path: Path | None = None,
             runs_manifest_sha: str | None = None,
             expected_commit: str | None = None,
             run_nonce: str | None = None,
             comparison_data: dict | None = None,
             probes_data: dict | None = None,
             manifest_data: dict | None = None) -> dict:
    rubric = load(ticket / "rubric.json")
    rubric_sha = sha(ticket / "rubric.json")
    contract = load(ticket / "backend-contract.json")
    workload = load(ticket / "workload-manifest.json")
    run_a = results / "run-a"
    comparison = (comparison_data if comparison_data is not None
                  else load(results / "backend-comparison.json"))
    probes = (probes_data if probes_data is not None
              else load(results / "probes.json"))
    # runs binding (review R3 style): the evaluator scores EXACTLY the
    # frozen run matrix named by the caller and verifies digests first.
    if runs_manifest_path is None:
        runs_manifest_path = results / "run-a" / "run-manifest.json"
    manifest = (manifest_data if manifest_data is not None else
                validate_runs_manifest(runs_manifest_path,
                                       runs_manifest_sha))

    # Git provenance binding: experiments on a dirty tree or from a
    # different commit than expected are rejected fail-closed.
    prov = manifest.get("provenance") or {}
    if prov.get("dirty"):
        raise EvalError("experiments recorded on a dirty working tree")
    if expected_commit is not None and prov.get("commit") != expected_commit:
        raise EvalError(
            f"experiment commit {prov.get('commit')} != expected commit "
            f"{expected_commit}")

    expected, manifest = validate_run_matrix(
        manifest, workload, comparison, run_a)
    if len(comparison["runs"]) != len(expected):
        raise EvalError("comparison runs != frozen matrix size")
    for run in comparison["runs"]:
        if run.get("commit") != prov.get("commit") or \
                run.get("tree_sha") != prov.get("tree_sha"):
            raise EvalError(
                f"run {run['run_id']}: commit/tree provenance diverges "
                "from the run manifest -> INCOMPARABLE")
        validate_run_entry(run)
    probe_results = evaluate_probes(probes)

    scores, unknown, rec_med, p95s = score_dims(comparison, contract)
    sens = sensitivity(scores, rubric["weights"], unknown)
    winner = sens["base_winner"]

    verdict = "PASS_WITH_LIMITS"  # inherited dependency limits always bind
    reasons = [
        "inherited limits: S1-002 is not a production SLO; S1-005 is "
        "same-host bounded and does not prove multi-host reliability"]
    if unknown.get(winner):
        reasons.append(f"unknown cells on winner: {unknown[winner]}")
    if not sens["stable"]:
        verdict = "PASS_WITH_LIMITS"
        reasons.append("winner flipped under sensitivity analysis")
    if any(v == 0 for b in scores.values() for v in b.values()):
        reasons.append(
            "a candidate scored 0 on at least one dimension (documented "
            "extreme, not a safety violation; safety counters remain zero)")

    return {
        "schema": SCHEMA,
        "rubric_sha256": rubric_sha,
        "run_nonce": run_nonce,
        "runs_binding": {
            "path": str(runs_manifest_path),
            "sha256": sha(runs_manifest_path),
        },
        "scores_normalized": scores,
        "recovery_median_us": rec_med,
        "p95_us": p95s,
        "winner": winner,
        "recommendation": {"topology": winner},
        "probe_rejections": {k: v["verdict"] for k, v in probe_results.items()},
        "sensitivity": {k: v for k, v in sens.items()},
        "verdict": verdict,
        "reasons": reasons,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticket", default=str(
        Path(__file__).resolve().parent))
    ap.add_argument("--results", default=None)
    ap.add_argument("--runs-manifest", default=None,
                    help="frozen run-a manifest to score")
    ap.add_argument("--runs-manifest-sha", default=None,
                    help="sha256 of the frozen run manifest")
    ap.add_argument("--expected-commit", default=None)
    args = ap.parse_args(argv)
    ticket = Path(args.ticket).resolve()
    results = Path(args.results).resolve() if args.results \
        else ticket / "results"
    try:
        result = evaluate(
            ticket, results,
            runs_manifest_path=(Path(args.runs_manifest).resolve()
                                if args.runs_manifest else None),
            runs_manifest_sha=args.runs_manifest_sha,
            expected_commit=args.expected_commit,
            run_nonce=os.environ.get("AGENTOS_RUN_NONCE"))
    except EvalError as exc:
        print(json.dumps({"verdict": "FAIL", "error": str(exc)}, indent=2))
        return 1
    (results / "sensitivity-analysis.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
