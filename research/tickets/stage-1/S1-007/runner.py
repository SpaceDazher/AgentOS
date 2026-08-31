"""AgentOS S1-007 — deterministic retrieval/index isolation simulator.

Simulates the frozen QA3 isolation contract (isolation-contract.json) for
two candidate retrieval topologies:

  per_scope  -- one index projection per canonical scope; retrieval only
                touches the caller's own scope index;
  shared_rls -- one shared index over all scopes; a row-level policy
                predicate is applied during retrieval before any
                materialization.

Both variants implement identical AgentOS semantics (authorize before
materialize, cache entries bound to (scope, policy_epoch), epoch-bump
invalidation at a committed invalidation point, identical policy contract
on bulk/pagination/aggregation/background paths, canonical deny form).
They differ only in index topology.  Honest variants are expected to hold
ISO1-ISO8; adversarial probe candidates (probes mode) deliberately violate
single invariants and must be detected by evaluator.py through the same
code paths - never by hand-written counters.

Modes:
  main   --out results/run-a   full frozen matrix (2 variants x 14 cases
                                x 3 seeds = 84 runs) + bounded timing probe
  rerun  --out results/run-b   identical matrix in a separate process
  probes --out results/probes.json  adversarial candidates A/B/C/D plus a
                                blast-radius fault injection (R)

Determinism: random.Random(seed) per run for request-order/cache-state
permutation; no wall clock in model observations (the timing probe is a
separate, explicitly bounded real-clock section).  Every run records
contract/corpus/rubric sha256, commit, tree, dirty state and the
environment manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import time
from pathlib import Path

TICKET = Path(__file__).resolve().parent
ROOT = TICKET.parents[3]

SCHEMA_RUN = "agentos.s1-007.run/v1"
SCHEMA_MANIFEST = "agentos.s1-007.run-manifest/v1"
SCHEMA_PROBES = "agentos.s1-007.probes/v1"

CONTRACT_FILES = (
    "isolation-contract.json", "threat-model.json", "rubric.json",
    "corpus-manifest.json", "fixtures.json",
)
EVIDENCE_SCRIPTS = (
    "runner.py", "evaluator.py", "make_bundle.py", "dependency_gate.py",
    "bundle_content.py", "publish_evidence_pack.py",
)

ISO_KEYS = ("ISO1", "ISO2", "ISO3", "ISO4", "ISO5", "ISO6", "ISO7", "ISO8")

DENY_BODY = {"objects": [], "result": "empty"}

INDEX_FIXED_OVERHEAD_BYTES = 256
TIMING = {"sample_count": 200, "warmup": 20, "inner_repeats": 8,
          "seeds": [101, 202, 303]}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_json(obj) -> str:
    return _sha(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8"))


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


# --------------------------------------------------------------------------
# git/environment provenance (fail closed: git failure is an error, never
# a silently "unavailable" field)
# --------------------------------------------------------------------------

def _git(args: list) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True,
                         timeout=30, cwd=str(ROOT))
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({out.returncode}): "
                           f"{out.stderr.strip()}")
    value = out.stdout.strip()
    if not value:
        raise RuntimeError(f"git {' '.join(args)} returned empty output")
    return value


def _git_lines(args: list) -> list:
    out = subprocess.run(["git", *args], capture_output=True, text=True,
                         timeout=30, cwd=str(ROOT))
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({out.returncode}): "
                           f"{out.stderr.strip()}")
    return out.stdout.splitlines()


def research_surface_dirty_lines(porcelain_lines: list) -> list:
    """Dirty input lines, ignoring only generated S1-007 outputs."""
    dirty = []
    for ln in porcelain_lines:
        if not ln.strip():
            continue
        path = ln[3:].strip().strip('"')
        if path.startswith("research/tickets/stage-1/S1-007/results/") or \
                path == "research/tickets/stage-1/S1-007/bundle.json" or \
                path == "research/tickets/stage-1/S1-007/dependency-gate.json":
            continue
        dirty.append(ln)
    return dirty


_PROV_CACHE: dict | None = None


def provenance() -> dict:
    global _PROV_CACHE
    if _PROV_CACHE is not None:
        return _PROV_CACHE
    scripts = {}
    script_blobs = {}
    commit = _git(["rev-parse", "HEAD"])
    for name in EVIDENCE_SCRIPTS:
        path = TICKET / name
        if path.is_file():
            scripts[name] = _sha(path.read_bytes())
            rel = path.relative_to(ROOT).as_posix()
            script_blobs[name] = _sha(
                subprocess.run(["git", "show", f"{commit}:{rel}"],
                               capture_output=True, timeout=30,
                               cwd=str(ROOT)).stdout)
    dirty_lines = research_surface_dirty_lines(
        _git_lines(["status", "--porcelain"]))
    result = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "commit": commit,
        "tree_sha": _git(["rev-parse", "HEAD^{tree}"]),
        "dirty": bool(dirty_lines),
        "dirty_lines": dirty_lines,
        "script_hashes": scripts,
        "script_blob_hashes": script_blobs,
        "executor_id": os.environ.get("AGENTOS_EXECUTOR_ID", "direct-test"),
    }
    result["environment_hash"] = _sha(json.dumps(
        {k: result[k] for k in ("python", "platform", "commit", "tree_sha",
                                "script_hashes", "script_blob_hashes",
                                "executor_id")},
        sort_keys=True, separators=(",", ":")).encode())
    _PROV_CACHE = result
    return result


def contract_hashes() -> dict:
    return {name: _sha((TICKET / name).read_bytes())
            for name in CONTRACT_FILES}


# --------------------------------------------------------------------------
# frozen world
# --------------------------------------------------------------------------

class World:
    def __init__(self, fixtures: dict):
        self.fixtures = fixtures
        self.scopes = {s["short"]: dict(s) for s in fixtures["scopes"]}
        self.scope_ids = {s["short"]: s["scope_id"]
                          for s in fixtures["scopes"]}
        self.memberships = {a["actor"]: list(a["member_of"])
                            for a in fixtures["actors"]}
        self.objects = {}
        for obj in fixtures["objects"]:
            self.objects[(obj["id"], obj["version"])] = dict(obj)
        self.queries = {q["query_id"]: dict(q) for q in fixtures["queries"]}
        self.deny_body = dict(fixtures["canonical_deny_body"])


def load_world() -> World:
    fixtures = json.loads((TICKET / "fixtures.json").read_text(encoding="utf-8"))
    return World(fixtures)


# --------------------------------------------------------------------------
# retrieval variants
# --------------------------------------------------------------------------

class VariantBase:
    """Common AgentOS retrieval semantics; subclasses differ only in index
    topology.  The decision order is frozen:

    1. resolve effective scope from the canonical authorization context
    2. policy check (membership + policy version)  -> commit decision
    3. cache lookup with (scope, epoch) binding revalidation
    4. index lookup (topology-specific)
    5. materialize content + provenance
    """
    name = "base"

    def __init__(self, world: World):
        self.world = world
        self.epochs = {s: spec["policy_epoch"]
                       for s, spec in world.scopes.items()}
        self.cache = {}
        self.audit = []
        self.metrics = {"policy_evaluations": 0, "rows_scanned": 0,
                        "cache_hits": 0, "cache_misses": 0,
                        "stale_invalidated": 0, "invalidation_ops": 0,
                        "index_writes_scope_bound": 0}
        self.build_index()

    # -- topology hooks ----------------------------------------------------
    def build_index(self) -> None:
        raise NotImplementedError

    def lookup_entries(self, eff: str, target_id: str) -> list:
        """Topology-specific lookup; returns entries visible to the policy
        predicate of scope `eff`, applying the predicate per row BEFORE any
        materialization.  `rows_scanned` accounting happens here."""
        raise NotImplementedError

    def visible_rows(self, eff: str) -> list:
        """Rows for aggregation/pagination: the policy predicate is applied
        per row before any aggregate accumulates."""
        raise NotImplementedError

    def all_entries(self) -> list:
        raise NotImplementedError

    def entries_of_scope(self, scope: str) -> list:
        raise NotImplementedError

    def remove_entries(self, scope: str, target_id: str) -> None:
        raise NotImplementedError

    def rebind_entry_scope(self, from_scope: str, to_scope: str,
                           target_id: str) -> None:
        raise NotImplementedError

    def storage_state(self) -> dict:
        raise NotImplementedError

    # -- authorization (shared, frozen) ------------------------------------
    def resolve_effective_scope(self, actor: str, claimed_scope, obs: dict):
        """Effective scope comes ONLY from canonical membership rows.  A
        caller-supplied scope may at most equal the canonical effective
        scope; anything else is forged/unknown and denies."""
        canonical = list(self.world.memberships.get(actor, []))
        if len(set(canonical)) > 1:
            raise RuntimeError("model ambiguity: actor with multiple scopes")
        eff = canonical[0] if canonical else None
        obs["policy_checks"].append("scope_resolution_canonical")
        if claimed_scope is None:
            if eff is None:
                obs["policy_checks"].append("membership_denied")
                return None, "policy_denied"
            return eff, None
        alias = {self.world.scope_ids[s]: s for s in self.world.scopes}
        claimed_short = alias.get(claimed_scope, claimed_scope)
        if claimed_short not in self.world.scopes:
            obs["policy_checks"].append("scope_unknown")
            return None, "unknown_scope"
        if eff is None or claimed_short != eff:
            obs["policy_checks"].append("membership_denied")
            # the canonical effective scope is reported unchanged; the
            # forged claim never widens it and the request denies
            return eff, "forged_scope"
        return eff, None

    def policy_check(self, actor: str, eff: str, obs: dict) -> bool:
        self.metrics["policy_evaluations"] += 1
        spec = self.world.scopes.get(eff)
        obs["policy_checks"].append("policy_version_valid")
        return spec is not None and spec["policy_version"] == "pol-v1"

    # -- cache (shared, frozen binding) ------------------------------------
    def cache_key(self, eff, query_id, target_id, version):
        return (eff, query_id, target_id,
                version if version is not None else "latest")

    def cache_lookup(self, eff, query_id, target_id, version, obs: dict,
                     *, revalidate: bool = True):
        key = self.cache_key(eff, query_id, target_id, version)
        entry = self.cache.get(key)
        if entry is None:
            obs["cache_events"].append("miss")
            self.metrics["cache_misses"] += 1
            return None
        if not revalidate:
            # regression semantics (probe B): the entry is served without
            # any scope/epoch revalidation
            obs["cache_events"].append("hit_no_revalidation")
            obs["cache_entry_binding"] = {"scope": entry["scope"],
                                          "epoch": entry["epoch"],
                                          "payload_digest": entry["digest"]}
            self.metrics["cache_hits"] += 1
            return entry["payload"]
        obs["policy_checks"].append("epoch_revalidation")
        current = self.epochs[eff]
        if entry["scope"] != eff or entry["epoch"] != current:
            obs["cache_events"].append("stale_invalidated")
            self.metrics["stale_invalidated"] += 1
            del self.cache[key]
            return None
        obs["cache_events"].append("hit")
        obs["cache_entry_binding"] = {"scope": entry["scope"],
                                      "epoch": entry["epoch"],
                                      "payload_digest": entry["digest"]}
        self.metrics["cache_hits"] += 1
        return entry["payload"]

    def cache_fill(self, eff, query_id, target_id, version, payload,
                   obs: dict) -> None:
        key = self.cache_key(eff, query_id, target_id, version)
        self.cache[key] = {"scope": eff, "epoch": self.epochs[eff],
                           "payload": payload, "digest": sha_json(payload)}
        obs["cache_events"].append("fill")

    # -- invalidation (shared, frozen) --------------------------------------
    def _commit_invalidation(self, scopes: list, obs: dict) -> None:
        for s in scopes:
            self.epochs[s] = self.epochs[s] + 1
        self.metrics["invalidation_ops"] += 1
        obs["committed_invalidation_point"] = True
        obs["epochs_after"] = dict(self.epochs)

    def op_revoke(self, scope: str, target_id: str, obs: dict) -> None:
        self.remove_entries(scope, target_id)
        self._commit_invalidation([scope], obs)
        self.audit.append({"event": "object.revoked", "scope": scope,
                           "target_id": target_id})
        obs["audit_event"] = {"event": "object.revoked", "scope": scope}

    def op_move(self, from_scope: str, to_scope: str, target_id: str,
                obs: dict) -> None:
        self.rebind_entry_scope(from_scope, to_scope, target_id)
        self._commit_invalidation([from_scope, to_scope], obs)
        self.audit.append({"event": "object.moved", "from_scope": from_scope,
                           "to_scope": to_scope, "target_id": target_id})
        obs["audit_event"] = {"event": "object.moved",
                              "from_scope": from_scope, "to_scope": to_scope}

    def op_supersede(self, scope: str, target_id: str, new_version: int,
                     obs: dict) -> None:
        self.remove_entries(scope, target_id)
        self.index_version(scope, target_id, new_version)
        self._commit_invalidation([scope], obs)
        self.audit.append({"event": "object.superseded", "scope": scope,
                           "target_id": target_id,
                           "new_version": new_version})
        obs["audit_event"] = {"event": "object.superseded", "scope": scope,
                              "new_version": new_version}

    def index_version(self, scope: str, target_id: str, version: int) -> None:
        raise NotImplementedError

    # -- retrieval (frozen decision order) ----------------------------------
    def retrieve(self, actor: str, query_id: str, target_id: str,
                 version=None, claimed_scope=None, op: str = "retrieve",
                 *, cache_revalidate: bool = True) -> dict:
        obs = {"op": op, "actor": actor, "query_id": query_id,
               "target_id": target_id, "claimed_scope": claimed_scope,
               "requested_version": version, "policy_checks": [],
               "cache_events": [], "materialize_before_policy_check": 0,
               "rows_scanned": 0, "policy_epoch_at_step":
                   dict(self.epochs)}
        eff, reason = self.resolve_effective_scope(actor, claimed_scope, obs)
        obs["effective_scope"] = eff
        if eff is None or reason is not None:
            obs["decision"] = "deny"
            obs["reason_class"] = reason or "policy_denied"
            obs["response"] = dict(self.world.deny_body)
            obs["response_digest"] = sha_json(obs["response"])
            self.audit.append({"event": "retrieval.deny", "actor": actor,
                               "effective_scope": eff,
                               "generic_reason_class": obs["reason_class"]})
            obs["audit_event"] = {"event": "retrieval.deny",
                                  "generic_reason_class": obs["reason_class"]}
            return obs
        obs["policy_epoch_current"] = self.epochs[eff]
        if not self.policy_check(actor, eff, obs):
            obs["decision"] = "deny"
            obs["reason_class"] = "policy_denied"
            obs["response"] = dict(self.world.deny_body)
            obs["response_digest"] = sha_json(obs["response"])
            self.audit.append({"event": "retrieval.deny", "actor": actor,
                               "effective_scope": eff,
                               "generic_reason_class": "policy_denied"})
            obs["audit_event"] = {"event": "retrieval.deny",
                                  "generic_reason_class": "policy_denied"}
            return obs
        cached = self.cache_lookup(eff, query_id, target_id, version, obs,
                                   revalidate=cache_revalidate)
        if cached is not None:
            obs["decision"] = "allow"
            obs["response"] = cached
            obs["response_digest"] = sha_json(cached)
            self.audit.append({"event": "retrieval.allow", "actor": actor,
                               "effective_scope": eff,
                               "result_count": len(cached["objects"])})
            obs["audit_event"] = {"event": "retrieval.allow",
                                  "result_count": len(cached["objects"])}
            return obs
        entries = self.lookup_entries(eff, target_id, obs)
        if version is not None:
            entries = [e for e in entries if e["version"] == version]
        else:
            entries = [e for e in entries if e["active"]]
        if not entries:
            obs["decision"] = "deny"
            obs["reason_class"] = "empty"
            obs["response"] = dict(self.world.deny_body)
            obs["response_digest"] = sha_json(obs["response"])
            self.audit.append({"event": "retrieval.deny", "actor": actor,
                               "effective_scope": eff,
                               "generic_reason_class": "empty"})
            obs["audit_event"] = {"event": "retrieval.deny",
                                  "generic_reason_class": "empty"}
            return obs
        entry = entries[0]
        response = self.materialize(entry, query_id, obs)
        self.cache_fill(eff, query_id, target_id, version, response, obs)
        obs["decision"] = "allow"
        obs["response"] = response
        obs["response_digest"] = sha_json(response)
        self.audit.append({"event": "retrieval.allow", "actor": actor,
                           "effective_scope": eff, "result_count": 1})
        obs["audit_event"] = {"event": "retrieval.allow", "result_count": 1}
        return obs

    def materialize(self, entry: dict, query_id: str, obs: dict) -> dict:
        obj = self.world.objects[(entry["id"], entry["version"])]
        digest = _sha(obj["content"].encode())
        corrupt = getattr(self, "corrupt_targets", {})
        if corrupt.get((entry["scope"], entry["id"])):
            digest = corrupt[(entry["scope"], entry["id"])]
        body = {
            "objects": [{
                "id": obj["id"], "version": obj["version"],
                "kind": obj["kind"], "scope": entry["scope"],
                "digest": digest,
                "content": obj["content"],
                "provenance": dict(obj["provenance"]),
            }],
            "result": "ok",
            "meta": {
                "result_count": 1,
                "ranks": [{"id": obj["id"], "rank": 1}],
                "snippets": [{"id": obj["id"],
                              "snippet": obj["content"][:24]}],
            },
        }
        return body

    # -- bulk / pagination / aggregation / background (frozen contract) ----
    def op_bulk(self, actor: str, target_ids: list, query_id: str) -> list:
        return [self.retrieve(actor, query_id, tid) for tid in target_ids]

    def op_paginate(self, actor: str, query_id: str, offset: int,
                    limit: int) -> dict:
        obs = {"op": "paginate", "actor": actor, "query_id": query_id,
               "offset": offset, "limit": limit, "policy_checks": [],
               "cache_events": [], "materialize_before_policy_check": 0,
               "rows_scanned": 0, "policy_epoch_at_step": dict(self.epochs)}
        eff, reason = self.resolve_effective_scope(actor, None, obs)
        obs["effective_scope"] = eff
        if eff is None or not self.policy_check(actor, eff, obs):
            obs["decision"] = "deny"
            obs["reason_class"] = reason or "policy_denied"
            obs["response"] = dict(self.world.deny_body)
            obs["response_digest"] = sha_json(obs["response"])
            return obs
        rows = self.visible_rows(eff, obs)
        rows = sorted(rows, key=lambda e: (e["id"], e["version"]))
        window = rows[offset:offset + limit]
        objects = []
        for entry in window:
            objects.append({
                "id": entry["id"], "version": entry["version"],
                "kind": entry["kind"], "scope": entry["scope"],
                "digest": self.world.objects[
                    (entry["id"], entry["version"])]["content"]
                and _sha(self.world.objects[
                    (entry["id"], entry["version"])]["content"].encode()),
                "content": self.world.objects[
                    (entry["id"], entry["version"])]["content"],
                "provenance": dict(self.world.objects[
                    (entry["id"], entry["version"])]["provenance"]),
            })
        response = {"objects": objects, "result": "ok",
                    "meta": {"result_count": len(objects),
                             "total_count": len(rows), "ranks": [],
                             "snippets": []}}
        obs["decision"] = "allow"
        obs["response"] = response
        obs["response_digest"] = sha_json(response)
        return obs

    def op_aggregate(self, actor: str, query_id: str) -> dict:
        obs = {"op": "aggregate", "actor": actor, "query_id": query_id,
               "policy_checks": [], "cache_events": [],
               "materialize_before_policy_check": 0, "rows_scanned": 0,
               "policy_epoch_at_step": dict(self.epochs)}
        eff, reason = self.resolve_effective_scope(actor, None, obs)
        obs["effective_scope"] = eff
        if eff is None or not self.policy_check(actor, eff, obs):
            obs["decision"] = "deny"
            obs["reason_class"] = reason or "policy_denied"
            obs["response"] = dict(self.world.deny_body)
            obs["response_digest"] = sha_json(obs["response"])
            return obs
        rows = self.visible_rows(eff, obs)
        response = {"objects": [], "result": "ok",
                    "meta": {"result_count": len(rows),
                             "total_count": len(rows),
                             "ranks": [{"id": e["id"], "rank": i + 1}
                                       for i, e in enumerate(
                                           sorted(rows,
                                                  key=lambda e: e["id"]))],
                             "snippets": [{"id": e["id"],
                                           "snippet": self.world.objects[
                                               (e["id"], e["version"])]
                                           ["content"][:24]}
                                          for e in sorted(
                                              rows,
                                              key=lambda e: e["id"])]}}
        obs["decision"] = "allow"
        obs["response"] = response
        obs["response_digest"] = sha_json(response)
        return obs

    def op_background_reindex(self, scope: str, obs: dict) -> dict:
        """Background job under a per-scope indexer authorization context;
        writes are scope-bound and must preserve provenance (ISO5/ISO6)."""
        obs["policy_checks"].append("indexer_scope_context")
        entries = self.entries_of_scope(scope)
        rebuilt = []
        for entry in entries:
            obj = self.world.objects[(entry["id"], entry["version"])]
            rebuilt.append({
                "id": entry["id"], "version": entry["version"],
                "scope": entry["scope"], "kind": entry["kind"],
                "provenance": dict(obj["provenance"]),
            })
            self.metrics["index_writes_scope_bound"] += 1
        self.metrics["policy_evaluations"] += 1
        return {"scope": scope, "entries": rebuilt,
                "provenance_preserved":
                    all(len(r["provenance"]) == 5 for r in rebuilt)}

    # -- fault injection (blast radius, D6) ---------------------------------
    def fault_predicate_bypass(self) -> int:
        """Model each topology's worst-case single retrieval-isolation
        regression and count the scopes able to observe unauthorized
        content through the real retrieval paths.

        shared_rls: the row-level scope predicate is skipped on the
        shared index -> an authorized caller of ANY scope can pull
        foreign rows by id -> potentially all scopes affected.
        per_scope: the analogous single fault is a misfiled projection -
        one foreign entry lands in one wrong scope's own index -> only
        that scope's callers can observe it."""
        affected = set()
        if self.name == "shared_rls":
            real_predicate = self._predicate
            self._predicate = lambda entry, eff: entry["active"]
            try:
                for actor, members in self.world.memberships.items():
                    if not members:
                        continue
                    obs = self.retrieve(actor, "q-pilot", "mem-0101-beta")
                    if obs["decision"] == "allow" and any(
                            o["scope"] != obs["effective_scope"]
                            for o in obs["response"]["objects"]):
                        affected.add(obs["effective_scope"])
            finally:
                self._predicate = real_predicate
        else:
            idx = self.indexes.get("SCP-A", {})
            save = idx.get("mem-0101-beta")
            # misfiled projection: the foreign entry lands in SCP-A's own
            # index while retaining its canonical scope binding
            idx["mem-0101-beta"] = [{"id": "mem-0101-beta", "version": 1,
                                     "scope": "SCP-B",
                                     "kind": "memory_record",
                                     "active": True}]
            try:
                obs = self.retrieve("alice", "q-pilot", "mem-0101-beta")
                if obs["decision"] == "allow" and any(
                        o["scope"] != obs["effective_scope"]
                        for o in obs["response"]["objects"]):
                    affected.add(obs["effective_scope"])
            finally:
                if save is None:
                    idx.pop("mem-0101-beta", None)
                else:
                    idx["mem-0101-beta"] = save
        return len(affected)

    def fault_corrupt_entry(self, scope: str, target_id: str) -> int:
        """Flip the digest of one index entry; count the scopes whose
        authorized retrieval can observe the corrupted content."""
        affected = 0
        self.corrupt_targets = getattr(self, "corrupt_targets", {})
        self.corrupt_targets[(scope, target_id)] = "deadbeef" * 8
        try:
            for actor, members in self.world.memberships.items():
                if not members:
                    continue
                obs = self.retrieve(actor, "q-common", target_id)
                if obs["decision"] == "allow":
                    for obj in obs["response"]["objects"]:
                        real = _sha(self.world.objects[
                            (obj["id"], obj["version"])]
                            ["content"].encode())
                        if obj["digest"] != real:
                            affected += 1
        finally:
            self.corrupt_targets.pop((scope, target_id), None)
        return affected


class PerScopeVariant(VariantBase):
    """One index projection per canonical scope; retrieval touches only
    the caller's own scope index.  A foreign/nonexistent id is a miss in
    the own-scope index without probing other scopes."""

    name = "per_scope"

    def build_index(self) -> None:
        self.indexes = {s: {} for s in self.world.scopes}
        for (oid, version), obj in self.world.objects.items():
            if obj["status"] == "active":
                self.indexes[obj["scope"]].setdefault(oid, []).append({
                    "id": oid, "version": version, "scope": obj["scope"],
                    "kind": obj["kind"], "active": True,
                })

    def lookup_entries(self, eff: str, target_id: str, obs: dict) -> list:
        own = self.indexes.get(eff, {})
        obs["rows_scanned"] = len(own.get(target_id, []))
        self.metrics["rows_scanned"] += obs["rows_scanned"]
        return list(own.get(target_id, []))

    def visible_rows(self, eff: str, obs: dict) -> list:
        rows = [e for entries in self.indexes.get(eff, {}).values()
                for e in entries if e["active"]]
        obs["rows_scanned"] = len(rows)
        self.metrics["rows_scanned"] += len(rows)
        return rows

    def all_entries(self) -> list:
        return [e for entries in self.indexes.values()
                for e in entries.values() for e in e]

    def entries_of_scope(self, scope: str) -> list:
        return [e for entries in self.indexes.get(scope, {}).values()
                for e in entries]

    def remove_entries(self, scope: str, target_id: str) -> None:
        self.indexes.get(scope, {}).pop(target_id, None)

    def rebind_entry_scope(self, from_scope: str, to_scope: str,
                           target_id: str) -> None:
        entries = self.indexes.get(from_scope, {}).pop(target_id, None)
        if entries:
            for e in entries:
                e["scope"] = to_scope
            self.indexes.setdefault(to_scope, {})[target_id] = entries

    def index_version(self, scope: str, target_id: str, version: int) -> None:
        obj = self.world.objects[(target_id, version)]
        self.indexes.setdefault(scope, {})[target_id] = [{
            "id": target_id, "version": version, "scope": scope,
            "kind": obj["kind"], "active": True}]

    def storage_state(self) -> dict:
        entries = sum(len(v) for idx in self.indexes.values()
                      for v in idx.values())
        payload_bytes = 0
        for idx in self.indexes.values():
            payload_bytes += INDEX_FIXED_OVERHEAD_BYTES
            for versions in idx.values():
                for e in versions:
                    payload_bytes += len(canonical(e))
        return {"index_count": len(self.indexes),
                "index_entries": entries,
                "payload_bytes_est": payload_bytes}


class SharedRLSVariant(VariantBase):
    """One shared index over all scopes; a row-level policy predicate
    (entry.scope == effective scope, epoch current) is applied per row
    during retrieval before any materialization."""

    name = "shared_rls"

    def build_index(self) -> None:
        self.index = {}
        for (oid, version), obj in self.world.objects.items():
            if obj["status"] == "active":
                self.index.setdefault(oid, []).append({
                    "id": oid, "version": version, "scope": obj["scope"],
                    "kind": obj["kind"], "active": True,
                })

    def _predicate(self, entry: dict, eff: str) -> bool:
        # row-level predicate; a stale (pre-invalidation) row fails here
        return entry["active"] and entry["scope"] == eff

    def lookup_entries(self, eff: str, target_id: str, obs: dict) -> list:
        candidates = self.index.get(target_id, [])
        obs["rows_scanned"] = len(candidates)
        self.metrics["rows_scanned"] += len(candidates)
        return [e for e in candidates if self._predicate(e, eff)]

    def visible_rows(self, eff: str, obs: dict) -> list:
        rows = []
        for entries in self.index.values():
            for e in entries:
                obs["rows_scanned"] += 1
                self.metrics["rows_scanned"] += 1
                if self._predicate(e, eff):
                    rows.append(e)
        return rows

    def all_entries(self) -> list:
        return [e for entries in self.index.values() for e in entries]

    def entries_of_scope(self, scope: str) -> list:
        return [e for entries in self.index.values() for e in entries
                if e["scope"] == scope]

    def remove_entries(self, scope: str, target_id: str) -> None:
        self.index.pop(target_id, None)

    def rebind_entry_scope(self, from_scope: str, to_scope: str,
                           target_id: str) -> None:
        for e in self.index.get(target_id, []):
            if e["scope"] == from_scope:
                e["scope"] = to_scope

    def index_version(self, scope: str, target_id: str, version: int) -> None:
        obj = self.world.objects[(target_id, version)]
        self.index[target_id] = [{
            "id": target_id, "version": version, "scope": scope,
            "kind": obj["kind"], "active": True}]

    def storage_state(self) -> dict:
        entries = sum(len(v) for v in self.index.values())
        payload_bytes = INDEX_FIXED_OVERHEAD_BYTES
        for versions in self.index.values():
            for e in versions:
                payload_bytes += len(canonical(e))
        return {"index_count": 1, "index_entries": entries,
                "payload_bytes_est": payload_bytes}


# --------------------------------------------------------------------------
# probe candidates (adversarial; single-invariant violations)
# --------------------------------------------------------------------------

class ProbeAExistenceOracle(SharedRLSVariant):
    """Probe A candidate: deny responses distinguish a valid foreign id
    from a nonexistent id via an error detail field (existence oracle)."""

    name = "probeA_existence_oracle"

    def retrieve(self, actor: str, query_id: str, target_id: str,
                 version=None, claimed_scope=None, op: str = "retrieve",
                 *, cache_revalidate: bool = True) -> dict:
        obs = super().retrieve(actor, query_id, target_id, version,
                               claimed_scope, op,
                               cache_revalidate=cache_revalidate)
        if obs["decision"] == "deny":
            body = dict(obs["response"])
            body["detail"] = "object_exists_but_denied" \
                if self.index.get(target_id) else "no_such_object"
            obs["response"] = body
            obs["response_digest"] = sha_json(body)
        return obs


class ProbeBStaleCache(SharedRLSVariant):
    """Probe B candidate: cache hits skip the policy/epoch revalidation,
    so a revoked object is served from the stale cache entry."""

    name = "probeB_stale_cache"

    def retrieve(self, actor: str, query_id: str, target_id: str,
                 version=None, claimed_scope=None, op: str = "retrieve",
                 *, cache_revalidate: bool = True) -> dict:
        return super().retrieve(actor, query_id, target_id, version,
                                claimed_scope, op, cache_revalidate=False)


class ProbeCPostFilter(SharedRLSVariant):
    """Probe C candidate: aggregation/pagination totals and highlights are
    computed over ALL shared-index rows BEFORE the policy predicate and
    attached to the response meta (content list may still be filtered)."""

    name = "probeC_postfilter"

    def _leaky_meta(self) -> dict:
        all_rows = [e for entries in self.index.values() for e in entries
                    if e["active"]]
        all_rows.sort(key=lambda e: e["id"])
        return {"result_count": len(all_rows),
                "total_count": len(all_rows),
                "ranks": [{"id": e["id"], "rank": i + 1}
                          for i, e in enumerate(all_rows)],
                "snippets": [{"id": e["id"],
                              "snippet": self.world.objects[
                                  (e["id"], e["version"])]["content"][:24]}
                             for e in all_rows]}

    def op_aggregate(self, actor: str, query_id: str) -> dict:
        obs = super().op_aggregate(actor, query_id)
        if obs["decision"] == "allow":
            obs["response"] = dict(obs["response"])
            obs["response"]["meta"] = self._leaky_meta()
            obs["response_digest"] = sha_json(obs["response"])
        return obs

    def op_paginate(self, actor: str, query_id: str, offset: int,
                    limit: int) -> dict:
        obs = super().op_paginate(actor, query_id, offset, limit)
        if obs["decision"] == "allow":
            obs["response"] = dict(obs["response"])
            obs["response"]["meta"] = self._leaky_meta()
            obs["response_digest"] = sha_json(obs["response"])
        return obs


class ProbeDForgedScopeProvenanceLoss(PerScopeVariant):
    """Probe D candidate: (a) a caller-supplied scope is accepted as the
    effective scope (privilege widening); (b) the background reindex drops
    the provenance tuple from projected entries."""

    name = "probeD_forged_scope_provenance_loss"

    def resolve_effective_scope(self, actor: str, claimed_scope, obs: dict):
        if claimed_scope is not None:
            # violation: caller input becomes the effective scope
            obs["policy_checks"].append("scope_resolution_caller_supplied")
            alias = {self.world.scope_ids[s]: s for s in self.world.scopes}
            short = alias.get(claimed_scope, claimed_scope)
            if short in self.world.scopes:
                return short, None
            return None, "unknown_scope"
        return super().resolve_effective_scope(actor, None, obs)

    def op_background_reindex(self, scope: str, obs: dict) -> dict:
        result = super().op_background_reindex(scope, obs)
        # violation: projection drops provenance
        result["entries"] = [{k: v for k, v in e.items()
                              if k != "provenance"}
                             for e in result["entries"]]
        result["provenance_preserved"] = False
        # the dropped provenance must also change what later materialize()
        # returns: emulate the lost binding in the index entries
        for entries in self.indexes.get(scope, {}).values():
            for e in entries:
                e["provenance_lost"] = True
        return result

    def materialize(self, entry: dict, query_id: str, obs: dict) -> dict:
        body = super().materialize(entry, query_id, obs)
        if entry.get("provenance_lost"):
            body["objects"][0]["provenance"] = {}
        return body


PROBE_CANDIDATES = {
    "A_existence_oracle": ProbeAExistenceOracle,
    "B_stale_cache": ProbeBStaleCache,
    "C_postfilter": ProbeCPostFilter,
    "D_forged_scope_provenance_loss": ProbeDForgedScopeProvenanceLoss,
}

PROBE_CASES = {
    "A_existence_oracle": ["foreign-id-valid", "nonexistent-id-control"],
    "B_stale_cache": ["revoke-stale-cache"],
    "C_postfilter": ["pagination-leak", "count-rank-snippet-aggregation"],
    "D_forged_scope_provenance_loss": ["forged-scope-param",
                                       "background-reindex-provenance",
                                       "same-scope-authorized"],
}

PROBE_SEEDS = [101]


# --------------------------------------------------------------------------
# case execution
# --------------------------------------------------------------------------

def execute_case(variant: VariantBase, case: dict, seed: int) -> dict:
    observations = []
    rng = random.Random(seed)
    for step in case["steps"]:
        op = step["op"]
        if op == "retrieve":
            obs = variant.retrieve(step["actor"], step["query_id"],
                                   step["target_id"],
                                   version=step.get("version"),
                                   claimed_scope=step.get("claimed_scope"))
        elif op == "revoke":
            obs = {"op": "revoke", "scope": step["scope"],
                   "target_id": step["target_id"], "policy_checks": [],
                   "cache_events": [],
                   "materialize_before_policy_check": 0, "rows_scanned": 0,
                   "policy_epoch_at_step": dict(variant.epochs)}
            variant.op_revoke(step["scope"], step["target_id"], obs)
        elif op == "move":
            obs = {"op": "move", "from_scope": step["from_scope"],
                   "to_scope": step["to_scope"],
                   "target_id": step["target_id"], "policy_checks": [],
                   "cache_events": [],
                   "materialize_before_policy_check": 0, "rows_scanned": 0,
                   "policy_epoch_at_step": dict(variant.epochs)}
            variant.op_move(step["from_scope"], step["to_scope"],
                            step["target_id"], obs)
        elif op == "supersede":
            obs = {"op": "supersede", "scope": step["scope"],
                   "target_id": step["target_id"],
                   "new_version": step["new_version"], "policy_checks": [],
                   "cache_events": [],
                   "materialize_before_policy_check": 0, "rows_scanned": 0,
                   "policy_epoch_at_step": dict(variant.epochs)}
            variant.op_supersede(step["scope"], step["target_id"],
                                 step["new_version"], obs)
        elif op == "paginate":
            obs = variant.op_paginate(step["actor"], step["query_id"],
                                      step["offset"], step["limit"])
        elif op == "aggregate":
            obs = variant.op_aggregate(step["actor"], step["query_id"])
        elif op == "bulk":
            ids = list(step["target_ids"])
            rng.shuffle(ids)
            sub = variant.op_bulk(step["actor"], ids, "q-common")
            for s in sub:
                s["bulk_order_shuffled_by_seed"] = True
            observations.extend(sub)
            observations.append({
                "op": "bulk_summary", "actor": step["actor"],
                "order": ids, "per_id_decisions":
                    [o["decision"] for o in sub]})
            continue
        elif op == "background_reindex":
            obs = {"op": "background_reindex", "actor": step["actor"],
                   "scope": step["scope"], "policy_checks": [],
                   "cache_events": [],
                   "materialize_before_policy_check": 0, "rows_scanned": 0,
                   "policy_epoch_at_step": dict(variant.epochs)}
            result = variant.op_background_reindex(step["scope"], obs)
            obs["reindex_result"] = result
        else:
            raise RuntimeError(f"unknown op {op}")
        observations.append(obs)
    return {
        "schema": SCHEMA_RUN,
        "run_id": f"{variant.name}|{case['id']}|{seed}",
        "variant": variant.name,
        "case_id": case["id"],
        "seed": seed,
        "observations": observations,
        "metrics": dict(variant.metrics),
        "final_state": {"storage": variant.storage_state(),
                        "cache_entries": len(variant.cache)},
        "iso_counters": derive_iso_counters(case, observations),
    }


def derive_iso_counters(case: dict, observations: list) -> dict:
    """Runner-side summary only.  The evaluator re-derives all counters
    from the raw observations with its own independent model and never
    trusts these numbers."""
    counters = {k: 0 for k in ISO_KEYS}
    return counters


def run_matrix(mode: str) -> list:
    manifest = json.loads(
        (TICKET / "corpus-manifest.json").read_text(encoding="utf-8"))
    cases = manifest["cases"]
    seeds = manifest["seeds"]
    variants = manifest["variants"]
    world = load_world()
    runs = []
    for variant_name in variants:
        cls = {"per_scope": PerScopeVariant,
               "shared_rls": SharedRLSVariant}[variant_name]
        for seed in seeds:
            # one fresh variant instance per run for cache-state isolation
            for case in cases:
                instance = cls(world)
                runs.append(execute_case(instance, case, seed))
    return runs


def run_timing_probe() -> dict:
    """Bounded real-clock existence-oracle probe per the frozen methodology
    in isolation-contract.timing_probe_contract plus runner TIMING
    parameters.  This section is explicitly NOT part of any run digest."""
    world = load_world()
    out = {"schema": "agentos.s1-007.timing/v1", "methodology": {
        "sample_count": TIMING["sample_count"], "warmup": TIMING["warmup"],
        "inner_repeats": TIMING["inner_repeats"],
        "seeds": TIMING["seeds"], "statistic": "median_of_seed_medians",
        "clock": "time.perf_counter_ns", "note":
            "bounded local wall-clock measurement of the simulated retrieval "
            "path; never a production SLO or exploitability claim"}}
    contract = json.loads((TICKET / "isolation-contract.json")
                          .read_text(encoding="utf-8"))
    tolerance_rule = contract["timing_probe_contract"]["tolerance"]
    out["frozen_tolerance"] = tolerance_rule
    results = {}
    for variant_name, cls in (("per_scope", PerScopeVariant),
                              ("shared_rls", SharedRLSVariant)):
        arms = {}
        for arm, target in (("valid_foreign_id", "mem-0001-alpha"),
                            ("nonexistent_id", "mem-does-not-exist")):
            per_seed = []
            for seed in TIMING["seeds"]:
                instance = cls(world)
                actor = "bruno"  # member of SCP-B only: target is foreign
                for _ in range(TIMING["warmup"]):
                    instance.retrieve(actor, "q-runbook", target)
                samples = []
                for _ in range(TIMING["sample_count"]):
                    t0 = time.perf_counter_ns()
                    for _ in range(TIMING["inner_repeats"]):
                        instance.retrieve(actor, "q-runbook", target)
                    samples.append(
                        (time.perf_counter_ns() - t0) // TIMING["inner_repeats"])
                samples.sort()
                per_seed.append({
                    "seed": seed,
                    "median_ns": samples[len(samples) // 2],
                    "p10_ns": samples[len(samples) // 10],
                    "p90_ns": samples[(len(samples) * 9) // 10],
                    "sample_count": len(samples)})
            per_seed.sort(key=lambda r: r["median_ns"])
            arms[arm] = {"per_seed": per_seed,
                         "median_ns":
                             per_seed[len(per_seed) // 2]["median_ns"]}
        foreign = arms["valid_foreign_id"]["median_ns"]
        control = arms["nonexistent_id"]["median_ns"]
        signal = abs(foreign - control)
        floor = tolerance_rule["absolute_floor_ns"]
        tol = max(tolerance_rule["relative"] * control, floor)
        results[variant_name] = {
            "arms": arms, "signal_ns": signal,
            "tolerance_ns": round(tol),
            "verdict": ("WITHIN_TOLERANCE" if signal <= tol
                        else "SIGNAL_ABOVE_TOLERANCE"),
            "power_note": f"{TIMING['sample_count']} samples x "
                          f"{TIMING['inner_repeats']} inner repeats x "
                          f"{len(TIMING['seeds'])} seeds per arm",
        }
    out["variants"] = results
    return out


def run_probes() -> dict:
    world = load_world()
    manifest = json.loads(
        (TICKET / "corpus-manifest.json").read_text(encoding="utf-8"))
    cases_by_id = {c["id"]: c for c in manifest["cases"]}
    probes = []
    for probe_id, cls in PROBE_CANDIDATES.items():
        runs = []
        for case_id in PROBE_CASES[probe_id]:
            for seed in PROBE_SEEDS:
                instance = cls(world)
                runs.append(execute_case(instance, cases_by_id[case_id],
                                         seed))
        probes.append({"probe": probe_id, "candidate": cls.name,
                       "runs": runs})
    # Probe R: blast-radius fault injection through real retrieval paths
    faults = {}
    for variant_name, cls in (("per_scope", PerScopeVariant),
                              ("shared_rls", SharedRLSVariant)):
        instance = cls(world)
        bypass = instance.fault_predicate_bypass()
        corrupt = instance.fault_corrupt_entry("SCP-C", "mem-0201-gamma")
        faults[variant_name] = {
            "predicate_bypass_affected_scopes": bypass,
            "corrupt_entry_affected_scopes": corrupt,
        }
    doc = {"schema": SCHEMA_PROBES, "probes": probes,
           "fault_injection": faults,
           "probe_hashes": {p["probe"]: [r["run_id"] for r in p["runs"]]
                            for p in probes}}
    return doc


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def execute_matrix(out_dir: Path, mode: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    runs = run_matrix(mode)
    runs_dir = out_dir / "runs"
    runs_dir.mkdir(exist_ok=True)
    prov = provenance()
    contracts = contract_hashes()
    entries = []
    for run in runs:
        payload = dict(run)
        payload["provenance_digest"] = prov["environment_hash"]
        payload["contract_hashes"] = contracts
        path = runs_dir / f"{run['run_id'].replace('|', '__')}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        entries.append({"run_id": run["run_id"], "path": path.name,
                        "sha256": _sha(path.read_bytes())})
    timing = run_timing_probe()
    (out_dir / "timing.json").write_text(
        json.dumps(timing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_doc = {
        "schema": SCHEMA_MANIFEST,
        "mode": mode,
        "executor_id": prov["executor_id"],
        "provenance": prov,
        "contract_hashes": contracts,
        "matrix": {"variants": ["per_scope", "shared_rls"],
                   "cases": [c["id"] for c in json.loads(
                       (TICKET / "corpus-manifest.json").read_text(
                           encoding="utf-8"))["cases"]],
                   "seeds": [101, 202, 303]},
        "runs": entries,
        "timing_path": "timing.json",
        "timing_sha256": _sha((out_dir / "timing.json").read_bytes()),
        "manifest_digest": None,
    }
    manifest_path = out_dir / "run-manifest.json"
    manifest_doc["manifest_digest"] = _sha(json.dumps(
        {k: v for k, v in manifest_doc.items() if k != "manifest_digest"},
        sort_keys=True, separators=(",", ":")).encode())
    manifest_path.write_text(
        json.dumps(manifest_doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest_doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("main", "rerun", "probes"),
                    required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    out = Path(args.out)
    if args.mode == "probes":
        doc = run_probes()
        out.mkdir(parents=True, exist_ok=True)
        (out / "probes.json").write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"probes: {len(doc['probes'])} adversarial candidates, "
              f"faults={json.dumps(doc['fault_injection'])}")
        return 0
    doc = execute_matrix(out, args.mode)
    print(f"{args.mode}: {len(doc['runs'])} runs -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
