"""Deterministic order/metadata sensitivity check for the closure decision."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import random
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent


def _load_evaluator():
    spec = importlib.util.spec_from_file_location("s1020_sensitivity_evaluator", HERE / "evaluator.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run() -> dict:
    evaluator = _load_evaluator()
    base = evaluator.baseline_state()
    baseline = evaluator.closure_decision(base)["status"]
    outcomes = []
    for seed in range(256):
        state = json.loads(json.dumps(base))
        rng = random.Random(seed)
        dep_items = list(state["dependency_status"].items())
        probe_items = list(state["prior_probe_pass"].items())
        rng.shuffle(dep_items); rng.shuffle(probe_items)
        state["dependency_status"] = dict(sorted(dep_items))
        state["prior_probe_pass"] = dict(sorted(probe_items))
        state["generated_at"] = f"ignored-metadata-{rng.randrange(1_000_000)}"
        observed = evaluator.closure_decision(state)["status"]
        outcomes.append({"seed": seed, "status": observed, "stable": observed == baseline})
    payload = {"schema": "agentos.s1-020.sensitivity/v1", "runs": len(outcomes),
               "baseline": baseline, "winner_flips": sum(not r["stable"] for r in outcomes),
               "all_stable": all(r["stable"] for r in outcomes), "outcomes": outcomes,
               "wall_clock_is_decision_input": False}
    payload["sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                                   separators=(",", ":")).encode()).hexdigest()
    return payload


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8",
                        newline="\n")
    print(json.dumps({"runs": result["runs"], "winner_flips": result["winner_flips"]}))
    raise SystemExit(0 if result["all_stable"] else 2)
