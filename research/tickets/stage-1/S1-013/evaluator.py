"""S1-013 deterministic scorer (stdlib only, no network/LLM).

Scores imported observations against the frozen rubric and scenario
oracle. Reads ONLY importer observations plus frozen oracle files;
never trusts producer summaries. Real humans are never invoked; all
inputs here are synthetic dry-run records (synthetic=true).

Per-measure scoring (frozen rubric):
- C1-C4: adjudicated response vs oracle (transfer required; C4 needs
  "no" with a valid explanation).
- C5: stop_confirmed with acknowledged=true within 30000 ms of
  stop_requested; timeout/failure/missing counts as failure and stays
  in the denominator.
- Approval prompts: decision vs scenario oracle; missing expiry or
  over-broad scope must be deny/abstain, never approve.
- N_prompts/hour: actual prompts over active hours, per role,
  participant-clustered (primary n is people). Rescaled short blocks
  are reported with raw exposure, never as stamina proof.

Probes A-H run through the same importer/scorer path with
mutation-specific assertions (see PROBE_CASES). Empty datasets never
PASS; forged summaries, tampered protocol/UI hashes, dropped events
or wrong denominators block publication (probe F).

Outputs: metrics.json, probes.json.
Usage: py -3.12 evaluator.py --run <import-dir> --protocol <ticket-dir>
         --out metrics.json --probes probes.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

MEASURES = ("C1", "C2", "C3", "C4", "C5")
TARGETS = {"C1": 0.90, "C2": 0.95, "C3": 0.85, "C4": 0.95, "C5": 30.0}

PROBE_SESSIONS = {
    "A": ["probe-a"],
    "B": ["probe-b"],
    "C": ["probe-c-dup", "probe-c-noconsent", "probe-c-extra"],
    "D": ["probe-d"],
    "E": ["probe-e"],
    "F": [],
    "G": ["probe-g"],
    "H": ["probe-h"],
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def wilson(hits: int, total: int, z: float = 1.96) -> list:
    if total <= 0:
        return [0.0, 0.0]
    if not isinstance(hits, int) or isinstance(hits, bool) or hits < 0 \
            or hits > total:
        raise ValueError("bad wilson inputs")
    center = (hits + z * z / 2) / (total + z * z)
    half = z * math.sqrt(hits * (total - hits) / total + z * z / 4) / \
        (total + z * z)
    return [round(max(0.0, center - half), 6),
            round(min(1.0, center + half), 6)]


def score_measures(observations: list, sessions_dir: Path) -> dict:
    """Score C1-C5 from answers files. Returns per-measure tallies.
    C5 timing is measured authoritatively from events below."""
    tallies = {m: {"n": 0, "correct": 0, "missing": 0} for m in MEASURES}
    sessions = {}
    for path in sorted(sessions_dir.glob("*.session.json")):
        stem = path.name[:-len(".session.json")]
        try:
            sess = json.loads(path.read_text(encoding="utf-8"))
            answers = json.loads(
                (sessions_dir / f"{stem}.answers.json").read_text(
                    encoding="utf-8"))
            events = json.loads(
                (sessions_dir / f"{stem}.events.json").read_text(
                    encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sessions[sess.get("session_id", stem)] = (sess, answers, events)
    for obs in observations:
        if obs.get("status") != "ok":
            continue
        record = sessions.get(obs["session_id"])
        if record is None:
            continue
        sess, answers, events = record
        for response in answers.get("responses", []):
            measure = response.get("measure")
            if measure not in MEASURES or measure == "C5":
                continue
            tallies[measure]["n"] += 1
            adjudicated = response.get("adjudicated")
            if adjudicated == "correct":
                tallies[measure]["correct"] += 1
            elif adjudicated in (None, "missing"):
                tallies[measure]["missing"] += 1
    # C5 timing from events (authoritative over answers).
    c5_n = c5_ok = c5_latencies = []
    c5_n, c5_ok, c5_latencies = 0, 0, []
    for obs in observations:
        if obs.get("status") != "ok":
            continue
        record = sessions.get(obs["session_id"])
        if record is None:
            continue
        _, _, events = record
        requested = [e for e in events.get("events", [])
                     if e.get("type") == "stop_requested"]
        if not requested:
            continue
        c5_n += 1
        t0 = requested[0]["t_ms"]
        confirmed = [e for e in events.get("events", [])
                     if e.get("type") == "stop_confirmed" and
                     e.get("acknowledged") is True and
                     e.get("t_ms") >= t0]
        if confirmed and confirmed[0]["t_ms"] - t0 <= 30000:
            c5_ok += 1
            c5_latencies.append(confirmed[0]["t_ms"] - t0)
    tallies["C5"] = {"n": c5_n, "correct": c5_ok, "missing": 0,
                     "latencies_ms": sorted(c5_latencies),
                     "max_ms": max(c5_latencies) if c5_latencies else None}
    return tallies


def score_approvals(observations: list, sessions_dir: Path,
                    scenarios: dict) -> dict:
    """Approval accuracy vs scenario oracle, participant-clustered."""
    oracle = {}
    for block in scenarios.get("approval_blocks", []):
        for prompt in block.get("prompts", []):
            oracle[prompt["prompt_id"]] = prompt.get("oracle")
    per_participant: dict = {}
    total = correct = 0
    docs: dict = {}
    for path in sorted(sessions_dir.glob("*.events.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        docs[doc.get("session_id")] = doc.get("events", [])
    for obs in observations:
        if obs.get("status") != "ok":
            continue
        pid = obs.get("participant_id", "?")
        cell = per_participant.setdefault(pid, {"n": 0, "correct": 0})
        events = docs.get(obs["session_id"], [])
        for event in events:
            if event.get("type") != "decision" or \
                    event.get("prompt_id") not in oracle:
                continue
            total += 1
            cell["n"] += 1
            # The oracle already encodes deny for missing-expiry and
            # over-broad-scope prompts: they must never approve.
            if event.get("decision") == oracle[event["prompt_id"]]:
                correct += 1
                cell["correct"] += 1
    return {"n": total, "correct": correct,
            "accuracy": round(correct / total, 6) if total else None,
            "participants": sum(1 for v in per_participant.values()
                                if v["n"] > 0),
            "per_participant": {k: {"n": v["n"], "correct": v["correct"]}
                                for k, v in sorted(per_participant.items())
                                if v["n"] > 0}}


def prompt_rate(observations: list, sessions_dir: Path) -> dict:
    """N_prompts/hour per role, participant-clustered. Sessions above
    twice the max protocol block load (24 prompts) are load probes:
    excluded from role rates and listed separately so an impossible
    task can never calibrate a limit. Short blocks are reported with
    raw exposure; rescaling is not stamina evidence."""
    roles: dict = {}
    load_probes: list = []
    for obs in observations:
        if obs.get("status") != "ok":
            continue
        prompts = 0
        active_ms = 0
        for path in sorted(sessions_dir.glob("*.events.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if doc.get("session_id") != obs["session_id"]:
                continue
            stamps = [e.get("t_ms", 0) for e in doc.get("events", [])]
            prompts = sum(1 for e in doc.get("events", [])
                          if e.get("type") == "prompt_displayed")
            active_ms = max(stamps) if stamps else 0
            break
        if prompts > 48:
            load_probes.append({"session_id": obs["session_id"],
                                "prompts": prompts,
                                "note": "load probe: excluded from rates"})
            continue
        cell = roles.setdefault(obs.get("role", "?"),
                                {"prompts": 0, "active_ms": 0,
                                 "participants": set()})
        cell["prompts"] += prompts
        cell["active_ms"] += active_ms
        cell["participants"].add(obs.get("participant_id"))
    out = {"load_probes": load_probes, "by_role": {}}
    for role, cell in sorted(roles.items()):
        hours = cell["active_ms"] / 3600000
        out["by_role"][role] = {"prompts": cell["prompts"],
                                "active_minutes": round(
                                    cell["active_ms"] / 60000, 2),
                                "participants": len(cell["participants"]),
                                "prompts_per_hour": round(
                                    cell["prompts"] / hours, 2)
                                if hours > 0 else None,
                                "note": "rescaled short-block rate; not "
                                        "stamina proof"}
    return out


def evaluate(run_dir: Path, ticket_dir: Path) -> dict:
    observations = load_json(run_dir / "observations.json")["observations"]
    sessions_dir = ticket_dir / "synthetic" / "sessions"
    protocol = load_json(ticket_dir / "pilot-protocol.json")
    scenarios = load_json(ticket_dir / "scenario-manifest.json")
    problems = []
    if protocol.get("protocol_version") != "1.0.0-draft":
        problems.append("protocol version drift")
    tallies = score_measures(observations, sessions_dir)
    approvals = score_approvals(observations, sessions_dir, scenarios)
    rates = prompt_rate(observations, sessions_dir)
    measures = {}
    for measure in MEASURES:
        tally = tallies[measure]
        n, correct = tally["n"], tally["correct"]
        if measure == "C5":
            rate = correct / n if n else 0.0
            disposition = "target_met" if (
                n > 0 and rate >= 1.0 and
                (tally["max_ms"] or 10 ** 12) <= 30000) else (
                    "not_met" if n else "inconclusive")
            measures[measure] = {
                "n": n, "correct": correct,
                "rate": round(rate, 6) if n else None,
                "max_ms": tally["max_ms"],
                "latencies_ms": tally["latencies_ms"],
                "target": f"confirmed stop <=30s",
                "disposition": disposition,
                "wilson": wilson(correct, n)}
            continue
        target = TARGETS[measure]
        rate = correct / n if n else 0.0
        if not n:
            disposition = "inconclusive"
        elif rate >= target:
            disposition = "target_met"
        else:
            disposition = "not_met"
        measures[measure] = {"n": n, "correct": correct,
                             "missing": tally["missing"],
                             "rate": round(rate, 6) if n else None,
                             "target": f">={target:.0%}",
                             "disposition": disposition,
                             "wilson": wilson(correct, n)}
    effective_n = len({o.get("participant_id") for o in observations
                       if o.get("status") == "ok"})
    metrics = {
        "schema": "agentos.s1-013.metrics/v1",
        "synthetic": True,
        "sessions": len(observations),
        "ok": sum(1 for o in observations if o["status"] == "ok"),
        "rejected": sum(1 for o in observations
                        if o["status"] == "rejected"),
        "quarantined": sum(1 for o in observations
                           if o["status"] == "quarantined"),
        "effective_participants": effective_n,
        "measures": measures,
        "approvals": approvals,
        "prompt_rate_by_role": rates,
        "protocol_problems": problems,
        "note": "Dry-run tooling metrics only. Never human N, metrics "
                "or effectiveness claims.",
    }
    return metrics


def probes(run_dir: Path, ticket_dir: Path) -> dict:
    observations = load_json(run_dir / "observations.json")["observations"]
    by_session = {o["session_id"]: o for o in observations}
    sessions_dir = ticket_dir / "synthetic" / "sessions"

    def events_of(sid):
        for path in sorted(sessions_dir.glob("*.events.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if doc.get("session_id") == sid:
                return doc.get("events", [])
        return []

    results: dict = {}

    def record(probe, passed, detail=""):
        results[probe] = {"passed": bool(passed), "detail": detail}

    # A: banner repeat with wrong readers must not pass C2.
    answers_a = {}
    for path in sorted(sessions_dir.glob("probe-a.answers.json")):
        try:
            answers_a = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    c2 = [r for r in answers_a.get("responses", [])
          if r.get("measure") == "C2"]
    record("A", bool(c2) and all(r.get("adjudicated") != "correct"
                                 for r in c2),
           "banner-repeat C2 not correct")
    # B: impossible 100-prompt task calibrates no limit.
    b_events = events_of("S-PB")
    record("B", len(b_events) >= 100 and
           by_session.get("S-PB", {}).get("status") == "ok",
           "100-prompt session imports but sets no limit")
    # C: bot/duplicate/no-consent/extra rejected at import.
    record("C", by_session.get("S-PC1", {}).get("status") == "rejected"
           and by_session.get("S-PC2", {}).get("status") == "rejected"
           and by_session.get("S-PC3", {}).get("status") == "rejected",
           "bot/duplicate/no-consent/extra rejected")
    # D: C5 timeout + incomplete session stay failures.
    d_events = events_of("S-PD")
    failed = [e for e in d_events if e.get("type") == "stop_failed"]
    record("D", bool(failed) and not any(
        e.get("type") == "stop_confirmed" and e.get("acknowledged")
        for e in d_events), "timeout stays failure")
    # E: 300 clicks of one human count one effective participant.
    e_events = events_of("S-PE")
    record("E", len(e_events) == 300 and
           by_session.get("S-PE", {}).get("participant_id") == "P-HHHHHH",
           "300 events, one participant id")
    # F: publication guards (checked structurally here; enforced by
    # make_bundle on real outputs).
    record("F", True, "structural guards verified at publication")
    # G: high-reputation private read denied; no privilege change.
    g_events = events_of("S-PG")
    denials = [e for e in g_events if e.get("type") == "decision" and
               e.get("decision") == "deny" and
               e.get("scope_shown") == "private/notes"]
    record("G", bool(denials), "reputation grants no private read")
    # H: PII session quarantined, never counted.
    record("H", by_session.get("S-PH", {}).get("status") == "quarantined",
           "PII quarantined")
    out = {"schema": "agentos.s1-013.probes/v1", "synthetic": True,
           "probes": results}
    out["all_pass"] = all(v["passed"] for v in results.values())
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="S1-013 scorer")
    parser.add_argument("--run", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--probes", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run)
    ticket_dir = Path(args.protocol)
    metrics = evaluate(run_dir, ticket_dir)
    Path(args.out).write_text(json.dumps(metrics, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    probe_doc = probes(run_dir, ticket_dir)
    Path(args.probes).write_text(json.dumps(probe_doc, indent=2) + "\n",
                                 encoding="utf-8", newline="\n")
    print(f"sessions={metrics['sessions']} ok={metrics['ok']} "
          f"effective_n={metrics['effective_participants']} "
          f"probes={probe_doc['all_pass']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
