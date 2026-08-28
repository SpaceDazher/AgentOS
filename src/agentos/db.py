"""SQLite persistence: connection factory + migration runner (clean-DB safe)."""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "agentos" / "migrations"


def _apply_migration(conn: sqlite3.Connection, name: str, sql: str) -> None:
    """Apply one migration and its marker as a single SQLite transaction."""
    quoted_name = name.replace("'", "''")
    script = (
        "BEGIN IMMEDIATE;\n"
        + sql
        + "\nINSERT INTO schema_migrations(name) VALUES ('"
        + quoted_name
        + "');\nCOMMIT;\n"
    )
    try:
        conn.executescript(script)
    except Exception:
        # executescript leaves the explicit transaction open when a statement
        # fails.  Roll back DDL, data writes, and the marker together.
        conn.rollback()
        raise


def _repair_interrupted_0010(
        conn: sqlite3.Connection, applied: set[str]) -> None:
    """Normalize a pre-marker partial 0010 so the shipped migration can retry.

    The historical runner was not atomic.  If it stopped after creating
    ``stage_gate_new`` (possibly after dropping ``stage_gate``), re-running
    0010 would fail at CREATE TABLE and permanently wedge startup.  Preserve
    every common decision field, deliberately discard authority bindings, and
    let 0010 recreate them as empty/stale evidence.
    """
    if "0010_review_r7.sql" in applied:
        return
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    if "stage_gate_new" not in tables:
        return

    common = (
        "id", "stage", "required_eval_ids_json", "decision", "rationale",
        "authority", "goal_id", "created_at",
    )
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DROP TABLE IF EXISTS stage_gate_recovered_r9")
        conn.execute("""
            CREATE TABLE stage_gate_recovered_r9 (
              id TEXT PRIMARY KEY,
              stage TEXT NOT NULL,
              required_eval_ids_json TEXT NOT NULL,
              decision TEXT NOT NULL CHECK (decision IN ('pass','fail')),
              rationale TEXT NOT NULL,
              authority TEXT NOT NULL DEFAULT 'GateAuthority',
              goal_id TEXT,
              created_at TEXT NOT NULL DEFAULT
                (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
        """)
        for source in ("stage_gate", "stage_gate_new"):
            if source not in tables:
                continue
            columns = {row[1] for row in conn.execute(
                f"PRAGMA table_info({source})")}
            missing = set(common) - columns
            if missing:
                raise RuntimeError(
                    f"cannot recover partial 0010: {source} lacks"
                    f" columns {sorted(missing)}")
            names = ", ".join(common)
            conn.execute(
                f"INSERT OR IGNORE INTO stage_gate_recovered_r9({names})"
                f" SELECT {names} FROM {source}")
        conn.execute("DROP TRIGGER IF EXISTS stage_gate_no_update")
        conn.execute("DROP TRIGGER IF EXISTS stage_gate_no_delete")
        conn.execute("DROP INDEX IF EXISTS idx_stage_gate_goal")
        if "stage_gate_new" in tables:
            conn.execute("DROP TABLE stage_gate_new")
        if "stage_gate" in tables:
            conn.execute("DROP TABLE stage_gate")
        conn.execute(
            "ALTER TABLE stage_gate_recovered_r9 RENAME TO stage_gate")
        conn.execute("COMMIT")
    except Exception:
        conn.rollback()
        raise


def _default_db_path() -> Path:
    root = Path(os.environ.get("AGENTOS_HOME", Path.home() / ".agentos"))
    return root / "agentos.db"


_RESEARCH_TICKET_RE = re.compile(
    r"^(S\d+-\d+)(?=$|[^A-Za-z0-9])", re.IGNORECASE)


def _research_ticket_key(topic: str) -> str | None:
    match = _RESEARCH_TICKET_RE.match(str(topic).strip())
    return match.group(1).upper() if match else None


def _backfill_research_series(conn: sqlite3.Connection) -> None:
    """Attach legacy campaigns after an additive series migration.

    Kept in the runner rather than the migration SQL so a database prepared
    without the optional research tables can still apply 0014 before 0013.
    Existing immutable rows are never updated or removed.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"research_campaign", "research_series"}.issubset(tables):
            conn.execute("COMMIT")
            return

        # Select the complete legacy input set while holding the write lock.
        # This prevents a concurrent opener from observing a partially planned
        # lineage or inserting another unbound campaign between read and write.
        rows = conn.execute(
            "SELECT c.id, c.goal_id, c.topic, c.manifest_sha256, c.created_at"
            " FROM research_campaign c"
            " LEFT JOIN research_series rs ON rs.campaign_id=c.id"
            " WHERE rs.campaign_id IS NULL ORDER BY c.created_at, c.id").fetchall()
        next_revision: dict[str, int] = {}
        prior_campaign: dict[str, str | None] = {}
        planned: list[tuple[sqlite3.Row, str, int, str | None]] = []
        for row in rows:
            key = _research_ticket_key(row["topic"])
            if key is None:
                # Campaign IDs are canonical primary keys, so this fallback is
                # collision-safe for legacy rows without a ticket prefix.
                key = "legacy:" + row["id"]
                revision = 1
                supersedes = None
            else:
                if key not in next_revision:
                    existing = conn.execute(
                        "SELECT revision, campaign_id FROM research_series"
                        " WHERE research_key=? ORDER BY revision DESC LIMIT 1",
                        (key,)).fetchone()
                    next_revision[key] = int(existing["revision"]) if existing else 0
                    prior_campaign[key] = (existing["campaign_id"]
                                           if existing else None)
                next_revision[key] += 1
                revision = next_revision[key]
                supersedes = prior_campaign[key]
                prior_campaign[key] = row["id"]
            planned.append((row, key, revision, supersedes))

        for row, key, revision, supersedes in planned:
            conn.execute(
                # Plain INSERT is intentional: a uniqueness/FK collision is
                # migration corruption and must abort rather than silently
                # leaving a campaign without its required series binding.
                "INSERT INTO research_series"
                "(id, research_key, revision, campaign_id, goal_id, topic,"
                " manifest_sha256, supersedes_campaign_id) VALUES (?,?,?,?,?,?,?,?)",
                ("rseries-legacy-" + row["id"], key, revision, row["id"],
                 row["goal_id"], row["topic"], row["manifest_sha256"],
                 supersedes),
            )
        remaining = conn.execute(
            "SELECT COUNT(*) FROM research_campaign c"
            " LEFT JOIN research_series rs ON rs.campaign_id=c.id"
            " WHERE rs.campaign_id IS NULL").fetchone()[0]
        if remaining:
            raise RuntimeError(
                f"research series backfill incomplete: {remaining} campaigns")
        conn.execute("COMMIT")
    except Exception:
        conn.rollback()
        raise


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
        _repair_interrupted_0010(self.conn, applied)
        done = []
        mig_dir = Path(__file__).resolve().parent / "migrations"
        for path in sorted(mig_dir.glob("*.sql")):
            if path.name in applied:
                continue
            _apply_migration(
                self.conn, path.name, path.read_text(encoding="utf-8"))
            done.append(path.name)
        _backfill_research_series(self.conn)
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
