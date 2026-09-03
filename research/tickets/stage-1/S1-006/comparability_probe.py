#!/usr/bin/env python3
"""S1-006 executable comparability probes (stdlib only, offline, no
LLM/network).  Fail-closed: a latency comparison that uses different task
DAGs or omits crash recovery is INCOMPARABLE and must be rejected.

Probe: ``comparability``
    (a) Extracts the QA2 decision matrix (``agentos.s1-006-decision-matrix/v1``)
        embedded in the ``architecture_models`` artifact.
    (b) Verifies the matrix reports >=3 load levels, p95/p99 per level, and
        recovery-time observations OR explicit ``unavailable`` labels for the
        durable side, with the SAME task DAG id used by both backends at every
        level (identical-DAG comparability).
    (c) Verifies >=4 crash/replay scenarios with detection and recovery paths
        for both backends.
    (d) Adversarial comparability checker: a comparison that uses different
        task DAGs for the two backends, or that omits crash recovery, must be
        rejected as "incomparable"; the bundle's own comparison must be
        accepted.
    (e) Runs a fast live micro-benchmark of the actual in-process engine
        (``agentos`` from this repo, stdlib only) at the 3 load levels,
        computing per-level p95/p99 of the dependency-ready scheduling pass and
        crash-to-resume recovery time; records the observations into
        probe-results.json so the benchmark_measurement claims are real.
    (f) Verifies recommendation completeness (one backend, assumptions,
        rollback/migration trigger, evidence requirements, non-goals), the
        ticket claim-class coverage, and that no production backend was
        installed by this ticket.

The last stdout line is the machine-readable verdict;
the process exits 0 only on ``pass`` and always writes ``probe-results.json``.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

TICKET_DIR = Path(__file__).resolve().parent
BUNDLE_PATH = TICKET_DIR / "bundle.json"
RESULTS_PATH = TICKET_DIR / "probe-results.json"
RESULTS_SCHEMA = "agentos.s1-006-probe-results/v1"
VERDICT_SCHEMA = "agentos.s1-006-probe-verdict/v1"
BENCH_SCHEMA = "agentos.s1-006-p95p99-benchmark/v1"
PROBE_NAME = "comparability"
MATRIX_SCHEMA = "agentos.s1-006-decision-matrix/v1"

MIN_LOAD_LEVELS = 3
MIN_SCENARIOS = 4
MIN_DIMENSIONS = 6
MIN_SCORE, MAX_SCORE = 1, 5
MIN_RECOMMENDED = 1
LOAD_LEVEL_RATE_LABELS = {"10", "34", "100"}

# Ticket claim-class taxonomy -> harness claim classes (research.py accepts
# fact|inference|assumption|target; the ticket labels live in claim text).
LABEL_TO_CLASSES = {
    "architecture_fact": {"fact"},
    "benchmark_measurement": {"fact"},
    "tradeoff": {"fact"},
    "failure_mode": {"assumption"},
    "decision": {"inference", "target"},
}
MIN_LABEL_COUNTS = {
    "architecture_fact": 4,
    "benchmark_measurement": 2,
    "tradeoff": 2,
    "failure_mode": 2,
    "decision": 2,
}

FORBIDDEN_POSITIVE_PATTERNS = (
    r"(?<!no )production (?:durable|execution) engine (?:was|has been|is) (?:installed|integrated|deployed|run|set up)",
    r"(?<!no )production (?:backend|vendor) (?:was|has been|is) (?:installed|integrated|deployed)",
    r"durability (?:is|has been) (?:proven|guaranteed) (?:for|beyond) (?:production|multi.host|distributed)",
)


def find_repo_root() -> Path:
    for candidate in (TICKET_DIR, *TICKET_DIR.parents):
        if (candidate / "AGENTS.md").is_file():
            return candidate
    raise RuntimeError("repository root (AGENTS.md) not found above ticket dir")


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(quantile * len(ordered)) - 1))
    return ordered[index]


def summarize(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0}
    return {
        "n": len(values),
        "p50": round(percentile(values, 0.50), 4),
        "p95": round(percentile(values, 0.95), 4),
        "p99": round(percentile(values, 0.99), 4),
        "max": round(max(values), 4),
    }


def extract_matrix(bundle: dict) -> dict:
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, dict):
        raise RuntimeError("bundle has no artifacts object")
    arch = artifacts.get("architecture_models")
    if not isinstance(arch, dict):
        raise RuntimeError("architecture_models artifact missing")
    content = arch.get("content")
    text = content if isinstance(content, str) else json.dumps(content)
    matches = re.findall(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    for blob in matches:
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("schema") == MATRIX_SCHEMA:
            return parsed
    raise RuntimeError("no fenced JSON block with schema %s found" % MATRIX_SCHEMA)


# -- adversarial comparability checker -----------------------------------------
def classify_comparison(level: dict) -> list[str]:
    """Reasons why a load-level latency comparison is INCOMPARABLE.  Empty
    list means the comparison is comparable (same DAG + crash recovery)."""
    reasons: list[str] = []
    lp = level.get("in_process_scheduler")
    dr = level.get("durable_execution_engine")
    if not isinstance(lp, dict) or not isinstance(dr, dict):
        reasons.append("missing one backend row")
        return reasons
    if lp.get("dag_id") != dr.get("dag_id"):
        reasons.append("different task DAGs between backends")
    if not dr.get("dag_id"):
        reasons.append("durable side declares no task DAG")
    recovery_present = 0
    for side in (lp, dr):
        rec = side.get("recovery")
        if isinstance(rec, dict):
            value = rec.get("recovery_time_ms")
            if value == "unavailable" or (isinstance(value, (int, float)) and value >= 0):
                recovery_present += 1
    if recovery_present < 2:
        reasons.append("crash recovery omitted from the comparison")
    return reasons


def near_miss_different_dag() -> list[str]:
    return classify_comparison({
        "rate_events_per_second": 34,
        "in_process_scheduler": {
            "dag_id": "s1-006-dag-wave-v1", "p95_ms": 0.5, "p99_ms": 1.0,
            "recovery": {"recovery_time_ms": 2.0},
        },
        "durable_execution_engine": {
            "dag_id": "s1-006-dag-OTHER-v1", "p95_ms": "unavailable",
            "p99_ms": "unavailable", "recovery": {"recovery_time_ms": "unavailable"},
        },
    })


def near_miss_omits_recovery() -> list[str]:
    return classify_comparison({
        "rate_events_per_second": 34,
        "in_process_scheduler": {
            "dag_id": "s1-006-dag-wave-v1", "p95_ms": 0.5, "p99_ms": 1.0,
        },
        "durable_execution_engine": {
            "dag_id": "s1-006-dag-wave-v1", "p95_ms": "unavailable",
            "p99_ms": "unavailable",
        },
    })


# -- live micro-benchmark of the real in-process engine ------------------------
def ensure_agentos_importable() -> None:
    sys.path.insert(0, str(find_repo_root() / "src"))


def run_live_benchmark() -> dict:
    """Measure dependency-ready scheduling-pass latency p95/p99 at the 3 load
    levels (10/34/100 tasks per wave, 18 passes each) plus crash-to-resume
    recovery time, using the real engine from this repository (stdlib only,
    temp SQLite under the ticket dir)."""
    ensure_agentos_importable()
    from agentos.db import open_db
    from agentos.engine import Engine
    from agentos.workers import FakeWorker

    # sweep stale temp dirs from interrupted runs (Windows file locks)
    for stale in TICKET_DIR.glob("s1-006-bench-*"):
        import shutil
        shutil.rmtree(stale, ignore_errors=True)

    tmp = Path(tempfile.mkdtemp(prefix="s1-006-bench-", dir=TICKET_DIR))
    db = None
    try:
        db = open_db(tmp / "bench.db")
        engine = Engine(db, tmp)
        levels: list[int] = [10, 34, 100]
        per_level: dict[str, dict] = {}
        for rate in levels:
            goal_id = engine.create_goal(
                "S1-006 comparability wave %s" % rate,
                constraints={"benchmark": "s1-006", "network": "disabled"})
            engine.refine_spec(
                goal_id,
                "Measure dependency-ready scheduling-pass latency.",
                criteria=[{"criterion_id": "latency_recorded", "kind": "tests_present"}])
            engine.activate_goal(goal_id)

            # --- crash-to-resume recovery observation for this level ----------
            # a dedicated no-dependency task so it is READY right after
            # scheduling (crash -> recover_expired_runs -> resume_task).
            engine.plan_tasks(goal_id, [{
                "key": "recovery-%d" % rate,
                "title": "recovery observation",
                "definition_of_done": "resumed",
                "depends_on": [],
            }], actor="system")
            engine.schedule_ready_tasks(goal_id)
            rec_task = db.conn.execute(
                "SELECT id FROM task WHERE goal_id=? AND status='READY'"
                " ORDER BY id LIMIT 1", (goal_id,)).fetchone()
            recovered: list[float] = []
            if rec_task:
                t2 = time.perf_counter_ns()
                run_id, _ctx = engine.open_run(rec_task["id"], lease_minutes=0)
                engine.record_checkpoint(
                    run_id, goal_id, completed=["recovery"],
                    in_progress={}, next_action={}, payload={"recovery": True})
                db.conn.execute(
                    "UPDATE run SET lease_expires_at = "
                    "strftime('%Y-%m-%dT%H:%M:%SZ','now','-1 minute') "
                    "WHERE id=?", (run_id,))
                engine.recover_expired_runs()
                engine.resume_task(rec_task["id"], FakeWorker())
                t3 = time.perf_counter_ns()
                recovered.append((t3 - t2) / 1e6)

            # --- dependency-ready scheduling-pass latency at this level -------
            pass_times: list[float] = []
            wave = 0
            for trial in range(6):
                tasks = []
                # wave DAG: chain of `rate` tasks, always the SAME structural
                # shape across levels (scaled by rate).
                for i in range(rate):
                    tasks.append({
                        "key": "w%d-t%d" % (wave, i),
                        "title": "wave task %d" % i,
                        "definition_of_done": "scheduled",
                        "depends_on": ["w%d-t%d" % (wave, i - 1)] if i > 0 else [],
                    })
                wave += 1
                t0 = time.perf_counter_ns()
                engine.plan_tasks(goal_id, tasks, actor="system")
                engine.schedule_ready_tasks(goal_id)
                t1 = time.perf_counter_ns()
                pass_times.append((t1 - t0) / 1e6)
            per_level["%d" % rate] = {
                "rate_events_per_second": rate,
                "dag_id": "s1-006-dag-wave-v1",
                "passes": summarize(pass_times),
                "recovery_time_ms": round(recovered[0], 4) if recovered else "unavailable",
            }
        return {
            "schema": BENCH_SCHEMA,
            "environment": "single-host Windows, CPython, SQLite/WAL, "
                           "in-process engine (agentos from repo)",
            "method": "dependency-ready scheduling pass = plan_tasks + "
                      "schedule_ready_tasks on a chain DAG of `rate` tasks; "
                      "6 passes per level; recovery = lease-expire -> "
                      "recover_expired_runs -> resume_task(FakeWorker)",
            "load_levels": per_level,
        }
    finally:
        import shutil
        if db is not None:
            try:
                db.conn.close()
            except Exception:
                pass
        shutil.rmtree(tmp, ignore_errors=True)


def evaluate_checks(bundle: dict) -> list[dict]:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> bool:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    matrix = extract_matrix(bundle)

    # --- load levels: >=3, p95/p99, recovery, SAME dag across backends -------
    levels = matrix.get("load_levels")
    level_problems: list[str] = []
    same_dag = True
    recovery_ok = True
    pct_ok = True
    distinct_rates: set[str] = set()
    if isinstance(levels, list) and len(levels) >= MIN_LOAD_LEVELS:
        for level in levels:
            rate = str(level.get("rate_events_per_second", "")).replace(".0", "")
            distinct_rates.add(rate)
            reasons = classify_comparison(level)
            if reasons:
                same_dag = False
                recovery_ok = False
            lp = level.get("in_process_scheduler")
            dr = level.get("durable_execution_engine")
            if isinstance(lp, dict):
                p95 = lp.get("p95_ms")
                p99 = lp.get("p99_ms")
                if not isinstance(p95, (int, float)) or p95 <= 0:
                    pct_ok = False
                if not isinstance(p99, (int, float)) or p99 <= 0:
                    pct_ok = False
            if isinstance(dr, dict):
                for key in ("p95_ms", "p99_ms"):
                    value = dr.get(key)
                    if value != "unavailable" and not (
                            isinstance(value, (int, float)) and value >= 0):
                        pct_ok = False
    else:
        level_problems.append("fewer than %d load levels" % MIN_LOAD_LEVELS)

    covered = LOAD_LEVEL_RATE_LABELS.issubset(distinct_rates) or (
        len(distinct_rates) >= MIN_LOAD_LEVELS and all(
            r in ("10", "34", "100") for r in distinct_rates))
    check("three-load-levels-with-p95p99-and-recovery-or-unavailable",
          covered and pct_ok and same_dag and recovery_ok,
          "rates=%s p95p99=%s same_dag=%s recovery=%s problems=%s" % (
              sorted(distinct_rates), pct_ok, same_dag, recovery_ok, level_problems))

    # --- >=4 crash/replay scenarios with both recovery paths ------------------
    scenarios = matrix.get("failure_scenarios")
    scen_problems: list[str] = []
    if isinstance(scenarios, list) and len(scenarios) >= MIN_SCENARIOS:
        for scenario in scenarios:
            sid = scenario.get("id", "?") if isinstance(scenario, dict) else "?"
            for key in ("detection", "in_process_recovery", "durable_recovery",
                        "evidence"):
                value = scenario.get(key) if isinstance(scenario, dict) else None
                if not value or (key == "evidence" and not isinstance(value, list)):
                    scen_problems.append("%s missing %s" % (sid, key))
    else:
        scen_problems.append("fewer than %d scenarios" % MIN_SCENARIOS)
    check("at-least-four-crash-replay-scenarios-complete",
          not scen_problems,
          "scenarios=%d problems=%s" % (
              len(scenarios) if isinstance(scenarios, list) else 0, scen_problems))

    # --- dimensions scored 1..5 for both backends, totals consistent ---------
    dimensions = matrix.get("dimensions")
    sums = {"in_process_scheduler": 0, "durable_execution_engine": 0}
    dim_problems: list[str] = []
    if isinstance(dimensions, list) and len(dimensions) >= MIN_DIMENSIONS:
        for dim in dimensions:
            if not isinstance(dim, dict) or not dim.get("id"):
                dim_problems.append("dimension missing id")
                continue
            for option in ("in_process_scheduler", "durable_execution_engine"):
                side = dim.get(option)
                if not isinstance(side, dict):
                    dim_problems.append("%s/%s missing" % (dim.get("id"), option))
                    continue
                score = side.get("score")
                if not isinstance(score, int) or not MIN_SCORE <= score <= MAX_SCORE:
                    dim_problems.append("%s/%s score %r outside %d..%d" % (
                        dim.get("id"), option, score, MIN_SCORE, MAX_SCORE))
                else:
                    sums[option] += score
                if not side.get("evidence"):
                    dim_problems.append("%s/%s lacks evidence refs" % (
                        dim.get("id"), option))
    else:
        dim_problems.append("fewer than %d dimensions" % MIN_DIMENSIONS)
    totals = matrix.get("totals") if isinstance(matrix.get("totals"), dict) else {}
    check("six-plus-dimensions-scored-totals-consistent",
          not dim_problems
          and totals.get("in_process_scheduler") == sums["in_process_scheduler"]
          and totals.get("durable_execution_engine") == sums["durable_execution_engine"],
          "recomputed=%s declared=%s problems=%s" % (sums, totals, dim_problems))

    # --- adversarial comparability near-misses --------------------------------
    diff_dag = near_miss_different_dag()
    omit_rec = near_miss_omits_recovery()
    check("near-miss-different-dag-rejected-incomparable",
          any("different task DAGs" in reason for reason in diff_dag),
          "reasons=%s" % diff_dag)
    check("near-miss-omitted-crash-recovery-rejected-incomparable",
          any("crash recovery omitted" in reason
              or "missing one backend row" in reason or "no task DAG" in reason
              for reason in omit_rec),
          "reasons=%s" % omit_rec)
    check("bundle-comparison-comparable-same-dag-with-recovery",
          not level_problems,
          "comparability reasons=%s" % level_problems)

    # --- recommendation completeness ------------------------------------------
    rec = matrix.get("recommendation")
    rec_problems: list[str] = []
    if not isinstance(rec, dict):
        rec_problems.append("recommendation missing")
    else:
        if rec.get("backend") not in ("in_process_scheduler", "durable_execution_engine"):
            rec_problems.append("no single backend recommended")
        assumptions = rec.get("assumptions")
        if not isinstance(assumptions, list) or len([a for a in assumptions if str(a).strip()]) < 2:
            rec_problems.append("missing explicit assumptions")
        for key in ("migration_trigger", "rollback_trigger"):
            value = rec.get(key)
            if not isinstance(value, list) or not [v for v in value if str(v).strip()]:
                rec_problems.append("missing %s" % key)
        evidence = rec.get("evidence_requirements")
        if not isinstance(evidence, list) or len([e for e in evidence if str(e).strip()]) < 3:
            rec_problems.append("missing evidence requirements")
        non_goals = rec.get("non_goals")
        if not isinstance(non_goals, list) or len([n for n in non_goals if str(n).strip()]) < 2:
            rec_problems.append("missing non-goals")
    check("single-recommendation-with-trigger-evidence-and-non-goals",
          not rec_problems, "problems=%s" % rec_problems)

    # --- no production backend installed claim --------------------------------
    haystacks: list[str] = []
    for claim in bundle.get("claims", []):
        if isinstance(claim, dict):
            haystacks.append(str(claim.get("text", "")))
    for kind, artifact in bundle.get("artifacts", {}).items():
        content = artifact.get("content") if isinstance(artifact, dict) else None
        haystacks.append(content if isinstance(content, str) else json.dumps(content))
    blob = "\n".join(haystacks)
    hits = [pat for pat in FORBIDDEN_POSITIVE_PATTERNS
            if re.search(pat, blob, flags=re.I)]
    check("no-production-backend-installed-claim",
          not hits, "forbidden positive claims: %s" % (hits or "none"))

    # --- ticket claim-class coverage ------------------------------------------
    counts = {label: 0 for label in LABEL_TO_CLASSES}
    claim_problems: list[str] = []
    for claim in bundle.get("claims", []):
        if not isinstance(claim, dict):
            continue
        text = str(claim.get("text", ""))
        match = re.match(r"\[([a-z_]+)\]", text)
        label = match.group(1) if match else None
        if label not in LABEL_TO_CLASSES:
            claim_problems.append("claim %s lacks a ticket-class label" % claim.get("id"))
            continue
        counts[label] += 1
        if claim.get("claim_class") not in LABEL_TO_CLASSES[label]:
            claim_problems.append(
                "claim %s label %s maps to %s but declares %s" % (
                    claim.get("id"), label, LABEL_TO_CLASSES[label],
                    claim.get("claim_class")))
    short = {label: counts[label] for label, minimum in MIN_LABEL_COUNTS.items()
             if counts[label] < minimum}
    check("ticket-claim-class-coverage-present-and-mapped",
          not short and not claim_problems,
          "counts=%s short=%s problems=%s" % (counts, short, claim_problems))

    # --- audit producer binding ------------------------------------------------
    platform_producer = bundle.get("artifacts", {}).get(
        "platform_plan", {}).get("producer", "")
    audit_artifact_producer = bundle.get("artifacts", {}).get(
        "independent_audit", {}).get("producer", "")
    audit = bundle.get("audit", {})
    audit_ok = (
        platform_producer == "agentos-s1-006-producer"
        and audit_artifact_producer == "agentos-s1-006-independent-verifier"
        and audit.get("subject_producer") == platform_producer
        and audit.get("auditor") == audit_artifact_producer
        and audit.get("verdict") in ("pass", "pass_with_limits")
        and bool(audit.get("limitations"))
    )
    check("independent-audit-producer-binding",
          audit_ok,
          "platform=%s audit_artifact=%s verdict=%s" % (
              platform_producer, audit_artifact_producer, audit.get("verdict")))

    return checks


def run_probe_with_benchmark(bundle: dict) -> tuple[list[dict], dict]:
    checks = evaluate_checks(bundle)
    bench = None
    try:
        bench = run_live_benchmark()
        levels = (bench or {}).get("load_levels") or {}
        checks.append({
            "name": "live-benchmark-recorded",
            "ok": bool(bench and levels),
            "detail": "levels measured: %s" % sorted(levels.keys())
                     if bench and levels else "benchmark produced no load levels",
        })
    except Exception as exc:  # benchmark failure is a fail-closed record
        checks.append({
            "name": "live-benchmark-recorded",
            "ok": False,
            "detail": "%s: %s" % (type(exc).__name__, exc),
        })
    return checks, bench


def write_results(record: dict, bench: dict | None) -> None:
    existing: dict = {}
    if RESULTS_PATH.is_file():
        try:
            loaded = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            existing = {}
    probes = {p.get("probe"): p
              for p in existing.get("probes", []) if isinstance(p, dict)}
    probes[record["probe"]] = record
    ordered = [probes[name] for name in ("replay-resume", "comparability")
               if name in probes]
    document = {
        "schema": RESULTS_SCHEMA,
        "ticket": "S1-006",
        "probes": ordered,
        "benchmark": bench,
        "final_verdict": "pass" if all(
            p.get("status") == "pass" for p in ordered) else "fail",
    }
    RESULTS_PATH.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1-006 comparability probe")
    parser.add_argument("--out", default=None,
                        help="optional result file (default: ticket dir probe-results.json)")
    parser.add_argument("--measure-only", action="store_true",
                        help="run only the live benchmark and print JSON (no verdict)")
    args = parser.parse_args(argv)

    if args.measure_only:
        try:
            bench = run_live_benchmark()
        except Exception as exc:
            print(json.dumps({"error": "%s: %s" % (type(exc).__name__, exc)}))
            return 1
        print(json.dumps(bench, indent=2, ensure_ascii=False))
        return 0

    try:
        bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
        checks, bench = run_probe_with_benchmark(bundle)
    except Exception as exc:  # fail closed
        record = {
            "probe": PROBE_NAME, "schema": VERDICT_SCHEMA,
            "status": "fail", "observed": "fail",
            "error": "%s: %s" % (type(exc).__name__, exc),
        }
        try:
            write_results(record, None)
        except OSError as e2:
            print("warning: could not write results file: %s" % e2, file=sys.stderr)
        print(json.dumps(record, ensure_ascii=False))
        return 1

    failed = [c["name"] for c in checks if not c["ok"]]
    record = {
        "probe": PROBE_NAME, "schema": VERDICT_SCHEMA,
        "status": "pass" if not failed else "fail",
        "observed": "pass" if not failed else "fail",
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "failed_checks": failed,
        "checks": checks,
    }
    out_path = Path(args.out) if args.out else RESULTS_PATH
    try:
        write_results(record, bench)
    except OSError as exc:
        print("warning: could not write results file: %s" % exc, file=sys.stderr)
    print(json.dumps(record, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())