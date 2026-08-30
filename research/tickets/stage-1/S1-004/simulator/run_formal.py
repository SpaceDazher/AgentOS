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
import locale
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
CONSOLE_ENCODING = locale.getpreferredencoding(False)

EXPECTED_ALLOY_COMMANDS = {
    "Run ValidDerivedGrantAndPromotion for 4 but exactly 2 Grant, "
    "exactly 2 Right, exactly 1 IdentityMembership": "SAT",
    "Run ValidProposedWithoutPromotion for 3": "SAT",
    "Run NearMissDualIdentity for 4": "UNSAT",
    "Run NearMissTwoScopes for 3": "UNSAT",
    "Run NearMissRightsExpansion for 4 but exactly 2 Grant, "
    "exactly 2 Right": "UNSAT",
    "Run NearMissPromotedWithoutEvidence for 4": "UNSAT",
    "Run NearMissPromotedWrongActivityCount for 4": "UNSAT",
    "Run MutantDualIdentity for 4": "SAT",
    "Run MutantTwoScopes for 3": "SAT",
    "Run MutantRightsExpansion for 4 but exactly 2 Grant, "
    "exactly 2 Right": "SAT",
    "Run MutantPromotedWithoutEvidence for 4": "SAT",
    "Run MutantPromotedWrongActivityCount for 4": "SAT",
}

REQUIRED_TLC_INVARIANTS = {
    "TypeOk", "BudgetConservation", "ChildBudgetConsistency",
    "RevocationMonotonicity", "OutboxCompleteness", "ReceiptConsistency",
    "NoBlindRetry", "GrantStateMachine", "ActivationWithinOneTick",
    "FenceMonotone",
}
REQUIRED_TLC_PROPERTIES = {"LiveDelivery"}
REQUIRED_TLC_CONFIG_LINES = {
    "SPECIFICATION Spec",
    "Grants = {g1, g2}",
    "Root = g1",
    "Child = g2",
    "Decisions = {d1}",
    "Alloc = 3",
    "MaxTick = 4",
    "MaxPub = 2",
}


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
    out = subprocess.run(
        ["java", "-version"], capture_output=True, text=True,
        encoding=CONSOLE_ENCODING, errors="strict")
    return (out.stderr or out.stdout).splitlines()[0].strip()


def validate_alloy_execution(returncode: int, body: str) -> dict:
    """Validate an Alloy report against the exact frozen command matrix."""
    if returncode != 0:
        raise ValueError(f"Alloy exited non-zero: {returncode}")
    verdicts = []
    for match in re.finditer(
            r'Executing "(Run|Check) ([^"]+)"\n(.*?)(?=Executing|\Z)',
            body, re.S):
        kind, name, block = match.group(1), match.group(2), match.group(3)
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

    names = [item["command"] for item in verdicts]
    duplicate_names = sorted({name for name in names if names.count(name) > 1})
    missing = sorted(set(EXPECTED_ALLOY_COMMANDS) - set(names))
    unexpected = sorted(set(names) - set(EXPECTED_ALLOY_COMMANDS))
    problems = []
    if duplicate_names:
        problems.append(f"duplicate commands: {duplicate_names}")
    if missing:
        problems.append(f"missing commands: {missing}")
    if unexpected:
        problems.append(f"unexpected commands: {unexpected}")
    if len(verdicts) != len(EXPECTED_ALLOY_COMMANDS):
        problems.append(
            f"command count {len(verdicts)} != {len(EXPECTED_ALLOY_COMMANDS)}")
    for item in verdicts:
        expected = EXPECTED_ALLOY_COMMANDS.get(item["command"])
        if expected is not None and item["verdict"] != expected:
            problems.append(
                f"{item['command']}: expected {expected}, "
                f"got {item['verdict']}")
    if problems:
        raise ValueError("; ".join(problems))
    return {
        "commands": verdicts,
        "expectation_problems": [],
        "verdict": "PASS",
    }


def validate_tlc_execution(returncode: int, console: str, cfg_text: str) -> dict:
    """Require the frozen invariant/property set and temporal verification."""
    if returncode != 0:
        raise ValueError(f"TLC exited non-zero: {returncode}")
    invariants = re.findall(r"^\s*INVARIANT\s+(\S+)\s*$", cfg_text, re.M)
    properties = re.findall(r"^\s*PROPERTY\s+(\S+)\s*$", cfg_text, re.M)
    if len(invariants) != len(set(invariants)):
        raise ValueError("TLC config contains duplicate invariants")
    if set(invariants) != REQUIRED_TLC_INVARIANTS:
        raise ValueError(
            "TLC config invariant set mismatch: "
            f"expected={sorted(REQUIRED_TLC_INVARIANTS)} actual={sorted(invariants)}")
    if len(properties) != len(set(properties)):
        raise ValueError("TLC config contains duplicate properties")
    if set(properties) != REQUIRED_TLC_PROPERTIES:
        raise ValueError(
            "TLC config property set mismatch: "
            f"expected={sorted(REQUIRED_TLC_PROPERTIES)} actual={sorted(properties)}")
    normalized_lines = {
        re.sub(r"\s+", " ", line.strip())
        for line in cfg_text.splitlines() if line.strip()
    }
    missing_config = sorted(REQUIRED_TLC_CONFIG_LINES - normalized_lines)
    if missing_config:
        raise ValueError(f"TLC config bound/spec mismatch: {missing_config}")

    completed = bool(re.search(
        r"Model checking completed\. No error has been found\.", console))

    def last_count(phrase: str) -> int | None:
        matches = re.findall(
            r"([\d\u00a0\u202f,]+)\s+" + re.escape(phrase), console)
        if not matches:
            return None
        digits = re.sub(r"\D", "", matches[-1])
        return int(digits) if digits else None

    states = last_count("distinct states found")
    generated = last_count("states generated")
    temporal = bool(re.search(r"Finished checking temporal properties", console))
    if not completed:
        raise ValueError("TLC report lacks a no-error completion marker")
    if not states or not generated:
        raise ValueError("TLC report lacks positive state counters")
    if not temporal:
        raise ValueError("TLC report lacks temporal verification marker")
    return {
        "completed_no_error": True,
        "distinct_states": states,
        "states_generated": generated,
        "temporal_properties_checked": True,
        "verified_invariants": sorted(REQUIRED_TLC_INVARIANTS),
        "verified_properties": sorted(REQUIRED_TLC_PROPERTIES),
        "verdict": "PASS",
        "model_bounds": {
            "grants": "{g1, g2}", "decisions": "{d1}", "alloc": 3,
            "max_tick": 4, "max_publishes": 2,
        },
    }


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
        f"console_encoding: {CONSOLE_ENCODING} (strict decoding)",
        f"java_property: -Dsat4j=yes (pure-java SAT solver, bundled sat4j)",
        "note: SimpleCLI hardcodes placeholder solve timings (12345ms) in "
        "its reporter; verdict lines are authoritative.",
        "",
    ]
    t0 = time.time()
    proc = subprocess.run(
        ["java", "-Dsat4j=yes", "-cp", str(jar), ALLOY_MAIN_CLASS,
         str(model)],
        capture_output=True, text=True, encoding=CONSOLE_ENCODING,
        errors="strict",
        cwd=str(ticket), timeout=3600)
    elapsed = time.time() - t0
    tmp = ticket / ".alloy.tmp"
    if not tmp.is_file():
        fail("alloy report .alloy.tmp was not produced; java stderr:\n"
             + (proc.stderr or proc.stdout or "<empty>"))
    body = tmp.read_text(encoding="utf-8", errors="strict")
    report_lines.append(f"exit_code: {proc.returncode}")
    report_lines.append(f"wall_seconds: {elapsed:.1f}")
    report_lines.append("---- engine report (.alloy.tmp) ----")
    report_lines.append(body)
    out = out_dir / "alloy_report.txt"
    out.write_text("\n".join(report_lines).rstrip("\n") + "\n",
                   encoding="utf-8", newline="\n")

    try:
        expected = validate_alloy_execution(proc.returncode, body)
    except ValueError as exc:
        fail(str(exc))
    (out_dir / "alloy_verdicts.json").write_text(
        json.dumps(expected, indent=2), encoding="utf-8")
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
        f"console_encoding: {CONSOLE_ENCODING} (strict decoding)",
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
                              encoding=CONSOLE_ENCODING, errors="strict",
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

    try:
        result = validate_tlc_execution(
            proc.returncode, console, cfg.read_text(encoding="utf-8"))
    except ValueError as exc:
        fail(f"{exc}: see {out}")
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
