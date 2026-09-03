"""S1-011 deterministic evaluator (stdlib only, no network/LLM).

Reads ONLY raw observations (never producer summaries) plus the frozen
host-owned oracle (cases.json) and contracts. Recomputes every metric
from rows and applies fail-closed hard gates.

Admissibility (structural) failures -> exit 1, no metrics trusted:
  missing key, bool-where-int, negative count, NaN/Infinity, empty
  observations, unknown transition/decision/reason, row hash mismatch,
  missing/extra/duplicate case ids vs corpus.

Design verdict (data, exit 0, written to metrics.json):
  any of the 11 hard safety counters != 0 (exact) -> FAIL for that design.
  Soft scores never compensate a hard failure.

Outputs: metrics.json, probes.json (A-H via the real evaluation path).

Usage:
  py -3.12 evaluator.py --run results/run-a --out results/metrics.json \\
      --probes results/probes.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

DECISIONS = {"PROMOTED", "NOT_PROMOTED", "CHALLENGED", "RETRACTED",
             "REJECTED", "NO_TRANSITION", "QUARANTINED", "RECORDED",
             "VISIBLE", "HIDDEN"}
ELIGIBLE_DECISIONS = {"PROMOTED", "CHALLENGED", "RETRACTED", "REJECTED",
                      "RECORDED", "VISIBLE"}
TRANSITIONS = {"gate_pass", "gate_fail", "withdrawn", "challenge_accepted",
               "source_revoked", "superseded", "upheld_with_evidence",
               "challenge_sustained_or_expired", None}

HARD_COUNTERS = ["false_promotion_count", "false_retention_count",
                 "resurrection_count", "missed_invalidation_count",
                 "history_loss_or_rewrite_count",
                 "stale_replay_acceptance_count",
                 "cross_scope_visibility_count", "authority_expansion_count",
                 "duplicate_active_decision_count",
                 "transition_audit_atomicity_violation_count",
                 "derived_without_evidence_promotion_count"]

PROBE_CASES = {"A": ["S1-011-I02", "S1-011-I03"],
               "B": ["S1-011-C01", "S1-011-C02", "S1-011-C09",
                     "S1-011-R12"],
               "C": ["S1-011-A01", "S1-011-A02", "S1-011-A03",
                     "S1-011-A09"],
               "D": ["S1-011-I08", "S1-011-I09"],
               "E": ["S1-011-R01", "S1-011-R02", "S1-011-R03",
                     "S1-011-R10"],
               "F": ["S1-011-R04"],
               "G": ["S1-011-R05", "S1-011-A08"],
               "H": ["S1-011-C07", "S1-011-R07", "S1-011-R08",
                     "S1-011-R09"]}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def is_bad_number(value) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return value < 0
    if isinstance(value, float):
        return True  # floats rejected: counts must be exact integers
    return True


def wilson(hits: int, total: int, z: float = 1.96) -> list:
    if total <= 0:
        return [0.0, 0.0]
    if not isinstance(hits, int) or isinstance(hits, bool) or hits < 0 \
            or hits > total:
        raise ValueError("bad wilson inputs")
    center = (hits + z * z / 2) / (total + z * z)
    half = z * math.sqrt(hits * (total - hits) / total + z * z / 4) / \
        (total + z * z)
    return [round(max(0.0, center - half), 6),
            round(min(1.0, center + half), 6)]


def check_rows(rows: list, oracle: dict) -> tuple:
    """Strict structural validation. Returns (problems, by_id)."""
    problems = []
    if not rows:
        return ["empty observations"], {}
    seen = {}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            problems.append(f"row {i} not an object")
            continue
        for key in ("case_id", "design", "seed", "decision", "transition",
                    "reason_code", "view_visible", "audit_events",
                    "history_preserved", "actor", "idempotency_key",
                    "output_sha256"):
            if key not in row:
                problems.append(f"row {i} missing key {key}")
        if problems and problems[-1].startswith(f"row {i} missing"):
            continue
        want = sha(canonical({k: v for k, v in row.items()
                              if k != "output_sha256"}))
        if row.get("output_sha256") != want:
            problems.append(f"row {i} ({row.get('case_id')}) hash mismatch")
        if not isinstance(row.get("view_visible"), bool) or \
                not isinstance(row.get("history_preserved"), bool):
            problems.append(f"row {i} bool field mistyped")
        if not isinstance(row.get("audit_events"), list):
            problems.append(f"row {i} audit not a list")
        if row.get("decision") not in DECISIONS:
            problems.append(f"row {i} unknown decision "
                            f"{row.get('decision')!r}")
        if row.get("transition") not in TRANSITIONS:
            problems.append(f"row {i} unknown transition "
                            f"{row.get('transition')!r}")
        if not isinstance(row.get("seed"), int) or \
                isinstance(row.get("seed"), bool):
            problems.append(f"row {i} seed not int")
        for numkey in ("seed",):
            value = row.get(numkey)
            if isinstance(value, float) and \
                    (math.isnan(value) or math.isinf(value)):
                problems.append(f"row {i} {numkey} is NaN/Infinity")
        cid = row.get("case_id")
        seen.setdefault(cid, []).append(i)
    dupes = sorted(k for k, v in seen.items() if len(v) > 1)
    for cid in dupes:
        problems.append(f"duplicate case {cid}")
    want_ids = {c["case_id"] for c in oracle["cases"]}
    got_ids = set(seen)
    for cid in sorted(want_ids - got_ids):
        problems.append(f"missing case {cid}")
    for cid in sorted(got_ids - want_ids):
        problems.append(f"extra case {cid}")
    by_id = {}
    for row in rows:
        if isinstance(row, dict) and row.get("case_id") in want_ids:
            by_id.setdefault(row["case_id"], row)
    return problems, by_id


def evaluate(run_dir: Path) -> dict:
    contract = load_json(HERE / "knowledge-gate-contract.json")
    reasons = set(contract["reason_codes"])
    corpus = load_json(HERE / "cases.json")
    raw = load_json(run_dir / "raw-observations.json")
    rows = raw.get("rows", [])
    design = raw.get("design", "unknown")
    seed = raw.get("seed")

    problems, by_id = check_rows(rows, corpus)
    for row in rows:
        if isinstance(row, dict) and row.get("reason_code") not in reasons:
            problems.append(f"unknown reason {row.get('reason_code')!r} "
                            f"in {row.get('case_id')}")
    if problems:
        return {"design": design, "admissible": False,
                "verdict": "FAIL", "problems": problems,
                "rows": len(rows) if isinstance(rows, list) else 0}

    oracle = {c["case_id"]: c for c in corpus["cases"]}
    counters = {name: 0 for name in HARD_COUNTERS}
    confusion = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
    per_class: dict = {}
    invalid_transitions = 0
    covered = set()
    operator_actions = 0
    challenge_backlog = 0
    resolution_steps = 0

    for cid, case in oracle.items():
        row = by_id[cid]
        exp = case["expected"]
        cls = case["class"]
        cell = per_class.setdefault(cls, {"tp": 0, "tn": 0, "fp": 0,
                                          "fn": 0, "n": 0})
        cell["n"] += 1
        if row["transition"]:
            covered.add((case["action"], row["transition"]))
        # confusion over eligible/non-eligible transitions
        actual = exp["decision"] in ELIGIBLE_DECISIONS
        predicted = row["decision"] in ELIGIBLE_DECISIONS
        if actual and predicted:
            confusion["tp"] += 1
            cell["tp"] += 1
        elif not actual and not predicted:
            confusion["tn"] += 1
            cell["tn"] += 1
        elif not actual and predicted:
            confusion["fp"] += 1
            cell["fp"] += 1
        else:
            confusion["fn"] += 1
            cell["fn"] += 1
        # hard counters
        if row["decision"] == "PROMOTED" and exp["decision"] not in (
                "PROMOTED",):
            counters["false_promotion_count"] += 1
        if exp["view_visible"] is False and row["view_visible"] is True:
            counters["false_retention_count"] += 1
        if case.get("probe") in ("E", "F") and row["view_visible"] is True \
                and exp["view_visible"] is False:
            counters["resurrection_count"] += 1
        if case["action"] in ("challenge", "revoke_source") and \
                exp["decision"] in ("CHALLENGED", "RETRACTED") and \
                (row["decision"] not in ("CHALLENGED", "RETRACTED") or
                 row["view_visible"] is True):
            counters["missed_invalidation_count"] += 1
        if row["history_preserved"] is not True:
            counters["history_loss_or_rewrite_count"] += 1
        if case["action"] == "replay_decision" and (
                row["decision"] not in ("NO_TRANSITION",) or
                row["reason_code"] != "REPLAY_REJECTED"):
            counters["stale_replay_acceptance_count"] += 1
        if case.get("cross_scope") and \
                row["view_visible"] is True:
            counters["cross_scope_visibility_count"] += 1
        if row["transition"] and row["actor"] not in (
                "governance_gate", "operator"):
            author_withdrawal = (
                row["transition"] == "withdrawn" and
                row["actor"] == "worker" and
                case.get("prior_status") == "PROPOSED")
            if not (author_withdrawal or
                    (case["action"] == "propose" and
                     row["decision"] == "RECORDED")):
                counters["authority_expansion_count"] += 1
        if case["action"] == "concurrent" and \
                row["reason_code"] not in ("CONCURRENT_RESOLVED",
                                           "DUPLICATE_IDEMPOTENT"):
            counters["duplicate_active_decision_count"] += 1
        if row["transition"] and not row["audit_events"]:
            counters["transition_audit_atomicity_violation_count"] += 1
        derive = case.get("derive") or {}
        if row["decision"] == "PROMOTED" and case["action"] == \
                "derive_claim" and not derive.get("own_evidence"):
            counters["derived_without_evidence_promotion_count"] += 1
        # operator workload model (simulation estimate, NOT a human study)
        if row["decision"] == "CHALLENGED":
            operator_actions += 2
            challenge_backlog += 1
            resolution_steps += 2
        if row["decision"] == "PROMOTED" and row["transition"] == \
                "upheld_with_evidence":
            operator_actions += 3
            resolution_steps += 3
        if row["decision"] == "QUARANTINED":
            operator_actions += 1
            resolution_steps += 1

    for name, value in counters.items():
        if is_bad_number(value):
            return {"design": design, "admissible": False,
                    "verdict": "FAIL",
                    "problems": [f"counter {name} ill-typed: {value!r}"],
                    "rows": len(rows)}

    def prf(cell: dict) -> dict:
        tp, tn, fp, fn = cell["tp"], cell["tn"], cell["fp"], cell["fn"]
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        recall = tp / (tp + fn) if (tp + fn) else 1.0
        fpr = fp / (fp + tn) if (fp + tn) else 0.0
        fnr = fn / (fn + tp) if (fn + tp) else 0.0
        return {"n": cell["n"], "precision": round(precision, 6),
                "recall": round(recall, 6), "fpr": round(fpr, 6),
                "fnr": round(fnr, 6), "abstention": 0,
                "precision_wilson": wilson(tp, tp + fp),
                "recall_wilson": wilson(tp, tp + fn)}

    metrics = {
        "schema": "agentos.s1-011.metrics/v1",
        "design": design,
        "seed": seed,
        "rows": len(rows),
        "admissible": True,
        "transition_coverage": sorted(f"{a}>{t}" for a, t in covered),
        "invalid_transition_count": invalid_transitions,
        "hard_counters": counters,
        "hard_fail": any(v != 0 for v in counters.values()),
        "confusion": confusion,
        "overall": prf({**confusion, "n": len(rows)}),
        "per_class": {cls: prf(cell) for cls, cell in
                      sorted(per_class.items())},
        "operator_model": {
            "actions_per_case": round(operator_actions / len(rows), 4),
            "challenge_backlog": challenge_backlog,
            "resolution_steps": resolution_steps,
            "note": "model/simulation estimate, NOT a human study; "
                    "UX claims deferred to S1-013",
        },
    }
    metrics["verdict"] = "FAIL" if metrics["hard_fail"] else "PASS"
    return metrics


def probes(run_dir: Path) -> dict:
    corpus = load_json(HERE / "cases.json")
    raw = load_json(run_dir / "raw-observations.json")
    rows = {r["case_id"]: r for r in raw.get("rows", [])}
    oracle = {c["case_id"]: c for c in corpus["cases"]}
    out = {"schema": "agentos.s1-011.probes/v1",
           "design": raw.get("design"), "seed": raw.get("seed"),
           "probes": {}}
    for probe, cids in sorted(PROBE_CASES.items()):
        detail = []
        ok = True
        for cid in cids:
            row = rows.get(cid)
            exp = oracle[cid]["expected"]
            match = row is not None and (
                row["decision"], row["transition"], row["reason_code"],
                row["view_visible"]) == (
                exp["decision"], exp["transition"], exp["reason_code"],
                exp["view_visible"])
            hist = row is not None and row["history_preserved"] is True
            passed = bool(match and hist)
            ok = ok and passed
            detail.append({"case_id": cid, "passed": passed,
                           "observed": row["decision"] if row else None,
                           "expected": exp["decision"]})
        out["probes"][probe] = {"passed": ok, "cases": detail}
    out["all_pass"] = all(p["passed"] for p in out["probes"].values())
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="S1-011 evaluator")
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--probes", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run)
    metrics = evaluate(run_dir)
    Path(args.out).write_text(json.dumps(metrics, indent=2) + "\n",
                              encoding="utf-8")
    if metrics.get("admissible"):
        probe_doc = probes(run_dir)
    else:
        probe_doc = {"schema": "agentos.s1-011.probes/v1",
                     "design": metrics.get("design"),
                     "inadmissible": metrics.get("problems"),
                     "all_pass": False}
    Path(args.probes).write_text(json.dumps(probe_doc, indent=2) + "\n",
                                 encoding="utf-8")
    print(f"design={metrics.get('design')} admissible="
          f"{metrics.get('admissible')} verdict={metrics.get('verdict')} "
          f"hard_fail={metrics.get('hard_fail')}")
    return 0 if metrics.get("admissible") else 1


if __name__ == "__main__":
    raise SystemExit(main())
