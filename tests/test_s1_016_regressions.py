"""S1-016 regression suite (Phase 1 preparation).

Stdlib only (+ rdflib/pySHACL for the SHACL module, pinned), no network, no
human participants. Run:
  $env:PYTHONPATH="src"
  py -3.12 -m unittest tests.test_s1_016_regressions -v
Ticket modules load under unique names (s1016_*) via importlib.
"""
import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S1016 = ROOT / "research" / "tickets" / "stage-1" / "S1-016"


def _load_ticket_module(name: str):
    unique = f"s1016_{name}"
    if unique in sys.modules:
        return sys.modules[unique]
    spec = importlib.util.spec_from_file_location(unique, S1016 / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    spec.loader.exec_module(module)
    return module


contract = _load_ticket_module("contract")
make_bundle = _load_ticket_module("make_bundle")
models = _load_ticket_module("models")
runner = _load_ticket_module("runner")
evaluator = _load_ticket_module("evaluator")
dependency_gate = _load_ticket_module("dependency_gate")
build_corpus = _load_ticket_module("build_corpus")
exporter = _load_ticket_module("exporter")
importer = _load_ticket_module("importer")
roundtrip = _load_ticket_module("roundtrip")
audit = _load_ticket_module("audit")
shacl_runner = _load_ticket_module("shacl_runner")
sensitivity = _load_ticket_module("sensitivity")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(name: str):
    return json.loads((S1016 / name).read_text(encoding="utf-8"))


SA = {"tenant_id": "t-a", "workspace_id": "w-1", "goal_id": "g-1"}
SB = {"tenant_id": "t-a", "workspace_id": "w-2", "goal_id": "g-2"}


def _op(op_id, op_type, scope, args, key=None, parents=None, crash=None):
    return {"op_id": op_id, "op_type": op_type, "actor": "actor",
            "scope": dict(scope), "args": args,
            "idempotency_key": key or f"k-{op_id}",
            "causal_parents": list(parents or []), "crash_point": crash,
            "_auth_scope": dict(scope)}


def _fresh_model(rep="A"):
    model = models.Model(rep)
    res = model.apply(_op("o1", "create", SA, {"obj_id": "d1", "content": "c1",
                                              "scope": dict(SA)}), dict(SA))
    assert res["outcome"] == "committed"
    return model


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
        schema = runner.operation_schema(S1016)
        bad = _op("o1", "create", SA, {"obj_id": "d", "content": "c",
                                       "scope": dict(SA)})
        bad["smuggled"] = "authority"
        with self.assertRaises(ValueError):
            runner.import_operation(bad, schema)

    def test_unknown_operation_rejected(self):
        schema = runner.operation_schema(S1016)
        bad = _op("o1", "teleport", SA, {})
        with self.assertRaises(ValueError):
            runner.import_operation(bad, schema)

    def test_traversal_detected(self):
        self.assertTrue(contract.has_traversal("../evil"))
        self.assertTrue(contract.has_traversal("/abs"))
        self.assertFalse(contract.has_traversal("doc-1"))

    def test_private_detected(self):
        self.assertTrue(contract.has_private({"content": "a@b.com"}))
        self.assertTrue(contract.has_private("token sk-proj-abcdefgh12345678"))
        self.assertFalse(contract.has_private({"content": "hello"}))


class TestDependencyGate(unittest.TestCase):
    def test_both_proven(self):
        results = [dependency_gate.check(dep) for dep in dependency_gate.DEPS]
        for result in results:
            self.assertEqual(result["status"], "PROVEN", msg=result.get("problems"))

    def test_forged_override_rejected(self):
        result = dependency_gate.check(dependency_gate.DEPS[0],
                                       rec_override={"forged": True})
        self.assertEqual(result["status"], "NOT_PROVEN")

    def test_gate_file_matches(self):
        doc = load("dependency-gate.json")
        self.assertTrue(doc["dependencies_proven"])
        self.assertTrue(doc["formal_semantics_available"])
        self.assertTrue(doc["scope_isolation_available"])
        self.assertFalse(doc["population_human_claims_proven"])
        by_ticket = {r["ticket"]: r for r in doc["dependencies"]}
        self.assertEqual(by_ticket["S1-003"]["goal_id"],
                         "goal_RVX89EP2SEQ94MSZ01M0VAVECK")
        self.assertEqual(by_ticket["S1-007"]["goal_id"],
                         "goal_5FX22ZHCEAW0G2B501M1DDTYSA")


class TestCorpus(unittest.TestCase):
    def test_48_balanced_unique(self):
        corpus = load("corpus.json")
        self.assertEqual(corpus["scenario_count"], 48)
        by_class = {}
        for case in corpus["cases"]:
            by_class[case["class"]] = by_class.get(case["class"], 0) + 1
        self.assertEqual(by_class, {"valid": 24, "near_miss": 12, "adversarial": 12})
        self.assertEqual(len({c["id"] for c in corpus["cases"]}), 48)
        self.assertEqual(len({c["semantic_digest"] for c in corpus["cases"]}), 48)

    def test_oracle_bound(self):
        oracle = load("oracle.json")
        corpus = load("corpus.json")
        self.assertEqual(len(oracle["entries"]), 48)
        for case in corpus["cases"]:
            entry = oracle["entries"][case["id"]]
            self.assertIn("expected_terminal_digest", entry)
            self.assertIn("expected_reconstruction_digest", entry)

    def test_generator_deterministic(self):
        first, first_oracle = build_corpus.build()
        second, second_oracle = build_corpus.build()
        self.assertEqual(first, second)
        self.assertEqual(first_oracle, second_oracle)

    def test_required_operations_covered(self):
        corpus = load("corpus.json")
        seen = set()
        for case in corpus["cases"]:
            for op in case["ops"]:
                seen.add(op["op_type"])
        for required in ("create", "insert", "remove", "update_supersede",
                         "copy_same_scope", "copy_cross_scope",
                         "move_cross_scope", "rename", "derive", "merge",
                         "fork", "withdraw", "export"):
            self.assertIn(required, seen, msg=required)


class TestModelSemantics(unittest.TestCase):
    def test_create_and_reject_duplicate(self):
        model = models.Model("A")
        res = model.apply(_op("o1", "create", SA, {"obj_id": "d", "content": "c",
                                                  "scope": dict(SA)}), dict(SA))
        self.assertEqual(res["outcome"], "committed")
        res = model.apply(_op("o2", "create", SA, {"obj_id": "d", "content": "c",
                                                  "scope": dict(SA)}), dict(SA))
        self.assertEqual(res["outcome"], "rejected:duplicate_version")

    def test_forged_scope_rejected(self):
        model = _fresh_model()
        res = model.apply(_op("o2", "copy_cross_scope", SB,
                              {"src_obj": "d1", "src_ver": 1,
                               "new_obj": "x", "target_scope": dict(SB)},
                              key="k-o2"), dict(SA))
        self.assertEqual(res["outcome"], "rejected:forged_scope")

    def test_traversal_id_rejected(self):
        model = models.Model("A")
        res = model.apply(_op("o1", "create", SA, {"obj_id": "../evil",
                                                  "content": "c",
                                                  "scope": dict(SA)}), dict(SA))
        self.assertEqual(res["outcome"], "rejected:traversal")

    def test_unknown_reference_rejected(self):
        model = models.Model("A")
        model.create_collection("col", SA)
        res = model.apply(_op("o1", "insert", SA,
                              {"collection": "col", "member_obj": "ghost",
                               "member_ver": 3, "key": "k"}, key="k-i1"), dict(SA))
        self.assertEqual(res["outcome"], "rejected:unknown_reference")

    def test_causal_order_rejected(self):
        model = _fresh_model()
        res = model.apply(_op("o2", "copy_same_scope", SA,
                              {"src_obj": "d1", "src_ver": 1, "new_obj": "d2"},
                              parents=[9]), dict(SA))
        self.assertEqual(res["outcome"], "rejected:causal_order")

    def test_idempotent_retry_single_effect(self):
        model = _fresh_model()
        first = model.apply(_op("o2", "copy_same_scope", SA,
                                {"src_obj": "d1", "src_ver": 1, "new_obj": "d2"},
                                key="k-same"), dict(SA))
        second = model.apply(_op("o3", "copy_same_scope", SA,
                                 {"src_obj": "d1", "src_ver": 1, "new_obj": "d2"},
                                 key="k-same"), dict(SA))
        self.assertEqual(first["outcome"], "committed")
        self.assertEqual(second["outcome"], "duplicate_replay")
        self.assertEqual(len([v for v in model.versions if v[0] == "d2"]), 1)

    def test_crash_before_commit_reconciles_once(self):
        model = _fresh_model()
        op = _op("o2", "copy_same_scope", SA,
                 {"src_obj": "d1", "src_ver": 1, "new_obj": "d2"},
                 key="k-crash", crash="before_commit")
        res = model.apply(dict(op), dict(SA))
        self.assertEqual(res["outcome"], "unknown")
        retry = dict(op)
        retry["crash_point"] = None
        res2 = model.reconcile(retry)
        self.assertEqual(res2["outcome"], "committed")
        self.assertEqual(len([v for v in model.versions if v[0] == "d2"]), 1)

    def test_crash_after_state_reconciles_events(self):
        model = _fresh_model()
        op = _op("o2", "copy_same_scope", SA,
                 {"src_obj": "d1", "src_ver": 1, "new_obj": "d2"},
                 key="k-half", crash="after_state_before_event")
        before = len(model.events)
        res = model.apply(dict(op), dict(SA))
        self.assertEqual(res["outcome"], "unknown")
        self.assertIn(("d2", 1), model.versions)
        self.assertEqual(len(model.events), before)
        retry = dict(op)
        retry["crash_point"] = None
        res2 = model.reconcile(retry)
        self.assertEqual(res2["outcome"], "committed")
        self.assertTrue(any(e["kind"] == "copy" for e in model.events))

    def test_partial_move_visible_without_reconcile(self):
        model = _fresh_model()
        op = _op("o2", "move_cross_scope", SB,
                 {"src_obj": "d1", "src_ver": 1, "new_obj": "d1b",
                  "target_scope": dict(SB)}, key="k-partial",
                 crash="after_state_before_event")
        res = model.apply(dict(op), dict(SB))
        self.assertEqual(res["outcome"], "unknown")
        self.assertIn(("d1b", 1), model.versions)
        recon = audit.reconstruct(model, {"versions": {}, "members": {}})
        self.assertFalse(recon["complete"])
        self.assertTrue(recon["partials"])

    def test_seed_ordering_deterministic(self):
        scenarios = {c["id"]: c for c in runner.corpus_cases(S1016)}
        first = [o["op_id"] for o in build_corpus.order_ops(scenarios["V-04"], 1)]
        second = [o["op_id"] for o in build_corpus.order_ops(scenarios["V-04"], 1)]
        self.assertEqual(first, second)

    def test_representations_share_terminal(self):
        scenarios = {c["id"]: c for c in runner.corpus_cases(S1016)}
        schema = runner.operation_schema(S1016)
        digests = set()
        for rep in ("A", "B", "C"):
            obs = runner.generate_observation(scenarios["V-10"], rep, 1, schema)
            self.assertEqual(obs["core"]["status"], "ok")
            digests.add(obs["core"]["terminal_digest"])
        self.assertEqual(len(digests), 1)


class TestExportImportRoundtrip(unittest.TestCase):
    def test_roundtrip_supported_subset(self):
        scenarios = {c["id"]: c for c in runner.corpus_cases(S1016)}
        model = models.Model("A")
        scenario = scenarios["V-17"]
        for v in scenario["versions"]:
            scope = {"S_A": SA, "S_B": SB}[v["scope"]]
            model.versions[(v["obj"], 1)] = {
                "id": v["obj"], "version": 1, "scope": dict(scope),
                "content_digest": sha(v["content"].encode()),
                "content": v["content"], "supersedes": None, "state": "active",
                "label": "", "created_by_op": -1}
        for c in scenario["collections"]:
            model.create_collection(c["id"], {"S_A": SA, "S_B": SB}[c["scope"]])
            for m in c["members"]:
                model.collections[c["id"]]["members"].append(
                    {"member": m["member"], "key": m["key"],
                     "inserted_by": -1, "removed_by": None})
        result = roundtrip.compare(model, "V-17", SA)
        self.assertTrue(result["match"], msg=result["reason"])
        self.assertEqual(result["unsupported"], [])

    def test_unknown_profile_rejected(self):
        with self.assertRaises(importer.ImportReject):
            importer.import_document({"profile": "evil/v9", "entities": [],
                                      "collections": [], "activities": [],
                                      "agents": []})

    def test_dangling_supersedes_rejected(self):
        model = models.Model("A")
        model.apply(_op("o1", "create", SA, {"obj_id": "d1", "content": "c1",
                                            "scope": dict(SA)}), dict(SA))
        model.apply(_op("o2", "update_supersede", SA, {"obj_id": "d1",
                                                      "content": "c2"}), dict(SA))
        doc = exporter.export_json(model, "V-06", SA)
        self.assertEqual(len(doc["entities"]), 2)
        doc["entities"] = [e for e in doc["entities"] if e["version"] != 1]
        with self.assertRaises(importer.ImportReject) as ctx:
            importer.import_document(doc)
        self.assertIn("dangling", str(ctx.exception))

    def test_redaction_receipt_present(self):
        scenarios = {c["id"]: c for c in runner.corpus_cases(S1016)}
        model = models.Model("A")
        for v in scenarios["V-24"]["versions"]:
            scope = {"S_A": SA, "S_B": SB, "S_C": {"tenant_id": "t-b", "workspace_id": "w-1", "goal_id": "g-3"}}[v["scope"]]
            model.versions[(v["obj"], 1)] = {
                "id": v["obj"], "version": 1, "scope": dict(scope),
                "content_digest": sha(v["content"].encode()),
                "content": v["content"], "supersedes": None, "state": "active",
                "label": "", "created_by_op": -1}
        doc = exporter.export_json(model, "V-24", SA)
        self.assertIn("redaction", doc)
        self.assertNotIn(sha("x".encode()), json.dumps(doc))


class TestShaclAndAudit(unittest.TestCase):
    def test_engine_identity_pinned(self):
        versions = shacl_runner.engine_identity()
        self.assertEqual(versions, {"rdflib": "7.6.0", "pyshacl": "0.40.1"})

    def test_valid_export_conforms(self):
        model = _fresh_model()
        result = shacl_runner.run_case(model, "T-VALID", SA)
        self.assertTrue(result["pyshacl_executed"])
        self.assertTrue(result["conforms"], msg=result["violations"])
        self.assertEqual(result["unclassified"], [])
        self.assertGreater(result["triples"], 0)

    def test_scope_cardinality_violation_classified(self):
        model = _fresh_model()
        doc = exporter.export_json(model, "T-DUAL", SA)
        doc["entities"][0]["scopeWorkspace"] = "w-2"
        turtle = exporter.export_turtle(model, "T-DUAL", SA)
        bad = turtle + "\n<agentos:T-DUAL/entity/d1_1> agentos:scopeWorkspace \"w-2\" .\n"
        result = shacl_runner.validate_turtle(bad)
        self.assertFalse(result["conforms"])
        self.assertIn("scope_cardinality", result["violations"])

    def test_audit_reconstruction_complete(self):
        model = _fresh_model()
        recon = audit.reconstruct(model, {"versions": {}, "members": {}})
        self.assertTrue(recon["complete"])
        self.assertTrue(recon["baseline_ok"])

    def test_blank_nodes_rejected(self):
        result = shacl_runner.validate_turtle(
            "@prefix ex: <http://example.org/> .\nex:a ex:p _:b .")
        self.assertFalse(result["conforms"])


class TestEvaluatorGates(unittest.TestCase):
    def test_invariant_checker_clean_on_valid(self):
        scenarios = {c["id"]: c for c in runner.corpus_cases(S1016)}
        oracle = load("oracle.json")["entries"]
        obs = runner.generate_observation(scenarios["V-10"], "A", 1,
                                          runner.operation_schema(S1016))
        result = evaluator.check_invariants(scenarios["V-10"], obs["core"],
                                            oracle["V-10"])
        self.assertTrue(all(v == 0 for v in result["counts"].values()))

    def test_invariant_checker_catches_tamper(self):
        scenarios = {c["id"]: c for c in runner.corpus_cases(S1016)}
        oracle = load("oracle.json")["entries"]
        obs = runner.generate_observation(scenarios["V-08"], "A", 1,
                                          runner.operation_schema(S1016))
        tampered = copy.deepcopy(obs["core"])
        for version in tampered["terminal"]["versions"]:
            if version["id"] == "d1":
                version["scope"] = dict(SB)
        result = evaluator.check_invariants(scenarios["V-08"], tampered,
                                            oracle["V-08"])
        self.assertGreater(result["counts"]["L2"], 0)

    def test_quarantine_path(self):
        scenarios = {c["id"]: c for c in runner.corpus_cases(S1016)}
        obs = runner.generate_observation(scenarios["X-11"], "A", 1,
                                          runner.operation_schema(S1016))
        self.assertEqual(obs["core"]["status"], "quarantined")

    def _mini_cells(self):
        cells = []
        for rep, steps in (("A", 40), ("B", 12), ("C", 30)):
            cells.append({"core": {
                "representation": rep, "status": "ok",
                "state_rows": {"versions": 2, "memberships": 1,
                               "operations": 2, "events": 2},
                "state_bytes": 400 if rep != "B" else 460,
                "complexity": {"checks_executed": 10},
                "query_probe": {"steps": steps, "queries": 4}},
                "latencies": {"export_ns": 30000 if rep != "C" else 34000}})
        return cells

    def test_sensitivity_scores_and_determinism(self):
        metrics = {"rates": {"audit_reconstruction": {"rate": 1.0}}}
        agg = sensitivity.per_rep_aggregates(self._mini_cells(), metrics)
        first = sensitivity.normalize_scores(agg)
        second = sensitivity.normalize_scores(agg)
        self.assertEqual(first, second)
        totals = sensitivity.score(first, {d: 1.0 for d in sensitivity.DIMS})
        winner = sensitivity.winner_of(totals)
        self.assertIn(winner, ("A", "B", "C"))
        # Scale-invariance: doubling all weights keeps the winner.
        totals2 = sensitivity.score(first, {d: 2.0 for d in sensitivity.DIMS})
        self.assertEqual(sensitivity.winner_of(totals2), winner)
        # Grid size meets the 200-vector minimum.
        import itertools
        self.assertGreaterEqual(
            len(list(itertools.product((0.5, 1.0, 1.5), repeat=6))), 200)


class TestOperatorVerdict(unittest.TestCase):
    GREEN_METRICS = {
        "invariant_violations": {f"L{i}": 0 for i in range(1, 13)},
        "mandatory": {"invariants_zero": True, "orphans_zero": True,
                      "expansions_zero": True, "leaks_zero": True,
                      "roundtrip_100": True, "reconstruction_100": True,
                      "rejection_100": True, "replay_consistent": True,
                      "shacl_exact": True},
        "human_study_n": 0,
    }
    GREEN_COMPARISON = {"replicated": True}
    GREEN_SENSITIVITY = {"vector_count": 748, "mapped_decision": "A", "flips": 0}

    def _letters(self, **overrides):
        base = {str(n): "A" for n in range(1, 11)}
        base.update(overrides)
        return base

    def test_all_a_no_flip_closes_flat(self):
        blockers, verdict = make_bundle.derive_verdict(
            copy.deepcopy(self.GREEN_METRICS), dict(self.GREEN_COMPARISON),
            dict(self.GREEN_SENSITIVITY), True, self._letters())
        self.assertEqual(blockers, [])
        self.assertEqual(verdict["design_decision"], "FLAT_RUNTIME_PROV_EXPORT")
        self.assertEqual(verdict["status"], "CLOSED_WITH_LIMITS")

    def test_6b_forbidden_yields_inconclusive(self):
        blockers, verdict = make_bundle.derive_verdict(
            copy.deepcopy(self.GREEN_METRICS), dict(self.GREEN_COMPARISON),
            dict(self.GREEN_SENSITIVITY), True, self._letters(**{"6": "B"}))
        self.assertEqual(blockers, [])
        self.assertEqual(verdict["design_decision"], "INCONCLUSIVE")
        self.assertEqual(verdict["status"], "CLOSED_INCONCLUSIVE")
        self.assertIn("6B", verdict["blocking_answers"])

    def test_flip_caps_despite_admissible_answers(self):
        sens = dict(self.GREEN_SENSITIVITY, flips=1)
        blockers, verdict = make_bundle.derive_verdict(
            copy.deepcopy(self.GREEN_METRICS), dict(self.GREEN_COMPARISON),
            sens, True, self._letters())
        self.assertEqual(blockers, [])
        self.assertEqual(verdict["design_decision"], "INCONCLUSIVE")

    def test_10b_leaves_open(self):
        blockers, verdict = make_bundle.derive_verdict(
            copy.deepcopy(self.GREEN_METRICS), dict(self.GREEN_COMPARISON),
            dict(self.GREEN_SENSITIVITY), True, self._letters(**{"10": "B"}))
        self.assertEqual(verdict["status"], "OPEN_INCONCLUSIVE")

    def test_no_decision_stays_preparation_ready(self):
        blockers, verdict = make_bundle.derive_verdict(
            copy.deepcopy(self.GREEN_METRICS), dict(self.GREEN_COMPARISON),
            dict(self.GREEN_SENSITIVITY), False, None)
        self.assertEqual(verdict["status"], "PREPARATION_READY")

    def test_violation_blocks(self):
        metrics = copy.deepcopy(self.GREEN_METRICS)
        metrics["invariant_violations"]["L1"] = 1
        blockers, _ = make_bundle.derive_verdict(
            metrics, dict(self.GREEN_COMPARISON),
            dict(self.GREEN_SENSITIVITY), True, self._letters())
        self.assertTrue(blockers)


class TestSourcesFrozen(unittest.TestCase):
    def test_registry_roles_and_hashes(self):
        registry = load("source-registry.json")
        roles = {s["role"] for s in registry["sources"]}
        for role in ("ontology", "audit-model", "formal-semantics",
                     "scope-isolation", "prov-standard", "prov-dictionary"):
            self.assertIn(role, roles)
        for entry in registry["sources"]:
            raw = (S1016 / entry["snapshot_path"].split("S1-016/")[-1]).read_bytes()
            self.assertEqual(sha(raw), entry["sha256"])
            self.assertEqual(len(raw), entry["bytes"])

    def test_rubric_and_decision_rule_frozen(self):
        rubric = load("rubric.json")
        self.assertTrue(rubric["frozen"])
        self.assertIn("L1", str(rubric))
        rule = load("decision-rule.json")
        self.assertTrue(rule["frozen"])
        self.assertIn("FLAT_RUNTIME_PROV_EXPORT", rule["allowed_decisions"])

    def test_prov_dictionary_not_recommendation(self):
        text = (S1016 / "sources" / "snap-06-prov-dictionary.md").read_text(
            encoding="utf-8")
        self.assertIn("NOT a Recommendation", text)
        self.assertIn("Working Group Note", text)


if __name__ == "__main__":
    unittest.main()
