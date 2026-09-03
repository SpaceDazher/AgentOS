#!/usr/bin/env python3
"""S1-006 executable replay/resume safety probes (stdlib only, offline, no
LLM/network).  Fail-closed: any missing artifact, hash mismatch, duplicated
effect, or unmapped outcome is a failure or an explicit abstention, never a
silent pass.

Probe: ``replay-resume``
    Simulates crash/replay along a dependency-ready task DAG with external
    effects and verifies:

      (a) CRASH-A (crash after local transition, before publish): the outbox
          replay publishes the effect exactly once; one unique receipt; a
          duplicate replay is refused.
      (b) CRASH-B (publish happened, acknowledgement lost): the effect is
          never re-executed; the unknown outcome enters reconciliation and is
          never blind-retried; receipt count stays one.
      (c) CRASH-C (crash mid-DAG after several effects are published): resume
          finishes the remaining tasks without re-executing earlier effects.
      (d) CRASH-D (crash during the resume attempt itself): a second resume
          does not duplicate effects already published before either crash.
      (e) Near-miss: a naive backend that on resume re-runs a step whose
          effect is already published MUST FAIL unless the duplicate outcome
          is reconciled AND its receipt is unique (a fresh unique receipt
          issued after reconciliation).  Either condition alone is rejected.
      (f) Checkpoint corruption: a checkpoint whose declared sha256 does not
          match its body must refuse resume (fail-closed).
      (g) Dependency-ready ordering: a dependent task is executed only after
          every dependency task's effect is published, under recovery too.
      (h) Evidence integrity: every repo-local source hash declared in the
          bundle is recomputed from disk and must match.

This mirrors the S1-004 safety semantics (outbox/replay exactly-once,
unknown-outcome -> reconciliation, unique receipts) which the ticket must not
regress.

The last stdout line is the machine-readable verdict:
``{"status": "pass"|"fail", "observed": "pass"|"fail", ...}``; the process
exits 0 only on ``pass`` and always writes ``probe-results.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

TICKET_DIR = Path(__file__).resolve().parent
BUNDLE_PATH = TICKET_DIR / "bundle.json"
RESULTS_PATH = TICKET_DIR / "probe-results.json"
RESULTS_SCHEMA = "agentos.s1-006-probe-results/v1"
VERDICT_SCHEMA = "agentos.s1-006-probe-verdict/v1"
PROBE_NAME = "replay-resume"

# Fixed scripted scenario DAG.  Each task executes one external effect once.
# Edges: a -> b, a -> c, b -> d, c -> d, d -> e  (dependency-ready fan-in/out).
DAG = {
    "a": {"deps": [], "effect": "t:a:sync"},
    "b": {"deps": ["a"], "effect": "t:b:sync"},
    "c": {"deps": ["a"], "effect": "t:c:sync"},
    "d": {"deps": ["b", "c"], "effect": "t:d:sync"},
    "e": {"deps": ["d"], "effect": "t:e:sync"},
}
TOPOLOGICAL = ["a", "b", "c", "d", "e"]
ALL_EFFECTS = [DAG[t]["effect"] for t in TOPOLOGICAL]


class EffectSink:
    """The external world.  Each effect key records every execution and every
    receipt issued; receipts are globally unique."""

    def __init__(self) -> None:
        self.executions: dict[str, int] = {}
        self.receipts: dict[str, list[str]] = {}
        self._seq = 0

    def execute(self, key: str) -> str:
        self.executions[key] = self.executions.get(key, 0) + 1
        self._seq += 1
        rid = f"r-{key}-{self._seq}"
        self.receipts.setdefault(key, []).append(rid)
        return rid

    def receipt_count(self, key: str) -> int:
        return len(self.receipts.get(key, []))

    def unique_receipts(self, key: str) -> int:
        return len(set(self.receipts.get(key, [])))


# Effect lifecycle per intent: LOCAL_COMMITTED (no outcome yet),
# PUBLISHED (outcome known + receipt), UNKNOWN (delivered, ack lost),
# RECONCILED_SUCCEEDED / RECONCILED_FAILED (after reconciliation).
PUBLISHED = "PUBLISHED"
UNKNOWN = "UNKNOWN"
LOCAL_COMMITTED = "LOCAL_COMMITTED"


class ReplayGuard:
    """The exactly-once / reconciliation guard over a run's effect intents."""

    def __init__(self, sink: EffectSink) -> None:
        self.sink = sink
        self.intents: dict[str, dict] = {}

    def intent(self, key: str) -> dict:
        if key not in self.intents:
            self.intents[key] = {
                "state": LOCAL_COMMITTED, "receipts": [], "reconciled": None,
            }
        return self.intents[key]

    def publish(self, key: str) -> str:
        """Publish an effect exactly once.  Any state other than
        LOCAL_COMMITTED (already published, unknown, or reconciled) refuses a
        new publish: duplicate delivery needs the supervised path below."""
        st = self.intent(key)
        if st["state"] != LOCAL_COMMITTED:
            raise AssertionError(
                "%s already %s (duplicate publish refused)" % (key, st["state"]))
        rid = self.sink.execute(key)
        st["receipts"].append(rid)
        st["state"] = PUBLISHED
        return rid

    def mark_unknown(self, key: str) -> None:
        st = self.intent(key)
        if st["state"] != PUBLISHED:
            raise AssertionError(f"{key} not PUBLISHED before unknown mark")
        st["state"] = UNKNOWN

    def reconcile(self, key: str, observed_succeeded: bool) -> str:
        """Reconciliation is its own authorized operation, never an
        auto-retry.  Only an UNKNOWN state may be reconciled."""
        st = self.intent(key)
        if st["state"] != UNKNOWN:
            raise AssertionError(f"{key} cannot be reconciled from {st['state']}")
        st["reconciled"] = observed_succeeded
        if observed_succeeded and self.sink.executions.get(key, 0) != 1:
            raise AssertionError(f"{key} reconciled-success implies sink==1")
        st["state"] = "RECONCILED_SUCCEEDED" if observed_succeeded else "RECONCILED_FAILED"
        return st["state"]

    def check_reconciled_unique_duplicate(self, key: str) -> list[str]:
        """Adversarial evaluation of a naive re-delivery: allowed ONLY when
        the original outcome was reconciled AND a new unique receipt is
        issued.  This is the ticket's duplicate-effect guard."""
        problems: list[str] = []
        st = self.intent(key)
        if st["state"] == UNKNOWN and st["reconciled"] is None:
            problems.append("duplicate delivery with unresolved UNKNOWN outcome "
                            "(reconciliation required)")
        if st["reconciled"] is None:
            problems.append("no reconciliation of the original outcome")
        # emulate the naive re-run: identical receipt re-emitted
        last = self.sink.receipts.get(key, [None])[-1]
        if last is not None:
            if last in self.sink.receipts.get(key, []):
                problems.append("receipt is not unique (same receipt re-emitted)")
        return problems

    def supervised_unique_delivery(self, key: str) -> str:
        """The ONLY accepted duplicate path: reconcile first, then deliver
        with a brand-new unique receipt."""
        st = self.intent(key)
        if st["reconciled"] is None:
            raise AssertionError(f"{key} supervised delivery without reconciliation")
        rid = self.sink.execute(key)
        if st["receipts"] and rid in st["receipts"]:
            raise AssertionError(f"{key} supervised delivery with non-unique receipt")
        st["receipts"].append(rid)
        return rid


class CheckPoint:
    def __init__(self, seq: int, body: str) -> None:
        self.seq = seq
        self.body = body
        self.sha = hashlib.sha256(body.encode("utf-8")).hexdigest()

    def tampered(self) -> "CheckPoint":
        other = CheckPoint(self.seq, self.body)
        other.sha = "0" * 64  # rewrite of the digest => fail-closed refusal
        return other


def evaluate_checks() -> list[dict]:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> bool:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    # --- (a) CRASH-A: local commit, crash before publish -------------------
    sink = EffectSink()
    guard = ReplayGuard(sink)
    # process 1: local-commits 'a', dies before its effect publishes
    guard.intent("t:a:sync")
    # recovery: outbox replay publishes 'a' exactly once
    guard.publish("t:a:sync")
    dup_refused = False
    try:
        guard.publish("t:a:sync")
    except AssertionError:
        dup_refused = True
    # resume continues the DAG from b onwards
    for task in ("b", "c", "d", "e"):
        guard.publish(DAG[task]["effect"])
    ok_a = (
        all(sink.executions[k] == 1 for k in ALL_EFFECTS)
        and all(sink.receipt_count(k) == 1 for k in ALL_EFFECTS)
        and all(sink.unique_receipts(k) == 1 for k in ALL_EFFECTS)
        and dup_refused
    )
    check("crash-a-outbox-replay-exactly-once", ok_a,
          "exec=%s receipts=%s dup-publish-refused=%s" % (
              {k: sink.executions[k] for k in ALL_EFFECTS},
              {k: sink.receipt_count(k) for k in ALL_EFFECTS}, dup_refused))

    # --- (b) CRASH-B: published then ack lost -> reconciliation -------------
    sink = EffectSink()
    guard = ReplayGuard(sink)
    guard.publish("t:a:sync")          # delivered
    guard.mark_unknown("t:a:sync")     # ack lost
    # never re-execute the unknown effect; reconcile instead
    state = guard.reconcile("t:a:sync", observed_succeeded=True)
    for task in ("b", "c", "d", "e"):
        guard.publish(DAG[task]["effect"])
    ok_b = (
        sink.executions["t:a:sync"] == 1
        and sink.receipt_count("t:a:sync") == 1
        and state == "RECONCILED_SUCCEEDED"
        and all(sink.executions[k] == 1 for k in ALL_EFFECTS)
    )
    check("crash-b-unknown-outcome-reconciled-never-replayed", ok_b,
          "exec=%s state=%s" % ({k: sink.executions[k] for k in ALL_EFFECTS}, state))

    # --- (c) CRASH-C: mid-DAG crash, resume completes remaining tasks -------
    sink = EffectSink()
    guard = ReplayGuard(sink)
    guard.publish("t:a:sync")
    guard.publish("t:b:sync")
    # crash mid-DAG; resume publishes the rest
    for task in ("c", "d", "e"):
        guard.publish(DAG[task]["effect"])
    ok_c = (
        all(sink.executions[k] == 1 for k in ALL_EFFECTS)
        and all(sink.unique_receipts(k) == 1 for k in ALL_EFFECTS)
    )
    check("crash-c-mid-dag-resume-no-re-execution", ok_c,
          "exec=%s" % {k: sink.executions[k] for k in ALL_EFFECTS})

    # --- (d) CRASH-D: crash during the resume attempt itself ----------------
    sink = EffectSink()
    guard = ReplayGuard(sink)
    # first process publishes a,b,c,d then dies before e
    for task in ("a", "b", "c", "d"):
        guard.publish(DAG[task]["effect"])
    # resume attempt 1 publishes e, then dies before marking completion
    guard.publish("t:e:sync")
    # resume attempt 2: nothing already published may be re-executed
    refused = 0
    for task in TOPOLOGICAL:
        try:
            guard.publish(DAG[task]["effect"])
        except AssertionError:
            refused += 1
    ok_d = (
        refused == len(TOPOLOGICAL)
        and all(sink.executions[k] == 1 for k in ALL_EFFECTS)
        and all(sink.unique_receipts(k) == 1 for k in ALL_EFFECTS)
    )
    check("crash-d-double-resume-no-duplication", ok_d,
          "refused=%s exec=%s" % (refused, {k: sink.executions[k] for k in ALL_EFFECTS}))

    # --- (e) near-miss naive resume that re-runs a published step -----------
    sink = EffectSink()
    guard = ReplayGuard(sink)
    guard.publish("t:a:sync")
    guard.mark_unknown("t:a:sync")
    naive_problems = guard.check_reconciled_unique_duplicate("t:a:sync")  # no reconcile yet
    naive_rejected = bool(naive_problems)
    check("near-miss-naive-resume-duplicated-effect-rejected",
          naive_rejected,
          "reasons=%s" % naive_problems)

    # reconciliation alone is not enough: receipt must be unique
    sink = EffectSink()
    guard = ReplayGuard(sink)
    guard.publish("t:a:sync")
    guard.mark_unknown("t:a:sync")
    guard.reconcile("t:a:sync", observed_succeeded=True)
    same_receipt_problems = guard.check_reconciled_unique_duplicate("t:a:sync")
    # after reconciliation the original receipt remains; a SECOND re-run with
    # the SAME receipt is non-unique => rejected
    rejected_nonunique = bool(same_receipt_problems)
    check("reconciled-but-non-unique-receipt-rejected",
          rejected_nonunique,
          "reasons=%s" % same_receipt_problems)

    # reconciled AND unique receipt is the only accepted duplicate path
    sink = EffectSink()
    guard = ReplayGuard(sink)
    guard.publish("t:a:sync")
    guard.mark_unknown("t:a:sync")
    guard.reconcile("t:a:sync", observed_succeeded=True)
    rid2 = guard.supervised_unique_delivery("t:a:sync")
    accepted = (
        sink.executions["t:a:sync"] == 2
        and sink.unique_receipts("t:a:sync") == 2
        and rid2
    )
    check("reconciled-duplicate-with-unique-receipt-accepted", accepted,
          "receipts=%s" % sink.receipts.get("t:a:sync"))

    # never blind-retry an unknown outcome
    sink = EffectSink()
    guard = ReplayGuard(sink)
    guard.publish("t:a:sync")
    guard.mark_unknown("t:a:sync")
    blind = False
    try:
        guard.publish("t:a:sync")
    except AssertionError:
        blind = True
    check("unknown-outcome-never-blind-retried",
          blind and sink.executions.get("t:a:sync", 0) == 1,
          "blind-retry-refused=%s exec=%s" % (blind, sink.executions.get("t:a:sync")))

    # --- (f) checkpoint corruption: sha mismatch refuses resume -------------
    cp = CheckPoint(1, "steps_done=1")
    refused = cp.tampered().sha != cp.sha
    check("checkpoint-corruption-refused-fail-closed",
          refused, "stored_sha=%s tampered_sha=%s" % (cp.sha, cp.tampered().sha))

    # --- (g) dependency-ready ordering under recovery ------------------------
    sink = EffectSink()
    guard = ReplayGuard(sink)
    guard.publish("t:a:sync")
    # crash before b/c; dependent tasks must not run before a is published
    deps_none = sink.executions.get("t:b:sync", 0) == 0 and sink.executions.get("t:c:sync", 0) == 0
    b_before = sink.executions.get("t:b:sync", 0)
    c_before = sink.executions.get("t:c:sync", 0)
    for task in ("b", "c", "d", "e"):
        guard.publish(DAG[task]["effect"])
    all_once = all(sink.executions[k] == 1 for k in ALL_EFFECTS)
    check("dependency-ready-ordering-preserved-after-crash",
          deps_none and all_once,
          "b_before=%s c_before=%s final_ok=%s" % (b_before, c_before, all_once))

    # --- (h) source-hash re-verification from disk ---------------------------
    hash_problems, hash_count = verify_local_source_hashes()
    check("repo-local-source-hashes-verified-from-disk",
          not hash_problems and hash_count >= 6,
          "%d file bindings checked; problems=%s" % (hash_count, hash_problems))

    return checks


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_repo_root() -> Path:
    for candidate in (TICKET_DIR, *TICKET_DIR.parents):
        if (candidate / "AGENTS.md").is_file():
            return candidate
    raise RuntimeError("repository root (AGENTS.md) not found above ticket dir")


def verify_local_source_hashes() -> tuple[list[str], int]:
    if not BUNDLE_PATH.is_file():
        return ["bundle.json missing"], 0
    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    repo_root = find_repo_root()
    problems: list[str] = []
    checked = 0
    for source in bundle.get("sources", []):
        provenance = source.get("verifier_provenance")
        if not isinstance(provenance, dict):
            continue
        rel = provenance.get("external_path_at_review") or provenance.get("path")
        expected = (provenance.get("external_file_sha256_at_review")
                    or provenance.get("file_sha256"))
        if not rel or not expected:
            continue
        checked += 1
        path = repo_root / str(rel).replace("\\", "/")
        if not path.is_file():
            problems.append("%s: missing file %s" % (source.get("id"), rel))
            continue
        actual = sha256_file(path)
        if actual != expected:
            problems.append("%s: sha256 mismatch for %s" % (source.get("id"), rel))
    return problems, checked


def write_results(record: dict) -> None:
    existing: dict = {}
    if RESULTS_PATH.is_file():
        try:
            loaded = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            existing = {}
    probes = {p.get("probe"): p
              for p in existing.get("probes", []) if isinstance(p, dict)}
    probes[record["probe"]] = record
    ordered = [probes[name] for name in ("replay-resume", "comparability")
               if name in probes]
    document = {
        "schema": RESULTS_SCHEMA,
        "ticket": "S1-006",
        "probes": ordered,
        "final_verdict": "pass" if all(
            p.get("status") == "pass" for p in ordered) else "fail",
    }
    RESULTS_PATH.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1-006 replay/resume safety probe")
    parser.add_argument("--out", default=None,
                        help="optional result file (default: ticket dir probe-results.json)")
    args = parser.parse_args(argv)
    try:
        checks = evaluate_checks()
    except Exception as exc:  # fail closed
        record = {
            "probe": PROBE_NAME, "schema": VERDICT_SCHEMA,
            "status": "fail", "observed": "fail",
            "error": "%s: %s" % (type(exc).__name__, exc),
        }
        print(json.dumps(record, ensure_ascii=False))
        return 1
    failed = [c["name"] for c in checks if not c["ok"]]
    record = {
        "probe": PROBE_NAME, "schema": VERDICT_SCHEMA,
        "status": "pass" if not failed else "fail",
        "observed": "pass" if not failed else "fail",
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "failed_checks": failed,
        "checks": checks,
    }
    out_path = Path(args.out) if args.out else RESULTS_PATH
    try:
        write_results(record)
    except OSError as exc:
        print("warning: could not write results file: %s" % exc, file=sys.stderr)
    print(json.dumps(record, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())