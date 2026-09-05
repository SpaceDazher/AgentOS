"""S1-014 dependency gate over immutable Git refs of S1-011, S1-012 and S1-013.

Reuses the byte-level verifier from S1-013 (record/pack/chain bindings) and
adds: pinned expected commits, exact goal/campaign/evaluation/chain bindings,
S1-013 operator-decision semantics (human_n=0, mass pilot cancelled, human
effectiveness NOT_MEASURED) and three independent outputs:
phase_a_dependencies_proven, operator_review_dependencies_proven and
population_human_claims_proven (always false in this ticket).
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

TICKET = Path(__file__).resolve().parent
REPO = TICKET.parents[3]
OUT = TICKET / "dependency-gate.json"
S1013_GATE = REPO / "research/tickets/stage-1/S1-013/dependency_gate.py"

EXPECTED = {
    "S1-011": {"branch": "codex/s1-011-knowledge-gate",
               "record": "research/tickets/stage-1/S1-011/evaluation-record.json",
               "commit": "0e794c4e7d74888df99a1818e50cd6a88d83e815",
               "goal_id": "goal_00THNQYSRE841R1201M1MSPWPR", "campaign_id": "rcamp_6P8Q5BC9SE6NXD8501M1MSPWPR",
               "evaluation_id": "reval_94X52VCQDV30J84Z01M1MSPWRD",
               "artifact_chain_hash": "027c456355d30f760dc4fe077c29c619a91db1fd7d26f31f2a6cb9f18210b313"},
    "S1-012": {"branch": "codex/s1-012-evidence-independence",
               "record": "research/tickets/stage-1/S1-012/evaluation-record.json",
               "commit": "14564354167568b3cdea47883ac1dbd126e4ab19",
               "goal_id": "goal_8VBM41JB75VDTSP201M1NNPB3S", "campaign_id": "rcamp_29WZZQ406M19WJS801M1NNPB3S",
               "evaluation_id": "reval_EPR9JR5JWBHXST6301M1NNPB5P",
               "artifact_chain_hash": "818a25e67a1865d425eebcb754376f06d143aaac9fa7f07aa704804311ffb21c"},
    "S1-013": {"branch": "codex/s1-013-comprehension-pilot",
               "record": "research/tickets/stage-1/S1-013/evaluation-record.json",
               "commit": "091ade232ba7f3dd8a0063285977c1705c571d62",
               "goal_id": "goal_PZ0WP37PRBM05XH101M1QB60YD", "campaign_id": "rcamp_YX958H0WJ4YDK4AH01M1QB60YD",
               "evaluation_id": "reval_P911RT2XC117Y74Y01M1QB612C",
               "artifact_chain_hash": "766172bb18bcf479ce672ebe5e881a083e89430003b697a12650abf11c943e34"},
}
S1013_DECISION = "research/tickets/stage-1/S1-013/operator-decision.json"


def _s1013():
    spec = importlib.util.spec_from_file_location("s1013_dependency_gate", S1013_GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_show = module.git_show
    branches = {exp["branch"] for exp in EXPECTED.values()}

    def portable_show(branch: str, rel: str) -> bytes:
        # Always read dependency bytes from the portable origin ref, never from
        # a local branch that a caller could recreate or advance.
        ref = f"refs/remotes/origin/{branch}" if branch in branches else branch
        return original_show(ref, rel)

    module.git_show = portable_show

    def check_tracked(branch: str, ticket: str, rec: dict, problems: list[str]) -> None:
        entries = rec.get("tracked_artifact_hashes") or rec.get("tracked_artifacts")
        if not isinstance(entries, dict) or not entries:
            problems.append("record has no tracked artifact hash map")
            return
        test_re = re.compile(rf"^tests/test_{ticket.lower().replace('-', '_')}_[a-z0-9_]+\.py$")
        for rel, expected in sorted(entries.items()):
            label = f"tracked artifact {rel}"
            if not module.contained(rel, ticket) and not test_re.fullmatch(rel):
                problems.append(f"{label} escapes ticket dir")
                continue
            if not isinstance(expected, str) or not module.HEX64.fullmatch(expected):
                problems.append(f"{label} has invalid hash")
                continue
            try:
                actual = module.sha(module.git_show(branch, rel))
            except RuntimeError as exc:
                problems.append(str(exc))
                continue
            if actual != expected:
                problems.append(f"{label} hash mismatch")

    module._check_tracked_artifacts = check_tracked
    return module


def _s1013_semantics(g, branch: str, problems: list[str]) -> dict:
    raw = g.git_show(branch, S1013_DECISION)
    decision = json.loads(raw.decode("utf-8"))
    facts = {
        "result_pass_with_limits": decision.get("target_status") == "PASS_WITH_LIMITS",
        "mass_pilot_cancelled": decision.get("full_human_pilot") == "cancelled_by_operator",
        "human_effectiveness_not_measured": (decision.get("interpretation") or {}).get("human_effectiveness") == "NOT_MEASURED",
        "raw_deleted_not_evidence": (decision.get("interpretation") or {}).get("raw_policy", "").endswith("deleted_after_aggregate"),
        "independent_grading_absent": (decision.get("interpretation") or {}).get("independent_grading") == "not_available_not_performed",
        "scope_solo_expert_review": decision.get("scope") == "solo_expert_review",
        "decision_sha256": g.sha(raw),
    }
    for key, value in facts.items():
        if value is False:
            problems.append(f"S1-013 semantics: {key} not satisfied")
    return facts


def run(rec_override: dict[str, Any] | None = None) -> dict:
    g = _s1013()
    results = []
    inherited: list[str] = []
    for ticket, exp in EXPECTED.items():
        dep = {"ticket": ticket, "branch": exp["branch"], "record": exp["record"]}
        override = (rec_override or {}).get(ticket)
        result = g.check(dep, rec_override=override)
        problems = list(result.get("problems", []))
        try:
            head = g.branch_head(exp["branch"])
            if head != exp["commit"]:
                problems.append(f"{ticket} origin ref {head} differs from pinned {exp['commit']}")
            record = g._authoritative_record(dep)
            for key in ("goal_id", "campaign_id", "evaluation_id", "artifact_chain_hash"):
                if record.get(key) != exp[key]:
                    problems.append(f"{ticket} record {key} differs from expected binding")
            if record.get("result") != "pass_with_limits":
                problems.append(f"{ticket} result is not pass_with_limits")
            for limit in record.get("limitations", []):
                inherited.append(f"{ticket}: {limit}")
            if ticket == "S1-013":
                result["s1_013_semantics"] = _s1013_semantics(g, exp["branch"], problems)
                inherited.append("S1-013: human_n=0; comprehension/fatigue/effectiveness NOT_MEASURED; raw observations deleted, not evidence")
        except (RuntimeError, ValueError, UnicodeDecodeError) as exc:
            problems.append(str(exc))
        result["problems"] = problems
        result["status"] = "PROVEN" if not problems else ("BLOCKED_DEPENDENCY" if any("origin" in p for p in problems) else "NOT_PROVEN")
        result["pinned_commit"] = exp["commit"]
        results.append(result)
    all_proven = all(r["status"] == "PROVEN" for r in results)
    gate = {
        "schema": "agentos.s1-014.dependency-gate/v1", "ticket": "S1-014",
        "dependencies": results,
        "phase_a_dependencies_proven": all_proven,
        "operator_review_dependencies_proven": all_proven,
        "population_human_claims_proven": False,
        "population_human_claims_reason": "S1-013 canonical record carries human_n=0; no dependency supplies population human evidence",
        "verdict_ceiling": "PASS_WITH_LIMITS",
        "inherited_limits": inherited,
        "status": "PROVEN" if all_proven else ("BLOCKED_DEPENDENCY" if any(r["status"] == "BLOCKED_DEPENDENCY" for r in results) else "NOT_PROVEN"),
        "note": "verified from tracked bytes of portable origin refs; same-host verification, not external audit",
    }
    return gate


if __name__ == "__main__":
    gate = run()
    OUT.write_text(json.dumps(gate, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(gate["status"], "phase_a", gate["phase_a_dependencies_proven"], "human", gate["population_human_claims_proven"])
    sys.exit(0 if gate["phase_a_dependencies_proven"] else 1)
