"""S1-015 regression suite (Phase A preparation).

Stdlib only (plus playwright for the browser module, not here), no network,
no human participants. Run:
  $env:PYTHONPATH="src"
  py -3.12 -m unittest tests.test_s1_015_regressions -v
Ticket modules load under unique names (s1015_*) via importlib.
"""
import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S1015 = ROOT / "research" / "tickets" / "stage-1" / "S1-015"


def _load_ticket_module(name: str):
    unique = f"s1015_{name}"
    if unique in sys.modules:
        return sys.modules[unique]
    spec = importlib.util.spec_from_file_location(unique, S1015 / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    spec.loader.exec_module(module)
    return module


contract = _load_ticket_module("contract")
runner = _load_ticket_module("runner")
evaluator = _load_ticket_module("evaluator")
dependency_gate = _load_ticket_module("dependency_gate")
build_corpus = _load_ticket_module("build_corpus")
make_bundle = _load_ticket_module("make_bundle")

GREEN_METRICS = {
    "hard_counters": {name: 0 for name in (
        "name_only_authorization_accept_count", "canonical_identity_hidden_count",
        "collision_auto_resolved_count", "historical_identity_rewritten_count",
        "petname_scope_escape_count", "confusable_spoof_accept_count",
        "untrusted_markup_executed_count", "stale_petname_rebound_count",
        "approval_binding_mutated_count", "accessibility_identity_omission_count")},
    "mandatory_safety": {"canonical_id_visibility": True,
                         "collision_confusable_detection": True,
                         "correct_selection_approval_rejection": True,
                         "history_preservation": True,
                         "keyboard_screen_reader_completeness": True},
    "human_study_n": 0,
    "recognition_improvement": "NOT_MEASURED",
}
GREEN_COMPARISON = {"replicated": True}


def _all_a_with(**overrides):
    base = {str(n): "A" for n in range(1, 13)}
    base.update(overrides)
    return base


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(name: str):
    return json.loads((S1015 / name).read_text(encoding="utf-8"))


def fresh_envelope(case_id="BEN-01", variant="petname"):
    cases = {c["case_id"]: c for c in runner.corpus_cases(S1015)}
    return runner.build_envelope(cases[case_id], variant, runner.corpus_digest(S1015))


class TestContractFailClosed(unittest.TestCase):
    def test_valid_envelope_passes(self):
        contract.validate_envelope(fresh_envelope())

    def test_unknown_schema_version_fails(self):
        env = fresh_envelope()
        env["schema_version"] = "forged/v9"
        with self.assertRaises(ValueError):
            contract.validate_envelope(env)

    def test_unknown_enum_fails(self):
        env = fresh_envelope()
        env["principal_type"] = "superuser"
        with self.assertRaises(ValueError):
            contract.validate_envelope(env)

    def test_unknown_field_fails(self):
        env = fresh_envelope()
        env["extra_authority"] = "yes"
        with self.assertRaises(ValueError):
            contract.validate_envelope(env)

    def test_duplicate_json_key_fails(self):
        with self.assertRaises(ValueError):
            contract.loads('{"a": 1, "a": 2}')

    def test_nan_infinity_fail(self):
        for text in ('{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}'):
            with self.assertRaises(ValueError, msg=text):
                contract.loads(text)

    def test_remote_ref_fails(self):
        with self.assertRaises(ValueError):
            contract.loads('{"$ref": "https://example.com/schema.json"}')

    def test_traversal_in_ids_fails(self):
        env = fresh_envelope()
        env["principal_id"] = "../evil"
        with self.assertRaises(ValueError):
            contract.validate_envelope(env)

    def test_wrong_type_fails(self):
        env = fresh_envelope()
        env["petname_version"] = "three"
        with self.assertRaises(ValueError):
            contract.validate_envelope(env)

    def test_petname_as_approval_target_fails(self):
        env = fresh_envelope("BEN-01")
        env["approval"] = dict(env["approval"], target=env["petname"])
        with self.assertRaises(ValueError):
            contract.validate_envelope(env)

    def test_hidden_canonical_fails(self):
        env = fresh_envelope()
        env["canonical_display"] = "a friendly label"
        with self.assertRaises(ValueError):
            contract.validate_envelope(env)
        env = fresh_envelope()
        env["accessibility_text"] = "a friendly label"
        with self.assertRaises(ValueError):
            contract.validate_envelope(env)

    def test_missing_no_authority_fails(self):
        env = fresh_envelope()
        env["no_authority"] = "trust-me"
        with self.assertRaises(ValueError):
            contract.validate_envelope(env)

    def test_normalize_case_and_nfd(self):
        self.assertEqual(contract.normalize_petname("Alex "), "alex")
        import unicodedata
        nfd = unicodedata.normalize("NFD", "café")
        nfc = unicodedata.normalize("NFC", "café")
        self.assertNotEqual(nfd, nfc)
        self.assertEqual(contract.normalize_petname(nfd), contract.normalize_petname(nfc))

    def test_detect_confusable_bidi_invisible_markup(self):
        flag, reason = contract.detect_confusable("аlex")
        self.assertTrue(flag)
        flag, _ = contract.detect_confusable("Alex\u202eDoe")
        self.assertTrue(flag)
        flag, _ = contract.detect_confusable("Alex\u200b")
        self.assertTrue(flag)
        self.assertTrue(contract.has_markup("<script>alert(1)</script>"))
        flag, _ = contract.detect_confusable("Courier")
        self.assertFalse(flag)


class TestDependencyGate(unittest.TestCase):
    def test_gate_proven(self):
        result = dependency_gate.check()
        self.assertEqual(result["status"], "PROVEN", msg=result.get("problems"))

    def test_forged_override_rejected(self):
        result = dependency_gate.check(rec_override={"forged": True})
        self.assertEqual(result["status"], "NOT_PROVEN")
        self.assertTrue(any("override" in p for p in result["problems"]))

    def test_gate_file_matches(self):
        doc = load("dependency-gate.json")
        self.assertTrue(doc["phase_a_dependencies_proven"])
        self.assertFalse(doc["population_human_claims_proven"])
        self.assertEqual(doc["dependency"]["goal_id"], "goal_PZ0WP37PRBM05XH101M1QB60YD")
        self.assertEqual(doc["dependency"]["evaluation_id"], "reval_P911RT2XC117Y74Y01M1QB612C")


class TestCorpus(unittest.TestCase):
    def test_forty_cases_eight_per_class(self):
        corpus = load("corpus.json")
        self.assertEqual(corpus["case_count"], 40)
        by_class = {}
        for case in corpus["cases"]:
            by_class[case["class"]] = by_class.get(case["class"], 0) + 1
        for klass in ("benign", "collision", "lifecycle", "unicode", "approval"):
            self.assertGreaterEqual(by_class.get(klass, 0), 8, msg=klass)

    def test_unique_ids_and_digests(self):
        corpus = load("corpus.json")
        ids = [c["case_id"] for c in corpus["cases"]]
        self.assertEqual(len(set(ids)), 40)
        digests = [c["semantic_digest"] for c in corpus["cases"]]
        self.assertEqual(len(set(digests)), 40)

    def test_oracle_separate_and_bound(self):
        oracle = load("oracle.json")
        corpus = load("corpus.json")
        self.assertEqual(len(oracle["entries"]), 40)
        for case in corpus["cases"]:
            self.assertIn(case["case_id"], oracle["entries"])

    def test_generator_deterministic(self):
        first, first_oracle = build_corpus.build()
        second, second_oracle = build_corpus.build()
        self.assertEqual(first, second)
        self.assertEqual(first_oracle, second_oracle)

    def test_mandatory_forms_present(self):
        corpus = {c["case_id"]: c for c in load("corpus.json")["cases"]}
        self.assertTrue(any(len(c["principal_id"]) > 60 for c in corpus.values()))  # long ID
        self.assertIn(corpus["COL-01"]["petname"], corpus["COL-02"]["petname"])  # same petname
        self.assertEqual(corpus["LIF-01"]["petname_state"], "renamed")
        self.assertEqual(corpus["LIF-02"]["petname_state"], "deleted")
        self.assertEqual(corpus["BEN-06"]["petname"], "Помощник")  # non-Latin valid
        self.assertEqual(corpus["UNI-02"]["petname"], "Hеlper")  # mixed-script suspicious
        self.assertEqual(corpus["UNI-08"]["petname"], "")  # empty
        self.assertEqual(len(corpus["UNI-07"]["petname"]), 500)  # oversized


class TestImporter(unittest.TestCase):
    def test_matrix_imports_all_ok(self):
        out = Path(tempfile.mkdtemp(prefix="s1015-t-"))
        old = sys.argv
        sys.argv = ["runner", "--generate", "--executor", "A",
                    "--ticket", str(S1015), "--out", str(out)]
        try:
            self.assertEqual(runner.main(), 0)
        finally:
            sys.argv = old
        observations = json.loads((out / "observations.json").read_text(encoding="utf-8"))["observations"]
        self.assertEqual(len(observations), 240)
        self.assertTrue(all(o["status"] == "ok" for o in observations))

    def test_executor_independent_bytes(self):
        outs = []
        for executor in ("A", "B"):
            out = Path(tempfile.mkdtemp(prefix=f"s1015-t-{executor}-"))
            old = sys.argv
            sys.argv = ["runner", "--generate", "--executor", executor,
                        "--ticket", str(S1015), "--out", str(out)]
            try:
                self.assertEqual(runner.main(), 0)
            finally:
                sys.argv = old
            outs.append((out / "observations.json").read_bytes())
        self.assertEqual(outs[0], outs[1])

    def test_duplicate_rejected(self):
        cases = {c["case_id"]: c for c in runner.corpus_cases(S1015)}
        seen: set[str] = set()
        first = runner.import_one(fresh_envelope(), cases, seen, S1015)
        second = runner.import_one(fresh_envelope(), cases, seen, S1015)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "rejected")

    def test_corpus_binding_mismatch_rejected(self):
        cases = {c["case_id"]: c for c in runner.corpus_cases(S1015)}
        env = fresh_envelope()
        env["scope"] = "tenant-evil/workspace-shared"
        obs = runner.import_one(env, cases, set(), S1015)
        self.assertEqual(obs["status"], "rejected")

    def test_pii_quarantined(self):
        cases = {c["case_id"]: c for c in runner.corpus_cases(S1015)}
        env = fresh_envelope()
        env["petname"] = "call somebody@example.com"
        obs = runner.import_one(env, cases, set(), S1015)
        self.assertIn(obs["status"], ("rejected", "quarantined"))

    def test_name_only_target_rejected(self):
        cases = {c["case_id"]: c for c in runner.corpus_cases(S1015)}
        env = fresh_envelope("COL-01")
        env["approval"] = dict(env["approval"], target="Alex")
        obs = runner.import_one(env, cases, set(), S1015)
        self.assertEqual(obs["status"], "rejected")


class TestEvaluator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = Path(tempfile.mkdtemp(prefix="s1015-eval-"))
        old = sys.argv
        sys.argv = ["runner", "--generate", "--executor", "A",
                    "--ticket", str(S1015), "--out", str(out)]
        try:
            assert runner.main() == 0
        finally:
            sys.argv = old
        cls.run_dir = out
        cls.metrics = evaluator.evaluate(out, S1015)
        cls.probe_doc = evaluator.probes(out, S1015)

    def test_hard_counters_zero(self):
        for name, value in self.metrics["hard_counters"].items():
            self.assertIsInstance(value, int, msg=name)
            self.assertEqual(value, 0, msg=name)

    def test_mandatory_safety_100pct(self):
        for name, value in self.metrics["mandatory_safety"].items():
            self.assertTrue(value, msg=name)

    def test_no_human_claim(self):
        self.assertEqual(self.metrics["human_study_n"], 0)
        self.assertEqual(self.metrics["recognition_improvement"], "NOT_MEASURED")
        self.assertTrue(self.metrics["synthetic"])

    def test_probes_a_to_n_pass(self):
        self.assertTrue(self.probe_doc["all_pass"])
        self.assertEqual(len(self.probe_doc["probes"]), 14)

    def test_tampered_verdict_detected(self):
        tampered = copy.deepcopy(self.metrics)
        tampered["verdict"] = "PASS"
        fresh = evaluator.evaluate(self.run_dir, S1015)
        self.assertNotEqual(tampered["verdict"], fresh["verdict"])

    def test_matrix_shape(self):
        self.assertEqual(self.metrics["observations"], 240)
        by_variant = self.metrics["variants"]["by_variant"]
        self.assertEqual(by_variant["baseline"]["observations"], 120)
        self.assertEqual(by_variant["petname"]["observations"], 120)


class TestPrototypeStatic(unittest.TestCase):
    def test_no_unsafe_dom_api(self):
        import re
        app_js = (S1015 / "prototype" / "app.js").read_text(encoding="utf-8")
        for pattern in (r"\.innerHTML\s*=", r"\.outerHTML\s*=",
                        r"insertAdjacentHTML\s*\(", r"document\.write\s*\("):
            self.assertIsNone(re.search(pattern, app_js), msg=pattern)

    def test_csp_present(self):
        index = (S1015 / "prototype" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy", index)
        self.assertIn("default-src 'self'", index)

    def test_both_variants_supported(self):
        app_js = (S1015 / "prototype" / "app.js").read_text(encoding="utf-8")
        self.assertIn("baseline", app_js)
        self.assertIn("petname", app_js)
        self.assertIn("textContent", app_js)

    def test_browser_contract_bound(self):
        doc = load("prototype/browser-contract.json")
        self.assertEqual(doc["export_schema"], "agentos.s1-015.export/v1")
        self.assertEqual(len(doc["cases"]), 40)
        manifest = load("corpus-manifest.json")
        self.assertEqual(doc["corpus_sha256"], manifest["corpus_sha256"])


class TestOperatorVerdict(unittest.TestCase):
    def test_all_a_admits_display_only(self):
        blockers, verdict = make_bundle.derive_verdict(
            copy.deepcopy(GREEN_METRICS), dict(GREEN_COMPARISON),
            True, _all_a_with())
        self.assertEqual(blockers, [])
        self.assertEqual(verdict["design_decision"],
                         "DISPLAY_ONLY_PETNAME_WITH_CANONICAL_ID")
        self.assertEqual(verdict["status"], "CLOSED_WITH_LIMITS")

    def test_2b_blocks_petname_closure_as_inconclusive(self):
        blockers, verdict = make_bundle.derive_verdict(
            copy.deepcopy(GREEN_METRICS), dict(GREEN_COMPARISON),
            True, _all_a_with(**{"2": "B"}))
        self.assertEqual(blockers, [])
        self.assertEqual(verdict["design_decision"], "INCONCLUSIVE")
        self.assertEqual(verdict["status"], "CLOSED_INCONCLUSIVE")
        self.assertIn("2B", verdict["blocking_answers"])

    def test_1b_downgrades_to_canonical_only(self):
        blockers, verdict = make_bundle.derive_verdict(
            copy.deepcopy(GREEN_METRICS), dict(GREEN_COMPARISON),
            True, _all_a_with(**{"1": "B"}))
        self.assertEqual(blockers, [])
        self.assertEqual(verdict["design_decision"], "CANONICAL_ID_ONLY")

    def test_nonzero_counter_blocks(self):
        metrics = copy.deepcopy(GREEN_METRICS)
        metrics["hard_counters"]["collision_auto_resolved_count"] = 1
        blockers, _ = make_bundle.derive_verdict(
            metrics, dict(GREEN_COMPARISON), True, _all_a_with())
        self.assertTrue(blockers)

    def test_no_decision_stays_preparation_ready(self):
        blockers, verdict = make_bundle.derive_verdict(
            copy.deepcopy(GREEN_METRICS), dict(GREEN_COMPARISON), False, None)
        self.assertEqual(verdict["status"], "PREPARATION_READY")


class TestSourcesFrozen(unittest.TestCase):
    def test_registry_roles_and_hashes(self):
        registry = load("source-registry.json")
        roles = {s["role"] for s in registry["sources"]}
        for role in ("mental-model", "identity-contract", "unicode-security",
                     "accessibility", "naming-context"):
            self.assertIn(role, roles)
        for entry in registry["sources"]:
            raw = (S1015 / entry["snapshot_path"].split("S1-015/")[-1]).read_bytes()
            self.assertEqual(sha(raw), entry["sha256"])
            self.assertEqual(len(raw), entry["bytes"])

    def test_rubric_and_decision_rule_frozen(self):
        rubric = load("rubric.json")
        self.assertTrue(rubric["frozen"])
        self.assertEqual(len(rubric["hard_counters"]), 10)
        rule = load("decision-rule.json")
        self.assertTrue(rule["frozen"])
        self.assertIn("DISPLAY_ONLY_PETNAME_WITH_CANONICAL_ID", rule["allowed_design_decisions"])


if __name__ == "__main__":
    unittest.main()
