"""S1-010 regression tests (TDD, offline, stdlib only).

Covers the mandatory regression areas from TASK_FOR_CLOUD_GLM.md:
corpus integrity, hash tampering, fail-closed behavior, probes A-F through the
production evaluator path, authority invariance, process separation, path
traversal, git-archive reproducibility, and synthetic-credential hygiene.

These tests never touch the network.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TICKET = REPO_ROOT / "research" / "tickets" / "stage-1" / "S1-010"
SRC_TICKET = TICKET  # alias for readability in helpers below

CORPUS = TICKET / "cases.json"
MANIFEST = TICKET / "corpus-manifest.json"
CONTRACT = TICKET / "tool-poisoning-contract.json"
RUBRIC = TICKET / "rubric.json"

BLOCKED = {"DENY", "QUARANTINE", "HUMAN_REVIEW", "UNSUPPORTED"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_evaluator(out_dir: Path, executor: str, nonce: str,
                  ticket_root: Path | None = None,
                  corpus: Path | None = None) -> tuple[int, dict]:
    """Run the production evaluator subprocess; return (exit, parsed stdout)."""
    cmd = [
        sys.executable, str((ticket_root or TICKET) / "evaluator.py"),
        "--corpus", str(corpus or CORPUS),
        "--out", str(out_dir),
        "--executor", executor,
        "--nonce", nonce,
    ]
    if ticket_root is not None:
        cmd += ["--ticket-root", str(ticket_root)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                          cwd=str(REPO_ROOT))
    payload = {}
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout.strip().splitlines()[-1])
        except json.JSONDecodeError:
            payload = {}
    return proc.returncode, payload


def run_single_run(out_dir: Path, executor: str, nonce: str,
                   ticket_root: Path | None = None) -> tuple[int, dict]:
    cmd = [
        sys.executable, str((ticket_root or TICKET) / "runner.py"),
        "--single", "--out", str(out_dir),
        "--executor", executor, "--nonce", nonce,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                          cwd=str(REPO_ROOT))
    payload = {}
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout.strip().splitlines()[-1])
        except json.JSONDecodeError:
            payload = {}
    return proc.returncode, payload


def load_decisions(out_dir: Path) -> dict:
    return load(out_dir / "evaluator-decisions.json")


def copy_ticket(tmp: Path) -> Path:
    """Copy the frozen ticket inputs (not results/) to a tamper sandbox."""
    dest = tmp / "ticket"
    shutil.copytree(TICKET, dest,
                    ignore=shutil.ignore_patterns("results", "__pycache__"))
    return dest


def probe_cases(cases: list[dict], letter: str) -> list[dict]:
    return [c for c in cases if f"probe-{letter}" in c["subtype"]]


class S1010CorpusIntegrity(unittest.TestCase):
    """The frozen corpus itself must be complete and hash-valid."""

    def test_01_exact_corpus_present_and_hash_valid(self):
        manifest = load(MANIFEST)
        cases = load(CORPUS)
        self.assertEqual(manifest["case_count"], len(cases))
        self.assertGreaterEqual(len(cases), 48)
        for cls, minimum in manifest.get("class_counts", {}).items():
            pass  # class_counts is informational; floor checks below
        counts: dict[str, int] = {}
        for c in cases:
            counts[c["class"]] = counts.get(c["class"], 0) + 1
        for cls in ("benign", "malicious_manifest", "malicious_output",
                    "near_miss"):
            self.assertGreaterEqual(counts.get(cls, 0), 12, cls)
        self.assertEqual(manifest["cases_sha256"], sha256_file(CORPUS))
        for c in cases:
            stripped = {k: v for k, v in c.items() if k != "case_sha256"}
            h = hashlib.sha256(json.dumps(
                stripped, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False).encode("utf-8")).hexdigest()
            self.assertEqual(h, c["case_sha256"], c["id"])

    def test_02_frozen_input_hashes_match(self):
        manifest = load(MANIFEST)
        for name, recorded in manifest["frozen_input_hashes"].items():
            self.assertEqual(recorded, sha256_file(TICKET / name), name)

    def test_03_probes_present(self):
        manifest = load(MANIFEST)
        for letter in ("A", "B", "C", "D", "E", "F"):
            self.assertTrue(probe_cases(load(CORPUS), letter),
                            f"probe {letter} missing")


class S1010ProductionPath(unittest.TestCase):
    """One production evaluator run shared by read-only assertions."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="s1-010-tests-"))
        rc, summary = run_evaluator(cls.tmp / "out", "verifier-test", "nonce-test")
        cls.rc = rc
        cls.summary = summary
        cls.decisions = load_decisions(cls.tmp / "out")
        cls.cases = {c["id"]: c for c in load(CORPUS)}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def decisions_by_id(self) -> dict:
        return {d["case_id"]: d for d in self.decisions["decisions"]}

    def test_10_evaluator_accepts_frozen_corpus(self):
        self.assertEqual(self.rc, 0, self.summary)
        self.assertEqual(self.summary["verdict"], "PASS")
        self.assertEqual(self.summary["case_count"], 56)
        self.assertEqual(
            self.summary["cases_sha256"], sha256_file(CORPUS))

    def test_11_every_case_exactly_once_no_duplicates(self):
        ids = [d["case_id"] for d in self.decisions["decisions"]]
        self.assertEqual(len(ids), 56)
        self.assertEqual(len(set(ids)), 56)
        self.assertEqual(set(ids), set(self.cases.keys()))

    def test_12_producer_expectations_do_not_control_decisions(self):
        """Flipping the oracle must not change decisions (decider independence)."""
        sys.path.insert(0, str(TICKET))
        try:
            import evaluator as ev
            malicious = self.cases["s1-010-mo-002"]
            record = ev.decide(malicious, ev.load_contract())
            tampered = json.loads(json.dumps(malicious))
            tampered["expected_decision"] = "ALLOW"
            record2 = ev.decide(tampered, ev.load_contract())
            self.assertEqual(record["decision"], record2["decision"])
            self.assertNotEqual(record2["decision"], "ALLOW")
        finally:
            sys.path.pop(0)

    # ---- probes A-F through the production path ----
    def assertBlocked(self, cid: str):
        d = self.decisions_by_id()[cid]
        self.assertIn(d["decision"], BLOCKED, f"{cid}: {d['decision']}")

    def test_20_probe_a_benign_unusual_not_silently_denied(self):
        for c in probe_cases(list(self.cases.values()), "A"):
            d = self.decisions_by_id()[c["id"]]
            self.assertNotIn("SI-DENY", d["reason_codes"])
            if c["expected_decision"] == "ALLOW":
                self.assertEqual(d["decision"], "ALLOW", c["id"])

    def test_21_probe_b_valid_manifest_poisoned_output_blocked(self):
        for c in probe_cases(list(self.cases.values()), "B"):
            self.assertBlocked(c["id"])
            d = self.decisions_by_id()[c["id"]]
            self.assertTrue(any(r.startswith("OD-") for r in d["reason_codes"]),
                            d["reason_codes"])

    def test_22_probe_c_capability_drift_detected(self):
        for c in probe_cases(list(self.cases.values()), "C"):
            self.assertBlocked(c["id"])
            d = self.decisions_by_id()[c["id"]]
            self.assertTrue(any(r.startswith("CD-") for r in d["reason_codes"]),
                            d["reason_codes"])

    def test_23_probe_d_obfuscated_poison_never_expands_authority(self):
        for c in probe_cases(list(self.cases.values()), "D"):
            d = self.decisions_by_id()[c["id"]]
            self.assertIn(d["decision"], BLOCKED, c["id"])
            self.assertEqual(d["authority_mutations"], [])

    def test_24_probe_e_governance_claims_inert(self):
        for c in probe_cases(list(self.cases.values()), "E"):
            d = self.decisions_by_id()[c["id"]]
            self.assertIn(d["decision"], BLOCKED, c["id"])
            self.assertTrue(any(r.startswith("GOV-") for r in d["reason_codes"]),
                            d["reason_codes"])
            self.assertEqual(d["authority_mutations"], [])

    def test_25_probe_f_degradation_fails_closed(self):
        for c in probe_cases(list(self.cases.values()), "F"):
            d = self.decisions_by_id()[c["id"]]
            self.assertIn(d["decision"], BLOCKED, c["id"])
            self.assertTrue(any(r.startswith("DD-") for r in d["reason_codes"]),
                            d["reason_codes"])

    # ---- metrics and hard gates ----
    def test_30_hard_gates_zero_escapes_zero_expansions(self):
        m = self.decisions["metrics"]
        self.assertEqual(m["critical_escape_count"], 0)
        for key in ("capability", "policy", "approval", "budget", "knowledge",
                    "acceptance"):
            self.assertEqual(m["authority_expansions"][key], 0, key)
        self.assertEqual(m["decision_mismatch_count"], 0)

    def test_31_confusion_matrix_and_derived_metrics(self):
        m = self.decisions["metrics"]
        cm = m["confusion_matrix_overall"]
        self.assertEqual(cm["tp"] + cm["fn"] + cm["fp"] + cm["tn"], 56)
        for cls, mm in m["per_class"].items():
            self.assertIn("precision", mm)
            self.assertIn("wilson", mm)
        self.assertGreaterEqual(m["per_class"]["malicious_manifest"]["recall"],
                                0.9)
        self.assertGreaterEqual(m["per_class"]["malicious_output"]["recall"],
                                0.9)
        self.assertLessEqual(m["benign_false_positive_rate"], 0.25)

    def test_32_abstention_counts_present(self):
        m = self.decisions["metrics"]
        for key in ("abstention_count", "quarantine_count", "human_review_count",
                    "malformed_count", "unknown_count", "timeout_count",
                    "scanner_disagreement_count"):
            self.assertIsInstance(m[key], int, key)

    def test_33_critical_false_negative_forces_fail(self):
        """A synthetic critical escape in raw records must flip verdict to FAIL."""
        sys.path.insert(0, str(TICKET))
        try:
            import evaluator as ev
            records = [dict(d) for d in self.decisions["decisions"]]
            victim = None
            for r in records:
                if self.cases[r["case_id"]]["critical"] and \
                        self.cases[r["case_id"]]["truth"] == "malicious":
                    victim = dict(r)
                    break
            assert victim is not None
            for r in records:
                if r["case_id"] == victim["case_id"]:
                    r["decision"] = "ALLOW"
            metrics = ev.grade(records, load(CORPUS), load(RUBRIC))
            verdict = ev.evaluate_hard_gates(records, metrics, load(RUBRIC))
            self.assertNotEqual(verdict["verdict"], "PASS")
            self.assertTrue(verdict["violations"])
        finally:
            sys.path.pop(0)

    def test_34_benign_false_positive_measured_and_visible(self):
        """Injecting a benign DENY must surface in recomputed metrics."""
        sys.path.insert(0, str(TICKET))
        try:
            import evaluator as ev
            records = [dict(d) for d in self.decisions["decisions"]]
            for r in records:
                if self.cases[r["case_id"]]["truth"] == "benign":
                    r["decision"] = "DENY"
                    break
            metrics = ev.grade(records, [self.cases[r["case_id"]] for r in records],
                               load(RUBRIC))
            self.assertGreaterEqual(metrics["benign_false_positive_rate"], 0)
            self.assertGreater(metrics["confusion_matrix_overall"]["fp"], 0)
        finally:
            sys.path.pop(0)

    # ---- authority invariants ----
    def test_40_capability_and_escalation_never_pass(self):
        for cid in ("s1-010-mm-009", "s1-010-mm-010", "s1-010-nm-005"):
            self.assertBlocked(cid)

    def test_41_governance_injections_inert(self):
        for cid in ("s1-010-mm-014", "s1-010-mo-005", "s1-010-mo-006",
                    "s1-010-mo-007", "s1-010-mo-008", "s1-010-mo-009"):
            d = self.decisions_by_id()[cid]
            self.assertIn(d["decision"], BLOCKED, cid)
            self.assertEqual(d["authority_mutations"], [])

    def test_42_alternate_correct_accepted(self):
        for cid in ("s1-010-bc-012", "s1-010-nm-006", "s1-010-nm-013"):
            d = self.decisions_by_id()[cid]
            self.assertEqual(d["decision"], "ALLOW", cid)

    def test_43_unknown_or_ambiguous_routes_to_quarantine_or_review(self):
        for cid in ("s1-010-nm-014", "s1-010-nm-008"):
            d = self.decisions_by_id()[cid]
            self.assertIn(d["decision"], {"QUARANTINE", "HUMAN_REVIEW"}, cid)

    def test_44_expected_decision_comes_from_oracle_only(self):
        """Producer decision records must not carry their own expectations."""
        for d in self.decisions["decisions"]:
            self.assertNotIn("expected_decision", d)


class S1010TamperRejection(unittest.TestCase):
    """Tampered frozen inputs must be rejected fail-closed (exit != 0)."""

    def tamper_eval(self, mutate) -> int:
        with tempfile.TemporaryDirectory(prefix="s1-010-tamper-") as tmp:
            root = copy_ticket(Path(tmp))
            mutate(root)
            out = Path(tmp) / "out"
            rc, _ = run_evaluator(out, "verifier-tamper", "nonce-tamper",
                                  ticket_root=root)
            return rc

    def test_50_case_tamper_rejected(self):
        def mutate(root: Path):
            cases = load(root / "cases.json")
            cases[0]["severity"] = "critical"
            (root / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        self.assertNotEqual(self.tamper_eval(mutate), 0)

    def test_51_manifest_case_hash_tamper_rejected(self):
        def mutate(root: Path):
            m = load(root / "corpus-manifest.json")
            first = next(iter(m["per_case_sha256"]))
            m["per_case_sha256"][first] = "0" * 64
            (root / "corpus-manifest.json").write_text(
                json.dumps(m), encoding="utf-8")
        self.assertNotEqual(self.tamper_eval(mutate), 0)

    def test_52_contract_tamper_rejected(self):
        def mutate(root: Path):
            data = json.loads((root / "tool-poisoning-contract.json")
                              .read_text(encoding="utf-8"))
            data["decision_enum"].append("MAYBE")
            (root / "tool-poisoning-contract.json").write_text(
                json.dumps(data), encoding="utf-8")
        self.assertNotEqual(self.tamper_eval(mutate), 0)

    def test_53_rubric_tamper_rejected(self):
        def mutate(root: Path):
            data = json.loads((root / "rubric.json").read_text(encoding="utf-8"))
            data["hard_gates"]["critical_escape_max"] = 1
            (root / "rubric.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertNotEqual(self.tamper_eval(mutate), 0)

    def test_54_source_snapshot_tamper_rejected(self):
        def mutate(root: Path):
            snap = root / "snapshots" / "slsa-v1.1-spec.html"
            snap.write_bytes(snap.read_bytes() + b"tampered\n")
        self.assertNotEqual(self.tamper_eval(mutate), 0)

    def test_55_missing_case_rejected(self):
        def mutate(root: Path):
            cases = load(root / "cases.json")
            cases.pop()
            (root / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        self.assertNotEqual(self.tamper_eval(mutate), 0)

    def test_56_extra_case_rejected(self):
        def mutate(root: Path):
            cases = load(root / "cases.json")
            extra = json.loads(json.dumps(cases[0]))
            extra["id"] = "s1-010-bc-099"
            cases.append(extra)
            (root / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        self.assertNotEqual(self.tamper_eval(mutate), 0)

    def test_57_duplicate_case_rejected(self):
        def mutate(root: Path):
            cases = load(root / "cases.json")
            cases.append(json.loads(json.dumps(cases[0])))
            (root / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        self.assertNotEqual(self.tamper_eval(mutate), 0)

    def test_58_producer_supplied_expectations_rejected(self):
        """A case that carries a producer-decided outcome cannot self-certify."""
        sys.path.insert(0, str(TICKET))
        try:
            import evaluator as ev
            case = load(CORPUS)[0]
            self.assertIn("expected_decision", case)
            contract = ev.load_contract()
            record = ev.decide(case, contract)
            tampered = dict(case, producer_decision="ALLOW",
                            expected_decision="ALLOW")
            record2 = ev.decide(tampered, contract)
            self.assertEqual(record["decision"], record2["decision"])
            with self.assertRaises((KeyError, ValueError)):
                ev.load_case_expectations(record)
        finally:
            sys.path.pop(0)


class S1010ProvenanceAndSeparation(unittest.TestCase):

    def test_60_dirty_tree_rejected_by_runner(self):
        marker = REPO_ROOT / "untracked-s1-010-probe.tmp"
        marker.write_text("dirty\n", encoding="utf-8")
        try:
            with tempfile.TemporaryDirectory(prefix="s1-010-dirty-") as tmp:
                cmd = [sys.executable, str(TICKET / "runner.py"),
                       "--single", "--out", str(Path(tmp) / "out"),
                       "--executor", "verifier-dirty", "--nonce", "n-dirty"]
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=600, cwd=str(REPO_ROOT))
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("dirty", (proc.stderr + proc.stdout).lower())
        finally:
            marker.unlink(missing_ok=True)

    def test_61_runs_are_process_separated_with_distinct_identity(self):
        with tempfile.TemporaryDirectory(prefix="s1-010-sep-") as tmp:
            tmp_path = Path(tmp)
            rc_a, sum_a = run_single_run(tmp_path / "run-a", "verifier-sep-a",
                                         "nonce-a")
            rc_b, sum_b = run_single_run(tmp_path / "run-b", "verifier-sep-b",
                                         "nonce-b")
            self.assertEqual(rc_a, 0)
            self.assertEqual(rc_b, 0)
            prov_a = sum_a["process_provenance"]
            prov_b = sum_b["process_provenance"]
            self.assertNotEqual(prov_a["evaluator_pid"], prov_b["evaluator_pid"])
            self.assertNotEqual(sum_a["executor_id"], sum_b["executor_id"])
            self.assertNotEqual(sum_a["nonce"], sum_b["nonce"])
            self.assertNotEqual(sum_a["output_root"], sum_b["output_root"])
            self.assertEqual(prov_a["commit_sha"], prov_b["commit_sha"])
            self.assertEqual(prov_a["tree_sha"], prov_b["tree_sha"])
            self.assertEqual(sum_a["decisions_sha256"],
                             sum_b["decisions_sha256"])
            self.assertNotEqual(sum_a["invocation_digest"],
                                sum_b["invocation_digest"])

    def test_62_mixed_commits_rejected_by_comparison(self):
        sys.path.insert(0, str(TICKET))
        try:
            import runner as rn
            base = {
                "commit_sha": "a" * 40, "tree_sha": "b" * 40,
                "executor_id": "A", "nonce": "na",
                "output_root": "results/run-a", "evaluator_sha256": "c" * 64,
                "runner_sha256": "d" * 64, "cases_sha256": "e" * 64,
                "contract_sha256": "f" * 64, "rubric_sha256": "0" * 64,
                "decision_count": 56, "decision_digest": "1" * 64,
                "reason_digest": "2" * 64, "pid": 1,
            }
            run_a = dict(base)
            run_b = dict(base, executor_id="B", nonce="nb",
                         output_root="results/run-b", pid=2)
            ok = rn.compare_runs(run_a, run_b)
            self.assertTrue(ok["identical"], ok)
            mixed = dict(run_b, commit_sha="9" * 40)
            bad = rn.compare_runs(run_a, mixed)
            self.assertFalse(bad["identical"])
            self.assertTrue(bad["violations"])
        finally:
            sys.path.pop(0)

    def test_63_reused_process_identity_rejected(self):
        sys.path.insert(0, str(TICKET))
        try:
            import runner as rn
            base = {
                "commit_sha": "a" * 40, "tree_sha": "b" * 40,
                "executor_id": "A", "nonce": "same",
                "output_root": "results/run-a", "evaluator_sha256": "c" * 64,
                "runner_sha256": "d" * 64, "cases_sha256": "e" * 64,
                "contract_sha256": "f" * 64, "rubric_sha256": "0" * 64,
                "decision_count": 56, "decision_digest": "1" * 64,
                "reason_digest": "2" * 64, "pid": 1,
            }
            clone = dict(base, output_root="results/run-b")
            bad = rn.compare_runs(base, clone)
            self.assertFalse(bad["identical"])
        finally:
            sys.path.pop(0)

    def test_64_path_traversal_and_absolute_paths_rejected(self):
        sys.path.insert(0, str(TICKET))
        try:
            import evaluator as ev
            for bad in ("../outside.json", "/etc/passwd",
                        "research/../../etc/passwd", "C:/Windows/temp"):
                with self.assertRaises((ValueError, RuntimeError)):
                    ev.safe_repo_relative(bad)
        finally:
            sys.path.pop(0)


class S1010ReproducibilityAndHygiene(unittest.TestCase):

    def ticket_paths_in_head(self) -> bool:
        proc = subprocess.run(
            ["git", "ls-files", "research/tickets/stage-1/S1-010/cases.json"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
        return bool(proc.stdout.strip())

    def test_70_git_archive_reproducibility(self):
        if not self.ticket_paths_in_head():
            self.skipTest("S1-010 artifacts not committed yet; "
                          "archive check runs after commit")
        proc = subprocess.run(["git", "archive", "HEAD"], cwd=str(REPO_ROOT),
                              capture_output=True, check=True, timeout=300)
        with tempfile.TemporaryDirectory(prefix="s1-010-archive-") as tmp:
            tar_path = Path(tmp) / "archive.tar"
            tar_path.write_bytes(proc.stdout)
            subprocess.run(["tar", "xf", str(tar_path), "-C", tmp], check=True)
            extracted = Path(tmp)
            for name in ("cases.json", "corpus-manifest.json",
                         "tool-poisoning-contract.json", "rubric.json",
                         "threat-model.json", "source-registry.json",
                         "evaluator.py", "runner.py"):
                tracked = TICKET / name
                archived = extracted / "research/tickets/stage-1/S1-010" / name
                self.assertTrue(archived.is_file(), name)
                self.assertEqual(sha256_file(tracked), sha256_file(archived),
                                 name)

    def test_71_tracked_artifact_hashes_recorded(self):
        candidate = TICKET / "candidate-record.json"
        if not candidate.is_file():
            self.skipTest("candidate-record.json not generated yet")
        record = load(candidate)
        for rel, recorded in record["tracked_artifact_hashes"].items():
            path = REPO_ROOT / rel
            self.assertTrue(path.is_file(), rel)
            self.assertEqual(recorded, sha256_file(path), rel)

    def test_72_no_real_credentials_in_tracked_artifacts(self):
        secret_patterns = [
            re.compile(r"sk-[A-Za-z0-9]{20,}"),
            re.compile(r"AKIA[0-9A-Z]{16}"),
            re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
            re.compile(r"ghp_[A-Za-z0-9]{30,}"),
            re.compile(r"xoxb-[0-9A-Za-z-]{20,}"),
        ]
        for path in TICKET.rglob("*.json"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in secret_patterns:
                self.assertIsNone(pattern.search(text),
                                  f"real-looking secret in {path.name}")
        self.assertIn("S1-010-SYNTHETIC-SECRET-MARKER",
                      CORPUS.read_text(encoding="utf-8"))

    def test_73_tests_and_evaluation_are_offline(self):
        for name in ("evaluator.py", "runner.py"):
            text = (TICKET / name).read_text(encoding="utf-8")
            for banned in ("urllib.request", "requests.", "http.client",
                           "socket.create_connection", "urlopen"):
                self.assertNotIn(banned, text, f"{name}:{banned}")


if __name__ == "__main__":
    unittest.main()
