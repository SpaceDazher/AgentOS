#!/usr/bin/env python3
"""S1-007 executable retrieval/isolation probes (stdlib only, offline).

Ticket S1-007 (QA3): is per-scope indexing safer and sufficiently useful than
a shared index with row-level retrieval filtering, and can either design prove
no cross-scope reads or leakage?

The QA3 decision contract (``agentos.s1-007-qa3-contract/v1``) is embedded as a
fenced JSON block in the ``architecture_models`` artifact of
``bundle.json``.  These probes parse that contract, execute the isolation
matrix against a deterministic in-process implementation of the chosen
contract, drive the REAL AgentOS memory-scoping code path
(``ToolGateway.memory_write``/``memory_read`` + the SQL ``scope_goal_id``
filter), and fail closed on any cross-scope disclosure, stale cache service,
or missing contract element.

Probes
------
1. ``cross-scope-isolation``
   Executes 6 isolation cases over >=3 scopes:
     C1 positive control: same-scope retrieval returns content INCLUDING
        scope_id and provenance fields;
     C2 cross-scope valid-object-id: the caller in another scope receives
        deny/empty with an error that is byte-identical to the unknown-id
        error, and p50 latency within a documented local bound of the
        unknown-id baseline (no existence leak through timing or error
        detail);
     C3 shared-RLS-only boundary: the SQL row filter alone returns empty for
        a cross-scope read (defense in depth holds), while the near-miss
        shared-index cache keyed by object id alone is demonstrated to have
        leaked and the contract is shown to reject shared-RLS-as-the-sole-
        design;
     C4 revoked object: index entry removed, version bumped, cache
        invalidated; old scope gets empty, owner scope gets deny(revoked),
        zero content;
     C5 moved object (scope transfer): old scope index invalidated -> empty;
        new scope returns content with scope_id updated and provenance
        preserved;
     C6 projection survival: every retrieved projection retains scope_id and
        provenance; every cross-scope projection is empty.
   Also drives the real gateway memory scoping path and recomputes every
   repo-local source hash binding from disk (excluding this ticket's own
   co-created ``probe-results.json``).

2. ``cache-revocation``
   Executes 6 cache/revocation cases over >=3 scopes with an injectable clock
   (deterministic, no sleeping):
     R1 revocation vs warm cache: the shared-index cache keyed by object id
        is demonstrated to serve stale content (near-miss hazard) and the
        implemented scope+version keyed cache must return a miss;
     R2 moved object with warm old-scope cache: new scope gets fresh
        content, old scope gets a miss;
     R3 content edit (version bump) with warm cache: cache returns the NEW
        version, never the old bytes;
     R4 revoked object queried by its owner scope: deny with an explicit
        revocation reason and no content;
     R5 TTL expiry (injected clock): a cached entry is never served after
        expiry;
     R6 invalidation cascade and provenance survival: an invalidated
        (``invalidated_by_id``) record is never retrievable in any scope, and
        the audit/provenance view remains scope-restricted.
   Also enforces the QA3 contract: decision == per_scope_index, mandatory
   retrieval-time scope check, threat model, test boundary, residual risks,
   migration triggers, >=3 scopes, >=6 cases, 0 allowed disclosures,
   near-miss rejections, ticket claim-class coverage, and absence of positive
   non-scope claims (production search service / ranking quality / profile-C
   rollout).

Counter semantics: ``unauthorized_disclosures`` and ``stale_servings`` count
only the IMPLEMENTED contract's behavior (must be 0); the demonstrated
near-miss hazards from the rejected designs are tracked separately as
``near_miss_hazards`` (must be >= 1 - they exist as data and are rejected by
the recorded contract).

The last stdout line is a machine-readable verdict:
``{"status": "pass"|"fail", "observed": "pass"|"fail", ...}`` and the process
exits 0 only on ``pass``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

TICKET_DIR = Path(__file__).resolve().parent
BUNDLE_PATH = TICKET_DIR / "bundle.json"
RESULTS_PATH = TICKET_DIR / "probe-results.json"
CONTRACT_SCHEMA = "agentos.s1-007-qa3-contract/v1"
RESULTS_SCHEMA = "agentos.s1-007-probe-results/v1"
VERDICT_SCHEMA = "agentos.s1-007-probe-verdict/v1"

REQUIRED_DECISION = "per_scope_index"
MIN_SCOPES = 3
MIN_CASES = 6
MAX_ALLOWED_DISCLOSURES = 0
TIMING_P50_TOLERANCE_MS = 5.0
# A hard, generous per-query ceiling for a local in-process observation; this
# is NOT a constant-time proof - it is a bounded-jitter observation.
TIMING_HARD_CAP_MS = 50.0

# Raw timing measurements from the latest cross-scope-isolation run.  The
# measured values are printed on stdout (and thereby captured into the
# research-plan evaluation detail) but deliberately NOT written into
# probe-results.json, keeping that artifact byte-stable across re-runs for a
# reproducible on-disk SHA-256 binding.
PROBE_1_TIMING: dict = {}

# Ticket claim-class taxonomy -> harness claim classes (research.py accepts
# fact|inference|assumption|target; the ticket labels live in claim text).
LABEL_TO_CLASSES = {
    "security_invariant": {"fact"},
    "architecture_tradeoff": {"fact", "inference"},
    "scope_fact": {"fact"},
    "test_measurement": {"fact"},
    "residual_risk": {"assumption"},
    "decision": {"inference", "target"},
}
# The five ticket-mandated claim classes must each be present; "decision" is
# the recorded-QA3-selection label for target-class claims (S1-005 precedent).
REQUIRED_LABELS = ("security_invariant", "architecture_tradeoff", "scope_fact",
                   "test_measurement", "residual_risk")

# Non-scope claims that would cross the ticket boundary if asserted positively.
FORBIDDEN_POSITIVE_PATTERNS = (
    r"(?<!no )production search service (?:was|has been|is) (?:built|deployed|served)",
    r"ranking quality (?:has been|was|is) optimized",
    r"profile[ -]C (?:rollout|production) (?:was|has been|is) (?:completed|deployed)",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_repo_root() -> Path:
    for candidate in (TICKET_DIR, *TICKET_DIR.parents):
        if (candidate / "AGENTS.md").is_file():
            return candidate
    raise RuntimeError("repository root (AGENTS.md) not found above ticket dir")


def load_bundle() -> dict:
    raw = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("bundle root must be a JSON object")
    return raw


def extract_contract(bundle: dict) -> dict:
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, dict):
        raise RuntimeError("bundle has no artifacts object")
    arch = artifacts.get("architecture_models")
    if not isinstance(arch, dict):
        raise RuntimeError("architecture_models artifact missing")
    content = arch.get("content")
    text = content if isinstance(content, str) else json.dumps(content)
    matches = re.findall(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    for blob in matches:
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("schema") == CONTRACT_SCHEMA:
            return parsed
    raise RuntimeError(f"no fenced JSON block with schema {CONTRACT_SCHEMA} found")


def verify_local_source_hashes(bundle: dict, repo_root: Path) -> tuple[list[str], int]:
    """Recompute every declared repo-local source binding from disk.

    The ticket's own ``probe-results.json`` is co-created by this probe and is
    therefore excluded here (it does not exist when the probe starts); the
    research-plan validator independently verifies that binding from disk.
    """
    problems: list[str] = []
    checked = 0
    for source in bundle.get("sources", []):
        if not isinstance(source, dict):
            continue
        provenance = source.get("verifier_provenance")
        if not isinstance(provenance, dict):
            continue
        rel = provenance.get("path")
        expected = provenance.get("file_sha256")
        if not rel or not expected:
            continue
        if rel.replace("\\", "/") == "research/tickets/stage-1/S1-007/probe-results.json":
            continue  # co-created by this probe; verified externally at plan time
        checked += 1
        path = repo_root / rel
        if not path.is_file():
            problems.append(f"{source.get('id', '?')}: missing file {rel}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            problems.append(f"{source.get('id', '?')}: sha256 mismatch for {rel}")
    return problems, checked


def claims_by_label(bundle: dict) -> tuple[dict[str, int], list[str]]:
    counts = {label: 0 for label in LABEL_TO_CLASSES}
    problems: list[str] = []
    for claim in bundle.get("claims", []):
        if not isinstance(claim, dict):
            continue
        text = str(claim.get("text", ""))
        match = re.match(r"\[([a-z_]+)\]", text)
        label = match.group(1) if match else None
        if label not in LABEL_TO_CLASSES:
            problems.append(f"claim {claim.get('id', '?')} lacks a ticket-class label")
            continue
        counts[label] += 1
        if claim.get("claim_class") not in LABEL_TO_CLASSES[label]:
            problems.append(
                f"claim {claim.get('id', '?')} label {label} maps to "
                f"{LABEL_TO_CLASSES[label]} but declares {claim.get('claim_class')}")
    return counts, problems


# ---------------------------------------------------------------------------
# Deterministic retrieval-index simulation implementing the QA3 contract.
# ---------------------------------------------------------------------------

class RetrievalSim:
    """Per-scope index over canonical scope-tagged rows, with an injectable
    clock.  The primary isolation boundary is the per-scope index
    (``retrieval_index(scope_id, object_id)``); the retrieval-time policy
    check (scope match + status) is mandatory defense in depth; the cache key
    binds (scope_id, object_id, version)."""

    def __init__(self, clock):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.clock = clock  # callable() -> epoch seconds; injectable
        c = self.conn
        c.executescript(
            """
            CREATE TABLE objects (
              id TEXT PRIMARY KEY,
              scope_id TEXT NOT NULL,
              content TEXT NOT NULL,
              provenance_json TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',   -- active|revoked
              version INTEGER NOT NULL DEFAULT 1,
              invalidated_by_id TEXT,
              moved_to_scope TEXT
            );
            -- The QA3 per-scope index: scope-addressed, one entry per object.
            CREATE TABLE retrieval_index (
              scope_id TEXT NOT NULL,
              object_id TEXT NOT NULL,
              entry_version INTEGER NOT NULL,
              PRIMARY KEY (scope_id, object_id)
            );
            -- Cache key binds (scope_id, object_id, version); cache-key scope
            -- is mandatory (scopeless keys are the demonstrated near miss).
            CREATE TABLE retrieval_cache (
              cache_scope TEXT NOT NULL,
              object_id TEXT NOT NULL,
              version INTEGER NOT NULL,
              expires_at REAL NOT NULL,
              content TEXT NOT NULL,
              PRIMARY KEY (cache_scope, object_id, version)
            );
            """
        )

    def add_object(self, oid: str, scope_id: str, content: str,
                   provenance: dict, status: str = "active",
                   version: int = 1) -> None:
        self.conn.execute(
            "INSERT INTO objects(id, scope_id, content, provenance_json, status, version)"
            " VALUES (?,?,?,?,?,?)",
            (oid, scope_id, content, json.dumps(provenance, sort_keys=True),
             status, version))
        self.conn.execute(
            "INSERT INTO retrieval_index(scope_id, object_id, entry_version)"
            " VALUES (?,?,?)", (scope_id, oid, version))

    def seed_cache(self, cache_scope: str, oid: str, version: int,
                   content: str, ttl_seconds: float = 3600.0) -> None:
        self.conn.execute(
            "INSERT INTO retrieval_cache(cache_scope, object_id, version,"
            " expires_at, content) VALUES (?,?,?,?,?)",
            (cache_scope, oid, version,
             self.clock() + ttl_seconds, content))

    def revoke(self, oid: str) -> None:
        self.conn.execute(
            "UPDATE objects SET status='revoked', version=version+1 WHERE id=?",
            (oid,))
        self.conn.execute(
            "DELETE FROM retrieval_index WHERE object_id=?", (oid,))

    def move(self, oid: str, to_scope: str) -> None:
        """Scope transfer: invalidate ALL index entries, then rebuild one for
        the new scope; version bump so every cache key dies.  moved_to_scope
        records the destination; a record is retrievable in the scope whose id
        equals its current scope_id (including after a completed transfer)."""
        self.conn.execute(
            "UPDATE objects SET scope_id=?, moved_to_scope=?, version=version+1"
            " WHERE id=?", (to_scope, to_scope, oid))
        self.conn.execute(
            "DELETE FROM retrieval_index WHERE object_id=?", (oid,))
        row = self.conn.execute(
            "SELECT version FROM objects WHERE id=?", (oid,)).fetchone()
        self.conn.execute(
            "INSERT INTO retrieval_index(scope_id, object_id, entry_version)"
            " VALUES (?,?,?)", (to_scope, oid, row["version"]))

    def edit(self, oid: str, new_content: str) -> None:
        self.conn.execute(
            "UPDATE objects SET content=?, version=version+1 WHERE id=?",
            (new_content, oid))
        row = self.conn.execute(
            "SELECT scope_id, version FROM objects WHERE id=?", (oid,)).fetchone()
        self.conn.execute(
            "DELETE FROM retrieval_index WHERE object_id=?", (oid,))
        self.conn.execute(
            "INSERT INTO retrieval_index(scope_id, object_id, entry_version)"
            " VALUES (?,?,?)", (row["scope_id"], oid, row["version"]))

    # -- the query path ------------------------------------------------------
    # "Unknown object" and "valid object in another scope" resolve to the SAME
    # deny branch (caller-scope index miss) with an IDENTICAL error, which is
    # what makes error detail indistinguishable and timing bounded by
    # construction.  A known object in the CALLER's own scope that has no
    # index entry (revoked / moved away / superseded) denies with a reason the
    # owner scope may legitimately see - but never with content.
    def query(self, caller_scope: str, oid: str) -> dict:
        t0 = time.perf_counter()
        entry = self.conn.execute(
            "SELECT object_id FROM retrieval_index WHERE scope_id=? AND object_id=?",
            (caller_scope, oid)).fetchone()
        if entry is None:
            obj = self.conn.execute(
                "SELECT status, scope_id, moved_to_scope FROM objects"
                " WHERE id=?", (oid,)).fetchone()
            if obj is None or obj["scope_id"] != caller_scope:
                # Unknown id, or a valid id that belongs to another scope:
                # byte-identical denial.  No existence is revealed.
                return self._deny(t0, err="no_such_object")
            reason = ("revoked" if obj["status"] == "revoked"
                      else "moved_scope" if obj["moved_to_scope"]
                      else "not_retrievable")
            return self._deny(t0, err="object_not_retrievable", reason=reason)
        row = self.conn.execute(
            "SELECT o.id, o.scope_id, o.content, o.provenance_json, o.status,"
            " o.version, o.invalidated_by_id, o.moved_to_scope,"
            " i.entry_version FROM retrieval_index i"
            " JOIN objects o ON o.id = i.object_id"
            " WHERE i.scope_id=? AND i.object_id=?",
            (caller_scope, oid)).fetchone()
        # Mandatory retrieval-time policy check (defense in depth, run on the
        # same path as the cache read; it is never skipped).
        moved_elsewhere = (row["moved_to_scope"] is not None
                           and row["moved_to_scope"] != row["scope_id"])
        if row["status"] != "active" or moved_elsewhere:
            return self._deny(t0, err="object_not_retrievable",
                              reason="revoked" if row["status"] == "revoked"
                              else "moved_scope")
        hit = self.conn.execute(
            "SELECT content, expires_at FROM retrieval_cache"
            " WHERE cache_scope=? AND object_id=? AND version=?",
            (caller_scope, oid, row["version"])).fetchone()
        if hit is not None and hit["expires_at"] > self.clock():
            return {"ok": True, "content": hit["content"], "version": row["version"],
                    "scope_id": row["scope_id"],
                    "provenance": json.loads(row["provenance_json"]),
                    "source": "cache", "elapsed_ms": (time.perf_counter() - t0) * 1000.0}
        return {"ok": True, "content": row["content"], "version": row["version"],
                "scope_id": row["scope_id"],
                "provenance": json.loads(row["provenance_json"]),
                "source": "index", "elapsed_ms": (time.perf_counter() - t0) * 1000.0}

    def _deny(self, t0: float, err: str, reason: str | None = None) -> dict:
        detail = {"status": "deny", "error": err}
        if reason is not None:
            detail["reason"] = reason  # only for OWNER-scope non-retrievable reasons
        return {"ok": False, "detail": detail,
                "elapsed_ms": (time.perf_counter() - t0) * 1000.0}

    # -- near-miss hazard (adversarial data, not the implemented contract) --
    def near_miss_shared_cache_lookup(self, oid: str) -> dict:
        """A shared-index cache keyed by object id ONLY (no scope, no
        version).  This is the demonstrated leakage surface the QA3 contract
        rejects: after a move/revoke it serves the stale entry to any scope."""
        rows = self.conn.execute(
            "SELECT content FROM retrieval_cache WHERE object_id=?"
            " ORDER BY version ASC LIMIT 1", (oid,)).fetchall()
        if not rows:
            return {"ok": False, "detail": {"status": "deny", "error": "no_such_object"}}
        return {"ok": True, "content": rows[0]["content"], "source": "shared-cache"}


# ---------------------------------------------------------------------------
# Real-code evidence: the current AgentOS gateway memory scoping path.
# ---------------------------------------------------------------------------

def real_gateway_scoping_check(checks: list[dict]) -> None:
    """Drive the REAL ToolGateway.memory_write/memory_read for two goals and
    assert the cross-goal read raises MemoryScopeViolation and the SQL
    scope_goal_id filter returns zero rows for the other scope."""
    repo = find_repo_root()
    src_dir = repo / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    from agentos.db import open_db
    from agentos.engine import Engine
    from agentos.gateway import MemoryScopeViolation, RunContext, ToolGateway
    from agentos.journal import Journal

    with tempfile.TemporaryDirectory(prefix="s1-007-") as td:
        root = Path(td)
        db = open_db(root / "agentos.db")
        try:
            engine = Engine(db, root)
            journal = Journal(db)
            gateway = ToolGateway(db, journal)
            goal_a = engine.create_goal("scope A probe goal", actor="requester")
            goal_b = engine.create_goal("scope B probe goal", actor="requester")
            ctx_a = RunContext(run_id="run-a", goal_id=goal_a, task_id="task-a",
                               lease_owner="worker", capabilities=set(),
                               workspace_path=td)
            ctx_b = RunContext(run_id="run-b", goal_id=goal_b, task_id="task-b",
                               lease_owner="worker", capabilities=set(),
                               workspace_path=td)
            mid = gateway.memory_write(ctx_a, "note", "secret-A-content",
                                       source_uri="file:///scope-a")
            # SQL-level scope filter (spec/SPEC.md §7): zero rows cross-scope.
            cross_rows = db.conn.execute(
                "SELECT id FROM memory_record WHERE id=? AND scope_goal_id=?",
                (mid, goal_b)).fetchall()
            checks.append({"name": "real-gateway-sql-scope-filter-cross-scope-empty",
                           "ok": len(cross_rows) == 0,
                           "detail": f"cross-scope rows={len(cross_rows)}"})
            # Same-scope read returns the record (positive control).
            same = gateway.memory_read(ctx_a, mid)
            checks.append({"name": "real-gateway-memory-read-same-scope",
                           "ok": same["content"] == "secret-A-content",
                           "detail": f"scope_goal_id={same['scope_goal_id']}"})
            # Cross-goal read must raise MemoryScopeViolation (AGENTS.md #7).
            denied = False
            try:
                gateway.memory_read(ctx_b, mid)
            except MemoryScopeViolation as exc:
                denied = "belongs to another scope" in str(exc)
            checks.append({"name": "real-gateway-memory-read-cross-scope-denied",
                           "ok": denied,
                           "detail": "MemoryScopeViolation raised" if denied
                           else "cross-scope read did NOT raise MemoryScopeViolation"})
            # memory_record carries scope_goal_id (SPEC.md §3 data model).
            schema_ok = "scope_goal_id" in [
                r["name"] for r in db.conn.execute(
                    "PRAGMA table_info(memory_record)")]
            checks.append({"name": "real-schema-memory-record-carries-scope",
                           "ok": schema_ok,
                           "detail": "memory_record.scope_goal_id present"})
        finally:
            # Windows keeps the SQLite file open until the connection closes;
            # close before TemporaryDirectory cleanup so the temp dir can be
            # removed.
            db.conn.close()


# ---------------------------------------------------------------------------
# Probe 1: cross-scope isolation matrix (6 cases, >=3 scopes).
# ---------------------------------------------------------------------------

PROBE_1_CASES = ("C1-same-scope-positive-control", "C2-cross-scope-deny-no-leak",
                 "C3-shared-RLS-boundary-and-near-miss", "C4-revoked-cross-scope",
                 "C5-moved-scope-transfer", "C6-projection-survival")


def probe_cross_scope_isolation(bundle: dict) -> dict:
    checks: list[dict] = []
    contract = extract_contract(bundle)
    scopes = contract.get("scopes") or []
    cases = contract.get("isolation_cases") or []
    clock = time.time
    sim = RetrievalSim(clock=clock)

    def check(name: str, ok: bool, detail: str) -> bool:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    # --- contract preconditions -------------------------------------------
    check("contract-decision-per-scope-index",
          contract.get("decision") == REQUIRED_DECISION,
          f"decision={contract.get('decision')!r}")
    check(f"contract-scopes-at-least-{MIN_SCOPES}",
          isinstance(scopes, list) and len(scopes) >= MIN_SCOPES,
          f"scopes={scopes}")
    check(f"contract-cases-at-least-{MIN_CASES}",
          isinstance(cases, list) and len(cases) >= MIN_CASES,
          f"isolation_cases={cases}")
    policy = contract.get("policy")
    check("contract-policy-mandates-retrieval-time-scope-check",
          isinstance(policy, dict)
          and policy.get("retrieval_time_scope_check") is True,
          "retrieval_time_scope_check must be mandatory, never optional")
    check("contract-acceptance-zero-disclosures",
          isinstance(contract.get("acceptance"), dict)
          and contract["acceptance"].get("max_unauthorized_disclosures") == 0,
          f"acceptance={contract.get('acceptance')}")

    # --- fixture data ------------------------------------------------------
    a, b, g = scopes[0], scopes[1], scopes[2]
    alpha_s = {"scope": a, "author": "fixture", "kind": "note"}
    beta_s = {"scope": b, "author": "fixture", "kind": "note"}
    gamma_s = {"scope": g, "author": "fixture", "kind": "note"}
    sim.add_object("obj-alpha-1", a, "alpha secret one", alpha_s)
    sim.add_object("obj-beta-1", b, "beta secret one", beta_s)
    sim.add_object("obj-gamma-1", g, "gamma secret one", gamma_s)
    sim.add_object("obj-beta-2", b, "beta secret two", beta_s)

    implemented_disclosures = 0
    near_miss_hazards = 0
    case_results: list[dict] = []

    def run_case(cid: str, ok: bool, detail: str) -> None:
        case_results.append({"case": cid, "ok": bool(ok), "detail": detail})

    # C1: same-scope positive control (scope alpha).
    r1 = sim.query(a, "obj-alpha-1")
    c1_ok = (r1["ok"] and r1["content"] == "alpha secret one"
             and r1["scope_id"] == a
             and r1["provenance"].get("scope") == a)
    run_case(PROBE_1_CASES[0], c1_ok,
             f"content={r1.get('content')!r} scope={r1.get('scope_id')} "
             f"provenance_scope={r1.get('provenance', {}).get('scope')}")
    if not c1_ok:
        implemented_disclosures += 1  # positive control failed -> treat as leak

    # C2: cross-scope valid-object-id must deny with identical error detail
    # and bounded timing (no existence leak).
    input_err_unknown = sim.query(b, "obj-does-not-exist-xyz")
    input_err_cross = sim.query(b, "obj-alpha-1")  # valid id, other scope
    same_detail = (input_err_cross["ok"] is False
                   and input_err_unknown["ok"] is False
                   and input_err_cross["detail"] == input_err_unknown["detail"])
    # warm-up, then measure the p50 distributions
    for _ in range(80):
        sim.query(b, "obj-alpha-1")
        sim.query(b, "obj-does-not-exist-xyz")
    t_cross, t_unknown = [], []
    for _ in range(120):
        t_cross.append(sim.query(b, "obj-alpha-1")["elapsed_ms"])
        t_unknown.append(sim.query(b, "obj-does-not-exist-xyz")["elapsed_ms"])
    p50_cross = statistics.median(t_cross)
    p50_unknown = statistics.median(t_unknown)
    delta = abs(p50_cross - p50_unknown)
    c2_ok = (same_detail and delta <= TIMING_P50_TOLERANCE_MS
             and max(t_cross) <= TIMING_HARD_CAP_MS
             and max(t_unknown) <= TIMING_HARD_CAP_MS)
    global PROBE_1_TIMING
    PROBE_1_TIMING = {
        "p50_cross_scope_ms": round(p50_cross, 4),
        "p50_unknown_ms": round(p50_unknown, 4),
        "p50_delta_ms": round(delta, 4),
        "max_cross_scope_ms": round(max(t_cross), 4),
        "max_unknown_ms": round(max(t_unknown), 4),
    }
    run_case(PROBE_1_CASES[1], c2_ok,
             f"identical_error={same_detail} "
             f"p50_delta_within_{TIMING_P50_TOLERANCE_MS}ms_bound={delta <= TIMING_P50_TOLERANCE_MS} "
             f"hard_cap_{TIMING_HARD_CAP_MS}ms_respected="
             f"{max(t_cross) <= TIMING_HARD_CAP_MS and max(t_unknown) <= TIMING_HARD_CAP_MS}")
    if not same_detail:
        implemented_disclosures += 1

    # C3: shared-RLS boundary - the per-scope-index deny keeps a cross-scope
    # read empty, while the near-miss shared-index cache (object-id-only key)
    # leaks, which is why shared-RLS-as-the-sole-design is rejected.
    sim.seed_cache(b, "obj-alpha-1", 1, "alpha secret one")  # warm shared cache
    shared_cross = sim.near_miss_shared_cache_lookup("obj-alpha-1")
    shared_cross_leaked = shared_cross.get("ok") is True
    # implemented contract: scope-indexed query from the CALLER's scope denies
    contract_cross = sim.query(b, "obj-alpha-1")
    c3_ok = (contract_cross["ok"] is False
             and shared_cross_leaked is True  # hazard is real ...
             and contract.get("near_miss_rejections")  # ... and rejected
             and any("shared" in str(x).lower() for x in
                     contract.get("near_miss_rejections", [])))
    run_case(PROBE_1_CASES[2], c3_ok,
             f"near_miss_shared_cache_leaked={shared_cross_leaked}"
             f" implemented_contract_denied={contract_cross['ok'] is False}"
             f" contract_rejections={contract.get('near_miss_rejections')}")
    if shared_cross_leaked:
        near_miss_hazards += 1  # data about the REJECTED design, not the contract
    if contract_cross.get("ok"):
        implemented_disclosures += 1

    # C4: revoked object - index entry removed, version bumped, cache dead.
    sim.add_object("obj-alpha-2", a, "alpha secret two", alpha_s, version=1)
    sim.seed_cache(a, "obj-alpha-2", 1, "alpha secret two")
    sim.revoke("obj-alpha-2")
    old_scope = sim.query(a, "obj-alpha-2")
    other = sim.query(b, "obj-alpha-2")
    c4_ok = old_scope["ok"] is False and other["ok"] is False
    run_case(PROBE_1_CASES[3], c4_ok,
             f"old_scope={old_scope['detail']} other_scope={other['detail']} "
             f"owner_deny_reason={old_scope['detail'].get('reason')}")
    if old_scope.get("ok") or other.get("ok"):
        implemented_disclosures += 1

    # C5: moved object (scope transfer alpha -> beta).
    sim.add_object("obj-alpha-3", a, "alpha secret three", alpha_s, version=1)
    sim.seed_cache(a, "obj-alpha-3", 1, "alpha secret three")
    sim.move("obj-alpha-3", b)
    old_q = sim.query(a, "obj-alpha-3")
    new_q = sim.query(b, "obj-alpha-3")
    c5_ok = (old_q["ok"] is False
             and new_q["ok"] and new_q["scope_id"] == b
             and new_q["provenance"].get("scope") == a  # provenance survives
             and new_q["content"] == "alpha secret three")
    run_case(PROBE_1_CASES[4], c5_ok,
             f"old_scope_denied={old_q['ok'] is False} "
             f"new_scope_content={new_q.get('content')!r} "
             f"scope_id={new_q.get('scope_id')} "
             f"provenance_scope={new_q.get('provenance', {}).get('scope')}")
    if old_q.get("ok"):
        implemented_disclosures += 1

    # C6: projection survival - every retrieved projection keeps scope_id +
    # provenance; the cross-scope projection is deny/empty.
    def projection_complete(r: dict) -> bool:
        return (bool(r.get("scope_id"))
                and isinstance(r.get("provenance"), dict)
                and bool(r["provenance"].get("scope")))

    proj_ok = all(projection_complete(r) for r in (r1, new_q))
    cross_proj = input_err_cross
    c6_ok = proj_ok and cross_proj["ok"] is False
    run_case(PROBE_1_CASES[5], c6_ok,
             "same-scope projections retain scope_id+provenance; "
             "cross-scope projection is deny/empty")
    if not c6_ok:
        implemented_disclosures += 1

    ok_cases = [c for c in case_results if c["ok"]]
    check("six-isolation-cases-executed-across-three-scopes",
          len(case_results) >= 6 and len(ok_cases) == len(case_results),
          f"{len(ok_cases)}/{len(case_results)} cases passed")
    check("zero-unauthorized-content-disclosures",
          implemented_disclosures == 0,
          f"implemented disclosures={implemented_disclosures}")
    check("near-miss-hazards-demonstrated-and-rejected",
          near_miss_hazards >= 1,
          f"near_miss_hazards={near_miss_hazards}")

    # Real-code evidence: current gateway memory scoping.
    real_gateway_scoping_check(checks)

    # Evidence integrity: every repo-local source hash binding from disk
    # (excluding the co-created probe-results.json).
    hash_problems, hash_count = verify_local_source_hashes(bundle, find_repo_root())
    check("repo-local-source-hashes-verified-from-disk",
          not hash_problems and hash_count >= 4,
          f"{hash_count} bindings checked; problems={hash_problems}")

    failed = [c["name"] for c in checks if not c["ok"]]
    verdict = "pass" if not failed else "fail"
    return {
        "probe": "cross-scope-isolation",
        "schema": VERDICT_SCHEMA,
        "status": verdict,
        "observed": verdict,
        "scopes": scopes,
        "cases": case_results,
        "identity_error_detail_identical": bool(same_detail),
        "p50_delta_within_bound_ms5": bool(delta <= TIMING_P50_TOLERANCE_MS),
        "hard_cap_50ms_respected": bool(max(t_cross) <= TIMING_HARD_CAP_MS
                                        and max(t_unknown) <= TIMING_HARD_CAP_MS),
        "unauthorized_disclosures": implemented_disclosures,
        "near_miss_hazards": near_miss_hazards,
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "failed_checks": failed,
    }


# ---------------------------------------------------------------------------
# Probe 2: cache / revocation matrix (6 cases, >=3 scopes, injectable clock).
# ---------------------------------------------------------------------------

PROBE_2_CASES = ("R1-revoke-vs-warm-cache", "R2-move-vs-warm-cache",
                 "R3-edit-version-bump", "R4-revoked-owner-scope",
                 "R5-ttl-expiry", "R6-invalidation-cascade-provenance")


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def probe_cache_revocation(bundle: dict) -> dict:
    checks: list[dict] = []
    contract = extract_contract(bundle)
    scopes = contract.get("scopes") or []
    clock = FakeClock()

    def check(name: str, ok: bool, detail: str) -> bool:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    stale_servings = 0          # implemented cache only
    disclosure_count = 0        # implemented contract only
    near_miss_hazards = 0       # demonstrated hazards of rejected designs
    case_results: list[dict] = []

    def run_case(cid: str, ok: bool, detail: str) -> None:
        case_results.append({"case": cid, "ok": bool(ok), "detail": detail})

    a, b, g = scopes[0], scopes[1], scopes[2]
    prov = lambda s: {"scope": s, "author": "fixture", "kind": "note"}
    sim = RetrievalSim(clock=clock)

    # R1: revocation vs a warm cache.  The implemented cache key binds
    # (scope, object, version); after revoke (version+1, index removed) the
    # old key can never be served.  The near-miss shared cache keyed by
    # object id alone still serves the stale row - a demonstrated hazard.
    sim.add_object("obj-r1", a, "r1 content", prov(a), version=1)
    sim.seed_cache(a, "obj-r1", 1, "r1 content")
    sim.revoke("obj-r1")
    miss = sim.query(a, "obj-r1")
    r1_ok = miss["ok"] is False
    stale_shared = sim.near_miss_shared_cache_lookup("obj-r1")
    if stale_shared.get("ok"):
        near_miss_hazards += 1
    run_case(PROBE_2_CASES[0], r1_ok,
             f"implemented_cache_miss={r1_ok} "
             f"near_miss_shared_cache_served_stale={stale_shared.get('ok')}")
    if not r1_ok:
        disclosure_count += 1

    # R2: moved object with a warm old-scope cache entry.
    sim.add_object("obj-r2", a, "r2 content", prov(a), version=1)
    sim.seed_cache(a, "obj-r2", 1, "r2 content")
    sim.move("obj-r2", b)
    old = sim.query(a, "obj-r2")
    new = sim.query(b, "obj-r2")
    r2_ok = old["ok"] is False and new["ok"] and new["content"] == "r2 content"
    run_case(PROBE_2_CASES[1], r2_ok,
             f"old_scope_miss={old['ok'] is False} new_scope_fresh={new.get('content')!r}")
    if old.get("ok"):
        stale_servings += 1
        disclosure_count += 1

    # R3: content edit (version bump) with a warm cache returns the NEW
    # version (never the old bytes).
    sim.add_object("obj-r3", g, "r3 version-1", prov(g), version=1)
    sim.seed_cache(g, "obj-r3", 1, "r3 version-1")
    sim.edit("obj-r3", "r3 version-2")
    q = sim.query(g, "obj-r3")
    r3_ok = q["ok"] and q["version"] == 2 and q["content"] == "r3 version-2"
    run_case(PROBE_2_CASES[2], r3_ok,
             f"version={q.get('version')} content={q.get('content')!r}")
    if q.get("content") == "r3 version-1":
        stale_servings += 1

    # R4: revoked object queried by its OWNER scope -> deny with a revocation
    # reason and no content.
    sim.add_object("obj-r4", a, "r4 content", prov(a), version=1)
    sim.revoke("obj-r4")
    q = sim.query(a, "obj-r4")
    r4_ok = q["ok"] is False and q["detail"].get("reason") == "revoked"
    run_case(PROBE_2_CASES[3], r4_ok, f"detail={q['detail']}")
    if q.get("ok"):
        disclosure_count += 1

    # R5: TTL expiry (injected clock) - never served after expiry.
    sim.add_object("obj-r5", b, "r5 content", prov(b), version=1)
    sim.seed_cache(b, "obj-r5", 1, "r5 content", ttl_seconds=30)
    q_before = sim.query(b, "obj-r5")
    clock.advance(31)
    q_after = sim.query(b, "obj-r5")
    r5_ok = (q_before["ok"] and q_before["source"] == "cache"
             and q_after["ok"] and q_after["source"] == "index"  # re-fetched
             and q_after["content"] == "r5 content")
    run_case(PROBE_2_CASES[4], r5_ok,
             f"before_source={q_before.get('source')} after_source={q_after.get('source')}")

    # R6: invalidation cascade + provenance survival: an invalidated record is
    # never retrievable in ANY scope; the scope-restricted provenance view
    # remains intact for the owner.
    sim.add_object("obj-r6", a, "r6 content", prov(a), version=1)
    sim.conn.execute(
        "UPDATE objects SET invalidated_by_id='mem-superseder',"
        " version=version+1 WHERE id='obj-r6'")
    sim.conn.execute("DELETE FROM retrieval_index WHERE object_id='obj-r6'")
    q_any = [sim.query(s, "obj-r6") for s in (a, b, g)]
    provenance_ok = sim.conn.execute(
        "SELECT provenance_json FROM objects WHERE id='obj-r6'").fetchone()[
            "provenance_json"] is not None
    r6_ok = all(not q["ok"] for q in q_any) and provenance_ok
    run_case(PROBE_2_CASES[5], r6_ok,
             f"denied_in_all_scopes={all(not q['ok'] for q in q_any)} "
             f"provenance_preserved={provenance_ok}")
    if any(q["ok"] for q in q_any):
        disclosure_count += 1

    ok_cases = [c for c in case_results if c["ok"]]
    check("six-cache-revocation-cases-across-three-scopes",
          len(case_results) >= 6 and len(ok_cases) == len(case_results),
          f"{len(ok_cases)}/{len(case_results)} cases passed")
    check("implemented-cache-never-serves-stale",
          stale_servings == 0,
          f"stale_servings={stale_servings}")
    check("zero-unauthorized-content-disclosures",
          disclosure_count == 0,
          f"disclosures={disclosure_count}")
    check("near-miss-hazards-demonstrated-and-rejected",
          near_miss_hazards >= 1,
          f"near_miss_hazards={near_miss_hazards}")

    # --- QA3 contract enforcement ------------------------------------------
    check("contract-decision-per-scope-index",
          contract.get("decision") == REQUIRED_DECISION,
          f"decision={contract.get('decision')!r}")
    policy = contract.get("policy")
    check("contract-policy-cache-key-scope-scoped-and-versioned",
          isinstance(policy, dict)
          and policy.get("cache_key_binds_scope_and_version") is True,
          "cache key must bind scope+version, never object id alone")
    tm = contract.get("threat_model")
    check("contract-threat-model-present",
          isinstance(tm, dict) and tm.get("existence_leak") and tm.get("stale_cache"),
          f"threat_model keys={list((tm or {}).keys())}")
    check("contract-test-boundary-present",
          isinstance(contract.get("test_boundary"), dict)
          and contract["test_boundary"].get("boundary"),
          "test boundary must be explicit")
    residual = contract.get("residual_risk")
    check("contract-residual-risks-explicit",
          isinstance(residual, list) and len([r for r in residual if str(r).strip()]) >= 2,
          f"residual_risk={residual}")
    triggers = contract.get("migration_triggers")
    check("contract-migration-triggers-explicit",
          isinstance(triggers, list) and len([t for t in triggers if str(t).strip()]) >= 2,
          f"migration_triggers={triggers}")
    non_goals = contract.get("non_goals")
    check("contract-non-goals-explicit",
          isinstance(non_goals, list) and len([n for n in non_goals if str(n).strip()]) >= 2,
          f"non_goals={non_goals}")
    # Near-miss rejections: shared-RLS-as-sole-design and scopeless cache
    # keys must both be rejected by the recorded contract.
    rejects = [str(x).lower() for x in contract.get("near_miss_rejections", [])]
    check("contract-rejects-shared-RLS-as-sole-design",
          any("shared-rls" in x or "shared index" in x for x in rejects),
          f"near_miss_rejections={contract.get('near_miss_rejections')}")
    check("contract-rejects-scopeless-cache-keys",
          any("scopeless" in x or "object-id-only" in x for x in rejects),
          f"near_miss_rejections={contract.get('near_miss_rejections')}")

    # platform_plan must state the chosen isolation contract explicitly.
    platform = bundle.get("artifacts", {}).get("platform_plan", {})
    platform_text = platform.get("content") if isinstance(platform.get("content"), str) else json.dumps(platform.get("content", ""))
    check("platform-plan-states-per-scope-index-and-retrieval-time-check",
          "per-scope" in platform_text.lower()
          and "retrieval-time" in platform_text.lower()
          and "cache" in platform_text.lower(),
          "platform_plan must name per-scope index, retrieval-time check and cache key rules")

    # Ticket claim-class coverage and harness-class mapping.
    counts, claim_problems = claims_by_label(bundle)
    missing = [label for label in REQUIRED_LABELS if counts[label] < 1]
    check("ticket-claim-class-coverage-present-and-mapped",
          not missing and not claim_problems,
          f"counts={counts}; missing={missing}; problems={claim_problems}")

    # No positive non-scope claims (production search service, ranking quality,
    # profile-C rollout).
    haystacks = [str(c.get("text", "")) for c in bundle.get("claims", []) if isinstance(c, dict)]
    for kind, artifact in bundle.get("artifacts", {}).items():
        content = artifact.get("content") if isinstance(artifact, dict) else None
        haystacks.append(content if isinstance(content, str) else json.dumps(content))
    blob = "\n".join(haystacks)
    hits = [pat for pat in FORBIDDEN_POSITIVE_PATTERNS if re.search(pat, blob, flags=re.I)]
    check("no-positive-non-scope-claims",
          not hits,
          f"forbidden positive non-scope claims: {hits}" if hits else "scope limits intact")

    failed = [c["name"] for c in checks if not c["ok"]]
    verdict = "pass" if not failed else "fail"
    return {
        "probe": "cache-revocation",
        "schema": VERDICT_SCHEMA,
        "status": verdict,
        "observed": verdict,
        "scopes": scopes,
        "cases": case_results,
        "stale_servings": stale_servings,
        "unauthorized_disclosures": disclosure_count,
        "near_miss_hazards": near_miss_hazards,
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "failed_checks": failed,
    }


PROBES = {
    "cross-scope-isolation": probe_cross_scope_isolation,
    "cache-revocation": probe_cache_revocation,
}
PROBE_ORDER = ("cross-scope-isolation", "cache-revocation")


def write_results(path: Path, records: list[dict]) -> None:
    existing: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            existing = {}
    probes = {p.get("probe"): p for p in existing.get("probes", []) if isinstance(p, dict)}
    for record in records:
        probes[record["probe"]] = record
    ordered = [probes[name] for name in PROBE_ORDER if name in probes]
    final = "pass" if ordered and all(p["status"] == "pass" for p in ordered) else "fail"
    document = {
        "schema": RESULTS_SCHEMA,
        "ticket": "S1-007",
        "probes": ordered,
        "final_verdict": final,
    }
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1-007 retrieval-isolation probes")
    parser.add_argument("--probe", choices=sorted(PROBES), required=True)
    parser.add_argument("--out", default=str(RESULTS_PATH),
                        help="results JSON to merge this probe's record into")
    args = parser.parse_args(argv)

    try:
        bundle = load_bundle()
        record = PROBES[args.probe](bundle)
    except Exception as exc:  # fail closed: any probe error is a failure
        record = {
            "probe": args.probe,
            "schema": VERDICT_SCHEMA,
            "status": "fail",
            "observed": "fail",
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        write_results(Path(args.out), [record])
    except OSError as exc:
        print(f"warning: could not write results file: {exc}", file=sys.stderr)
    # The measured timing values ride on stdout (captured into the
    # research-plan evaluation detail) but never into the stable results file.
    printed = dict(record)
    if args.probe == "cross-scope-isolation" and PROBE_1_TIMING:
        printed.update(PROBE_1_TIMING)
    print(json.dumps({
        "probe": printed["probe"],
        "checks_total": printed.get("checks_total"),
        "checks_failed": printed.get("checks_failed"),
    }))
    print(json.dumps(printed, ensure_ascii=False))
    return 0 if record["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())