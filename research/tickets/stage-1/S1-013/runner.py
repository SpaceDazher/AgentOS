"""Strict synthetic-only importer. Browser envelopes and fixtures share a boundary."""
import argparse
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("s1013_contract", HERE / "contract.py")
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)
canonical = contract.canonical

def sha(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()

def import_session(sess, events_doc, answers_doc, seen_pids):
    docs = {"session": sess, "events": events_doc, "answers": answers_doc}
    sid = sess.get("session_id", "") if isinstance(sess, dict) else ""
    sid = sid if isinstance(sid, str) and re.fullmatch(r"S-[A-Z0-9-]{1,40}", sid) else "INVALID"
    if contract.has_private(docs):
        return {"session_id": sid, "status": "quarantined", "reason": "PII_OR_CONSENT_TEXT", "problems": []}
    try:
        for name, doc in docs.items():
            contract.validate(doc, contract.load(f"schemas/{name}.schema.json"))
        protocol = contract.load("pilot-protocol.json")
        if sess["protocol_version"] != protocol["protocol_version"]:
            raise ValueError("protocol version drift")
        if sess.get("contract_sha256") != contract.digest(protocol):
            raise ValueError("protocol digest mismatch")
        if sess["synthetic"] is not True or sess["cohort"] != "synthetic":
            raise ValueError("non-synthetic record refused by preparation build")
        if not sess["consent"]["given"] or sess["consent"]["version"] != protocol["consent_version"]:
            raise ValueError("missing/invalid consent")
        if sess["participant_id"] in seen_pids:
            raise ValueError("duplicate participant id")
        if "sid:" + sid in seen_pids:
            raise ValueError("duplicate session id")
        if events_doc["session_id"] != sid or answers_doc["session_id"] != sid:
            raise ValueError("session binding mismatch")
        events = events_doc["events"]
        scenarios = contract.load("scenario-manifest.json")
        tasks = {s["id"]: s["measure"] for s in scenarios["comprehension_scenarios"]}
        blocks = {b["block"]: b for b in scenarios["approval_blocks"]}
        prompts = {p["prompt_id"]: b["block"] for b in blocks.values() for p in b["prompts"]}
        prompt_definitions = {p["prompt_id"]: p for b in blocks.values() for p in b["prompts"]}
        presented, answered, decisions, started_blocks = set(), set(), set(), set()
        active, paused = None, False
        requested, confirmed, withdrawn = False, False, False
        previous = -1
        for i, event in enumerate(events):
            if withdrawn:
                raise ValueError("events after withdrawal")
            if event["seq"] != i or event["t_ms"] < previous:
                raise ValueError("non-contiguous sequence or backwards time")
            previous = event["t_ms"]
            kind, pid = event["type"], event.get("prompt_id")
            if kind == "prompt_displayed":
                if pid in presented or pid not in tasks and pid not in prompts:
                    raise ValueError("unknown/duplicate prompt")
                if pid in prompts and (active != prompts[pid] or paused):
                    raise ValueError("approval prompt outside active block")
                if pid in prompts:
                    definition = prompt_definitions[pid]
                    if any(event.get(key + "_shown") != definition[key] for key in ("actor", "action", "scope")) or event.get("expiry_shown") is not (definition["expiry"] is not None):
                        raise ValueError("displayed approval differs from frozen prompt")
                if pid in tasks and any(tasks.get(p) == tasks[pid] for p in presented):
                    raise ValueError("duplicate comprehension measure")
                presented.add(pid)
            elif kind == "answer":
                if pid not in presented or pid not in tasks or pid in answered:
                    raise ValueError("answer without unique presentation")
                answered.add(pid)
            elif kind == "decision":
                if pid not in presented or pid not in prompts or pid in decisions or active != prompts[pid] or paused:
                    raise ValueError("decision without active unique approval")
                if event.get("decision") not in ("approve", "deny", "abstain"):
                    raise ValueError("decision missing")
                decisions.add(pid)
            elif kind == "block_started":
                bid = event.get("block_id")
                if active is not None or bid not in blocks or bid in started_blocks:
                    raise ValueError("invalid block start")
                active, paused = bid, False
                started_blocks.add(bid)
            elif kind in ("block_paused", "block_resumed", "block_ended"):
                if active is None or event.get("block_id") != active:
                    raise ValueError("block transition mismatch")
                if kind == "block_paused":
                    if paused: raise ValueError("already paused")
                    paused = True
                elif kind == "block_resumed":
                    if not paused: raise ValueError("not paused")
                    paused = False
                else:
                    active = None
            elif kind == "stop_requested":
                if requested or not any(tasks.get(p) == "C5" for p in presented):
                    raise ValueError("stop without unique C5 presentation")
                requested = True
            elif kind in ("stop_confirmed", "stop_failed"):
                if not requested or confirmed:
                    raise ValueError("stop outcome without request")
                confirmed = True
                if kind == "stop_confirmed":
                    acks = event.get("acknowledgements") or []
                    expected = protocol["mock_agents"]
                    if event.get("acknowledged") is not True or len(acks) != len(expected) or {a["agent_id"] for a in acks} != set(expected) or any(a["state"] != "stopped" for a in acks):
                        raise ValueError("unconfirmed mock agents")
            elif kind == "fatigue_report":
                if event.get("fatigue") not in ("ok", "tired", "stop"):
                    raise ValueError("missing fatigue value")
            elif kind == "withdrawn":
                withdrawn = True
        seen_measures = set()
        for response in answers_doc["responses"]:
            measure, pid = response["measure"], response.get("scenario_id")
            if measure in seen_measures or tasks.get(pid) != measure or pid not in answered:
                raise ValueError("duplicate/unbound measure response")
            seen_measures.add(measure)
        if answered != {x["scenario_id"] for x in answers_doc["responses"]}:
            raise ValueError("answer event/payload mismatch")
    except (ValueError, KeyError, TypeError, AttributeError):
        return {"session_id": sid, "status": "rejected", "reason": "invalid schema/version/lifecycle or duplicate participant", "problems": []}
    seen_pids.add(sess["participant_id"])
    seen_pids.add("sid:" + sid)
    return {"session_id": sid, "status": "ok", "participant_id": sess["participant_id"],
            "role": sess["role"], "session_sha256": contract.digest(sess),
            "record_sha256": contract.digest(docs), "record": docs,
            "event_count": len(events), "response_count": len(answers_doc["responses"]), "problems": []}

def import_export(doc, seen):
    if not isinstance(doc, dict) or set(doc) != {"schema", "session", "events", "answers"} or doc.get("schema") != "agentos.s1-013.export/v1":
        return {"session_id": "INVALID", "status": "rejected", "reason": "invalid export envelope", "problems": []}
    return import_session(doc["session"], doc["events"], doc["answers"], seen)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    source, target = Path(args.src), Path(args.out)
    paths = sorted(source.glob("*.export.json")) + sorted(source.glob("*.session.json"))
    observations, seen = [], set()
    for path in paths:
        try:
            if path.stat().st_size > 2_000_000: raise ValueError("oversize")
            if path.name.endswith(".export.json"):
                doc = contract.loads(path.read_text(encoding="utf-8"))
            else:
                stem = path.name[:-len(".session.json")]
                doc = {"schema": "agentos.s1-013.export/v1"}
                for name in ("session", "events", "answers"):
                    raw = (source / f"{stem}.{name}.json").read_bytes()
                    if len(raw) > 2_000_000: raise ValueError("oversize")
                    doc[name] = contract.loads(raw.decode("utf-8"))
            obs = import_export(doc, seen)
        except (OSError, ValueError):
            obs = {"session_id": "INVALID", "status": "rejected", "reason": "unreadable input", "problems": []}
        obs["output_sha256"] = contract.digest(obs)
        observations.append(obs)
    target.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": "agentos.s1-013.import-manifest/v1", "sessions": len(observations)}
    for status in ("ok", "rejected", "quarantined"):
        manifest[status] = sum(o["status"] == status for o in observations)
    for name, obj in (("observations", {"schema": "agentos.s1-013.observations/v1", "observations": observations}), ("import-manifest", manifest)):
        (target / (name + ".json")).write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest))
    return 0 if observations else 1

if __name__ == "__main__":
    raise SystemExit(main())
