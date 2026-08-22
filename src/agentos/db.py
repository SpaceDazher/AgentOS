"""SQLite persistence: connection factory + migration runner (clean-DB safe)."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "agentos" / "migrations"


def _default_db_path() -> Path:
    root = Path(os.environ.get("AGENTOS_HOME", Path.home() / ".agentos"))
    return root / "agentos.db"


class Database:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else _default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    # -- transaction helper -------------------------------------------------
    def tx(self) -> sqlite3.Connection:
        """Returns the connection inside an explicit transaction context."""
        return _Tx(self.conn)

    # -- migrations ----------------------------------------------------------
    def migrate(self) -> list[str]:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        applied = {r["name"] for r in self.conn.execute("SELECT name FROM schema_migrations")}
        done = []
        mig_dir = Path(__file__).resolve().parent / "migrations"
        for path in sorted(mig_dir.glob("*.sql")):
            if path.name in applied:
                continue
            # executescript() manages its own transaction; do not wrap in tx().
            self.conn.executescript(path.read_text(encoding="utf-8"))
            self.conn.execute(
                "INSERT INTO schema_migrations(name) VALUES (?)", (path.name,))
            done.append(path.name)
        return done


class _Tx:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")
        return False


def open_db(path: str | os.PathLike | None = None) -> Database:
    return Database(path)
