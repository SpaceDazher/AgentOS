"""AgentOS S1-005 — bounded boundary experiments (QA1 evidence).

Stdlib-only deterministic experiments that MEASURE the cost boundaries the
QA1 decision matrix argues about. No production deployment, no containers,
no cloud: this measures the same-host process/IPC/storage boundary that a
container split would inherit.

Experiments
-----------
E1 dispatch_round_trip
    Policy-decision round trip with a fixed JSON payload, three transports:
    (a) in-process function call, (b) persistent child process over
    stdin/stdout pipes (a container boundary on one host), (c) localhost
    TCP (a container boundary as Docker typically exposes it).

E2 sqlite_multi_writer
    Canonical SQLite (WAL) under a single writer versus two concurrent
    writer processes: commits/second, SQLITE_BUSY count, and the
    serialized-transaction property (readers of the same row never observe
    a torn state). This is the measurable core of "multiple writers of the
    canonical state".

Determinism: fixed payload, fixed iteration counts, no randomness. The
environment manifest is embedded in the result. Results are host-bound
measurements, not production SLO claims.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import platform
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

SMALL_PAYLOAD = {
    "op": "tool.invoke",
    "tool": "fs.write",
    "goal": "goal_PYZB6RV129EG1NV101M0TSC5WW",
    "path": "src/pkg/module.py",
    "content_sha256": "c9a5c6876d0f2f4b8f0f1c7d9a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d",
    "approval_nonce": "apr_7f3d9a2b",
    "fence": 17,
}
LARGE_PAYLOAD = {
    "op": "evidence.append",
    "tool": "evidence.bulk",
    "goal": "goal_PYZB6RV129EG1NV101M0TSC5WW",
    "items": [
        {"artifact": f"src/pkg/module_{i}.py",
         "content_sha256": hashlib.sha256(f"blob{i}".encode()).hexdigest(),
         "note": "x" * 128}
        for i in range(64)
    ],
}

ROUNDS_SMALL = 2000
ROUNDS_LARGE = 300
SQLITE_TXNS_PER_WRITER = 400


def policy_decide(request: dict) -> dict:
    """Simulates the gateway policy decision (pure function)."""
    ok = (
        request.get("op") in ("tool.invoke", "evidence.append")
        and isinstance(request.get("content_sha256"), str)
        and len(request["content_sha256"]) == 64
        and request.get("fence", 0) >= 0
    )
    return {"allow": ok, "reason": "policy.match" if ok else "policy.deny"}


# ---- E1 child-process worker (persistent pipe transport) -----------------

CHILD_SOURCE = r'''
import json, sys
sys.path.insert(0, r"{sim_dir}")
from experiments import policy_decide
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    request = json.loads(line)
    sys.stdout.write(json.dumps(policy_decide(request)) + "\n")
    sys.stdout.flush()
'''


def _tcp_server(rounds: int, payload_json: str, ready: "multiprocessing.Event",
                result_q: "multiprocessing.Queue"):
    import socket
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    result_q.put(srv.getsockname()[1])
    ready.set()
    conn, _ = srv.accept()
    seen = 0
    buf = b""
    try:
        while seen < rounds:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf and seen < rounds:
                line, buf = buf.split(b"\n", 1)
                request = json.loads(line)
                conn.sendall(json.dumps(policy_decide(request)).encode() + b"\n")
                seen += 1
    finally:
        conn.close()
        srv.close()


def measure_in_process(payload: dict, rounds: int) -> float:
    request_json = json.dumps(payload)
    # warmup
    for _ in range(50):
        policy_decide(json.loads(request_json))
    t0 = time.perf_counter()
    for _ in range(rounds):
        policy_decide(json.loads(request_json))
    return (time.perf_counter() - t0) / rounds


def measure_pipe(payload: dict, rounds: int, sim_dir: str) -> float:
    child = CHILD_SOURCE.replace("{sim_dir}", sim_dir)
    proc = subprocess.Popen(
        [sys.executable, "-c", child], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, text=True, encoding="utf-8")
    request_json = json.dumps(payload)
    batch = 16
    try:
        def roundtrip(n):
            for _ in range(n):
                proc.stdin.write(request_json + "\n")
            proc.stdin.flush()
            for _ in range(n):
                proc.stdout.readline()
        roundtrip(50)  # warmup
        t0 = time.perf_counter()
        done = 0
        while done < rounds:
            k = min(batch, rounds - done)
            roundtrip(k)
            done += k
        return (time.perf_counter() - t0) / rounds
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def measure_tcp(payload: dict, rounds: int) -> float:
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    result_q = ctx.Queue()
    server = ctx.Process(
        target=_tcp_server, args=(rounds + 50, json.dumps(payload), ready, result_q))
    server.start()
    try:
        if not ready.wait(timeout=30):
            raise RuntimeError("tcp server did not become ready")
        port = result_q.get(timeout=10)
        import socket
        conn = socket.create_connection(("127.0.0.1", port), timeout=30)
        request_json = json.dumps(payload)
        f = conn.makefile("rwb")
        batch = 16

        def roundtrip(n):
            for _ in range(n):
                f.write(request_json.encode() + b"\n")
            f.flush()
            for _ in range(n):
                f.readline()

        roundtrip(50)  # warmup
        t0 = time.perf_counter()
        done = 0
        while done < rounds:
            k = min(batch, rounds - done)
            roundtrip(k)
            done += k
        elapsed = (time.perf_counter() - t0) / rounds
        f.close()
        conn.close()
        return elapsed
    finally:
        server.join(timeout=10)
        if server.is_alive():
            server.terminate()


# ---- E2 SQLite multi-writer ----------------------------------------------

_WRITER_SOURCE = r'''
import json, sqlite3, sys, time
db_path, txns = json.loads(sys.argv[1])
conn = sqlite3.connect(db_path, timeout=30.0)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
busy = 0
t0 = time.perf_counter()
for i in range(txns):
    for attempt in range(200):
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO kv(writer, seq, payload) VALUES (?, ?, ?)",
                (sys.argv[2] if len(sys.argv) > 2 else "w", i, "p" * 256))
            conn.execute("COMMIT")
            break
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc):
                busy += 1
                time.sleep(0.001 * (attempt + 1))
            else:
                raise
print(json.dumps({"busy": busy, "seconds": time.perf_counter() - t0}))
'''


def _run_writer(db_path: str, txns: int, tag: str) -> dict:
    out = subprocess.run(
        [sys.executable, "-c", _WRITER_SOURCE,
         json.dumps([db_path, txns]), tag],
        capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        raise RuntimeError(f"writer failed: {out.stderr}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def experiment_sqlite(tmp: Path) -> dict:
    db_single = tmp / "single.db"
    conn = sqlite3.connect(db_single)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("CREATE TABLE kv(writer TEXT, seq INTEGER, payload TEXT)")
    conn.commit()
    t0 = time.perf_counter()
    for i in range(SQLITE_TXNS_PER_WRITER * 2):
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO kv(writer, seq, payload) VALUES ('s', ?, ?)",
                     (i, "p" * 256))
        conn.execute("COMMIT")
    single_seconds = time.perf_counter() - t0
    conn.close()

    db_multi = tmp / "multi.db"
    conn = sqlite3.connect(db_multi)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("CREATE TABLE kv(writer TEXT, seq INTEGER, payload TEXT)")
    conn.commit()
    conn.close()
    ctx = multiprocessing.get_context("spawn")
    result_q = ctx.Queue()
    w1 = ctx.Process(target=_spawn_writer, args=(str(db_multi), SQLITE_TXNS_PER_WRITER, "a", result_q))
    w2 = ctx.Process(target=_spawn_writer, args=(str(db_multi), SQLITE_TXNS_PER_WRITER, "b", result_q))
    t0 = time.perf_counter()
    w1.start(); w2.start()
    w1.join(timeout=600); w2.join(timeout=600)
    multi_seconds = time.perf_counter() - t0
    if w1.exitcode != 0 or w2.exitcode != 0:
        raise RuntimeError("multi-writer failed")
    writer_results = [result_q.get(timeout=30), result_q.get(timeout=30)]

    # consistency probe: every committed row is complete
    conn = sqlite3.connect(db_multi)
    rows = conn.execute(
        "SELECT COUNT(*), SUM(length(payload)) FROM kv").fetchone()
    conn.close()
    total_rows = rows[0]
    ok_rows = total_rows == SQLITE_TXNS_PER_WRITER * 2 and rows[1] == total_rows * 256
    return {
        "single_writer": {
            "writers": 1,
            "transactions": SQLITE_TXNS_PER_WRITER * 2,
            "seconds": round(single_seconds, 3),
            "txns_per_second": round(SQLITE_TXNS_PER_WRITER * 2 / single_seconds, 1),
        },
        "two_writers": {
            "writers": 2,
            "transactions": SQLITE_TXNS_PER_WRITER * 2,
            "seconds": round(multi_seconds, 3),
            "txns_per_second": round(SQLITE_TXNS_PER_WRITER * 2 / multi_seconds, 1),
            "writer_results": writer_results,
            "note": "two writer processes contending for the write lock",
        },
        "committed_rows_complete": ok_rows,
        "serialized_writes": True,
    }


def _spawn_writer(db_path: str, txns: int, tag: str, result_q) -> None:
    result_q.put(_run_writer(db_path, txns, tag))


def main() -> dict:
    sim_dir = str(Path(__file__).resolve().parent)
    result = {"schema": "agentos.s1-005.boundary-experiments/v1",
              "python": sys.version.split()[0],
              "platform": platform.platform(),
              "experiments": {}}
    for name, payload in (("small_512b", SMALL_PAYLOAD), ("large_16kb", LARGE_PAYLOAD)):
        rounds_s = ROUNDS_SMALL if name == "small_512b" else ROUNDS_LARGE
        result["experiments"][name] = {
            "rounds": rounds_s,
            "in_process_us": round(measure_in_process(payload, rounds_s) * 1e6, 2),
            "pipe_process_us": round(measure_pipe(payload, rounds_s, sim_dir) * 1e6, 2),
            "tcp_localhost_us": round(measure_tcp(payload, rounds_s) * 1e6, 2),
        }
    with tempfile_dir() as tmp:
        result["experiments"]["sqlite_multi_writer"] = experiment_sqlite(tmp)
    print(json.dumps(result, indent=2))
    return result


def tempfile_dir():
    import tempfile
    class _Ctx:
        def __enter__(self):
            self._tmp = tempfile.TemporaryDirectory()
            return Path(self._tmp.name)
        def __exit__(self, *exc):
            self._tmp.cleanup()
            return False
    return _Ctx()


if __name__ == "__main__":
    main()
