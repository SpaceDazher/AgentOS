"""S1-017 regression suite (Phase A preparation).

Stdlib only, offline, no human subjects. Run:
  $env:PYTHONPATH="src"
  py -3.12 -m unittest tests.test_s1_017_regressions -v
Ticket modules load under unique names (s1017_*) via importlib.
Phase A scope: contracts, vocabulary, corpus generator, model core and
evaluator skeleton on small-scale fixtures. No final matrix, no placement
choice, no publication.
"""
import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S1017 = ROOT / "research" / "tickets" / "stage-1" / "S1-017"


def _load_ticket_module(name: str):
    unique = f"s1017_{name}"
    if unique in sys.modules:
        return sys.modules[unique]
    spec = importlib.util.spec_from_file_location(unique, S1017 / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    spec.loader.exec_module(module)
    return module


contract = _load_ticket_module("contract")
models = _load_ticket_module("models")
runner = _load_ticket_module("runner")
evaluator = _load_ticket_module("evaluator")
build_corpus = _load_ticket_module("build_corpus")
sensitivity = _load_ticket_module("sensitivity")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(name: str):
    return json.loads((S1017 / name).read_text(encoding="utf-8"))


SA = {"tenant_id": "t-a", "workspace_id": "w-1", "goal_id": "g-1"}
SB = {"tenant_id": "t-a", "workspace_id": "w-2", "goal_id": "g-2"}


def _game_grant_allow():
    return {
        "states": [
            {"state_id": "s0", "authority": {"grants": {"grant1": {
                "scope": dict(SA), "actions": ["read"], "revoked": False,
                "expired": False}}}, "phase": "ready"},
            {"state_id": "s1", "authority": {}, "phase": "done"},
        ],
        "initial": "s0",
        "transitions": [
            {"from": "s0", "actor": "prin_A", "action": "read",
             "args": {"path": "doc"}, "to": "s1",
             "authority_required": {"grant_id": "grant1"},
             "outcome": "effect", "environment_move": None,
             "audit_ref": "ev1"},
            {"from": "s0", "actor": "prin_A", "action": "wait",
             "args": {}, "to": "s0",
             "authority_required": None,
             "outcome": "effect", "environment_move": None,
             "audit_ref": "ev0"},
        ],
    }


class TestContractFailClosed(unittest.TestCase):
    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):
            contract.loads('{"a": 1, "a": 2}')

    def test_nonfinite_rejected(self):
        for text in ('{"a": NaN}', '{"a": Infinity}'):
            with self.assertRaises(ValueError, msg=text):
                contract.loads(text)

    def test_remote_ref_rejected(self):
        with self.assertRaises(ValueError):
            contract.loads('{"$ref": "https://example.com/s.json"}')

    def test_unknown_field_rejected(self):
        schema = contract.load("schemas/scenario.schema.json")
        bad = {"scenario_id": "CS-01", "class": "complete_supported",
               "description": "x", "principals": [], "states": [],
               "initial": "s0", "transitions": [],
               "trace": {"events": [], "request_scope": dict(SA)},
               "oracle_hint": {"kind": "stit_holds"}, "smuggled": 1}
        with self.assertRaises(ValueError):
            contract.validate(bad, schema)

    def test_authority_true_rejected(self):
        schema = contract.load("schemas/annotation.schema.json")
        annotation = evaluator.make_annotation(
            model_version="m1", trace_digest="0" * 64, scope=dict(SA),
            producer="p", observed=["o"], derived=["d"],
            unknowns=[], counterfactuals=[], confidence="SUPPORTED")
        annotation["authority"] = True
        with self.assertRaises(ValueError):
            contract.validate(annotation, schema)

    def test_annotation_requires_all_fields(self):
        schema = contract.load("schemas/annotation.schema.json")
        annotation = evaluator.make_annotation(
            model_version="m1", trace_digest="0" * 64, scope=dict(SA),
            producer="p", observed=["o"], derived=["d"],
            unknowns=[], counterfactuals=[], confidence="SUPPORTED")
        del annotation["counterfactuals"]
        with self.assertRaises(ValueError):
            contract.validate(annotation, schema)

    def test_traversal_detected(self):
        self.assertTrue(contract.has_traversal("../evil"))
        self.assertTrue(contract.has_traversal("..\\evil"))
        self.assertFalse(contract.has_traversal("prin_A"))
        self.assertFalse(contract.has_traversal("a\\b"))

    def test_legal_blame_out_of_scope(self):
        vocabulary = load("responsibility-contract.json")["vocabulary"]
        self.assertEqual(vocabulary["legal_moral_blame"],
                         "OUT_OF_SCOPE, always; no model output may assert it")


class TestModelCore(unittest.TestCase):
    def test_grant_allow_effect(self):
        game = _game_grant_allow()
        decision = models.gateway_decide(game, "s0", "prin_A", "read",
                                         {"grant_id": "grant1"})
        self.assertEqual(decision, "ALLOW")

    def test_annotation_cannot_flip_deny(self):
        game = _game_grant_allow()
        game["states"][0]["authority"]["grants"]["grant1"]["revoked"] = True
        decision = models.gateway_decide(game, "s0", "prin_A", "read",
                                         {"grant_id": "grant1"})
        self.assertEqual(decision, "DENY")
        # Even an annotation claiming allow must not change the outcome.
        annotation = evaluator.make_annotation(
            model_version="m1", trace_digest="0" * 64, scope=dict(SA),
            producer="p", observed=["revoked grant"], derived=["allow"],
            unknowns=[], counterfactuals=[], confidence="SUPPORTED")
        self.assertEqual(models.gateway_decide(
            game, "s0", "prin_A", "read", {"grant_id": "grant1"},
            annotation=annotation), "DENY")

    def test_no_alternative_abstains(self):
        game = {"states": [
            {"state_id": "s0", "authority": {"grants": {"g": {
                "scope": dict(SA), "actions": ["read"], "revoked": False,
                "expired": False}}}, "phase": "ready"},
            {"state_id": "s1", "authority": {}, "phase": "done"}],
            "initial": "s0",
            "transitions": [
                {"from": "s0", "actor": "prin_A", "action": "read",
                 "args": {}, "to": "s1",
                 "authority_required": {"grant_id": "g"},
                 "outcome": "effect", "environment_move": None,
                 "audit_ref": "ev1"}]}
        result = models.stit_holds(game, "prin_A", {"kind": "phase", "phase": "done"},
                                   ["s0", "s1"])
        self.assertFalse(result["holds"])
        self.assertEqual(result["reason"], "no_available_alternative")

    def test_stit_holds_with_difference_making_alternative(self):
        game = _game_grant_allow()
        result = models.stit_holds(game, "prin_A", {"kind": "phase", "phase": "done"},
                                   ["s0", "s1"])
        self.assertTrue(result["holds"], msg=result)

    def test_revoked_grant_unavailable(self):
        game = _game_grant_allow()
        game["states"][0]["authority"]["grants"]["grant1"]["revoked"] = True
        choices = models.available_actions(game, "s0", "prin_A")
        kinds = {a["action"]: a["standing"] for a in choices}
        self.assertEqual(kinds.get("read"), "revoked")
        self.assertNotIn("read", [a["action"] for a in choices
                                  if a["standing"] == "authorised"])

    def test_unknown_outcome_needs_reconciliation(self):
        game = _game_grant_allow()
        game["transitions"][0]["outcome"] = "unknown"
        with self.assertRaises(models.NeedsReconciliation):
            models.execute(game, "s0", "prin_A", "read", {"grant_id": "grant1"})
        # Blind retry with a fresh key is refused; reconcile resolves.
        with self.assertRaises(models.BlindRetryRefused):
            models.reconcile(game, "s0", "prin_A", "read", {"grant_id": "grant1"},
                             idempotency_key="k-new")
        outcome = models.reconcile(game, "s0", "prin_A", "read",
                                   {"grant_id": "grant1"})
        self.assertIn(outcome["resolution"], ("effect", "failed"))

    def test_coalition_ability_requires_environment(self):
        game = _game_grant_allow()
        game["transitions"].append(
            {"from": "s0", "actor": "env", "action": "perturb",
             "args": {}, "to": "s0", "authority_required": None,
             "outcome": "effect", "environment_move": "perturb",
             "audit_ref": "ev9"})
        result = models.atl_holds(game, ["prin_A"],
                                  {"eventually": {"kind": "phase", "phase": "done"}})
        self.assertIn("holds", result)
        # Without modeled environment moves where declared adversarial: abstain.
        game2 = copy.deepcopy(game)
        for transition in game2["transitions"]:
            transition["environment_move"] = None
        result2 = models.atl_holds(game2, ["prin_A"],
                                   {"eventually": {"kind": "phase", "phase": "done"}},
                                   adversarial_env=True)
        self.assertFalse(result2["holds"])

    def test_identity_keys_are_canonical(self):
        first = models.stit_holds(_game_grant_allow(), "prin_A",
                                  {"kind": "phase", "phase": "done"}, ["s0", "s1"])
        second = models.stit_holds(_game_grant_allow(), "prin_A",
                                   {"kind": "phase", "phase": "done"}, ["s0", "s1"])
        self.assertEqual(first["holds"], second["holds"])
        # Display names never enter attribution keys.
        self.assertNotIn("display", json.dumps(first))

    def test_model_determinism(self):
        game = _game_grant_allow()
        first = models.evaluate_game(game, ["prin_A"], "s0")
        second = models.evaluate_game(game, ["prin_A"], "s0")
        self.assertEqual(first["digest"], second["digest"])


class TestCorpus(unittest.TestCase):
    def test_48_balanced_unique_deterministic(self):
        corpus = load("corpus.json")
        self.assertEqual(corpus["scenario_count"], 48)
        by_class = {}
        for case in corpus["cases"]:
            by_class[case["class"]] = by_class.get(case["class"], 0) + 1
        self.assertEqual(by_class, {"complete_supported": 12,
                                    "complete_no_responsibility": 12,
                                    "underdetermined": 12,
                                    "adversarial_or_invalid": 12})
        self.assertEqual(len({c["scenario_id"] for c in corpus["cases"]}), 48)
        self.assertEqual(len({c["semantic_digest"] for c in corpus["cases"]}), 48)
        first, _ = build_corpus.build()
        self.assertEqual(first["cases"], corpus["cases"])

    def test_quota_coverage(self):
        corpus = load("corpus.json")
        tags: dict[str, int] = {}
        for case in corpus["cases"]:
            for tag in case.get("tags", []):
                tags[tag] = tags.get(tag, 0) + 1
        for tag, minimum in (("denial", 8), ("delegation", 8), ("revocation", 8),
                             ("unknown", 4), ("coalition", 4),
                             ("incomplete", 4), ("identity", 4)):
            self.assertGreaterEqual(tags.get(tag, 0), minimum, msg=tag)

    def test_oracle_separate_and_malformed_rejected(self):
        oracle = load("oracle.json")
        corpus = load("corpus.json")
        self.assertEqual(len(oracle["entries"]), 48)
        for case in corpus["cases"]:
            self.assertIn(case["scenario_id"], oracle["entries"])
            self.assertNotIn("expected_stit", json.dumps(case))
        with self.assertRaises(ValueError):
            build_corpus.validate_case({"scenario_id": "CS-01"})
        dup = copy.deepcopy(corpus["cases"][0])
        with self.assertRaises(ValueError):
            build_corpus.validate_case(dup, known_ids={dup["scenario_id"]})

    def test_required_kinds_present(self):
        corpus = load("corpus.json")
        kinds = set()
        for case in corpus["cases"]:
            kinds.add(case["oracle_hint"]["kind"])
        for kind in ("stit_holds", "stit_absent", "atl_holds", "atl_absent",
                     "underdetermined", "invalid"):
            self.assertIn(kind, kinds, msg=kind)


class TestRunnerEvaluatorSkeleton(unittest.TestCase):
    def _sample(self):
        corpus = {c["scenario_id"]: c for c in load("corpus.json")["cases"]}
        return corpus["CS-01"], corpus["UD-01"]

    def test_observation_binds_trace_digest(self):
        scenario, _ = self._sample()
        obs = runner.generate_observation(scenario, "A", 1)["core"]
        self.assertEqual(obs["scenario_id"], "CS-01")
        self.assertEqual(obs["placement"], "A")
        self.assertRegex(obs["trace_digest"], r"^[0-9a-f]{64}$")
        self.assertIn("annotation", obs)
        self.assertFalse(obs["annotation"]["authority"])

    def test_evaluator_recomputes_oracle_sample(self):
        scenario, _ = self._sample()
        oracle = load("oracle.json")["entries"]
        result = evaluator.evaluate_cell(scenario, "A", 1, oracle["CS-01"])
        self.assertTrue(result["agreement"])
        self.assertEqual(result["invariant_violations"], {})

    def test_evaluator_catches_forged_authority(self):
        scenario, _ = self._sample()
        oracle = load("oracle.json")["entries"]
        obs = runner.generate_observation(scenario, "A", 1)["core"]
        tampered = copy.deepcopy(obs)
        tampered["annotation"]["authority"] = True
        result = evaluator.check_observation(tampered, scenario, oracle["CS-01"])
        self.assertIn("R2", result["violations"])

    def test_abstention_on_incomplete(self):
        _, scenario = self._sample()
        oracle = load("oracle.json")["entries"]
        result = evaluator.evaluate_cell(scenario, "A", 1, oracle["UD-01"])
        self.assertEqual(result["verdict"], "UNDERDETERMINED")


class TestProbesAndQuestionnaire(unittest.TestCase):
    def test_probe_a_deny_stands(self):
        outcome = evaluator.probe_allow_after_deny()
        self.assertEqual(outcome["gateway_decision"], "DENY")
        self.assertFalse(outcome["influence_detected"])

    def test_probe_f_identity_collapse(self):
        outcome = evaluator.probe_identity_collapse()
        self.assertTrue(outcome["identity_fail_detected"])

    def test_probe_p_parser_battery(self):
        outcome = evaluator.probe_parser_battery()
        self.assertTrue(all(outcome["rejected"].values()))
        self.assertEqual(len(outcome["rejected"]), 6)

    def test_questionnaire_has_ten_questions(self):
        text = (S1017 / "operator-questionnaire.md").read_text(encoding="utf-8")
        for number in range(1, 11):
            self.assertIn(f"{number}.", text)
        self.assertIn("1A 2A", text)

    def test_expected_binding_has_no_invented_ids(self):
        text = (S1017 / "sources" / "snap-05-s1-016-expected-binding.md").read_text(
            encoding="utf-8")
        self.assertNotRegex(text, r"goal_[A-Z0-9]{20,}")
        self.assertNotRegex(text, r"reval_[A-Z0-9]{20,}")
        self.assertNotRegex(text, r"rcamp_[A-Z0-9]{20,}")
        self.assertNotRegex(text, r"[0-9a-f]{64}")


class TestSourcesPresent(unittest.TestCase):
    def test_registry_roles_and_hashes(self):
        registry = load("source-registry.json")
        roles = {s["role"] for s in registry["sources"]}
        for role in ("ontology", "audit-boundary", "formal-constraints",
                     "formal-execution", "lineage-binding", "stit-primary",
                     "atl-primary", "causality-limits"):
            self.assertIn(role, roles)
        for entry in registry["sources"]:
            raw = (S1017 / entry["snapshot_path"].split("S1-017/")[-1]).read_bytes()
            self.assertEqual(sha(raw), entry["sha256"])
            self.assertEqual(len(raw), entry["bytes"])

    def test_contract_terms_frozen(self):
        vocabulary = load("responsibility-contract.json")["vocabulary"]
        self.assertIn("choice_point", vocabulary)
        self.assertIn("available_alternative", vocabulary)
        self.assertEqual(len(load("responsibility-contract.json")["hard_invariants"]), 14)


if __name__ == "__main__":
    unittest.main()


class TestPhaseBNonCircularity(unittest.TestCase):
    """Phase B: producer must not read the answer key."""

    def _cases(self):
        return json.loads((S1017 / "corpus.json").read_text("utf-8"))["cases"]

    def test_analyzer_ignores_oracle_hint(self):
        for case in self._cases():
            forged = copy.deepcopy(case)
            forged["oracle_hint"] = {"kind": "forged"}
            base = runner.analyze_scenario(case, "A", 1)
            other = runner.analyze_scenario(forged, "A", 1)
            for field in ("verdict", "confidence", "unknowns", "disagreement"):
                self.assertEqual(
                    base[field], other[field],
                    f"{case['scenario_id']} changed {field} with forged hint")

    def test_oracle_holds_no_engine_internals(self):
        oracle = json.loads((S1017 / "oracle.json").read_text("utf-8"))
        for sid, entry in oracle["entries"].items():
            self.assertNotIn("expected_stit", entry, sid)
            self.assertNotIn("expected_atl", entry, sid)
            self.assertIn("expected_verdict", entry, sid)
            self.assertIn("expected_confidence", entry, sid)
            self.assertIn("construction", entry, sid)

    def test_oracle_verdict_matches_construction_mapping(self):
        oracle = json.loads((S1017 / "oracle.json").read_text("utf-8"))
        mapping = {"stit_holds": ("ATTRIBUTION", "PROVEN"),
                   "atl_holds": ("ATTRIBUTION", "PROVEN"),
                   "stit_absent": ("NO_ATTRIBUTION", "SUPPORTED"),
                   "atl_absent": ("NO_ATTRIBUTION", "SUPPORTED"),
                   "underdetermined": ("UNDERDETERMINED", "UNDERDETERMINED"),
                   "invalid": ("UNDERDETERMINED", "UNDERDETERMINED")}
        for sid, entry in oracle["entries"].items():
            expected = mapping[entry["construction"]]
            self.assertEqual(entry["expected_verdict"], expected[0], sid)
            self.assertEqual(entry["expected_confidence"], expected[1], sid)


class TestPhaseBSemantics(unittest.TestCase):
    def _cases(self):
        return json.loads((S1017 / "corpus.json").read_text("utf-8"))["cases"]

    def _oracle(self):
        return json.loads((S1017 / "oracle.json").read_text("utf-8"))["entries"]

    def test_full_corpus_agreement_every_placement(self):
        oracle = self._oracle()
        for case in self._cases():
            for placement in runner.PLACEMENTS:
                out = runner.analyze_scenario(case, placement, 1)
                entry = oracle[case["scenario_id"]]
                self.assertEqual(
                    out["verdict"], entry["expected_verdict"],
                    f"{case['scenario_id']}/{placement}: {out['unknowns']} "
                    f"stit={out['stit'].get('reason')} atl={out['atl'].get('reason')}")
                self.assertEqual(out["confidence"], entry["expected_confidence"],
                                 case["scenario_id"])

    def test_unknown_without_reconciliation_abstains(self):
        game = runner.game_of(self._cases()[0])
        scenario = copy.deepcopy(self._cases()[0])
        scenario["transitions"] = [dict(t) for t in scenario["transitions"]]
        for transition in scenario["transitions"]:
            if transition.get("outcome") == "effect":
                transition["outcome"] = "unknown"  # crash, no reconciliation
        out = runner.analyze_scenario(scenario, "A", 1)
        self.assertEqual(out["verdict"], "UNDERDETERMINED")

    def test_disagreement_between_models_abstains(self):
        case = next(c for c in self._cases() if c["scenario_id"] == "UD-04")
        out = runner.analyze_scenario(case, "A", 1)
        self.assertEqual(out["verdict"], "UNDERDETERMINED")
        self.assertTrue(out["disagreement"])

    def test_atl_question_without_env_moves_abstains(self):
        case = next(c for c in self._cases() if c["scenario_id"] == "UD-10")
        out = runner.analyze_scenario(case, "A", 1)
        self.assertEqual(out["verdict"], "UNDERDETERMINED")

    def test_no_effect_under_revoked_grant(self):
        case = next(c for c in self._cases() if c["scenario_id"] == "CS-04")
        for transition in case["transitions"]:
            if transition.get("authority_required"):
                self.assertNotEqual(transition.get("outcome"), "effect",
                                    "revoked grant must not produce an effect")
        out = runner.analyze_scenario(case, "A", 1)
        self.assertEqual(out["verdict"], "NO_ATTRIBUTION")


class TestPhaseBInfrastructure(unittest.TestCase):
    def test_dependency_gate_script_exists_and_expected_refs(self):
        source = (S1017 / "dependency_gate.py").read_text("utf-8")
        self.assertIn("S1-004", source)
        self.assertIn("S1-016", source)
        self.assertIn("origin/main", source)

    def test_freeze_script_exists(self):
        self.assertTrue((S1017 / "freeze.py").is_file())
        self.assertTrue((S1017 / "replicate.py").is_file())

    def test_sensitivity_uses_no_wallclock_dimension(self):
        source = (S1017 / "sensitivity.py").read_text("utf-8")
        self.assertNotIn("latency_parsimony", source)
        self.assertIn("steps_parsimony", source)

    def test_evaluator_exposes_full_probe_set(self):
        source = (S1017 / "evaluator.py").read_text("utf-8")
        for letter in "ABCDEFGHIJKLMNOP":
            self.assertIn(f"probe_{letter.lower()}_", source)

    def test_make_bundle_operator_fail_closed(self):
        source = (S1017 / "make_bundle.py").read_text("utf-8")
        self.assertIn("verify_operator_decision", source)
        self.assertIn("FORBIDDEN", source)
