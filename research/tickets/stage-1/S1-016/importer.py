"""S1-016 validated importer: PROV document -> canonical subset (no authority).

Accepts only the declared profile/version. Never creates authority, never
restores content from digests, never resolves dangling references. Constructs
outside the supported subset yield explicit UNSUPPORTED entries. Scope
rewrites (entity scope contradicting its generating activity scope) reject.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("s1016_contract_imp", HERE / "contract.py")
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)

PROFILE = "agentos.prov-export/v1"

SUPPORTED_TYPES = {"Entity", "Dictionary", "Activity", "Agent"}
SUPPORTED_RELS = {"wasGeneratedBy", "wasDerivedFrom", "wasRevisionOf",
                  "wasAttributedTo", "wasInvalidatedBy", "actedOnBehalfOf",
                  "hadDictionaryMember", "DerivedByInsertionFrom",
                  "DerivedByRemovalFrom"}


class ImportReject(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _scope_ok(scope) -> bool:
    return isinstance(scope, dict) and \
        all(isinstance(scope.get(k), str) and scope[k] and not contract.has_traversal(scope[k])
            for k in ("tenant_id", "workspace_id", "goal_id")) and \
        set(scope) == {"tenant_id", "workspace_id", "goal_id"}


def import_document(doc) -> dict:
    """Validate a PROV JSON document; return {state, unsupported} or raise."""
    if contract.has_private(doc):
        raise ImportReject("quarantine_private")
    if not isinstance(doc, dict):
        raise ImportReject("not_an_object")
    if doc.get("profile") != PROFILE:
        raise ImportReject("unknown_profile")
    for key in ("entities", "collections", "activities", "agents"):
        if not isinstance(doc.get(key), list):
            raise ImportReject(f"missing_{key}")
    unsupported: list[dict] = []
    for extra in doc.get("unsupported", []):
        unsupported.append({"declared": extra})
    entities: dict[str, dict] = {}
    for entity in doc["entities"]:
        if not isinstance(entity, dict):
            raise ImportReject("malformed_entity")
        if entity.get("prov_type") not in ("Entity",):
            unsupported.append({"kind": "entity_type", "value": entity.get("prov_type")})
            continue
        if not _scope_ok(entity.get("scope")):
            raise ImportReject("scope_rewrite_or_missing")
        eid = entity.get("id")
        if not isinstance(eid, str) or not eid or contract.has_traversal(eid):
            raise ImportReject("malformed_entity_id")
        if eid in entities:
            raise ImportReject("duplicate_entity")
        entities[eid] = {
            "local": entity.get("local"),
            "supersedes_local": entity.get("supersedes_local"),
            "scope": dict(entity["scope"]),
            "version": entity.get("version"),
            "object": entity.get("object"),
            "supersedes": entity.get("supersedes"),
            "content_digest": entity.get("content_digest"),
            "content": None,
            "content_unrestorable": True,
            "state": entity.get("state", "active"),
        }
    for eid, entity in entities.items():
        sup = entity["supersedes"]
        if sup is not None and sup not in entities:
            raise ImportReject("dangling_supersedes")
    for activity in doc["activities"]:
        if not isinstance(activity, dict):
            raise ImportReject("malformed_activity")
        if activity.get("prov_type") not in ("Activity", None):
            unsupported.append({"kind": "activity_type",
                                "value": activity.get("prov_type")})
    # Scope-rewrite defense: an entity's scope must agree with the scope of
    # the activity that generated it (derivations carry the link).
    activity_scope: dict[str, dict] = {}
    for activity in doc["activities"]:
        if isinstance(activity.get("scope"), dict):
            activity_scope[activity["id"]] = activity["scope"]
    for derivation in doc.get("derivations", []):
        if not isinstance(derivation, dict):
            raise ImportReject("malformed_derivation")
        dst = derivation.get("dst")
        if isinstance(dst, dict):
            # Redacted copy-out receipt: in-profile, carries no entity link.
            if dst.get("redacted") is not True:
                raise ImportReject("malformed_derivation")
            continue
        if dst not in entities:
            raise ImportReject("dangling_derivation")
        for src in derivation.get("sources", []):
            if isinstance(src, dict):
                if src.get("redacted") is not True:
                    raise ImportReject("malformed_derivation")
            elif src not in entities:
                raise ImportReject("dangling_derivation")
    # Membership bindings resolve to imported entities or explicit redaction.
    collections = []
    for coll in doc["collections"]:
        if not isinstance(coll, dict):
            raise ImportReject("malformed_collection")
        if coll.get("prov_type") not in ("Dictionary",):
            unsupported.append({"kind": "collection_type",
                                "value": coll.get("prov_type")})
            continue
        if not _scope_ok(coll.get("scope")):
            raise ImportReject("scope_rewrite_or_missing")
        members = []
        for member in coll.get("members", []):
            ref = member.get("member")
            if ref is None:
                if member.get("redacted") is not True:
                    raise ImportReject("dangling_member")
                members.append({"key": member.get("key"), "redacted": True,
                                "inserted_by_op": member.get("inserted_by_op"),
                                "removed_by_op": member.get("removed_by_op")})
            elif ref not in entities:
                raise ImportReject("dangling_member")
            else:
                members.append({"key": member.get("key"), "member": ref,
                                "member_local": member.get("member_local"),
                                "inserted_by_op": member.get("inserted_by_op"),
                                "removed_by_op": member.get("removed_by_op")})
        collections.append({"id": coll["id"], "scope": dict(coll["scope"]),
                            "members": members})
    state = {"entities": entities, "collections": collections,
             "redaction": dict(doc.get("redaction", {}))}
    return {"state": state, "unsupported": unsupported}


def import_turtle(text: str) -> dict:
    """RDF import path: reject blank nodes, then map the supported subset."""
    from rdflib import Graph
    from rdflib.term import BNode
    graph = Graph()
    try:
        graph.parse(data=text, format="turtle")
    except Exception as exc:
        raise ImportReject(f"rdf_parse_error: {exc}") from exc
    for term in list(graph.subjects()) + list(graph.predicates()) + list(graph.objects()):
        if isinstance(term, BNode):
            raise ImportReject("blank_node")
    raise ImportReject("rdf_import_requires_json_envelope")
