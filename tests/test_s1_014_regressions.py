"""S1-014 regression suite: contract, parity, importer, evaluator, probes,
replay, publisher negatives, operator-decision verifier and real browser run."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "research/tickets/stage-1/S1-014"
sys.path.insert(0, str(T))


def module(name):
    spec = importlib.util.spec_from_file_location("s1014_" + name, T / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


c = module("contract")
importer = module("importer")
evaluator = module("evaluator")
publisher = module("publisher")


def synthetic(pred=lambda e: True):
    for p in sorted((T / "synthetic/sessions").glob("*.json")):
        env = c.load_json(p)
        if pred(env):
            return env
    raise AssertionError("no synthetic envelope")


def resign(env):
    body = {k: v for k, v in env.items() if k != "payload_sha256"}
    body["payload_sha256"] = c.digest(body)
    return body


class TestContract(unittest.TestCase):
    def test_corpus_frozen_and_parity(self):
        docs, oracle = c.build_corpus()
        manifest = c.load_json(T / "task-manifest.json")
        self.assertEqual(manifest["disputes"], docs)
        self.assertEqual(len(docs), 8)
        self.assertEqual({d["complexity_stratum"] for d in docs}, {"simple", "medium", "complex"})
        self.assertEqual(c.load_json(T / "oracle/oracle.json")["oracle"], oracle)
        for d in docs:
            self.assertTrue(c.parity_report(d)["equivalent"], d["dispute_id"])

    def test_oracle_not_in_browser_contract(self):
        raw = (T / "prototype/browser-contract.json").read_text(encoding="utf-8")
        self.assertNotIn("correct_answer", raw)
        self.assertNotIn("scoring_rationale", raw)
        frozen = c.load_json(T / "prototype/browser-contract.json")
        self.assertEqual(frozen["contract_sha256"], c.browser_contract(frozen["disputes"])["contract_sha256"])

    def test_strict_json_fail_closed(self):
        with self.assertRaises(c.ContractError):
            c.strict_loads('{"a":1,"a":2}')
        with self.assertRaises(c.ContractError):
            c.strict_loads('{"a":NaN}')
        docs, _ = c.build_corpus()
        bad = copy.deepcopy(docs[0]); bad["extra"] = 1
        self.assertTrue(c.validate_dispute(bad))
        bad = copy.deepcopy(docs[0]); bad["focal_claim"]["status"] = "verified-by-ui"
        self.assertTrue(c.validate_dispute(bad))
        bad = copy.deepcopy(docs[0]); bad["contract_version"] = "2.0.0"
        self.assertTrue(c.validate_dispute(bad))
        self.assertTrue(c.validate({}, {"$ref": "https://evil.invalid/schema"}))

    def test_counterbalancing(self):
        docs, _ = c.build_corpus()
        for seed in c.SEEDS:
            for ex in c.EXECUTORS:
                a = c.assignment(seed, ex, docs)
                self.assertEqual(sorted(t["dispute_id"] for t in a["trials"]), sorted(d["dispute_id"] for d in docs))
                self.assertEqual(sum(t["variant"] == "CARD" for t in a["trials"]), 4)
                self.assertEqual(a, c.assignment(seed, ex, docs))
        self.assertNotEqual(c.assignment("seed-0001", "EXEC-RUN-A", docs)["trials"],
                            c.assignment("seed-0002", "EXEC-RUN-A", docs)["trials"])


class TestImporterEvaluator(unittest.TestCase):
    def test_paths(self):
        ok = synthetic(lambda e: all(t["outcome"] == "submitted" for t in e["trials"]))
        r = importer.import_envelope(ok, set(), set())
        self.assertEqual(r["status"], "ok", r)
        dup = importer.import_envelope(ok, {ok["session"]["session_id"]}, set())
        self.assertEqual(dup["status"], "rejected")
        forged = copy.deepcopy(ok); forged["trials"][0]["answer"] = "focal_holds"
        self.assertEqual(importer.import_envelope(forged, set(), set())["status"], "rejected")  # digest
        pii = copy.deepcopy(ok); pii["events"][0]["detail"] = "someone@example.org"
        self.assertEqual(importer.import_envelope(resign(pii), set(), set())["status"], "quarantined")
        grade = copy.deepcopy(ok); grade["trials"][0]["correct"] = True
        self.assertNotEqual(importer.import_envelope(resign(grade), set(), set())["status"], "ok")

    def test_evaluator_denominators_and_no_winner(self):
        m = c.load_json(T / "results/metrics.json")
        self.assertEqual(m["human_study_n"], 0)
        self.assertIsNone(m["winner"])
        self.assertEqual(m["comparative_human_effectiveness"], "NOT_MEASURED")
        total = sum(cell["n_assigned"] for v in m["by_variant_task"].values() for cell in v.values())
        self.assertEqual(total, 8 * m["synthetic_session_n"])
        withdrawn = sum(cell["n_withdrawn"] for v in m["by_variant_task"].values() for cell in v.values())
        timeouts = sum(cell["n_timeout"] for v in m["by_variant_task"].values() for cell in v.values())
        self.assertGreater(withdrawn, 0); self.assertGreater(timeouts, 0)
        self.assertTrue(m["hard_gates_green"])
        fresh = evaluator.evaluate(T / "results/import", executor="EXEC-TEST")
        self.assertEqual(fresh["metrics_sha256"], m["metrics_sha256"])


class TestProbesReplayPublisher(unittest.TestCase):
    def test_probe_matrix(self):
        p = c.load_json(T / "results/probes.json")
        self.assertEqual([x["probe"] for x in p["probes"]], list("ABCDEFGHIJ"))
        self.assertTrue(p["control_passed"]); self.assertTrue(p["all_detected"])

    def test_replay_and_frozen(self):
        cmp_ = c.load_json(T / "results/comparison.json")
        self.assertTrue(cmp_["replicated"]); self.assertNotEqual(cmp_["runs"][0]["pid"], cmp_["runs"][1]["pid"])
        self.assertEqual(publisher.check_frozen(), [])

    def test_publisher_negatives(self):
        fresh = c.load_json(T / "results/metrics.json")
        forged = copy.deepcopy(fresh); forged["winner"] = "CARD"
        self.assertTrue(publisher.compare_saved(forged, fresh))
        self.assertTrue(publisher.synthetic_claims_forbidden({"winner": "GRAPH"}))
        self.assertTrue(publisher.synthetic_claims_forbidden({"human_study_n": 16}))
        self.assertTrue(publisher.synthetic_claims_forbidden({"note": "card is better"}))
        with tempfile.TemporaryDirectory() as td:
            shutil.copytree(T, Path(td) / "t", ignore=shutil.ignore_patterns("__pycache__"))
            root = Path(td) / "t"
            (root / "sources/extra.md").write_text("x")
            self.assertTrue(any("added" in p for p in publisher.check_frozen(root)))
            (root / "sources/extra.md").unlink()
            (root / "decision-rule.json").write_text("{}")
            self.assertTrue(any("changed" in p for p in publisher.check_frozen(root)))
            (root / "protocol.md").unlink()
            self.assertTrue(any("missing" in p for p in publisher.check_frozen(root)))

    def test_candidate_and_bundle_invariants(self):
        cand = c.load_json(T / "candidate-record.json")
        self.assertIn(cand["status"], ("PREPARATION_READY", "PASS_WITH_LIMITS", "INCONCLUSIVE"))
        self.assertEqual(cand["human_study_n"], 0); self.assertIsNone(cand["winner"])
        self.assertEqual(cand["comparative_human_effectiveness"], "NOT_MEASURED")
        self.assertFalse(cand["dependency_gate"]["population_human_claims_proven"])
        self.assertEqual(cand["bundle_sha256"], c.sha_file(T / "bundle.json"))
        b = c.load_json(T / "bundle.json")
        self.assertEqual(set(b["artifacts"]), set(b["config"]["required_artifacts"]))
        self.assertNotEqual(b["producer"], b["auditor"])
        classes = {cl["s1_014_class"] for cl in b["claims"]}
        self.assertTrue({"HCI_measurement", "usability_observation", "design_inference", "accessibility_risk", "decision", "limitation"} <= classes)
        text = json.dumps(b).lower()
        for phrase in ("card is better", "graph is better"):
            self.assertNotIn(phrase, text)

    def test_operator_decision_verifier(self):
        frozen = c.load_json(T / "frozen-manifest.json")
        good = {"schema": "agentos.s1-014.operator-decision/v1", "operator_review_n": 1, "human_study_n": 0,
                "selected_answers": {str(i): "A" for i in range(1, 13)}, "frozen_manifest_sha256": frozen["manifest_sha256"],
                "browser_contract_sha256": frozen["browser_contract_sha256"], "variants_reviewed": ["CARD", "GRAPH"]}
        self.assertEqual(publisher.verify_decision(good, frozen, None), [])
        for q, a in (("2", "B"), ("3", "B"), ("4", "C"), ("6", "B"), ("7", "B"), ("8", "B"), ("9", "C"), ("10", "C"), ("12", "C"), ("11", "C"), ("1", "Z")):
            bad = copy.deepcopy(good); bad["selected_answers"][q] = a
            self.assertTrue(publisher.verify_decision(bad, frozen, None), f"{q}{a}")
        bad = copy.deepcopy(good); bad["frozen_manifest_sha256"] = "0" * 64
        self.assertTrue(publisher.verify_decision(bad, frozen, None))
        bad = copy.deepcopy(good); del bad["selected_answers"]["12"]
        self.assertTrue(publisher.verify_decision(bad, frozen, None))

    def test_dependency_gate_outputs(self):
        g = c.load_json(T / "dependency-gate.json")
        self.assertTrue(g["phase_a_dependencies_proven"]); self.assertTrue(g["operator_review_dependencies_proven"])
        self.assertFalse(g["population_human_claims_proven"])
        self.assertEqual([d["ticket"] for d in g["dependencies"]], ["S1-011", "S1-012", "S1-013"])
        self.assertTrue(g["dependencies"][2]["s1_013_semantics"]["mass_pilot_cancelled"])
        self.assertTrue(any("human_n=0" in x for x in g["inherited_limits"]))

    def test_static_ui_checks(self):
        self.assertTrue(all(publisher.static_ui_checks().values()), publisher.static_ui_checks())


class TestRealBrowser(unittest.TestCase):
    def test_real_browser_export_import_and_evaluate(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for the real browser check")
        with tempfile.TemporaryDirectory(prefix="s1014-browser-") as td:
            out = Path(td) / "envelope.json"
            proc = subprocess.run([node, str(T / "prototype/browser_probe.cjs"), str(out), "seed-0002", "EXEC-RUN-B", "keyboard_only"],
                                  capture_output=True, text=True, timeout=180, env=dict(os.environ))
            if proc.returncode != 0 and ("Cannot find module" in proc.stderr or "missing dependencies" in proc.stderr
                                         or "Executable doesn't exist" in proc.stderr):
                self.skipTest("Playwright/Chromium not installed in this environment: " + proc.stderr.strip().splitlines()[-1][:120])
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            evidence = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertIn("8-trials-keyboard-only", evidence["checks"]); self.assertTrue(evidence["synthetic"])
            src = Path(td) / "in"; src.mkdir(); shutil.copy(out, src / "e.json"); shutil.copy(str(out) + ".withdrawn.json", src / "w.json")
            imp = Path(td) / "imp"
            result = importer.import_directory(src, imp)
            self.assertEqual(len(result["observations"]), 2)
            m = evaluator.evaluate(imp, executor="EXEC-BROWSER")
            self.assertEqual(m["human_study_n"], 0); self.assertIsNone(m["winner"]); self.assertTrue(m["hard_gates_green"])


if __name__ == "__main__":
    unittest.main()
