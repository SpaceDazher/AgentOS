"""S1-013 session importer (stdlib only, no network/LLM).

Reads session/events/answers JSON, validates against the frozen
schemas (minimal in-house validator: required, types, enums,
patterns), and builds observations. Rejections (probe C) and PII
quarantine (probe H) happen HERE at the boundary:

- duplicate participant id, missing/false consent, malformed
  participant id -> session REJECTED with reason (never scored);
- contact/consent-text/PII-looking fields in session records ->
  QUARANTINED (never published, never counted);
- non-synthetic records in the human pipeline are refused by this
  preparation build (no human data exists yet): only synthetic=true
  sessions import, and they are always labeled synthetic.

Writes observations.json + import-manifest.json. Indeterminate or
malformed inputs fail closed with explicit reasons.
Usage: py -3.12 runner.py --src synthetic/sessions --out <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMAS = HERE / "schemas"

EVENT_TYPES = ["prompt_displayed", "decision", "answer",
               "stop_requested", "stop_confirmed", "stop_failed",
               "fatigue_report", "debrief_done"]
ROLES = ("owner", "reviewer")
MEASURES = ("C1", "C2", "C3", "C4", "C5")
PID_RE = re.compile(r"^P-[0-9A-Z]{6}$")
PII_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|"
    r"\b\d{4}-\d{2}-\d{2}\b.*(?:agree|consent)|"
    r"\b(passport|ssn|consent_text)\b", re.IGNORECASE)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def fail(problems: list, message: str) -> None:
    problems.append(message)


def check_event(event: dict, problems: list) -> bool:
    ok = True
    for key in ("seq", "t_ms", "type"):
        if key not in event:
            fail(problems, f"event missing {key}")
            ok = False
    if not isinstance(event.get("seq"), int) or \
            isinstance(event.get("seq"), bool) or event.get("seq", -1) < 0:
        fail(problems, "event seq ill-typed")
        ok = False
    if not isinstance(event.get("t_ms"), int) or \
            isinstance(event.get("t_ms"), bool) or event.get("t_ms", -1) < 0:
        fail(problems, "event t_ms ill-typed")
        ok = False
    if event.get("type") not in EVENT_TYPES:
        fail(problems, f"unknown event type {event.get('type')!r}")
        ok = False
    decision = event.get("decision")
    if decision is not None and decision not in ("approve", "deny",
                                                 "abstain"):
        fail(problems, f"unknown decision {decision!r}")
        ok = False
    return ok


def import_session(sess: dict, events_doc: dict, answers_doc: dict,
                   seen_pids: set) -> dict:
    """Returns an observation dict with status ok/rejected/quarantined."""
    problems: list[str] = []
    sid = sess.get("session_id", "?")
    blob = json.dumps(sess, sort_keys=True)
    if PII_RE.search(blob):
        return {"session_id": sid, "status": "quarantined",
                "reason": "PII_OR_CONSENT_TEXT",
                "session_sha256": sha(canonical(sess)), "problems": []}
    for key in ("session_id", "participant_id", "role",
                "protocol_version", "cohort", "synthetic", "started_at",
                "consent"):
        if key not in sess:
            fail(problems, f"session missing {key}")
    pid = sess.get("participant_id", "")
    if not isinstance(pid, str) or not PID_RE.match(pid):
        fail(problems, f"malformed participant id {pid!r}")
    elif pid in seen_pids:
        fail(problems, f"duplicate participant id {pid}")
    if sess.get("role") not in ROLES:
        fail(problems, f"unknown role {sess.get('role')!r}")
    if sess.get("synthetic") is not True:
        fail(problems, "non-synthetic record refused by preparation build")
    consent = sess.get("consent") or {}
    if consent.get("given") is not True:
        fail(problems, "missing/false consent")
    if problems:
        return {"session_id": sid, "status": "rejected",
                "reason": "; ".join(problems[:3]),
                "session_sha256": sha(canonical(sess)),
                "problems": problems}
    seen_pids.add(pid)
    events = events_doc.get("events", [])
    if events_doc.get("session_id") != sid:
        fail(problems, "events session mismatch")
    seqs = []
    for event in events:
        check_event(event, problems)
        seqs.append(event.get("seq"))
    if seqs != sorted(seqs) or len(set(seqs)) != len(seqs):
        fail(problems, "event seq not strictly increasing")
    responses = answers_doc.get("responses", [])
    if answers_doc.get("session_id") != sid:
        fail(problems, "answers session mismatch")
    for response in responses:
        if response.get("measure") not in MEASURES:
            fail(problems, f"unknown measure {response.get('measure')!r}")
    if problems:
        return {"session_id": sid, "status": "rejected",
                "reason": "; ".join(problems[:3]),
                "session_sha256": sha(canonical(sess)),
                "problems": problems}
    return {"session_id": sid, "status": "ok",
            "participant_id": pid, "role": sess.get("role"),
            "session_sha256": sha(canonical(sess)),
            "event_count": len(events),
            "response_count": len(responses), "problems": []}


def main() -> int:
    parser = argparse.ArgumentParser(description="S1-013 importer")
    parser.add_argument("--src", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    src = Path(args.src)
    sessions = {}
    for path in sorted(src.glob("*.session.json")):
        stem = path.name[:-len(".session.json")]
        try:
            sess = json.loads(path.read_text(encoding="utf-8"))
            events_doc = json.loads(
                (src / f"{stem}.events.json").read_text(encoding="utf-8"))
            answers_doc = json.loads(
                (src / f"{stem}.answers.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            sessions[stem] = {"session_id": stem, "status": "rejected",
                              "reason": f"unreadable: {exc}",
                              "session_sha256": None, "problems": [str(exc)]}
            continue
        sessions[stem] = (sess, events_doc, answers_doc)
    seen: set = set()
    observations = []
    for stem in sorted(sessions):
        item = sessions[stem]
        if isinstance(item, dict):
            observations.append(item)
            continue
        sess, events_doc, answers_doc = item
        observations.append(import_session(sess, events_doc, answers_doc,
                                           seen))
    for obs in observations:
        obs["output_sha256"] = sha(canonical(
            {k: v for k, v in obs.items() if k != "output_sha256"}))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "agentos.s1-013.import-manifest/v1",
        "source": str(src),
        "sessions": len(observations),
        "ok": sum(1 for o in observations if o["status"] == "ok"),
        "rejected": sum(1 for o in observations
                        if o["status"] == "rejected"),
        "quarantined": sum(1 for o in observations
                           if o["status"] == "quarantined"),
    }
    (out_dir / "observations.json").write_text(
        json.dumps({"schema": "agentos.s1-013.observations/v1",
                    "observations": observations}, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    (out_dir / "import-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
        newline="\n")
    print(f"sessions={manifest['sessions']} ok={manifest['ok']} "
          f"rejected={manifest['rejected']} "
          f"quarantined={manifest['quarantined']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
