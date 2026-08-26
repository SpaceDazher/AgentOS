"""CLI orchestrator for SLOQUAL-001 (freeze -> env -> run -> compare -> report)."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import RUNNER_VERSION
from . import compare as cmp_mod
from . import report as rep_mod
from .contract import freeze_contract, verify_frozen
from .environment import capture, manifest_hash, write_manifest
from .scenarios import SCENARIO_REGISTRY

MANDATORY = ("cold_start", "warm_steady_state", "sustained_load", "soak",
             "burst", "queue_backpressure", "provider_full_outage",
             "provider_degraded", "worker_restart", "scheduler_restart",
             "full_restart", "sqlite_lock_contention", "disk_slow_saturation",
             "db_growth", "network_faults", "revocation_under_load",
             "recovery_after_failures")


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_freeze(args) -> int:
    stamped = freeze_contract(Path(args.ticket) / "slo-contract.json")
    print(json.dumps({"frozen": True, "self_hash_sha256": stamped}))
    return 0


def cmd_env_manifest(args) -> int:
    ticket = Path(args.ticket)
    _, contract_hash = verify_frozen(ticket / "slo-contract.json")
    def _as_obj(value):
        if isinstance(value, dict):
            return value
        return json.loads(value) if value else {}

    manifest = capture(
        repo_root=Path(args.repo_root), work_root=Path(args.work_root),
        db_path=Path(args.db) if args.db else None,
        topology=_as_obj(args.topology),
        input_files=[ticket / "slo-contract.json",
                     ticket / "scenario-manifest.json"],
        capacity_mapping=_as_obj(args.capacity_mapping))
    manifest["contract_sha256"] = contract_hash
    out = Path(args.out) if args.out else (
        Path(args.work_root) / "environment-manifest.json")
    write_manifest(manifest, out)
    print(json.dumps({"out": str(out), "environment_hash": manifest_hash(manifest)}))
    return 0


def cmd_run_scenario(args) -> int:
    scenario_id = args.scenario
    if scenario_id not in SCENARIO_REGISTRY:
        print(f"unknown scenario {scenario_id}", file=sys.stderr)
        return 2
    ticket = Path(args.ticket)
    contract, contract_hash = verify_frozen(ticket / "slo-contract.json")
    overrides = dict(kv.split("=", 1) for kv in args.override or [])
    overrides = {k: float(v) for k, v in overrides.items()}
    cfg_seed = args.seed
    work_root = Path(args.work_root) / args.run_id / scenario_id
    started_wall = _utc()
    started_ns = time.perf_counter_ns()
    from .scenarios import ScenarioConfig

    cfg = ScenarioConfig(work_root=Path(args.work_root) / args.run_id,
                         seeds=[cfg_seed], overrides=overrides,
                         repo_src=Path(args.repo_src))
    result = SCENARIO_REGISTRY[scenario_id](cfg, cfg_seed)
    # Persist scenario-local deny-pool failures in the root invariant record
    # as well as their detailed phase/window bucket.
    false_acceptances = cmp_mod._metric_counter_total(
        result.get("metrics", {}), "false_acceptance_count")
    if false_acceptances:
        invariants = result.setdefault("invariants", {})
        invariants["false_acceptance_count"] = max(
            false_acceptances,
            int(invariants.get("false_acceptance_count") or 0))
    ended_ns = time.perf_counter_ns()
    # Bind every result to the recorded environment: hash + exact commit
    # travel INSIDE the seed file (review finding: unrecorded hashes let a
    # mixed-version series look comparable).
    env_hash = None
    manifest_path = (Path(args.work_root) / args.run_id /
                     "environment-manifest.json")
    if not manifest_path.exists():
        manifest_path = Path(args.work_root) / "environment-manifest.json"
    if manifest_path.exists():
        try:
            from .environment import manifest_hash as _mh
            env_hash = _mh(json.loads(
                manifest_path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            env_hash = None
    commit_sha = None
    try:
        commit_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=str(Path(args.repo_src).parent), timeout=10,
            encoding="utf-8", errors="replace").stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        commit_sha = None
    payload = {
        "schema": "agentos.sloqual-result/v1",
        "runner_version": RUNNER_VERSION,
        "run_id": args.run_id,
        "scenario_id": scenario_id,
        "scenario_manifest_version": "1.0.0",
        "seed": cfg_seed,
        "contract_sha256": contract_hash,
        "environment_hash": env_hash,
        "commit_sha": commit_sha,
        "started_at_utc": started_wall,
        "ended_at_utc": _utc(),
        "elapsed_seconds": round((ended_ns - started_ns) / 1e9, 6),
        "result": result,
    }
    out_dir = Path(args.work_root) / args.run_id / scenario_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"seed-{cfg_seed}.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True,
                              ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "ok": True}))
    return 0


def cmd_compare(args) -> int:
    result = cmp_mod.compare(Path(args.ticket), args.run_ids,
                             work_root=Path(args.work_root),
                             repo_src=Path(args.repo_src))
    out = Path(args.ticket) / "reports" / "compare-result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True,
                              ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": result["verdict"],
                      "failures": len(result["fail_conditions"]),
                      "limits": len(result["limits"]), "out": str(out)}))
    return 0 if result["verdict"] != "FAIL" else 1


def cmd_report(args) -> int:
    md = rep_mod.generate_markdown(Path(args.ticket))
    out = Path(args.ticket) / "reports" / "REPORT.md"
    out.write_text(md, encoding="utf-8")
    print(json.dumps({"out": str(out)}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentos.sloqual.runner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("freeze-contract")
    p.add_argument("--ticket", required=True)
    p.set_defaults(func=cmd_freeze)

    p = sub.add_parser("env-manifest")
    p.add_argument("--ticket", required=True)
    p.add_argument("--repo-root", required=True)
    p.add_argument("--work-root", required=True)
    p.add_argument("--db")
    p.add_argument("--topology")
    p.add_argument("--capacity-mapping")
    p.add_argument("--out")
    p.set_defaults(func=cmd_env_manifest)

    p = sub.add_parser("run-scenario")
    p.add_argument("--ticket", required=True)
    p.add_argument("--repo-src", required=True)
    p.add_argument("--work-root", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--scenario", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--override", action="append")
    p.set_defaults(func=cmd_run_scenario)

    p = sub.add_parser("compare")
    p.add_argument("--ticket", required=True)
    p.add_argument("--work-root", required=True)
    p.add_argument("--repo-src", required=True)
    p.add_argument("--run-ids", nargs="+", required=True)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("report")
    p.add_argument("--ticket", required=True)
    p.set_defaults(func=cmd_report)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
