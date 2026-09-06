"""Fail-closed wall-clock preflight for the S1-019 synthesis ticket.

The checker reads a single Git tree, not the mutable working directory.  It
allows clocks as evidence in explicitly registered places, but prevents them
from silently selecting a cross-ticket architecture.  Legacy tickets with a
known timing path need a machine-checked counterfactual or quarantine rule.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
POLICY_PATH = HERE / "decision-input-policy.json"
POLICY = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
REQUIRED_TICKETS = tuple(POLICY["required_tickets"])
TICKET_ROOT = "research/tickets/stage-1"

CLOCK_NAMES = {
    "perf_counter", "perf_counter_ns", "monotonic", "monotonic_ns",
    "process_time", "process_time_ns", "time", "time_ns",
}

# Clock calls outside this exact registry are a new, unreviewed input and fail.
# Registration is not authority to use the value in synthesis; the semantic
# checks below constrain the known legacy paths.
ALLOWED_CLOCK_FILES = {
    "S1-004": {"simulator/run_formal.py", "simulator/run_acceptance.py"},
    "S1-005": {"experiments.py"},
    "S1-007": {"runner.py"},
    "S1-008": {"runner.py"},
    "S1-016": {"runner.py", "evaluator.py"},
    "S1-017": {"runner.py"},
    "S1-018": {"runner.py"},
}


class GitTree:
    """Read-only view of one commit/ref."""

    def __init__(self, repo: Path, ref: str):
        self.repo = repo.resolve()
        self.ref = ref

    def _git(self, *args: str) -> str:
        proc = subprocess.run(
            ["git", "-c", f"safe.directory={self.repo}", "-C",
             str(self.repo), *args],
            capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode != 0:
            raise ValueError((proc.stderr or proc.stdout).strip())
        return proc.stdout

    def list_files(self, prefix: str) -> list[str]:
        raw = self._git("ls-tree", "-r", "--name-only", self.ref, "--", prefix)
        return sorted(line for line in raw.splitlines() if line)

    def has(self, path: str) -> bool:
        return path in self.list_files(path)

    def read_text(self, path: str) -> str:
        return self._git("show", f"{self.ref}:{path}")

    def read_json(self, path: str) -> dict:
        value = json.loads(self.read_text(path))
        if not isinstance(value, dict):
            raise ValueError(f"{path}: expected JSON object")
        return value


def _call_name(node: ast.Call, direct_aliases: dict[str, str],
               module_aliases: set[str]) -> str | None:
    target = node.func
    if isinstance(target, ast.Name):
        if target.id in direct_aliases:
            return direct_aliases[target.id]
        if target.id in CLOCK_NAMES:
            return target.id
    if isinstance(target, ast.Attribute) and target.attr in CLOCK_NAMES:
        if isinstance(target.value, ast.Name) and target.value.id in module_aliases:
            return f"time.{target.attr}"
        return target.attr
    return None


def clock_calls(source: str) -> list[dict[str, Any]]:
    """Return executable wall-clock calls; comments and strings do not count."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [{"line": exc.lineno or 0, "call": "SYNTAX_ERROR"}]
    direct_aliases: dict[str, str] = {}
    module_aliases = {"time"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                if name.name == "time":
                    module_aliases.add(name.asname or name.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            for name in node.names:
                if name.name in CLOCK_NAMES:
                    direct_aliases[name.asname or name.name] = f"time.{name.name}"
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node, direct_aliases, module_aliases)
            if name:
                found.append({"line": node.lineno, "call": name})
    return sorted(found, key=lambda item: (item["line"], item["call"]))


def _weighted_scores(matrix: dict, rubric: dict,
                     excluded: set[str] | None = None) -> dict[str, float]:
    excluded = excluded or set()
    weights = rubric.get("weights", {})
    candidates = ("monolith", "containers")
    totals = {candidate: 0.0 for candidate in candidates}
    used = {candidate: 0.0 for candidate in candidates}
    for row in matrix.get("matrix", []):
        dimension = row.get("dimension")
        if dimension in excluded:
            continue
        weight = weights.get(dimension)
        if not isinstance(weight, (int, float)) or weight < 0:
            continue
        for candidate in candidates:
            score = row.get("cells", {}).get(candidate, {}).get("score")
            if isinstance(score, (int, float)):
                totals[candidate] += float(weight) * float(score)
                used[candidate] += float(weight)
    if any(value == 0 for value in used.values()):
        raise ValueError("S1-005 counterfactual has no scored weight")
    return {candidate: totals[candidate] / used[candidate]
            for candidate in candidates}


def _winner(scores: dict[str, float]) -> str:
    high = max(scores.values())
    winners = sorted(key for key, value in scores.items() if value == high)
    return winners[0] if len(winners) == 1 else "TIE"


def check_s1_005(matrix: dict, rubric: dict, result: dict) -> dict:
    baseline = _weighted_scores(matrix, rubric)
    counterfactual = _weighted_scores(
        matrix, rubric, excluded={"latency_serialization"})
    recorded = result.get("winner")
    baseline_winner = _winner(baseline)
    counterfactual_winner = _winner(counterfactual)
    passed = (recorded == baseline_winner == counterfactual_winner
              and recorded != "TIE")
    return {
        "ticket": "S1-005", "passed": passed,
        "rule": "latency-free counterfactual preserves recorded winner",
        "recorded_winner": recorded, "baseline_winner": baseline_winner,
        "counterfactual_winner": counterfactual_winner,
        "counterfactual_scores": {
            key: round(value, 4) for key, value in counterfactual.items()},
    }


def check_s1_007(timing: dict, decision: dict) -> dict:
    variants = timing.get("variants", {})
    verdicts = {name: value.get("verdict") for name, value in variants.items()
                if isinstance(value, dict)}
    d1 = decision.get("scores_per_dimension", {}).get("D1", {})
    d1_values = [d1.get(name) for name in ("per_scope", "shared_rls")]
    neutral = (set(verdicts) == {"per_scope", "shared_rls"}
               and all(value == "WITHIN_TOLERANCE"
                       for value in verdicts.values())
               and all(isinstance(value, (int, float)) for value in d1_values)
               and d1_values[0] == d1_values[1])
    return {
        "ticket": "S1-007", "passed": neutral,
        "rule": "wall-clock timing is directionally neutral",
        "timing_verdicts": verdicts, "d1": d1,
        "recorded_winner": decision.get("winner"),
    }


def check_s1_016(record: dict, candidate: dict,
                  sensitivity: dict) -> dict:
    flips_value = sensitivity.get("flips", 0)
    flips = len(flips_value) if isinstance(flips_value, list) else flips_value
    limitations = record.get("limitations", [])
    wall_clock_named = any(
        "wall-clock" in str(item).lower() for item in limitations)
    passed = (
        record.get("result") == "pass_with_limits"
        and candidate.get("design_decision") == "INCONCLUSIVE"
        and candidate.get("sensitivity_flips") == flips
        and isinstance(flips, int) and flips > 0
        and sensitivity.get("stable") is False
        and wall_clock_named
    )
    return {
        "ticket": "S1-016", "passed": passed,
        "rule": "noise-sensitive architecture winner is quarantined",
        "architecture_decision": candidate.get("design_decision"),
        "sensitivity_flips": flips, "wall_clock_limitation": wall_clock_named,
        "admissible_outputs": ["INCONCLUSIVE", "safety_findings"],
    }


def _function_text(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return ast.get_source_segment(source, node) or ""
    return ""


def check_latency_excluded(tree: Any, ticket: str) -> dict:
    prefix = f"{TICKET_ROOT}/{ticket}"
    sensitivity = tree.read_text(f"{prefix}/sensitivity.py")
    bundle = tree.read_text(f"{prefix}/make_bundle.py")
    scoring_name = "measured_scores" if ticket == "S1-017" else "_per_arch_scores"
    scoring_source = (sensitivity if ticket == "S1-017" else bundle)
    scoring = _function_text(scoring_source, scoring_name)
    projection = _function_text(bundle, "_semantic_metrics")
    dims = []
    parsed = ast.parse(sensitivity)
    for node in parsed.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "DIMS"
                for target in node.targets):
            dims = list(ast.literal_eval(node.value))
    forbidden = ("latency", "timing", "perf_counter", "monotonic")
    passed = (
        not clock_calls(sensitivity)
        and bool(scoring)
        and not any(token in scoring.lower() for token in forbidden)
        and not any(token in str(dim).lower() for dim in dims
                    for token in ("latency", "timing"))
        and bool(projection)
        and "latencies" in projection
        and "not in" in projection
    )
    return {
        "ticket": ticket, "passed": passed,
        "rule": "wall-clock excluded from semantic projection and sensitivity",
        "dimensions": dims, "scoring_function": scoring_name,
    }


def synthesis_import_policy() -> dict[str, dict[str, str]]:
    policy = {
        ticket: {"wall_clock": "deny", "architecture_decision": "allow"}
        for ticket in REQUIRED_TICKETS
    }
    policy["S1-008"] = {
        "wall_clock": "native_slo_only",
        "architecture_decision": "not_applicable",
    }
    policy["S1-016"] = {
        "wall_clock": "deny",
        "architecture_decision": "deny",
        "admissible": "INCONCLUSIVE and safety findings only",
    }
    return policy


def _semantic_checks(tree: Any) -> list[dict]:
    base = TICKET_ROOT
    return [
        check_s1_005(
            tree.read_json(f"{base}/S1-005/results/qa1-decision-matrix.json"),
            tree.read_json(f"{base}/S1-005/rubric.json"),
            tree.read_json(f"{base}/S1-005/results/sensitivity-analysis.json"),
        ),
        check_s1_007(
            tree.read_json(f"{base}/S1-007/results/timing-analysis.json"),
            tree.read_json(f"{base}/S1-007/results/decision-matrix.json"),
        ),
        check_s1_016(
            tree.read_json(f"{base}/S1-016/evaluation-record.json"),
            tree.read_json(f"{base}/S1-016/candidate-record.json"),
            tree.read_json(f"{base}/S1-016/results/sensitivity.json"),
        ),
        check_latency_excluded(tree, "S1-017"),
        check_latency_excluded(tree, "S1-018"),
    ]


def audit(tree: Any, semantic_checks: bool = True) -> dict:
    missing = []
    violations = []
    clock_inventory = []
    for ticket in REQUIRED_TICKETS:
        prefix = f"{TICKET_ROOT}/{ticket}/"
        files = tree.list_files(prefix)
        if not files:
            missing.append(ticket)
            continue
        allowed = ALLOWED_CLOCK_FILES.get(ticket, set())
        for path in files:
            if not path.endswith(".py"):
                continue
            relative = path[len(prefix):]
            calls = clock_calls(tree.read_text(path))
            if not calls:
                continue
            entry = {"ticket": ticket, "path": relative, "calls": calls,
                     "registered": relative in allowed}
            clock_inventory.append(entry)
            if relative not in allowed:
                violations.append({
                    **entry,
                    "reason": "unregistered executable clock source",
                })

    checks = []
    if semantic_checks and not missing:
        try:
            checks = _semantic_checks(tree)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            violations.append({
                "ticket": "S1-019", "path": "preflight",
                "reason": f"semantic check error: {exc}",
            })
        for check in checks:
            if not check.get("passed"):
                violations.append({
                    "ticket": check.get("ticket"), "path": "decision-input",
                    "reason": check.get("rule"), "evidence": check,
                })

    if missing:
        status = "BLOCKED_DEPENDENCY"
    elif violations:
        status = "FAIL"
    else:
        status = "PASS_WITH_LIMITS"
    policy_bytes = POLICY_PATH.read_bytes()
    return {
        "schema": "agentos.s1-019.wall-clock-preflight/v1",
        "status": status,
        "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
        "required_tickets": list(REQUIRED_TICKETS),
        "missing_tickets": missing,
        "clock_inventory": clock_inventory,
        "semantic_checks": checks,
        "violations": violations,
        "synthesis_import_policy": synthesis_import_policy(),
        "limitations": [
            "S1-005 and S1-007 are admitted by tracked counterfactual containment",
            "S1-016 architecture winner is quarantined",
            "S1-008 wall-clock evidence is scoped to its native revocation SLO",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--ref", default="origin/main")
    parser.add_argument("--out")
    args = parser.parse_args()
    report = audit(GitTree(Path(args.repo), args.ref))
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8", newline="\n")
    print(payload, end="")
    if report["status"] in {"PASS", "PASS_WITH_LIMITS"}:
        return 0
    return 2 if report["status"] == "BLOCKED_DEPENDENCY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
