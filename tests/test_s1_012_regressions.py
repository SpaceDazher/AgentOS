"""S1-012 regression suite (Phase A).

Covers TASK_FOR_AGENT.md checks plus corrective lessons from S1-011
(strict validation, ledger-free digest rechecks, honest confusion,
native bundle, derived verdict, importlib unique names).
Stdlib only, no network/LLM.
Run: $env:PYTHONPATH="src"; py -3.12 -m unittest tests.test_s1_012_regressions -v
"""
import copy
import hashlib
import importlib.util
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S1012 = ROOT / "research" / "tickets" / "stage-1" / "S1-012"


def _load_ticket_module(name: str):
    unique = f"s1012_{name}"
    if unique in sys.modules:
        return sys.modules[unique]
    spec = importlib.util.spec_from_file_location(unique, S1012 / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    spec.loader.exec_module(module)
    return module


canonicalize_corpus = _load_ticket_module("canonicalize_corpus")
evaluator = _load_ticket_module("evaluator")
runner = _load_ticket_module("runner")
dependency_gate = _load_ticket_module("dependency_gate")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(name: str):
    return json.loads((S1012 / name).read_text(encoding="utf-8"))


def run_variant(variant: str, seed: int = 12012, **params):
    corpus = load("cases.json")
    full = {"prior_a": 1, "prior_b": 1, "decay": 1.0, "cap": 2,
            "threshold": 0.9}
    full.update(params)
    return [runner.decide(runner.Case(raw), variant, seed, full)
            for raw in corpus["cases"]]


def rows_by_id(rows):
    return {r["case_id"]: r for r in rows}


def mutated_rows(base_rows, case_id, **changes):
    out = []
    for row in base_rows:
        row = dict(row)
        if row["case_id"] == case_id:
            row.update(changes)
            row.pop("output_sha256", None)
            row["output_sha256"] = sha(evaluator.canonical(
                {k: v for k, v in row.items() if k != "output_sha256"}))
        out.append(row)
    return out


def evaluate_in_memory(rows, variant="document", seed=12012):
    import tempfile
    run_dir = Path(tempfile.mkdtemp())
    (run_dir / "raw-observations.json").write_text(json.dumps(
        {"schema": "x", "variant": variant, "seed": seed,
         "rows": rows}), encoding="utf-8")
    return evaluator.evaluate(run_dir)


class TestNamespaceIsolation(unittest.TestCase):
    def test_ticket_modules_have_unique_names(self):
        self.assertEqual(runner.__name__, "s1012_runner")
        self.assertEqual(evaluator.__name__, "s1012_evaluator")
        self.assertTrue(hasattr(evaluator, "OUTCOMES"))
        self.assertTrue(hasattr(evaluator, "check_rows"))


class TestCorpusFrozen(unittest.TestCase):
    def test_counts_and_families(self):
        corpus = load("cases.json")
        self.assertEqual(len(corpus["cases"]), 60)
        counts = {}
        for case in corpus["cases"]:
            counts[case["family"]] = counts.get(case["family"], 0) + 1
        for family in ("gold", "correlation", "sybil", "invalid",
                       "nearmiss"):
            self.assertEqual(counts.get(family, 0), 12, family)

    def test_split_sizes(self):
        corpus = load("cases.json")
        splits = [c["split"] for c in corpus["cases"]]
        self.assertEqual(splits.count("dev"), 40)
        self.assertEqual(splits.count("holdout"), 20)

    def test_lineage_isolation(self):
        self.assertEqual(canonicalize_corpus.check_lineage(), 0)

    def test_canonicalizer_check_passes(self):
        self.assertEqual(canonicalize_corpus.check(), 0)

    def test_tampered_case_detected(self):
        frozen = load("cases.json")
        tampered = copy.deepcopy(frozen["cases"][0])
        tampered["expected"]["document"]["outcome"] = "reject"
        body = {k: v for k, v in tampered.items() if k != "case_sha256"}
        self.assertNotEqual(
            sha(evaluator.canonical(body)), tampered["case_sha256"])

    def test_manifest_hashes_match_disk(self):
        manifest = load("corpus-manifest.json")
        for name, pinned in manifest["hashes"].items():
            data = (S1012 / name).read_bytes()
            self.assertEqual(sha(data), pinned, name)
        self.assertEqual(manifest["matrix"]["rows_per_run"], 720)

    def test_expected_outcomes_host_owned(self):
        for src in ("cases-dev.src.json", "cases-holdout.src.json"):
            doc = load(src)
            for case in doc["cases"]:
                self.assertIn("expected", case)
                for variant in ("document", "span", "digest",
                                "reputation-only"):
                    exp = case["expected"][variant]
                    self.assertIn(exp["outcome"],
                                  ("admit", "reject", "abstain"))
                    self.assertIsInstance(exp["n_independent"], int)


class TestOracleMatch(unittest.TestCase):
    def test_all_variants_match_oracle(self):
        corpus = load("cases.json")
        for variant in ("document", "span", "digest", "reputation-only"):
            by_id = rows_by_id(run_variant(variant))
            mismatches = []
            for case in corpus["cases"]:
                row = by_id[case["case_id"]]
                exp = case["expected"][variant]
                if (row["n_independent"], row["outcome"],
                        row["reason_code"]) != (
                        exp["n_independent"], exp["outcome"],
                        exp["reason"]):
                    mismatches.append(case["case_id"])
            self.assertEqual(mismatches, [], variant)

    def test_governed_metrics_pass(self):
        for variant in ("document", "span", "digest"):
            metrics = evaluate_in_memory(run_variant(variant), variant)
            self.assertTrue(metrics["admissible"], variant)
            self.assertEqual(metrics["verdict"], "PASS", variant)
            self.assertTrue(all(v == 0 for v in
                                metrics["hard_counters"].values()),
                            variant)
            self.assertEqual(metrics["transition_exactness"], 1.0,
                             variant)

    def test_baseline_is_negative_control(self):
        metrics = evaluate_in_memory(run_variant("reputation-only"),
                                     "reputation-only")
        self.assertTrue(metrics["admissible"])
        self.assertEqual(metrics["verdict"], "FAIL")
        self.assertGreater(metrics["hard_counters"]
                           ["mirror_sybil_double_count"], 0)


class TestProbes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.probe_docs = {}
        for variant in ("document", "span", "digest", "reputation-only"):
            run_dir = Path(tempfile.mkdtemp())
            (run_dir / "raw-observations.json").write_text(json.dumps(
                {"schema": "x", "variant": variant, "seed": 12012,
                 "rows": run_variant(variant)}), encoding="utf-8")
            cls.probe_docs[variant] = evaluator.probes(run_dir)

    def test_all_probes_pass_governed(self):
        for variant in ("document", "span", "digest"):
            doc = self.probe_docs[variant]
            self.assertTrue(doc["all_pass"], variant)
            for probe in "ABCDEFG":
                self.assertTrue(doc["probes"][probe]["passed"],
                                f"{variant}/{probe}")

    def test_mirror_collapse_probe_a(self):
        doc = self.probe_docs["document"]
        for cid in ("S1-012-D09", "S1-012-D10", "S1-012-H05"):
            found = [c for p in doc["probes"].values() for c in p["cases"]
                     if c["case_id"] == cid]
            self.assertTrue(found and all(c["passed"] for c in found), cid)


class TestBetaMath(unittest.TestCase):
    def test_reference_values_match_binomial(self):
        plan = load("calibration-plan.json")
        for ref in plan["beta"]["reference_values"]["cases"]:
            got = 1.0 - runner.beta_cf(ref["a"], ref["b"], ref["x"])
            self.assertAlmostEqual(got, ref["tail"], places=4,
                                   msg=str(ref))

    def test_runner_matches_binomial_on_integers(self):
        import random
        rng = random.Random(7)
        for _ in range(25):
            a = rng.randint(1, 12)
            b = rng.randint(1, 12)
            x = rng.choice([0.5, 0.8, 0.9, 0.95])
            ref = evaluator.binomial_tail(a, b, x)
            got = 1.0 - runner.beta_cf(a, b, x)
            self.assertAlmostEqual(got, ref, places=9)

    def test_metamorphic_monotone(self):
        base = runner.beta_over(["support"] * 3, 1, 1, 1.0, 0.9)
        more = runner.beta_over(["support"] * 6, 1, 1, 1.0, 0.9)
        self.assertGreater(more["tail"], base["tail"])
        refuted = runner.beta_over(["support"] * 3 + ["refute"] * 3,
                                   1, 1, 1.0, 0.9)
        self.assertLess(refuted["tail"], base["tail"])

    def test_metamorphic_prior_washout(self):
        # Same data under opposing priors must disagree less as data grows.
        few_a = runner.beta_over(["support"] * 2, 1, 3, 1.0, 0.9)
        few_b = runner.beta_over(["support"] * 2, 3, 1, 1.0, 0.9)
        many_a = runner.beta_over(["support"] * 200, 1, 3, 1.0, 0.9)
        many_b = runner.beta_over(["support"] * 200, 3, 1, 1.0, 0.9)
        gap_few = abs(few_a["tail"] - few_b["tail"])
        gap_many = abs(many_a["tail"] - many_b["tail"])
        self.assertGreater(gap_few, 0.0)
        self.assertLess(gap_many, gap_few)

    def test_metamorphic_washout(self):
        weak = runner.beta_over(["support"] * 2, 1, 3, 1.0, 0.9)
        strong = runner.beta_over(["support"] * 200, 1, 3, 1.0, 0.9)
        self.assertGreater(strong["tail"], weak["tail"])

    def test_invalid_params_rejected(self):
        bad = runner.beta_over(["support"], 0, 1, 1.0, 0.9)
        self.assertIsNone(bad["tail"])
        bad = runner.beta_over(["support"], 1, 1, float("nan"), 0.9)
        self.assertIsNone(bad["tail"])
        bad = runner.beta_over(["support"], 1, 1, 1.0, 1.5)
        self.assertIsNone(bad["tail"])

    def test_zero_trials_abstain_not_posterior(self):
        beta = runner.beta_over([], 1, 1, 1.0, 0.9)
        self.assertEqual(beta["trials"], 0)
        self.assertAlmostEqual(beta["tail"], 0.1, places=9)


class TestEigenTrust(unittest.TestCase):
    def test_frozen_two_node_reference(self):
        result = runner.eigentrust(["S1", "S2"],
                                   [{"from": "S1", "to": "S2", "value": 1.0},
                                    {"from": "S2", "to": "S1", "value": 1.0}],
                                   ["S1"], damping=0.85)
        self.assertTrue(result["converged"])
        self.assertAlmostEqual(result["trust"]["S1"], 20 / 37, places=6)
        self.assertAlmostEqual(result["trust"]["S2"], 17 / 37, places=6)

    def test_anchorless_abstains(self):
        result = runner.eigentrust(["S1", "S2"],
                                   [{"from": "S1", "to": "S2", "value": 0.95},
                                    {"from": "S2", "to": "S1", "value": 0.95}],
                                   [], damping=0.85)
        self.assertTrue(result["abstain"])
        self.assertIsNone(result["trust"])

    def test_vector_stochastic(self):
        rows = run_variant("document")
        for row in rows:
            trust = row["eigentrust"] or {}
            if trust.get("trust"):
                total = sum(trust["trust"].values())
                self.assertAlmostEqual(total, 1.0, places=9)

    def test_reference_case_matches(self):
        by_id = rows_by_id(run_variant("document"))
        row = by_id["S1-012-D23"]
        trust = row["eigentrust"]
        self.assertTrue(trust["converged"])
        self.assertAlmostEqual(trust["trust"]["S1"], 20 / 37, places=6)


class TestAttacks(unittest.TestCase):
    def test_inflated_count_fails(self):
        rows = run_variant("document")
        bad = mutated_rows([dict(r) for r in rows], "S1-012-D09",
                           n_independent=2, outcome="admit")
        metrics = evaluate_in_memory(bad)
        self.assertEqual(metrics["verdict"], "FAIL")
        self.assertGreater(metrics["hard_counters"]
                           ["mirror_sybil_double_count"], 0)

    def test_enforcement_flag_blocked(self):
        rows = run_variant("document")
        bad = mutated_rows([dict(r) for r in rows], "S1-012-D19",
                           enforcement_allow=True)
        problems, _ = evaluator.check_rows(
            bad, load("cases.json"), "document")
        self.assertTrue(any("enforcement_allow" in p for p in problems))

    def test_null_digest_unbound(self):
        rows = run_variant("document")
        bad = [dict(r) for r in rows]
        for row in bad:
            if row["case_id"] == "S1-012-D01":
                row["units"][0]["digest"] = None
                break
        bad = mutated_rows(bad, "S1-012-D01")
        metrics = evaluate_in_memory(bad)
        self.assertEqual(metrics["verdict"], "FAIL")

    def test_missing_row_inadmissible(self):
        rows = [r for r in run_variant("document")
                if r["case_id"] != "S1-012-D01"]
        problems, _ = evaluator.check_rows(
            rows, load("cases.json"), "document")
        self.assertTrue(any("missing case" in p for p in problems))

    def test_valid_reject_swap_is_fn(self):
        rows = run_variant("document")
        bad = mutated_rows([dict(r) for r in rows], "S1-012-D01",
                           outcome="reject", reason_code="REJECTED_CORRELATED")
        metrics = evaluate_in_memory(bad)
        # No safety gate fires (a wrong rejection is not unsafe), but the
        # miss must be recorded as FN with recall below 1, never hidden.
        self.assertEqual(metrics["confusion"]["fn"], 1)
        self.assertLess(metrics["overall"]["recall"], 1.0)
        self.assertLess(metrics["transition_exactness"], 1.0)


class TestDependencyGateStrict(unittest.TestCase):
    def test_real_dependencies_proven(self):
        for ticket in ("S1-001", "S1-003", "S1-011"):
            self.assertEqual(dependency_gate.check(ticket)["status"],
                             "PROVEN", ticket)

    def test_fail_verdict_never_proven(self):
        rec = json.loads((ROOT / "research/tickets/stage-1/S1-001"
                          / "evaluation-record.json").read_text(
                              encoding="utf-8"))
        bad = copy.deepcopy(rec)
        bad["result"] = "fail"
        segment = ("### S1-001 probe\n- **Status:** `FAIL`\n"
                   "research revision 1\n")
        result = dependency_gate.check("S1-001", rec_override=bad,
                                       docs_override=segment)
        self.assertEqual(result["status"], "NOT_PROVEN")
        self.assertTrue(any("allowlist" in p for p in result["problems"]))

    def test_fabricated_revision_rejected(self):
        rec = json.loads((ROOT / "research/tickets/stage-1/S1-001"
                          / "evaluation-record.json").read_text(
                              encoding="utf-8"))
        bad = copy.deepcopy(rec)
        bad["research_revision"] = 999999
        result = dependency_gate.check("S1-001", rec_override=bad)
        self.assertEqual(result["status"], "NOT_PROVEN")
        self.assertTrue(any("not bound" in p for p in result["problems"]))

    def test_traversal_path_rejected(self):
        self.assertFalse(dependency_gate.contained(
            "research/tickets/stage-1/S1-001/../../S1-002/x.json", "S1-001"))
        self.assertFalse(dependency_gate.contained(
            "C:\\Windows\\x.json", "S1-001"))
        self.assertFalse(dependency_gate.contained(
            "//server/share/x.json", "S1-001"))
        self.assertTrue(dependency_gate.contained(
            "research/tickets/stage-1/S1-001/results/evidence/x.json",
            "S1-001"))


class TestStdlibOnly(unittest.TestCase):
    def test_ticket_modules_import_stdlib_only(self):
        import ast
        allowed = set(sys.stdlib_module_names) | {
            "s1012_runner", "s1012_evaluator",
            "s1012_canonicalize_corpus", "s1012_dependency_gate",
            "s1012_compare_runs", "s1012_make_bundle"}
        for name in ("runner.py", "evaluator.py", "canonicalize_corpus.py",
                     "dependency_gate.py", "compare_runs.py",
                     "make_bundle.py"):
            path = S1012 / name
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
                     "dependency_gate.py", "compare_runs.py",
                     "make_bundle.py"):
            path = S1012 / name
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for mod in banned:
                self.assertNotIn(f"import {mod}", text, f"{name}: {mod}")


class TestSecretsAbsent(unittest.TestCase):
    def test_no_credentials_in_ticket_files(self):
        import re
        patterns = [re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
                    re.compile(r"sk-(proj|live)-[A-Za-z0-9]{8,}"),
                    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]{16,}")]
        hits = []
        for path in list(S1012.glob("*.py")) + list(S1012.glob("*.json")) \
                + list((S1012 / "results").rglob("*.json")):
            if "snapshots" in path.parts or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for pattern in patterns:
                if pattern.search(text):
                    hits.append(f"{path.name}: {pattern.pattern[:30]}")
        self.assertEqual(hits, [])


class TestComparison(unittest.TestCase):
    def test_compare_module_functions_exist(self):
        compare_runs = _load_ticket_module("compare_runs")
        self.assertTrue(hasattr(compare_runs, "compare"))
        self.assertTrue(hasattr(compare_runs, "sensitivity"))
        self.assertTrue(hasattr(compare_runs, "check_series"))
        self.assertTrue(hasattr(compare_runs, "select_eligible"))

    def test_hard_failed_excluded_from_ranking(self):
        compare_runs = _load_ticket_module("compare_runs")
        per_design = {"a": {"safety": 1.0}, "b": {"safety": 0.0}}
        metrics_by = {"a": {"verdict": "PASS"},
                      "b": {"verdict": "FAIL"}}
        eligible = compare_runs.select_eligible(per_design, metrics_by)
        self.assertEqual(set(eligible), {"a"})

    def test_unknown_dependence_detected(self):
        compare_runs = _load_ticket_module("compare_runs")
        scores = {"A": {"x": 1.0, "y": None},
                  "B": {"x": 0.9, "y": 0.9}}
        result = compare_runs.sensitivity(
            scores, weights={"x": 0.5, "y": 0.5}, seeded=200)
        self.assertEqual(result["winner"], "A")
        self.assertTrue(result["unknown_dependent"])


class TestBundleNative(unittest.TestCase):
    def test_bundle_passes_evaluation_checks(self):
        from agentos.research import (_normalise_config, _normalize_bundle,
                                      _evaluation_checks)
        bundle = json.loads((S1012 / "bundle.json").read_text(
            encoding="utf-8"))
        config, config_errors = _normalise_config(None, bundle)
        self.assertEqual(config_errors, [])
        normalized, bundle_errors = _normalize_bundle(bundle, config)
        self.assertEqual(bundle_errors, [])
        failures, _ = _evaluation_checks(normalized, config)
        self.assertEqual(failures, [])

    def test_bundle_binding_matches_disk(self):
        bundle = json.loads((S1012 / "bundle.json").read_text(
            encoding="utf-8"))
        candidate = json.loads((S1012 / "candidate-record.json").read_text(
            encoding="utf-8"))
        self.assertEqual(sha((S1012 / "bundle.json").read_bytes()),
                         candidate["bundle_sha256"])
        self.assertEqual(len(bundle["artifacts"]), 11)


class TestBundleRefusal(unittest.TestCase):
    def test_refusal_without_evidence(self):
        import tempfile
        unique = "s1012_make_bundle_refusal"
        spec = importlib.util.spec_from_file_location(
            unique, S1012 / "make_bundle.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique] = module
        spec.loader.exec_module(module)
        work = Path(tempfile.mkdtemp())
        (work / "results").mkdir()
        gate = {"all_proven": False,
                "canonical_db_recheck_required": True}
        (work / "dependency-gate.json").write_text(json.dumps(gate))
        module.HERE = work
        module.RESULTS = work / "results"
        code = module.main()
        self.assertEqual(code, 1)
        self.assertFalse((work / "candidate-record.json").exists())


    def test_unresolved_tie_blocked(self):
        unique = "s1012_make_bundle_adj"
        spec = importlib.util.spec_from_file_location(
            unique, S1012 / "make_bundle.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique] = module
        spec.loader.exec_module(module)
        governed = {"document": {}, "span": {}}
        base = {"verdict": "DECIDED", "sensitivity_flips": 0,
                "unknown_dependent": False}
        sens = {"winner": "TIE", "flip_count": 0,
                "unknown_dependent": True,
                "parameter_grid": {"flip_count": 0}}
        tied = dict(base, sensitivity_winner="TIE",
                    tie_limitation={"tied": ["document", "span"],
                                    "all_eligible": True})
        self.assertEqual(module.adjudicate_winner(tied, sens, governed),
                         [])
        untied = dict(base, sensitivity_winner="TIE",
                      tie_limitation=None)
        problems = module.adjudicate_winner(untied, sens, governed)
        self.assertTrue(any("tie" in line for line in problems), problems)
        flips = dict(tied, sensitivity_flips=1)
        problems = module.adjudicate_winner(flips, sens, governed)
        self.assertTrue(any("flip" in line for line in problems))


class TestPublicationRecompute(unittest.TestCase):
    """Finding F1: saved flags are never authority. These tests build
    full in-process series (real decision core, realistic manifests)
    and prove the publication gate recomputes and crosschecks."""

    @classmethod
    def setUpClass(cls):
        import subprocess
        import tempfile
        cls.work = Path(tempfile.mkdtemp(prefix="s1012-pub-"))
        manifest = load("corpus-manifest.json")
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
            text=True, check=False).stdout.strip()
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT,
            capture_output=True, text=True, check=False).stdout.strip()
        base = 50000
        for series in ("run-a", "run-b"):
            for vi, variant in enumerate(
                    ("document", "span", "digest", "reputation-only")):
                for si, seed in enumerate((12012, 22022, 33033)):
                    pid = base + vi * 10 + si + (1000 if series == "run-b"
                                                 else 0)
                    cell = cls.work / series / f"{variant}-{seed}"
                    cell.mkdir(parents=True)
                    rows = run_variant(variant, seed)
                    (cell / "raw-observations.json").write_text(json.dumps(
                        {"schema": "agentos.s1-012.raw-observations/v1",
                         "variant": variant, "seed": seed,
                         "rows": rows}, indent=2) + "\n",
                        encoding="utf-8")
                    (cell / "run-manifest.json").write_text(json.dumps(
                        {"schema": "agentos.s1-012.run-manifest/v1",
                         "ticket": "S1-012", "variant": variant,
                         "seed": seed, "rows": len(rows), "pid": pid,
                         "ppid": pid - 1,
                         "invocation_id": f"test-{series}-{variant}-{seed}",
                         "nonce": f"nonce-{series}-{variant}-{seed}",
                         "executor_id": f"test@localhost#{pid}",
                         "commit": commit, "tree": tree,
                         "clean_tree": True,
                         "describe": commit[:12],
                         "python": "3.12.6",
                         "input_hashes": dict(manifest["hashes"]),
                         "output_root": str(cell)}) + "\n",
                        encoding="utf-8")
        for variant in ("document", "span", "digest", "reputation-only"):
            for series in ("run-a", "run-b"):
                for seed in (12012, 22022, 33033):
                    cell = cls.work / series / f"{variant}-{seed}"
                    metrics = evaluator.evaluate(cell)
                    (cell / "metrics.json").write_text(
                        json.dumps(metrics, indent=2) + "\n",
                        encoding="utf-8")
                    (cell / "probes.json").write_text(
                        json.dumps(evaluator.probes(cell), indent=2) + "\n",
                        encoding="utf-8")
        unique = "s1012_compare_runs_pubtest"
        spec = importlib.util.spec_from_file_location(
            unique, S1012 / "compare_runs.py")
        cls.compare_runs = importlib.util.module_from_spec(spec)
        sys.modules[unique] = cls.compare_runs
        spec.loader.exec_module(cls.compare_runs)
        code = cls.compare_runs.main([
            "--a", str(cls.work / "run-a"), "--b", str(cls.work / "run-b"),
            "--out", str(cls.work / "comparison.json"),
            "--sensitivity", str(cls.work / "sensitivity.json"),
            "--metrics", str(cls.work / "metrics.json"),
            "--probes", str(cls.work / "probes.json")])
        assert code == 0, "fixture series must compare cleanly"

    def _derive(self, results):
        unique = "s1012_make_bundle_pubtest"
        spec = importlib.util.spec_from_file_location(
            unique, S1012 / "make_bundle.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique] = module
        spec.loader.exec_module(module)
        (results / "dependency-gate.json").write_text(json.dumps(
            load("dependency-gate.json")))
        return module.derive_verdict(here=S1012, results=results)

    def test_honest_series_publishes(self):
        blockers, facts = self._derive(self.work)
        self.assertEqual(blockers, [])
        self.assertIn("recomputed_from", facts)

    def test_repro_a_flag_counter_mismatch_blocked(self):
        import shutil
        work = Path(self.work.parent / "s1012-repro-a")
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(self.work, work)
        metrics = json.loads((work / "metrics.json").read_text(
            encoding="utf-8"))
        doc = metrics["designs"]["document"]
        doc["hard_fail"] = True
        doc["hard_counters"]["mirror_sybil_double_count"] = 5
        (work / "metrics.json").write_text(json.dumps(metrics))
        unique = "s1012_make_bundle_reproa"
        spec = importlib.util.spec_from_file_location(
            unique, S1012 / "make_bundle.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique] = module
        spec.loader.exec_module(module)
        (work / "dependency-gate.json").write_text(json.dumps(
            load("dependency-gate.json")))
        blockers, _ = module.derive_verdict(here=S1012, results=work)
        self.assertTrue(blockers, "Repro A must block publication")
        self.assertTrue(any("differs from recomputation" in line or
                            "mismatch" in line for line in blockers),
                        blockers)

    def test_repro_b_fabrication_blocked(self):
        import shutil
        work = Path(self.work.parent / "s1012-repro-b")
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(self.work, work)
        metrics = {"designs": {
            v: {"verdict": "PASS",
                "hard_counters": {k: 0 for k in evaluator.HARD_COUNTERS}}
            for v in ("document", "span", "digest", "reputation-only")}}
        (work / "metrics.json").write_text(json.dumps(metrics))
        comparison = {"verdict": "DECIDED", "sensitivity_winner": "digest",
                      "sensitivity_flips": 0, "unknown_dependent": False,
                      "tie_limitation": None, "commits": ["x"],
                      "trees": ["y"], "cells": []}
        (work / "comparison.json").write_text(json.dumps(comparison))
        sens = {"winner": "digest", "flip_count": 0,
                "unknown_dependent": False,
                "parameter_grid": {"flip_count": 0}}
        (work / "sensitivity.json").write_text(json.dumps(sens))
        unique = "s1012_make_bundle_reprob"
        spec = importlib.util.spec_from_file_location(
            unique, S1012 / "make_bundle.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique] = module
        spec.loader.exec_module(module)
        (work / "dependency-gate.json").write_text(json.dumps(
            load("dependency-gate.json")))
        blockers, _ = module.derive_verdict(here=S1012, results=work)
        self.assertTrue(blockers, "Repro B must block publication")

    def test_consistency_unit(self):
        unique = "s1012_make_bundle_cons"
        spec = importlib.util.spec_from_file_location(
            unique, S1012 / "make_bundle.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique] = module
        spec.loader.exec_module(module)
        ok = {"designs": {"document": {
            "verdict": "PASS",
            "hard_counters": {"mirror_sybil_double_count": 0}}}}
        self.assertEqual(module.check_verdict_consistency(ok), [])
        bad = {"designs": {"document": {
            "verdict": "PASS",
            "hard_counters": {"mirror_sybil_double_count": 5}}}}
        problems = module.check_verdict_consistency(bad)
        self.assertTrue(any("mismatch" in line for line in problems))

    def test_tracked_registry_matches_disk(self):
        unique = "s1012_make_bundle_reg"
        spec = importlib.util.spec_from_file_location(
            unique, S1012 / "make_bundle.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique] = module
        spec.loader.exec_module(module)
        registry = module.tracked_registry()
        self.assertGreater(len(registry), 20)
        for rel, pinned in sorted(registry.items())[:5]:
            path = ROOT / rel.replace("/", "\\")
            if not path.is_file():
                path = ROOT / rel
            self.assertTrue(path.is_file(), rel)
            self.assertEqual(sha(path.read_bytes()), pinned, rel)
        snapshots = [k for k in registry
                     if "/snapshots/" in k]
        self.assertEqual(len(snapshots), 6)


if __name__ == "__main__":
    unittest.main()
