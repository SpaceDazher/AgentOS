"""Durable capability ledger + gateway-compatible enforcing context.

Core AgentOS grants capabilities via the in-memory ``RunContext`` and has
durable revocation only for exact-action approvals. This module provides the
reference **durable** capability store that the qualification scenarios use to
measure revoke-to-deny latency across real OS processes:

* ``grant`` inserts a GRANTED row (durable).
* ``revoke_durable`` flips GRANTED->REVOKED and appends a revocation event in
  ONE SQLite transaction; the returned ``commit_perf_ns`` is read strictly
  after COMMIT returns (the durable commit point).
* ``LedgerRunContext.capabilities`` re-reads durable state on every access, so
  every gateway invocation observes the current durable truth (this models a
  gateway instance consulting its authorization plane per request).

This is package-level reference enforcement, not a change to core semantics.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from ..ids import new_id


def ensure_schema(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sloqual_capability_grant ("
        " grant_id TEXT PRIMARY KEY,"
        " subject TEXT NOT NULL,"
        " capability TEXT NOT NULL,"
        " status TEXT NOT NULL CHECK (status IN ('GRANTED','REVOKED')),"
        " granted_at TEXT NOT NULL,"
        " revoked_at TEXT)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sloqual_grant_subject"
        " ON sloqual_capability_grant(subject, status)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sloqual_revocation_event ("
        " seq INTEGER PRIMARY KEY AUTOINCREMENT,"
        " grant_id TEXT NOT NULL,"
        " subject TEXT NOT NULL,"
        " capability TEXT NOT NULL,"
        " committed_at TEXT NOT NULL,"
        " actor TEXT NOT NULL)")
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS sloqual_grant_no_update_unrevoked BEFORE UPDATE ON sloqual_capability_grant "
        "WHEN OLD.status='GRANTED' AND NEW.status='GRANTED' AND (OLD.capability IS NOT NEW.capability OR OLD.subject IS NOT NEW.subject) "
        "BEGIN SELECT RAISE(ABORT,'sloqual grant rows are immutable except GRANTED->REVOKED'); END")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def grant(conn, *, subject: str, capability: str, actor: str = "sloqual") -> str:
    ensure_schema(conn)
    grant_id = new_id("slogrant")
    conn.execute(
        "INSERT INTO sloqual_capability_grant"
        "(grant_id, subject, capability, status, granted_at, revoked_at)"
        " VALUES (?,?,?,'GRANTED',?,NULL)",
        (grant_id, subject, capability, _now()))
    return grant_id


def revoke_durable(conn, grant_id: str, *, actor: str = "sloqual-operator") -> dict:
    """Atomically revoke and append the durable event; returns the commit point."""
    ensure_schema(conn)
    started = time.perf_counter_ns()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "UPDATE sloqual_capability_grant SET status='REVOKED', revoked_at=?"
            " WHERE grant_id=? AND status='GRANTED'",
            (_now(), grant_id))
        if cur.rowcount != 1:
            raise ValueError(f"grant {grant_id} not in GRANTED state")
        row = conn.execute(
            "SELECT subject, capability FROM sloqual_capability_grant WHERE grant_id=?",
            (grant_id,)).fetchone()
        conn.execute(
            "INSERT INTO sloqual_revocation_event"
            "(grant_id, subject, capability, committed_at, actor) VALUES (?,?,?,?,?)",
            (grant_id, row["subject"], row["capability"], _now(), actor))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    commit_perf_ns = time.perf_counter_ns()
    return {
        "grant_id": grant_id,
        "commit_perf_ns": commit_perf_ns,
        "begin_to_commit_ms": round((commit_perf_ns - started) / 1e6, 6),
        "wall_committed_at": _now(),
    }


def durable_capabilities(conn, subject: str) -> set[str]:
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT capability FROM sloqual_capability_grant"
        " WHERE subject=? AND status='GRANTED'", (subject,))
    return {r[0] for r in rows}


def is_granted(conn, subject: str, capability: str) -> bool:
    ensure_schema(conn)
    row = conn.execute(
        "SELECT 1 FROM sloqual_capability_grant"
        " WHERE subject=? AND capability=? AND status='GRANTED' LIMIT 1",
        (subject, capability)).fetchone()
    return row is not None


class LedgerRunContext:
    """Drop-in stand-in for agentos.gateway.RunContext whose ``capabilities``
    property consults the durable ledger on EVERY access, keyed by the
    durable principal ``subject`` (not the ephemeral run id)."""

    def __init__(self, conn, *, run_id: str, goal_id: str, task_id: str,
                 lease_owner: str, workspace_path: str, subject: str,
                 fence_token: int = 0):
        self.conn = conn
        self.run_id = run_id
        self.goal_id = goal_id
        self.task_id = task_id
        self.lease_owner = lease_owner
        self.workspace_path = workspace_path
        self.subject = subject
        self.fence_token = fence_token

    @property
    def capabilities(self) -> set[str]:
        return durable_capabilities(self.conn, self.subject)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"LedgerRunContext(run_id={self.run_id!r})"


def resurrection_check(conn, grant_id: str) -> bool:
    """True when a REVOKED grant stays revoked across a fresh connection."""
    row = conn.execute(
        "SELECT status FROM sloqual_capability_grant WHERE grant_id=?",
        (grant_id,)).fetchone()
    return bool(row) and row["status"] == "REVOKED"


def as_gateway_context(context: LedgerRunContext) -> Any:
    return context
