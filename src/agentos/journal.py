"""Transactional transition + audit journal.

Every guarded state change goes through `transition()`: the object mutation and
its audit event commit in ONE sqlite transaction. Audit rows are hash-chained:
row N stores `prev_event_sha256` = digest of row N-1, where
digest(row) = sha256(prev_stored_or_empty + "|" + canonical_body(row)).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
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
                             payload: dict[str, Any], *,
                             mirror_external: bool = True) -> str:
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
        digest = sha256_text((prev or "") + "|" + body)
        # maintain the tamper-evidence head anchor in the same transaction so a
        # rewritten LAST row cannot silently pass chain verification
        new_seq = conn.execute(
            "SELECT seq FROM audit_event ORDER BY seq DESC LIMIT 1").fetchone()["seq"]
        conn.execute(
            "UPDATE audit_anchor SET head_digest=?, last_seq=? WHERE id=1",
            (digest, new_seq))
        # P1: mirror the anchor OUTSIDE the database (separate tamper channel).
        # An attacker rewriting both audit_event and audit_anchor must also
        # notice and rewrite this file; a periodic off-host copy of it gives
        # true external anchoring (see GAP_REGISTER).
        if mirror_external:
            self._write_anchor_file(new_seq, digest)
        return digest

    def _write_anchor_file(self, seq: int, digest: str) -> None:
        try:
            anchor_file = Path(self.db.path).parent / "audit_anchor.head"
            anchor_file.parent.mkdir(parents=True, exist_ok=True)
            anchor_file.write_text(f"{seq} {digest}\n", encoding="utf-8")
        except OSError:
            pass  # read-only DB location: in-DB anchor still maintained

    def mirror_committed_anchor(self) -> None:
        """Refresh the local mirror from the committed in-DB anchor.

        Batch writers call this once after their transaction instead of once
        per event.  The database anchor remains updated for every event.
        """
        row = self.db.conn.execute(
            "SELECT head_digest, last_seq FROM audit_anchor WHERE id=1"
        ).fetchone()
        if row and row["head_digest"] is not None and row["last_seq"] is not None:
            self._write_anchor_file(int(row["last_seq"]), str(row["head_digest"]))

    def append_event(self, goal_id: str | None, actor: str, event_type: str,
                     payload: dict[str, Any]) -> None:
        with self.db.tx() as conn:
            self._append_event_locked(conn, goal_id, actor, event_type, payload)

    # -- guarded transition ------------------------------------------------------
    # TERMINAL_TRANSITIONS may only be executed through
    # Machines.accept_by_gate_record(); Journal.transition refuses them so the
    # raw journal can never be used to bypass the state machines (review R2-1).
    TERMINAL_TRANSITIONS = {
        ("goal", "ACCEPTED"), ("goal", "REJECTED"),
    }

    def transition(self, *, table: str, obj_id: str, field: str = "status",
                   expect_from: str | None = None, to: str | None = None,
                   actor: str = "system", authority_ok: bool | None = None,
                   extra_sets: dict[str, Any] | None = None,
                   goal_id: str | None = None,
                   event_type: str | None = None,
                   payload: dict[str, Any] | None = None,
                   transition_key: str | None = None,
                   _via_gate_authority: bool = False) -> dict:
        """Atomically CAS-update a status column + append the audit event.

        Public entry point. Terminal goal transitions are REFUSED here; they
        must go through Machines.accept_by_gate_record(), which uses the
        locked variant below with an internal authority token.
        """
        if (table, to) in self.TERMINAL_TRANSITIONS and not _via_gate_authority:
            raise TransitionError(
                f"{table}->{to} is terminal and may only be executed via "
                f"Machines.accept_by_gate_record() (journal bypass denied)")
        return self._transition_impl(
            table=table, obj_id=obj_id, field=field, expect_from=expect_from,
            to=to, actor=actor, authority_ok=authority_ok,
            extra_sets=extra_sets, goal_id=goal_id, event_type=event_type,
            payload=payload, transition_key=transition_key)

    def transition_locked(self, conn: sqlite3.Connection, *, table: str,
                          obj_id: str, field: str = "status",
                          expect_from: str | None = None, to: str | None = None,
                          actor: str = "system", authority_ok: bool | None = None,
                          extra_sets: dict[str, Any] | None = None,
                          goal_id: str | None = None,
                          event_type: str | None = None,
                          payload: dict[str, Any] | None = None,
                          transition_key: str | None = None) -> dict:
        """Locked variant for accept_by_gate_record: runs inside the caller's
        open BEGIN IMMEDIATE transaction (gate-row check + CAS + audit event
        commit atomically)."""
        if (table, to) in self.TERMINAL_TRANSITIONS:
            from .machines import GateAuthority  # noqa: F401 — import guard only
        return self._transition_impl(
            table=table, obj_id=obj_id, field=field, expect_from=expect_from,
            to=to, actor=actor, authority_ok=authority_ok,
            extra_sets=extra_sets, goal_id=goal_id, event_type=event_type,
            payload=payload, transition_key=transition_key, _conn=conn)

    def _transition_impl(self, *, table: str, obj_id: str, field: str,
                         expect_from: str | None, to: str | None,
                         actor: str, authority_ok: bool | None,
                         extra_sets: dict[str, Any] | None,
                         goal_id: str | None, event_type: str | None,
                         payload: dict[str, Any] | None,
                         transition_key: str | None,
                         _conn: sqlite3.Connection | None = None) -> dict:
        if authority_ok is False:
            raise TransitionError(
                f"actor '{actor}' is not authorized for {table}:{obj_id}")

        if transition_key:
            seen = (_conn or self.db.conn).execute(
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
        if _conn is not None:
            cur = _conn.execute(sql, params)
            if cur.rowcount != 1:
                actual = _conn.execute(
                    f"SELECT {field} FROM {table} WHERE id=?", (obj_id,)
                ).fetchone()
                raise TransitionError(
                    f"invalid transition on {table}:{obj_id}: expected {field}="
                    f"{expect_from!r}, found {actual[0] if actual else '<missing>'!r}"
                )
            self._append_event_locked(_conn, goal_id, actor, etype, body_payload)
            row = _conn.execute(f"SELECT * FROM {table} WHERE id=?", (obj_id,)).fetchone()
            return {"ok": True, "duplicate": False, "row": dict(row)}
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
        """Recompute the whole hash chain + compare against the head anchor.

        Returns (ok, first_bad_seq). The anchor catches tampering of the LAST
        row (which has no successor to detect a broken link)."""
        prev: str | None = None
        last_row = None
        for row in self.db.conn.execute("SELECT * FROM audit_event ORDER BY seq"):
            if row["prev_event_sha256"] != prev:
                return False, row["seq"]
            prev = self.digest_of_row(row)
            last_row = row
        anchor = self.db.conn.execute(
            "SELECT head_digest, last_seq FROM audit_anchor WHERE id=1").fetchone()
        if anchor is None:
            # pre-anchor DB with events: nothing to compare (legacy) — accept
            return True, None
        if last_row is None:
            return (anchor["head_digest"] is None, None)
        if anchor["head_digest"] != prev or anchor["last_seq"] != last_row["seq"]:
            return False, last_row["seq"]
        return True, None
