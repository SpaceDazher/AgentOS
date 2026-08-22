"""Fence-aware sink handlers (P1 tail): file-system effects that validate the
fence token against per-sink monotonic state BEFORE touching the world.

A sink is identified by the workspace root. Each accepted mutating call bumps
`fence_sink_state.last_accepted_fence`; a handler receiving a token <= the
stored value raises StaleFenceError — the classic stale-writer protection,
enforced at the SINK rather than only in gateway pre-checks.
"""
from __future__ import annotations

from pathlib import Path

from .gateway import GatewayError


class StaleFenceError(GatewayError):
    """Sink rejected the fence token as stale (a newer writer already won)."""


def _bump_and_check(db, sink: str, fence: int) -> None:
    """Atomically: reject stale token, else advance the sink's counter."""
    with db.tx() as conn:
        row = conn.execute(
            "SELECT last_accepted_fence FROM fence_sink_state WHERE sink=?",
            (sink,)).fetchone()
        last = int(row["last_accepted_fence"]) if row else 0
        if fence <= last:
            raise StaleFenceError(
                f"sink '{sink}' rejected stale fence {fence} "
                f"(last accepted: {last})")
        conn.execute(
            "INSERT INTO fence_sink_state(sink, last_accepted_fence)"
            " VALUES (?,?) ON CONFLICT(sink) DO UPDATE SET"
            " last_accepted_fence=excluded.last_accepted_fence,"
            " updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
            (sink, fence))


def make_fs_write_handler(db):
    """Build an fs.write handler bound to a database for fence validation.

    Handler kwargs: path, content, and optionally _fence + _sink injected by
    the engine/gateway from the activity record. When _fence is absent
    (legacy callers/tests), the write proceeds without sink validation —
    the gateway-side lease check remains the only guard.
    """

    def fs_write(path: str, content: str,
                 _fence: int | None = None, _sink: str | None = None) -> dict:
        if _fence is not None:
            _bump_and_check(db, _sink or str(Path(path).anchor or "default"),
                            int(_fence))
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"written": str(p), "bytes": len(content),
                **({"fence": int(_fence)} if _fence is not None else {})}

    return fs_write
