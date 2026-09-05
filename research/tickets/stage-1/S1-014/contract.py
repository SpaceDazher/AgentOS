"""S1-014 canonical claim-dispute contract.

One authoritative machine-checkable contract feeds the card renderer, the
graph renderer, the browser fixture, the importer and the evaluator.  Nothing
in this module decides a human winner; it only defines data, parity rules and
deterministic helpers.  The oracle (correct answers) lives in ``oracle/`` and is
never copied into the browser contract.

stdlib only; no network.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

TICKET = Path(__file__).resolve().parent
REPO = TICKET.parents[3]
TICKET_ID = "S1-014"
CONTRACT_SCHEMA = "agentos.s1-014.dispute-contract/v1"
CONTRACT_VERSION = "1.0.0"
ENVELOPE_SCHEMA = "agentos.s1-014.browser-envelope/v1"
OBSERVATIONS_SCHEMA = "agentos.s1-014.observations/v1"
VARIANTS = ("CARD", "GRAPH")
STRATA = ("simple", "medium", "complex")
STATUSES = ("promoted", "candidate", "rejected", "revoked", "unknown", "withheld")
ANSWER_CHOICES = ("focal_holds", "challenge_holds", "undetermined", "withheld_cannot_decide")
OVERLOAD_CHOICES = ("low", "medium", "high", "not_reported")
BANNER = "OPERATOR DESIGN REVIEW \u2014 NOT A USER STUDY"
OPAQUE_ID = re.compile(r"^[A-Z]{2,4}-[0-9a-f]{8,32}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SEEDS = ("seed-0001", "seed-0002", "seed-0003")
EXECUTORS = ("EXEC-RUN-A", "EXEC-RUN-B")

# Frozen disclosure rule: max actions allowed to reveal each cue (0 = level-0).
DISCLOSURE_RULE = {
    "focal_claim": 0, "challenge_indicator": 0, "status": 0, "source_cue": 0,
    "independence_cue": 0, "provenance_detail": 1, "evidence_detail": 1,
    "relations_detail": 1,
}


class ContractError(ValueError):
    """Fail-closed contract violation."""


# ----------------------------------------------------------------- strict JSON
def _no_dup_pairs(pairs: list[tuple[str, Any]]) -> dict:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ContractError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _bad_constant(name: str) -> Any:
    raise ContractError(f"non-finite JSON constant rejected: {name}")


def strict_loads(text: str | bytes) -> Any:
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    return json.loads(text, object_pairs_hook=_no_dup_pairs, parse_constant=_bad_constant)


def load_json(path: Path) -> Any:
    return strict_loads(path.read_bytes())


def _check_finite(v: Any) -> None:
    if isinstance(v, float) and not math.isfinite(v):
        raise ContractError("non-finite float in canonical document")
    if isinstance(v, dict):
        for item in v.values():
            _check_finite(item)
    elif isinstance(v, list):
        for item in v:
            _check_finite(item)


def canonical(value: Any) -> bytes:
    _check_finite(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                               allow_nan=False) + "\n", encoding="utf-8")


# ------------------------------------------- minimal fail-closed schema check
_TYPES = {"object": dict, "array": list, "string": str, "integer": int,
          "number": (int, float), "boolean": bool, "null": type(None)}


def validate(instance: Any, schema: dict, path: str = "$", root: dict | None = None) -> list[str]:
    root = root if root is not None else schema
    errors: list[str] = []
    if "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return [f"{path}: remote or malformed $ref rejected"]
        target: Any = root
        for part in ref[2:].split("/"):
            if not isinstance(target, dict) or part not in target:
                return [f"{path}: unresolvable local $ref {ref}"]
            target = target[part]
        return validate(instance, target, path, root)
    typ = schema.get("type")
    if typ is not None:
        allowed = typ if isinstance(typ, list) else [typ]
        ok = False
        for name in allowed:
            py = _TYPES.get(name)
            if py is None:
                return [f"{path}: unknown schema type {name}"]
            if name in ("integer", "number") and isinstance(instance, bool):
                continue
            if isinstance(instance, py):
                ok = True
        if not ok:
            return [f"{path}: expected {allowed}, got {type(instance).__name__}"]
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value {instance!r} not in enum")
    if isinstance(instance, str):
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(f"{path}: pattern mismatch")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: too long")
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: too short")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if not math.isfinite(instance):
            errors.append(f"{path}: non-finite number")
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: above maximum")
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required {key}")
        for key, value in instance.items():
            if key in props:
                errors.extend(validate(value, props[key], f"{path}.{key}", root))
            elif schema.get("additionalProperties", True) is False:
                errors.append(f"{path}: unexpected field {key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(validate(value, schema["additionalProperties"], f"{path}.{key}", root))
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems") and len({canonical(i) for i in instance}) != len(instance):
            errors.append(f"{path}: duplicate items")
        if "items" in schema:
            for index, item in enumerate(instance):
                errors.extend(validate(item, schema["items"], f"{path}[{index}]", root))
    return errors


def schema(name: str) -> dict:
    return load_json(TICKET / "schemas" / f"{name}.schema.json")


def validate_dispute(doc: Any) -> list[str]:
    errors = validate(doc, schema("dispute"))
    if errors:
        return errors
    ids = {e["evidence_id"] for e in doc["evidence"]}
    srcs = {s["source_id"] for s in doc["sources"]}
    groups = {g["group_id"] for g in doc["independence_groups"]}
    claims = {doc["focal_claim"]["claim_id"], doc["challenge_claim"]["claim_id"]}
    if len(claims) != 2:
        errors.append("focal and challenge claims must be distinct")
    for ev in doc["evidence"]:
        if ev["source_id"] not in srcs:
            errors.append(f"evidence {ev['evidence_id']} unknown source")
        if ev["independence_group"] not in groups:
            errors.append(f"evidence {ev['evidence_id']} unknown group")
    for rel in doc["relations"]:
        if rel["from_evidence"] not in ids:
            errors.append(f"relation from unknown evidence {rel['from_evidence']}")
        if rel["to_claim"] not in claims:
            errors.append(f"relation to unknown claim {rel['to_claim']}")
    for key in ("supporting_evidence", "challenging_evidence"):
        for ev_id in doc[key]:
            if ev_id not in ids:
                errors.append(f"{key} references unknown evidence {ev_id}")
    if not doc["challenging_evidence"]:
        errors.append("a dispute must carry at least one challenging relation")
    if doc["contract_version"] != CONTRACT_VERSION:
        errors.append("unsupported contract_version")
    if doc.get("renderer_may_change_authority") is not False:
        errors.append("renderer authority flag must be false")
    return errors


# ------------------------------------------------ corpus + separate oracle
def _src(sid: str, publisher: str, origin: str, boundary: str, state: str = "known") -> dict:
    return {"source_id": sid, "publisher": publisher, "origin": origin,
            "retrieval_boundary": boundary, "provenance_state": state}


def _ev(eid: str, sid: str, group: str, text: str, state: str = "known") -> dict:
    return {"evidence_id": eid, "source_id": sid, "independence_group": group,
            "summary": text, "evidence_state": state}


def _rel(eid: str, claim: str, kind: str) -> dict:
    return {"from_evidence": eid, "to_claim": claim, "relation": kind}


def _g(gid: str, label: str, basis: str) -> dict:
    return {"group_id": gid, "label": label, "independence_basis": basis}


def _dispute(num: int, stratum: str, focal: str, focal_status: str, challenge: str,
             challenge_status: str, sources: list, groups: list, evidence: list,
             relations: list, wording: str, gate_state: str,
             withheld: list[str] | None = None) -> dict:
    did = f"DSP-{hashlib.sha256(f'{TICKET_ID}:{num}'.encode()).hexdigest()[:12]}"
    fid, cid = f"CLM-{num:02d}A", f"CLM-{num:02d}B"
    return {
        "contract_schema": CONTRACT_SCHEMA, "contract_version": CONTRACT_VERSION,
        "dispute_id": did, "ordinal": num, "complexity_stratum": stratum,
        "task_wording": wording, "answer_choices": list(ANSWER_CHOICES),
        "focal_claim": {"claim_id": fid, "text": focal, "status": focal_status},
        "challenge_claim": {"claim_id": cid, "text": challenge, "status": challenge_status},
        "knowledge_gate_state": gate_state,
        "sources": sources, "independence_groups": groups,
        "evidence": evidence, "relations": relations,
        "supporting_evidence": [r["from_evidence"] for r in relations
                                if r["relation"] == "supports" and r["to_claim"] == fid],
        "challenging_evidence": sorted({r["from_evidence"] for r in relations
                                        if r["to_claim"] == cid or r["relation"] == "challenges"}),
        "withheld_fields": withheld or [],
        "renderer_may_change_authority": False,
    }


def build_corpus() -> tuple[list[dict], dict]:
    """Return (public dispute documents, frozen oracle)."""
    docs: list[dict] = []
    oracle: dict[str, dict] = {}

    def add(doc: dict, answer: str, needed: list[str], rationale: str) -> None:
        docs.append(doc)
        oracle[doc["dispute_id"]] = {
            "correct_answer": answer, "provenance_recall_set": sorted(needed),
            "challenge_present": True, "scoring_rationale": rationale,
        }

    add(_dispute(1, "simple", "Agent A-1 may read the shared workspace W-2.", "promoted",
                 "Agent A-1 was never granted W-2 access.", "candidate",
                 [_src("SRC-a1", "Workspace registry", "Workspace registry", "2026-08-01T00:00:00Z"),
                  _src("SRC-a2", "Colleague message", "Colleague message", "2026-08-02T00:00:00Z")],
                 [_g("IG-1", "registry", "system record"), _g("IG-2", "colleague", "human report")],
                 [_ev("EV-01", "SRC-a1", "IG-1", "Grant record lists A-1 with read scope on W-2."),
                  _ev("EV-02", "SRC-a2", "IG-2", "Colleague recalls no grant being made.")],
                 [_rel("EV-01", "CLM-01A", "supports"), _rel("EV-02", "CLM-01B", "supports")],
                 "Which claim holds given the evidence shown?", "promoted"),
        "focal_holds", ["SRC-a1"],
        "direct claim versus one challenge: promoted registry record vs unverified recollection.")

    add(_dispute(2, "medium", "Build 42 passed the acceptance gate.", "candidate",
                 "Build 42 acceptance evidence is not independent.", "candidate",
                 [_src("SRC-b1", "CI mirror", "Vendor CI log", "2026-08-03T00:00:00Z"),
                  _src("SRC-b2", "CI mirror", "Vendor CI log", "2026-08-03T00:00:00Z"),
                  _src("SRC-b3", "CI mirror", "Vendor CI log", "2026-08-03T00:00:00Z")],
                 [_g("IG-1", "single CI cluster", "same origin, same pipeline")],
                 [_ev("EV-01", "SRC-b1", "IG-1", "CI status green."),
                  _ev("EV-02", "SRC-b2", "IG-1", "CI summary green."),
                  _ev("EV-03", "SRC-b3", "IG-1", "CI badge green.")],
                 [_rel("EV-01", "CLM-02A", "supports"), _rel("EV-02", "CLM-02A", "supports"),
                  _rel("EV-03", "CLM-02A", "supports"), _rel("EV-01", "CLM-02B", "supports")],
                 "Is the focal claim corroborated by independent evidence?", "candidate"),
        "challenge_holds", ["SRC-b1", "SRC-b2", "SRC-b3"],
        "several supports from one independence group count once (S1-012 rule).")

    add(_dispute(3, "medium", "Release 7 was signed by the release key.", "candidate",
                 "Release 7 signature is unverified.", "candidate",
                 [_src("SRC-c1", "Signing service", "HSM audit log", "2026-08-04T00:00:00Z"),
                  _src("SRC-c2", "Transparency log", "Public log operator", "2026-08-04T00:00:00Z"),
                  _src("SRC-c3", "Reviewer note", "Reviewer note", "2026-08-05T00:00:00Z")],
                 [_g("IG-1", "signing", "HSM"), _g("IG-2", "transparency", "third-party log"),
                  _g("IG-3", "reviewer", "human review")],
                 [_ev("EV-01", "SRC-c1", "IG-1", "HSM log records signing event."),
                  _ev("EV-02", "SRC-c2", "IG-2", "Transparency log includes matching digest."),
                  _ev("EV-03", "SRC-c3", "IG-3", "Reviewer says signature was not checked.")],
                 [_rel("EV-01", "CLM-03A", "supports"), _rel("EV-02", "CLM-03A", "supports"),
                  _rel("EV-03", "CLM-03B", "supports")],
                 "Which claim holds given the evidence shown?", "candidate"),
        "focal_holds", ["SRC-c1", "SRC-c2"],
        "genuinely independent corroboration across two groups; challenge is one opinion.")

    add(_dispute(4, "simple", "Delegation grant G-9 expired on 2026-08-01.", "promoted",
                 "Grant G-9 is still active.", "rejected",
                 [_src("SRC-d1", "Grant ledger", "Grant ledger", "2026-08-06T00:00:00Z"),
                  _src("SRC-d2", "Agent self-report", "Agent A-3", "2026-08-06T00:00:00Z")],
                 [_g("IG-1", "ledger", "system record"), _g("IG-2", "agent", "self report")],
                 [_ev("EV-01", "SRC-d1", "IG-1", "Ledger shows expiry timestamp."),
                  _ev("EV-02", "SRC-d2", "IG-2", "Agent claims grant still valid.")],
                 [_rel("EV-01", "CLM-04A", "supports"), _rel("EV-02", "CLM-04B", "supports")],
                 "Which claim holds given the evidence shown?", "promoted"),
        "focal_holds", ["SRC-d1"],
        "strong winning claim; the rejected challenge must remain visible (probe B).")

    add(_dispute(5, "complex", "Assertion K-12 is promoted knowledge.", "revoked",
                 "Assertion K-12 was withdrawn by its author.", "unknown",
                 [_src("SRC-e1", "Knowledge gate", "Knowledge gate", "2026-08-07T00:00:00Z"),
                  _src("SRC-e2", "Author notice", "Author", "2026-08-07T00:00:00Z", "withheld")],
                 [_g("IG-1", "gate", "system record"), _g("IG-2", "author", "human")],
                 [_ev("EV-01", "SRC-e1", "IG-1", "Gate log: K-12 revoked after review."),
                  _ev("EV-02", "SRC-e2", "IG-2", "Notice content withheld by policy.", "withheld")],
                 [_rel("EV-01", "CLM-05A", "challenges"), _rel("EV-02", "CLM-05B", "supports")],
                 "Can the dispute be decided from the evidence shown?", "revoked",
                 withheld=["evidence.EV-02.summary"]),
        "withheld_cannot_decide", ["SRC-e1"],
        "revoked focal status plus withheld challenge evidence: defer, do not invent.")

    add(_dispute(6, "medium", "Dataset D-3 originates from the public statistics office.", "candidate",
                 "Dataset D-3 was republished by a third party without origin.", "candidate",
                 [_src("SRC-f1", "Mirror portal", "Public statistics office", "2026-08-08T00:00:00Z"),
                  _src("SRC-f2", "Mirror portal", "Mirror portal", "2026-08-08T00:00:00Z")],
                 [_g("IG-1", "office chain", "origin attested"), _g("IG-2", "mirror only", "no origin")],
                 [_ev("EV-01", "SRC-f1", "IG-1", "Mirror copy carries origin attestation."),
                  _ev("EV-02", "SRC-f2", "IG-2", "Second copy lacks origin metadata.")],
                 [_rel("EV-01", "CLM-06A", "supports"), _rel("EV-02", "CLM-06B", "supports")],
                 "Which claim holds given the evidence shown?", "candidate"),
        "focal_holds", ["SRC-f1"],
        "publisher differs from origin; the attested chain decides (probe A).")

    many_src = [_src(f"SRC-g{i}", f"Sensor hub {i}", f"Sensor {i}", "2026-08-09T00:00:00Z") for i in range(1, 7)]
    many_groups = [_g(f"IG-{i}", f"sensor {i}", "independent device") for i in range(1, 7)]
    many_ev = [_ev(f"EV-0{i}", f"SRC-g{i}", f"IG-{i}", f"Sensor {i} reports nominal.") for i in range(1, 6)]
    many_ev.append(_ev("EV-06", "SRC-g6", "IG-6", "Sensor 6 reports over limit."))
    many_rel = [_rel(f"EV-0{i}", "CLM-07A", "supports") for i in range(1, 6)] + [_rel("EV-06", "CLM-07B", "supports")]
    add(_dispute(7, "complex", "Rack R-1 is within thermal limits.", "candidate",
                 "Rack R-1 exceeds thermal limits.", "candidate",
                 many_src, many_groups, many_ev, many_rel,
                 "Which claim holds given the evidence shown?", "candidate"),
        "focal_holds", [f"SRC-g{i}" for i in range(1, 6)],
        "near-miss: many nodes, simple decision (five independent supports vs one).")

    add(_dispute(8, "complex", "Message M-5 came from colleague C-2.", "candidate",
                 "Message M-5 was relayed by an external agent claiming to be C-2.", "candidate",
                 [_src("SRC-h1", "Chat relay", "External agent X-9", "2026-08-10T00:00:00Z"),
                  _src("SRC-h2", "Identity directory", "Identity directory", "2026-08-10T00:00:00Z")],
                 [_g("IG-1", "relay", "self-asserted"), _g("IG-2", "directory", "system record")],
                 [_ev("EV-01", "SRC-h1", "IG-1", "Relay header names C-2 as sender."),
                  _ev("EV-02", "SRC-h2", "IG-2", "Directory shows C-2 has no relay binding to X-9.")],
                 [_rel("EV-01", "CLM-08A", "supports"), _rel("EV-02", "CLM-08B", "supports"),
                  _rel("EV-02", "CLM-08A", "challenges")],
                 "Which claim holds given the evidence shown?", "candidate"),
        "challenge_holds", ["SRC-h1", "SRC-h2"],
        "small card, logically complex: relay publisher, external origin, directory challenge.")

    for doc in docs:
        problems = validate_dispute(doc)
        if problems:
            raise ContractError(f"corpus dispute {doc['ordinal']} invalid: {problems}")
    return docs, oracle


# --------------------------------------------------------- renderers
def render_card(doc: dict) -> dict:
    src_by_id = {s["source_id"]: s for s in doc["sources"]}
    level0 = {
        "focal_claim": doc["focal_claim"], "status": doc["focal_claim"]["status"],
        "knowledge_gate_state": doc["knowledge_gate_state"],
        "challenge_indicator": {"present": True, "claim": doc["challenge_claim"],
                                "challenging_count": len(doc["challenging_evidence"])},
        "source_cue": [dict(s) for s in doc["sources"]],
        "independence_cue": [{"group_id": g["group_id"], "label": g["label"],
                              "size": sum(1 for e in doc["evidence"] if e["independence_group"] == g["group_id"])}
                             for g in doc["independence_groups"]],
        "task_wording": doc["task_wording"], "answer_choices": doc["answer_choices"],
        "withheld_fields": doc["withheld_fields"],
    }
    disclosures = {
        "provenance_detail": {"actions_to_reveal": 1, "control": "button", "content": doc["sources"]},
        "evidence_detail": {"actions_to_reveal": 1, "control": "button",
                            "content": [dict(e, source=src_by_id[e["source_id"]]) for e in doc["evidence"]]},
        "relations_detail": {"actions_to_reveal": 1, "control": "button", "content": doc["relations"],
                             "independence_groups": doc["independence_groups"]},
    }
    return {"variant": "CARD", "dispute_id": doc["dispute_id"], "level0": level0, "disclosures": disclosures}


def render_graph(doc: dict) -> dict:
    nodes = [
        {"id": doc["focal_claim"]["claim_id"], "kind": "claim", "role": "focal",
         "label": doc["focal_claim"]["text"], "status": doc["focal_claim"]["status"]},
        {"id": doc["challenge_claim"]["claim_id"], "kind": "claim", "role": "challenge",
         "label": doc["challenge_claim"]["text"], "status": doc["challenge_claim"]["status"]},
    ]
    src_by_id = {s["source_id"]: s for s in doc["sources"]}
    for ev in doc["evidence"]:
        src = src_by_id[ev["source_id"]]
        nodes.append({"id": ev["evidence_id"], "kind": "evidence", "label": ev["summary"],
                      "source_id": src["source_id"], "publisher": src["publisher"], "origin": src["origin"],
                      "retrieval_boundary": src["retrieval_boundary"],
                      "provenance_state": src["provenance_state"],
                      "independence_group": ev["independence_group"], "evidence_state": ev["evidence_state"]})
    edges = [{"from": r["from_evidence"], "to": r["to_claim"], "relation": r["relation"]} for r in doc["relations"]]
    linear = [f"{n['kind']} {n['id']}: {n['label']}" +
              (f" [status {n['status']}]" if n["kind"] == "claim" else
               f" [source {n['source_id']} publisher {n['publisher']} origin {n['origin']} "
               f"group {n['independence_group']} state {n['evidence_state']}]") for n in nodes]
    linear += [f"edge {e['from']} {e['relation']} {e['to']}" for e in edges]
    return {"variant": "GRAPH", "dispute_id": doc["dispute_id"],
            "level0": {"nodes": nodes, "edges": edges, "groups": doc["independence_groups"],
                       "knowledge_gate_state": doc["knowledge_gate_state"],
                       "task_wording": doc["task_wording"], "answer_choices": doc["answer_choices"],
                       "withheld_fields": doc["withheld_fields"], "linear_equivalent": linear},
            "disclosures": {
                "provenance_detail": {"actions_to_reveal": 1, "control": "button", "content": doc["sources"]},
                "evidence_detail": {"actions_to_reveal": 1, "control": "button", "content": doc["evidence"]},
                "relations_detail": {"actions_to_reveal": 1, "control": "button", "content": doc["relations"],
                                     "independence_groups": doc["independence_groups"]}}}


def information_set(view: dict) -> dict:
    """Representation-free information content of a rendered view."""
    l0 = view["level0"]
    if view["variant"] == "CARD":
        claims = sorted([canonical(l0["focal_claim"]).decode(), canonical(l0["challenge_indicator"]["claim"]).decode()])
        evidence = sorted(canonical({k: e[k] for k in ("evidence_id", "source_id", "independence_group", "summary", "evidence_state")}).decode()
                          for e in view["disclosures"]["evidence_detail"]["content"])
        sources = sorted(canonical(s).decode() for s in l0["source_cue"])
        groups = sorted(g["group_id"] for g in l0["independence_cue"])
        relations = sorted(canonical(r).decode() for r in view["disclosures"]["relations_detail"]["content"])
        challenge_visible = bool(l0["challenge_indicator"]["present"])
    else:
        claim_nodes = [n for n in l0["nodes"] if n["kind"] == "claim"]
        claims = sorted(canonical({"claim_id": n["id"], "text": n["label"], "status": n["status"]}).decode() for n in claim_nodes)
        evidence = sorted(canonical({"evidence_id": n["id"], "source_id": n["source_id"], "independence_group": n["independence_group"],
                                     "summary": n["label"], "evidence_state": n["evidence_state"]}).decode()
                          for n in l0["nodes"] if n["kind"] == "evidence")
        seen: dict[str, dict] = {}
        for n in l0["nodes"]:
            if n["kind"] == "evidence":
                seen[n["source_id"]] = {"source_id": n["source_id"], "publisher": n["publisher"], "origin": n["origin"],
                                        "retrieval_boundary": n["retrieval_boundary"], "provenance_state": n["provenance_state"]}
        sources = sorted(canonical(s).decode() for s in seen.values())
        groups = sorted(g["group_id"] for g in l0["groups"])
        relations = sorted(canonical({"from_evidence": e["from"], "to_claim": e["to"], "relation": e["relation"]}).decode() for e in l0["edges"])
        challenge_visible = any(n["role"] == "challenge" for n in claim_nodes)
    return {"claims": claims, "evidence": evidence, "sources": sources, "independence_groups": groups,
            "relations": relations, "challenge_visible_level0": challenge_visible,
            "knowledge_gate_state": l0["knowledge_gate_state"], "task_wording": l0["task_wording"],
            "answer_choices": list(l0["answer_choices"]), "withheld_fields": list(l0["withheld_fields"]),
            "provenance_level0": bool(sources), "independence_level0": bool(groups)}


def canonical_information(doc: dict) -> dict:
    return {"claims": sorted([canonical(doc["focal_claim"]).decode(), canonical(doc["challenge_claim"]).decode()]),
            "evidence": sorted(canonical(e).decode() for e in doc["evidence"]),
            "sources": sorted(canonical(s).decode() for s in doc["sources"]),
            "independence_groups": sorted(g["group_id"] for g in doc["independence_groups"]),
            "relations": sorted(canonical(r).decode() for r in doc["relations"]),
            "challenge_visible_level0": True, "knowledge_gate_state": doc["knowledge_gate_state"],
            "task_wording": doc["task_wording"], "answer_choices": list(doc["answer_choices"]),
            "withheld_fields": list(doc["withheld_fields"]), "provenance_level0": True, "independence_level0": True}


def disclosure_costs(view: dict) -> dict:
    costs = {k: 0 for k in ("focal_claim", "challenge_indicator", "status", "source_cue", "independence_cue")}
    for name, disc in view["disclosures"].items():
        costs[name] = int(disc["actions_to_reveal"])
    return costs


def parity_report(doc: dict, card: dict | None = None, graph: dict | None = None) -> dict:
    card = card if card is not None else render_card(doc)
    graph = graph if graph is not None else render_graph(doc)
    ref = canonical_information(doc)
    ic, ig = information_set(card), information_set(graph)
    problems: list[str] = []
    for label, info in (("CARD", ic), ("GRAPH", ig)):
        for key, expected in ref.items():
            if info.get(key) != expected:
                problems.append(f"{label} differs from canonical on {key}")
    for label, view in (("CARD", card), ("GRAPH", graph)):
        costs = disclosure_costs(view)
        for cue, allowed in DISCLOSURE_RULE.items():
            actual = costs.get(cue)
            if actual is None or actual > allowed:
                problems.append(f"{label} needs {actual} actions for {cue} (rule {allowed})")
        for disc in view["disclosures"].values():
            if disc["control"] != "button":
                problems.append(f"{label} disclosure is not a keyboard control")
    if disclosure_costs(card) != disclosure_costs(graph):
        problems.append("disclosure action asymmetry between variants")
    if not graph["level0"].get("linear_equivalent"):
        problems.append("GRAPH has no linear accessible equivalent")
    return {"dispute_id": doc["dispute_id"], "equivalent": not problems, "problems": problems,
            "card_information_sha256": digest(ic), "graph_information_sha256": digest(ig),
            "canonical_information_sha256": digest(ref)}


# --------------------------------------------- deterministic counterbalancing
def assignment(seed: str, executor: str, disputes: list[dict]) -> dict:
    """4 CARD + 4 GRAPH, no dispute repeated, alternating variants, order by seed."""
    key = hashlib.sha256(f"{TICKET_ID}|{seed}|{executor}".encode()).digest()
    order = sorted(range(len(disputes)), key=lambda i: hashlib.sha256(key + bytes([i])).hexdigest())
    first = VARIANTS[key[0] % 2]
    trials = []
    for position, index in enumerate(order):
        variant = first if position % 2 == 0 else VARIANTS[1 - VARIANTS.index(first)]
        trials.append({"position": position, "dispute_id": disputes[index]["dispute_id"], "variant": variant})
    body = {"seed": seed, "executor": executor, "trials": trials}
    return dict(body, assignment_sha256=digest(body))


def browser_contract(disputes: list[dict]) -> dict:
    """Public browser payload.  The oracle is intentionally absent."""
    doc = {
        "contract_schema": CONTRACT_SCHEMA, "contract_version": CONTRACT_VERSION, "banner": BANNER,
        "disputes": disputes,
        "views": {d["dispute_id"]: {"CARD": render_card(d), "GRAPH": render_graph(d)} for d in disputes},
        "disclosure_rule": DISCLOSURE_RULE,
        "assignments": [assignment(s, e, disputes) for s in SEEDS for e in EXECUTORS],
        "schemas": {"dispute": schema("dispute"), "envelope": schema("envelope")},
        "answer_choices": list(ANSWER_CHOICES), "overload_choices": list(OVERLOAD_CHOICES),
    }
    doc["contract_sha256"] = digest(doc)
    return doc


def frozen_browser_contract() -> dict:
    return load_json(TICKET / "prototype" / "browser-contract.json")
