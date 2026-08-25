"""Subprocess gateway worker: invokes the real ToolGateway path against the
shared durable DB, streaming one JSONL observation per invocation.

Used by restart scenarios and the S1-008 revocation gate so that revoke-to-
deny latency is measured across real OS processes. Timing fields:
`t_ns` = time.perf_counter_ns (monotonic, QPC-backed on Windows and
CLOCK_MONOTONIC on Linux — comparable across processes on the same host),
`wall_ns` = time.time_ns cross-check.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--goal-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--lease-owner", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--duration-s", type=float, default=60.0)
    parser.add_argument("--poll-ms", type=float, default=25.0)
    parser.add_argument("--out", required=True)
    parser.add_argument("--op", choices=["authorize"], default="authorize")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from agentos.db import open_db  # noqa: E402
    from agentos.gateway import CapabilityDenied, ToolContract, ToolGateway  # noqa: E402
    from agentos.journal import Journal  # noqa: E402
    from agentos.sloqual.harness import _authorize_handler  # noqa: E402
    from agentos.sloqual.revocation import LedgerRunContext  # noqa: E402

    db = open_db(args.db)
    journal = Journal(db)
    gateway = ToolGateway(db, journal)

    def handler(**kwargs):
        return _authorize_handler(**kwargs)

    contract = ToolContract(
        name="qual.authorize", version="1.0.0",
        input_schema={
            "type": "object",
            "properties": {"resource": {"type": "string"},
                           "action": {"type": "string"}},
            "required": ["resource", "action"],
            "additionalProperties": False},
        output_schema={"type": "object"},
        required_capability="resource.read", effect_class="read",
        idempotency="none", handler=handler)
    gateway.register(contract)
    ctx = LedgerRunContext(
        db.conn, run_id=args.run_id, goal_id=args.goal_id,
        task_id=args.task_id, lease_owner=args.lease_owner,
        workspace_path=args.workspace, subject=args.subject)
    resolved = gateway.resolve("qual.authorize", "1.0.0")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.perf_counter() + args.duration_s
    counter = 0
    with open(out_path, "a", encoding="utf-8") as handle:
        while time.perf_counter() < deadline:
            started = time.perf_counter_ns()
            outcome = "ERROR"
            try:
                result = gateway.invoke(
                    ctx, resolved,
                    {"resource": "workspace/demo", "action": "read"})
                outcome = str(result.get("status", "ERROR"))
            except CapabilityDenied:
                outcome = "DENIED"
            except Exception as exc:  # noqa: BLE001 - scenario boundary
                outcome = f"ERROR:{type(exc).__name__}"
            handle.write(json.dumps({
                "t_ns": started, "wall_ns": time.time_ns(),
                "outcome": outcome, "seq": counter}) + "\n")
            handle.flush()
            counter += 1
            time.sleep(args.poll_ms / 1000.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
