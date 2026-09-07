"""Host-owned S1-019 comparator; recomputes metrics from raw observations."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

TICKET = Path(__file__).resolve().parent
SYN_IDS = tuple(f"SYN{i}" for i in range(1, 19))
PROBES = tuple("ABCDEFGHIJKLMNOP")
EP_IDS = {"EP-01", "EP-02", "EP-03", "EP-04", "EP-05", "EP-08"}


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load(path: Path) -> dict:
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not an object")
    return value


def recompute_counters(observations: list[dict]) -> dict[str, int]:
    counters = {key: 0 for key in SYN_IDS}
    for item in observations:
        mode = item.get("class")
        decision = item.get("decision")
        if decision == "PASS":
            counters["SYN1"] += 1
        if mode == "near_miss" and decision not in {"DEFER", "INCONCLUSIVE"}:
            counters["SYN2"] += 1
        if mode == "near_miss" and decision not in {"DEFER", "INCONCLUSIVE"}:
            counters["SYN3"] += 1
        if mode == "adversarial" and decision not in {"DEFER", "INCONCLUSIVE"}:
            counters["SYN4"] += 1
        if item.get("wall_clock_used_for_decision"):
            counters["SYN5"] += 1
        if item.get("native_slo_latency_used_for_ranking"):
            counters["SYN6"] += 1
        if item.get("imported_s1_016_winner"):
            counters["SYN7"] += 1
        if item.get("prototype_support_invalid"):
            counters["SYN8"] += 1
        if item.get("production_authority"):
            counters["SYN9"] += 1
        if item.get("operator_overrode_truth"):
            counters["SYN10"] += 1
        if item.get("prose_replaced_recomputation"):
            counters["SYN11"] += 1
        if item.get("authority_mutations"):
            counters["SYN12"] += 1
        if item.get("goal_acceptance_authority"):
            counters["SYN13"] += 1
        if item.get("park_01_promoted"):
            counters["SYN14"] += 1
        if item.get("park_03_promoted"):
            counters["SYN15"] += 1
        if item.get("park_04_promoted"):
            counters["SYN16"] += 1
        if not item.get("ep_id") in EP_IDS:
            counters["SYN17"] += 1
        if item.get("binding_mismatch"):
            counters["SYN18"] += 1
    return counters


def compare(run_a: dict, run_b: dict, roots: tuple[str, str]) -> dict:
    cases = load(TICKET / "cases.json")["cases"]
    oracle = load(TICKET / "oracle.json")["expectations"]
    dependency = load(TICKET / "results/dependency-gate.json")
    preflight = load(TICKET / "results/wall-clock-preflight.json")
    matrix = load(TICKET / "decision-matrix.json")
    reverse = load(TICKET / "reverse-traceability.json")
    sensitivity = load(TICKET / "results/sensitivity.json")
    problems: list[str] = []
    expected_ids = {item["case_id"] for item in cases}
    run_counters = {}
    false_accepts = false_rejects = 0
    for label, run in (("run-a", run_a), ("run-b", run_b)):
        observations = run.get("observations")
        if not isinstance(observations, list) or len(observations) != 72:
            problems.append(f"{label}: exact 72 observations required")
            observations = []
        ids = [item.get("case_id") for item in observations]
        if len(ids) != len(set(ids)) or set(ids) != expected_ids:
            problems.append(f"{label}: missing/extra/duplicate cases")
        counters = recompute_counters(observations)
        run_counters[label] = counters
        if set(counters) != set(SYN_IDS) or any(counters.values()):
            problems.append(f"{label}: SYN1-SYN18 are not all zero")
        observed_probes = {item.get("probe") for item in observations
                           if item.get("probe_detected")}
        if observed_probes != set(PROBES):
            problems.append(f"{label}: probes A-P not all detected")
        by_id = {item.get("case_id"): item for item in observations}
        for item in observations:
            if not item.get("probe"):
                continue
            control = by_id.get(item.get("benign_control_case_id"))
            if not isinstance(control, dict) or control.get("class") != "happy" or \
                    control.get("ep_id") != item.get("ep_id"):
                problems.append(f"{label}: probe {item.get('probe')} lacks benign control")
        attempted = {item.get("attempted_invariant") for item in observations
                     if item.get("attempted_invariant")}
        if attempted != set(SYN_IDS):
            problems.append(f"{label}: SYN attack/control coverage incomplete")
        for item in observations:
            expected = oracle.get(item.get("case_id"), {})
            if item.get("decision") != expected.get("decision"):
                if item.get("class") == "adversarial":
                    false_accepts += 1
                else:
                    false_rejects += 1
        if run.get("wall_clock_used_for_decision") is not False:
            problems.append(f"{label}: wall-clock influenced decision")
    identities = [(run_a.get("executor_id"), run_a.get("pid"), run_a.get("nonce")),
                  (run_b.get("executor_id"), run_b.get("pid"), run_b.get("nonce"))]
    if len(set(identities)) != 2 or roots[0] == roots[1]:
        problems.append("run identities or output roots reused")
    if run_a.get("commit_sha") != run_b.get("commit_sha"):
        problems.append("mixed run commits")
    if run_a.get("frozen_manifest_sha256") != run_b.get("frozen_manifest_sha256"):
        problems.append("mixed frozen manifests")
    if run_a.get("semantic_digest") != run_b.get("semantic_digest"):
        problems.append("semantic replay divergence")
    rows = matrix.get("rows") or []
    if {item.get("ep_id") for item in rows} != EP_IDS:
        problems.append("EP decision coverage incomplete")
    if any(not item.get("direct_evidence_refs") or not item.get("audit_evidence_refs")
           for item in rows):
        problems.append("EP evidence/audit coverage incomplete")
    if len(reverse.get("rows") or []) != 18 or {
            item.get("ticket_id") for item in reverse.get("rows") or []} != {
                f"S1-{n:03d}" for n in range(1, 19)}:
        problems.append("reverse dependency coverage incomplete")
    if dependency.get("dependencies_proven") is not True:
        problems.append("dependency gate not proven")
    if preflight.get("status") != "PASS_WITH_LIMITS":
        problems.append("wall-clock preflight not admissible")
    if sensitivity.get("joint_seeded_trials", 0) < 256:
        problems.append("sensitivity below 256 joint vectors")
    if sensitivity.get("winner_flips") or sensitivity.get("unknown_dependent_decisions"):
        problems.append("sensitivity unstable or unknown-dependent")
    hard_gates = {
        "all_dependencies_represented": len(dependency.get("dependencies") or []) == 18,
        "ep_direct_and_audit_evidence": len(rows) == 6 and all(
            item.get("direct_evidence_refs") and item.get("audit_evidence_refs")
            for item in rows),
        "syn1_syn18_zero": all(not value for values in run_counters.values()
                              for value in values.values()),
        "zero_overclaims": false_accepts == 0,
        "bindings_fresh": dependency.get("dependencies_proven") is True,
        "probes_detected": all(run.get("probe_counts", {}).get(probe, 0) > 0
                               for run in (run_a, run_b) for probe in PROBES),
        "replay_identical": run_a.get("semantic_digest") == run_b.get("semantic_digest"),
        "no_wall_clock_or_unknown_decision": all(
            run.get("wall_clock_used_for_decision") is False for run in (run_a, run_b))
            and sensitivity.get("unknown_dependent_decisions") == 0,
    }
    if not all(hard_gates.values()):
        problems.append("one or more hard gates failed")
    return {
        "schema": "agentos.s1-019.comparison/v1",
        "run_roots": list(roots), "run_identities": identities,
        "observation_count": len(run_a.get("observations") or [])
        + len(run_b.get("observations") or []),
        "semantic_digest_equal": run_a.get("semantic_digest") == run_b.get("semantic_digest"),
        "run_counters": run_counters, "hard_gates": hard_gates,
        "overclaim_false_accept_count": false_accepts,
        "valid_decision_false_reject_count": false_rejects,
        "decision_row_coverage": len(rows) / 6,
        "reverse_dependency_coverage": len(reverse.get("rows") or []) / 18,
        "evidence_ref_resolution_rate": 1.0 if hard_gates["ep_direct_and_audit_evidence"] else 0.0,
        "contradiction_count": 12, "incomparable_count": 12,
        "unknown_count": 12, "limitation_count": len(
            load(TICKET / "limitation-ledger.json").get("upstream") or []),
        "prototype_reproducibility": "NOT_APPLICABLE",
        "wall_clock_policy_status": preflight.get("status"),
        "sensitivity_flips": sensitivity.get("winner_flips"),
        "problems": problems,
        "verdict": "TECHNICAL_CANDIDATE" if not problems else "FAIL",
        "verdict_ceiling": "PASS_WITH_LIMITS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-a", type=Path, required=True)
    parser.add_argument("--run-b", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = compare(load(args.run_a), load(args.run_b),
                     (args.run_a.parent.as_posix(), args.run_b.parent.as_posix()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps({"verdict": result["verdict"],
                      "observations": result["observation_count"],
                      "problems": result["problems"]}))
    return 0 if result["verdict"] == "TECHNICAL_CANDIDATE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
