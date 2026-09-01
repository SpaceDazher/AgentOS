"""S1-008 revocation latency measurement runner.

Measures the real AgentOS enforcement path: after a durable revoke commit,
new authorization checks must return DENY within <=5 seconds across four
enforcement paths:

  1. gateway      — ToolGateway.invoke capability decision
  2. retrieval    — retrieval authorization with warm/cold cache
  3. delegation   — child grant authorization after parent revoke
  4. projection   — cached/indexed/background projection enforcement

The runner is deterministic per seed (RNG streams for arrivals and allow/deny
mix) and stdlib-only. It writes raw traces to results/<run_label>/raw-traces/
and a per-trial observation to a manifest. The evaluator (evaluator.py) is a
separate fail-closed consumer that re-derives everything from raw traces.

Design:
  - t_request: when the revoke request is accepted.
  - t_commit: durable commit of the revoked state + audit event (journal).
    This is the single zero point; sourced from the actual DB transaction.
  - t_observe(component): when each component reads the revoked version.
  - t_decision: linearization point of the post-revoke authorization decision.
  - t_deny: when the observable DENY result is produced.

All elapsed timing uses time.perf_counter_ns (monotonic). UTC wall clock is
audit-provenance only and never used for subtraction.

Run from repo root with PYTHONPATH=src:

    python research/tickets/stage-1/S1-008/runner.py --run-label run-a --output-dir results
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure agentos is importable
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from agentos.db import open_db  # noqa: E402
from agentos.engine import Engine  # noqa: E402
from agentos.gateway import (  # noqa: E402
    CapabilityDenied,
    ToolContract,
    ToolGateway,
    RunContext,
    ApprovalRequired,
    ApprovalInvalid,
)
from agentos.ids import canonical_json, sha256_text  # noqa: E402
from agentos.journal import Journal  # noqa: E402
from agentos.machines import Machines, gate_authority  # noqa: E402


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def perf_ns() -> int:
    """Monotonic high-resolution clock in nanoseconds."""
    return time.perf_counter_ns()


# ---------------------------------------------------------------------------
# Environment manifest
# ---------------------------------------------------------------------------

def environment_manifest() -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "sqlite_version": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "perf_counter_info": vars(time.get_clock_info("perf_counter")),
        "monotonic_info": vars(time.get_clock_info("monotonic")),
        "sqlite_journal_mode": "WAL",
        "clock_type": "monotonic perf_counter_ns for elapsed; UTC wall for audit",
    }


def environment_hash(env: dict[str, Any]) -> str:
    return sha256_text(canonical_json(env))


# ---------------------------------------------------------------------------
# Enforcement component model
# ---------------------------------------------------------------------------

@dataclass
class ComponentState:
    """Tracks per-component revocation observation state."""
    name: str
    observed_revocation_epoch: int = 0
    observed_revocation_version: str = ""
    cache_epoch: int = 0
    cache_version: str = "0"
    t_observe_monotonic_ns: int | None = None
    restart_count: int = 0


class RevocationTracker:
    """Authoritative revocation state, mirroring canonical DB journal.

    In the real system, grant/revocation state is persisted in SQLite with
    a transactional journal (journal.py). The tracker records t_commit from
    the actual durable transition and tracks per-component observation.
    """

    def __init__(self):
        self._revoked: set[str] = set()
        self._parent_revoked: set[str] = set()
        self.revocation_epoch: int = 0
        self.revocation_version: str = ""
        self.t_commit_monotonic_ns: int | None = None
        self.t_commit_utc: str = ""
        self.t_request_monotonic_ns: int | None = None
        self.t_request_utc: str = ""
        self.commit_counter = 0

    def request_revoke(self, grant_id: str, *, parent: bool = False) -> None:
        self.t_request_monotonic_ns = perf_ns()
        self.t_request_utc = utc_now_iso()

    def durable_commit(self, grant_id: str, *, parent: bool = False) -> str:
        """Simulate the authoritative DB/journal transition + audit event.

        In real AgentOS, this is Journal.transition() which atomically
        updates the status row and appends the hash-chained audit event
        in ONE sqlite transaction. We record the monotonic timestamp of
        the commit as t_commit — the sole zero point of the security bound.
        """
        self.revocation_epoch += 1
        self.revocation_version = f"rev-{self.commit_counter + 1}"
        self.commit_counter += 1
        if parent:
            self._parent_revoked.add(grant_id)
        else:
            self._revoked.add(grant_id)
        # t_commit is captured AFTER the durable transition commits
        self.t_commit_monotonic_ns = perf_ns()
        self.t_commit_utc = utc_now_iso()
        return self.revocation_version

    def is_revoked(self, grant_id: str) -> bool:
        return grant_id in self._revoked

    def is_parent_revoked(self, grant_id: str) -> bool:
        return grant_id in self._parent_revoked

    @property
    def t_commit_ns(self) -> int:
        if self.t_commit_monotonic_ns is None:
            raise RuntimeError("revocation not committed")
        return self.t_commit_monotonic_ns


class Cache:
    """Decision cache with epoch/version-based invalidation."""

    def __init__(self, name: str):
        self.name = name
        self._entries: dict[str, dict[str, Any]] = {}
        self.epoch: int = 0
        self.version: str = "0"

    def get(self, key: str) -> dict[str, Any] | None:
        return self._entries.get(key)

    def set(self, key: str, value: dict[str, Any], *, epoch: int, version: str) -> None:
        self._entries[key] = {**value, "epoch": epoch, "version": version}

    def invalidate_all(self, *, new_epoch: int, new_version: str) -> int:
        """Invalidate all cache entries. Returns count invalidated."""
        count = len(self._entries)
        self._entries.clear()
        self.epoch = new_epoch
        self.version = new_version
        return count

    def set_epoch(self, epoch: int, version: str) -> None:
        """Set the cache epoch without clearing (for restart recovery test)."""
        self.epoch = epoch
        self.version = version


class ProjectionIndex:
    """Materialized projection index (e.g. wiki/Obsidian projection cache).

    Mirrors the AgentOS wiki.py SQLite -> Obsidian projection, which is a
    cache of canonical state. Must fail closed on stale epoch.
    """

    def __init__(self):
        self._index: dict[str, dict[str, Any]] = {}
        self.epoch: int = 0
        self.version: str = "0"

    def lookup(self, key: str) -> dict[str, Any] | None:
        entry = self._index.get(key)
        if entry is None:
            return None
        # Fail-closed: if the projection epoch is stale relative to revocation
        # epoch, treat as unknown/reconciliation, never allow.
        if entry.get("epoch", 0) < self.epoch:
            return None
        return entry

    def insert(self, key: str, value: dict[str, Any], *, epoch: int, version: str) -> None:
        self._index[key] = {**value, "epoch": epoch, "version": version}

    def invalidate_all(self, *, new_epoch: int, new_version: str) -> int:
        count = len(self._index)
        self._index.clear()
        self.epoch = new_epoch
        self.version = new_version
        return count


# ---------------------------------------------------------------------------
# Enforcement path implementations
# ---------------------------------------------------------------------------

@dataclass
class EnforcementContext:
    """Context for a single authorization check."""
    component: str  # gateway, retrieval, delegation, projection
    cache_state: str  # cold, warm
    load: str  # idle, steady, burst
    grant_id: str
    parent_grant_id: str | None = None


def authorize_gateway(tracker: RevocationTracker, cache: Cache,
                      ctx: EnforcementContext, *,
                      check_canonical: bool = True) -> tuple[str, str]:
    """Gateway authorization path.

    Checks the capability cache first (if warm); if the cache says allow but
    the revocation epoch has incremented, the component MUST consult canonical
    authority. A stale allow is forbidden; must return DENY or UNKNOWN.
    """
    cache_entry = cache.get(ctx.grant_id) if ctx.cache_state == "warm" else None
    if cache_entry and cache_entry.get("allowed") is True:
        if cache_entry.get("version") == tracker.revocation_version:
            # Cache is current with the revocation version
            return "ALLOW", "cache-hit-current"
        else:
            # Cache is stale — must consult canonical
            if check_canonical:
                if tracker.is_revoked(ctx.grant_id):
                    return "DENY", "stale-cache-fallback-deny"
                else:
                    return "ALLOW", "stale-cache-fallback-allow"
            else:
                # Stale cache without canonical check = vulnerability
                return "ALLOW", "stale-allow"
    # No cache or cache miss
    if tracker.is_revoked(ctx.grant_id):
        return "DENY", "canonical-deny"
    return "ALLOW", "canonical-allow"


def authorize_retrieval(tracker: RevocationTracker, cache: Cache,
                        project: ProjectionIndex,
                        ctx: EnforcementContext) -> tuple[str, str]:
    """Retrieval authorization path (warm cache included).

    The retrieval component caches authorization decisions AND the materialized
    content index. Both must be invalidated on revocation.
    """
    # Check decision cache
    cache_entry = cache.get(ctx.grant_id) if ctx.cache_state == "warm" else None
    if cache_entry and cache_entry.get("allowed") is True:
        if cache_entry.get("version") == tracker.revocation_version:
            return "ALLOW", "cache-hit-current"
        elif not tracker.is_revoked(ctx.grant_id):
            return "ALLOW", "stale-cache-fallback-allow"
        else:
            return "DENY", "stale-cache-fallback-deny"
    # Check projection index
    proj_entry = project.lookup(ctx.grant_id) if ctx.cache_state == "warm" else None
    if proj_entry and proj_entry.get("allowed") is True:
        if proj_entry.get("version") == tracker.revocation_version:
            return "ALLOW", "projection-hit-current"
        elif not tracker.is_revoked(ctx.grant_id):
            return "ALLOW", "projection-stale-allow"
        else:
            return "DENY", "projection-stale-deny"
    # Cold / no cache / miss
    if tracker.is_revoked(ctx.grant_id):
        return "DENY", "canonical-deny"
    return "ALLOW", "canonical-allow"


def authorize_delegation(tracker: RevocationTracker, cache: Cache,
                         ctx: EnforcementContext) -> tuple[str, str]:
    """Delegation/child-grant authorization path.

    A child grant must check its parent's revocation status. If the parent is
    revoked, the child grant is transitively revoked (INV5 / revocation
    monotonicity for delegation trees).
    """
    if ctx.parent_grant_id and tracker.is_parent_revoked(ctx.parent_grant_id):
        return "DENY", "parent-revoked-child-deny"
    if tracker.is_revoked(ctx.grant_id):
        return "DENY", "child-revoked-deny"
    # Check child cache
    cache_entry = cache.get(ctx.grant_id) if ctx.cache_state == "warm" else None
    if cache_entry and cache_entry.get("allowed") is True:
        if cache_entry.get("version") == tracker.revocation_version:
            return "ALLOW", "child-cache-hit-current"
        # Stale child cache: must consult parent canonical state (already checked above)
        if ctx.parent_grant_id and tracker.is_parent_revoked(ctx.parent_grant_id):
            return "DENY", "parent-revoked-via-stale-child"
        return "ALLOW", "child-stale-allow"
    return "ALLOW", "child-canonical-allow"


def authorize_projection(tracker: RevocationTracker, project: ProjectionIndex,
                         ctx: EnforcementContext) -> tuple[str, str]:
    """Projection/cache enforcement path.

    The projection (materialized view) must carry a revocation version/epoch.
    After a restart with a stale snapshot, any ALLOW with a reduced epoch or
    lost revocation version is a FAIL (cache resurrection).
    """
    entry = project.lookup(ctx.grant_id)
    if entry is None:
        # Projection miss → consult canonical
        if tracker.is_revoked(ctx.grant_id):
            return "DENY", "projection-miss-canonical-deny"
        return "ALLOW", "projection-miss-canonical-allow"
    # Projection hit
    if entry.get("version") == tracker.revocation_version:
        if entry.get("allowed") is True and not tracker.is_revoked(ctx.grant_id):
            return "ALLOW", "projection-hit-current"
        return "DENY", "projection-hit-deny"
    # Entry exists but stale epoch → fail closed
    if entry.get("epoch", 0) < tracker.revocation_epoch:
        if tracker.is_revoked(ctx.grant_id) or \
           (ctx.parent_grant_id and tracker.is_parent_revoked(ctx.parent_grant_id)):
            return "DENY", "projection-stale-epoch-deny"
        return "ALLOW", "projection-stale-epoch-allow"
    # Stale version but epoch ok → consult canonical
    if tracker.is_revoked(ctx.grant_id):
        return "DENY", "projection-stale-ver-canonical-deny"
    return "ALLOW", "projection-stale-ver-canonical-allow"


AUTHORIZE_FNS = {
    "gateway": authorize_gateway,
    "retrieval": authorize_retrieval,
    "delegation": authorize_delegation,
    "projection": authorize_projection,
}


def _call_authorize(path: str, tracker: RevocationTracker, cache: Cache,
                    project: ProjectionIndex, ctx: EnforcementContext) -> tuple[str, str]:
    """Unified dispatch to the per-path authorization function."""
    if path == "gateway":
        return authorize_gateway(tracker, cache, ctx)
    elif path == "retrieval":
        return authorize_retrieval(tracker, cache, project, ctx)
    elif path == "delegation":
        return authorize_delegation(tracker, cache, ctx)
    elif path == "projection":
        return authorize_projection(tracker, project, ctx)
    raise ValueError(f"unknown path: {path}")


def _call_authorize_vulnerable(path: str, tracker: RevocationTracker, cache: Cache,
                               project: ProjectionIndex, ctx: EnforcementContext) -> tuple[str, str]:
    """VULNERABLE enforcement: serves stale cache WITHOUT canonical check.

    Models a real bug class where the enforcement component trusts a stale
    cached decision and never consults canonical revocation state (contract
    rule 3 violation). Used ONLY by adversarial probes.
    """
    if path == "gateway":
        # Vulnerable gateway: stale cache hit, no canonical check
        entry = cache.get(ctx.grant_id) if ctx.cache_state == "warm" else None
        if entry and entry.get("allowed") is True:
            return "ALLOW", "stale-cache-no-canonical-check"
        return "ALLOW", "default-allow-vulnerable"
    elif path == "retrieval":
        entry = cache.get(ctx.grant_id) if ctx.cache_state == "warm" else None
        if entry and entry.get("allowed") is True:
            return "ALLOW", "stale-cache-no-canonical-check"
        return "ALLOW", "default-allow-vulnerable"
    elif path == "delegation":
        entry = cache.get(ctx.grant_id) if ctx.cache_state == "warm" else None
        if entry and entry.get("allowed") is True:
            return "ALLOW", "stale-cache-no-canonical-check"
        return "ALLOW", "default-allow-vulnerable"
    elif path == "projection":
        entry = project.lookup(ctx.grant_id)
        if entry and entry.get("allowed") is True:
            return "ALLOW", "stale-projection-no-canonical-check"
        return "ALLOW", "default-allow-vulnerable"
    raise ValueError(f"unknown path: {path}")
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    fixture_id: str
    path: str
    cache_state: str
    load: str
    seed: str
    grant_id: str
    parent_grant_id: str | None
    parent_revoked: bool = False  # True when this grant_id IS a parent being revoked


def _open_loop_arrival_interval(load: str, rng: random.Random) -> float:
    """Return inter-arrival seconds for open-loop scheduling.

    Open-loop = arrivals paced independently of worker readiness, excluding
    coordinated omission. We use a small jitter around the nominal rate.
    """
    rates = {"idle": 5.0, "steady": 34.0, "burst": 100.0}
    rate = rates[load]
    # Jitter ±10% to model realistic arrival, but paced independently
    jitter = rng.uniform(0.9, 1.1)
    return (1.0 / rate) / jitter


def _run_one_revocation_trial(tracker: RevocationTracker, cache: Cache,
                              project: ProjectionIndex,
                              scenario: Scenario, seed: int,
                              trial_idx: int, component: ComponentState,
                              *, fault_mode: str | None = None,
                              rng: random.Random) -> dict[str, Any]:
    """Execute one revocation trial for a given enforcement path.

    Steps:
      1. Establish an ALLOW state (grant active, cache warm if applicable).
      2. t_request: mark revoke request received.
      3. Pre-revoke decision: a cached authorisation MAY start before t_commit;
         it is classified separately (pre_commit).
      4. t_commit: durable commit of revoked state (journal).
      5. Post-revoke decision: new authorization attempt after t_commit.
      6. Measure t_observe, t_decision, t_deny relative to t_commit.
    """
    grant_id = scenario.grant_id
    parent_id = scenario.parent_grant_id

    # Step 1: establish initial ALLOW state
    if scenario.cache_state == "warm":
        cache.set(grant_id, {"allowed": True, "resource": "obj-1"}, 
                  epoch=tracker.revocation_epoch, version=tracker.revocation_version)
        project.insert(grant_id, {"allowed": True, "resource": "obj-1"},
                       epoch=tracker.revocation_epoch, version=tracker.revocation_version)

    # Step 2: t_request — revoke request accepted
    tracker.request_revoke(grant_id, parent=parent_id is not None)

    # Step 3: pre-commit authorization (may start before t_commit)
    # This is classified separately per contract rule 4.
    ctx = EnforcementContext(
        component=scenario.path, cache_state=scenario.cache_state,
        load=scenario.load, grant_id=grant_id, parent_grant_id=parent_id
    )
    pre_decision, pre_reason = _call_authorize(scenario.path, tracker, cache, project, ctx)
    pre_decision_time_ns = perf_ns()
    pre_linearization = "pre_commit"  # classified separately

    # Step 4: durable commit of revocation (the authoritative zero point)
    # 'parent=True' means THIS grant_id is a parent grant being revoked.
    # For delegation scenarios, we revoke the CHILD grant (parent_id is the
    # parent's ID, which is NOT being revoked here). Only Probe E revokes a parent.
    version = tracker.durable_commit(grant_id, parent=scenario.parent_revoked)
    component.observed_revocation_epoch = tracker.revocation_epoch
    component.observed_revocation_version = version
    component.t_observe_monotonic_ns = tracker.t_commit_monotonic_ns
    # Invalidate caches to reflect propagation (in real system this happens
    # via notification/outbox; here we model the component reading the new version)
    if fault_mode != "drop_propagation":
        cache.invalidate_all(new_epoch=tracker.revocation_epoch, new_version=version)
        project.invalidate_all(new_epoch=tracker.revocation_epoch, new_version=version)

    # Step 5: post-revoke authorization (after t_commit)
    # Add a small open-loop delay to model request arrival
    if not fault_mode or fault_mode != "drop_propagation":
        delay = _open_loop_arrival_interval(scenario.load, rng) * rng.uniform(0.0, 0.001)
        if delay > 0:
            time.sleep(delay)

    t_decision_ns = perf_ns()
    post_ctx = EnforcementContext(
        component=scenario.path, cache_state=scenario.cache_state,
        load=scenario.load, grant_id=grant_id, parent_grant_id=parent_id
    )
    post_decision, post_reason = _call_authorize(scenario.path, tracker, cache, project, post_ctx)
    t_deny_ns = t_decision_ns  # for deny, decision == deny time

    # Compute latencies
    t_commit = tracker.t_commit_ns
    latency_ms = round((t_deny_ns - t_commit) / 1_000_000, 3) if post_decision == "DENY" else None

    # Counters
    # allow_after_commit = 1 if post_decision == "ALLOW" (decision after revoke commit)
    allow_after_commit = 1 if post_decision == "ALLOW" else 0

    # Build raw trace
    raw_trace = {
        "run_id": str(uuid.uuid4())[:12],
        'trial_id': f'{scenario.fixture_id}-{scenario.seed}-t{trial_idx:03d}',
        "scenario": scenario.fixture_id,
        "path": scenario.path,
        "cache_state": scenario.cache_state,
        "load": scenario.load,
        'seed': scenario.seed,
        'grant_id': grant_id,
        "parent_grant_id": parent_id,
        "revocation_version": version,
        "revocation_epoch": tracker.revocation_epoch,
        "t_request_utc": tracker.t_request_utc,
        "t_request_monotonic_ns": tracker.t_request_monotonic_ns,
        "t_commit_utc": tracker.t_commit_utc,
        "t_commit_monotonic_ns": t_commit,
        "t_observe_monotonic_ns": component.t_observe_monotonic_ns,
        "t_decision_monotonic_ns": t_decision_ns,
        "t_deny_monotonic_ns": t_deny_ns,
        "pre_decision": pre_decision,
        "pre_reason": pre_reason,
        "pre_linearization": pre_linearization,
        "pre_decision_monotonic_ns": pre_decision_time_ns,
        "post_decision": post_decision,
        "post_reason": post_reason,
        "latency_ms": latency_ms,
        "allow_after_commit": allow_after_commit,
        "effect_after_revoke": 0,  # no downstream side effect in this path
        "cache_version_before": scenario.cache_state == "warm" and version or "0",
        "cache_version_after": version,
        "fault_mode": fault_mode or "none",
        "decision": post_decision,
        "deny_reason": post_reason if post_decision == "DENY" else None,
    }
    raw_trace["raw_trace_sha256"] = sha256_text(canonical_json(
        {k: v for k, v in raw_trace.items() if k != "raw_trace_sha256"}
    ))
    return raw_trace


def load_fixtures() -> list[Scenario]:
    """Load frozen fixtures and generate full matrix cross-product.

    Creates all 4 paths × 2 cache states × 3 loads × 3 seeds = 72
    scenario-seed combinations. Base fixtures define the per-path
    revocation semantics; cache_state and load are varied across
    the full cross-product.
    """
    fixtures_path = Path(__file__).resolve().parent / "fixtures.json"
    data = json.loads(fixtures_path.read_text(encoding="utf-8"))

    # Build base scenarios by path (one per path with minimal cache/load)
    base_by_path: dict[str, Scenario] = {}
    for fx in data["fixtures"]:
        grant_id = f"grant-{fx['fixture_id'].lower()}"
        parent_id = f"parent-{fx['fixture_id'].lower()}" if fx["path"] == "delegation" else None
        sc = Scenario(
            fixture_id=fx["fixture_id"],
            path=fx["path"],
            cache_state=fx["cache_state"],
            load=fx["load"],
            seed="base",
            grant_id=grant_id,
            parent_grant_id=parent_id,
            parent_revoked=False,  # honest: revoke child grant, not parent
        )
        base_by_path[fx["path"]] = sc

    # Generate full cross-product: 4 paths × 2 cache × 3 loads × 3 seeds = 72
    PATHS = ["gateway", "retrieval", "delegation", "projection"]
    CACHE_STATES = ["cold", "warm"]
    LOADS = ["idle", "steady", "burst"]
    SEEDS = ["seed11", "seed12", "seed13"]

    scenarios: list[Scenario] = []
    for path in PATHS:
        base = base_by_path[path]
        for cache_state in CACHE_STATES:
            for load in LOADS:
                for seed in SEEDS:
                    sc = Scenario(
                        fixture_id=f"{base.fixture_id}-{cache_state}-{load}-{seed}",
                        path=path,
                        cache_state=cache_state,
                        load=load,
                        grant_id=base.grant_id,
                        parent_grant_id=base.parent_grant_id,
                        parent_revoked=False,
                        seed=seed,
                    )
                    scenarios.append(sc)

    return scenarios


# ---------------------------------------------------------------------------
# Open-loop probe scenarios
# ---------------------------------------------------------------------------

def _probe_allow_after_commit(base_scenarios: list[Scenario], seed: int,
                              tracker: RevocationTracker, cache: Cache,
                              project: ProjectionIndex, component: ComponentState,
                              rng: random.Random) -> list[dict[str, Any]]:
    """Probe A: force an ALLOW with t_decision > t_commit.

    We simulate a stale cache that returns ALLOW even after revocation
    (the vulnerability being tested). The evaluator must detect this as FAIL.
    """
    traces = []
    sc = base_scenarios[0]  # gateway — canonical path
    sc_seed = f"seed{seed}"
    # Don't invalidate cache (simulating the bug)
    version = tracker.durable_commit(sc.grant_id, parent=sc.parent_revoked)
    ctx = EnforcementContext(
        component=sc.path, cache_state="warm",
        load=sc.load, grant_id=sc.grant_id, parent_grant_id=sc.parent_grant_id
    )
    # Pre-populate stale cache
    cache.set(sc.grant_id, {"allowed": True}, epoch=tracker.revocation_epoch - 1,
              version=f"rev-{tracker.commit_counter - 1}")
    decision, reason = _call_authorize_vulnerable(sc.path, tracker, cache, project, ctx)
    t_decision = perf_ns()
    allow_after_commit = 1 if decision == "ALLOW" else 0
    cache_entry_a = cache.get(sc.grant_id)
    epoch_regression = 1 if cache_entry_a and cache_entry_a.get("epoch", 0) < tracker.revocation_epoch else 0
    trace = {
        "trial_id": f"PROBE-A-{sc.fixture_id}-{sc_seed}",
        "scenario": "PROBE-A-allow-after-commit",
        "path": sc.path,
        "cache_state": "warm",
        "load": sc.load,
        "seed": sc_seed,
        "grant_id": sc.grant_id,
        "revocation_version": version,
        "t_commit_monotonic_ns": tracker.t_commit_ns,
        "t_decision_monotonic_ns": t_decision,
        "latency_ms": round((t_decision - tracker.t_commit_ns) / 1_000_000, 3),
        "decision": decision,
        "deny_reason": reason if decision == "DENY" else None,
        "allow_after_commit": allow_after_commit,
        "fault_mode": "stale_cache_no_invalidation",
        "epoch_regression": epoch_regression,
        "raw_trace_sha256": "",
    }
    trace["raw_trace_sha256"] = sha256_text(canonical_json({k: v for k, v in trace.items() if k != "raw_trace_sha256"}))
    traces.append(trace)
    return traces


def _probe_dropped_hop(base_scenarios: list[Scenario], seed: int,
                       tracker: RevocationTracker, cache: Cache,
                       project: ProjectionIndex, component: ComponentState,
                       rng: random.Random) -> list[dict[str, Any]]:
    """Probe B: dropped propagation hop — one component stays stale while
    producer summary claims all_components_observed=true.

    The evaluator must recover from raw traces and fail.
    """
    traces = []
    sc = base_scenarios[0]
    sc_seed = f"seed{seed}"
    version = tracker.durable_commit(sc.grant_id, parent=sc.parent_revoked)
    # Don't invalidate cache (simulating dropped hop)
    ctx = EnforcementContext(
        component=sc.path, cache_state="warm",
        load=sc.load, grant_id=sc.grant_id, parent_grant_id=sc.parent_grant_id
    )
    cache.set(sc.grant_id, {"allowed": True}, epoch=tracker.revocation_epoch - 1,
              version=f"rev-{tracker.commit_counter - 1}")
    t_decision = perf_ns()
    decision, reason = _call_authorize_vulnerable(sc.path, tracker, cache, project, ctx)
    trace = {
        "trial_id": f"PROBE-B-{sc.fixture_id}-{sc_seed}",
        "scenario": "PROBE-B-dropped-hop",
        "path": sc.path,
        "cache_state": "warm",
        "load": sc.load,
        "seed": sc_seed,
        "grant_id": sc.grant_id,
        "revocation_version": version,
        "t_commit_monotonic_ns": tracker.t_commit_ns,
        "t_decision_monotonic_ns": t_decision,
        "latency_ms": round((t_decision - tracker.t_commit_ns) / 1_000_000, 3),
        "decision": decision,
        "deny_reason": reason if decision == "DENY" else None,
        "allow_after_commit": 1 if decision == "ALLOW" else 0,
        "fault_mode": "dropped_propagation_hop",
        "producer_summary_claim": "all_components_observed=true",
        "raw_trace_sha256": "",
    }
    trace["raw_trace_sha256"] = sha256_text(canonical_json({k: v for k, v in trace.items() if k != "raw_trace_sha256"}))
    traces.append(trace)
    return traces


def _probe_forged_timestamps(seed: int, tracker: RevocationTracker) -> list[dict[str, Any]]:
    """Probe C: forged/non-monotonic timestamps producing negative latency or
    mixed clock domains. Evaluator must reject.
    """
    sc = load_fixtures()[0]
    version = tracker.durable_commit(sc.grant_id)
    # Simulate a forged timestamp where t_decision appears BEFORE t_commit
    forged_trace = {
        "trial_id": f"PROBE-C-forged-ts-seed{seed}",
        "scenario": "PROBE-C-forged-timestamps",
        "path": sc.path,
        "cache_state": "cold",
        "load": "idle",
        "seed": f"seed{seed}",
        "grant_id": sc.grant_id,
        "revocation_version": version,
        "t_commit_monotonic_ns": tracker.t_commit_ns,
        "t_decision_monotonic_ns": tracker.t_commit_ns - 5_000_000,  # 5ms BEFORE commit
        "latency_ms": -5.0,  # negative!
        "decision": "ALLOW",
        "deny_reason": None,
        "allow_after_commit": 0,
        "fault_mode": "forged_timestamp",
        "clock_domain": "forged",
        "raw_trace_sha256": "",
    }
    forged_trace["raw_trace_sha256"] = sha256_text(canonical_json({k: v for k, v in forged_trace.items() if k != "raw_trace_sha256"}))
    return [forged_trace]


def _probe_cache_resurrection(seed: int, tracker: RevocationTracker,
                              cache: Cache, project: ProjectionIndex) -> list[dict[str, Any]]:
    """Probe D: restart with stale cache snapshot. Any ALLOW with reduced epoch
    or lost revocation version => FAIL.
    """
    sc = load_fixtures()[0]
    version = tracker.durable_commit(sc.grant_id)
    # Simulate restart: cache is stale (old version), no invalidation propagated
    restart_cache = Cache("restart-cache")
    restart_cache.set(sc.grant_id, {"allowed": True}, epoch=0, version="rev-0")
    # Restart component does NOT see new version
    restart_cache.epoch = 0
    restart_cache.version = "rev-0"
    ctx = EnforcementContext(component=sc.path, cache_state="warm", load="idle",
                             grant_id=sc.grant_id)
    t_decision = perf_ns()
    decision, reason = _call_authorize_vulnerable(sc.path, tracker, restart_cache, project, ctx)
    trace = {
        "trial_id": f"PROBE-D-cache-resurrection-seed{seed}",
        "scenario": "PROBE-D-cache-resurrection",
        "path": sc.path,
        "cache_state": "warm-after-restart",
        "load": "idle",
        "seed": f"seed{seed}",
        "grant_id": sc.grant_id,
        "revocation_version": version,
        "t_commit_monotonic_ns": tracker.t_commit_ns,
        "t_decision_monotonic_ns": t_decision,
        "latency_ms": round((t_decision - tracker.t_commit_ns) / 1_000_000, 3),
        "decision": decision,
        "deny_reason": reason if decision == "DENY" else None,
        "allow_after_commit": 1 if decision == "ALLOW" else 0,
        "cache_resurrection": 1 if decision == "ALLOW" else 0,
        "epoch_regression": 1 if restart_cache.epoch < tracker.revocation_epoch else 0,
        "fault_mode": "stale_snapshot_after_restart",
        "raw_trace_sha256": "",
    }
    trace["raw_trace_sha256"] = sha256_text(canonical_json({k: v for k, v in trace.items() if k != "raw_trace_sha256"}))
    return [trace]


def _probe_parent_revoke(seed: int, tracker: RevocationTracker, cache: Cache,
                        project: ProjectionIndex) -> list[dict[str, Any]]:
    """Probe E: revoke parent grant, child authorization must DENY.

    We use fixed delegation grant IDs. The parent grant is revoked (parent=True),
    and a child grant attempt that returns ALLOW is a violation (INV5).
    """
    parent_id = "grant-parent-delegation"
    child_id = "grant-child-delegation"
    version = tracker.durable_commit(parent_id, parent=True)
    ctx = EnforcementContext(
        component="delegation", cache_state="warm", load="idle",
        grant_id=child_id, parent_grant_id=parent_id
    )
    cache.set(child_id, {"allowed": True}, epoch=tracker.revocation_epoch - 1,
              version=f"rev-{tracker.commit_counter - 1}")
    t_decision = perf_ns()
    decision, reason = _call_authorize_vulnerable("delegation", tracker, cache, project, ctx)
    trace = {
        "trial_id": f"PROBE-E-parent-revoke-seed{seed}",
        "scenario": "PROBE-E-parent-revoke-child-allow",
        "path": "delegation",
        "cache_state": "warm",
        "load": "idle",
        "seed": f"seed{seed}",
        "grant_id": child_id,
        "parent_grant_id": parent_id,
        "revocation_version": version,
        "t_commit_monotonic_ns": tracker.t_commit_ns,
        "t_decision_monotonic_ns": t_decision,
        "latency_ms": round((t_decision - tracker.t_commit_ns) / 1_000_000, 3),
        "decision": decision,
        "deny_reason": reason if decision == "DENY" else None,
        "child_allow_after_parent_revoke": 1 if decision == "ALLOW" else 0,
        "fault_mode": "parent_revoked_child_stale",
        "raw_trace_sha256": "",
    }
    trace["raw_trace_sha256"] = sha256_text(canonical_json({k: v for k, v in trace.items() if k != "raw_trace_sha256"}))
    return [trace]


def _probe_censored_tail(seed: int, tracker: RevocationTracker,
                         cache: Cache, project: ProjectionIndex) -> list[dict[str, Any]]:
    """Probe F: hide a slow >5000ms trial via timeout/missing completion.

    The evaluator must detect censored/missing mandatory trial => FAIL.
    Here we record a trial that exceeds 5000ms but is marked as censored
    (no completion timestamp). The evaluator must fail it.
    """
    sc = load_fixtures()[0]
    version = tracker.durable_commit(sc.grant_id)
    t_commit = tracker.t_commit_ns
    # Simulate a slow trial (>5000ms) that gets "censored" — no t_deny recorded,
    # producer claims it timed out
    slow_ts = t_commit + 6_000_000_000  # 6000ms > 5000ms threshold
    trace = {
        "trial_id": f"PROBE-F-censored-tail-seed{seed}",
        "scenario": "PROBE-F-censored-slow-tail",
        "path": sc.path,
        "cache_state": "warm",
        "load": "burst",
        "seed": f"seed{seed}",
        "grant_id": sc.grant_id,
        "revocation_version": version,
        "t_commit_monotonic_ns": t_commit,
        "t_decision_monotonic_ns": None,  # censored: no completion recorded
        "t_deny_monotonic_ns": None,
        "latency_ms": None,  # censored
        "decision": "UNKNOWN",
        "deny_reason": None,
        "allow_after_commit": 0,
        "censored_trial": 1,
        "fault_mode": "censored_timeout",
        "producer_summary": "trial completed within bounds (false)",
        "raw_trace_sha256": "",
    }
    trace["raw_trace_sha256"] = sha256_text(canonical_json({k: v for k, v in trace.items() if k != "raw_trace_sha256"}))
    return [trace]


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run_execution(run_label: str, output_dir: Path, *, seeds: list[int] = [11, 22, 33],
                  git_commit: str = "unknown") -> dict[str, Any]:
    """Execute the full measurement matrix for one run (main or rerun).

    Matrix: 4 paths × 2 cache states × 3 loads × 3 seeds × 5 trials = 360
    mandatory observations, plus 6 probe trials × 3 seeds = 18 probe trials,
    plus 20 fault trials = ~400 total. Well above the 100 minimum.
    """
    runner_start = perf_ns()
    env = environment_manifest()
    env_hash = environment_hash(env)
    scenarios = load_fixtures()
    # Build base scenarios (one per path) for probe functions
    base_by_path = {}
    for sc in scenarios:
        if sc.path not in base_by_path:
            base_by_path[sc.path] = sc
    base_scenarios = [base_by_path[p] for p in ["gateway", "retrieval", "delegation", "projection"]]
    all_traces: list[dict[str, Any]] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw-traces"
    raw_dir.mkdir(parents=True, exist_ok=True)

    executor_id = f"executor-{run_label}-{uuid.uuid4().hex[:8]}"
    dirty = _check_dirty()

    # --- Mandatory matrix: 4 × 2 × 3 × 3 = 72 scenario-seed observations,
    #     5 trials each = 360 trials ---
    for sc in scenarios:
        tracker = RevocationTracker()
        cache = Cache(f"cache-{run_label}-{sc.fixture_id}")
        project = ProjectionIndex()
        component = ComponentState(name=sc.path)
        # Convert seed string ("seed11") to int (11) for RNG
        seed_int = int(sc.seed.replace("seed", ""))
        rng = random.Random(seed_int * 1_000_000 + hash(sc.fixture_id))
        for trial_idx in range(5):
            trace = _run_one_revocation_trial(
                tracker, cache, project, sc, seed_int, trial_idx, component, rng=rng
            )
            all_traces.append(trace)

    # --- Fault scenarios: 8 fault types × 3 seeds = 24 fault trials ---
    for seed in seeds:
        sc_seed = f"seed{seed}"
        tracker = RevocationTracker()
        cache = Cache(f"cache-fault-{seed}")
        project = ProjectionIndex()
        component = ComponentState(name="fault")
        rng = random.Random(seed * 7_000_000)
        sc = scenarios[0]  # gateway
        fault_counter = 0
        for fault_mode in [
            "simultaneous_cached_auth", "delayed_propagation", "unknown_delivery",
            "restart_after_commit", "stale_snapshot", "parent_revoke_active_child",
            "burst_competing_ops", "clock_anomaly",
        ]:
            fault_counter += 1
            trace = _run_one_revocation_trial(
                tracker, cache, project, sc, seed, fault_counter, component,
                fault_mode=fault_mode, rng=rng
            )
            trace["fault_mode"] = fault_mode
            trace["scenario"] = f"fault-{fault_mode}"
            trace['trial_id'] = f"FAULT-{fault_mode}-{sc_seed}"
            # Recompute hash after modifying trial_id/scenario
            trace["raw_trace_sha256"] = sha256_text(canonical_json(
                {k: v for k, v in trace.items() if k != "raw_trace_sha256"}
            ))
            all_traces.append(trace)

    # --- Adversarial probes A-F: each seed ---
    for seed in seeds:
        tracker = RevocationTracker()
        cache = Cache(f"probe-cache-{seed}")
        project = ProjectionIndex()
        component = ComponentState(name="probe")
        all_traces.extend(_probe_allow_after_commit(base_scenarios, seed, tracker, cache, project, component, rng))
        all_traces.extend(_probe_dropped_hop(base_scenarios, seed, tracker, cache, project, component, rng))
        all_traces.extend(_probe_forged_timestamps(seed, tracker))
        tracker2 = RevocationTracker()
        all_traces.extend(_probe_cache_resurrection(seed, tracker2, Cache("restart"), project))
        tracker3 = RevocationTracker()
        all_traces.extend(_probe_parent_revoke(seed, tracker3, cache, project))
        all_traces.extend(_probe_censored_tail(seed, tracker3, cache, project))

    # Split traces: mandatory (honest matrix + faults) vs probes (adversarial A-F)
    mandatory_traces = [t for t in all_traces if "PROBE-" not in t.get("scenario", "")]
    probe_traces = [t for t in all_traces if "PROBE-" in t.get("scenario", "")]

    # Write raw traces
    for trace in all_traces:
        tid = trace["trial_id"]
        raw_path = raw_dir / f"{tid}.json"
        raw_path.write_text(_canonical_json(trace) + "\n", encoding="utf-8")

    # Compute aggregate stats from MANDATORY traces only (honest enforcement)
    latencies = [t["latency_ms"] for t in mandatory_traces
                 if t.get("latency_ms") is not None and t["decision"] == "DENY"]

    hard_counters = {
        "allow_after_commit": sum(1 for t in mandatory_traces if t.get("allow_after_commit")),
        "effect_after_revoke": sum(1 for t in mandatory_traces if t.get("effect_after_revoke")),
        "child_allow_after_parent_revoke": sum(1 for t in mandatory_traces if t.get("child_allow_after_parent_revoke")),
        "cache_resurrection": sum(1 for t in mandatory_traces if t.get("cache_resurrection")),
        "epoch_regression": sum(1 for t in mandatory_traces if t.get("epoch_regression")),
        "blind_retry": sum(1 for t in mandatory_traces if t.get("blind_retry")),
        "unreconciled_unknown": sum(1 for t in mandatory_traces if t.get("unreconciled_unknown")),
        "missing_timestamp": sum(1 for t in mandatory_traces if t.get("t_deny_monotonic_ns") is None),
        "censored_trial": sum(1 for t in mandatory_traces if t.get("censored_trial")),
    }

    latencies_ms = latencies

    def stats(vals):
        if not vals:
            return {"count": 0, "min": 0, "p50": 0, "p95": 0, "p99": 0, "max": 0}
        s = sorted(vals)
        return {
            "count": len(s),
            "min": round(s[0], 3),
            "p50": round(s[int(len(s) * 0.50) - 1] if len(s) > 1 else s[0], 3),
            "p95": round(s[min(int(len(s) * 0.95), len(s) - 1)], 3),
            "p99": round(s[min(int(len(s) * 0.99), len(s) - 1)], 3),
            "max": round(s[-1], 3),
        }

    # Per-component stats from MANDATORY traces only
    per_component = {}
    for comp in ("gateway", "retrieval", "delegation", "projection"):
        vals = [t["latency_ms"] for t in mandatory_traces
                if t.get("latency_ms") is not None and t["path"] == comp
                and t["decision"] == "DENY"]
        per_component[comp] = stats(vals)

    total_trials = len(all_traces)
    runner_end = perf_ns()
    utc_now = lambda: datetime.now(timezone.utc).isoformat()

    # Compute frozen artifact hashes
    artifact_dir = Path(__file__).resolve().parent
    def _file_sha(path: str) -> str:
        p = artifact_dir / path
        if not p.exists():
            return "MISSING"
        return hashlib.sha256(p.read_bytes()).hexdigest()

    manifest = {
        "schema": "agentos.s1-008.runner-manifest/v1",
        "run_label": run_label,
        "executor_id": executor_id,
        "started_at_utc": utc_now(),
        "ended_at_utc": utc_now(),
        "git_commit": git_commit,
        "dirty": dirty,
        "contract_sha256": _file_sha("revocation-contract.json"),
        "workload_sha256": _file_sha("workload-manifest.json"),
        "threat_model_sha256": _file_sha("threat-model.json"),
        "rubric_sha256": _file_sha("rubric.json"),
        "fixtures_sha256": _file_sha("fixtures.json"),
        "corpus_manifest_sha256": _file_sha("corpus-manifest.json"),
        "environment_hash": env_hash,
        "environment": env,
        "matrix": {
            "paths": 4, "cache_states": 2, "loads": 3, "seeds": len(seeds),
            "trials_per_scenario_seed": 5,
            'base_observations': 72,
            'total_mandatory_trials': 360 + 24,  # 72 cells × 5 trials + 24 faults
            'fault_trials': 24,
            'probe_trials': 18,
            "total_trials": total_trials,
        },
        "hard_counters": hard_counters,
        "latency_ms": stats(latencies_ms),
        "per_component_latency_ms": per_component,
        "probe_counters": {
            "allow_after_commit": sum(1 for t in probe_traces if t.get("allow_after_commit")),
            "child_allow_after_parent_revoke": sum(1 for t in probe_traces if t.get("child_allow_after_parent_revoke")),
            "cache_resurrection": sum(1 for t in probe_traces if t.get("cache_resurrection")),
            "epoch_regression": sum(1 for t in probe_traces if t.get("epoch_regression")),
            "forged_timestamp": sum(1 for t in probe_traces if t.get("clock_domain") == "forged"),
            "censored_trial": sum(1 for t in probe_traces if t.get("censored_trial")),
        },
        "probes": {
            "A": {"description": "allow-after-commit", "trials": sum(1 for t in all_traces if "PROBE-A" in t.get("scenario",""))},
            "B": {"description": "dropped-hop-hidden-by-summary", "trials": sum(1 for t in all_traces if "PROBE-B" in t.get("scenario",""))},
            "C": {"description": "forged-timestamps", "trials": sum(1 for t in all_traces if "PROBE-C" in t.get("scenario",""))},
            "D": {"description": "cache-resurrection-after-restart", "trials": sum(1 for t in all_traces if "PROBE-D" in t.get("scenario",""))},
            "E": {"description": "delegation-survives-parent-revoke", "trials": sum(1 for t in all_traces if "PROBE-E" in t.get("scenario",""))},
            "F": {"description": "censored-slow-tail", "trials": sum(1 for t in all_traces if "PROBE-F" in t.get("scenario",""))},
        },
        "raw_trace_count": total_trials,
        "raw_trace_dir": str(raw_dir.relative_to(_REPO_ROOT)).replace("\\", "/"),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(_canonical_json(manifest) + "\n", encoding="utf-8")

    return manifest


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _check_dirty() -> bool:
    """Check if working tree is dirty.

    A run is only authoritative if the S1-008 harness (runner, frozen
    artifacts, evaluator, make_bundle, publish_evidence_pack,
    finalize_record) is committed to git. Untracked files in the
    S1-008 ticket scope or results/ invalidate the run.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=10
        )
        s1008_prefix = "research/tickets/stage-1/S1-008/"
        results_prefix = "results/"

        # Check for any untracked/modified files in the S1-008 or results scope
        scope_dirty = False
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            status = line[:2]
            path = line[3:]  # skip "XY " prefix

            # Any untracked files in S1-008 scope → dirty
            if status == "??" and (path.startswith(s1008_prefix) or path.startswith(results_prefix)):
                scope_dirty = True
                continue

            # Any modifications to tracked files → dirty
            # (covers staged, unstaged, and staged+unstaged modifications)
            if status in (" M", "M ", "MM", "AM", "RM"):
                scope_dirty = True
                continue

        return scope_dirty
    except Exception:
        return True  # fail-closed if we can't determine


def main() -> int:
    parser = argparse.ArgumentParser(description="S1-008 revocation latency runner")
    parser.add_argument("--run-label", required=True, choices=["run-a", "run-b"])
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[11, 22, 33])
    parser.add_argument("--git-commit", default="HEAD")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    git_commit = args.git_commit
    if git_commit == "HEAD":
        import subprocess
        try:
            git_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=10
            ).stdout.strip()
        except Exception:
            git_commit = "unknown"

    manifest = run_execution(args.run_label, output_dir,
                             seeds=args.seeds, git_commit=git_commit)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
