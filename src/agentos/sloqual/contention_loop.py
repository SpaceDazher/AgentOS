"""Subprocess SQLite write-contention generator (lock contention scenario)."""
from __future__ import annotations

import argparse
import sqlite3
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--hold-ms", type=float, default=40.0)
    parser.add_argument("--sleep-ms", type=float, default=20.0)
    parser.add_argument("--duration-s", type=float, default=30.0)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db, isolation_level=None)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("CREATE TABLE IF NOT EXISTS sloqual_contention("
                 "id INTEGER PRIMARY KEY, marker TEXT)")
    deadline = time.perf_counter() + args.duration_s
    cycles = 0
    while time.perf_counter() < deadline:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO sloqual_contention(marker) VALUES (?)",
                         (f"c{cycles}",))
            time.sleep(args.hold_ms / 1000.0)   # hold the write lock
            conn.execute("COMMIT")
        except sqlite3.Error:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        cycles += 1
        time.sleep(args.sleep_ms / 1000.0)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
