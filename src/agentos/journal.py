"""Transactional transition + audit journal.

Every guarded state change goes through `transition()`: the object mutation and
its audit event commit in ONE sqlite transaction. Audit rows are hash-chained:
row N stores `prev_event_sha256` = digest of row N-1, where
digest(row) = sha256(prev_stored_or_empty + "|" + canonical_body(row)).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from .ids import canonical_json, sha256_text


class TransitionError(Exception):
    """A state machine precondition or authority check failed."""


class Journal:
    def __init__(self, db):
        self.db = db

    # -- digest ---------------------------------------------------------------
    @staticmethod
    def _body(goal_id: str | None, actor: str, event_type: str, payload: dict) -> str:
        return canonical_json({
            "goal_id": goal_id, "actor": actor,
            "event_type": event_type, "payload": payload,
        })

    def digest_of_row(self, row: sqlite3.Row) -> str:
        body = self._body(row["goal_id"], row["actor"], row["event_type"],
                          json.loads(row["payload_json"]))
        return sha256_text((row["prev_event_sha256"] or "") + "|" + body)

    # -- append (must be called inside an open transaction) --------------------
    def _append_event_locked(self, conn: sqlite3.Connection, goal_id: str | None,
                             actor: str, event_type: str,
                             payload: dict[str, Any]) -> str:
        last = conn.execute(
            "SELECT goal_id, actor, event_type, payload_json, prev_event_sha256"
            " FROM audit_event ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        # link = DIGEST of the previous row (not its own prev pointer)
        prev = self.digest_of_row(last) if last else None
        body = self._body(goal_id, actor, event_type, payload)
        conn.execute(
            "INSERT INTO audit_event(goal_id, actor, event_type, payload_json,"
            " prev_event_sha256) VALUES (?,?,?,?,?)",
            (goal_id, actor, event_type, canonical_json(payload), prev),
        )
        return sha256_text((prev or "") + "|" + body)

    def append_event(self, goal_id: str | None, actor: str, event_type: str,
                     payload: dict[str, Any]) -> None:
        with self.db.tx() as conn:
            self._append_event_locked(conn, goal_id, actor, event_type, payload)

    # -- guarded transition ------------------------------------------------------
    def transition(self, *, table: str, obj_id: str, field: str = "status",
                   expect_from: str | None = None, to: str | None = None,
                   actor: str = "system", authority_ok: bool | None = None,
                   extra_sets: dict[str, Any] | None = None,
                   goal_id: str | None = None,
                   event_type: str | None = None,
                   payload: dict[str, Any] | None = None,
                   transition_key: str | None = None) -> dict:
        """Atomically CAS-update a status column + append the audit event.

        Duplicate transition_key returns the originally recorded payload
        (idempotent retry of the transition itself).
        """
        if authority_ok is False:
            raise TransitionError(
                f"actor '{actor}' is not authorized for {table}:{obj_id}")

        if transition_key:
            seen = self.db.conn.execute(
                "SELECT payload_json FROM audit_event"
                " WHERE json_extract(payload_json,'$.transition_key')=?"
                " ORDER BY seq DESC LIMIT 1",
                (transition_key,),
            ).fetchone()
            if seen:
                return {"ok": True, "duplicate": True,
                        "event": json.loads(seen["payload_json"])}
        sets: list[str] = []
        vals: list[Any] = []
        if to is not None:
            sets.append(f"{field}=?")
            vals.append(to)
        for k, v in (extra_sets or {}).items():
            sets.append(f"{k}=?")
            vals.append(v)
        if not sets:
            raise ValueError("transition requires 'to' or extra_sets")

        sql = f"UPDATE {table} SET {', '.join(sets)} WHERE id=?"
        params: list[Any] = [*vals, obj_id]
        if expect_from is not None:
            sql += f" AND {field}=?"
            params.append(expect_from)

        etype = event_type or f"{table}.transition"
        body_payload = {
            "object": f"{table}:{obj_id}",
            **(payload or {}),
            **({"from": expect_from, "to": to} if to is not None else {}),
            **({"transition_key": transition_key} if transition_key else {}),
        }
        with self.db.tx() as conn:
            cur = conn.execute(sql, params)
            if cur.rowcount != 1:
                actual = conn.execute(
                    f"SELECT {field} FROM {table} WHERE id=?", (obj_id,)
                ).fetchone()
                raise TransitionError(
                    f"invalid transition on {table}:{obj_id}: expected {field}="
                    f"{expect_from!r}, found {actual[0] if actual else '<missing>'!r}"
                )
            self._append_event_locked(conn, goal_id, actor, etype, body_payload)
            row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (obj_id,)).fetchone()
        return {"ok": True, "duplicate": False, "row": dict(row)}

    # -- chain verification ------------------------------------------------------
    def full_chain_check(self) -> tuple[bool, int | None]:
        """Recompute the whole hash chain; returns (ok, first_bad_seq)."""
        prev: str | None = None
        for row in self.db.conn.execute("SELECT * FROM audit_event ORDER BY seq"):
            if row["prev_event_sha256"] != prev:
                return False, row["seq"]
            prev = self.digest_of_row(row)
        return True, None
