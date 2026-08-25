"""Controlled external-provider boundary: stdlib TCP JSON-lines stub + client.

The stub models the EXTERNAL API edge only (latency, timeouts, empty bodies,
rate limiting, disconnects, full outage). All AgentOS-side policy/capability/
audit behavior still flows through the real gateway; the stub never bypasses
it. Fault configuration is injected per scenario phase.
"""
from __future__ import annotations

import json
import random
import socket
import threading
import time


class ProviderServer:
    """Fault-injecting JSON-lines server bound to an ephemeral loopback port."""

    def __init__(self, *, seed: int = 0):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self.port = self._sock.getsockname()[1]
        self._sock.listen(64)
        self._lock = threading.Lock()
        self._rng = random.Random(seed)
        # fault knobs (mutated between phases by scenarios)
        self.mode = "ok"                # ok|full_outage|disconnect|timeout|empty_response|rate_limited|latency|mixed
        self.latency_ms = 0
        self.timeout_ms = 500
        self.rate_limit_per_sec = 1000000
        self.mix_probabilities = {}
        self.loss_fraction = 0.0
        self._window_start = time.perf_counter()
        self._served_in_window = 0
        self._accept_thread = threading.Thread(target=self._serve, daemon=True)
        self._running = True

    def start(self) -> "ProviderServer":
        self._accept_thread.start()
        return self

    def stop(self) -> None:
        self._running = False
        try:
            self._sock.close()
        except OSError:
            pass

    def set_fault(self, **knobs) -> None:
        with self._lock:
            for key, value in knobs.items():
                setattr(self, key, value)

    def _classify_current_mode(self) -> str:
        with self._lock:
            if self.mode == "mixed":
                r = self._rng.random()
                acc = 0.0
                for name, prob in self.mix_probabilities.items():
                    acc += prob
                    if r < acc:
                        return name
                return "ok"
            return self.mode

    def _serve(self) -> None:
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        try:
            mode = self._classify_current_mode()
            if mode == "full_outage":
                conn.close()
                return
            conn.settimeout(2.0)
            line = conn.makefile("r", encoding="utf-8").readline()
            if not line:
                conn.close()
                return
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                conn.close()
                return
            with self._lock:
                if self._rng.random() < self.loss_fraction:
                    conn.close()  # simulated packet loss / reset
                    return
                now = time.perf_counter()
                if now - self._window_start >= 1.0:
                    self._window_start = now
                    self._served_in_window = 0
                self._served_in_window += 1
                limited = self._served_in_window > self.rate_limit_per_sec
            if mode == "disconnect":
                conn.close()
                return
            if mode == "timeout":
                time.sleep(self.timeout_ms / 1000.0)
                conn.close()  # no response -> client-side timeout
                return
            if mode == "empty_response":
                conn.sendall(b"\n")
                conn.close()
                return
            if mode == "rate_limited" or limited:
                reply = {"id": request.get("id"), "status": "rate_limited"}
                conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))
                conn.close()
                return
            if mode == "latency":
                time.sleep(self.latency_ms / 1000.0)
            reply = {"id": request.get("id"), "status": "ok",
                     "op": request.get("op")}
            conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))
            conn.close()
        except OSError:
            try:
                conn.close()
            except OSError:
                pass


class ProviderClient:
    """Single-connection client that classifies outcomes honestly."""

    def __init__(self, port: int, *, connect_timeout_s: float = 1.0):
        self.port = port
        self.connect_timeout_s = connect_timeout_s
        self._conn: socket.socket | None = None

    def _ensure_conn(self) -> socket.socket:
        if self._conn is None:
            conn = socket.create_connection(
                ("127.0.0.1", self.port), timeout=self.connect_timeout_s)
            self._conn = conn
        return self._conn

    def call(self, op: str, request_id: str, *, timeout_s: float = 2.0) -> dict:
        started = time.perf_counter_ns()
        try:
            conn = self._ensure_conn()
            conn.settimeout(timeout_s)
            conn.sendall((json.dumps({"id": request_id, "op": op}) + "\n")
                         .encode("utf-8"))
            buffer = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    outcome = "disconnect"
                    break
                buffer += chunk
                if b"\n" in buffer:
                    line = buffer.split(b"\n")[0]
                    if not line.strip():
                        outcome = "empty_response"
                    else:
                        payload = json.loads(line.decode("utf-8"))
                        outcome = payload.get("status", "error")
                    break
        except socket.timeout:
            outcome = "timeout"
        except OSError:
            outcome = "disconnect"
        except (json.JSONDecodeError, UnicodeDecodeError):
            outcome = "error"
        finally:
            if outcome in ("timeout", "disconnect", "error", "empty_response"):
                self.close()
        latency_ns = time.perf_counter_ns() - started
        failed = outcome in ("timeout", "disconnect", "error",
                             "empty_response", "rate_limited")
        return {
            "request_id": request_id,
            "outcome": outcome,
            "failed": failed,
            "latency_ms": round(latency_ns / 1e6, 6),
        }

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass
            self._conn = None
