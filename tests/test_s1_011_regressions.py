"""S1-011 regression suite (Phase A).

Covers TASK_FOR_OPENCODE.md section 15. Stdlib only, no network/LLM.
Run: $env:PYTHONPATH="src"; py -3.12 -m unittest tests.test_s1_011_regressions -v

Conventions mirror tests/test_s1_003_regressions.py: ticket modules are
imported via sys.path from research/tickets/stage-1/S1-011/.
"""
import ast
import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S1011 = ROOT / "research" / "tickets" / "stage-1" / "S1-011"
sys.path.insert(0, str(S1011))

import canonicalize_corpus
import evaluator
import runner


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(name: str):
    return json.loads((S1011 / name).read_text(encoding="utf-8"))


def run_design(design: str, seed: int = 11011):
    corpus = load("cases.json")
    decide = runner.DECIDE[design]
    return [decide(runner.Case(raw), seed) for raw in corpus["cases"]]


def rows_by_id(rows):
    return {r["case_id"]: r for r in rows}


class TestMatrixExactness(unittest.TestCase):
    def test_complete_matrix_shape(self):
        manifest = load("corpus-manifest.json")
        corpus = load("cases.json")
        self.assertEqual(len(corpus["cases"]), 60)
        self.assertEqual(manifest["matrix"]["rows_per_run"], 540)
        self.assertEqual(manifest["matrix"]["cases"], 60)
        self.assertEqual(len(manifest["matrix"]["designs"]), 3)
        self.assertEqual(len(manifest["seeds"]), 3)

    def test_class_minimums(self):
        corpus = load("cases.json")
        counts = {}
        for case in corpus["cases"]:
            counts[case["class"]] = counts.get(case["class"], 0) + 1
        for cls in ("valid_promotion", "insufficient_evidence",
                    "challenge_retraction", "replay_concurrency",
                    "adversarial_authority"):
            self.assertGreaterEqual(counts.get(cls, 0), 12, cls)

    def test_missing_case_rejected(self):
        corpus = load("cases.json")
        rows = run_design("minimal-gate")
        short = [r for r in rows if r["case_id"] != "S1-011-V01"]
        problems, _ = evaluator.check_rows(short, corpus)
        self.assertTrue(any("missing case S1-011-V01" in p for p in problems))

    def test_extra_case_rejected(self):
        corpus = load("cases.json")
        rows = run_design("minimal-gate")
        extra = dict(rows[0])
        extra["case_id"] = "S1-011-XX"
        problems, _ = evaluator.check_rows(rows + [extra], corpus)
        self.assertTrue(any("extra case" in p for p in problems))

    def test_duplicate_case_rejected(self):
        corpus = load("cases.json")
        rows = run_design("minimal-gate")
        problems, _ = evaluator.check_rows(rows + [dict(rows[0])], corpus)
        self.assertTrue(any("duplicate case" in p for p in problems))

    def test_empty_observations_rejected(self):
        corpus = load("cases.json")
        problems, _ = evaluator.check_rows([], corpus)
        self.assertTrue(any("empty observations" in p for p in problems))

    def test_row_hash_mismatch_rejected(self):
        corpus = load("cases.json")
        rows = run_design("minimal-gate")
        tampered = [dict(r) for r in rows]
        idx = next(i for i, r in enumerate(tampered)
                   if r["decision"] != "PROMOTED")
        tampered[idx]["decision"] = "PROMOTED"
        problems, _ = evaluator.check_rows(tampered, corpus)
        self.assertTrue(any("hash mismatch" in p for p in problems))

    def test_unknown_decision_rejected(self):
        corpus = load("cases.json")
        rows = run_design("minimal-gate")
        bad = [dict(r) for r in rows]
        bad[5] = dict(bad[5])
        bad[5]["decision"] = "MAYBE"
        bad[5].pop("output_sha256")
        bad[5]["output_sha256"] = sha(evaluator.canonical(
            {k: v for k, v in bad[5].items() if k != "output_sha256"}))
        problems, _ = evaluator.check_rows(bad, corpus)
        self.assertTrue(any("unknown decision" in p for p in problems))

    def test_unknown_transition_rejected(self):
        corpus = load("cases.json")
        rows = run_design("minimal-gate")
        bad = [dict(r) for r in rows]
        bad[5] = dict(bad[5])
        bad[5]["transition"] = "teleport"
        bad[5].pop("output_sha256")
        bad[5]["output_sha256"] = sha(evaluator.canonical(
            {k: v for k, v in bad[5].items() if k != "output_sha256"}))
        problems, _ = evaluator.check_rows(bad, corpus)
        self.assertTrue(any("unknown transition" in p for p in problems))

    def test_unknown_reason_rejected_by_evaluate(self):
        import tempfile
        corpus = load("cases.json")
        rows = run_design("minimal-gate")
        bad = [dict(r) for r in rows]
        bad[0] = dict(bad[0])
        bad[0]["reason_code"] = "BECAUSE_REASONS"
        bad[0].pop("output_sha256")
        bad[0]["output_sha256"] = sha(evaluator.canonical(
            {k: v for k, v in bad[0].items() if k != "output_sha256"}))
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "raw-observations.json").write_text(json.dumps(
                {"schema": "x", "design": "minimal-gate", "seed": 1,
                 "rows": bad}), encoding="utf-8")
            metrics = evaluator.evaluate(run_dir)
        self.assertFalse(metrics["admissible"])
        self.assertTrue(any("unknown reason" in p
                            for p in metrics["problems"]))

    def test_nan_seed_rejected(self):
        corpus = load("cases.json")
        rows = run_design("minimal-gate")
        bad = [dict(r) for r in rows]
        bad[0] = dict(bad[0])
        bad[0]["seed"] = float("nan")
        bad[0].pop("output_sha256")
        raw = json.dumps({k: v for k, v in bad[0].items()
                          if k != "output_sha256"},
                         allow_nan=True, sort_keys=True,
                         separators=(",", ":"))
        bad[0]["output_sha256"] = sha(raw.encode())
        problems, _ = evaluator.check_rows(bad, corpus)
        self.assertTrue(any("NaN/Infinity" in p or "seed not int" in p
                            for p in problems))


class TestCorpusFrozen(unittest.TestCase):
    def test_canonicalizer_check_passes(self):
        self.assertEqual(canonicalize_corpus.check(), 0)

    def test_tampered_case_detected(self):
        frozen = load("cases.json")
        tampered = copy.deepcopy(frozen["cases"][0])
        self.assertEqual(tampered["expected"]["decision"], "PROMOTED")
        tampered["expected"]["decision"] = "REJECTED"
        body = {k: v for k, v in tampered.items() if k != "case_sha256"}
        self.assertNotEqual(
            sha(evaluator.canonical(body)), tampered["case_sha256"])

    def test_manifest_hashes_match_disk(self):
        manifest = load("corpus-manifest.json")
        for name, pinned in manifest["hashes"].items():
            data = (S1011 / name).read_bytes()
            self.assertEqual(sha(data), pinned, name)
        self.assertTrue(manifest["runner_hash"])
        self.assertTrue(manifest["evaluator_hash"])
        self.assertEqual(manifest["runner_hash"],
                         sha((S1011 / "runner.py").read_bytes()))
        self.assertEqual(manifest["evaluator_hash"],
                         sha((S1011 / "evaluator.py").read_bytes()))
        self.assertIn("compare_runs.py", manifest["hashes"])
        self.assertEqual(manifest["hashes"]["compare_runs.py"],
                         sha((S1011 / "compare_runs.py").read_bytes()))

    def test_expected_outcomes_host_owned(self):
        for src in ("cases-a.src.json", "cases-b.src.json"):
            doc = load(src)
            for case in doc["cases"]:
                self.assertIn("expected", case)
                self.assertIn(case["expected"]["decision"],
                              evaluator.DECISIONS)


class TestMinimalAcceptsOracle(unittest.TestCase):
    def test_minimal_matches_oracle_all_cases(self):
        corpus = load("cases.json")
        by_id = rows_by_id(run_design("minimal-gate"))
        mismatches = []
        for case in corpus["cases"]:
            row = by_id[case["case_id"]]
            exp = case["expected"]
            if (row["decision"], row["transition"], row["reason_code"],
                    row["view_visible"], row["audit_events"]) != (
                    exp["decision"], exp["transition"], exp["reason_code"],
                    exp["view_visible"], exp["audit"]):
                mismatches.append(case["case_id"])
        self.assertEqual(mismatches, [])

    def test_minimal_metrics_pass(self):
        import tempfile
        rows = run_design("minimal-gate")
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "raw-observations.json").write_text(json.dumps(
                {"schema": "x", "design": "minimal-gate", "seed": 11011,
                 "rows": rows}), encoding="utf-8")
            metrics = evaluator.evaluate(run_dir)
            probe_doc = evaluator.probes(run_dir)
        self.assertTrue(metrics["admissible"])
        self.assertEqual(metrics["verdict"], "PASS")
        self.assertTrue(all(v == 0 for v in
                            metrics["hard_counters"].values()))
        self.assertTrue(probe_doc["all_pass"])


class TestProbesRealPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.min_rows = rows_by_id(run_design("minimal-gate"))
        cls.arg_rows = rows_by_id(run_design("argumentation"))
        cls.tms_rows = rows_by_id(run_design("tms"))

    def test_probe_a_single_source_no_promote(self):
        for cid in ("S1-011-I02", "S1-011-I03"):
            row = self.min_rows[cid]
            self.assertEqual(row["decision"], "REJECTED")
            self.assertEqual(row["reason_code"], "EVIDENCE_CORRELATED")
            self.assertFalse(row["view_visible"])
        # naive alternatives accept correlated support: recorded honestly
        self.assertEqual(self.arg_rows["S1-011-I02"]["decision"], "PROMOTED")
        self.assertEqual(self.tms_rows["S1-011-I02"]["decision"], "PROMOTED")

    def test_probe_b_invalidation_preserves_history(self):
        for cid in ("S1-011-C01", "S1-011-C02", "S1-011-C09"):
            row = self.min_rows[cid]
            self.assertIn(row["decision"], ("CHALLENGED", "RETRACTED"))
            self.assertFalse(row["view_visible"])
            self.assertTrue(row["history_preserved"])
            self.assertTrue(row["audit_events"])

    def test_probe_c_external_quarantined(self):
        for cid in ("S1-011-A01", "S1-011-A02", "S1-011-A03",
                    "S1-011-A09"):
            for rows in (self.min_rows, self.arg_rows, self.tms_rows):
                row = rows[cid]
                self.assertEqual(row["decision"], "QUARANTINED", cid)
                self.assertIsNone(row["transition"])
                self.assertEqual(row["reason_code"],
                                 "EXTERNAL_CONTENT_QUARANTINED")

    def test_probe_d_sybil_no_promote(self):
        for cid in ("S1-011-I08", "S1-011-I09"):
            row = self.min_rows[cid]
            self.assertEqual(row["decision"], "REJECTED")
            self.assertFalse(row["view_visible"])

    def test_probe_e_stale_replay_rejected(self):
        for cid in ("S1-011-R01", "S1-011-R02", "S1-011-R03",
                    "S1-011-R10"):
            row = self.min_rows[cid]
            self.assertEqual(row["decision"], "NO_TRANSITION")
            self.assertEqual(row["reason_code"], "REPLAY_REJECTED")
            self.assertFalse(row["view_visible"])

    def test_probe_f_cache_resurrection_closed(self):
        row = self.min_rows["S1-011-R04"]
        self.assertEqual(row["decision"], "HIDDEN")
        self.assertEqual(row["reason_code"], "STALE_EPOCH")
        self.assertFalse(row["view_visible"])

    def test_probe_g_no_transitive_promotion(self):
        for cid in ("S1-011-R05", "S1-011-A08"):
            row = self.min_rows[cid]
            self.assertEqual(row["decision"], "NOT_PROMOTED")
            self.assertFalse(row["view_visible"])
        self.assertEqual(self.arg_rows["S1-011-R05"]["decision"], "PROMOTED")
        self.assertEqual(self.tms_rows["S1-011-A08"]["decision"], "PROMOTED")

    def test_probe_h_concurrency_single_decision(self):
        row = self.min_rows["S1-011-R07"]
        self.assertEqual(row["decision"], "CHALLENGED")
        self.assertEqual(row["reason_code"], "CONCURRENT_RESOLVED")
        row = self.min_rows["S1-011-R09"]
        self.assertEqual(row["decision"], "PROMOTED")
        self.assertEqual(row["audit_events"], ["PROMOTE"])
        row = self.min_rows["S1-011-R08"]
        self.assertEqual(row["reason_code"], "DUPLICATE_IDEMPOTENT")


class TestInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.min_rows = rows_by_id(run_design("minimal-gate"))

    def test_single_evidence_never_promotes(self):
        for cid in ("S1-011-I01", "S1-011-I05", "S1-011-C10"):
            self.assertNotEqual(self.min_rows[cid]["decision"], "PROMOTED")

    def test_worker_cannot_promote_or_uphold(self):
        for cid in ("S1-011-I12", "S1-011-A04", "S1-011-A05"):
            row = self.min_rows[cid]
            self.assertEqual(row["decision"], "NO_TRANSITION")
            self.assertEqual(row["reason_code"], "AUTHORITY_DENIED")

    def test_unknown_transition_no_default_pass(self):
        for cid in ("S1-011-A12", "S1-011-C12"):
            row = self.min_rows[cid]
            self.assertEqual(row["decision"], "NO_TRANSITION")
            self.assertEqual(row["reason_code"], "UNKNOWN_TRANSITION")
            self.assertFalse(row["view_visible"])

    def test_version_pinning_exact(self):
        for cid in ("S1-011-I05", "S1-011-I11", "S1-011-A11"):
            self.assertNotEqual(self.min_rows[cid]["decision"], "PROMOTED")

    def test_challenge_removes_from_view(self):
        for cid in ("S1-011-C01", "S1-011-C02", "S1-011-R07"):
            self.assertFalse(self.min_rows[cid]["view_visible"])

    def test_derived_without_evidence_counter(self):
        import tempfile
        rows = run_design("argumentation")
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "raw-observations.json").write_text(json.dumps(
                {"schema": "x", "design": "argumentation", "seed": 1,
                 "rows": rows}), encoding="utf-8")
            metrics = evaluator.evaluate(run_dir)
        self.assertGreaterEqual(
            metrics["hard_counters"]
            ["derived_without_evidence_promotion_count"], 1)


class TestS1003Alignment(unittest.TestCase):
    def test_mapping_covers_all_fixture_states(self):
        sm = load("state-machine.json")
        mapping = sm["s1_003_mapping"]["KnowledgeAssertion"]
        fixtures = json.loads(
            (ROOT / "research/tickets/stage-1/S1-003/fixtures.json")
            .read_text(encoding="utf-8"))
        states = set(fixtures["expected_lifecycle_states"]
                     ["KnowledgeAssertion"])
        self.assertEqual(set(mapping), states)
        self.assertIn("revoked", set().union(*[
            v if isinstance(v, list) else [v]
            for v in fixtures["expected_lifecycle_states"].values()]))

    def test_mapping_images_are_valid_states(self):
        sm = load("state-machine.json")
        valid = set(sm["states"]) | {"PROPOSED", "RETRACTED+SUPERSEDES"}
        for state, image in sm["s1_003_mapping"]["KnowledgeAssertion"].items():
            self.assertIn(image, valid, state)

    def test_every_edge_has_contract_row(self):
        sm = load("state-machine.json")
        contract = load("knowledge-gate-contract.json")
        table = {(t["from"], t["event"], t["to"])
                 for t in contract["transitions"]}
        for edge in sm["edges"]:
            self.assertIn((edge["from"], edge["event"], edge["to"]), table)


class TestDeterminism(unittest.TestCase):
    def test_seed_invariant_rows(self):
        first = run_design("minimal-gate", seed=11011)
        second = run_design("minimal-gate", seed=22022)
        strip = [{k: v for k, v in r.items()
                  if k not in ("seed", "output_sha256")} for r in first]
        other = [{k: v for k, v in r.items()
                  if k not in ("seed", "output_sha256")} for r in second]
        self.assertEqual(strip, other)

    def test_no_wall_clock_in_rows(self):
        for row in run_design("tms"):
            for key in ("created_at", "recorded_at", "timestamp", "now"):
                self.assertNotIn(key, row)


class TestStdlibOnly(unittest.TestCase):
    def test_ticket_modules_import_stdlib_only(self):
        allowed = set(sys.stdlib_module_names)
        for name in ("runner.py", "evaluator.py", "canonicalize_corpus.py",
                     "dependency_gate.py", "compare_runs.py"):
            path = S1011 / name
            if not path.is_file():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name.split(".")[0], allowed,
                                      f"{name}: {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        self.assertIn(node.module.split(".")[0], allowed,
                                      f"{name}: {node.module}")

    def test_no_network_or_llm_imports(self):
        banned = ("requests", "urllib", "http", "socket", "openai",
                  "anthropic", "llm")
        for name in ("runner.py", "evaluator.py", "canonicalize_corpus.py",
                     "dependency_gate.py"):
            text = (S1011 / name).read_text(encoding="utf-8")
            for mod in banned:
                self.assertNotIn(f"import {mod}", text, f"{name}: {mod}")


class TestSecretsAbsent(unittest.TestCase):
    def test_no_credentials_in_ticket_files(self):
        import re
        patterns = [re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
                    re.compile(r"sk-(proj|live)-[A-Za-z0-9]{8,}"),
                    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]{16,}")]
        hits = []
        for path in list(S1011.glob("*.py")) + list(S1011.glob("*.json")) \
                + list((S1011 / "results").rglob("*.json")):
            if "snapshots" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for pattern in patterns:
                if pattern.search(text):
                    hits.append(f"{path.name}: {pattern.pattern[:30]}")
        self.assertEqual(hits, [])

    def test_dependency_gate_never_writes_db_or_creds(self):
        text = (S1011 / "dependency_gate.py").read_text(encoding="utf-8")
        self.assertNotIn("sqlite3", text)
        self.assertNotIn(".agentos-research", text)


class TestPathSafety(unittest.TestCase):
    def test_repo_relative_paths_only(self):
        manifest = load("corpus-manifest.json")
        for name in manifest["hashes"]:
            self.assertNotIn("..", Path(name).parts, name)
            self.assertFalse(Path(name).is_absolute(), name)

    def test_archive_bytes_match_worktree(self):
        import subprocess
        proc = subprocess.run(
            ["git", "archive", "HEAD", "--",
             "research/tickets/stage-1/S1-011/TASK_FOR_OPENCODE.md"],
            cwd=ROOT, capture_output=True, check=False)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(proc.stdout)


class TestComparison(unittest.TestCase):
    def test_compare_module_exists_and_scores(self):
        compare_runs = __import__("compare_runs")
        self.assertTrue(hasattr(compare_runs, "compare"))
        self.assertTrue(hasattr(compare_runs, "sensitivity"))

    def test_mixed_commit_rejected(self):
        compare_runs = __import__("compare_runs")
        doc_a = {"manifest": {"commit": "a" * 40, "tree": "b" * 40,
                              "clean_tree": True,
                              "input_hashes": {"cases.json": "c"}},
                 "metrics": {"design": "minimal-gate"}}
        doc_b = {"manifest": {"commit": "d" * 40, "tree": "b" * 40,
                              "clean_tree": True,
                              "input_hashes": {"cases.json": "c"}},
                 "metrics": {"design": "minimal-gate"}}
        with self.assertRaises(compare_runs.Inadmissible):
            compare_runs.compare(doc_a, doc_b)

    def test_reused_process_identity_rejected(self):
        compare_runs = __import__("compare_runs")
        manifest = {"commit": "a" * 40, "tree": "b" * 40,
                    "clean_tree": True,
                    "input_hashes": {"cases.json": "c"},
                    "pid": 1, "ppid": 1, "invocation_id": "x",
                    "nonce": "y", "executor_id": "e",
                    "output_root": "o"}
        doc = {"manifest": manifest, "metrics": {"design": "x"},
               "rows": []}
        with self.assertRaises(compare_runs.Inadmissible):
            compare_runs.compare(doc, copy.deepcopy(doc))

    def test_sensitivity_exact_count_and_deterministic(self):
        compare_runs = __import__("compare_runs")
        first = compare_runs.sensitivity(
            {"minimal-gate": {"safety_fail_closed": 1.0,
                              "provenance_auditability": 1.0,
                              "challenge_retraction": 1.0,
                              "explainability": 0.9,
                              "operator_load": 0.7,
                              "complexity": 1.0,
                              "replay_testability": 1.0,
                              "ontology_shacl_fit": 1.0,
                              "migration_rollback": 0.9,
                              "evolvability": 0.8},
             "argumentation": {"safety_fail_closed": 0.0,
                               "provenance_auditability": 1.0,
                               "challenge_retraction": 0.8,
                               "explainability": 0.3,
                               "operator_load": 0.4,
                               "complexity": 0.5,
                               "replay_testability": 0.6,
                               "ontology_shacl_fit": None,
                               "migration_rollback": 0.6,
                               "evolvability": 1.0}})
        second = compare_runs.sensitivity(
            {"minimal-gate": {"safety_fail_closed": 1.0,
                              "provenance_auditability": 1.0,
                              "challenge_retraction": 1.0,
                              "explainability": 0.9,
                              "operator_load": 0.7,
                              "complexity": 1.0,
                              "replay_testability": 1.0,
                              "ontology_shacl_fit": 1.0,
                              "migration_rollback": 0.9,
                              "evolvability": 0.8},
             "argumentation": {"safety_fail_closed": 0.0,
                               "provenance_auditability": 1.0,
                               "challenge_retraction": 0.8,
                               "explainability": 0.3,
                               "operator_load": 0.4,
                               "complexity": 0.5,
                               "replay_testability": 0.6,
                               "ontology_shacl_fit": None,
                               "migration_rollback": 0.6,
                               "evolvability": 1.0}})
        self.assertEqual(first, second)
        total = (len(first["per_weight_sweeps"]) +
                 len(first["seeded_compositions"]))
        self.assertGreaterEqual(total, 200)
        self.assertIn("winner", first)
        self.assertIn("flips", first)


if __name__ == "__main__":
    unittest.main()
