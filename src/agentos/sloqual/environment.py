"""Environment manifest capture for SLO qualification.

Best-effort, secret-free system description. Every probe failure is recorded
explicitly as `"unavailable"` instead of being silently omitted, so the
fail-closed comparator can demand a complete profile.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RUNNER_VERSION = "2.1.0"

_SECRET_MARKERS = ("token", "secret", "password", "api_key", "apikey")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_probe(command: list[str], timeout_s: float = 5.0) -> str:
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout_s, check=False)
        output = (completed.stdout or "").strip()
        return output.splitlines()[0][:200] if output else "unavailable"
    except Exception as exc:  # noqa: BLE001 - probe boundary
        return f"unavailable ({type(exc).__name__})"


def _ram_total_bytes() -> int | str:
    try:
        if sys.platform == "win32":
            import ctypes

            class _Memory(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = _Memory()
            status.dwLength = ctypes.sizeof(_Memory)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return int(status.ullTotalPhys)
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except Exception:  # noqa: BLE001
        pass
    return "unavailable"


def _volume_info(path: Path) -> dict:
    info: dict = {"filesystem": "unverified", "storage_class": "unverified",
                  "drive": "unknown"}
    try:
        root = Path(path.anchor)
        info["drive"] = str(root)
        free, total = shutil.disk_usage(root).free, shutil.disk_usage(root).total
        info["total_bytes"] = total
        info["free_bytes"] = free
        if sys.platform == "win32":
            import ctypes

            buf = ctypes.create_unicode_buffer(261)
            fs_buf = ctypes.create_unicode_buffer(65)
            flags = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(str(root)), buf, len(buf), None, None,
                ctypes.byref(flags), fs_buf, len(fs_buf))
            if ok:
                info["filesystem"] = fs_buf.value or "unknown"
        else:
            info["filesystem"] = os.statvfs(str(root)) and "unverified-posix"
        info["storage_class"] = "unverified"  # no admin-grade probe available
    except Exception as exc:  # noqa: BLE001
        info["error"] = type(exc).__name__
    return info


def sqlite_profile(db_path: Path | None) -> dict:
    profile: dict = {
        "sqlite_version": sqlite3.sqlite_version,
        "journal_mode": "unavailable",
        "synchronous": "unavailable",
        "busy_timeout_ms": "unavailable",
        "page_size": "unavailable",
        "page_count": "unavailable",
    }
    if db_path is None or not db_path.exists():
        profile["note"] = "no database file captured"
        return profile
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            profile["journal_mode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
            profile["synchronous"] = conn.execute("PRAGMA synchronous").fetchone()[0]
            profile["busy_timeout_ms"] = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            profile["page_size"] = conn.execute("PRAGMA page_size").fetchone()[0]
            profile["page_count"] = conn.execute("PRAGMA page_count").fetchone()[0]
            wal = Path(str(db_path) + "-wal")
            profile["wal_bytes"] = wal.stat().st_size if wal.exists() else 0
            counts = {}
            for table in ("goal", "task", "run", "activity", "audit_event"):
                try:
                    counts[table] = conn.execute(
                        f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
                except sqlite3.Error:
                    counts[table] = "absent"
            profile["row_counts"] = counts
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        profile["error"] = type(exc).__name__
    return profile


def capture(
    *,
    repo_root: Path,
    work_root: Path,
    db_path: Path | None = None,
    topology: dict | None = None,
    input_files: list[Path] | None = None,
    capacity_mapping: dict | None = None,
) -> dict:
    """Build the environment-manifest payload. Never includes secrets."""
    manifest: dict = {
        "schema": "agentos.environment-manifest/v1",
        "runner_version": RUNNER_VERSION,
        "captured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "capture_monotonic_ns": time.perf_counter_ns(),
        "os": {
            "platform": platform.platform(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable_hash_policy": "path omitted by design",
        },
        "cpu": {
            "processor": platform.processor() or "unavailable",
            "logical_count": os.cpu_count(),
            "architecture": platform.machine(),
        },
        "ram_total_bytes": _ram_total_bytes(),
        "disk": _volume_info(work_root),
        "power_plan": _run_probe(["powercfg", "/getactivescheme"]),
        "time_sync": {
            "w32tm_status": _run_probe(["w32tm", "/query", "/status"]),
            "clock_policy": "all latency SLIs use time.perf_counter_ns (monotonic); wall timestamps informational only",
        },
        "background_load": {
            "method": "not measured automatically; operator statement required",
            "operator_statement": "single-operator workstation during qualification runs",
        },
        "dependencies": {
            "policy": "core AgentOS stdlib-only; harness adds none",
            "third_party": [],
        },
        "git_commit_sha": _run_probe(["git", "-C", str(repo_root), "rev-parse", "HEAD"]),
        "sqlite": sqlite_profile(db_path),
        "process_topology": topology or {},
        "payload_distributions": {
            "reference": "scenario-manifest.json#workload_engine",
            "allow_deny_mix": "seeded 90/10 (S1-002 compatible)",
        },
        "external_apis": {
            "provider_stub": "stdlib TCP JSON-lines stub on 127.0.0.1; fault modes per scenario-manifest.json#provider_stub",
            "real_external_calls": "none during qualification",
        },
        "network_topology": "single host, loopback TCP for provider boundary, shared SQLite file for durability plane",
        "sanitized_configuration": {
            "constraints": "benchmark constraints only; secrets are never present in manifests, traces or reports",
        },
        "input_file_hashes": {},
        "production_like_proof": {
            "required": True,
            "capacity_mapping": capacity_mapping or {},
            "rule_ref": "slo-contract.json#production_like_profile.qualification_rule",
        },
    }
    for path in input_files or []:
        manifest["input_file_hashes"][Path(path).name] = sha256_file(path)
    # Defense-in-depth: refuse to emit a manifest whose KEY NAMES look like
    # credential fields (free-text values may legitimately discuss policy).
    def _walk_keys(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                lowered_key = str(key).lower()
                for marker in _SECRET_MARKERS:
                    if marker in lowered_key:
                        raise ValueError(
                            f"environment manifest would embed credential-like key '{key}'")
                _walk_keys(value)
        elif isinstance(node, list):
            for item in node:
                _walk_keys(item)

    _walk_keys(manifest)
    return manifest


def write_manifest(manifest: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True,
                                   ensure_ascii=False) + "\n", encoding="utf-8")
    return out_path


def manifest_hash(manifest: dict) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
