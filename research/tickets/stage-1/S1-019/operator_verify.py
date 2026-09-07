"""Bind real operator answers to the frozen S1-019 technical candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

TICKET = Path(__file__).resolve().parent
ANSWER_RE = re.compile(r"^(?:[1-9]|10)[ABC]$")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--answers", nargs=10, required=True)
    parser.add_argument("--operator-id", required=True)
    args = parser.parse_args()
    expected_numbers = [str(number) for number in range(1, 11)]
    normalized = [value.upper() for value in args.answers]
    if any(not ANSWER_RE.fullmatch(value) for value in normalized):
        raise SystemExit("answers must be 1A ... 10A tokens")
    if [re.match(r"\d+", value).group() for value in normalized] != expected_numbers:
        raise SystemExit("answers must be ordered 1 through 10")
    comparison = json.loads((TICKET / "results/comparison.json").read_text("utf-8"))
    if comparison.get("verdict") != "TECHNICAL_CANDIDATE":
        raise SystemExit("technical candidate is not admissible")
    choices = {str(index): value[-1] for index, value in enumerate(normalized, 1)}
    if choices["10"] == "A":
        status = "PASS_WITH_LIMITS"
    elif choices["10"] == "B":
        status = "DEFER"
    else:
        status = "FAIL"
    if any(choices[str(index)] != "A" for index in range(1, 7)) and status == "PASS_WITH_LIMITS":
        status = "DEFER"
    decision = {
        "schema": "agentos.s1-019.operator-decision/v1",
        "operator_id": args.operator_id,
        "selected_answers": choices,
        "answer_tokens": normalized,
        "questionnaire_sha256": sha(TICKET / "operator-questionnaire.md"),
        "frozen_manifest_sha256": sha(TICKET / "frozen-manifest.json"),
        "technical_comparison_sha256": sha(TICKET / "results/comparison.json"),
        "decision_matrix_sha256": sha(TICKET / "decision-matrix.json"),
        "hard_gates_all_pass": all(comparison["hard_gates"].values()),
        "derived_status": status,
        "verdict_ceiling": "PASS_WITH_LIMITS",
        "operator_cannot_override_hard_gates": True,
        "production_authority": False,
        "goal_acceptance_authority": False,
    }
    (TICKET / "operator-decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({"status": status, "operator_id": args.operator_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
