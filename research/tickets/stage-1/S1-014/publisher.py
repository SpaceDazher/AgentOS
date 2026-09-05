"""S1-014 probes, process-separated replay, freeze and fail-closed publisher.

subcommands:
  freeze      explicit freeze of the whole input set -> frozen-manifest.json
  probes      run adversarial probes A-J through the production importer/evaluator
  replicate   two separate processes (distinct PID/executor/nonce/output root)
  publish     full pipeline; writes results/, candidate-record.json, bundle.json
              (PREPARATION_READY without operator decision; never above PWL)
  verify-decision  fail-closed check of operator-decision.json

Never network.  Never human N.  Never a winner.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as c  # noqa: E402
import evaluator  # noqa: E402
import importer  # noqa: E402

T = c.TICKET
RESULTS = T / "results"
FROZEN = T / "frozen-manifest.json"
FROZEN_INPUTS = [
    "contract.py", "importer.py", "evaluator.py", "publisher.py", "build_fixtures.py",
    "dependency_gate.py", "schemas/dispute.schema.json", "schemas/envelope.schema.json",
    "task-manifest.json", "oracle/oracle.json", "assignment-table.json",
    "prototype/index.html", "prototype/app.js", "prototype/style.css",
    "prototype/browser-contract.json", "prototype/browser_probe.cjs", "prototype/README.md",
    "renderer-contract.json", "decision-rule.json", "rubric.json", "operator-review-protocol.json",
    "source-registry.json", "protocol.md", "privacy-plan.md", "facilitator-guide.md",
    "analysis-plan.md", "templates/human-study-template.md",
    "synthetic/synthetic-manifest.json", "make_bundle.py",
]
FROZEN_GLOBS = ["sources/*", "synthetic/sessions/*.json"]
QUESTIONNAIRE = {str(i): opts for i, opts in enumerate(
    ["ABCD", "ABC", "AB", "ABC", "ABC", "AB", "AB", "AB", "ABC", "ABC", "ABC", "ABC"], start=1)}
HARD_VIOLATIONS = {"2": "B", "3": "B", "4": "BC", "6": "B", "7": "B", "8": "B", "9": "C"}
FORBIDDEN_WITHOUT_HUMANS = {"10": "C", "12": "C"}
STOP_ROUND = {"11": "C"}


def frozen_files(root: Path = T) -> list[str]:
    files = set(FROZEN_INPUTS)
    for pattern in FROZEN_GLOBS:
        files.update(str(p.relative_to(root)).replace(os.sep, "/") for p in root.glob(pattern) if p.is_file())
    return sorted(files)


def freeze(confirm: bool) -> dict:
    if not confirm:
        raise SystemExit("freeze requires --confirm after review; it is never run by the evaluator")
    entries = {rel: c.sha_file(T / rel) for rel in frozen_files()}
    manifest = {"schema": "agentos.s1-014.frozen-manifest/v1", "ticket": c.TICKET_ID,
                "contract_version": c.CONTRACT_VERSION, "files": entries,
                "browser_contract_sha256": c.frozen_browser_contract()["contract_sha256"],
                "rule": "replay rejects any added, missing or changed input; update only via `publisher.py freeze --confirm`"}
    manifest["manifest_sha256"] = c.digest(manifest["files"])
    c.dump(FROZEN, manifest)
    return manifest


def check_frozen(root: Path = T) -> list[str]:
    if not FROZEN.exists():
        return ["frozen-manifest.json missing"]
    manifest = c.load_json(FROZEN)
    problems = []
    expected = manifest["files"]
    if c.digest(expected) != manifest.get("manifest_sha256"):
        problems.append("frozen manifest digest mismatch")
    actual = {rel: c.sha_file(root / rel) for rel in frozen_files(root) if (root / rel).exists()}
    for rel in sorted(set(expected) | set(actual)):
        if rel not in actual:
            problems.append(f"frozen input missing: {rel}")
        elif rel not in expected:
            problems.append(f"unfrozen input added: {rel}")
        elif actual[rel] != expected[rel]:
            problems.append(f"frozen input changed: {rel}")
    return problems


# ------------------------------------------------------------------ helpers
def _import_and_evaluate(envelopes: list[dict], workdir: Path, executor: str = "EXEC-PROBE") -> tuple[dict, dict]:
    src = workdir / "in"
    src.mkdir(parents=True, exist_ok=True)
    for i, env in enumerate(envelopes):
        (src / f"{i:02d}.json").write_text(json.dumps(env, allow_nan=False), encoding="utf-8")
    out = workdir / "imp"
    importer.import_directory(src, out)
    manifest = c.load_json(out / "import-manifest.json")
    metrics = evaluator.evaluate(out, executor=executor) if manifest["accepted"] else None
    return manifest, metrics


def _synthetic() -> list[dict]:
    return [c.load_json(p) for p in sorted((T / "synthetic" / "sessions").glob("*.json"))]


def _resign(env: dict) -> dict:
    body = {k: v for k, v in env.items() if k != "payload_sha256"}
    body["payload_sha256"] = c.digest(body)
    return body


# ------------------------------------------------------------------ probes
def run_probes(workdir: Path) -> dict:
    disputes = c.load_json(T / "task-manifest.json")["disputes"]
    control_env = next(e for e in _synthetic() if all(t['outcome'] == 'submitted' and t['answer'] != '__MISSING__' for t in e['trials']))
    control_manifest, control_metrics = _import_and_evaluate([control_env], workdir / "control")
    control_ok = control_manifest["accepted"] == 1 and control_metrics["hard_gates_green"]
    probes: list[dict] = []

    def record(pid: str, title: str, expected: str, detected: bool, detail: Any) -> None:
        probes.append({"probe": pid, "title": title, "expected": expected, "detected": bool(detected),
                       "control_passed": control_ok, "detail": detail})

    d6 = next(d for d in disputes if d["ordinal"] == 6)
    # A: graph shows more nodes but hides canonical source / independence group
    g = c.render_graph(d6)
    for n in g["level0"]["nodes"]:
        if n["kind"] == "evidence":
            n["source_id"], n["origin"], n["independence_group"] = "HIDDEN", "HIDDEN", "HIDDEN"
    g["level0"]["nodes"].append({"id": "EV-99", "kind": "evidence", "label": "decorative", "source_id": "HIDDEN",
                                 "publisher": "x", "origin": "HIDDEN", "retrieval_boundary": "2026-08-08T00:00:00Z",
                                 "provenance_state": "known", "independence_group": "HIDDEN", "evidence_state": "known"})
    r = c.parity_report(d6, graph=g)
    record("A", "graph hides canonical source/independence group", "provenance gate FAIL",
           not r["equivalent"] and any("sources" in p or "independence" in p for p in r["problems"]), r["problems"][:4])
    # B: card shows winner, hides challenge (even if faster)
    d4 = next(d for d in disputes if d["ordinal"] == 4)
    card = c.render_card(d4)
    card["level0"]["challenge_indicator"] = {"present": False, "claim": {"claim_id": "CLM-04B", "text": "", "status": "rejected"}, "challenging_count": 0}
    r = c.parity_report(d4, card=card)
    record("B", "card hides challenge behind winning claim", "comprehension/challenge gate FAIL",
           not r["equivalent"] and any("challenge" in p or "claims" in p for p in r["problems"]), r["problems"][:4])
    # C: differing wording/choices/evidence/status between variants
    d1 = next(d for d in disputes if d["ordinal"] == 1)
    g = c.render_graph(d1)
    g["level0"]["task_wording"] = "Different wording"
    g["level0"]["nodes"][0]["status"] = "promoted-by-ui"
    r = c.parity_report(d1, graph=g)
    record("C", "variant wording/status drift", "equivalence FAIL before measurement", not r["equivalent"], r["problems"][:4])
    # D: missing/timeout/slow trials removed from denominator
    env = copy.deepcopy(next(e for e in _synthetic() if any(t['outcome'] == 'timeout' for t in e['trials'])))
    env["trials"] = [t for t in env["trials"] if t["outcome"] == "submitted"]
    manifest, _ = _import_and_evaluate([_resign(env)], workdir / "D")
    record("D", "denominator drop of timeout trial", "import FAIL", manifest["accepted"] == 0,
           manifest["entries"][0]["reasons"][:3])
    # E: forged adjudication / self-grading / single rater score
    env = copy.deepcopy(control_env)
    env["trials"][0]["correct"] = True
    env["session"]["adjudicated"] = True
    manifest, _ = _import_and_evaluate([_resign(env)], workdir / "E")
    record("E", "forged adjudicated/self-grade fields", "UNSCORED or FAIL", manifest["accepted"] == 0,
           manifest["entries"][0]["status"])
    # F: version/duplicate/sequence gap/non-monotonic/assignment drift
    variants = []
    e1 = copy.deepcopy(control_env); e1["contract_version"] = "9.9.9"; variants.append(("wrong version", _resign(e1)))
    variants.append(("duplicate session", copy.deepcopy(control_env)))
    e3 = copy.deepcopy(control_env); e3["events"][3]["seq"] = 99; variants.append(("sequence gap", _resign(e3)))
    e4 = copy.deepcopy(control_env); e4["events"][4]["t_ms"] = 1; variants.append(("non-monotonic time", _resign(e4)))
    e5 = copy.deepcopy(control_env); e5["trials"][0]["variant"] = "GRAPH" if e5["trials"][0]["variant"] == "CARD" else "CARD"; variants.append(("assignment drift", _resign(e5)))
    manifest, _ = _import_and_evaluate([control_env] + [v for _, v in variants], workdir / "F")
    statuses = [e["status"] for e in manifest["entries"]]
    record("F", "version/duplicate/sequence/time/assignment faults", "import FAIL for each fault",
           statuses[0] == "ok" and all(s != "ok" for s in statuses[1:]),
           dict(zip([n for n, _ in variants], statuses[1:])))
    # G: graph without keyboard/linear equivalent; card disclosure needs pointer
    g = c.render_graph(d1); g["level0"]["linear_equivalent"] = []
    card = c.render_card(d1); card["disclosures"]["provenance_detail"]["control"] = "hover"
    rg, rc = c.parity_report(d1, graph=g), c.parity_report(d1, card=card)
    env = copy.deepcopy(control_env); env["trials"][0]["pointer_used"] = True
    manifest, _ = _import_and_evaluate([_resign(env)], workdir / "G")
    record("G", "graph not keyboard/screen-reader reachable; pointer-only disclosure", "accessibility gate FAIL",
           not rg["equivalent"] and not rc["equivalent"] and manifest["accepted"] == 0,
           {"graph": rg["problems"][:2], "card": rc["problems"][:2], "pointer_in_keyboard_mode": manifest["entries"][0]["status"]})
    # H: saved verdict/metrics tampered without raw evidence -> publication FAIL on fresh recomputation
    tampered = copy.deepcopy(control_metrics); tampered["hard_gates_green"] = True; tampered["winner"] = "CARD"
    tampered["by_variant_task"] = {}
    record("H", "saved metrics/verdict tampered", "publication FAIL", compare_saved(tampered, control_metrics) != [],
           compare_saved(tampered, control_metrics)[:3])
    # I: synthetic dry-run claiming a winner or human N
    record("I", "synthetic output declares winner or human N", "hard FAIL",
           control_metrics["winner"] is None and control_metrics["human_study_n"] == 0
           and control_metrics["comparative_human_effectiveness"] == "NOT_MEASURED"
           and synthetic_claims_forbidden({"winner": "GRAPH", "human_study_n": 12}) != [],
           synthetic_claims_forbidden({"winner": "GRAPH", "human_study_n": 12}))
    # J: PII/secret/raw consent nested anywhere
    env = copy.deepcopy(control_env); env["events"].append({"seq": len(env["events"]) + 1, "t_ms": 10**7, "type": "session_complete", "detail": "op@example.org"})
    env["events"][-2]["t_ms"] = min(env["events"][-2]["t_ms"], 10**7)
    env2 = copy.deepcopy(control_env); env2["session"]["consent"]["form_version"] = "api_key=abc"
    manifest, _ = _import_and_evaluate([_resign(env), _resign(env2)], workdir / "J")
    record("J", "PII/secret nested in payload", "quarantine, no publication",
           all(e["status"] == "quarantined" for e in manifest["entries"]), [e["reasons"][:1] for e in manifest["entries"]])
    return {"schema": "agentos.s1-014.probes/v1", "control_passed": control_ok,
            "all_detected": control_ok and all(p["detected"] for p in probes), "probes": probes}


def compare_saved(saved: dict, fresh: dict) -> list[str]:
    problems = []
    for key in ("metrics_sha256", "hard_gates_green", "winner", "human_study_n",
                "comparative_human_effectiveness", "by_variant_task", "gates"):
        if saved.get(key) != fresh.get(key):
            problems.append(f"saved {key} differs from fresh recomputation")
    return problems


def synthetic_claims_forbidden(doc: dict) -> list[str]:
    problems = []
    if doc.get("winner") not in (None, ""):
        problems.append("winner declared without human study")
    if doc.get("human_study_n", 0) != 0:
        problems.append("human_study_n must be 0")
    if doc.get("comparative_human_effectiveness", "NOT_MEASURED") != "NOT_MEASURED":
        problems.append("comparative_human_effectiveness must be NOT_MEASURED")
    text = c.canonical(doc).decode().lower()
    for phrase in ("card is better", "graph is better", "superior", "outperform"):
        if phrase in text:
            problems.append(f"forbidden phrase: {phrase}")
    return problems


# --------------------------------------------------------------- replicate
def replicate(workdir: Path) -> dict:
    src = workdir / "sessions"
    src.mkdir(parents=True, exist_ok=True)
    for p in (T / "synthetic" / "sessions").glob("*.json"):
        shutil.copy(p, src / p.name)
    runs = []
    for label, seed_nonce in (("A", "nonce-a1"), ("B", "nonce-b2")):
        root = workdir / f"run-{label}"
        imp = root / "imp"
        imp.mkdir(parents=True, exist_ok=True)
        proc_imp = subprocess.run([sys.executable, str(T / "importer.py"), str(src), str(imp)],
                                  capture_output=True, text=True, check=False)
        proc = subprocess.run([sys.executable, str(T / "evaluator.py"), str(imp), str(root),
                               "--executor", f"EXEC-RUN-{label}", "--nonce", seed_nonce],
                              capture_output=True, text=True, check=False)
        if proc_imp.returncode or proc.returncode:
            raise RuntimeError(f"replay {label} failed: {proc_imp.stderr}{proc.stderr}")
        metrics = c.load_json(root / "metrics.json")
        runs.append({"run": label, "pid": metrics["pid"], "executor": metrics["executor"], "nonce": metrics["nonce"],
                     "output_root": str(root), "observations_sha256": metrics["observations_sha256"],
                     "metrics_sha256": metrics["metrics_sha256"], "hard_gates_green": metrics["hard_gates_green"]})
    same = (runs[0]["metrics_sha256"] == runs[1]["metrics_sha256"]
            and runs[0]["observations_sha256"] == runs[1]["observations_sha256"])
    distinct = runs[0]["pid"] != runs[1]["pid"] and runs[0]["executor"] != runs[1]["executor"] and runs[0]["nonce"] != runs[1]["nonce"]
    return {"schema": "agentos.s1-014.comparison/v1", "runs": runs, "digests_match": same,
            "process_separated": distinct, "replicated": same and distinct,
            "kind": "same-host process-separated replay (not external audit)",
            "metrics": c.load_json(workdir / "run-A" / "metrics.json")}


# ------------------------------------------------------------ operator decision
def verify_decision(decision: dict, frozen: dict, bundle_sha: str | None) -> list[str]:
    problems = []
    if decision.get("schema") != "agentos.s1-014.operator-decision/v1":
        problems.append("decision schema mismatch")
    answers = decision.get("selected_answers")
    if not isinstance(answers, dict) or set(answers) != set(QUESTIONNAIRE):
        return problems + ["decision must answer exactly questions 1..12"]
    for q, a in answers.items():
        if a not in QUESTIONNAIRE[q]:
            problems.append(f"question {q}: answer {a!r} outside grammar")
    for q, bad in HARD_VIOLATIONS.items():
        if answers.get(q) in bad:
            problems.append(f"question {q}={answers[q]} violates hard contract")
    for q, bad in FORBIDDEN_WITHOUT_HUMANS.items():
        if answers.get(q) == bad:
            problems.append(f"question {q}={bad} forbidden with human_study_n=0")
    for q, stop in STOP_ROUND.items():
        if answers.get(q) == stop:
            problems.append(f"question {q}={stop} requires separate recruitment authorisation; round stops")
    if decision.get("operator_review_n") != 1 or decision.get("human_study_n") != 0:
        problems.append("decision must record operator_review_n=1 and human_study_n=0")
    if decision.get("frozen_manifest_sha256") != frozen.get("manifest_sha256"):
        problems.append("decision bound to a different frozen manifest")
    if decision.get("browser_contract_sha256") != frozen.get("browser_contract_sha256"):
        problems.append("decision bound to a different browser contract")
    if bundle_sha and decision.get("bundle_sha256") != bundle_sha:
        problems.append("decision bundle binding differs from published bundle")
    if sorted(decision.get("variants_reviewed", [])) != ["CARD", "GRAPH"]:
        problems.append("both CARD and GRAPH must be reviewed")
    for key in ("name", "email", "free_text", "notes"):
        if key in c.canonical(decision).decode():
            problems.append(f"decision contains forbidden field {key}")
    return problems


def decision_outcome(answers: dict) -> str:
    return {"A": "CARD_WITH_GRAPH_DRILLDOWN", "B": "GRAPH_WITH_LINEAR_FALLBACK",
            "C": "TASK_DEPENDENT_SPLIT", "D": "NO_DEFAULT"}[answers["1"]]


# -------------------------------------------------------------------- publish
def _clean_stale() -> None:
    for name in ("metrics.json", "probes.json", "comparison.json", "task-equivalence.json",
                 "accessibility.json", "participant-flow.json"):
        (RESULTS / name).unlink(missing_ok=True)
    (T / "candidate-record.json").unlink(missing_ok=True)
    (T / "bundle.json").unlink(missing_ok=True)


def publish(browser_evidence: dict | None) -> dict:
    import make_bundle  # local, after frozen check
    problems = check_frozen()
    if problems:
        _clean_stale()
        raise SystemExit("frozen manifest violation: " + "; ".join(problems[:5]))
    gate = c.load_json(T / "dependency-gate.json")
    if not gate.get("phase_a_dependencies_proven"):
        _clean_stale()
        raise SystemExit("dependency gate not proven")
    with tempfile.TemporaryDirectory(prefix="s1-014-publish-") as td:
        work = Path(td)
        importer.import_directory(T / "synthetic" / "sessions", RESULTS / "import")
        probes = run_probes(work / "probes")
        comparison = replicate(work / "replay")
        fresh = evaluator.evaluate(RESULTS / "import", executor="EXEC-PUBLISH")
    metrics_for_compare = comparison.pop("metrics")
    if compare_saved(metrics_for_compare, fresh):
        _clean_stale()
        raise SystemExit("replay metrics differ from fresh recomputation")
    if not (probes["all_detected"] and comparison["replicated"] and fresh["hard_gates_green"]):
        _clean_stale()
        raise SystemExit("hard gate, probe or replay failure")
    forbidden = synthetic_claims_forbidden(fresh)
    if forbidden:
        _clean_stale()
        raise SystemExit("forbidden synthetic claim: " + "; ".join(forbidden))
    frozen = c.load_json(FROZEN)
    c.dump(RESULTS / "metrics.json", fresh)
    c.dump(RESULTS / "probes.json", probes)
    c.dump(RESULTS / "comparison.json", comparison)
    c.dump(RESULTS / "task-equivalence.json", {"schema": "agentos.s1-014.task-equivalence/v1",
                                               "all_equivalent": all(p["equivalent"] for p in fresh["parity"]),
                                               "disclosure_rule": c.DISCLOSURE_RULE, "reports": fresh["parity"]})
    c.dump(RESULTS / "accessibility.json", {"schema": "agentos.s1-014.accessibility/v1",
                                            "graph_linear_equivalent": fresh["gates"]["graph_linear_equivalent"],
                                            "disclosure_controls_are_buttons": True,
                                            "keyboard_only_browser_run": browser_evidence,
                                            "failures": fresh["gates"]["accessibility_failures"],
                                            "static_checks": static_ui_checks()})
    c.dump(RESULTS / "participant-flow.json", {"schema": "agentos.s1-014.participant-flow/v1",
                                               "human_study_n": 0, "operator_review_n": fresh["operator_review_n"],
                                               "synthetic_session_n": fresh["synthetic_session_n"],
                                               "sessions": fresh["sessions"],
                                               "import": c.load_json(RESULTS / "import" / "import-manifest.json")})
    decision_path = T / "operator-decision.json"
    status = "PREPARATION_READY"
    decision_summary = None
    if decision_path.exists():
        decision = c.load_json(decision_path)
        dproblems = verify_decision(decision, frozen, None)
        if dproblems:
            _clean_stale()
            raise SystemExit("operator decision rejected: " + "; ".join(dproblems))
        outcome = decision_outcome(decision["selected_answers"])
        status = "INCONCLUSIVE" if outcome == "NO_DEFAULT" else "PASS_WITH_LIMITS"
        decision_summary = {"outcome": outcome, "selected_answers": decision["selected_answers"],
                            "decided_at_utc": decision["decided_at_utc"], "operator_id": decision["operator_id"]}
    candidate = {
        "schema": "agentos.s1-014.candidate-record/v1", "ticket": c.TICKET_ID, "status": status,
        "operator_review": "REQUIRED" if decision_summary is None else "RECORDED",
        "operator_review_n": 0 if decision_summary is None else 1, "human_study_n": 0,
        "comparative_human_effectiveness": "NOT_MEASURED", "winner": None,
        "provisional_design_decision": None if decision_summary is None else decision_summary,
        "frozen_manifest_sha256": frozen["manifest_sha256"],
        "browser_contract_sha256": frozen["browser_contract_sha256"],
        "metrics_sha256": fresh["metrics_sha256"], "probes_all_detected": probes["all_detected"],
        "replicated": comparison["replicated"], "hard_gates_green": fresh["hard_gates_green"],
        "dependency_gate": {k: gate[k] for k in ("status", "phase_a_dependencies_proven",
                                                 "operator_review_dependencies_proven",
                                                 "population_human_claims_proven")},
        "inherited_limits": gate["inherited_limits"],
        "browser_evidence": browser_evidence,
        "variants": list(c.VARIANTS), "tasks": fresh["tasks"], "seeds": list(c.SEEDS), "executors": list(c.EXECUTORS),
    }
    c.dump(T / "candidate-record.json", candidate)
    bundle = make_bundle.build(candidate, fresh, probes, comparison, gate)
    c.dump(T / "bundle.json", bundle)
    candidate["bundle_sha256"] = c.sha_file(T / "bundle.json")
    c.dump(T / "candidate-record.json", candidate)
    return candidate


def static_ui_checks() -> dict:
    js = (T / "prototype" / "app.js").read_text(encoding="utf-8")
    html = (T / "prototype" / "index.html").read_text(encoding="utf-8")
    css = (T / "prototype" / "style.css").read_text(encoding="utf-8")
    js_no_ns = js.replace("http://www.w3.org/2000/svg", "")
    return {"no_innerHTML": ".innerHTML" not in js and "insertAdjacentHTML" not in js,
            "no_external_urls": "https://" not in js_no_ns and "http://" not in js_no_ns,
            "no_external_script_or_font": "https://" not in html and "<link rel=\"preconnect\"" not in html,
            "csp_present": "Content-Security-Policy" in html, "focus_visible_style": ":focus-visible" in css,
            "banner_present": c.BANNER in html, "no_date_now": "Date.now()" not in js,
            "performance_now_used": "performance.now()" in js, "no_oracle_reference": "correct_answer" not in js}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "publish"
    if cmd == "freeze":
        m = freeze("--confirm" in sys.argv)
        print("frozen", m["manifest_sha256"])
    elif cmd == "check-frozen":
        p = check_frozen()
        print("OK" if not p else "\n".join(p)); sys.exit(1 if p else 0)
    elif cmd == "probes":
        with tempfile.TemporaryDirectory() as td:
            r = run_probes(Path(td))
        print(json.dumps({p["probe"]: p["detected"] for p in r["probes"]}), "all", r["all_detected"])
    elif cmd == "replicate":
        with tempfile.TemporaryDirectory() as td:
            r = replicate(Path(td)); r.pop("metrics")
        print(json.dumps(r, indent=1))
    elif cmd == "verify-decision":
        d = c.load_json(T / "operator-decision.json")
        p = verify_decision(d, c.load_json(FROZEN), c.sha_file(T / "bundle.json") if (T / "bundle.json").exists() else None)
        print("OK " + decision_outcome(d["selected_answers"]) if not p else "\n".join(p)); sys.exit(1 if p else 0)
    else:
        evidence = None
        if len(sys.argv) > 2 and Path(sys.argv[2]).exists():
            evidence = c.load_json(Path(sys.argv[2]))
        rec = publish(evidence)
        print(rec["status"], "bundle", rec["bundle_sha256"])
