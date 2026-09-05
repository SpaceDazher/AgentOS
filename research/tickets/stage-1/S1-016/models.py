"""S1-016 lineage representations A/B/C + deterministic simulator core.

All three representations implement one observable operation contract over the
same canonical vocabulary. They share the commit core below and differ only
in auxiliary runtime structures (which the complexity proxy measures):

- A FLAT_RUNTIME_PROV_EXPORT: single scope column, membership table, op log.
- B RICH_RUNTIME_PROV_DICTIONARY: plus authoritative dictionary/member/
  insertion/removal runtime objects with a query API (scope stays separate).
- C HYBRID_MINIMAL_LINEAGE: flat state plus a minimal append-only lineage
  relation/event table; the materialized graph cache is droppable.

Crash semantics: two-phase commit (stage state, stage events, commit
atomically). Crash before_commit leaves nothing; crash after_state_before_
event stages state without events (outcome UNKNOWN). Reconciliation with the
same idempotency key completes staged effects exactly once and emits the
missing events. Blind retry is refused; replays return the original digest.
"""
from __future__ import annotations

import hashlib
import json

REPS = ("A", "B", "C")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def scope_key(scope: dict) -> str:
    return f"{scope['tenant_id']}/{scope['workspace_id']}/{scope['goal_id']}"


TABLE_COUNTS = {"A": 4, "B": 8, "C": 6}
CONSTRAINT_COUNTS = {"A": 9, "B": 17, "C": 12}
QUERY_ENTRY_POINTS = {"A": 2, "B": 5, "C": 3}


class Reject(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Model:
    """One representation instance over an initially empty canonical state."""

    def __init__(self, rep: str):
        assert rep in REPS
        self.rep = rep
        self.versions: dict[tuple, dict] = {}
        self.collections: dict[str, dict] = {}
        self.operations: list[dict] = []
        self.events: list[dict] = []
        self.idempotency: dict[str, dict] = {}
        self.staged: list[dict] = []
        self.checks_executed = 0
        self.query_steps = 0
        # B structures.
        self.dictionaries: dict[str, dict] = {}
        # C structures.
        self.relations: list[dict] = []
        self.relation_events: list[dict] = []
        self.graph_cache: dict | None = None

    # -- internal helpers -------------------------------------------------
    def _check(self) -> None:
        self.checks_executed += 1

    def _scope_of_version(self, obj: str, ver: int) -> str:
        self._check()
        key = (obj, ver)
        if key not in self.versions:
            raise Reject("unknown_reference")
        return scope_key(self.versions[key]["scope"])

    @staticmethod
    def _id_ok(*values) -> None:
        """Identity-shaped arguments must be plain relative IDs."""
        import re as _re
        for value in values:
            if not isinstance(value, str) or not value or len(value) > 256:
                raise Reject("malformed_id")
            if value.startswith("-") or value.startswith("/") or \
                    "\\" in value or "\x00" in value or \
                    _re.search(r"(^|/)\.\.(/|$)", value):
                raise Reject("traversal")

    def _emit(self, staged_events: list[dict]) -> None:
        for event in staged_events:
            event = dict(event)
            event["seq"] = len(self.events)
            self.events.append(event)
            if self.rep == "C":
                self.relation_events.append(dict(event))

    def _relate(self, from_kind, from_id, to_kind, to_id, op_seq, rel) -> None:
        if self.rep == "C":
            self.relations.append({"from_kind": from_kind, "from_id": from_id,
                                   "to_kind": to_kind, "to_id": to_id,
                                   "op_seq": op_seq, "rel": rel})
            self.graph_cache = None

    # -- commit core ------------------------------------------------------
    def apply(self, op: dict, auth_scope: dict) -> dict:
        """Apply one canonical operation; returns the outcome record."""
        key = op["idempotency_key"]
        if key in self.idempotency:
            prior = self.idempotency[key]
            return {"outcome": "duplicate_replay", "digest": prior["digest"],
                    "reason": None, "op_seq": prior["seq"]}
        crash = op.get("crash_point") or "none"
        seq = len(self.operations)
        try:
            if crash not in ("none", "before_commit", "after_state_before_event"):
                raise Reject("unknown_crash_point")
            for parent in op.get("causal_parents", []):
                self._check()
                if not isinstance(parent, int) or parent < 0 or parent >= seq:
                    raise Reject("causal_order")
                if self.operations[parent]["outcome"] != "committed":
                    raise Reject("causal_order")
            staged_state, staged_events = self._stage(op, auth_scope, seq)
        except Reject as exc:
            record = {"seq": seq, "op_id": op["op_id"], "op_type": op["op_type"],
                      "outcome": f"rejected:{exc.reason}", "events": [],
                      "digest": sha(canonical({"op": op["op_id"], "r": exc.reason}))}
            self.operations.append(record)
            self.idempotency[key] = record
            return {"outcome": record["outcome"], "digest": record["digest"],
                    "reason": exc.reason, "op_seq": seq}
        if crash == "before_commit":
            # Nothing was staged or committed: the outcome is UNKNOWN and a
            # retry with the same idempotency key must complete exactly once.
            unknown = {"seq": seq, "op_id": op["op_id"], "op_type": op["op_type"],
                       "outcome": "unknown", "events": [],
                       "digest": sha(canonical({"op": op["op_id"], "u": "crash"}))}
            self.operations.append(unknown)
            return {"outcome": "unknown", "digest": unknown["digest"],
                    "reason": "crash_before_commit", "op_seq": seq,
                    "retry_op": op}
        for staged_event in staged_events:
            staged_event.setdefault("auth_scope", scope_key(auth_scope))
        self._commit_state(staged_state)
        if crash == "after_state_before_event":
            self.staged.append({"op": op, "seq": seq, "events": staged_events,
                                "state": staged_state})
            unknown = {"seq": seq, "op_id": op["op_id"], "op_type": op["op_type"],
                       "outcome": "unknown", "events": [],
                       "digest": sha(canonical({"op": op["op_id"], "u": "half"}))}
            self.operations.append(unknown)
            return {"outcome": "unknown", "digest": unknown["digest"],
                    "reason": "crash_after_state_before_event", "op_seq": seq,
                    "retry_op": op}
        self._emit(staged_events)
        record = {"seq": seq, "op_id": op["op_id"], "op_type": op["op_type"],
                  "outcome": "committed",
                  "events": [e["kind"] for e in staged_events],
                  "digest": sha(canonical({"op": op["op_id"], "seq": seq,
                                           "ev": [e["kind"] for e in staged_events]}))}
        self.operations.append(record)
        self.idempotency[key] = record
        return {"outcome": "committed", "digest": record["digest"],
                "reason": None, "op_seq": seq}

    def reconcile(self, op: dict) -> dict:
        """Resolve an UNKNOWN outcome for the same idempotency key, exactly once."""
        key = op["idempotency_key"]
        if key in self.idempotency and \
                self.idempotency[key]["outcome"] == "committed":
            prior = self.idempotency[key]
            return {"outcome": "duplicate_replay", "digest": prior["digest"],
                    "reason": None, "op_seq": prior["seq"]}
        for i, item in enumerate(self.staged):
            if item["op"]["idempotency_key"] == key:
                self.staged.pop(i)
                self._emit(item["events"])
                record = {"seq": item["seq"], "op_id": op["op_id"],
                          "op_type": op["op_type"], "outcome": "committed",
                          "events": [e["kind"] for e in item["events"]],
                          "digest": sha(canonical(
                              {"op": op["op_id"], "seq": item["seq"], "reconciled": True}))}
                # Replace the earlier unknown record in place.
                self.operations[item["seq"]] = record
                self.idempotency[key] = record
                return {"outcome": "committed", "digest": record["digest"],
                        "reason": "reconciled", "op_seq": item["seq"]}
        # Crash before commit staged nothing: re-apply through the normal path.
        for record in self.operations:
            if record["op_id"] == op["op_id"] and record["outcome"] == "unknown":
                self.operations.remove(record)
                break
        return self.apply(op, self._auth_of(op))

    def _auth_of(self, op: dict) -> dict:
        return op["_auth_scope"]

    # -- staging (pure transition proposal; no mutation) -------------------
    def _stage(self, op: dict, auth: dict, seq: int):
        handler = getattr(self, "_op_" + op["op_type"], None)
        if handler is None:
            raise Reject("unknown_operation")
        return handler(op, auth, seq)

    def _new_version(self, obj, content, scope, supersedes, label, seq):
        self._check()
        ver = 1
        while (obj, ver) in self.versions:
            ver += 1
        version = {"id": obj, "version": ver, "scope": dict(scope),
                   "content_digest": sha(content.encode("utf-8")),
                   "content": content, "supersedes": supersedes,
                   "state": "active", "label": label,
                   "created_by_op": seq}
        return (obj, ver), version

    def _op_create(self, op, auth, seq):
        a = op["args"]
        self._id_ok(a.get("obj_id"))
        if a.get("scope") != auth:
            raise Reject("forged_scope")
        if (a["obj_id"], 1) in self.versions:
            raise Reject("duplicate_version")
        key, version = self._new_version(a["obj_id"], a["content"], auth, None,
                                         a.get("label", ""), seq)
        events = [{"kind": "create", "version": [key[0], key[1]],
                   "scope": scope_key(auth), "op_seq": seq}]
        self._relate("operation", op["op_id"], "version", f"{key[0]}@{key[1]}",
                     seq, "generated")
        return {"versions": {key: version}, "collections": {}}, events

    def _op_insert(self, op, auth, seq):
        a = op["args"]
        self._id_ok(a.get("collection"), a.get("member_obj"), a.get("key"))
        coll = self.collections.get(a["collection"])
        if coll is None:
            raise Reject("unknown_reference")
        self._check()
        if scope_key(coll["scope"]) != scope_key(auth):
            raise Reject("forged_scope")
        mkey = (a["member_obj"], a["member_ver"])
        if mkey not in self.versions:
            raise Reject("unknown_reference")
        self._check()
        if scope_key(self.versions[mkey]["scope"]) != scope_key(auth):
            raise Reject("forged_scope")
        for member in coll["members"]:
            if member["removed_by"] is None and (
                    member["key"] == a["key"] or member["member"] == [mkey[0], mkey[1]]):
                raise Reject("duplicate_insertion")
        member = {"member": [mkey[0], mkey[1]], "key": a["key"],
                  "inserted_by": op["op_id"], "removed_by": None}
        events = [{"kind": "insert", "collection": a["collection"],
                   "member": [mkey[0], mkey[1]], "key": a["key"], "op_seq": seq}]
        self._relate("version", f"{mkey[0]}@{mkey[1]}", "collection", a["collection"],
                     seq, "member_inserted")
        if self.rep == "B":
            events.append({"kind": "dict_insert", "collection": a["collection"],
                           "key": a["key"], "member": [mkey[0], mkey[1]], "op_seq": seq})
        return {"versions": {}, "collections": {a["collection"]: [member]}}, events

    def _op_remove(self, op, auth, seq):
        a = op["args"]
        self._id_ok(a.get("collection"))
        if a.get("key") is not None:
            self._id_ok(a.get("key"))
        coll = self.collections.get(a["collection"])
        if coll is None:
            raise Reject("unknown_reference")
        self._check()
        if scope_key(coll["scope"]) != scope_key(auth):
            raise Reject("forged_scope")
        target = None
        for member in coll["members"]:
            if member["removed_by"] is None and (
                    member["key"] == a.get("key") or member["member"] == a.get("member")):
                target = member
                break
        if target is None:
            # Distinguish repeated deletion (interval already closed) from
            # unknown references for exact failure semantics.
            for member in coll["members"]:
                if member["removed_by"] is not None and (
                        member["key"] == a.get("key") or member["member"] == a.get("member")):
                    raise Reject("already_removed")
            raise Reject("unknown_reference")
        close = {"member_key": target["key"], "removed_by": op["op_id"]}
        events = [{"kind": "remove", "collection": a["collection"],
                   "member": target["member"], "key": target["key"], "op_seq": seq}]
        self._relate("collection", a["collection"], "version",
                     f"{target['member'][0]}@{target['member'][1]}", seq, "member_removed")
        if self.rep == "B":
            events.append({"kind": "dict_remove", "collection": a["collection"],
                           "key": target["key"], "op_seq": seq})
        return {"versions": {}, "collections": {a["collection"]: [close]}}, events

    def _op_update_supersede(self, op, auth, seq):
        a = op["args"]
        self._id_ok(a.get("obj_id"))
        prev = self._latest(a["obj_id"])
        if prev is None:
            raise Reject("unknown_reference")
        self._check()
        if scope_key(self.versions[prev]["scope"]) != scope_key(auth):
            raise Reject("forged_scope")
        key, version = self._new_version(a["obj_id"], a["content"], auth,
                                         [prev[0], prev[1]], a.get("label", ""), seq)
        events = [{"kind": "supersede", "version": [key[0], key[1]],
                   "supersedes": [prev[0], prev[1]], "op_seq": seq}]
        self._relate("version", f"{prev[0]}@{prev[1]}", "version",
                     f"{key[0]}@{key[1]}", seq, "superseded_by")
        return {"versions": {key: version}, "collections": {}}, events

    def _latest(self, obj):
        ver = 0
        while (obj, ver + 1) in self.versions:
            ver += 1
        return (obj, ver) if ver else None

    def _op_copy_same_scope(self, op, auth, seq):
        a = op["args"]
        self._id_ok(a.get("src_obj"), a.get("new_obj"))
        src = (a["src_obj"], a["src_ver"])
        if src not in self.versions:
            raise Reject("unknown_reference")
        self._check()
        if scope_key(self.versions[src]["scope"]) != scope_key(auth):
            raise Reject("forged_scope")
        if (a["new_obj"], 1) in self.versions:
            raise Reject("duplicate_version")
        content = self.versions[src]["content"]
        key, version = self._new_version(a["new_obj"], content, auth, None,
                                         a.get("label", ""), seq)
        events = [{"kind": "copy", "src": [src[0], src[1]],
                   "dst": [key[0], key[1]], "op_seq": seq}]
        self._relate("version", f"{src[0]}@{src[1]}", "version",
                     f"{key[0]}@{key[1]}", seq, "copied_to")
        return {"versions": {key: version}, "collections": {}}, events

    def _op_copy_cross_scope(self, op, auth, seq):
        a = op["args"]
        self._id_ok(a.get("src_obj"), a.get("new_obj"))
        src = (a["src_obj"], a["src_ver"])
        if src not in self.versions:
            raise Reject("unknown_reference")
        if a.get("target_scope") != auth:
            raise Reject("forged_scope")
        self._check()
        if scope_key(self.versions[src]["scope"]) == scope_key(auth):
            raise Reject("wrong_op_use_same_scope_copy")
        if (a["new_obj"], 1) in self.versions:
            raise Reject("duplicate_version")
        content = self.versions[src]["content"]
        key, version = self._new_version(a["new_obj"], content, auth, None,
                                         a.get("label", ""), seq)
        events = [{"kind": "copy", "src": [src[0], src[1]],
                   "src_scope": scope_key(self.versions[src]["scope"]),
                   "dst": [key[0], key[1]], "dst_scope": scope_key(auth),
                   "op_seq": seq}]
        self._relate("version", f"{src[0]}@{src[1]}", "version",
                     f"{key[0]}@{key[1]}", seq, "copied_cross_scope")
        return {"versions": {key: version}, "collections": {}}, events

    def _op_move_cross_scope(self, op, auth, seq):
        a = op["args"]
        self._id_ok(a.get("src_obj"), a.get("new_obj"))
        src = (a["src_obj"], a["src_ver"])
        if src not in self.versions:
            raise Reject("unknown_reference")
        if a.get("target_scope") != auth:
            raise Reject("forged_scope")
        self._check()
        if scope_key(self.versions[src]["scope"]) == scope_key(auth):
            raise Reject("wrong_op_use_same_scope_copy")
        if (a["new_obj"], 1) in self.versions:
            raise Reject("duplicate_version")
        if self.versions[src]["state"] == "withdrawn":
            raise Reject("source_withdrawn")
        content = self.versions[src]["content"]
        key, version = self._new_version(a["new_obj"], content, auth, None,
                                         a.get("label", ""), seq)
        events = [{"kind": "copy", "src": [src[0], src[1]],
                   "src_scope": scope_key(self.versions[src]["scope"]),
                   "dst": [key[0], key[1]], "dst_scope": scope_key(auth),
                   "op_seq": seq},
                  {"kind": "withdraw", "version": [src[0], src[1]],
                   "reason": "moved", "tombstone": True, "op_seq": seq}]
        self._relate("version", f"{src[0]}@{src[1]}", "version",
                     f"{key[0]}@{key[1]}", seq, "moved_to")
        state = {"versions": {key: version,
                              src: {"__withdraw": True}}, "collections": {}}
        return state, events

    def _op_rename(self, op, auth, seq):
        a = op["args"]
        self._id_ok(a.get("obj_id"))
        latest = self._latest(a["obj_id"])
        if latest is None:
            raise Reject("unknown_reference")
        self._check()
        if scope_key(self.versions[latest]["scope"]) != scope_key(auth):
            raise Reject("forged_scope")
        events = [{"kind": "rename", "version": [latest[0], latest[1]],
                   "label": a["new_label"], "op_seq": seq}]
        return {"versions": {latest: {"__label": a["new_label"]}},
                "collections": {}}, events

    def _op_derive(self, op, auth, seq):
        a = op["args"]
        self._id_ok(a.get("new_obj"), *[s[0] for s in a.get("sources", [])])
        sources = [(s[0], s[1]) for s in a["sources"]]
        for src in sources:
            if src not in self.versions:
                raise Reject("unknown_reference")
        # Cycle check: the new object must not already exist upstream.
        if (a["new_obj"], 1) in self.versions:
            raise Reject("duplicate_version")
        for src in sources:
            self._check()
            if self.versions[src]["id"] == a["new_obj"]:
                raise Reject("causal_cycle")
        if a.get("scope") != auth:
            raise Reject("forged_scope")
        key, version = self._new_version(a["new_obj"], a["content"], auth, None,
                                         a.get("label", ""), seq)
        events = [{"kind": "derive", "dst": [key[0], key[1]],
                   "sources": [[s[0], s[1]] for s in sources], "op_seq": seq}]
        for src in sources:
            self._relate("version", f"{src[0]}@{src[1]}", "version",
                         f"{key[0]}@{key[1]}", seq, "derived_from")
        return {"versions": {key: version}, "collections": {}}, events

    def _op_merge(self, op, auth, seq):
        return self._op_derive(
            {"op_id": op["op_id"], "op_type": "derive", "args": op["args"],
             "idempotency_key": op["idempotency_key"],
             "causal_parents": op["causal_parents"]}, auth, seq)

    def _op_fork(self, op, auth, seq):
        a = op["args"]
        self._id_ok(a.get("src_obj"), *a.get("new_objs", []))
        src = (a["src_obj"], a["src_ver"])
        if src not in self.versions:
            raise Reject("unknown_reference")
        if a.get("scope") != auth:
            raise Reject("forged_scope")
        staged_versions: dict = {}
        events: list = []
        for new_obj in a["new_objs"]:
            if (new_obj, 1) in self.versions or \
                    any(k[0] == new_obj for k in staged_versions):
                raise Reject("duplicate_version")
            key, version = self._new_version(
                new_obj, self.versions[src]["content"], auth, None, "", seq)
            staged_versions[key] = version
            events.append({"kind": "derive", "dst": [key[0], key[1]],
                           "sources": [[src[0], src[1]]], "fork": True, "op_seq": seq})
            self._relate("version", f"{src[0]}@{src[1]}", "version",
                         f"{key[0]}@{key[1]}", seq, "forked_to")
        return {"versions": staged_versions, "collections": {}}, events

    def _op_withdraw(self, op, auth, seq):
        a = op["args"]
        self._id_ok(a.get("obj_id"))
        target = (a["obj_id"], a["obj_ver"])
        if target not in self.versions:
            raise Reject("unknown_reference")
        self._check()
        if scope_key(self.versions[target]["scope"]) != scope_key(auth):
            raise Reject("forged_scope")
        events = [{"kind": "withdraw", "version": [target[0], target[1]],
                   "reason": a.get("reason", "revoked"), "tombstone": True,
                   "op_seq": seq}]
        return {"versions": {target: {"__withdraw": True}},
                "collections": {}}, events

    def _op_export(self, op, auth, seq):
        # Export changes no state; the exporter module computes the document.
        # The request scope must equal the authorized scope: a forged export
        # request across scopes is denied, never silently narrowed.
        self._check()
        if op["args"].get("request_scope") != auth:
            raise Reject("forged_scope")
        return {"versions": {}, "collections": {}}, [
            {"kind": "export", "request_scope": scope_key(auth), "op_seq": seq}]

    def _op_roundtrip_import(self, op, auth, seq):
        # Import validation lives in importer.py; the model records the verdict.
        verdict = op["args"].get("verdict", "accepted")
        if verdict not in ("accepted", "rejected"):
            raise Reject("unknown_import_verdict")
        if verdict == "rejected":
            raise Reject(op["args"].get("reason", "import_rejected"))
        return {"versions": {}, "collections": {}}, [
            {"kind": "import", "profile": op["args"].get("profile"),
             "digest": op["args"].get("digest"), "op_seq": seq}]

    def _op_reconcile(self, op, auth, seq):
        return {"versions": {}, "collections": {}}, [
            {"kind": "reconcile", "key": op["args"].get("key"), "op_seq": seq}]

    # -- commit helpers ---------------------------------------------------
    def _commit_state(self, staged: dict) -> None:
        for key, version in staged.get("versions", {}).items():
            if isinstance(version, dict) and "__withdraw" in version:
                self.versions[key]["state"] = "withdrawn"
            elif isinstance(version, dict) and "__label" in version:
                self.versions[key]["label"] = version["__label"]
            else:
                self.versions[key] = version
        for coll_id, items in staged.get("collections", {}).items():
            coll = self.collections[coll_id]
            for item in items:
                if "removed_by" in item and "member_key" in item:
                    for member in coll["members"]:
                        if member["key"] == item["member_key"] and \
                                member["removed_by"] is None:
                            member["removed_by"] = item["removed_by"]
                else:
                    coll["members"].append(item)
        if self.rep == "B":
            self._sync_dictionaries()

    def create_collection(self, coll_id: str, scope: dict) -> None:
        self.collections[coll_id] = {"id": coll_id, "scope": dict(scope),
                                     "members": []}
        if self.rep == "B":
            self.dictionaries[coll_id] = {"id": coll_id, "scope": dict(scope),
                                          "entries": {}, "insertions": [],
                                          "removals": []}

    def _sync_dictionaries(self) -> None:
        for coll_id, coll in self.collections.items():
            entry = self.dictionaries.get(coll_id)
            if entry is None:
                entry = {"id": coll_id, "scope": dict(coll["scope"]),
                         "entries": {}, "insertions": [], "removals": []}
                self.dictionaries[coll_id] = entry
            for member in coll["members"]:
                record = entry["entries"].setdefault(
                    member["key"], {"member": member["member"],
                                    "inserted_by": member["inserted_by"],
                                    "removed_by": None, "history": []})
                record["history"].append(
                    {"member": member["member"],
                     "inserted_by": member["inserted_by"],
                     "removed_by": member["removed_by"]})
                if member["removed_by"] is not None:
                    record["removed_by"] = member["removed_by"]

    # -- B query API (A/C emulate with counted scans) ----------------------
    def member_at(self, coll_id: str, key: str):
        """Return the active member for key, counting query steps."""
        if self.rep == "B":
            self.query_steps += 1
            entry = self.dictionaries.get(coll_id, {}).get("entries", {}).get(key)
            if entry and entry["removed_by"] is None:
                return entry["member"]
            return None
        steps = 0
        coll = self.collections.get(coll_id)
        if coll is None:
            return None
        found = None
        for member in coll["members"]:
            steps += 1
            if member["key"] == key and member["removed_by"] is None:
                found = member["member"]
        self.query_steps += steps
        return found

    def drop_cache(self) -> None:
        """C: drop the materialized graph; canonical rows are untouched."""
        if self.rep == "C":
            self.graph_cache = None

    def materialized_graph(self) -> dict:
        if self.rep != "C":
            raise Reject("no_materialized_graph")
        if self.graph_cache is None:
            nodes = {f"{obj}@{ver}": {"scope": scope_key(v["scope"]),
                                      "state": v["state"]}
                     for (obj, ver), v in self.versions.items()}
            self.graph_cache = {"nodes": nodes,
                                "edges": [dict(r) for r in self.relations]}
            self.query_steps += len(self.relations) + len(nodes)
        return self.graph_cache

    # -- digests ------------------------------------------------------------
    def state_digest(self) -> str:
        versions = {f"{o}@{v}": {"scope": scope_key(x["scope"]),
                                 "digest": x["content_digest"],
                                 "supersedes": x["supersedes"],
                                 "state": x["state"], "label": x["label"]}
                    for (o, v), x in sorted(self.versions.items())}
        collections = {cid: {"scope": scope_key(c["scope"]),
                             "members": sorted(
                                 [{"m": m["member"], "k": m["key"],
                                   "ins": m["inserted_by"], "rm": m["removed_by"]}
                                  for m in c["members"]],
                                 key=lambda m: (m["k"], str(m["m"])))}
                       for cid, c in sorted(self.collections.items())}
        return sha(canonical({"versions": versions, "collections": collections}))

    def lineage_digest(self) -> str:
        return sha(canonical([
            {"k": e["kind"], "s": e["op_seq"],
             "r": {k: v for k, v in e.items() if k not in ("kind", "op_seq", "seq")}}
            for e in self.events]))

    def lineage_semantic_digest(self) -> str:
        """Order-insensitive lineage digest: same operation multiset and
        refs regardless of seed interleaving (op_seq/order excluded)."""
        projections = sorted(
            canonical({"k": e["kind"],
                       "r": {k: v for k, v in e.items()
                             if k not in ("kind", "op_seq", "seq", "auth_scope")}}
                      ).decode("utf-8")
            for e in self.events)
        return sha("\n".join(projections).encode("utf-8"))

    def state_rows(self) -> dict:
        return {"versions": len(self.versions),
                "collections": len(self.collections),
                "memberships": sum(len(c["members"]) for c in self.collections.values()),
                "operations": len(self.operations),
                "events": len(self.events),
                "dictionaries": len(self.dictionaries),
                "relations": len(self.relations)}

    def state_bytes(self) -> int:
        return len(canonical({"v": sorted(
            [(o, v, scope_key(x["scope"]), x["content_digest"]) for (o, v), x in
             self.versions.items()]),
            "c": sorted((cid, len(c["members"])) for cid, c in self.collections.items()),
            "e": len(self.events)}))

    def complexity(self) -> dict:
        return {"tables": TABLE_COUNTS[self.rep],
                "constraints": CONSTRAINT_COUNTS[self.rep],
                "query_entry_points": QUERY_ENTRY_POINTS[self.rep],
                "checks_executed": self.checks_executed,
                "query_steps": self.query_steps}
