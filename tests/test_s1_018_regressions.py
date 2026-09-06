"""S1-018 regression suite (pre-gate RED phase).

Stdlib only, offline, deterministic. Run:
  $env:PYTHONPATH="src"
  py -3.12 -m unittest tests.test_s1_018_regressions -v
Ticket modules load under unique names (s1018_*) via importlib.
Pre-gate scope: contracts, invariants, corpus quotas, probes and math.
Implementation lands only after the dependency gate is proven.
"""
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S1018 = ROOT / "research" / "tickets" / "stage-1" / "S1-018"


def _load_ticket_module(name: str):
    unique = f"s1018_{name}"
    if unique in sys.modules:
        return sys.modules[unique]
    spec = importlib.util.spec_from_file_location(unique, S1018 / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    spec.loader.exec_module(module)
    return module


contract = _load_ticket_module("contract")
models = _load_ticket_module("models")
runner = _load_ticket_module("runner")
evaluator = _load_ticket_module("evaluator")
dependency_gate = _load_ticket_module("dependency_gate")
build_corpus = _load_ticket_module("build_corpus")
sensitivity = _load_ticket_module("sensitivity")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(name: str):
    return json.loads((S1018 / name).read_text(encoding="utf-8"))


SA = {"tenant_id": "t-a", "workspace_id": "w-1", "goal_id": "g-1"}


class TestContractStrictness(unittest.TestCase):
    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):
            contract.loads('{"a": 1, "a": 2}')

    def test_nonfinite_rejected(self):
        for text in ('{"a": NaN}', '{"a": Infinity}'):
            with self.assertRaises(ValueError, msg=text):
                contract.loads(text)

    def test_unknown_field_rejected(self):
        schema = contract.load("schemas/query.schema.json")
        bad = {"query_id": "q1", "scope": dict(SA), "terms": ["t"],
               "requester": "m1", "smuggled": "capability"}
        with self.assertRaises(ValueError):
            contract.validate(bad, schema)

    def test_unknown_enum_rejected(self):
        schema = contract.load("schemas/query.schema.json")
        bad = {"query_id": "q1", "scope": dict(SA), "terms": ["t"],
               "requester": "m1", "profile": "evil/v9"}
        with self.assertRaises(ValueError):
            contract.validate(bad, schema)

    def test_traversal_rejected(self):
        self.assertTrue(contract.has_traversal("../../keys"))
        self.assertTrue(contract.has_traversal("..\\keys"))
        self.assertFalse(contract.has_traversal("partition-1"))

    def test_oversized_rejected(self):
        with self.assertRaises(ValueError):
            contract.check_size("x" * (contract.MAX_INPUT_BYTES + 1), "query")


class TestDependencyGate(unittest.TestCase):
    def test_gate_proven_all_three(self):
        doc = load("dependency-gate.json")
        self.assertTrue(doc["dependencies_proven"])
        self.assertTrue(doc["scope_isolation_baseline_available"])
        self.assertTrue(doc["revocation_baseline_available"])
        self.assertTrue(doc["adapter_boundary_available"])
        self.assertFalse(doc.get("population_human_claims_proven", True))
        by_ticket = {r["ticket"]: r for r in doc["dependencies"]}
        for ticket in ("S1-007", "S1-008", "S1-009"):
            self.assertEqual(by_ticket[ticket]["status"], "PROVEN", msg=ticket)
            self.assertEqual(by_ticket[ticket]["problems"], [], msg=ticket)
        self.assertEqual(doc["verified_commit"], "b8eeddd66bdc76f273cb14066e76c63eecad2f8f")

    def test_gate_discovers_no_hardcoded_ids(self):
        source = (S1018 / "dependency_gate.py").read_text(encoding="utf-8")
        for token in ("goal_RVX89", "goal_5FX22", "goal_1XSF", "goal_B87S",
                      "reval_KHXH", "reval_6BH3", "reval_85CM", "reval_KJWP",
                      "b9c9e2fb", "4c344ab2", "5c43c03d", "1d1b2deb"):
            self.assertNotIn(token, source)

    def test_forged_override_rejected(self):
        result = dependency_gate.check("S1-007", rec_override={"forged": True})
        self.assertEqual(result["status"], "NOT_PROVEN")


class TestInvariants(unittest.TestCase):
    def _sessioned(self, model, member="m1", scope=None):
        scope = dict(scope or SA)
        challenge = model.create_challenge(member)
        evidence = model.make_evidence(challenge["nonce"])
        opened = model.open_session(member, scope, evidence)
        self.assertTrue(opened["open"])
        return opened["session_id"]

    def test_gateway_authority_only(self):
        model = models.new_model("B", SA)
        model.create_group("g1", SA, ["m1"])
        model.submit_object("d1", "plaintext-doc", SA)
        session = self._sessioned(model)
        self.assertTrue(session)
        # Even with an open attested session, the gateway decides alone.
        self.assertEqual(model.gateway_decide("m1", "read", "d1"), "ALLOW")
        self.assertEqual(model.gateway_decide("mallory", "read", "d1"), "DENY")
        # A provider payload claiming attested=true changes nothing.
        self.assertEqual(model.gateway_decide(
            "mallory", "read", "d1",
            provider_claim={"attested": True, "admin": True}), "DENY")

    def _sessioned(self, model, member= "m1", scope=None):
        scope = dict(scope or SA)
        challenge = model.create_challenge(member)
        evidence = model.make_evidence(challenge["nonce"])
        opened = model.open_session(member, scope, evidence)
        self.assertTrue(opened["open"])
        return opened["session_id"]

    def test_revocation_dominates_cache(self):
        model = models.new_model("C", SA)
        model.create_group("g1", SA, ["m1"])
        model.submit_object("d1", "doc", SA)
        model.build_index("p1", SA, "g1")
        session = self._sessioned(model)
        token = model.query_token("m1", SA, ["doc"])
        self.assertTrue(model.query("m1", token, session)["ok"])
        model.revoke_member("m1")
        self.assertFalse(model.query("m1", token, session)["ok"])
        # The sessionless direct path is gateway-gated too (defense in depth).
        self.assertFalse(model.query(
            "m1", ["alpha"], None, dict(SA), require_session=False)["ok"])
        self.assertEqual(model.counters()["post_revoke_allow"], 0)

    def test_rollback_detected(self):
        model = models.new_model("B", SA)
        model.create_group("g1", SA, ["m1"])
        snap = model.sealed_snapshot()
        model.commit_epoch("g1")
        restored = model.restore_snapshot(snap)
        self.assertEqual(restored["outcome"], "rollback_detected")

    def test_unknown_fails_closed(self):
        model = models.new_model("A", SA)
        outcome = model.query("ghost", {"token": "nope"})
        self.assertFalse(outcome["ok"])
        self.assertIn(outcome["reason"],
                      ("unknown_member", "unknown_token", "no_session",
                       "stale_session", "unsupported"))

    def test_no_blind_retry(self):
        model = models.new_model("B", SA)
        model.create_group("g1", SA, ["m1"])
        first = model.submit_object("d1", "doc", SA, crash="before_commit")
        self.assertEqual(first["outcome"], "unknown")
        with self.assertRaises(models.BlindRetryRefused):
            model.submit_object("d1", "doc", SA, idempotency_key="k-other")
        second = model.reconcile("d1", idempotency_key=first["key"])
        self.assertEqual(second["outcome"], "committed")


class TestCorpus(unittest.TestCase):
    def test_48_balanced_unique_deterministic(self):
        corpus = load("cases.json")
        self.assertEqual(corpus["case_count"], 48)
        by_class = {}
        for case in corpus["cases"]:
            by_class[case["class"]] = by_class.get(case["class"], 0) + 1
        self.assertEqual(by_class, {"mls_lifecycle": 12, "attestation": 12,
                                    "revocation_cache": 12, "leakage_unknown": 12})
        self.assertEqual(len({c["case_id"] for c in corpus["cases"]}), 48)
        self.assertEqual(len({c["semantic_digest"] for c in corpus["cases"]}), 48)
        first, _ = build_corpus.build()
        self.assertEqual(first["cases"], corpus["cases"])

    def test_oracle_separate(self):
        oracle = load("oracle.json")
        corpus = load("cases.json")
        self.assertEqual(len(oracle["entries"]), 48)
        for case in corpus["cases"]:
            self.assertIn(case["case_id"], oracle["entries"])
            self.assertNotIn("expected_decision", json.dumps(case))

    def test_malformed_case_rejected(self):
        with self.assertRaises(ValueError):
            build_corpus.validate_case({"case_id": "X-01"})
        dup = {"case_id": "Q-01", "class": "mls_lifecycle", "description": "x",
               "inputs": {}, "transitions": []}
        with self.assertRaises(ValueError):
            build_corpus.validate_case(dup, known_ids={"Q-01"})

    def test_threat_and_attestation_coverage(self):
        corpus = load("cases.json")
        joined = json.dumps(corpus)
        for marker in ("stale", "replay", "rollback", "revoked", "cross-tenant",
                       "plaintext", "forged", "restart", "timeout"):
            self.assertIn(marker, joined, msg=marker)


class TestArchitectures(unittest.TestCase):
    def _smoke(self, arch):
        return runner.generate_observation(
            {"case_id": "SMOKE-01", "class": "mls_lifecycle",
             "inputs": {"scope": dict(SA)},
             "transitions": [
                 {"op": "create_group", "args": {"group": "g1", "members": ["m1"]}},
                 {"op": "submit", "args": {"doc": "d1"}},
                 {"op": "build_index", "args": {"partition": "p1"}},
                 {"op": "query_as", "args": {"member": "m1", "terms": ["alpha"]}}]},
            arch, 1)["core"]

    def test_same_observable_contract(self):
        observations = {arch: self._smoke(arch) for arch in ("A", "B", "C")}
        for arch in ("A", "B", "C"):
            self.assertEqual(observations[arch]["decision"], "allow")
            self.assertEqual(observations[arch]["hardware_tee_evidence"],
                             "NOT_MEASURED")
            self.assertFalse(observations[arch]["mock_quote_is_hardware"])

    def test_mock_quote_never_hardware(self):
        for arch in ("A", "B", "C"):
            obs = runner.generate_observation(
                {"case_id": "SMOKE-02", "class": "attestation",
                 "inputs": {"scope": dict(SA)},
                 "transitions": [
                     {"op": "create_group",
                      "args": {"group": "g1", "members": ["m1"]}},
                     {"op": "attest", "args": {"member": "m1"}}]},
                arch, 1)["core"]
            self.assertEqual(obs["hardware_tee_evidence"], "NOT_MEASURED")
            self.assertFalse(obs["mock_quote_is_hardware"])


class TestEvaluatorAndProbes(unittest.TestCase):
    def test_recompute_catches_forged_counter(self):
        metrics = {"pc_violations": {f"PC{i}": 0 for i in range(1, 16)},
                   "critical_false_accepts": 0}
        forged = dict(metrics, critical_false_accepts=0)
        forged["pc_violations"] = dict(metrics["pc_violations"])
        self.assertTrue(evaluator.verify_counters(forged, metrics))
        tampered = {"pc_violations": {f"PC{i}": 0 for i in range(1, 16)},
                    "critical_false_accepts": 1}
        self.assertFalse(evaluator.verify_counters(tampered, metrics))

    def test_wilson_ci_no_data(self):
        interval = evaluator.wilson(0, 0)
        self.assertEqual(interval["status"], "NO_DATA")

    def test_probe_stale_evidence(self):
        outcome = evaluator.probe_attestation("stale_evidence")
        self.assertEqual(outcome["decision"], "DENY")
        self.assertFalse(outcome["session_open"])

    def test_probe_replay_nonce(self):
        outcome = evaluator.probe_attestation("replayed_nonce")
        self.assertEqual(outcome["decision"], "DENY")
        self.assertEqual(outcome["reason"], "replay")

    def test_probe_parser_battery(self):
        outcome = evaluator.probe_parser_battery()
        self.assertTrue(all(outcome["rejected"].values()))
        self.assertGreaterEqual(len(outcome["rejected"]), 6)

    def test_leakage_channels_separate(self):
        report = evaluator.leakage_report({}, {})
        self.assertIn("content", report["channels"])
        self.assertIn("access_pattern", report["channels"])
        self.assertNotIn("secure", json.dumps(report))


class TestSensitivityMath(unittest.TestCase):
    def test_vectors_and_determinism(self):
        scores = {dim: {"A": 0.9, "B": 0.9, "C": 0.7}
                  for dim in sensitivity.DIMS}
        first = sensitivity.analyze(scores)
        second = sensitivity.analyze(scores)
        self.assertEqual(first, second)
        self.assertGreaterEqual(first["vector_count"], 200)
        self.assertIn(first["base_winner"], ("A", "B", "C", "TIE"))


class TestSourcesPresent(unittest.TestCase):
    def test_registry_roles_and_hashes(self):
        registry = load("source-registry.json")
        roles = {s["role"] for s in registry["sources"]}
        for role in ("local-basis", "mls-standard", "rats-architecture",
                     "eat-format", "tee-platform", "leakage-analysis"):
            self.assertIn(role, roles)
        for entry in registry["sources"]:
            raw = (S1018 / entry["snapshot_path"].split("S1-018/")[-1]).read_bytes()
            self.assertEqual(sha(raw), entry["sha256"])
            self.assertEqual(len(raw), entry["bytes"])

    def test_no_standard_overclaim(self):
        rats = (S1018 / "sources" / "snap-03-rats-rfc9334.md").read_text(
            encoding="utf-8")
        self.assertIn("Informational", rats)
        self.assertIn("NOT Standards Track", rats)
        dictionary = (S1018 / "sources").joinpath("snap-06-access-pattern-leakage.md")
        self.assertTrue(dictionary.exists())


if __name__ == "__main__":
    unittest.main()
