"""S1-011 run comparison and sensitivity analysis (stdlib only).

compare(doc_a, doc_b) fail-closed: mixed commit/tree, dirty tree, input
hash drift, or reused process identity (pid/ppid/invocation/nonce/
executor/output-root equal) raises Inadmissible. Row sets must match
exactly (same case/design/seed, no missing/extra/duplicate).

sensitivity(scores) varies frozen rubric weights: each soft weight +-50%
one at a time plus >=200 seeded normalized compositions (seed_base from
rubric). Records winner flips, ties, and unknown-dependent winners.

Scores combine measured safety (from metrics.json hard counters) with the
frozen qualitative cells (design-alternatives.json); UNKNOWN abstains and
is renormalized out. Operator workload stays a model estimate (S1-013).

CLI:
  py -3.12 compare_runs.py --a results/run-a --b results/run-b \\
      --out results/comparison.json --sensitivity results/sensitivity.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


class Inadmissible(Exception):
    """Raised when a run pair cannot be honestly compared."""


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


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
        return sorted((r.get("case_id"), r.get("design"), r.get("seed"))
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
    rows_b = {(r.get("case_id"), r.get("design"), r.get("seed")): r
              for r in doc_b.get("rows", [])}
    identical = 0
    total = 0
    for row in doc_a.get("rows", []):
        key = (row.get("case_id"), row.get("design"), row.get("seed"))
        other = rows_b.get(key)
        total += 1
        if other is not None and {k: v for k, v in row.items()
                                  if k not in ("output_sha256",)} == \
                {k: v for k, v in other.items()
                 if k not in ("output_sha256",)}:
            identical += 1
    if identical != total:
        # Semantic divergence between two runs of the same matrix is
        # inadmissible evidence, never a noted mismatch (F5).
        raise Inadmissible(f"semantic divergence: {identical}/{total} "
                           f"identical rows")
    return {"admissible": True, "rows_compared": total,
            "identical_rows": identical,
            "fully_reproducible": True}


def dimension_values(metrics: dict, alternatives: dict) -> dict:
    design = metrics["design"]
    counters = metrics["hard_counters"]
    cells = alternatives["cells"][design]
    values = {
        "safety_fail_closed": 1.0 if all(
            v == 0 for v in counters.values()) else 0.0,
        "provenance_auditability": 1.0 if counters[
            "history_loss_or_rewrite_count"] == 0 else 0.0,
        "challenge_retraction": 1.0 if (
            counters["missed_invalidation_count"] == 0 and
            counters["false_retention_count"] == 0) else 0.0,
        "replay_testability": 1.0 if (
            counters["stale_replay_acceptance_count"] == 0 and
            counters["resurrection_count"] == 0) else 0.0,
    }
    for dim in ("explainability", "operator_load", "complexity",
                "ontology_shacl_fit", "migration_rollback",
                "evolvability"):
        # Utility estimate from the frozen cell (F11: never confidence).
        values[dim] = cells[dim].get("utility")
    return values


def score(values: dict, weights: dict) -> tuple:
    total = 0.0
    denom = 0.0
    abstained = []
    for dim, weight in weights.items():
        value = values.get(dim)
        if value is None:
            abstained.append(dim)
            continue
        total += weight * value
        denom += weight
    if denom <= 0:
        return 0.0, abstained
    return round(total / denom, 6), abstained


def base_weights() -> dict:
    rubric = load_json(HERE / "rubric.json")
    return {dim["id"]: float(dim["weight"]) for dim in rubric["dimensions"]}


def pick_winner(scores: dict, weights: dict) -> tuple:
    ranked = []
    for design, values in sorted(scores.items()):
        value, _ = score(values, weights)
        ranked.append((value, design))
    ranked.sort(reverse=True)
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return "TIE", ranked
    return ranked[0][1], ranked


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
        winner, ranked = pick_winner(scores, varied)
        compositions.append({"composition": i, "winner": winner,
                             "flip": winner != base_winner,
                             "unknown_dependent": winner == "TIE"})
    # UNKNOWN disclosure (F11): re-score with every abstained dimension
    # forced to worst (0.0) and best (1.0). A winner change means the
    # conclusion depends on unknown values.
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
    # Simultaneous worst-winner/best-challenger bounds cover combinations
    # missed by changing only one design at a time (positive linear weights).
    for challenger in sorted(scores):
        if challenger == base_winner:
            continue
        bounded = {d: {dim: (v.get(dim) if v.get(dim) is not None else
                              (1.0 if d == challenger else 0.0))
                       for dim in dims} for d, v in scores.items()}
        winner, _ = pick_winner(bounded, weights)
        changed = winner != base_winner
        unknown_dependent |= changed
        disclosures.append({"challenger": challenger, "winner": winner,
                            "changed": changed, "simultaneous_bounds": True})
    flips = [s for s in sweeps if s["flip"]] + \
        [c for c in compositions if c["flip"]]
    return {"schema": "agentos.s1-011.sensitivity/v1",
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


def load_run(run_dir: Path) -> dict:
    return {"manifest": load_json(run_dir / "run-manifest.json"),
            "metrics": load_json(run_dir / "metrics.json"),
            "probes": load_json(run_dir / "probes.json"),
            "rows": load_json(run_dir / "raw-observations.json")
            .get("rows", [])}


def check_series(cells_a: dict, cells_b: dict, manifest: dict) -> list:
    """Global series validation against the frozen manifest. Returns
    problems (empty means admissible series). Checks: frozen Cartesian
    cell set, one commit/tree, clean everywhere, input hashes bound to
    frozen bytes, all process identities present and globally distinct."""
    problems = []
    expected_cells = sorted(
        f"{design}-{seed}" for design in manifest["matrix"]["designs"]
        for seed in manifest["seeds"])
    if sorted(cells_a) != expected_cells or \
            sorted(cells_b) != expected_cells:
        problems.append(f"run cells != frozen matrix {expected_cells}: "
                        f"a={sorted(cells_a)} b={sorted(cells_b)}")
        return problems
    case_ids = {c["case_id"] for c in load_json(HERE / "cases.json")["cases"]}
    for tag, cells in (("A", cells_a), ("B", cells_b)):
        for design in manifest["matrix"]["designs"]:
            for seed in manifest["seeds"]:
                cell = cells[f"{design}-{seed}"]
                expected = {(cid, design, seed) for cid in case_ids}
                actual = [(r.get("case_id"), r.get("design"), r.get("seed"))
                          for r in cell.get("rows", []) if isinstance(r, dict)]
                m = cell["manifest"]
                if len(actual) != len(expected) or set(actual) != expected or \
                        m.get("design") != design or m.get("seed") != seed or \
                        type(m.get("rows")) is not int or m["rows"] != len(expected):
                    problems.append(f"{tag} {design}-{seed} incomplete/misbound rows")
    all_manifests = [cells_a[n]["manifest"] for n in cells_a] + \
        [cells_b[n]["manifest"] for n in cells_b]
    commits = {m.get("commit") for m in all_manifests}
    trees = {m.get("tree") for m in all_manifests}
    if len(commits) != 1 or len(trees) != 1:
        problems.append(f"series spans commits {sorted(commits)} / "
                        f"trees {sorted(trees)}")
    if any(m.get("clean_tree") is not True for m in all_manifests):
        problems.append("dirty tree in series")
    frozen_hashes = manifest["hashes"]
    commit = next(iter(commits)) if len(commits) == 1 else None
    tree = next(iter(trees)) if len(trees) == 1 else None
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit) or \
            not isinstance(tree, str) or not re.fullmatch(r"[0-9a-f]{40}", tree):
        problems.append("invalid Git object identity")
    else:
        resolved = subprocess.run(["git", "rev-parse", f"{commit}^{{tree}}"],
                                  cwd=HERE, capture_output=True, text=True)
        if resolved.returncode or resolved.stdout.strip() != tree:
            problems.append("Git commit does not resolve to recorded tree")
        else:
            for name, pinned in frozen_hashes.items():
                path = (HERE / name).resolve()
                if not path.is_relative_to(HERE.resolve()) or not path.is_file():
                    problems.append(f"invalid frozen path: {name}")
                    continue
                rel = path.relative_to(HERE.parents[3]).as_posix()
                obj = subprocess.run(["git", "show", f"{commit}:{rel}"],
                                     cwd=HERE, capture_output=True)
                if obj.returncode or hashlib.sha256(obj.stdout).hexdigest() != pinned or \
                        hashlib.sha256(path.read_bytes()).hexdigest() != pinned:
                    problems.append(f"frozen bytes not bound to Git tree: {name}")
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


def select_eligible(per_design: dict, metrics_by_design: dict) -> dict:
    """Exclude hard-failed designs before any ranking (F10). A design
    with a non-PASS verdict never enters scoring or sensitivity."""
    return {design: values for design, values in per_design.items()
            if metrics_by_design.get(design, {}).get("verdict") == "PASS"}


def load_root(root: Path) -> dict:
    """Load a run root: one subdir per design-seed cell, each a run dir."""
    cells = {}
    for sub in sorted(root.iterdir()):
        if sub.is_dir() and (sub / "run-manifest.json").is_file():
            cells[sub.name] = load_run(sub)
    if not cells:
        raise Inadmissible(f"no run cells under {root}")
    return cells


def merged_metrics(cells: dict, design: str, tmp: Path):
    """Re-evaluate seed-merged rows for one design via the real path."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "s1011_evaluator", HERE / "evaluator.py")
    evaluator_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluator_mod)
    rows = []
    for name in sorted(cells):
        for row in cells[name]["rows"]:
            if row.get("design") == design:
                rows.append(row)
    if not rows:
        raise Inadmissible(f"no rows for design {design}")
    work = tmp / f"merged-{design}"
    work.mkdir(parents=True, exist_ok=True)
    (work / "raw-observations.json").write_text(json.dumps(
        {"schema": "agentos.s1-011.raw-observations/v1", "design": design,
         "seed": "merged", "rows": rows}, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    metrics = evaluator_mod.evaluate(work)
    probe_doc = evaluator_mod.probes(work)
    return metrics, probe_doc, rows


def main() -> int:
    parser = argparse.ArgumentParser(description="S1-011 run comparison")
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--sensitivity", required=True)
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--probes", required=True)
    args = parser.parse_args()
    root_a = Path(args.a)
    root_b = Path(args.b)
    cells_a = load_root(root_a)
    cells_b = load_root(root_b)
    # Frozen Cartesian product (F6): designs x seeds from the manifest,
    # not from whatever the producer happened to emit.
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
    alternatives = load_json(HERE / "design-alternatives.json")
    per_design: dict = {}
    merged_metrics_doc: dict = {}
    merged_probes_doc: dict = {}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        designs = sorted({r.get("design") for cell in cells_a.values()
                          for r in cell["rows"]})
        for design in designs:
            rows_a = [r for cell in cells_a.values()
                      for r in cell["rows"]
                      if r.get("design") == design]
            rows_b = [r for cell in cells_b.values()
                      for r in cell["rows"]
                      if r.get("design") == design]
            if len(rows_a) != len(rows_b):
                print(f"INADMISSIBLE: design {design} row count "
                      f"{len(rows_a)} != {len(rows_b)}", file=sys.stderr)
                return 1
            metrics, probe_doc, _ = merged_metrics(cells_a, design, tmp)
            if not metrics.get("admissible"):
                print(f"INADMISSIBLE: merged {design} not admissible: "
                      f"{metrics.get('problems')}", file=sys.stderr)
                return 1
            # Both series must independently support the same verdict
            # and counters (F5): A-only scoring is inadmissible.
            metrics_b, _, _ = merged_metrics(cells_b, design, tmp)
            if not metrics_b.get("admissible") or \
                    metrics_b.get("verdict") != metrics.get("verdict") \
                    or metrics_b.get("hard_counters") != \
                    metrics.get("hard_counters"):
                print(f"INADMISSIBLE: series B disagrees on {design}",
                      file=sys.stderr)
                return 1
            merged_metrics_doc[design] = metrics
            merged_probes_doc[design] = probe_doc
            per_design[design] = dimension_values(metrics, alternatives)
    # Hard-failed designs are excluded before any ranking (F10).
    eligible = select_eligible(per_design, merged_metrics_doc)
    if not eligible:
        blocked = {"schema": "agentos.s1-011.comparison/v1",
                   "verdict": "BLOCKED",
                   "reason": "no design passes the hard gates",
                   "cells": sorted(cells_a)}
        Path(args.out).write_text(json.dumps(blocked, indent=2) + "\n",
                                  encoding="utf-8", newline="\n")
        print("BLOCKED: no design passes the hard gates",
              file=sys.stderr)
        return 1
    sens = sensitivity(eligible)
    all_manifests = [cells_a[n]["manifest"] for n in cells_a] + \
        [cells_b[n]["manifest"] for n in cells_b]
    commits = sorted({m.get("commit") for m in all_manifests})
    trees = sorted({m.get("tree") for m in all_manifests})
    comparison = {"schema": "agentos.s1-011.comparison/v1",
                  "verdict": "DECIDED",
                  "cells": sorted(cells_a),
                  "pair_results": pair_results,
                  "commits": sorted(commits),
                  "trees": sorted(trees),
                  "design_values": per_design,
                  "eligible_designs": sorted(eligible),
                  "excluded_designs": sorted(set(per_design) - set(eligible)),
                  "sensitivity_winner": sens["winner"],
                  "sensitivity_flips": sens["flip_count"],
                  "unknown_dependent": sens["unknown_dependent"]}
    Path(args.out).write_text(json.dumps(comparison, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    Path(args.sensitivity).write_text(json.dumps(sens, indent=2) + "\n",
                                      encoding="utf-8", newline="\n")
    Path(args.metrics).write_text(
        json.dumps({"schema": "agentos.s1-011.metrics-merged/v1",
                    "designs": merged_metrics_doc}, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    Path(args.probes).write_text(
        json.dumps({"schema": "agentos.s1-011.probes-merged/v1",
                    "designs": merged_probes_doc}, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    total_rows = sum(r["rows_compared"] for r in pair_results.values())
    print(f"admissible cells={len(pair_results)} rows={total_rows} "
          f"winner={sens['winner']} flips={sens['flip_count']} "
          f"unknown_dependent={sens['unknown_dependent']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
