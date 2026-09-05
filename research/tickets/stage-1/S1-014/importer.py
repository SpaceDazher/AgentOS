"""S1-014 strict envelope importer.

Accepts only a versioned browser envelope bound to the frozen browser contract
and to a frozen assignment.  Anything rejected or quarantined is returned with
a reason and must never be copied into tracked evidence.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as c  # noqa: E402

PII_PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"(?<!\d)\+?\d[\d\s().-]{8,}\d(?!\d)"),
    "secret": re.compile(r"(?i)(api[_-]?key|secret|password|bearer\s+[a-z0-9._-]{16,}|-----BEGIN)"),
    "ipv4": re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"),
    "long_token": re.compile(r"(?<![0-9a-f])[A-Za-z0-9+/_-]{40,}(?![0-9a-f])"),
}
FORBIDDEN_KEYS = {"name", "full_name", "email", "phone", "address", "consent_text",
                  "free_text", "notes", "comment", "identity", "ip", "user_agent",
                  "correct", "is_correct", "score", "adjudicated", "rater", "verdict",
                  "winner"}
TERMINAL = {"task_submitted", "task_timeout"}
ALLOWED_HEX = re.compile(r"^[0-9a-f]{64}$")


def privacy_scan(node: Any, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key.lower() in FORBIDDEN_KEYS:
                hits.append(f"{path}.{key}: forbidden key")
            hits.extend(privacy_scan(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            hits.extend(privacy_scan(item, f"{path}[{index}]"))
    elif isinstance(node, str):
        if ALLOWED_HEX.fullmatch(node) or c.OPAQUE_ID.fullmatch(node):
            return hits
        for label, pattern in PII_PATTERNS.items():
            if pattern.search(node):
                hits.append(f"{path}: {label} pattern")
    return hits


def import_envelope(doc: Any, seen_sessions: set[str], seen_participants: set[str],
                    frozen: dict | None = None) -> dict:
    """Return {'status': 'ok'|'rejected'|'quarantined', 'reasons': [...], 'observation': {...}}."""
    frozen = frozen if frozen is not None else c.frozen_browser_contract()
    reasons: list[str] = []
    pii = privacy_scan(doc)
    if pii:
        return {"status": "quarantined", "reasons": pii[:20], "observation": None}
    errors = c.validate(doc, c.schema("envelope"))
    if errors:
        return {"status": "rejected", "reasons": errors[:20], "observation": None}
    if doc["contract_sha256"] != frozen["contract_sha256"]:
        reasons.append("contract digest does not match frozen browser contract")
    if doc["contract_version"] != frozen["contract_version"]:
        reasons.append("contract version mismatch")
    body = {k: v for k, v in doc.items() if k != "payload_sha256"}
    if c.digest(body) != doc["payload_sha256"]:
        reasons.append("payload digest mismatch")
    session = doc["session"]
    if session["session_id"] in seen_sessions:
        reasons.append("duplicate session id")
    if session["participant_id"] in seen_participants:
        reasons.append("participant reuse across sessions")
    if session["session_id"] == session["participant_id"]:
        reasons.append("session and participant ids must differ")
    if not session["consent"]["given"]:
        reasons.append("consent not given")
    assignment = next((a for a in frozen["assignments"]
                       if a["assignment_sha256"] == session["assignment_sha256"]), None)
    if assignment is None:
        reasons.append("assignment binding unknown")
    elif assignment["seed"] != session["seed"] or assignment["executor"] != session["executor"]:
        reasons.append("assignment drift: seed/executor differ from bound table")
    else:
        expected = {(t["position"], t["dispute_id"], t["variant"]) for t in assignment["trials"]}
        actual = {(t["position"], t["dispute_id"], t["variant"]) for t in doc["trials"]}
        if expected != actual:
            reasons.append("assignment drift: trials differ from bound table")
        if len(doc["trials"]) != len(assignment["trials"]):
            reasons.append("trial count differs from assignment (denominator drift)")
    positions = [t["position"] for t in doc["trials"]]
    if len(set(positions)) != len(positions):
        reasons.append("duplicate trial position")
    events = doc["events"]
    seqs = [e["seq"] for e in events]
    if seqs != list(range(1, len(events) + 1)):
        reasons.append("event sequence gap or reorder")
    times = [e["t_ms"] for e in events]
    if any(b < a for a, b in zip(times, times[1:])):
        reasons.append("non-monotonic event time")
    types = [e["type"] for e in events]
    if types[:1] != ["consent_given"]:
        reasons.append("lifecycle must start with consent_given")
    if "practice_start" not in types or "practice_end" not in types:
        reasons.append("practice task missing from lifecycle")
    terminal = types[-1] if types else None
    if session["lifecycle"] == "complete" and terminal != "session_complete":
        reasons.append("complete lifecycle without session_complete event")
    if session["lifecycle"] == "withdrawn" and terminal != "withdraw":
        reasons.append("withdrawn lifecycle without withdraw event")
    if session["lifecycle"] == "incomplete":
        reasons.append("incomplete lifecycle is not importable")
    presented = {(e["dispute_id"], e["variant"]) for e in events if e["type"] == "task_presented"}
    for t in doc["trials"]:
        key = (t["dispute_id"], t["variant"])
        if t["outcome"] in ("submitted", "timeout"):
            if key not in presented:
                reasons.append(f"trial {t['position']} answered without task_presented event")
            if t["presented_t_ms"] is None or t["submitted_t_ms"] is None:
                reasons.append(f"trial {t['position']} lacks presentation/submit timestamps")
            elif t["submitted_t_ms"] < t["presented_t_ms"]:
                reasons.append(f"trial {t['position']} submit precedes presentation")
            if t["outcome"] == "timeout" and not any(
                    e["type"] == "task_timeout" and (e.get("dispute_id"), e.get("variant")) == key for e in events):
                reasons.append(f"trial {t['position']} timeout without timeout event")
        else:
            if t["answer"] != "__MISSING__":
                reasons.append(f"trial {t['position']} missing outcome carries an answer")
        if t["pointer_used"] and session["accessibility_mode"] != "pointer":
            reasons.append(f"trial {t['position']} pointer use in non-pointer mode")
    paused = 0
    for e in events:
        if e["type"] == "pause":
            paused += 1
        elif e["type"] == "resume":
            paused -= 1
        if paused not in (0, 1):
            reasons.append("pause/resume imbalance")
            break
    if reasons:
        return {"status": "rejected", "reasons": sorted(set(reasons))[:30], "observation": None}
    seen_sessions.add(session["session_id"])
    seen_participants.add(session["participant_id"])
    observation = {
        "session_id": session["session_id"], "participant_id": session["participant_id"],
        "role": session["role"], "seed": session["seed"], "executor": session["executor"],
        "assignment_sha256": session["assignment_sha256"],
        "accessibility_mode": session["accessibility_mode"], "lifecycle": session["lifecycle"],
        "contract_sha256": doc["contract_sha256"], "payload_sha256": doc["payload_sha256"],
        "trials": sorted(doc["trials"], key=lambda t: t["position"]),
        "event_counts": {t: types.count(t) for t in sorted(set(types))},
        "human": False if session["role"] == "synthetic_technical_replay" else None,
    }
    observation["observation_sha256"] = c.digest(observation)
    return {"status": "ok", "reasons": [], "observation": observation}


def import_directory(source: Path, out_dir: Path, frozen: dict | None = None) -> dict:
    """Import every ``*.json`` envelope in ``source``; write manifest + observations."""
    frozen = frozen if frozen is not None else c.frozen_browser_contract()
    seen_s: set[str] = set()
    seen_p: set[str] = set()
    manifest: list[dict] = []
    observations: list[dict] = []
    for path in sorted(source.glob("*.json")):
        raw = path.read_bytes()
        try:
            doc = c.strict_loads(raw)
        except (c.ContractError, ValueError, UnicodeDecodeError) as exc:
            manifest.append({"file": path.name, "sha256": c.sha_bytes(raw), "status": "rejected",
                             "reasons": [f"strict JSON: {exc}"]})
            continue
        result = import_envelope(doc, seen_s, seen_p, frozen)
        entry = {"file": path.name, "sha256": c.sha_bytes(raw), "status": result["status"],
                 "reasons": result["reasons"]}
        manifest.append(entry)
        if result["status"] == "ok":
            observations.append(result["observation"])
    out = {"schema": c.OBSERVATIONS_SCHEMA, "contract_sha256": frozen["contract_sha256"],
           "observations": observations}
    out["observations_sha256"] = c.digest(observations)
    c.dump(out_dir / "import-manifest.json",
           {"schema": "agentos.s1-014.import-manifest/v1", "entries": manifest,
            "accepted": sum(1 for m in manifest if m["status"] == "ok"),
            "rejected": sum(1 for m in manifest if m["status"] == "rejected"),
            "quarantined": sum(1 for m in manifest if m["status"] == "quarantined")})
    c.dump(out_dir / "observations.json", out)
    return out


if __name__ == "__main__":
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    result = import_directory(src, dst)
    print(f"imported {len(result['observations'])} observation(s)")
