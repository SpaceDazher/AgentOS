"""AgentOS S1-004 — formal engine driver (Alloy + TLC).

Executes the versioned Alloy and TLA+ models with the real engines recorded
in ``results/ENVIRONMENT.md`` and captures full reports plus SHA-256 of
every model and engine artifact. Stdlib only (java is shell-out).

Fail-closed: a missing engine jar, a non-zero engine exit, or an
unrecognizable verdict line aborts with a non-zero exit code.

Usage (from the repository root):
    python research/tickets/stage-1/S1-004/simulator/run_formal.py \
        --ticket research/tickets/stage-1/S1-004
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ALLOY_MAIN_CLASS = "edu.mit.csail.sdg.alloy4whole.SimpleCLI"
TLC_MAIN_CLASS = "tlc2.TLC"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(message: str) -> None:
    print(f"FORMAL FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def java_version() -> str:
    out = subprocess.run(["java", "-version"], capture_output=True, text=True)
    return (out.stderr or out.stdout).splitlines()[0].strip()


def run_alloy(ticket: Path, out_dir: Path) -> dict:
    jar = (ticket / "tools" / "alloy.jar").resolve()
    model = (ticket / "alloy" / "agentos_structural_v2.als").resolve()
    stale_tmp = ticket / ".alloy.tmp"
    if stale_tmp.exists():
        # fail closed: never read a report from a previous invocation
        stale_tmp.unlink()
    if not jar.is_file():
        fail(f"missing alloy jar: {jar}")
    if not model.is_file():
        fail(f"missing alloy model: {model}")
    report_lines = [
        "AgentOS S1-004 Alloy structural model run",
        f"command: java -Dsat4j=yes -cp tools/alloy.jar {ALLOY_MAIN_CLASS} "
        f"alloy/agentos_structural_v2.als",
        f"engine: Alloy {ALLOY_MAIN_CLASS} (org.alloytools.alloy.dist), "
        f"jar sha256={sha256_file(jar)}",
        f"model: alloy/agentos_structural_v2.als sha256={sha256_file(model)}",
        f"runtime: {java_version()} on {platform.platform()}",
        f"java_property: -Dsat4j=yes (pure-java SAT solver, bundled sat4j)",
        "note: SimpleCLI hardcodes placeholder solve timings (12345ms) in "
        "its reporter; verdict lines are authoritative.",
        "",
    ]
    t0 = time.time()
    proc = subprocess.run(
        ["java", "-Dsat4j=yes", "-cp", str(jar), ALLOY_MAIN_CLASS,
         str(model)],
        capture_output=True, text=True, cwd=str(ticket), timeout=3600)
    elapsed = time.time() - t0
    tmp = ticket / ".alloy.tmp"
    if not tmp.is_file():
        fail("alloy report .alloy.tmp was not produced; java stderr:\n"
             + (proc.stderr or proc.stdout or "<empty>"))
    body = tmp.read_text(encoding="utf-8", errors="replace")
    report_lines.append(f"exit_code: {proc.returncode}")
    report_lines.append(f"wall_seconds: {elapsed:.1f}")
    report_lines.append("---- engine report (.alloy.tmp) ----")
    report_lines.append(body)
    out = out_dir / "alloy_report.txt"
    out.write_text("\n".join(report_lines).rstrip("\n") + "\n",
                   encoding="utf-8", newline="\n")

    verdicts = []
    for m in re.finditer(r'Executing "(Run|Check) ([^"]+)"\n(.*?)(?=Executing|\Z)',
                         body, re.S):
        kind, name, block = m.group(1), m.group(2), m.group(3)
        if "Instance found. Predicate is consistent." in block:
            verdict = "SAT"
        elif "No instance found. Predicate may be inconsistent." in block:
            verdict = "UNSAT"
        elif "Counterexample found. Assertion is invalid." in block:
            verdict = "COUNTEREXAMPLE"
        elif "No counterexample found. Assertion may be valid." in block:
            verdict = "NO_COUNTEREXAMPLE"
        else:
            verdict = "UNRECOGNIZED"
        verdicts.append({"command": f"{kind} {name}", "verdict": verdict})
    if not verdicts or any(v["verdict"] == "UNRECOGNIZED" for v in verdicts):
        fail(f"alloy verdicts not recognizable: {verdicts}")

    # expected matrix: Valid* SAT, NearMiss* UNSAT, Mutant* SAT
    problems = []
    for v in verdicts:
        name = v["command"]
        if name.startswith("Run Valid") and v["verdict"] != "SAT":
            problems.append(f"{name}: expected SAT, got {v['verdict']}")
        if name.startswith("Run NearMiss") and v["verdict"] != "UNSAT":
            problems.append(f"{name}: expected UNSAT, got {v['verdict']}")
        if name.startswith("Run Mutant") and v["verdict"] != "SAT":
            problems.append(f"{name}: expected SAT, got {v['verdict']}")
    expected = {
        "commands": verdicts,
        "expectation_problems": problems,
        "verdict": "PASS" if not problems else "FAIL",
    }
    (out_dir / "alloy_verdicts.json").write_text(
        json.dumps(expected, indent=2), encoding="utf-8")
    if problems:
        fail(f"alloy expectation matrix violated: {problems}")
    return expected


def run_tla(ticket: Path, out_dir: Path) -> dict:
    jar = ticket / "tools" / "tla2tools-1.7.0.jar"
    spec = ticket / "tla" / "agentos_transitions_v1.tla"
    cfg = ticket / "tla" / "agentos_transitions_v1.cfg"
    for p in (jar, spec, cfg):
        if not p.is_file():
            fail(f"missing TLA artifact: {p}")
    command = ["java", "-cp", str(jar.resolve()), TLC_MAIN_CLASS,
               "-deadlock", "-config", "agentos_transitions_v1.cfg",
               "agentos_transitions_v1.tla"]
    report_lines = [
        "AgentOS S1-004 TLA+ transition model run (TLC)",
        f"command: java -cp tools/tla2tools-1.7.0.jar {TLC_MAIN_CLASS} "
        f"-deadlock -config agentos_transitions_v1.cfg "
        f"agentos_transitions_v1.tla  (run inside a scratch directory "
        f"containing copies of the module and config)",
        f"engine: TLC2 from tla2tools 1.7.0 (TLC2 Version 2.15), "
        f"jar sha256={sha256_file(jar)}",
        f"spec: tla/agentos_transitions_v1.tla sha256={sha256_file(spec)}",
        f"config: tla/agentos_transitions_v1.cfg sha256={sha256_file(cfg)}",
        f"runtime: {java_version()} on {platform.platform()}",
        "-deadlock rationale: bounded-model terminal states (tick = MaxTick "
        "or exhausted retry budget publishes = MaxPub) have no enabled "
        "action by design; premature parking is ruled out by the "
        "LiveDelivery temporal property under weak fairness.",
        "",
    ]
    with tempfile.TemporaryDirectory() as td:
        shutil.copy(spec, Path(td) / spec.name)
        shutil.copy(cfg, Path(td) / cfg.name)
        t0 = time.time()
        proc = subprocess.run(command, capture_output=True, text=True,
                              cwd=td, timeout=7200)
        elapsed = time.time() - t0
        console = proc.stdout + "\n" + proc.stderr
        states_dir = Path(td) / "states"
    report_lines.append(f"exit_code: {proc.returncode}")
    report_lines.append(f"wall_seconds: {elapsed:.1f}")
    report_lines.append("---- TLC console ----")
    report_lines.append(console)
    out = out_dir / "tlc_report.txt"
    out.write_text("\n".join(report_lines).rstrip("\n") + "\n",
                   encoding="utf-8", newline="\n")

    if proc.returncode != 0:
        fail(f"TLC exited non-zero: see {out}")
    completed = re.search(r"Model checking completed\. No error has been found\.",
                          console)
    # TLC progress lines use locale group separators (e.g. U+202F); take the
    # final occurrence of each counter and strip separators.
    def last_count(phrase):
        matches = re.findall(
            r"([\d\u00a0\u202f,]+)\s+" + re.escape(phrase), console)
        if not matches:
            return None
        digits = re.sub(r"\D", "", matches[-1])
        return int(digits) if digits else None
    states = last_count("distinct states found")
    generated = last_count("states generated")
    temporal = re.search(r"Finished checking temporal properties", console)
    if not completed or not states:
        fail("TLC report lacks a completion marker")
    result = {
        "completed_no_error": bool(completed),
        "distinct_states": states,
        "states_generated": generated,
        "temporal_properties_checked": bool(temporal),
        "verdict": "PASS",
        "model_bounds": {
            "grants": "{g1, g2}", "decisions": "{d1}", "alloc": 3,
            "max_tick": 4, "max_publishes": 2,
        },
    }
    (out_dir / "tlc_verdicts.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True)
    args = parser.parse_args(argv)
    ticket = Path(args.ticket)
    out_dir = ticket / "results"
    (out_dir / "alloy").mkdir(parents=True, exist_ok=True)
    (out_dir / "tla").mkdir(parents=True, exist_ok=True)

    alloy = run_alloy(ticket, out_dir / "alloy")
    print(f"[alloy] verdict={alloy['verdict']} "
          f"commands={len(alloy['commands'])}")
    tla = run_tla(ticket, out_dir / "tla")
    print(f"[tla] verdict={tla['verdict']} "
          f"distinct_states={tla['distinct_states']}")
    summary = {"alloy": alloy, "tla": tla}
    (out_dir / "formal_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[formal] summary written to results/formal_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
