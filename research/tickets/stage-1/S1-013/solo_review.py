"""Run the operator-authorized accelerated two-role S1-013 walkthrough."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULT = HERE / "results" / "solo-review.json"


def module(name: str):
    spec = importlib.util.spec_from_file_location(f"s1013_solo_run_{name}", HERE / f"{name}.py")
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


def run(argv: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                          timeout=120, check=False)
    if proc.returncode:
        detail = (proc.stderr or proc.stdout).replace("\r", " ").replace("\n", " ")
        raise RuntimeError(detail[:500])
    return proc.stdout


def main() -> int:
    closure = module("solo_closure")
    decision = json.loads((HERE / "operator-decision.json").read_text(encoding="utf-8"))
    closure.verify_operator_decision(HERE, decision)
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node is required for the real browser walkthrough")
    environment = dict(os.environ)
    if not environment.get("NODE_PATH"):
        suffix = Path(".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules")
        roots = [Path(value) for name in ("USERPROFILE", "HOME")
                 if (value := environment.get(name))]
        roots.extend(Path(sys.executable).resolve().parents)
        for root in roots:
            bundled = root / suffix
            if bundled.is_dir():
                environment["NODE_PATH"] = str(bundled)
                break
    work = Path(tempfile.mkdtemp(prefix="s1013-solo-review-"))
    try:
        browser_results = {}
        envelope_hashes = {}
        for role in ("owner", "reviewer"):
            output = work / f"{role}.export.json"
            stdout = run([node, str(HERE / "prototype" / "browser_probe.cjs"),
                          str(output), role], HERE, environment)
            browser_results[role] = json.loads(stdout.strip().splitlines()[-1])
            envelope_hashes[role] = hashlib.sha256(output.read_bytes()).hexdigest()
        imported = work / "imported"
        run([sys.executable, str(HERE / "runner.py"), "--src", str(work),
             "--out", str(imported)], HERE, environment)
        observations = json.loads((imported / "observations.json").read_text(
            encoding="utf-8"))["observations"]
        by_role = {item["role"]: item for item in observations if item.get("status") == "ok"}
        if set(by_role) != {"owner", "reviewer"} or len(observations) != 2:
            raise RuntimeError("two-role importer matrix incomplete")
        metrics = module("evaluator").evaluate(imported, HERE)
        if metrics.get("human_n") != 0 or metrics.get("synthetic") is not True:
            raise RuntimeError("walkthrough was misclassified as human evidence")
        executions = []
        for role in ("owner", "reviewer"):
            record = by_role[role]["record"]
            events = record["events"]["events"]
            browser = browser_results[role]
            executions.append({
                "role": role, "browser_version": browser["browser"],
                "checks": browser["checks"], "import_status": "ok",
                "evaluator_completed": True,
                "approval_prompts": sum(event.get("type") == "decision" for event in events),
                "stop_confirmed": sum(event.get("type") == "stop_confirmed" for event in events),
                "transient_envelope_sha256": envelope_hashes[role],
            })
        summary = {
            "schema": "agentos.s1-013.solo-review/v1", "ticket": "S1-013",
            "operator_id": "OP-OWNER-01", "mode": "accelerated",
            "reviewed_roles": ["owner", "reviewer"],
            "classification": "operator_authorized_scripted_expert_conformance",
            "executions": executions, "human_n": 0,
            "independent_grading_performed": False, "raw_retained": False,
            "raw_repository_path": None, "result": "PASS_WITH_LIMITS",
            "human_effectiveness": "NOT_MEASURED",
            "full_human_pilot": "CANCELLED_BY_OPERATOR",
            "aggregate": {
                "eligible_synthetic_sessions": metrics["effective_participants"],
                "browser_roles_completed": 2,
                "tooling_chain": "browser-export-importer-evaluator",
            },
            "limitations": decision["limitations"],
        }
        closure.verify_solo_review(HERE, summary)
        RESULT.parent.mkdir(parents=True, exist_ok=True)
        temporary = RESULT.with_suffix(".tmp")
        temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8", newline="\n")
        temporary.replace(RESULT)
        print("solo review PASS_WITH_LIMITS: owner+reviewer, human_n=0, raw deleted")
        return 0
    finally:
        # Work is an OS temporary directory created by this process; no user path
        # or repository directory is accepted as input to this removal.
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
