"""Deterministic 48-scenario corpus generator for S1-016.

Single source of corpus.json + oracle.json. Oracle digests are frozen by
running the reference simulator (representation A) at build time; the UI of
trust is: evaluator recomputes everything from corpus bytes, SHACL validates
externally, the audit reconstructor reads events only, and probes mutate.
Re-running must be byte-identical.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import models
import audit as audit_mod
import exporter as exporter_mod
import roundtrip as roundtrip_mod
import shacl_runner as shacl_mod

SA = {"tenant_id": "t-a", "workspace_id": "w-1", "goal_id": "g-1"}
SB = {"tenant_id": "t-a", "workspace_id": "w-2", "goal_id": "g-2"}
SC = {"tenant_id": "t-b", "workspace_id": "w-1", "goal_id": "g-3"}
SCOPES = {"S_A": SA, "S_B": SB, "S_C": SC}


def op(op_id, op_type, scope, args, parents=None, crash=None, key=None):
    return {"op_id": op_id, "op_type": op_type, "actor": f"actor@{scope}",
            "scope": dict(SCOPES[scope]),
            "args": args, "idempotency_key": key or f"k-{op_id}",
            "causal_parents": list(parents or []),
            "crash_point": crash}


def ver(obj, content, scope, label=""):
    return {"obj": obj, "content": content, "scope": scope, "label": label}


def coll(cid, scope, members=None):
    return {"id": cid, "scope": scope, "members": members or []}


def mem(obj, ver_, key):
    return {"member": [obj, ver_], "key": key}


# Each scenario: id, class, description, initial versions/collections,
# operations, independent groups (seed shuffling), oracle expectations.
SCENARIOS = [
    # ---------------- valid (24) ----------------
    {"id": "V-01", "class": "valid", "desc": "create artifact version",
     "versions": [], "collections": [],
     "ops": [op("o1", "create", "S_A", {"obj_id": "doc1", "content": "hello", "scope": SA})],
     "groups": [[0]], "expect": "committed"},
    {"id": "V-02", "class": "valid", "desc": "create two artifacts and a collection",
     "versions": [ver("d1", "c1", "S_A"), ver("d2", "c2", "S_A")],
     "collections": [coll("col1", "S_A")], "ops": [],
     "groups": [], "expect": "committed"},
    {"id": "V-03", "class": "valid", "desc": "insert member into collection",
     "versions": [ver("d1", "c1", "S_A")], "collections": [coll("col1", "S_A")],
     "ops": [op("o1", "insert", "S_A", {"collection": "col1", "member_obj": "d1", "member_ver": 1, "key": "k1"})],
     "groups": [[0]], "expect": "committed"},
    {"id": "V-04", "class": "valid", "desc": "insert multiple members",
     "versions": [ver("d1", "c1", "S_A"), ver("d2", "c2", "S_A")],
     "collections": [coll("col1", "S_A")],
     "ops": [op("o1", "insert", "S_A", {"collection": "col1", "member_obj": "d1", "member_ver": 1, "key": "k1"}),
             op("o2", "insert", "S_A", {"collection": "col1", "member_obj": "d2", "member_ver": 1, "key": "k2"})],
     "groups": [[0, 1]], "expect": "committed"},
    {"id": "V-05", "class": "valid", "desc": "remove membership keeps insertion history",
     "versions": [ver("d1", "c1", "S_A")],
     "collections": [coll("col1", "S_A", [mem("d1", 1, "k1")])],
     "ops": [op("o1", "remove", "S_A", {"collection": "col1", "key": "k1"})],
     "groups": [[0]], "expect": "committed"},
    {"id": "V-06", "class": "valid", "desc": "same-scope update with supersedes chain",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "update_supersede", "S_A", {"obj_id": "d1", "content": "c2"}),
             op("o2", "update_supersede", "S_A", {"obj_id": "d1", "content": "c3"})],
     "groups": [[0], [1]], "expect": "committed"},
    {"id": "V-07", "class": "valid", "desc": "same-scope copy",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "copy_same_scope", "S_A", {"src_obj": "d1", "src_ver": 1, "new_obj": "d1copy"})],
     "groups": [[0]], "expect": "committed"},
    {"id": "V-08", "class": "valid", "desc": "cross-scope copy A to B",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "copy_cross_scope", "S_B", {"src_obj": "d1", "src_ver": 1, "new_obj": "d1b", "target_scope": SB})],
     "groups": [[0]], "expect": "committed"},
    {"id": "V-09", "class": "valid", "desc": "cross-tenant copy A to C",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "copy_cross_scope", "S_C", {"src_obj": "d1", "src_ver": 1, "new_obj": "d1c", "target_scope": SC})],
     "groups": [[0]], "expect": "committed"},
    {"id": "V-10", "class": "valid", "desc": "cross-scope move complete with tombstone",
     "versions": [ver("d1", "c1", "S_A")],
     "collections": [coll("colA", "S_A", [mem("d1", 1, "k1")])],
     "ops": [op("o1", "move_cross_scope", "S_B", {"src_obj": "d1", "src_ver": 1, "new_obj": "d1b", "target_scope": SB})],
     "groups": [[0]], "expect": "committed"},
    {"id": "V-11", "class": "valid", "desc": "rename without identity change",
     "versions": [ver("d1", "c1", "S_A", "old")], "collections": [],
     "ops": [op("o1", "rename", "S_A", {"obj_id": "d1", "new_label": "new"})],
     "groups": [[0]], "expect": "committed"},
    {"id": "V-12", "class": "valid", "desc": "derive from one source",
     "versions": [ver("s1", "a", "S_A")], "collections": [],
     "ops": [op("o1", "derive", "S_A", {"sources": [["s1", 1]], "new_obj": "d1", "content": "b", "scope": SA})],
     "groups": [[0]], "expect": "committed"},
    {"id": "V-13", "class": "valid", "desc": "derive from many sources",
     "versions": [ver("s1", "a", "S_A"), ver("s2", "b", "S_A")], "collections": [],
     "ops": [op("o1", "derive", "S_A", {"sources": [["s1", 1], ["s2", 1]], "new_obj": "d1", "content": "c", "scope": SA})],
     "groups": [[0]], "expect": "committed"},
    {"id": "V-14", "class": "valid", "desc": "merge lineage",
     "versions": [ver("s1", "a", "S_A"), ver("s2", "b", "S_A")], "collections": [],
     "ops": [op("o1", "merge", "S_A", {"sources": [["s1", 1], ["s2", 1]], "new_obj": "m1", "content": "m", "scope": SA})],
     "groups": [[0]], "expect": "committed"},
    {"id": "V-15", "class": "valid", "desc": "fork lineage",
     "versions": [ver("s1", "a", "S_A")], "collections": [],
     "ops": [op("o1", "fork", "S_A", {"src_obj": "s1", "src_ver": 1, "new_objs": ["f1", "f2"], "scope": SA})],
     "groups": [[0]], "expect": "committed"},
    {"id": "V-16", "class": "valid", "desc": "withdraw visibility retains content",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "withdraw", "S_A", {"obj_id": "d1", "obj_ver": 1, "reason": "revoked"})],
     "groups": [[0]], "expect": "committed"},
    {"id": "V-17", "class": "valid", "desc": "export and round-trip supported subset",
     "versions": [ver("d1", "c1", "S_A")],
     "collections": [coll("col1", "S_A", [mem("d1", 1, "k1")])],
     "ops": [op("o1", "export", "S_A", {"request_scope": SA})],
     "groups": [[0]], "expect": "committed", "roundtrip": True},
    {"id": "V-18", "class": "valid", "desc": "empty collection create and export",
     "versions": [], "collections": [coll("empty", "S_A")],
     "ops": [op("o1", "export", "S_A", {"request_scope": SA})],
     "groups": [[0]], "expect": "committed", "roundtrip": True},
    {"id": "V-19", "class": "valid", "desc": "legacy version readable after supersede chain",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "update_supersede", "S_A", {"obj_id": "d1", "content": "c2"}),
             op("o2", "update_supersede", "S_A", {"obj_id": "d1", "content": "c3"})],
     "groups": [[0], [1]], "expect": "committed", "legacy_read": ["d1", 1]},
    {"id": "V-20", "class": "valid", "desc": "move with crash before commit reconciles once",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "move_cross_scope", "S_B", {"src_obj": "d1", "src_ver": 1, "new_obj": "d1b", "target_scope": SB}, crash="before_commit")],
     "groups": [[0]], "expect": "committed", "crash": "before_commit"},
    {"id": "V-21", "class": "valid", "desc": "move with crash after state reconciles events",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "move_cross_scope", "S_B", {"src_obj": "d1", "src_ver": 1, "new_obj": "d1b", "target_scope": SB}, crash="after_state_before_event")],
     "groups": [[0]], "expect": "committed", "crash": "after_state_before_event"},
    {"id": "V-22", "class": "valid", "desc": "copy crash with idempotent retry, no duplicate",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "copy_cross_scope", "S_B", {"src_obj": "d1", "src_ver": 1, "new_obj": "d1b", "target_scope": SB}, crash="before_commit")],
     "groups": [[0]], "expect": "committed", "crash": "before_commit"},
    {"id": "V-23", "class": "valid", "desc": "removal then export shows tombstone interval",
     "versions": [ver("d1", "c1", "S_A")],
     "collections": [coll("col1", "S_A", [mem("d1", 1, "k1")])],
     "ops": [op("o1", "remove", "S_A", {"collection": "col1", "key": "k1"}),
             op("o2", "export", "S_A", {"request_scope": SA})],
     "groups": [[0], [1]], "expect": "committed", "roundtrip": True},
    {"id": "V-24", "class": "valid", "desc": "redacted export explains omission",
     "versions": [ver("d1", "c1", "S_A"), ver("e1", "x", "S_C")],
     "collections": [coll("colA", "S_A", [mem("d1", 1, "k1")])],
     "ops": [op("o1", "export", "S_A", {"request_scope": SA})],
     "groups": [[0]], "expect": "committed", "roundtrip": True, "redacted": True},
    # ---------------- near-miss (12) ----------------
    {"id": "N-01", "class": "near_miss", "desc": "duplicate insertion rejected",
     "versions": [ver("d1", "c1", "S_A")],
     "collections": [coll("col1", "S_A", [mem("d1", 1, "k1")])],
     "ops": [op("o1", "insert", "S_A", {"collection": "col1", "member_obj": "d1", "member_ver": 1, "key": "k1"})],
     "groups": [[0]], "expect": "rejected:duplicate_insertion"},
    {"id": "N-02", "class": "near_miss", "desc": "repeated deletion rejected",
     "versions": [ver("d1", "c1", "S_A")],
     "collections": [coll("col1", "S_A", [mem("d1", 1, "k1")])],
     "ops": [op("o1", "remove", "S_A", {"collection": "col1", "key": "k1"}),
             op("o2", "remove", "S_A", {"collection": "col1", "key": "k1"})],
     "groups": [[0], [1]], "expect": "mixed"},
    {"id": "N-03", "class": "near_miss", "desc": "stale ID resolves to legacy version",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "update_supersede", "S_A", {"obj_id": "d1", "content": "c2"})],
     "groups": [[0]], "expect": "committed", "legacy_read": ["d1", 1]},
    {"id": "N-04", "class": "near_miss", "desc": "derive from missing source rejected",
     "versions": [], "collections": [],
     "ops": [op("o1", "derive", "S_A", {"sources": [["ghost", 9]], "new_obj": "d1", "content": "c", "scope": SA})],
     "groups": [[0]], "expect": "rejected:unknown_reference"},
    {"id": "N-05", "class": "near_miss", "desc": "cross-tenant near-miss copy with wrong auth rejected",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "copy_cross_scope", "S_A", {"src_obj": "d1", "src_ver": 1, "new_obj": "d1c", "target_scope": SC})],
     "groups": [[0]], "expect": "rejected:forged_scope"},
    {"id": "N-06", "class": "near_miss", "desc": "operation retry with same key is single effect",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "copy_same_scope", "S_A", {"src_obj": "d1", "src_ver": 1, "new_obj": "d2"}),
             op("o1b", "copy_same_scope", "S_A", {"src_obj": "d1", "src_ver": 1, "new_obj": "d2"}, key="k-o1")],
     "groups": [[0], [1]], "expect": "mixed"},
    {"id": "N-07", "class": "near_miss", "desc": "out-of-order causal parent rejected",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "copy_same_scope", "S_A", {"src_obj": "d1", "src_ver": 1, "new_obj": "d2"}, parents=[5])],
     "groups": [[0]], "expect": "rejected:causal_order"},
    {"id": "N-08", "class": "near_miss", "desc": "legacy chain integrity across three versions",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "update_supersede", "S_A", {"obj_id": "d1", "content": "c2"}),
             op("o2", "update_supersede", "S_A", {"obj_id": "d1", "content": "c3"}),
             op("o3", "update_supersede", "S_A", {"obj_id": "d1", "content": "c4"})],
     "groups": [[0], [1], [2]], "expect": "committed"},
    {"id": "N-09", "class": "near_miss", "desc": "redacted export keeps cross-scope op as redacted ref",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "copy_cross_scope", "S_B", {"src_obj": "d1", "src_ver": 1, "new_obj": "d1b", "target_scope": SB}),
             op("o2", "export", "S_A", {"request_scope": SA})],
     "groups": [[0], [1]], "expect": "committed", "roundtrip": True, "redacted": True},
    {"id": "N-10", "class": "near_miss", "desc": "partial move without reconcile stays visible PARTIAL",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "move_cross_scope", "S_B", {"src_obj": "d1", "src_ver": 1, "new_obj": "d1b", "target_scope": SB}, crash="after_state_before_event")],
     "groups": [[0]], "expect": "unknown", "crash": "after_state_before_event", "no_reconcile": True},
    {"id": "N-11", "class": "near_miss", "desc": "rename label collision keeps distinct identity",
     "versions": [ver("d1", "c1", "S_A", "shared"), ver("d2", "c2", "S_A", "other")],
     "collections": [],
     "ops": [op("o1", "rename", "S_A", {"obj_id": "d2", "new_label": "shared"})],
     "groups": [[0]], "expect": "committed"},
    {"id": "N-12", "class": "near_miss", "desc": "scope-narrowed export sees subset",
     "versions": [ver("d1", "c1", "S_A"), ver("d2", "c2", "S_B")],
     "collections": [coll("colA", "S_A", [mem("d1", 1, "k1")]), coll("colB", "S_B", [mem("d2", 1, "k1")])],
     "ops": [op("o1", "export", "S_A", {"request_scope": SA})],
     "groups": [[0]], "expect": "committed", "roundtrip": True, "redacted": True},
    # ---------------- adversarial (12) ----------------
    {"id": "X-01", "class": "adversarial", "desc": "forged scope copy rejected",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "copy_cross_scope", "S_B", {"src_obj": "d1", "src_ver": 1, "new_obj": "d1b", "target_scope": SB})],
     "groups": [[0]], "expect": "rejected:forged_scope", "forge_auth": "S_C"},
    {"id": "X-02", "class": "adversarial", "desc": "cyclic derivation rejected",
     "versions": [ver("loop", "a", "S_A")], "collections": [],
     "ops": [op("o1", "derive", "S_A", {"sources": [["loop", 1]], "new_obj": "loop", "content": "b", "scope": SA}, parents=None)],
     "groups": [[0]], "expect": "rejected:duplicate_version"},
    {"id": "X-03", "class": "adversarial", "desc": "history wipe attempt fails, insertion kept",
     "versions": [ver("d1", "c1", "S_A")],
     "collections": [coll("col1", "S_A", [mem("d1", 1, "k1")])],
     "ops": [op("o1", "remove", "S_A", {"collection": "col1", "key": "k1"}),
             op("o2", "remove", "S_A", {"collection": "col1", "key": "k1"})],
     "groups": [[0], [1]], "expect": "mixed"},
    {"id": "X-04", "class": "adversarial", "desc": "provenance edge grants nothing",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "copy_cross_scope", "S_C", {"src_obj": "d1", "src_ver": 1, "new_obj": "d1c", "target_scope": SC})],
     "groups": [[0]], "expect": "rejected:forged_scope", "forge_auth": "S_A"},
    {"id": "X-05", "class": "adversarial", "desc": "dual authoritative scopes rejected",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "copy_cross_scope", "S_B", {"src_obj": "d1", "src_ver": 1, "new_obj": "d1", "target_scope": SB})],
     "groups": [[0]], "expect": "rejected:duplicate_version"},
    {"id": "X-06", "class": "adversarial", "desc": "orphan edge rejected",
     "versions": [], "collections": [coll("col1", "S_A")],
     "ops": [op("o1", "insert", "S_A", {"collection": "col1", "member_obj": "ghost", "member_ver": 3, "key": "k9"})],
     "groups": [[0]], "expect": "rejected:unknown_reference"},
    {"id": "X-07", "class": "adversarial", "desc": "export with forged request scope denied",
     "versions": [ver("d1", "c1", "S_A")],
     "collections": [coll("col1", "S_A", [mem("d1", 1, "k1")])],
     "ops": [op("o1", "export", "S_A", {"request_scope": SC})],
     "groups": [[0]], "expect": "rejected:forged_scope", "forge_auth": "S_A", "export_deny": True},
    {"id": "X-08", "class": "adversarial", "desc": "importer rejects unknown profile version",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [], "groups": [], "expect": "committed", "import_attack": "unknown_profile"},
    {"id": "X-09", "class": "adversarial", "desc": "importer rejects scope rewrite",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [], "groups": [], "expect": "committed", "import_attack": "scope_rewrite"},
    {"id": "X-10", "class": "adversarial", "desc": "mixed-manifest replay detected",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "create", "S_A", {"obj_id": "d2", "content": "z", "scope": SA})],
     "groups": [[0]], "expect": "committed", "provenance_attack": "mixed_executors"},
    {"id": "X-11", "class": "adversarial", "desc": "secret content quarantined",
     "versions": [], "collections": [],
     "ops": [op("o1", "create", "S_A", {"obj_id": "sek", "content": "token sk-proj-abcdefgh12345678", "scope": SA})],
     "groups": [[0]], "expect": "quarantined"},
    {"id": "X-12", "class": "adversarial", "desc": "move retry after commit is single effect",
     "versions": [ver("d1", "c1", "S_A")], "collections": [],
     "ops": [op("o1", "move_cross_scope", "S_B", {"src_obj": "d1", "src_ver": 1, "new_obj": "d1b", "target_scope": SB}),
             op("o1r", "move_cross_scope", "S_B", {"src_obj": "d1", "src_ver": 1, "new_obj": "d1b", "target_scope": SB}, key="k-o1")],
     "groups": [[0], [1]], "expect": "mixed"},
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def order_ops(scenario: dict, seed: int):
    ops = scenario["ops"]
    order = list(range(len(ops)))
    for group in scenario.get("groups", []):
        idx = [i for i in group if i < len(ops)]
        keyed = sorted(idx, key=lambda i: sha(f"{seed}|{scenario['id']}|{i}".encode()))
        pos = [order.index(i) for i in idx]
        for p, i in zip(sorted(pos), keyed):
            order[p] = i
    return [ops[i] for i in order]


def build_reference(scenario: dict, seed: int):
    """Run the reference simulator (rep A); returns terminal/lineage digests."""
    model = models.Model("A")
    for v in scenario.get("versions", []):
        scope = SCOPES[v["scope"]]
        key = (v["obj"], 1)
        model.versions[key] = {"id": v["obj"], "version": 1, "scope": dict(scope),
                               "content_digest": sha(v["content"].encode()),
                               "content": v["content"], "supersedes": None,
                               "state": "active", "label": v.get("label", ""),
                               "created_by_op": -1}
    for c in scenario.get("collections", []):
        model.create_collection(c["id"], SCOPES[c["scope"]])
        for m in c.get("members", []):
            model.collections[c["id"]]["members"].append(
                {"member": m["member"], "key": m["key"],
                 "inserted_by": -1, "removed_by": None})
    outcomes = []
    for nop, op in enumerate(order_ops(scenario, seed)):
        op = dict(op)
        auth = dict(SCOPES[scenario.get("forge_auth") or op_auth(scenario, op)])
        op["_auth_scope"] = auth
        overlay = dict(op)
        overlay["crash_point"] = op.get("crash_point")
        res = model.apply(overlay, auth)
        if res["outcome"] == "unknown" and not scenario.get("no_reconcile"):
            retry = dict(op)
            retry["_auth_scope"] = auth
            retry["crash_point"] = None
            res = model.reconcile(retry)
        outcomes.append({"op": op["op_id"], "outcome": res["outcome"],
                         "reason": res.get("reason")})
    return model, outcomes


def op_auth(scenario: dict, op: dict) -> str:
    for name, scope in SCOPES.items():
        if op["scope"] == scope:
            return name
    raise ValueError("unknown op scope")


def build():
    corpus_cases = []
    oracle = {}
    for scenario in SCENARIOS:
        model, outcomes = build_reference(scenario, seed=1)
        terminal = model.state_digest()
        lineage = model.lineage_digest()
        baseline = {"versions": {
            (v["obj"], 1): sha(v["content"].encode("utf-8"))
            for v in scenario.get("versions", [])}, "members": {}}
        reconstruction = audit_mod.reconstruct(model, baseline)
        scope = dict(SA)
        for o in scenario.get("ops", []):
            if o["op_type"] == "export":
                scope = dict(o["args"]["request_scope"])
                break
        rt = roundtrip_mod.compare(model, scenario["id"], scope)
        sh = shacl_mod.run_case(model, scenario["id"], scope)
        payload = {"id": scenario["id"], "class": scenario["class"],
                   "desc": scenario["desc"], "expect": scenario.get("expect", ""),
                   "versions": scenario.get("versions", []),
                   "collections": scenario.get("collections", []),
                   "ops": scenario["ops"], "groups": scenario.get("groups", []),
                   "terminal_digest": terminal, "lineage_digest": lineage,
                   "op_outcomes": outcomes,
                   "flags": {k: v for k, v in scenario.items()
                             if k in ("roundtrip", "redacted", "legacy_read", "crash",
                                      "no_reconcile", "forge_auth", "export_deny",
                                      "import_attack", "provenance_attack")}}
        digest = sha(canonical(payload))
        corpus_cases.append({**payload, "semantic_digest": digest})
        oracle[scenario["id"]] = {
            "expected_terminal_digest": terminal,
            "expected_lineage_digest": lineage,
            "expected_op_outcomes": outcomes,
            "expected_class": scenario["expect"],
            "expected_reconstruction_digest": reconstruction["digest"],
            "expected_reconstruction_complete": reconstruction["complete"],
            "expected_roundtrip_match": rt["match"] if scenario.get("roundtrip") else None,
            "expected_roundtrip_digest": rt["import_digest"],
            "expected_shacl_conforms": sh["conforms"],
            "expected_shacl_violations": sh["violations"],
        }
    ids = [c["id"] for c in corpus_cases]
    assert len(ids) == len(set(ids)) == 48
    assert len({c["semantic_digest"] for c in corpus_cases}) == 48
    by_class = {}
    for c in corpus_cases:
        by_class[c["class"]] = by_class.get(c["class"], 0) + 1
    assert by_class.get("valid", 0) == 24, by_class
    assert by_class.get("near_miss", 0) == 12, by_class
    assert by_class.get("adversarial", 0) == 12, by_class
    corpus = {"schema": "agentos.s1-016.corpus/v1", "ticket": "S1-016",
              "scenario_count": 48, "cases": corpus_cases}
    oracle_doc = {"schema": "agentos.s1-016.oracle/v1", "ticket": "S1-016",
                  "entries": oracle}
    return corpus, oracle_doc


def main() -> int:
    corpus, oracle_doc = build()
    (HERE / "corpus.json").write_text(
        json.dumps(corpus, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    (HERE / "oracle.json").write_text(
        json.dumps(oracle_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    manifest = {
        "schema": "agentos.s1-016.corpus-manifest/v1",
        "ticket": "S1-016",
        "corpus_sha256": sha((HERE / "corpus.json").read_bytes()),
        "oracle_sha256": sha((HERE / "oracle.json").read_bytes()),
        "generator_sha256": sha((HERE / "build_corpus.py").read_bytes()),
        "models_sha256": sha((HERE / "models.py").read_bytes()),
        "scenario_count": 48,
        "deterministic": True,
    }
    (HERE / "corpus-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"scenarios": 48, **manifest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
