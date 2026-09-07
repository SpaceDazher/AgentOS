"""Build the deterministic, reviewable inputs for the S1-020 closure audit."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
BASE_COMMIT = "78a4218606212c4f65642fe8dbf9c6a808209cfb"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git_blob(path: str) -> bytes:
    proc = subprocess.run(
        ["git", "show", f"{BASE_COMMIT}:{path}"], cwd=ROOT,
        capture_output=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"missing pinned blob {path}: {proc.stderr.decode(errors='replace')}")
    return proc.stdout


def write(name: str, value: object) -> None:
    path = HERE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                               allow_nan=False) + "\n", encoding="utf-8", newline="\n")


PROBE_PATHS = {
    "S1-001": "research/tickets/stage-1/S1-001/bundle.json",
    "S1-002": "research/tickets/stage-1/S1-002/bundle.json",
    "S1-003": "research/tickets/stage-1/S1-003/probe-results.json",
    "S1-004": "research/tickets/stage-1/S1-004/results/simulation/manifest.json",
    "S1-005": "research/tickets/stage-1/S1-005/results/sensitivity-analysis.json",
    "S1-006": "research/tickets/stage-1/S1-006/results/sensitivity-analysis.json",
    "S1-007": "research/tickets/stage-1/S1-007/results/sensitivity-analysis.json",
    "S1-008": "research/tickets/stage-1/S1-008/evaluation-record.json",
    **{f"S1-{n:03d}": f"research/tickets/stage-1/S1-{n:03d}/results/probes.json"
       for n in range(9, 20)},
}


OPEN_ITEMS = [
    ("G-01", ["S1-013", "S1-014", "S1-015"]),
    ("G-02", ["S1-009"]), ("G-03", ["S1-002", "S1-006", "S1-019"]),
    ("G-04", ["S1-018"]), ("G-05", ["S1-001", "S1-012"]),
    ("G-06", ["S1-011"]), ("G-07", ["S1-010"]),
    ("G-08", ["S1-008"]), ("G-09", ["S1-013", "S1-014"]),
    ("G-10", ["S1-004"]),
    ("QA1", ["S1-005"]), ("QA2", ["S1-006"]), ("QA3", ["S1-007"]),
    ("QM1", ["S1-014"]), ("QM2", ["S1-013"]), ("QM3", ["S1-015"]),
    ("ONTOLOGY-Q1", ["S1-016"]), ("ONTOLOGY-Q2", ["S1-017"]),
    ("ONTOLOGY-Q3", ["S1-012"]),
    ("MODEL-LIMIT-1", ["S1-002", "S1-019", "PARK-03"]),
    ("MODEL-LIMIT-2", ["S1-012"]),
    ("MODEL-LIMIT-3", ["S1-011", "S1-012"]),
    ("MODEL-LIMIT-4", ["S1-003", "S1-004", "S1-020"]),
    ("MODEL-LIMIT-5", ["S1-001", "S1-012"]),
    ("NO-BENCHMARK", ["S1-002", "S1-006", "S1-008", "PARK-03"]),
    ("NO-USER-STUDY", ["S1-013", "S1-014", "S1-015"]),
    ("NO-LEGAL-QUALIFICATION", ["PARK-01"]),
    ("UNVERIFIED-SOURCE-TAIL", ["S1-001", "PARK-02"]),
    ("PROFILE-C-ROLLOUT", ["S1-018", "PARK-04"]),
    ("PRODUCTION-CERTIFICATION", ["PARK-03", "PARK-04"]),
]


def build() -> None:
    active = [f"S1-{n:03d}" for n in range(1, 21)]
    parked = [f"PARK-{n:02d}" for n in range(1, 5)]
    contract = {
        "schema": "agentos.s1-020.closure-contract/v1",
        "ticket": "S1-020", "base_commit": BASE_COMMIT,
        "active_ticket_ids": active, "dependency_ticket_ids": active[:-1],
        "parked_ids": parked,
        "allowed_prior_statuses": ["PASS", "PASS_WITH_LIMITS"],
        "required_pack_schema": "agentos.evidence-pack/v3",
        "required_common_gates": ["dependencies_proven", "all_prior_probes_pass",
                                  "chain_fresh", "latest_evaluation_valid", "wiki_ok",
                                  "auditor_distinct", "coverage_complete", "parked_preserved"],
        "research_pass_is_goal_accepted": False,
        "reopen_parked_items": False,
        "production_authority": False,
        "decision_inputs_exclude": ["wall_clock", "mtime", "generated_at", "retrieved_at"],
        "closure_status": "PASS_WITH_LIMITS",
        "limits": ["research closure only; no Goal ACCEPTED authority",
                   "no production certification or rollout authority",
                   "prior PASS_WITH_LIMITS findings remain binding",
                   "same-host process-separated audit; not an external audit firm"],
    }
    write("closure-contract.json", contract)

    s19_sources = json.loads((ROOT / "research/tickets/stage-1/S1-019/source-registry.json")
                             .read_text(encoding="utf-8"))["sources"]
    aliases = []
    for item in s19_sources:
        path = item["canonical_path"]
        raw = git_blob(path)
        aliases.append({**item, "sha256": sha(raw), "bytes": len(raw),
                        "verified_commit": BASE_COMMIT})
    ticket_sources = []
    for ticket in active[:-1]:
        path = f"research/tickets/stage-1/{ticket}/evaluation-record.json"
        raw = git_blob(path)
        ticket_sources.append({
            "id": f"DEP-{ticket}", "ticket_id": ticket,
            "canonical_uri": f"https://local.agentos.invalid/{path}",
            "canonical_path": path, "sha256": sha(raw), "bytes": len(raw),
            "verified_commit": BASE_COMMIT, "verification_status": "HASH_FROZEN_GIT_BLOB",
            "source_type": "canonical ticket evaluation record",
            "title": f"{ticket} canonical evaluation record",
        })
    write("source-registry.json", {
        "schema": "agentos.s1-020.source-registry/v1", "offline_evaluation": True,
        "source_alias_count": len(aliases), "prior_ticket_count": len(ticket_sources),
        "sources": aliases + ticket_sources,
    })

    write("probe-registry.json", {
        "schema": "agentos.s1-020.probe-registry/v1", "verified_commit": BASE_COMMIT,
        "entries": [{"ticket_id": ticket, "path": path,
                     "sha256": sha(git_blob(path)), "semantic_profile": ticket}
                    for ticket, path in PROBE_PATHS.items()],
    })

    dependency_map = {
        "S1-001": [], "S1-002": [], "S1-003": [],
        "S1-004": ["S1-002", "S1-003"], "S1-005": ["S1-002"],
        "S1-006": ["S1-002", "S1-005"], "S1-007": ["S1-003", "S1-005"],
        "S1-008": ["S1-002", "S1-004"], "S1-009": ["S1-001", "S1-005"],
        "S1-010": ["S1-001", "S1-009"],
        "S1-011": ["S1-001", "S1-003"],
        "S1-012": ["S1-001", "S1-003", "S1-011"],
        "S1-013": ["S1-011", "S1-012"], "S1-014": ["S1-011", "S1-013"],
        "S1-015": ["S1-013"], "S1-016": ["S1-003", "S1-007"],
        "S1-017": ["S1-004", "S1-016"],
        "S1-018": ["S1-007", "S1-008", "S1-009"],
        "S1-019": [f"S1-{n:03d}" for n in range(4, 19)],
        "S1-020": active[:-1],
    }
    write("coverage-matrix.json", {
        "schema": "agentos.s1-020.coverage-matrix/v1",
        "ticket_rows": [{"ticket_id": ticket, "dependencies": dependency_map[ticket],
                         "accounted": True} for ticket in active],
        "parked_rows": [{"parked_id": pid, "status": "PARKED", "reopened": False}
                        for pid in parked],
        "open_item_rows": [{"open_item_id": item, "ticket_mappings": mappings,
                            "accounted": True} for item, mappings in OPEN_ITEMS],
    })

    mutations = [
        ("chain_fresh", "set", False), ("latest_evaluation_valid", "set", False),
        ("auditor_equal", "special", True), ("probe_missing", "special", "S1-019"),
        ("dependency_missing", "special", "S1-009"),
        ("parked_reopened", "special", "PARK-03"),
        ("wiki_ok", "set", False), ("production_authority", "set", True),
        ("goal_acceptance_authority", "set", True),
        ("coverage_complete", "set", False),
        ("status_forgery", "special", "S1-010"),
        ("probe_missing", "special", "S1-001"),
        ("dependency_missing", "special", "S1-019"),
        ("parked_reopened", "special", "PARK-01"),
        ("auditor_empty", "special", True), ("limits_missing", "special", True),
        ("active_count", "special", True), ("parked_count", "special", True),
        ("dependency_not_proven", "special", "S1-004"),
        ("probe_false", "special", "S1-018"),
    ]
    cases, expected = [], {}
    for index in range(20):
        case_id = f"S1-020-G-{index + 1:02d}"
        cases.append({"case_id": case_id, "class": "gold", "mutation": None,
                      "probe_id": None})
        expected[case_id] = "PASS_WITH_LIMITS"
    for index in range(20):
        case_id = f"S1-020-N-{index + 1:02d}"
        cases.append({"case_id": case_id, "class": "near_miss",
                      "mutation": {"field": "generated_at", "op": "set",
                                   "value": f"metadata-{index:02d}"}, "probe_id": None})
        expected[case_id] = "PASS_WITH_LIMITS"
    for index, (field, op, value) in enumerate(mutations):
        case_id = f"S1-020-A-{index + 1:02d}"
        cases.append({"case_id": case_id, "class": "adversarial",
                      "mutation": {"field": field, "op": op, "value": value},
                      "probe_id": chr(65 + index)})
        expected[case_id] = "BLOCKED"
    write("cases.json", {"schema": "agentos.s1-020.cases/v1", "cases": cases})
    write("oracle.json", {"schema": "agentos.s1-020.oracle/v1", "expected": expected})
    write("rubric.json", {
        "schema": "agentos.s1-020.rubric/v1", "required_cases": 60,
        "hard_counters": ["dependency_failures", "probe_failures", "coverage_failures",
                          "parked_reopens", "authority_expansions", "oracle_mismatches",
                          "identity_failures", "freshness_failures"],
        "pass_rule": "all hard counters zero and all 60 cases match host-owned oracle",
        "result": "PASS_WITH_LIMITS when prior bounded limits remain; otherwise PASS",
    })


if __name__ == "__main__":
    build()
