"""Deterministic fixture builder for S1-014 (run before freeze; no network).

Writes: task-manifest.json, oracle/oracle.json, prototype/browser-contract.json,
assignment-table.json, synthetic/synthetic-manifest.json and
synthetic/sessions/*.json (technical replay envelopes; never human data).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as c  # noqa: E402

T = c.TICKET


def _hex(seed: str, n: int = 16) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:n]


def synthetic_envelope(frozen: dict, seed: str, executor: str, scenario: str) -> dict:
    """Technical replay envelope.  ``scenario`` selects importer paths:
    ok | timeout | withdrawn | missing_answer."""
    disputes = {d["dispute_id"]: d for d in frozen["disputes"]}
    assignment = next(a for a in frozen["assignments"] if a["seed"] == seed and a["executor"] == executor)
    oracle_free_answers = list(c.ANSWER_CHOICES)
    events: list[dict] = []
    t = 0
    seq = 0

    def ev(kind: str, **extra: object) -> None:
        nonlocal seq, t
        seq += 1
        t += 250
        events.append(dict(seq=seq, t_ms=t, type=kind, **extra))

    ev("consent_given")
    ev("practice_start")
    ev("practice_end")
    trials = []
    lifecycle = "complete"
    for i, spec in enumerate(assignment["trials"]):
        did, var = spec["dispute_id"], spec["variant"]
        d = disputes[did]
        if scenario == "withdrawn" and i == 3:
            ev("withdraw")
            lifecycle = "withdrawn"
            trials.append({"position": spec["position"], "dispute_id": did, "variant": var, "presented_t_ms": None,
                           "submitted_t_ms": None, "outcome": "withdrawn", "answer": "__MISSING__", "provenance_recall": [],
                           "challenge_choice": "__MISSING__", "overload": "not_reported", "disclosure_actions": 0,
                           "keyboard_steps": 0, "pointer_used": False})
            continue
        if lifecycle == "withdrawn":
            trials.append({"position": spec["position"], "dispute_id": did, "variant": var, "presented_t_ms": None,
                           "submitted_t_ms": None, "outcome": "withdrawn", "answer": "__MISSING__", "provenance_recall": [],
                           "challenge_choice": "__MISSING__", "overload": "not_reported", "disclosure_actions": 0,
                           "keyboard_steps": 0, "pointer_used": False})
            continue
        ev("task_presented", dispute_id=did, variant=var)
        presented = t
        ev("disclosure_opened", dispute_id=did, variant=var, detail="provenance_detail")
        if var == "GRAPH":
            ev("node_focus", dispute_id=did, variant=var, detail=d["focal_claim"]["claim_id"])
        # deterministic, oracle-free answer pattern (the builder must not see the oracle)
        answer = oracle_free_answers[(i + int(_hex(seed + executor, 2), 16)) % 4]
        recall = [d["sources"][0]["source_id"]]
        if scenario == "timeout" and i == 2:
            ev("task_timeout", dispute_id=did, variant=var)
            trials.append({"position": spec["position"], "dispute_id": did, "variant": var, "presented_t_ms": presented,
                           "submitted_t_ms": t, "outcome": "timeout", "answer": "__MISSING__", "provenance_recall": [],
                           "challenge_choice": "__MISSING__", "overload": "not_reported", "disclosure_actions": 1,
                           "keyboard_steps": 4, "pointer_used": False})
            continue
        missing = scenario == "missing_answer" and i == 5
        if not missing:
            ev("answer_selected", dispute_id=did, variant=var, detail=answer)
            ev("provenance_marked", dispute_id=did, variant=var, detail="+".join(recall))
            ev("challenge_marked", dispute_id=did, variant=var, detail="challenge_seen")
            ev("overload_reported", dispute_id=did, variant=var, detail="medium")
        ev("task_submitted", dispute_id=did, variant=var)
        trials.append({"position": spec["position"], "dispute_id": did, "variant": var, "presented_t_ms": presented,
                       "submitted_t_ms": t, "outcome": "submitted",
                       "answer": "__MISSING__" if missing else answer,
                       "provenance_recall": [] if missing else recall,
                       "challenge_choice": "__MISSING__" if missing else "challenge_seen",
                       "overload": "not_reported" if missing else "medium",
                       "disclosure_actions": 1, "keyboard_steps": 9 + i, "pointer_used": False})
    if lifecycle == "complete":
        ev("session_complete")
    body = {
        "envelope_schema": c.ENVELOPE_SCHEMA, "contract_schema": c.CONTRACT_SCHEMA,
        "contract_version": c.CONTRACT_VERSION, "contract_sha256": frozen["contract_sha256"],
        "banner": c.BANNER,
        "session": {"session_id": "SES-" + _hex(f"ses|{seed}|{executor}|{scenario}"),
                    "participant_id": "SYN-" + _hex(f"syn|{seed}|{executor}|{scenario}"),
                    "role": "synthetic_technical_replay", "seed": seed, "executor": executor,
                    "assignment_sha256": assignment["assignment_sha256"],
                    "consent": {"given": True, "form_version": "S1-014-synthetic-v1", "t_ms": 0},
                    "accessibility_mode": "keyboard_only", "lifecycle": lifecycle},
        "trials": trials, "events": events,
    }
    body["payload_sha256"] = c.digest(body)
    return body


def build() -> dict:
    disputes, oracle = c.build_corpus()
    manifest = {"schema": "agentos.s1-014.task-manifest/v1", "ticket": c.TICKET_ID,
                "contract_schema": c.CONTRACT_SCHEMA, "contract_version": c.CONTRACT_VERSION,
                "variants": list(c.VARIANTS), "disclosure_rule": c.DISCLOSURE_RULE,
                "strata": {s: [d["dispute_id"] for d in disputes if d["complexity_stratum"] == s] for s in c.STRATA},
                "coverage": {
                    "direct_claim_vs_one_challenge": disputes[0]["dispute_id"],
                    "multiple_supports_one_group": disputes[1]["dispute_id"],
                    "independent_corroboration": disputes[2]["dispute_id"],
                    "strong_winner_visible_challenge": disputes[3]["dispute_id"],
                    "rejected_revoked_unknown_state": disputes[4]["dispute_id"],
                    "publisher_not_origin": disputes[5]["dispute_id"],
                    "near_miss_many_nodes": disputes[6]["dispute_id"],
                    "small_card_complex_logic": disputes[7]["dispute_id"]},
                "disputes": disputes}
    c.dump(T / "task-manifest.json", manifest)
    c.dump(T / "oracle" / "oracle.json", {"schema": "agentos.s1-014.oracle/v1", "ticket": c.TICKET_ID,
                                           "browser_visible": False, "oracle": oracle,
                                           "corpus_sha256": c.digest(disputes)})
    frozen = c.browser_contract(disputes)
    c.dump(T / "prototype" / "browser-contract.json", frozen)
    c.dump(T / "assignment-table.json", {"schema": "agentos.s1-014.assignment-table/v1",
                                          "seeds": list(c.SEEDS), "executors": list(c.EXECUTORS),
                                          "rule": "alternating CARD/GRAPH, first variant by seed byte, 8 disputes without repetition",
                                          "assignments": frozen["assignments"]})
    sessions_dir = T / "synthetic" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    for old in sessions_dir.glob("*.json"):
        old.unlink()
    entries = []
    plan = [("seed-0001", "EXEC-RUN-A", "ok"), ("seed-0002", "EXEC-RUN-A", "timeout"),
            ("seed-0003", "EXEC-RUN-A", "withdrawn"), ("seed-0001", "EXEC-RUN-B", "missing_answer"),
            ("seed-0002", "EXEC-RUN-B", "ok")]
    for seed, executor, scenario in plan:
        env = synthetic_envelope(frozen, seed, executor, scenario)
        name = f"{scenario}-{seed}-{executor}.json"
        c.dump(sessions_dir / name, env)
        entries.append({"file": name, "scenario": scenario, "seed": seed, "executor": executor,
                        "sha256": c.sha_file(sessions_dir / name), "human": False})
    c.dump(T / "synthetic" / "synthetic-manifest.json",
           {"schema": "agentos.s1-014.synthetic-manifest/v1", "purpose": "technical replay of importer/evaluator paths",
            "human_study_n": 0, "sessions": entries})
    return frozen


if __name__ == "__main__":
    f = build()
    print("browser contract", f["contract_sha256"])
