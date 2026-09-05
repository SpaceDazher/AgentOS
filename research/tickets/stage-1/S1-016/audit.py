"""S1-016 audit reconstructor: rebuilds chains from canonical events only.

Reads versions/collections (state) plus the event log (evidence). Never reads
producer summaries, operation outcome records, or digests. Reports PARTIAL
chains where staged state lacks generating events, with the pending endpoint.
"""
from __future__ import annotations

import hashlib
import json


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def scope_key(scope: dict) -> str:
    return f"{scope['tenant_id']}/{scope['workspace_id']}/{scope['goal_id']}"


def reconstruct(model, baseline: dict | None = None) -> dict:
    """Rebuild create/insert/remove/copy/move/supersede chains from events."""
    baseline = baseline or {"versions": {}, "members": {}}
    generated: dict[tuple, list[str]] = {}
    for event in model.events:
        kind = event.get("kind")
        if kind == "create":
            generated.setdefault(tuple(event["version"]), []).append("create")
        elif kind in ("copy",):
            dst = tuple(event["dst"])
            generated.setdefault(dst, []).append("copy")
        elif kind == "derive":
            generated.setdefault(tuple(event["dst"]), []).append("derive")
        elif kind == "supersede":
            generated.setdefault(tuple(event["version"]), []).append("supersede")
    chains: dict[str, dict] = {}
    partials: list[dict] = []
    objects: dict[str, list] = {}
    for (obj, ver) in model.versions:
        objects.setdefault(obj, []).append(ver)
    for obj in sorted(objects):
        versions = sorted(objects[obj])
        links = []
        for ver in versions:
            key = (obj, ver)
            version = model.versions[key]
            sup = version["supersedes"]
            if sup is not None:
                links.append({"version": ver, "supersedes": sup[1]})
            gens = generated.get(key, [])
            if version.get("created_by_op", -1) == -1:
                origin = "baseline"
            elif not gens:
                origin = "PARTIAL"
                partials.append({"version": [obj, ver],
                                 "pending": "staged state without generating event"})
            else:
                origin = "+".join(sorted(set(gens)))
            links.append({"version": ver, "origin": origin})
        chains[obj] = {"versions": versions, "links": links}
    intervals: dict[str, list] = []
    intervals = {}
    for cid in sorted(model.collections):
        coll = model.collections[cid]
        rebuilt = []
        for member in sorted(coll["members"], key=lambda m: (m["key"], str(m["member"]))):
            inserted = any(e.get("kind") == "insert" and e.get("key") == member["key"]
                           and e.get("collection") == cid for e in model.events)
            removed = [e for e in model.events
                       if e.get("kind") == "remove" and e.get("key") == member["key"]
                       and e.get("collection") == cid]
            baseline_member = member["inserted_by"] == -1
            entry = {"key": member["key"], "member": member["member"],
                     "inserted": bool(inserted or baseline_member),
                     "removed": member["removed_by"],
                     "removal_events": len(removed)}
            if not entry["inserted"] and member["inserted_by"] != -1:
                partials.append({"membership": [cid, member["key"]],
                                 "pending": "staged membership without insert event"})
            rebuilt.append(entry)
        intervals[cid] = rebuilt
    # Verify initial baseline versions are untouched.
    baseline_ok = True
    for key, digest in baseline.get("versions", {}).items():
        current = model.versions.get(tuple(key))
        if current is None or current["content_digest"] != digest:
            baseline_ok = False
    digest = sha(canonical({"chains": chains, "intervals": intervals,
                            "partials": sorted(
                                (str(sorted(p.items()))) for p in partials),
                            "baseline_ok": baseline_ok}))
    return {"chains": chains, "intervals": intervals, "partials": partials,
            "baseline_ok": baseline_ok, "digest": digest,
            "complete": not partials and baseline_ok}
