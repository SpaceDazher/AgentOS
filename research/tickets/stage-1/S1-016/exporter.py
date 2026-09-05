"""S1-016 deterministic exporter: canonical model -> PROV JSON + RDF Turtle.

The export is a derived projection for a single requesting scope. It never
mutates canonical state. Foreign content/IDs never leave except redacted
counterparty scope triples of cross-scope operations touching the requesting
scope (counts of omitted entities stay explainable per L11).
"""
from __future__ import annotations

import hashlib
import json

PROV = "http://www.w3.org/ns/prov#"
AGENTOS = "https://local.agentos.invalid/ns/lineage#"
XSD = "http://www.w3.org/2001/XMLSchema#"

PROFILE = "agentos.prov-export/v1"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def scope_key(scope: dict) -> str:
    return f"{scope['tenant_id']}/{scope['workspace_id']}/{scope['goal_id']}"


def iri(case_id: str, kind: str, local: str) -> str:
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in local)
    return f"agentos:{case_id}/{kind}/{safe}"


def export_json(model, case_id: str, request_scope: dict) -> dict:
    """Build the declared-profile PROV JSON document for one scope."""
    req = scope_key(request_scope)
    entities, collections, activities = [], [], []
    agents: dict[str, dict] = {}
    derivations = []
    redacted_refs = []
    omitted = 0

    visible_versions = {k for k, v in model.versions.items()
                        if scope_key(v["scope"]) == req}
    for (obj, ver) in sorted(model.versions):
        version = model.versions[(obj, ver)]
        if (obj, ver) not in visible_versions:
            continue
        sup = version["supersedes"]
        entities.append({
            "id": iri(case_id, "entity", f"{obj}@{ver}"),
            "local": f"{obj}@{ver}",
            "prov_type": "Entity",
            "scope": dict(version["scope"]),
            "version": ver,
            "object": obj,
            "label": version["label"],
            "state": version["state"],
            "content_digest": version["content_digest"],
            "supersedes": iri(case_id, "entity", f"{sup[0]}@{sup[1]}") if sup else None,
            "supersedes_local": f"{sup[0]}@{sup[1]}" if sup else None,
            "created_by_op": version["created_by_op"],
        })
    for cid in sorted(model.collections):
        coll = model.collections[cid]
        if scope_key(coll["scope"]) != req:
            omitted += 1 + len(coll["members"])
            continue
        members = []
        for member in sorted(coll["members"], key=lambda m: (m["key"], str(m["member"]))):
            mkey = (member["member"][0], member["member"][1])
            if mkey in visible_versions:
                members.append({"key": member["key"],
                                "member": iri(case_id, "entity", f"{mkey[0]}@{mkey[1]}"),
                                "member_local": f"{mkey[0]}@{mkey[1]}",
                                "inserted_by_op": member["inserted_by"],
                                "removed_by_op": member["removed_by"]})
            else:
                members.append({"key": member["key"], "member": None,
                                "redacted": True,
                                "inserted_by_op": member["inserted_by"],
                                "removed_by_op": member["removed_by"]})
        collections.append({"id": iri(case_id, "collection", cid),
                            "prov_type": "Dictionary",
                            "scope": dict(coll["scope"]), "members": members})
    for record in model.operations:
        if record["outcome"] != "committed":
            continue
        op_scope = _op_scope(model, record)
        touches = op_scope == req or _op_touches(model, record, req)
        if not touches and record["op_type"] not in ("export", "reconcile"):
            omitted += 1
            continue
        actor_iri = iri(case_id, "agent", record_actor(model, record))
        agents[actor_iri] = {"id": actor_iri, "prov_type": "Agent",
                             "name": record_actor(model, record)}
        activities.append({
            "id": iri(case_id, "activity", record["op_id"]),
            "prov_type": "Activity",
            "op_id": record["op_id"], "op_type": record["op_type"],
            "actor": actor_iri, "scope": op_scope, "seq": record["seq"],
        })
        for derivation in _derivations(model, record, case_id, req, redacted_refs):
            derivations.append(derivation)
    doc = {"profile": PROFILE, "case_id": case_id,
           "request_scope": dict(request_scope),
           "entities": entities, "collections": collections,
           "activities": activities,
           "agents": sorted(agents.values(), key=lambda a: a["id"]),
           "derivations": derivations, "redacted_refs": redacted_refs,
           "redaction": {"mode": "scope_filtered", "omitted_entities": omitted},
           "unsupported": []}
    return doc


def _op_scope(model, record) -> dict | None:
    for event in model.events:
        if event.get("op_seq") == record["seq"]:
            scope = event.get("auth_scope") or event.get("scope")
            if isinstance(scope, str):
                tenant, workspace, goal = scope.split("/")
                return {"tenant_id": tenant, "workspace_id": workspace,
                        "goal_id": goal}
            kind = event.get("kind")
            if kind in ("export", "import", "reconcile"):
                return None
    return None


def _op_touches(model, record, req: str) -> bool:
    for event in model.events:
        if event.get("op_seq") != record["seq"]:
            continue
        for key in ("src_scope", "dst_scope"):
            if event.get(key) == req:
                return True
    return False


def record_actor(model, record) -> str:
    return f"actor-of-{record['op_id']}"


def _derivations(model, record, case_id, req, redacted_refs):
    out = []
    for event in model.events:
        if event.get("op_seq") != record["seq"]:
            continue
        kind = event.get("kind")
        if kind in ("derive",) or (kind == "copy"):
            src = event.get("sources") or ([event["src"]] if "src" in event else [])
            dst = event.get("dst")
            if dst is None:
                continue
            dst_scope = _version_scope(model, tuple(dst), req)

            def endpoint(item):
                item_scope = _version_scope(model, tuple(item), req)
                if item_scope == req:
                    return iri(case_id, "entity", f"{item[0]}@{item[1]}"), False
                ref = {"scope": _scope_of(model, tuple(item)), "redacted": True}
                if ref not in redacted_refs:
                    redacted_refs.append(ref)
                return {"redacted": True}, True

            src_iris = []
            for src_item in src:
                rendered, _ = endpoint(src_item)
                src_iris.append(rendered)
            if dst_scope != req:
                # Copy/move out: the requesting scope keeps a redacted
                # derivation receipt instead of a silent loss.
                rendered_dst, _ = endpoint(dst)
                out.append({"dst": rendered_dst, "sources": src_iris,
                            "kind": "copy_out_redacted",
                            "op": iri(case_id, "activity", record["op_id"])})
                continue
            out.append({"dst": iri(case_id, "entity", f"{dst[0]}@{dst[1]}"),
                        "sources": src_iris,
                        "kind": "derivation" if kind == "derive" else "copy",
                        "op": iri(case_id, "activity", record["op_id"])})
        elif kind == "supersede":
            ver = event["version"]
            sup = event["supersedes"]
            if _version_scope(model, tuple(ver), req) == req:
                out.append({"dst": iri(case_id, "entity", f"{ver[0]}@{ver[1]}"),
                            "sources": [iri(case_id, "entity", f"{sup[0]}@{sup[1]}")],
                            "kind": "revision",
                            "op": iri(case_id, "activity", record["op_id"])})
    return out


def _version_scope(model, key, req):
    version = model.versions.get((key[0], key[1]))
    if version is None:
        return None
    return scope_key(version["scope"])


def _scope_of(model, key):
    version = model.versions.get((key[0], key[1]))
    if version is None:
        return None
    return dict(version["scope"])


def semantic_digest(doc: dict) -> str:
    """Digest over the normalized supported-subset projection."""
    entities = sorted(
        (e["id"], e["scope"]["tenant_id"], e["scope"]["workspace_id"],
         e["scope"]["goal_id"], e["version"], e["object"], e["supersedes"],
         e["content_digest"], e["state"])
        for e in doc["entities"])
    collections = sorted(
        (c["id"], tuple(sorted(
            (m["key"], m.get("member"), m["inserted_by_op"], m["removed_by_op"])
            for m in c["members"])))
        for c in doc["collections"])
    activities = sorted(
        (a["op_id"], a["op_type"], a["actor"], a["seq"]) for a in doc["activities"])
    core = {"profile": doc["profile"], "request_scope": doc["request_scope"],
            "entities": entities, "collections": collections,
            "activities": activities, "derivations": doc["derivations"],
            "redaction": doc["redaction"]}
    return sha(canonical(core))


def export_turtle(model, case_id: str, request_scope: dict) -> str:
    """Deterministic Turtle rendering of export_json (no blank nodes)."""
    doc = export_json(model, case_id, request_scope)
    lines = ["@prefix prov: <http://www.w3.org/ns/prov#> .",
             "@prefix agentos: <https://local.agentos.invalid/ns/lineage#> .",
             "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .", ""]
    triples: set[tuple[str, str, str]] = set()

    def lit(value):
        if isinstance(value, bool):
            return f'"{str(value).lower()}"^^xsd:boolean'
        if isinstance(value, int):
            return f'"{value}"^^xsd:integer'
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def ref(rid):
        return f"<{rid}>"
    for entity in doc["entities"]:
        s = ref(entity["id"])
        triples.add((s, "a", "prov:Entity"))
        triples.add((s, "agentos:scopeTenant", lit(entity["scope"]["tenant_id"])))
        triples.add((s, "agentos:scopeWorkspace", lit(entity["scope"]["workspace_id"])))
        triples.add((s, "agentos:scopeGoal", lit(entity["scope"]["goal_id"])))
        triples.add((s, "agentos:version", lit(entity["version"])))
        triples.add((s, "agentos:contentDigest", lit(entity["content_digest"])))
        triples.add((s, "agentos:state", lit(entity["state"])))
        if entity["supersedes"]:
            triples.add((s, "prov:wasRevisionOf", ref(entity["supersedes"])))
    for coll in doc["collections"]:
        s = ref(coll["id"])
        triples.add((s, "a", "prov:Dictionary"))
        for member in coll["members"]:
            mid = f"{coll['id']}/member/{member['key']}"
            triples.add((s, "agentos:hasMembership", ref(mid)))
            triples.add((ref(mid), "a", "agentos:Membership"))
            triples.add((ref(mid), "agentos:memberKey", lit(member["key"])))
            triples.add((ref(mid), "agentos:insertedByOp",
                         lit(member["inserted_by_op"] if member["inserted_by_op"] is not None else -1)))
            if member.get("member"):
                triples.add((s, "prov:hadDictionaryMember", ref(member["member"])))
                triples.add((ref(mid), "agentos:memberEntity", ref(member["member"])))
            if member.get("removed_by_op") is not None:
                triples.add((ref(mid), "agentos:removedByOp", lit(member["removed_by_op"])))
    for activity in doc["activities"]:
        s = ref(activity["id"])
        triples.add((s, "a", "prov:Activity"))
        triples.add((s, "agentos:opType", lit(activity["op_type"])))
        triples.add((s, "agentos:opSeq", lit(activity["seq"])))
        triples.add((s, "prov:wasAssociatedWith", ref(activity["actor"])))
    for agent in doc["agents"]:
        triples.add((ref(agent["id"]), "a", "prov:Agent"))
    for derivation in doc["derivations"]:
        if not isinstance(derivation.get("dst"), str):
            # Redacted copy-out receipts stay JSON-only; the activity and
            # redacted counterparty scope remain in the RDF graph.
            continue
        d = ref(derivation["dst"])
        for src in derivation["sources"]:
            if isinstance(src, str):
                pred = {"derivation": "prov:wasDerivedFrom",
                        "copy": "prov:wasDerivedFrom",
                        "revision": "prov:wasRevisionOf"}.get(
                            derivation["kind"], "prov:wasDerivedFrom")
                triples.add((d, pred, ref(src)))
    for line in sorted(f"{s} {p} {o} ." for s, p, o in triples):
        lines.append(line)
    return "\n".join(lines) + "\n"
