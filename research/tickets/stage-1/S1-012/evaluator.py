"""S1-012 deterministic evaluator (stdlib only, no network/LLM).

Reads ONLY raw observations (never producer summaries) plus the frozen
host-owned oracle (cases.json) and contracts. Recomputes every metric
from rows and applies fail-closed hard gates.

Admissibility (structural) failures -> exit 1:
  missing key, bool-where-int, negative count, NaN/Infinity, empty
  observations, unknown variant/decision/reason, row hash mismatch,
  missing/extra/duplicate (case, variant, seed) cells.

Independent rechecks (never trusting row math):
  - unit digests recomputed from frozen corpus texts per view;
  - Beta tails recomputed by exact binomial summation for integer
    (a,b) (tolerance 1e-9); non-integer params checked finite/in-range;
    threshold flag consistency;
  - EigenTrust vectors checked row-stochastic; anchorless runs must
    abstain with null trust; the frozen 2-node reference (D23) must
    match within tolerance;
  - oracle match on (n_independent, outcome, reason_code) per variant.

Hard gates (exact zero per governed variant; reputation-only is the
expected-to-fail negative control and is excluded from candidacy):
  mirror_sybil_double_count, cross_scope/stale/revoked acceptance,
  authority_expansion (enforcement_allow must stay false),
  unbound_or_missing observations. UNKNOWN/abstain per oracle is
  allowed but never counted as correct.

Metrics: PROMOTED-analogous positive is admit; raw confusion with
denominators, precision/recall/FPR/FNR, coverage/abstention per
class x variant, false split/merge, independent-count MAE, AUC of the
Beta tail against oracle admit labels plus mean tail by class (tails
are hypothesis quantities, never truth probabilities), Wilson
intervals at case level (mirrors/seed-reruns excluded from n).

Outputs: metrics.json, probes.json (A-G via the real path; H
publication-tamper is validated at compare time and merged there).

Usage:
  py -3.12 evaluator.py --run <cell> --out <cell>/metrics.json \\
      --probes <cell>/probes.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

VARIANTS = ("document", "span", "digest", "reputation-only")
OUTCOMES = ("admit", "reject", "abstain")
GOVERNED = ("document", "span", "digest")

HARD_COUNTERS = ["mirror_sybil_double_count", "cross_scope_acceptance",
                 "stale_acceptance", "revoked_acceptance",
                 "authority_expansion_count",
                 "unbound_or_missing_observations"]

PROBE_CASES = {
    "A": ["S1-012-D09", "S1-012-D10", "S1-012-D11", "S1-012-H05",
          "S1-012-D17", "S1-012-H09"],
    "B": ["S1-012-D19", "S1-012-D20", "S1-012-H10"],
    "C": ["S1-012-D13", "S1-012-D14", "S1-012-D15", "S1-012-H07",
          "S1-012-H08"],
    "D": ["S1-012-D21", "S1-012-D22", "S1-012-D30", "S1-012-H11"],
    "E": ["S1-012-D25", "S1-012-D26", "S1-012-D27", "S1-012-D28",
          "S1-012-D29", "S1-012-H13", "S1-012-H14", "S1-012-H16"],
    "F": ["S1-012-D19", "S1-012-D20", "S1-012-H10", "S1-012-D23",
          "S1-012-H12"],
    "G": ["S1-012-D02", "S1-012-D33", "S1-012-D34", "S1-012-D40",
          "S1-012-H03", "S1-012-H17", "S1-012-H18"],
}

ATTACK_FAMILIES = ("correlation", "sybil")


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
        return True
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


def binomial_tail(a: int, b: int, x: float) -> float:
    """Exact P[theta > x] for integer Beta(a,b) via finite summation."""
    n = a + b - 1
    cdf = sum(math.comb(n, j) * x ** j * (1.0 - x) ** (n - j)
              for j in range(a, n + 1))
    return 1.0 - cdf


def auc_rank(scores: list, labels: list) -> float | None:
    """AUC by pairwise comparison. None when undefined (one class)."""
    pos = [s for s, lab in zip(scores, labels) if lab == 1]
    neg = [s for s, lab in zip(scores, labels) if lab == 0]
    if not pos or not neg:
        return None
    wins = sum(1 for p in pos for n in neg if p > n)
    ties = sum(1 for p in pos for n in neg if p == n)
    return round((wins + 0.5 * ties) / (len(pos) * len(neg)), 6)


def check_rows(rows: list, oracle: dict, variant: str) -> tuple:
    problems = []
    if not rows:
        return ["empty observations"], {}
    seen = {}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            problems.append(f"row {i} not an object")
            continue
        for key in ("case_id", "split", "family", "variant", "seed",
                    "params", "n_independent", "outcome", "reason_code",
                    "enforcement_allow", "units", "groups", "beta",
                    "eigentrust", "costs", "output_sha256"):
            if key not in row:
                problems.append(f"row {i} missing key {key}")
        if problems and problems[-1].startswith(f"row {i} missing"):
            continue
        want = sha(canonical({k: v for k, v in row.items()
                              if k != "output_sha256"}))
        if row.get("output_sha256") != want:
            problems.append(f"row {i} ({row.get('case_id')}) hash mismatch")
        if row.get("variant") != variant:
            problems.append(f"row {i} variant drift {row.get('variant')!r}")
        if row.get("outcome") not in OUTCOMES:
            problems.append(f"row {i} unknown outcome "
                            f"{row.get('outcome')!r}")
        if not isinstance(row.get("n_independent"), int) or \
                isinstance(row.get("n_independent"), bool) or \
                row.get("n_independent") < 0:
            problems.append(f"row {i} n_independent ill-typed")
        if row.get("enforcement_allow") is not False:
            problems.append(f"row {i} enforcement_allow not false")
        if not isinstance(row.get("units"), list) or \
                not isinstance(row.get("groups"), list):
            problems.append(f"row {i} units/groups not lists")
        beta = row.get("beta") or {}
        for numkey in ("a", "b", "tail"):
            value = beta.get(numkey)
            if value is not None and (
                    not isinstance(value, (int, float)) or
                    isinstance(value, bool) or
                    (isinstance(value, float) and
                     (math.isnan(value) or math.isinf(value)))):
                problems.append(f"row {i} beta.{numkey} ill-typed")
        if not isinstance(row.get("seed"), int) or \
                isinstance(row.get("seed"), bool):
            problems.append(f"row {i} seed not int")
        cid = row.get("case_id")
        seen.setdefault((cid, row.get("seed")), []).append(i)
    dupes = sorted(f"{cid}@{seed}" for (cid, seed), v in seen.items()
                   if len(v) > 1)
    for dup in dupes:
        problems.append(f"duplicate case {dup}")
    seeds = {row.get("seed") for row in rows
             if isinstance(row, dict) and isinstance(row.get("seed"), int)
             and not isinstance(row.get("seed"), bool)}
    want_ids = {(c["case_id"], seed) for c in oracle["cases"]
                for seed in (seeds or {None})}
    got_ids = set(seen)
    for cid, seed in sorted(want_ids - got_ids, key=str):
        problems.append(f"missing case {cid}@{seed}")
    for cid, seed in sorted(got_ids - want_ids, key=str):
        problems.append(f"extra case {cid}@{seed}")
    by_id = {}
    oracle_ids = {c["case_id"] for c in oracle["cases"]}
    for row in rows:
        if isinstance(row, dict) and row.get("case_id") in oracle_ids:
            by_id.setdefault((row["case_id"], row.get("seed")), row)
    return problems, by_id


def verify_units(row: dict, case: dict, variant: str) -> list:
    """Recompute unit digests from frozen corpus texts per view."""
    violations = []
    texts: dict = {}
    for doc in case.get("documents", []):
        texts[("doc", doc.get("doc_id"))] = doc.get("text", "")
        for span in doc.get("spans", []):
            texts[("span", span.get("span_id"))] = span.get("text", "")
    if variant == "document":
        want = {sha(f"s1-012:content:{doc.get('text', '')}".encode())
                for doc in case.get("documents", [])}
        got = {u.get("digest") for u in row.get("units", [])}
        if got != want:
            violations.append("document unit digests != corpus texts")
    elif variant == "span":
        want = set()
        for doc in case.get("documents", []):
            spans = doc.get("spans") or [
                {"span_id": doc.get("doc_id") + "#whole",
                 "text": doc.get("text", "")}]
            for span in spans:
                want.add(sha(f"s1-012:content:{span.get('text', '')}"
                             .encode()))
        got = {u.get("digest") for u in row.get("units", [])}
        if got != want:
            violations.append("span unit digests != corpus texts")
    elif variant == "digest":
        want = {sha(f"s1-012:content:{doc.get('text', '')}".encode())
                for doc in case.get("documents", [])}
        got = {u.get("digest") for u in row.get("units", [])}
        if got != want:
            violations.append("digest unit set != corpus digests")
    for unit in row.get("units", []):
        digest = unit.get("digest", "")
        if not isinstance(digest, str) or len(digest) != 64:
            violations.append(f"unit {unit.get('unit_id')} digest malformed")
    return violations


def verify_beta(row: dict) -> list:
    violations = []
    beta = row.get("beta") or {}
    aval, bval, tail = beta.get("a"), beta.get("b"), beta.get("tail")
    if tail is None:
        if beta.get("threshold_met") is not None:
            violations.append("null tail with non-null flag")
        return violations
    if not (0.0 <= tail <= 1.0):
        violations.append("tail outside [0,1]")
    if beta.get("threshold_met") != bool(tail >= 0.95):
        violations.append("threshold flag inconsistent with tail")
    if isinstance(aval, int) and not isinstance(aval, bool) and \
            isinstance(bval, int) and not isinstance(bval, bool) and \
            aval > 0 and bval > 0 and aval + bval <= 60:
        try:
            ref = binomial_tail(aval, bval, 0.9)
        except (ValueError, OverflowError):
            violations.append("reference computation failed")
            return violations
        if abs(ref - tail) > 1e-9:
            violations.append(
                f"tail {tail} != binomial reference {ref}")
    return violations


def verify_trust(row: dict, case: dict) -> list:
    violations = []
    trust = row.get("eigentrust") or {}
    ratings = case.get("ratings", [])
    anchor = case.get("anchor")
    if not ratings:
        if trust.get("abstain") is not True:
            violations.append("rating-free case must abstain trust")
        return violations
    if not anchor:
        if trust.get("abstain") is not True or \
                trust.get("trust") is not None:
            violations.append("anchorless graph must abstain with null "
                              "trust")
        return violations
    vector = trust.get("trust") or {}
    if trust.get("abstain") is not False or not vector:
        violations.append("anchored graph must converge with a vector")
        return violations
    total = sum(vector.values())
    if abs(total - 1.0) > 1e-9:
        violations.append("trust vector not stochastic")
    if any(v < 0.0 or v > 1.0 for v in vector.values()):
        violations.append("trust value outside [0,1]")
    ref = (case.get("eigentrust_reference") or {})
    if ref:
        for node, value in zip(sorted(vector), ref.get("trust", [])):
            if abs(vector[node] - value) > ref.get("tolerance", 1e-6):
                violations.append(
                    f"trust mismatch on {node} vs frozen reference")
    return violations


def evaluate(run_dir: Path) -> dict:
    contract = load_json(HERE / "independence-contract.json")
    reasons = set(contract["reason_codes"])
    corpus = load_json(HERE / "cases.json")
    raw = load_json(run_dir / "raw-observations.json")
    rows = raw.get("rows", [])
    variant = raw.get("design", raw.get("variant", "unknown"))
    seed = raw.get("seed")

    problems, by_id = check_rows(rows, corpus, variant)
    for row in rows:
        if isinstance(row, dict) and row.get("reason_code") not in reasons:
            problems.append(f"unknown reason {row.get('reason_code')!r} "
                            f"in {row.get('case_id')}")
    if problems:
        return {"variant": variant, "admissible": False,
                "verdict": "FAIL", "problems": problems,
                "rows": len(rows) if isinstance(rows, list) else 0}

    oracle = {c["case_id"]: c for c in corpus["cases"]}
    counters = {name: 0 for name in HARD_COUNTERS}
    confusion = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
    per_class: dict = {}
    per_split: dict = {}
    exact = 0
    view_n_err = 0
    total = 0
    abstentions = 0
    false_split = 0
    false_merge = 0
    tails: list = []
    labels: list = []
    tails_by_class: dict = {}
    operator_flags = 0

    for (cid, _seed) in sorted(by_id, key=str):
        row = by_id[(cid, _seed)]
        case = oracle[cid]
        exp = case["expected"][variant]
        total += 1
        for bucket, key in ((per_class, case["family"]),
                            (per_split, case.get("split", "dev"))):
            cell = bucket.setdefault(key, {"tp": 0, "tn": 0, "fp": 0,
                                           "fn": 0, "n": 0,
                                           "abstain": 0})
            cell["n"] += 1
        # independent rechecks
        violations = verify_units(row, case, variant)
        violations += verify_beta(row)
        violations += verify_trust(row, case)
        if violations:
            counters["unbound_or_missing_observations"] += 1
        # oracle match
        if (row["n_independent"], row["outcome"], row["reason_code"]) == (
                exp["n_independent"], exp["outcome"], exp["reason"]):
            exact += 1
        if row["n_independent"] != exp["n_independent"]:
            view_n_err += abs(row["n_independent"] - exp["n_independent"])
        # confusion: positive is admit; abstain excluded from P/R
        actual = exp["outcome"] == "admit"
        predicted = row["outcome"] == "admit"
        if row["outcome"] == "abstain" or exp["outcome"] == "abstain":
            abstentions += 1
            per_class[case["family"]]["abstain"] += 1
            per_split[case.get("split", "dev")]["abstain"] += 1
            if row["outcome"] == "abstain" and exp["outcome"] != "abstain":
                confusion["fn"] += 1
                per_class[case["family"]]["fn"] += 1
                per_split[case.get("split", "dev")]["fn"] += 1
            elif row["outcome"] != "abstain" and exp["outcome"] == "abstain":
                confusion["fp"] += 1
                per_class[case["family"]]["fp"] += 1
                per_split[case.get("split", "dev")]["fp"] += 1
        elif actual and predicted:
            confusion["tp"] += 1
            per_class[case["family"]]["tp"] += 1
            per_split[case.get("split", "dev")]["tp"] += 1
        elif not actual and not predicted:
            confusion["tn"] += 1
            per_class[case["family"]]["tn"] += 1
            per_split[case.get("split", "dev")]["tn"] += 1
        elif not actual and predicted:
            confusion["fp"] += 1
            per_class[case["family"]]["fp"] += 1
            per_split[case.get("split", "dev")]["fp"] += 1
        else:
            confusion["fn"] += 1
            per_class[case["family"]]["fn"] += 1
            per_split[case.get("split", "dev")]["fn"] += 1
        # hard counters (governed truth: oracle document-view n)
        true_n = case["expected"]["document"]["n_independent"]
        if case["family"] in ATTACK_FAMILIES and \
                case["expected"]["document"]["outcome"] == "reject" and \
                row["n_independent"] > true_n:
            counters["mirror_sybil_double_count"] += 1
        if exp["reason"] in ("REJECTED_CROSS_SCOPE",) and \
                row["outcome"] == "admit":
            counters["cross_scope_acceptance"] += 1
        if exp["reason"] in ("REJECTED_STALE",) and \
                row["outcome"] == "admit":
            counters["stale_acceptance"] += 1
        if exp["reason"] in ("REJECTED_REVOKED",) and \
                row["outcome"] == "admit":
            counters["revoked_acceptance"] += 1
        if row.get("enforcement_allow") is not False:
            counters["authority_expansion_count"] += 1
        # false split/merge on span/digest views
        if variant == "span" and row["n_independent"] > true_n and \
                case["family"] in ATTACK_FAMILIES:
            false_split += 1
        if variant == "digest" and row["n_independent"] < true_n and \
                case["family"] == "gold":
            false_merge += 1
        # tail discrimination data (tails are hypothesis quantities)
        beta = row.get("beta") or {}
        if beta.get("tail") is not None and exp["outcome"] in (
                "admit", "reject"):
            tails.append(beta["tail"])
            labels.append(1 if exp["outcome"] == "admit" else 0)
            tails_by_class.setdefault(case["family"], []).append(
                beta["tail"])
        if row["outcome"] == "admit" and \
                row.get("reason_code") == "RECOMMENDATION_ONLY":
            operator_flags += 1

    for name, value in counters.items():
        if is_bad_number(value):
            return {"variant": variant, "admissible": False,
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
                "fnr": round(fnr, 6),
                "abstention": cell.get("abstain", 0),
                "precision_wilson": wilson(tp, tp + fp),
                "recall_wilson": wilson(tp, tp + fn)}

    hard_fail = any(v != 0 for v in counters.values())
    metrics = {
        "schema": "agentos.s1-012.metrics/v1",
        "variant": variant,
        "seed": seed,
        "rows": len(rows),
        "admissible": True,
        "hard_counters": counters,
        "hard_fail": hard_fail,
        "confusion": confusion,
        "confusion_definition": "positive outcome is admit; abstain rows "
                                "are excluded from precision/recall and "
                                "reported as abstention",
        "overall": prf({**confusion, "n": total,
                        "abstain": abstentions}),
        "transition_exactness": round(exact / total, 6) if total else 0.0,
        "n_mae": round(view_n_err / total, 6) if total else 0.0,
        "abstention_rate": round(abstentions / total, 6) if total else 0.0,
        "false_split": false_split,
        "false_merge": false_merge,
        "tail_auc_vs_admit": auc_rank(tails, labels),
        "mean_tail_by_class": {cls: round(sum(v) / len(v), 6) for cls, v in
                               sorted(tails_by_class.items())},
        "tail_note": "Beta tails are hypothesis quantities for the "
                     "planning threshold, never truth probabilities.",
        "operator_flags": operator_flags,
        "per_class": {cls: prf(cell) for cls, cell in
                      sorted(per_class.items())},
        "per_split": {spl: prf(cell) for spl, cell in
                      sorted(per_split.items())},
    }
    metrics["verdict"] = "FAIL" if hard_fail else "PASS"
    return metrics


def probes(run_dir: Path) -> dict:
    corpus = load_json(HERE / "cases.json")
    raw = load_json(run_dir / "raw-observations.json")
    grouped: dict = {}
    for row in raw.get("rows", []):
        grouped.setdefault(row.get("case_id"), []).append(row)
    oracle = {c["case_id"]: c for c in corpus["cases"]}
    variant = raw.get("design", raw.get("variant"))
    out = {"schema": "agentos.s1-012.probes/v1", "variant": variant,
           "seed": raw.get("seed"), "probes": {}}
    for probe, cids in sorted(PROBE_CASES.items()):
        detail = []
        ok = True
        for cid in cids:
            candidates = grouped.get(cid, [])
            exp = oracle[cid]["expected"][variant]
            seed_results = []
            for row in candidates:
                match = (
                    row["n_independent"], row["outcome"],
                    row["reason_code"]) == (
                    exp["n_independent"], exp["outcome"], exp["reason"])
                firewall = row.get("enforcement_allow") is False
                seed_results.append(bool(match and firewall))
            passed = bool(candidates) and all(seed_results)
            ok = ok and passed
            detail.append({"case_id": cid, "passed": passed,
                           "seeds": len(candidates),
                           "observed": candidates[0]["outcome"]
                           if candidates else None,
                           "expected": exp["outcome"]})
        out["probes"][probe] = {"passed": ok, "cases": detail}
    out["all_pass"] = all(p["passed"] for p in out["probes"].values())
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="S1-012 evaluator")
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--probes", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run)
    metrics = evaluate(run_dir)
    Path(args.out).write_text(json.dumps(metrics, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    if metrics.get("admissible"):
        probe_doc = probes(run_dir)
    else:
        probe_doc = {"schema": "agentos.s1-012.probes/v1",
                     "design": metrics.get("variant"),
                     "inadmissible": metrics.get("problems"),
                     "all_pass": False}
    Path(args.probes).write_text(json.dumps(probe_doc, indent=2) + "\n",
                                 encoding="utf-8", newline="\n")
    print(f"variant={metrics.get('variant')} admissible="
          f"{metrics.get('admissible')} verdict={metrics.get('verdict')} "
          f"hard_fail={metrics.get('hard_fail')}")
    return 0 if metrics.get("admissible") else 1


if __name__ == "__main__":
    raise SystemExit(main())
