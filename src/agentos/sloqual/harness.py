"""Scenario runtime: wires the REAL AgentOS engine/gateway/journal to the
qualification ledger, plus invariant sweep helpers used after every fault.

Nothing here modifies core behavior; the gateway/engine are used exactly as
the reference implementation exposes them.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agentos.db import open_db
from agentos.engine import Engine
from agentos.gateway import CapabilityDenied, ToolContract, ToolGateway
from agentos.journal import Journal

from .revocation import LedgerRunContext, ensure_schema, grant

READ_CAPABILITY = "resource.read"
WRITE_CAPABILITY = "resource.write"


class ProfilingConnection:
    """Transparent wrapper timing every execute() for DB/audit SLIs.

    Classification: statements touching `audit_event` count as audit-journal
    latency; other write statements count toward DB transaction latency.
    Read-only SELECTs are excluded from both (documented in the contract).
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self.audit_execute_ns = 0
        self.db_write_execute_ns = 0
        self.audit_executes = 0
        self.db_write_executes = 0
        self.audit_samples_ms: list[float] = []
        self.db_write_samples_ms: list[float] = []
        self.sample_cap = 200000
        row_factory = getattr(conn, "row_factory", None)
        if row_factory is not None:
            self.row_factory = row_factory

    @property
    def conn(self) -> sqlite3.Connection:  # escape hatch for raw needs
        return self._conn

    def execute(self, sql: str, *args):
        started = time.perf_counter_ns()
        result = self._conn.execute(sql, *args)
        elapsed = time.perf_counter_ns() - started
        lowered = sql.lstrip().lower()
        if lowered.startswith(("select", "pragma", "explain")):
            return result
        if "audit_event" in lowered or "audit_anchor" in lowered:
            self.audit_execute_ns += elapsed
            self.audit_executes += 1
            if len(self.audit_samples_ms) < self.sample_cap:
                self.audit_samples_ms.append(elapsed / 1e6)
        else:
            self.db_write_execute_ns += elapsed
            self.db_write_executes += 1
            if len(self.db_write_samples_ms) < self.sample_cap:
                self.db_write_samples_ms.append(elapsed / 1e6)
        return result

    def __getattr__(self, name):  # delegate the rest
        return getattr(self._conn, name)


@dataclass
class RuntimeHandle:
    root: Path
    db_path: Path
    db: object
    engine: Engine
    journal: Journal
    gateway: ToolGateway
    goal_id: str
    task_id: str
    base_ctx: object
    profiling: ProfilingConnection
    provider_client: object | None = None
    extra_run_ids: list[str] = field(default_factory=list)
    # Single-process SQLite model: gateway invocations are serialized exactly
    # like the reference monolith; cross-process concurrency is provided by
    # the subprocess scenarios against the shared durable DB.
    invoke_lock: threading.RLock = field(default_factory=threading.RLock)

    def close(self) -> None:
        try:
            self.profiling.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        try:
            self.db.conn.close()
        except sqlite3.Error:
            pass


def _authorize_handler(**kwargs) -> dict:
    return {"allowed": True, "resource": kwargs.get("resource", ""),
            "action": kwargs.get("action", "")}


def _provider_call_handler_factory(client) -> callable:
    def handler(**kwargs) -> dict:
        outcome = client.call("echo", kwargs.get("request_id", "n/a"))
        if outcome["failed"]:
            raise RuntimeError(f"provider outcome={outcome['outcome']}")
        return {"provider": outcome["outcome"],
                "latency_ms": outcome["latency_ms"]}
    return handler


def _worklog_append_handler(line_id: str, _sink: str | None = None,
                            _fence: int | None = None, **_) -> dict:
    target = Path(_sink or ".") / "worklog.log"
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(f"{line_id}\n")
    return {"appended": line_id}


def build_runtime(root: Path, *, lease_minutes: float = 30.0,
                  provider_client=None) -> RuntimeHandle:
    """Create a fresh durable runtime (goal/spec/task/run) + contracts."""
    root.mkdir(parents=True, exist_ok=True)
    db = open_db(root / "qual.db")          # runs core migrations
    db.conn.close()
    raw_conn = sqlite3.connect(str(db.path), isolation_level=None,
                               check_same_thread=False)
    raw_conn.row_factory = sqlite3.Row       # core expects mapping rows
    profiled = ProfilingConnection(raw_conn)
    profiled.execute("PRAGMA journal_mode=WAL")
    profiled.execute("PRAGMA foreign_keys=ON")
    db.conn = profiled                       # Database keeps tx()/path semantics
    ensure_schema(db.conn)

    engine = Engine(db, root)
    journal = Journal(db)
    gateway = ToolGateway(db, journal)
    goal_id = engine.create_goal(
        "SLOQUAL-001 production-like qualification workload",
        constraints={"qualification": "sloqual-001", "network": "loopback-stub-only"},
    )
    engine.refine_spec(
        goal_id,
        "Measure control-plane SLIs against the real gateway path.",
        criteria=[{"criterion_id": "qualification_recorded",
                   "kind": "tests_present"}],
    )
    engine.activate_goal(goal_id)
    engine.plan_tasks(goal_id, [{
        "key": "qual-workload",
        "title": "Qualification workload",
        "definition_of_done": "Raw timed observations are persisted.",
    }])
    engine.schedule_ready_tasks(goal_id)
    task_id = db.conn.execute(
        "SELECT id FROM task WHERE goal_id=? AND status='READY'",
        (goal_id,)).fetchone()[0]
    _, base_ctx = engine.open_run(task_id, lease_minutes=lease_minutes)

    contracts = [
        ToolContract(
            name="qual.authorize", version="1.0.0",
            input_schema={
                "type": "object",
                "properties": {"resource": {"type": "string"},
                               "action": {"type": "string"}},
                "required": ["resource", "action"],
                "additionalProperties": False},
            output_schema={"type": "object"},
            required_capability=READ_CAPABILITY, effect_class="read",
            idempotency="none", handler=_authorize_handler),
        ToolContract(
            name="qual.worklog_append", version="1.0.0",
            input_schema={
                "type": "object",
                "properties": {"line_id": {"type": "string"}},
                "required": ["line_id"], "additionalProperties": False},
            output_schema={"type": "object"},
            required_capability=WRITE_CAPABILITY, effect_class="write_local",
            idempotency="keyed", handler=_worklog_append_handler),
    ]
    if provider_client is not None:
        contracts.append(ToolContract(
            name="qual.provider_call", version="1.0.0",
            input_schema={
                "type": "object",
                "properties": {"request_id": {"type": "string"}},
                "required": ["request_id"], "additionalProperties": False},
            output_schema={"type": "object"},
            required_capability=READ_CAPABILITY, effect_class="read",
            idempotency="none",
            handler=_provider_call_handler_factory(provider_client)))
    for contract in contracts:
        gateway.register(contract)
    return RuntimeHandle(
        root=root, db_path=db.path, db=db, engine=engine, journal=journal,
        gateway=gateway, goal_id=goal_id, task_id=task_id, base_ctx=base_ctx,
        profiling=db.conn)


def ledger_subject_context(handle: RuntimeHandle, *, subject: str,
                           run_id: str | None = None,
                           lease_owner: str | None = None) -> LedgerRunContext:
    """Context whose capability set = durable grants for `subject`."""
    return LedgerRunContext(
        handle.db.conn,
        run_id=run_id or handle.base_ctx.run_id,
        goal_id=handle.goal_id,
        task_id=handle.task_id,
        lease_owner=lease_owner or handle.base_ctx.lease_owner,
        workspace_path=handle.base_ctx.workspace_path,
        subject=subject)


def journal_chain_ok(conn) -> tuple[bool, int | None]:
    """End-to-end audit chain verification for an arbitrary open connection."""
    return Journal(type("ChainDB", (), {"conn": conn})()).full_chain_check()


_SECRET_MARKERS = (
    "BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE KEY", "sk-", "api_key=",
    "password=", "Authorization: Bearer ", "ghp_", "AKIA")


def _parse_ts(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def sweep_invariants(conn, paths=()) -> dict:
    """Static post-failure invariant sweep over one durable DB.

    Every contract-mandatory counter receives a REAL measured value: the
    comparator treats missing or negative sentinels as violations, so this
    function never returns -1 placeholders.

    Fixture goal ids shipped by core migrations (present in every fresh
    database, CANCELLED without audit events by design) are excluded."""
    findings: dict = {
        "audit_chain_violations_count": 0,
        "first_bad_seq": None,
        "lost_terminal_transitions_count": 0,
        "false_acceptance_count": 0,
        "unresolved_unknown_outcomes_count": 0,
        "stale_lease_executions_count": 0,
        "capability_scope_violations_count": 0,
        "side_effect_duplication_count": 0,
        "confirmed_data_loss_count": 0,
        "secrets_in_artifacts_count": 0,
    }
    shim = type("ChainDB", (), {"conn": conn})()
    ok, bad_seq = Journal(shim).full_chain_check()
    if not ok:
        findings["audit_chain_violations_count"] = 1
        findings["first_bad_seq"] = bad_seq
    # terminal transitions must have their audit events
    rows = conn.execute(
        "SELECT g.id, g.status FROM goal g WHERE g.status IN"
        " ('ACCEPTED','REJECTED','CANCELLED') AND g.id NOT IN"
        " ('goal_MIGRATED','goal_MIGRATION_QUARANTINE')").fetchall()
    for row in rows:
        event = {"ACCEPTED": "goal.accepted", "REJECTED": "goal.rejected",
                 "CANCELLED": "goal.cancelled"}[row["status"]]
        hit = conn.execute(
            "SELECT 1 FROM audit_event WHERE goal_id=? AND event_type=? LIMIT 1",
            (row["id"], event)).fetchone()
        if not hit:
            findings["lost_terminal_transitions_count"] += 1
        if row["status"] == "ACCEPTED":
            passed = conn.execute(
                "SELECT count(*) FROM evaluation WHERE goal_id=? AND result='pass'",
                (row["id"],)).fetchone()[0]
            if passed == 0:
                findings["false_acceptance_count"] += 1
    unresolved = conn.execute(
        "SELECT count(*) FROM activity WHERE status IN"
        " ('UNKNOWN_OUTCOME','EXECUTING')").fetchone()[0]
    findings["unresolved_unknown_outcomes_count"] = unresolved

    # stale-lease executions: a SUCCEEDED write-class op stamped after its
    # run's persisted lease expiry. Timestamps are parsed, never compared as
    # strings (writer second-precision vs activity millisecond precision).
    expiry_cache: dict[str, datetime | None] = {}
    for row in conn.execute(
            "SELECT a.created_at AS ts, r.id AS rid, r.lease_expires_at AS exp"
            " FROM activity a JOIN run r ON r.id = a.run_id"
            " WHERE a.status='SUCCEEDED' AND a.effect_class='write'"):
        if row["rid"] not in expiry_cache:
            expiry_cache[row["rid"]] = _parse_ts(row["exp"])
        exp = expiry_cache[row["rid"]]
        ts = _parse_ts(row["ts"])
        if exp is not None and ts is not None and ts > exp:
            findings["stale_lease_executions_count"] += 1
    # capability/scope: succeeded write-class ops with no durable grant for
    # their lease-owner subject covering the operation time.
    for row in conn.execute(
            "SELECT a.run_id AS rid, a.created_at AS ts,"
            " r.lease_owner AS owner FROM activity a"
            " JOIN run r ON r.id = a.run_id"
            " WHERE a.status='SUCCEEDED' AND a.effect_class='write'"):
        grant_row = conn.execute(
            "SELECT 1 FROM sloqual_capability_grant g"
            " WHERE g.subject=? AND g.status='GRANTED' AND g.granted_at <= ?"
            " LIMIT 1", (row["owner"], row["ts"])).fetchone()
        revoke_row = conn.execute(
            "SELECT 1 FROM sloqual_revocation_event e WHERE e.subject=?"
            " AND e.revoked_at <= ? LIMIT 1",
            (row["owner"], row["ts"])).fetchone()
        if grant_row is None and revoke_row is None:
            # no ledger coverage at all: only acceptable when the DB has no
            # ledger tables (pure-core scenarios); counted otherwise.
            has_ledger = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name="
                "'sloqual_capability_grant'").fetchone()
            if has_ledger:
                findings["capability_scope_violations_count"] += 1
    # side-effect duplication: same op+args executed successfully more than
    # once within a run (idempotency key must have made it REPLAYED).
    dup_rows = conn.execute(
        "SELECT count(*) FROM (SELECT run_id, op_name, args_canonical_json"
        " FROM activity WHERE status='SUCCEEDED' AND effect_class='write'"
        " GROUP BY run_id, op_name, args_canonical_json HAVING count(*) > 1)"
    ).fetchone()[0]
    findings["side_effect_duplication_count"] = dup_rows
    # confirmed data loss: runs marked COMPLETED whose task left non-DONE.
    lost = conn.execute(
        "SELECT count(*) FROM run r JOIN task t ON t.id=r.task_id"
        " WHERE r.status='COMPLETED' AND t.status NOT IN ('DONE','CANCELLED')"
    ).fetchone()[0]
    findings["confirmed_data_loss_count"] = lost
    # secrets in artifacts on disk next to this database.
    for path in paths:
        base = Path(path)
        if not base.exists():
            continue
        files = ([base] if base.is_file() else
                 [p for p in base.rglob("*") if p.is_file()])
        for artifact in files:
            if artifact.suffix.lower() in (".db", ".wal", ".shm"):
                continue
            try:
                text = artifact.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            low = text.lower()
            findings["secrets_in_artifacts_count"] += sum(
                1 for marker in _SECRET_MARKERS
                if marker.lower() in low)
    return findings
