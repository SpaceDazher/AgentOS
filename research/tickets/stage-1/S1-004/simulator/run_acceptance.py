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
import os
import platform
import subprocess
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


def validate_acceptance_request(seeds: list[int], ops: int) -> None:
    """Validate the non-negotiable acceptance envelope before any work."""
    if ops <= 0:
        raise ValueError("operation series must be non-empty")
    if ops < ACCEPTANCE_OPS:
        raise ValueError(
            f"acceptance requires at least {ACCEPTANCE_OPS} operations per "
            f"seed, got {ops}")
    if len(seeds) < len(ACCEPTANCE_SEEDS):
        raise ValueError(
            f"acceptance requires at least {len(ACCEPTANCE_SEEDS)} seeds, "
            f"got {len(seeds)}")
    if len(set(seeds)) != len(seeds):
        raise ValueError("acceptance seeds must be distinct")


def validate_simulation_result(result: object, seed: int, ops: int) -> dict:
    """Validate a primary or rerun result without trusting its producer."""
    if not isinstance(result, dict):
        raise RuntimeError(f"seed {seed}: simulator output is not an object")
    if type(result.get("seed")) is not int or result.get("seed") != seed:
        raise RuntimeError(
            f"seed {seed}: reported seed is {result.get('seed')!r}")
    if (type(result.get("operations")) is not int
            or result.get("operations") != ops):
        raise RuntimeError(
            f"seed {seed}: operation count {result.get('operations')!r} != {ops}")
    counters = result.get("invariant_counters")
    if not isinstance(counters, dict):
        raise RuntimeError(f"seed {seed}: invariant counters are missing")
    missing = [inv for inv in INVARIANT_IDS if inv not in counters]
    if missing:
        raise RuntimeError(
            f"seed {seed}: incomplete invariant counters, missing {missing}")
    unexpected = sorted(set(counters) - set(INVARIANT_IDS))
    if unexpected:
        raise RuntimeError(
            f"seed {seed}: unexpected invariant counters: {unexpected}")
    violations = {
        inv: counters[inv] for inv in INVARIANT_IDS
        if type(counters[inv]) is not int or counters[inv] != 0
    }
    if violations:
        raise RuntimeError(f"seed {seed}: violations recorded: {violations}")
    digest = result.get("trace_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise RuntimeError(f"seed {seed}: invalid trace digest")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise RuntimeError(f"seed {seed}: non-hex trace digest") from exc
    op_counts = result.get("op_counts")
    if not isinstance(op_counts, dict) or not op_counts:
        raise RuntimeError(f"seed {seed}: empty operation series")
    malformed_counts = {
        name: value for name, value in op_counts.items()
        if not isinstance(name, str) or type(value) is not int or value <= 0
    }
    # Internal replay work can emit extra recorded operations during one
    # externally scheduled step, so the coverage floor is >= ops, not == ops.
    if malformed_counts or sum(op_counts.values()) < ops:
        raise RuntimeError(
            f"seed {seed}: operation counters do not cover at least {ops} "
            f"operations: malformed={malformed_counts} total="
            f"{sum(value for value in op_counts.values() if type(value) is int)}")
    return result


def run_seed(seed: int, ops: int, out_dir: Path) -> dict:
    t0 = time.time()
    sim, result = simulate(seed, ops, audit_every=AUDIT_EVERY)
    elapsed = time.time() - t0

    try:
        validate_simulation_result(result, seed, ops)
    except RuntimeError as exc:
        fail(str(exc))
    counters = result["invariant_counters"]
    violations = {inv: counters[inv] for inv in INVARIANT_IDS if counters[inv]}

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
    """Reproduce one seed in a new interpreter with a stripped environment."""
    simulator = Path(invariant_simulator.__file__).resolve()
    command = [sys.executable, str(simulator), str(seed), str(ops)]
    child_env = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR") if key in os.environ
    }
    child_env.update({"PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8"})
    proc = subprocess.run(
        command, cwd=str(simulator.parent), env=child_env,
        capture_output=True, text=True, encoding="utf-8", errors="strict",
        timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(
            f"seed {seed}: rerun subprocess exited {proc.returncode}: "
            f"{proc.stderr.strip() or '<empty stderr>'}")
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"seed {seed}: rerun emitted invalid JSON") from exc
    validate_simulation_result(result, seed, ops)
    matches = result["trace_digest"] == expected_digest
    return {
        "seed": seed,
        "operations": ops,
        "rerun_digest": result["trace_digest"],
        "expected_digest": expected_digest,
        "digest_match": matches,
        "verdict": "REPRODUCED" if matches else "DIVERGED",
        "invariant_counters": result["invariant_counters"],
        "executor": {
            "mode": "subprocess",
            "python_executable": str(Path(sys.executable).resolve()),
            "python_version": sys.version.split()[0],
            "simulator_sha256": sha256_file(simulator),
            "environment_keys": sorted(child_env),
            "exit_code": proc.returncode,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ops", type=int, default=ACCEPTANCE_OPS)
    parser.add_argument("--seeds", type=int, nargs="+",
                        default=list(ACCEPTANCE_SEEDS))
    args = parser.parse_args(argv)

    try:
        validate_acceptance_request(args.seeds, args.ops)
    except ValueError as exc:
        fail(str(exc))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    for seed in args.seeds:
        print(f"[acceptance] seed {seed}: {args.ops} operations ...",
              flush=True)
        entries.append(run_seed(seed, args.ops, out_dir))

    reruns = []
    for entry in entries:
        print(f"[rerun] seed {entry['seed']}: reproducing digest ...",
              flush=True)
        try:
            reruns.append(rerun_seed(
                entry["seed"], args.ops, entry["trace_digest"]))
        except RuntimeError as exc:
            fail(str(exc))

    diverged = [r for r in reruns if not r["digest_match"]]
    if diverged:
        fail(f"rerun diverged for seeds {[r['seed'] for r in diverged]}")

    probes = invariant_simulator.run_probes()
    failed_probes = [probe["probe"] for probe in probes if not probe["passed"]]
    if failed_probes:
        fail(f"adversarial probes failed: {failed_probes}")
    probes_path = out_dir / "probes.json"
    probes_path.write_text(
        json.dumps(probes, indent=2, sort_keys=True), encoding="utf-8")

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
        "probes": {
            "count": len(probes),
            "all_passed": True,
            "path": "probes.json",
            "sha256": sha256_file(probes_path),
        },
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
