"""S1-016 semantic round-trip comparator (canonical -> export -> import)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _mod(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


exporter = _mod("s1016_exporter_rt", "exporter.py")
importer = _mod("s1016_importer_rt", "importer.py")


def _scope_key(scope: dict) -> str:
    return f"{scope['tenant_id']}/{scope['workspace_id']}/{scope['goal_id']}"


def subset_projection(model, request_scope: dict) -> dict:
    """Supported-subset projection of live canonical state for one scope."""
    req = _scope_key(request_scope)
    versions = {}
    for (obj, ver), version in sorted(model.versions.items()):
        if _scope_key(version["scope"]) != req:
            continue
        sup = version["supersedes"]
        versions[f"{obj}@{ver}"] = {
            "scope": dict(version["scope"]), "version": ver, "object": obj,
            "supersedes": f"{sup[0]}@{sup[1]}" if sup else None,
            "content_digest": version["content_digest"],
            "state": version["state"], "label": version["label"],
        }
    collections = {}
    for cid in sorted(model.collections):
        coll = model.collections[cid]
        if _scope_key(coll["scope"]) != req:
            continue
        collections[cid] = {
            "scope": dict(coll["scope"]),
            "members": sorted(
                [{"key": m["key"],
                  "member": (f"{m['member'][0]}@{m['member'][1]}"
                             if f"{m['member'][0]}@{m['member'][1]}" in versions else None),
                  "redacted": (f"{m['member'][0]}@{m['member'][1]}" not in versions),
                  "inserted_by_op": m["inserted_by"], "removed_by_op": m["removed_by"]}
                 for m in coll["members"]],
                key=lambda m: (m["key"], str(m["member"]))),
        }
    return {"versions": versions, "collections": collections}


def imported_projection(imported: dict) -> dict:
    """Same projection shape over importer output (content never restored)."""
    state = imported["state"]
    versions = {}
    for eid in sorted(state["entities"]):
        entity = state["entities"][eid]
        local = entity.get("local") or eid.split("/")[-1]
        versions[local] = {
            "scope": dict(entity["scope"]), "version": entity["version"],
            "object": entity["object"],
            "supersedes": (entity.get("supersedes_local")
                           or (entity["supersedes"].split("/")[-1]
                               if entity["supersedes"] else None)),
            "content_digest": entity["content_digest"],
            "state": entity["state"],
        }
    collections = {}
    for coll in state["collections"]:
        cid = coll["id"].split("/")[-1]
        collections[cid] = {
            "scope": dict(coll["scope"]),
            "members": sorted(
                [{"key": m["key"],
                  "member": (m.get("member_local")
                             or (m["member"].split("/")[-1] if m.get("member") else None)),
                  "redacted": m.get("member") is None,
                  "inserted_by_op": m["inserted_by_op"],
                  "removed_by_op": m["removed_by_op"]}
                 for m in coll["members"]],
                key=lambda m: (m["key"], str(m["member"]))),
        }
    return {"versions": versions, "collections": collections}


def compare(model, case_id: str, request_scope: dict) -> dict:
    """Round-trip one scope; return match verdict with both digests."""
    doc = exporter.export_json(model, case_id, request_scope)
    try:
        imported = importer.import_document(doc)
    except importer.ImportReject as exc:
        return {"match": False, "reason": f"import_rejected:{exc.reason}",
                "export_digest": exporter.semantic_digest(doc),
                "import_digest": None,
                "unsupported": []}
    want = subset_projection(model, request_scope)
    # Labels do not round-trip (display metadata outside the supported
    # subset); normalize both sides before comparison.
    for key in want["versions"]:
        want["versions"][key] = {k: v for k, v in want["versions"][key].items()
                                 if k != "label"}
    got = imported_projection(imported)
    for key in got["versions"]:
        got["versions"][key] = {k: v for k, v in got["versions"][key].items()
                                if k != "label"}
    import hashlib
    import json
    digest = lambda v: hashlib.sha256(json.dumps(
        v, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    match = digest(want) == digest(got)
    return {"match": match,
            "reason": None if match else "subset_mismatch",
            "export_digest": exporter.semantic_digest(doc),
            "import_digest": digest(got),
            "unsupported": imported["unsupported"]}
