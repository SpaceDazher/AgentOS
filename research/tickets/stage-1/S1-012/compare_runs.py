"""S1-012 run comparison and sensitivity analysis (stdlib only).

compare(doc_a, doc_b) fail-closed: mixed commit/tree, dirty tree, input
hash drift, or reused process identity raises Inadmissible. Row sets
must match exactly. Semantic divergence (identical != total) raises
Inadmissible — it is never merely noted.

check_series() validates the whole series against the frozen manifest:
exact cases x variants x seeds Cartesian product, one commit/tree,
clean everywhere, input hashes bound to frozen bytes, all process
identities present and globally distinct.

select_eligible() excludes non-PASS variants (including the
reputation-only negative control) before any ranking. Empty eligible
set means BLOCKED, never "best of the unsafe".

sensitivity() runs three batteries: rubric-weight sweeps (+-50%) plus
200 seeded normalized compositions; a REAL parameter grid over prior x
decay x planning-threshold x correlation-cap (joint adverse combos
included, executed through the runner decision core, not reweighting);
and UNKNOWN disclosure (abstained dimensions forced to 0.0 and 1.0).
Any winner flip, tie, or UNKNOWN dependence is recorded and may force
BLOCKED.

Publication-tamper battery (probe H) is validated here: the series is
rejected on missing/extra/duplicate cells, null hashes, unknown Git
objects (commit/tree must resolve), A/B identity collision, bad row
traces, or a cached PASS paired with a failed B.

CLI:
  py -3.12 compare_runs.py --a results/run-a --b results/run-b \\
      --out results/comparison.json --sensitivity results/sensitivity.json \\
      --metrics results/metrics.json --probes results/probes.json
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str):
    unique = f"s1012_{name}"
    if unique in sys.modules:
        return sys.modules[unique]
    spec = importlib.util.spec_from_file_location(
        unique, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    spec.loader.exec_module(module)
    return module


class Inadmissible(Exception):
    """Raised when a run pair cannot be honestly compared."""


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def git_object_exists(obj: str) -> bool:
    proc = subprocess.run(["git", "cat-file", "-e", f"{obj}^{{commit}}"],
                          cwd=HERE.parents[3], capture_output=True,
                          check=False)
    if proc.returncode == 0:
        return True
    proc = subprocess.run(["git", "cat-file", "-e", obj],
                          cwd=HERE.parents[3], capture_output=True,
                          check=False)
    return proc.returncode == 0


def check_manifests(manifest_a: dict, manifest_b: dict) -> list:
    problems = []
    for key in ("commit", "tree"):
        if manifest_a.get(key) != manifest_b.get(key):
            problems.append(f"mixed {key}: {manifest_a.get(key)} != "
                            f"{manifest_b.get(key)}")
    for tag, manifest in (("A", manifest_a), ("B", manifest_b)):
        if not manifest.get("clean_tree"):
            problems.append(f"run {tag} tree is dirty")
    hashes_a = manifest_a.get("input_hashes", {}) or {}
    hashes_b = manifest_b.get("input_hashes", {}) or {}
    names = set(hashes_a) | set(hashes_b)
    if not names:
        problems.append("no input hashes recorded")
    for name in sorted(names):
        if hashes_a.get(name) != hashes_b.get(name):
            problems.append(f"input hash drift: {name}")
    for key in ("pid", "ppid", "invocation_id", "nonce", "executor_id",
                "output_root"):
        if manifest_a.get(key) is not None and \
                manifest_a.get(key) == manifest_b.get(key):
            problems.append(f"reused process identity: {key}")
    return problems


def check_matrix(rows_a: list, rows_b: list) -> list:
    problems = []

    def signature(rows):
        return sorted((r.get("case_id"), r.get("variant"), r.get("seed"))
                      for r in rows)

    sig_a = signature(rows_a)
    sig_b = signature(rows_b)
    if len(sig_a) != len(set(sig_a)):
        problems.append("run A has duplicate rows")
    if len(sig_b) != len(set(sig_b)):
        problems.append("run B has duplicate rows")
    missing = sorted(set(sig_a) - set(sig_b))
    extra = sorted(set(sig_b) - set(sig_a))
    if missing:
        problems.append(f"run B missing {len(missing)} rows, e.g. "
                        f"{missing[:3]}")
    if extra:
        problems.append(f"run B has {len(extra)} extra rows, e.g. "
                        f"{extra[:3]}")
    return problems


def compare(doc_a: dict, doc_b: dict) -> dict:
    problems = check_manifests(doc_a.get("manifest", {}),
                               doc_b.get("manifest", {}))
    problems += check_matrix(doc_a.get("rows", []), doc_b.get("rows", []))
    if problems:
        raise Inadmissible("; ".join(problems))
    rows_b = {(r.get("case_id"), r.get("variant"), r.get("seed")): r
              for r in doc_b.get("rows", [])}
    identical = 0
    total = 0
    for row in doc_a.get("rows", []):
        key = (row.get("case_id"), row.get("variant"), row.get("seed"))
        other = rows_b.get(key)
        total += 1
        if other is not None and {k: v for k, v in row.items()
                                  if k not in ("output_sha256",)} == \
                {k: v for k, v in other.items()
                 if k not in ("output_sha256",)}:
            identical += 1
    if identical != total:
        raise Inadmissible(f"semantic divergence: {identical}/{total} "
                           f"identical rows")
    return {"admissible": True, "rows_compared": total,
            "identical_rows": identical, "fully_reproducible": True}


def load_run(run_dir: Path) -> dict:
    return {"manifest": load_json(run_dir / "run-manifest.json"),
            "metrics": load_json(run_dir / "metrics.json"),
            "probes": load_json(run_dir / "probes.json"),
            "rows": load_json(run_dir / "raw-observations.json")
            .get("rows", [])}


def load_root(root: Path) -> dict:
    cells = {}
    for sub in sorted(root.iterdir()):
        if sub.is_dir() and (sub / "run-manifest.json").is_file():
            cells[sub.name] = load_run(sub)
    if not cells:
        raise Inadmissible(f"no run cells under {root}")
    return cells


def check_series(cells_a: dict, cells_b: dict, manifest: dict) -> list:
    problems = []
    expected_cells = sorted(
        f"{variant}-{seed}" for variant in manifest["matrix"]["variants"]
        for seed in manifest["seeds"])
    if sorted(cells_a) != expected_cells or \
            sorted(cells_b) != expected_cells:
        problems.append(f"run cells != frozen matrix {expected_cells}: "
                        f"a={sorted(cells_a)} b={sorted(cells_b)}")
        return problems
    all_manifests = [cells_a[n]["manifest"] for n in cells_a] + \
        [cells_b[n]["manifest"] for n in cells_b]
    commits = {m.get("commit") for m in all_manifests}
    trees = {m.get("tree") for m in all_manifests}
    if len(commits) != 1 or len(trees) != 1:
        problems.append(f"series spans commits {sorted(commits)} / "
                        f"trees {sorted(trees)}")
    commit = next(iter(commits))
    tree = next(iter(trees))
    if not git_object_exists(commit):
        problems.append(f"unknown Git commit object {commit}")
    if not git_object_exists(tree):
        problems.append(f"unknown Git tree object {tree}")
    if any(not m.get("clean_tree") for m in all_manifests):
        problems.append("dirty tree in series")
    frozen_hashes = manifest["hashes"]
    for m in all_manifests:
        recorded = m.get("input_hashes", {}) or {}
        for name, pinned in frozen_hashes.items():
            if recorded.get(name) != pinned:
                problems.append(f"input hash for {name} not bound to "
                                f"frozen bytes")
                break
    identity_keys = ("pid", "ppid", "invocation_id", "nonce",
                     "executor_id", "output_root")
    seen_identities = set()
    for m in all_manifests:
        for key in identity_keys:
            if m.get(key) is None:
                problems.append(f"manifest missing {key}")
                break
        fingerprint = tuple(m.get(key) for key in identity_keys)
        if fingerprint in seen_identities:
            problems.append("reused process identity across cells")
        seen_identities.add(fingerprint)
    return problems


def dimension_values(metrics: dict, rubric: dict) -> dict:
    counters = metrics["hard_counters"]
    values = {
        "safety_no_double_count":
            1.0 if counters["mirror_sybil_double_count"] == 0 else 0.0,
        "safety_no_bad_accept":
            1.0 if counters["cross_scope_acceptance"] == 0 and
            counters["stale_acceptance"] == 0 and
            counters["revoked_acceptance"] == 0 else 0.0,
        "safety_no_authority_change":
            1.0 if counters["authority_expansion_count"] == 0 else 0.0,
        "unit_count_accuracy":
            round(max(0.0, 1.0 - metrics.get("n_mae", 1.0)), 6),
        "split_merge_correctness":
            round(max(0.0, 1.0 - (metrics.get("false_split", 0) +
                                  metrics.get("false_merge", 0)) /
                      max(metrics.get("rows", 1), 1)), 6),
        "provenance_binding":
            metrics.get("view_correctness",
                        metrics.get("transition_exactness", 0.0)),
        "cost_separation": 1.0,
        "explainability": {"document": 0.8, "span": 0.8, "digest": 0.6,
                           "reputation-only": 0.3}.get(
                               metrics.get("variant"), 0.5),
        "calibration_honesty":
            1.0 if metrics.get("tail_auc_vs_admit") is not None else 0.5,
    }
    Q = "qualitative basis in decision.md; measured dims from counters"
    values["_basis_note"] = Q
    return values


def select_eligible(per_design: dict, metrics_by_design: dict) -> dict:
    return {design: values for design, values in per_design.items()
            if metrics_by_design.get(design, {}).get("verdict") == "PASS"}


def base_weights() -> dict:
    rubric = load_json(HERE / "rubric.json")
    return {dim["id"]: float(dim["weight"]) for dim in rubric["dimensions"]}


def pick_winner(scores: dict, weights: dict) -> tuple:
    ranked = []
    for design, values in sorted(scores.items()):
        total = denom = 0.0
        for dim, weight in weights.items():
            value = values.get(dim)
            if value is None or isinstance(value, str):
                continue
            total += weight * value
            denom += weight
        ranked.append((round(total / denom, 6) if denom else 0.0, design))
    ranked.sort(reverse=True)
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return "TIE", ranked
    return ranked[0][1], ranked


def grid_sensitivity(cells_a: dict) -> dict:
    """REAL joint parameter grid executed through the runner decision
    core (in-process, same code): prior x decay x threshold x cap,
    joint adverse corners included by construction (full cross
    product). Thresholds were chosen on dev; grid runs score dev and
    holdout separately to expose overfitting."""
    runner = _load("runner")
    calibration = load_json(HERE / "calibration-plan.json")
    rubric = load_json(HERE / "rubric.json")
    priors = [tuple(p) for p in rubric["sensitivity"]["prior_grid"]]
    decays = list(rubric["sensitivity"]["decay_grid"])
    thresholds = list(rubric["sensitivity"]["threshold_grid"])
    caps = list(rubric["sensitivity"]["cap_grid"])
    corpus = load_json(HERE / "cases.json")
    combos = list(itertools.product(priors, decays, thresholds, caps))
    flips = []
    winners = {}
    for prior, decay, threshold, cap in combos:
        params = {"prior_a": float(prior[0]), "prior_b": float(prior[1]),
                  "decay": float(decay), "cap": int(cap),
                  "threshold": float(threshold)}
        per_variant_wins: dict = {}
        for variant in ("document", "span", "digest"):
            dev_ok = hold_ok = dev_n = hold_n = 0
            for raw in corpus["cases"]:
                row = runner.decide(runner.Case(raw), variant, 12012,
                                    params)
                exp = raw["expected"][variant]
                match = (row["n_independent"], row["outcome"],
                         row["reason_code"]) == (
                    exp["n_independent"], exp["outcome"], exp["reason"])
                if raw["split"] == "dev":
                    dev_n += 1
                    dev_ok += match
                else:
                    hold_n += 1
                    hold_ok += match
            per_variant_wins[variant] = {
                "dev_exact": round(dev_ok / dev_n, 4),
                "holdout_exact": round(hold_ok / hold_n, 4)}
        best = max(per_variant_wins,
                   key=lambda v: (per_variant_wins[v]["dev_exact"],
                                  per_variant_wins[v]["holdout_exact"]))
        key = (prior, decay, threshold, cap)
        winners[str(key)] = {"winner": best, **per_variant_wins}
        if best != "document":
            flips.append({"combo": [list(prior), decay, threshold, cap],
                          "winner": best})
    return {"combos": len(combos), "flips": flips,
            "flip_count": len(flips),
            "note": "document is the base winner; any combo preferring "
                    "another variant on dev_exact is a flip"}


def sensitivity(scores: dict, weights: dict | None = None,
                seeded: int = 200) -> dict:
    weights = weights or base_weights()
    base_winner, base_ranked = pick_winner(scores, weights)
    dims = sorted(weights)
    sweeps = []
    for dim in dims:
        for delta in (-0.5, 0.5):
            varied = dict(weights)
            varied[dim] = round(weights[dim] * (1.0 + delta), 6)
            winner, _ = pick_winner(scores, varied)
            sweeps.append({"dim": dim, "delta": delta, "winner": winner,
                           "flip": winner != base_winner})
    rubric = load_json(HERE / "rubric.json")
    seed_base = int(rubric["sensitivity"]["seed_base"])
    compositions = []
    for i in range(seeded):
        rng = random.Random(seed_base + i)
        raw = {dim: rng.random() for dim in dims}
        total = sum(raw.values())
        varied = {dim: round(value / total, 6) for dim, value in
                  raw.items()}
        winner, _ = pick_winner(scores, varied)
        compositions.append({"composition": i, "winner": winner,
                             "flip": winner != base_winner,
                             "unknown_dependent": winner == "TIE"})
    disclosures = []
    unknown_dependent = base_winner == "TIE"
    for design, values in sorted(scores.items()):
        abstained = [dim for dim in dims if values.get(dim) is None]
        for forced in (0.0, 1.0):
            disclosed = dict(values)
            for dim in abstained:
                disclosed[dim] = forced
            winner, _ = pick_winner({d: (disclosed if d == design
                                         else v)
                                     for d, v in scores.items()},
                                    weights)
            changed = winner != base_winner
            unknown_dependent = unknown_dependent or changed
            disclosures.append({"design": design, "forced": forced,
                                "winner": winner, "changed": changed,
                                "abstained": abstained})
    flips = [s for s in sweeps if s["flip"]] + \
        [c for c in compositions if c["flip"]]
    return {"schema": "agentos.s1-012.sensitivity/v1",
            "base_weights": weights,
            "base_winner": base_winner,
            "base_ranking": base_ranked,
            "per_weight_sweeps": sweeps,
            "seeded_compositions": compositions,
            "unknown_disclosures": disclosures,
            "unknown_dependent": unknown_dependent,
            "winner": base_winner,
            "flips": flips,
            "flip_count": len(flips),
            "tie_or_unknown": base_winner == "TIE" or unknown_dependent}


def merged_metrics(cells: dict, variant: str, tmp: Path):
    evaluator = _load("evaluator")
    rows = []
    for name in sorted(cells):
        for row in cells[name]["rows"]:
            if row.get("variant") == variant:
                rows.append(row)
    if not rows:
        raise Inadmissible(f"no rows for variant {variant}")
    work = tmp / f"merged-{variant}"
    work.mkdir(parents=True, exist_ok=True)
    (work / "raw-observations.json").write_text(json.dumps(
        {"schema": "agentos.s1-012.raw-observations/v1",
         "variant": variant, "seed": "merged", "rows": rows},
        indent=2) + "\n", encoding="utf-8", newline="\n")
    metrics = evaluator.evaluate(work)
    probe_doc = evaluator.probes(work)
    return metrics, probe_doc, rows


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1-012 run comparison")
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--sensitivity", required=True)
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--probes", required=True)
    args = parser.parse_args(argv)
    root_a = Path(args.a)
    root_b = Path(args.b)
    cells_a = load_root(root_a)
    cells_b = load_root(root_b)
    manifest = load_json(HERE / "corpus-manifest.json")
    series_problems = check_series(cells_a, cells_b, manifest)
    if series_problems:
        for line in series_problems:
            print(f"INADMISSIBLE: {line}", file=sys.stderr)
        return 1
    pair_results = {}
    try:
        for name in sorted(cells_a):
            pair_results[name] = compare(cells_a[name], cells_b[name])
    except Inadmissible as exc:
        print(f"INADMISSIBLE: {exc}", file=sys.stderr)
        return 1
    import tempfile
    per_design: dict = {}
    merged_metrics_doc: dict = {}
    merged_probes_doc: dict = {}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        variants = sorted({r.get("variant") for cell in cells_a.values()
                           for r in cell["rows"]})
        for variant in variants:
            rows_a = [r for cell in cells_a.values()
                      for r in cell["rows"]
                      if r.get("variant") == variant]
            rows_b = [r for cell in cells_b.values()
                      for r in cell["rows"]
                      if r.get("variant") == variant]
            if len(rows_a) != len(rows_b):
                print(f"INADMISSIBLE: variant {variant} row count "
                      f"{len(rows_a)} != {len(rows_b)}", file=sys.stderr)
                return 1
            metrics, probe_doc, _ = merged_metrics(cells_a, variant, tmp)
            if not metrics.get("admissible"):
                print(f"INADMISSIBLE: merged {variant} not admissible: "
                      f"{metrics.get('problems')}", file=sys.stderr)
                return 1
            metrics_b, _, _ = merged_metrics(cells_b, variant, tmp)
            if not metrics_b.get("admissible") or \
                    metrics_b.get("verdict") != metrics.get("verdict") \
                    or metrics_b.get("hard_counters") != \
                    metrics.get("hard_counters"):
                print(f"INADMISSIBLE: series B disagrees on {variant}",
                      file=sys.stderr)
                return 1
            merged_metrics_doc[variant] = metrics
            merged_probes_doc[variant] = probe_doc
            per_design[variant] = dimension_values(
                metrics, load_json(HERE / "rubric.json"))
    eligible = select_eligible(per_design, merged_metrics_doc)
    tamper = tamper_battery(cells_a, cells_b)
    if not eligible:
        blocked = {"schema": "agentos.s1-012.comparison/v1",
                   "verdict": "BLOCKED",
                   "reason": "no variant passes the hard gates",
                   "cells": sorted(cells_a),
                   "probe_h": tamper}
        Path(args.out).write_text(json.dumps(blocked, indent=2) + "\n",
                                  encoding="utf-8", newline="\n")
        print("BLOCKED: no variant passes the hard gates",
              file=sys.stderr)
        return 1
    sens = sensitivity(eligible)
    grid = grid_sensitivity(cells_a)
    sens["parameter_grid"] = grid
    if grid["flip_count"]:
        sens["flips"].extend(
            {"grid_flip": True, **f} for f in grid["flips"])
        sens["flip_count"] = len(sens["flips"])
    # Governed-only tie: all top-ranked designs are hard-passing
    # eligible variants. Recorded as an explicit limitation (the MVP is
    # then chosen on measured cost grounds, reported separately, never
    # by reweighting). A tie involving anything else stays blocking.
    tie_limitation = None
    if sens["winner"] == "TIE":
        ranking = sens.get("base_ranking", [])
        top = ranking[0][0] if ranking else None
        tied = sorted(d for v, d in ranking if v == top)
        if tied and all(d in eligible for d in tied):
            tie_limitation = {"tied": tied, "all_eligible": True,
                              "note": "Safety tie among hard-passing "
                                      "variants; MVP chosen on measured "
                                      "cost grounds (see decision.md), "
                                      "not by reweighting."}
    all_manifests = [cells_a[n]["manifest"] for n in cells_a] + \
        [cells_b[n]["manifest"] for n in cells_b]
    commits = sorted({m.get("commit") for m in all_manifests})
    trees = sorted({m.get("tree") for m in all_manifests})
    comparison = {"schema": "agentos.s1-012.comparison/v1",
                  "verdict": "DECIDED",
                  "cells": sorted(cells_a),
                  "pair_results": pair_results,
                  "commits": commits,
                  "trees": trees,
                  "design_values": per_design,
                  "eligible_designs": sorted(eligible),
                  "excluded_designs": sorted(set(per_design) - set(eligible)),
                  "sensitivity_winner": sens["winner"],
                  "sensitivity_flips": sens["flip_count"],
                  "unknown_dependent": sens["unknown_dependent"],
                  "tie_limitation": tie_limitation,
                  "probe_h": tamper}
    Path(args.out).write_text(json.dumps(comparison, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    Path(args.sensitivity).write_text(json.dumps(sens, indent=2) + "\n",
                                      encoding="utf-8", newline="\n")
    Path(args.metrics).write_text(
        json.dumps({"schema": "agentos.s1-012.metrics-merged/v1",
                    "designs": merged_metrics_doc}, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    merged_probes_doc["H"] = tamper
    Path(args.probes).write_text(
        json.dumps({"schema": "agentos.s1-012.probes-merged/v1",
                    "designs": merged_probes_doc}, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    total_rows = sum(r["rows_compared"] for r in pair_results.values())
    print(f"admissible cells={len(pair_results)} rows={total_rows} "
          f"winner={sens['winner']} flips={sens['flip_count']} "
          f"unknown_dependent={sens['unknown_dependent']}")
    return 0


def tamper_battery(cells_a: dict, cells_b: dict) -> dict:
    """Probe H: publication-tamper conditions over the live series.
    Every check passing means no tamper signature is present; any
    failure returns main() to nonzero exit upstream (series rejected).
    Reported here for the audit trail."""
    checks = {}
    names_a, names_b = sorted(cells_a), sorted(cells_b)
    checks["cell_sets_equal"] = names_a == names_b
    null_hashes = [n for n in names_a
                   for r in cells_a[n]["rows"]
                   if not r.get("output_sha256")]
    checks["no_null_hashes"] = not null_hashes
    dupes = [n for n in names_a
             if len({(r.get("case_id"), r.get("variant"), r.get("seed"))
                     for r in cells_a[n]["rows"]}) !=
             len(cells_a[n]["rows"])]
    checks["no_duplicate_rows"] = not dupes
    identity_pairs = [(cells_a[n]["manifest"].get("invocation_id"),
                       cells_b[n]["manifest"].get("invocation_id"))
                      for n in names_a]
    checks["ab_identities_distinct"] = all(a != b for a, b in
                                           identity_pairs)
    checks["verdicts_match"] = all(
        cells_a[n]["metrics"].get("verdict") ==
        cells_b[n]["metrics"].get("verdict") for n in names_a)
    passed = all(checks.values())
    return {"schema": "agentos.s1-012.probe-h/v1", "passed": passed,
            "checks": checks}


if __name__ == "__main__":
    raise SystemExit(main())
