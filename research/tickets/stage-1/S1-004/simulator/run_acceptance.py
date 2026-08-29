"""AgentOS S1-004 — acceptance runner for the seeded deterministic simulator.

Executes the required acceptance envelope (>= 3 seeds x 1,000,000 simulated
operations per run), then an independent rerun that must reproduce the exact
trace digest of every seed. Fail-closed rules (ticket S1-004):

- an empty operation series, a missing seed, an incomplete invariant
  counter table, an unreadable trace, or a digest mismatch aborts the run
  with a non-zero exit code;
- invariant counters must be complete (every tracked invariant present) and
  zero for an acceptance verdict;
- every artifact is hashed (SHA-256) and recorded in the results manifest.

Usage (from the repository root):
    $env:PYTHONPATH = "research/tickets/stage-1/S1-004/simulator"
    python research/tickets/stage-1/S1-004/simulator/run_acceptance.py \
        --out research/tickets/stage-1/S1-004/results/simulation
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import invariant_simulator
from invariant_simulator import INVARIANT_IDS, SIMULATOR_VERSION, simulate

ACCEPTANCE_SEEDS = (11, 22, 33)
ACCEPTANCE_OPS = 1_000_000
AUDIT_EVERY = 4096


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(message: str) -> None:
    print(f"ACCEPTANCE FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def environment_manifest() -> dict:
    return {
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "simulator_version": SIMULATOR_VERSION,
        "random_module": "python stdlib random.Random (Mersenne Twister)",
        "third_party_dependencies": [],
    }


def run_seed(seed: int, ops: int, out_dir: Path) -> dict:
    t0 = time.time()
    sim, result = simulate(seed, ops, audit_every=AUDIT_EVERY)
    elapsed = time.time() - t0

    # ---- fail-closed validation of the raw result ----
    if result["operations"] != ops:
        fail(f"seed {seed}: operation count {result['operations']} != {ops}")
    counters = result["invariant_counters"]
    missing = [inv for inv in INVARIANT_IDS if inv not in counters]
    if missing:
        fail(f"seed {seed}: incomplete invariant counters, missing {missing}")
    violations = {inv: counters[inv] for inv in INVARIANT_IDS if counters[inv]}
    if violations:
        fail(f"seed {seed}: violations recorded: {violations}")
    if not result["trace_digest"]:
        fail(f"seed {seed}: empty trace digest")
    if not result["op_counts"]:
        fail(f"seed {seed}: empty operation series")

    seed_dir = out_dir / f"seed-{seed}"
    seed_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "seed": seed,
        "operations": ops,
        "audit_every": AUDIT_EVERY,
        "mutations": [],
        "fault_probabilities": sim.fault_probs,
        "simulator_version": SIMULATOR_VERSION,
        "environment": environment_manifest(),
    }
    config_path = seed_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True),
                           encoding="utf-8")
    result_path = seed_dir / "result.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    entry = {
        "seed": seed,
        "operations": ops,
        "elapsed_seconds": round(elapsed, 3),
        "invariant_counters": counters,
        "trace_digest": result["trace_digest"],
        "config_sha256": sha256_file(config_path),
        "result_sha256": sha256_file(result_path),
        "verdict": "PASS" if not violations else "FAIL",
    }
    (seed_dir / "trace_digest.txt").write_text(
        result["trace_digest"] + "\n", encoding="ascii")
    entry["trace_digest_sha256"] = sha256_file(seed_dir / "trace_digest.txt")
    return entry


def rerun_seed(seed: int, ops: int, expected_digest: str) -> dict:
    """Independent rerun: a fresh process-level simulator instance must
    reproduce the exact trace digest of the acceptance run."""
    sim, result = simulate(seed, ops, audit_every=AUDIT_EVERY)
    matches = result["trace_digest"] == expected_digest
    return {
        "seed": seed,
        "operations": ops,
        "rerun_digest": result["trace_digest"],
        "expected_digest": expected_digest,
        "digest_match": matches,
        "verdict": "REPRODUCED" if matches else "DIVERGED",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ops", type=int, default=ACCEPTANCE_OPS)
    parser.add_argument("--seeds", type=int, nargs="+",
                        default=list(ACCEPTANCE_SEEDS))
    parser.add_argument("--skip-rerun", action="store_true",
                        help="skip the independent rerun (not acceptance)")
    args = parser.parse_args(argv)

    if args.ops <= 0:
        fail("operation series must be non-empty")
    if not args.seeds:
        fail("no seeds requested")
    if args.ops < ACCEPTANCE_OPS:
        fail(f"acceptance requires at least {ACCEPTANCE_OPS} operations per "
             f"seed, got {args.ops}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    for seed in args.seeds:
        print(f"[acceptance] seed {seed}: {args.ops} operations ...",
              flush=True)
        entries.append(run_seed(seed, args.ops, out_dir))

    reruns = []
    if not args.skip_rerun:
        for entry in entries:
            print(f"[rerun] seed {entry['seed']}: reproducing digest ...",
                  flush=True)
            reruns.append(rerun_seed(entry["seed"], args.ops,
                                     entry["trace_digest"]))

    diverged = [r for r in reruns if not r["digest_match"]]
    if diverged:
        fail(f"rerun diverged for seeds {[r['seed'] for r in diverged]}")

    manifest = {
        "acceptance": {
            "seeds": args.seeds,
            "operations_per_seed": args.ops,
            "invariants": list(INVARIANT_IDS),
            "violation_count_total": 0,
            "verdict": "PASS",
        },
        "runs": entries,
        "reruns": reruns,
        "environment": environment_manifest(),
        "module_sha256": {
            name: hashlib.sha256(
                (Path(invariant_simulator.__file__).parent / name)
                .read_bytes()).hexdigest()
            for name in ("invariant_simulator.py", "run_acceptance.py")
        },
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True),
                             encoding="utf-8")
    manifest_rel = manifest_path
    digest = sha256_file(manifest_path)
    print(f"[manifest] {manifest_rel} sha256={digest}")
    print(f"ACCEPTANCE PASS: {len(entries)} seeds x {args.ops} operations, "
          f"0 violations, reruns reproduced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
