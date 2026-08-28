"""Agent-driven autoresearch campaign (ROADMAP near-circle item 0).

Wires a real worker adapter (FakeWorker for deterministic drills,
DshAgentWorker/HermesAgentWorker for live LLM episodes) into the ADR-0008
campaign loop as the CANDIDATE GENERATOR:

    worktree -> worker.step() with the hypothesis -> DECLARED effects are
    replayed into the worktree by the HOST -> scope + frozen verification
    from disk -> dev evals at fixed seeds -> MANDATORY holdout -> decision.

The worker output is untrusted data; authorship is never trusted — the
campaign judges the resulting worktree bytes (mutable scope, frozen pins).

Run:  python -m eval.run_autoresearch --worker fake --db .agentos-autoresearch
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "eval"))

from agentos.autoresearch import Autoresearch, make_manifest  # noqa: E402
from agentos.db import open_db  # noqa: E402
from agentos.engine import Engine  # noqa: E402
from agentos.ids import sha256_text  # noqa: E402
from agentos.workers import FakeWorker, StepRequest  # noqa: E402

# -- frozen demo task -----------------------------------------------------------
CANDIDATE_REL = "candidate/add.py"

DEV_CASES = [((2, 3), 5), ((10, -4), 6)]
HOLD_CASES = [((7, 8), 15), ((0, 0), 0), ((5, 5), 10)]

GOOD_IMPL = (
    "def add(a, b):\n"
    "    return a + b\n"
)
BROKEN_IMPL = (
    "def add(a, b):\n"
    "    return a - b\n"
)
PARTIAL_IMPL = (
    "def add(a, b):\n"
    "    if a == b:\n"
    "        return a + b + 1\n"   # dev cases have a != b; holdout (5,5) breaks
    "    return a + b\n"
)

BASELINE_ERROR = 0.6   # current repo behavior has no candidate module at all


def task_definition() -> dict:
    return {
        "task": "implement add(a, b) in candidate/add.py",
        "candidate_rel": CANDIDATE_REL,
        "dev_cases": DEV_CASES,
        "holdout_cases": HOLD_CASES,
    }


def build_manifest(budget: int = 3):
    task_hash = sha256_text(json.dumps(task_definition(), sort_keys=True))
    corpus_path = _REPO / "evals" / "corpus_manifest.json"
    corpus_hash = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    manifest = make_manifest(
        baseline_ref="HEAD",
        primary_metric="dev_error_rate_min",
        mutable_scope=["candidate/*"],
        frozen_eval_hashes={"campaign_task": task_hash},
        corpus_hash=corpus_hash,
        budget=budget,
        seeds=[0],
        frozen_files={"evals/corpus_manifest.json": corpus_hash},
    )
    return manifest, {"campaign_task": task_hash}, corpus_hash


# -- host-owned candidate generation --------------------------------------------
def generate_candidate(wt: Path, worker, hypothesis: str,
                       dod: str, timeout_s: int) -> dict:
    """Spawn ONE worker episode scoped to the worktree; replay its DECLARED
    effects into the worktree. Host code only — the agent never gets
    authority; the campaign verifies the resulting bytes afterwards."""
    packet = (f"hypothesis: {hypothesis}\n"
              f"candidate file path must be exactly: {CANDIDATE_REL}\n"
              "declare the full module content via AGENTOS_EFFECTS blocks.")
    try:
        res = worker.step(StepRequest(
            task_id="autoresearch-candidate", run_id="autoresearch",
            goal_id="autoresearch", title=hypothesis[:120],
            definition_of_done=dod, inputs={},
            workspace_path=str(wt), step=0, checkpoint=None,
            context_packet_text=packet))
    except Exception as e:  # noqa: BLE001 — provider crash => CRASH class
        return {"crash": f"{type(e).__name__}: {e}"}
    if not res.ok:
        return {"crash": f"worker failed: {res.fail_class}: {res.note[:200]}"}
    written = []
    for rel, content in (res.outputs.get("files") or {}).items():
        target = wt / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(rel)
    return {"files": written}


def make_apply_host(worker, timeout_s: int, hypothesis: str):
    def apply_host(wt: Path) -> dict:
        info = generate_candidate(
            wt, worker, hypothesis,
            dod=f"write exactly one module {CANDIDATE_REL} implementing "
                f"add(a,b) for the cases in the packet",
            timeout_s=timeout_s)
        if info.get("crash"):
            # provider/worker failure => infrastructure failure => CRASH
            raise RuntimeError(info["crash"])
        return info
    return apply_host


# -- frozen evals ------------------------------------------------------------------
def _run_cases(wt: Path | None, cases) -> float:
    """Error rate over `cases` for the candidate module in the worktree."""
    if wt is None:
        return BASELINE_ERROR
    mod_path = wt / CANDIDATE_REL
    if not mod_path.exists():
        return 1.0
    try:
        spec = importlib.util.spec_from_file_location("campaign_candidate",
                                                      mod_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        passed = sum(1 for (a, b), want in cases
                     if getattr(mod, "add")(a, b) == want)
    except Exception:  # noqa: BLE001 — any candidate failure is an error
        return 1.0
    return 1.0 - passed / len(cases)


def dev_eval_fn(wt, seed: int = 0) -> float:
    return round(_run_cases(wt, DEV_CASES), 4)


def holdout_fn(wt, seed: int = 0) -> dict:
    err = _run_cases(wt, HOLD_CASES)
    return {"passed": wt is not None and err == 0.0, "error_rate": round(err, 4)}


# -- worker factory -----------------------------------------------------------------
def build_worker(kind: str, timeout_s: int, mode: str = "good"):
    if kind == "fake":
        impl = {"good": GOOD_IMPL, "broken": BROKEN_IMPL,
                "partial": PARTIAL_IMPL}[mode]
        return FakeWorker([{"ok": True,
                            "outputs": {"files": {CANDIDATE_REL: impl}}}])
    if kind == "dsh":
        from agentos.dsh_worker import DshAgentWorker
        return DshAgentWorker(timeout_s=timeout_s)
    if kind == "hermes":
        from agentos.hermes_worker import HermesAgentWorker
        return HermesAgentWorker(timeout_s=timeout_s)
    raise SystemExit(f"unknown worker kind: {kind}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="run_autoresearch")
    ap.add_argument("--db", default=".agentos-autoresearch")
    ap.add_argument("--worker", choices=["fake", "dsh", "hermes"],
                    default="fake")
    ap.add_argument("--mode", choices=["good", "broken", "partial"],
                    default="good",
                    help="fake-worker candidate quality preset")
    ap.add_argument("--budget", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=600,
                    help="per-episode worker timeout, seconds")
    ap.add_argument("--hypothesis", default="candidate add(a,b) beats the "
                                            "missing-module baseline")
    args = ap.parse_args(argv)

    root = Path(args.db).resolve()
    root.mkdir(parents=True, exist_ok=True)
    db = open_db(root / "agentos.db")
    eng = Engine(db, root)
    goal_id = eng.create_goal(
        f"autoresearch campaign: {args.hypothesis}", actor="autoresearch")

    ar = Autoresearch(db, root, stage_evals=None, repo_source=_REPO)
    manifest, eval_hashes, corpus_hash = build_manifest(budget=args.budget)
    if not ar.verify_frozen(manifest, eval_hashes, corpus_hash):
        print(json.dumps({"error": "frozen eval/corpus hashes changed"}))
        return 1

    worker = build_worker(args.worker, args.timeout, args.mode)
    results = ar.run_campaign(
        manifest,
        scenarios=[{
            "hypothesis": args.hypothesis,
            "candidate_ref": f"{args.worker}:{args.mode}",
            "apply_host": make_apply_host(worker, args.timeout,
                                          args.hypothesis),
            "noise_floor": 0.02,
        }],
        dev_eval_fn=dev_eval_fn,
        holdout_fn=holdout_fn,
        goal_id=goal_id)

    print(json.dumps({"goal_id": goal_id,
                      "manifest_hash": manifest.manifest_hash,
                      "results": results}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
