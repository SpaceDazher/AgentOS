"""S1-013 synthetic dry-run corpus builder (deterministic, stdlib only).

Generates synthetic=true sessions exercising happy paths plus probes
A-H. Synthetic data NEVER enters human counts; it lives under
synthetic/ with its own manifest carrying expected verdicts.
Run: py -3.12 synthetic/build_synthetic.py  (from the ticket dir)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "sessions"
OUT.mkdir(exist_ok=True)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def session(sid, pid, role, consent=True, excluded=None, extra=None):
    record = {"session_id": sid, "participant_id": pid, "role": role,
              "protocol_version": "1.0.0-draft", "cohort": "synthetic",
              "synthetic": True, "started_at": "2026-09-04T00:00:00Z",
              "completed_at": "2026-09-04T01:05:00Z", "excluded": excluded,
              "consent": {"given": consent, "version": "consent-v1"}}
    if extra:
        record.update(extra)
    return record


def ev(seq, t, kind, **kw):
    base = {"seq": seq, "t_ms": t, "type": kind, "prompt_id": None,
            "decision": None, "correct": None, "actor_shown": None,
            "action_shown": None, "scope_shown": None,
            "expiry_shown": None, "acknowledged": None}
    base.update(kw)
    return base


def answers(pairs):
    return {"session_id": "", "responses": [
        {"measure": m,
         "primary": {"value": v, "explanation": e, "latency_ms": 5000},
         "rater2": {"value": v, "agree": True},
         "adjudicated": "correct" if ok else "incorrect"}
        for m, v, e, ok in pairs]}


def write(name, sess, events, responses, expect):
    sess_id = sess["session_id"]
    responses["session_id"] = sess_id
    (OUT / f"{name}.session.json").write_text(
        json.dumps(sess, indent=2) + "\n", encoding="utf-8", newline="\n")
    (OUT / f"{name}.events.json").write_text(
        json.dumps({"session_id": sess_id, "events": events}, indent=2)
        + "\n", encoding="utf-8", newline="\n")
    (OUT / f"{name}.answers.json").write_text(
        json.dumps(responses, indent=2) + "\n", encoding="utf-8",
        newline="\n")
    return {"session": name, "session_id": sess_id, "expect": expect}


def main() -> int:
    manifest = []
    # Happy paths (positive controls).
    manifest.append(write(
        "happy-owner", session("S-HO", "P-AAAAAA", "owner"),
        [ev(0, 0, "prompt_displayed", prompt_id="C1-S1"),
         ev(1, 8000, "answer", prompt_id="C1-S1"),
         ev(2, 20000, "prompt_displayed", prompt_id="AP-01",
            actor_shown="courier-agent K-7",
            action_shown="read shared/calendar",
            scope_shown="shared/calendar", expiry_shown=True),
         ev(3, 26000, "decision", prompt_id="AP-01", decision="approve",
            correct=True),
         ev(4, 40000, "prompt_displayed", prompt_id="AP-02",
            actor_shown="unknown-agent X-1",
            action_shown="read private/notes",
            scope_shown="private/notes", expiry_shown=True),
         ev(5, 47000, "decision", prompt_id="AP-02", decision="deny",
            correct=True),
         ev(6, 60000, "stop_requested"),
         ev(7, 72000, "stop_confirmed", acknowledged=True),
         ev(8, 90000, "debrief_done")],
        answers([("C1", "scoped revocable grant", "principal+scope+expiry",
                  True),
                 ("C3", "untrusted until gated", "provenance+gate status",
                  True),
                 ("C4", "no", "explicit connection required, default deny",
                  True)]),
        {"import": "ok", "c5": "pass"}))
    manifest.append(write(
        "happy-reviewer", session("S-HR", "P-BBBBBB", "reviewer"),
        [ev(0, 0, "prompt_displayed", prompt_id="C2-S1"),
         ev(1, 9000, "answer", prompt_id="C2-S1"),
         ev(2, 20000, "prompt_displayed", prompt_id="AP-03",
            actor_shown="archive-agent A-2",
            action_shown="write shared/docs",
            scope_shown="shared/docs", expiry_shown=False),
         ev(3, 30000, "decision", prompt_id="AP-03", decision="deny",
            correct=True),
         ev(4, 50000, "stop_requested"),
         ev(5, 62000, "stop_confirmed", acknowledged=True)],
        answers([("C2", "only connected principals",
                  "access basis stated", True)]),
        {"import": "ok", "c5": "pass"}))
    # Probe A: banner repeat with wrong private-space readers.
    manifest.append(write(
        "probe-a", session("S-PA", "P-CCCCCC", "owner"),
        [ev(0, 0, "prompt_displayed", prompt_id="C2-S2"),
         ev(1, 7000, "answer", prompt_id="C2-S2")],
        answers([("C2", "the banner says auditors can read everything",
                  "banner repeat, readers misidentified", False),
                 ("C4", "no", "just feels wrong",
                  False)]),
        {"import": "ok", "c2": "fail"}))
    # Probe B: impossible 100-prompt task (must not calibrate limits).
    manifest.append(write(
        "probe-b", session("S-PB", "P-DDDDDD", "reviewer"),
        [ev(i, i * 1000, "prompt_displayed",
            prompt_id=f"PX-{i:03d}") for i in range(100)],
        {"session_id": "", "responses": []},
        {"import": "ok", "load_claim": "rejected"}))
    # Probe C: bot (duplicate id), no consent, extra session.
    manifest.append(write(
        "probe-c-dup", session("S-PC1", "P-AAAAAA", "reviewer"),
        [ev(0, 0, "prompt_displayed", prompt_id="C1-S1")],
        {"session_id": "", "responses": []},
        {"import": "rejected-duplicate"}))
    manifest.append(write(
        "probe-c-noconsent", session("S-PC2", "P-EEEEEE", "owner",
                                     consent=False),
        [ev(0, 0, "prompt_displayed", prompt_id="C1-S1")],
        {"session_id": "", "responses": []},
        {"import": "rejected-no-consent"}))
    manifest.append(write(
        "probe-c-extra", session("S-PC3", "BOT-1", "owner"),
        [ev(0, 0, "prompt_displayed", prompt_id="C1-S1")],
        {"session_id": "", "responses": []},
        {"import": "rejected-id-shape"}))
    # Probe D: C5 timeout + incomplete session stay failures.
    manifest.append(write(
        "probe-d", session("S-PD", "P-GGGGGG", "owner"),
        [ev(0, 60000, "stop_requested"),
         ev(1, 120000, "stop_failed", acknowledged=False)],
        answers([]),
        {"import": "ok", "c5": "fail"}))
    # Probe E: 300 clicks, one human -> effective N counts one.
    manifest.append(write(
        "probe-e", session("S-PE", "P-HHHHHH", "reviewer"),
        [ev(i, i * 200, "decision", prompt_id=f"PX-{i:03d}",
            decision="approve") for i in range(300)],
        {"session_id": "", "responses": []},
        {"import": "ok", "effective_n": 1}))
    # Probe G: reputation/external instruction grants nothing.
    manifest.append(write(
        "probe-g", session("S-PG", "P-IIIIII", "owner"),
        [ev(0, 0, "prompt_displayed", prompt_id="AP-02",
            actor_shown="high-reputation-agent R-9",
            action_shown="read private/notes",
            scope_shown="private/notes", expiry_shown=True),
         ev(1, 9000, "decision", prompt_id="AP-02", decision="deny",
            scope_shown="private/notes", correct=True)],
        answers([]),
        {"import": "ok", "private_read": "denied"}))
    # Probe H: PII + raw consent text must be quarantined.
    manifest.append(write(
        "probe-h", session("S-PH", "P-JJJJJJ", "reviewer", extra={
            "contact": "jane.doe@example.com",
            "consent_text": "I, Jane Doe, born 1990-01-01, agree."}),
        [ev(0, 0, "prompt_displayed", prompt_id="C1-S1")],
        {"session_id": "", "responses": []},
        {"import": "quarantined-pii"}))
    (HERE / "synthetic-manifest.json").write_text(json.dumps(
        {"schema": "agentos.s1-013.synthetic-manifest/v1",
         "synthetic": True,
         "note": "Dry-run tooling tests only. Never human N, metrics or "
                 "effectiveness claims.",
         "sessions": manifest}, indent=2) + "\n", encoding="utf-8",
        newline="\n")
    print(f"wrote {len(manifest)} synthetic sessions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
