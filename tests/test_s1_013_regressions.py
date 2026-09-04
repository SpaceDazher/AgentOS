"""S1-013 regression suite (Phase 1 preparation).

Stdlib only, no network/LLM, no human participants invoked.
Run: $env:PYTHONPATH="src"; py -3.12 -m unittest tests.test_s1_013_regressions -v
Ticket modules load under unique names (s1013_*) via importlib.
"""
import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S1013 = ROOT / "research" / "tickets" / "stage-1" / "S1-013"


def _load_ticket_module(name: str):
    unique = f"s1013_{name}"
    if unique in sys.modules:
        return sys.modules[unique]
    spec = importlib.util.spec_from_file_location(unique, S1013 / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    spec.loader.exec_module(module)
    return module


runner = _load_ticket_module("runner")
evaluator = _load_ticket_module("evaluator")
dependency_gate = _load_ticket_module("dependency_gate")
make_bundle = _load_ticket_module("make_bundle")
replicate = _load_ticket_module("replicate")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(name: str):
    return json.loads((S1013 / name).read_text(encoding="utf-8"))


def import_synthetic(tmp=None):
    import tempfile
    out = Path(tmp) if tmp else Path(tempfile.mkdtemp())
    old = sys.argv
    sys.argv = ["runner", "--src",
                str(S1013 / "synthetic" / "sessions"), "--out", str(out)]
    try:
        code = runner.main()
    finally:
        sys.argv = old
    assert code == 0
    return out


def score_imported(imp_dir, tmp=None):
    import tempfile
    out = Path(tmp) if tmp else Path(tempfile.mkdtemp())
    old = sys.argv
    sys.argv = ["evaluator", "--run", str(imp_dir), "--protocol",
                str(S1013), "--out", str(out / "metrics.json"),
                "--probes", str(out / "probes.json")]
    try:
        code = evaluator.main()
    finally:
        sys.argv = old
    assert code == 0
    return out


class TestNamespaceIsolation(unittest.TestCase):
    def test_ticket_modules_have_unique_names(self):
        self.assertEqual(runner.__name__, "s1013_runner")
        self.assertEqual(evaluator.__name__, "s1013_evaluator")
        self.assertTrue(hasattr(evaluator, "MEASURES"))


class TestImporter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.imp = import_synthetic(tempfile.mkdtemp())
        cls.obs = {o["session_id"]: o for o in json.loads(
            (cls.imp / "observations.json").read_text(
                encoding="utf-8"))["observations"]}

    def test_counts(self):
        statuses = [o["status"] for o in self.obs.values()]
        self.assertEqual(len(statuses), 11)
        self.assertEqual(statuses.count("ok"), 7)
        self.assertEqual(statuses.count("rejected"), 3)
        self.assertEqual(statuses.count("quarantined"), 1)

    def test_duplicate_rejected(self):
        self.assertEqual(self.obs["S-PC1"]["status"], "rejected")
        self.assertIn("duplicate", self.obs["S-PC1"]["reason"])

    def test_no_consent_rejected(self):
        self.assertEqual(self.obs["S-PC2"]["status"], "rejected")

    def test_malformed_id_rejected(self):
        self.assertEqual(self.obs["S-PC3"]["status"], "rejected")

    def test_pii_quarantined(self):
        self.assertEqual(self.obs["S-PH"]["status"], "quarantined")

    def test_output_hashes_verify(self):
        for obs in self.obs.values():
            want = sha(evaluator.canonical(
                {k: v for k, v in obs.items() if k != "output_sha256"}))
            self.assertEqual(obs["output_sha256"], want)

    def test_event_and_answer_privacy_are_quarantined(self):
        import tempfile
        import shutil
        src = Path(tempfile.mkdtemp())
        for suffix in ("session", "events", "answers"):
            shutil.copy2(
                S1013 / "synthetic" / "sessions" / f"happy-owner.{suffix}.json",
                src / f"leak.{suffix}.json")
        events_path = src / "leak.events.json"
        events = json.loads(events_path.read_text(encoding="utf-8"))
        events["events"][0]["action_shown"] = "email jane.doe@example.com"
        events_path.write_text(json.dumps(events), encoding="utf-8")
        out = import_synthetic(src.parent / "out") if False else Path(tempfile.mkdtemp())
        old = sys.argv
        sys.argv = ["runner", "--src", str(src), "--out", str(out)]
        try:
            self.assertEqual(runner.main(), 0)
        finally:
            sys.argv = old
        observations = json.loads(
            (out / "observations.json").read_text(encoding="utf-8"))[
                "observations"]
        self.assertEqual(observations[0]["status"], "quarantined")
        self.assertNotIn("jane.doe@example.com", (out / "observations.json").read_text(encoding="utf-8"))

    def test_protocol_version_drift_is_rejected(self):
        import tempfile
        import shutil
        src = Path(tempfile.mkdtemp())
        for suffix in ("session", "events", "answers"):
            shutil.copy2(
                S1013 / "synthetic" / "sessions" / f"happy-owner.{suffix}.json",
                src / f"drift.{suffix}.json")
        session_path = src / "drift.session.json"
        session = json.loads(session_path.read_text(encoding="utf-8"))
        session["protocol_version"] = "0.9.0"
        session_path.write_text(json.dumps(session), encoding="utf-8")
        out = Path(tempfile.mkdtemp())
        old = sys.argv
        sys.argv = ["runner", "--src", str(src), "--out", str(out)]
        try:
            self.assertEqual(runner.main(), 0)
        finally:
            sys.argv = old
        observations = json.loads(
            (out / "observations.json").read_text(encoding="utf-8"))["observations"]
        self.assertEqual(observations[0]["status"], "rejected")


class TestScorer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        imp = import_synthetic(tempfile.mkdtemp())
        out = score_imported(imp, tempfile.mkdtemp())
        cls.metrics = json.loads((out / "metrics.json").read_text(
            encoding="utf-8"))
        cls.probes = json.loads((out / "probes.json").read_text(
            encoding="utf-8"))

    def test_synthetic_marking(self):
        self.assertTrue(self.metrics["synthetic"])
        self.assertEqual(self.metrics["effective_participants"], 7)

    def test_c4_requires_explanation(self):
        # probe-a C4 bare "no" must not count as correct.
        c4 = self.metrics["measures"]["C4"]
        self.assertEqual(c4["correct"], 1)
        self.assertEqual(c4["n"], 2)

    def test_c5_counts_failures(self):
        c5 = self.metrics["measures"]["C5"]
        self.assertEqual(c5["n"], 3)
        self.assertEqual(c5["correct"], 2)
        self.assertEqual(c5["disposition"], "not_met")

    def test_dispositions_honest(self):
        disp = {k: v["disposition"]
                for k, v in self.metrics["measures"].items()}
        self.assertEqual(disp["C1"], "target_met")
        self.assertEqual(disp["C3"], "target_met")
        self.assertEqual(disp["C5"], "not_met")
        self.assertIn(disp["C2"], ("target_met", "not_met", "inconclusive"))

    def test_approvals_clustered(self):
        approvals = self.metrics["approvals"]
        self.assertEqual(approvals["correct"], 4)
        self.assertEqual(approvals["n"], 4)
        # probe-e click flood contributes no oracle decisions.
        self.assertNotIn("P-HHHHHH", approvals["per_participant"])

    def test_load_probe_excluded_from_rates(self):
        rates = self.metrics["prompt_rate_by_role"]
        flagged = [s["session_id"] for s in rates["load_probes"]]
        self.assertIn("S-PB", flagged)
        reviewer = rates["by_role"]["reviewer"]
        self.assertLess(reviewer["prompts"], 50)

    def test_all_probes_pass(self):
        self.assertTrue(self.probes["all_pass"])
        for probe in "ABCDEFGH":
            self.assertTrue(self.probes["probes"][probe]["passed"], probe)

    def test_tampered_probe_case_fails(self):
        import tempfile
        work = Path(tempfile.mkdtemp())
        (work / "observations.json").write_text(json.dumps(
            {"schema": "x", "observations": [{
                "session_id": "S-PG", "status": "ok",
                "participant_id": "P-IIIIII", "role": "owner",
                "session_sha256": "x", "event_count": 2,
                "response_count": 0, "problems": [],
                "output_sha256": "tampered"}]}))
        metrics = evaluator.evaluate(work, S1013)
        # Tampered rows are not trusted: scorer works from session files,
        # so this stays consistent; the hash mismatch is an importer fact.
        self.assertIn("measures", metrics)

    def test_adjudicated_flag_without_dual_rating_is_not_score(self):
        """A producer cannot turn a single response into human evidence."""
        import tempfile
        work = Path(tempfile.mkdtemp())
        src = S1013 / "synthetic" / "sessions"
        for suffix in ("session", "events", "answers"):
            (work / f"attack.{suffix}.json").write_bytes(
                (src / f"probe-a.{suffix}.json").read_bytes())
        answers_path = work / "attack.answers.json"
        answers = json.loads(answers_path.read_text(encoding="utf-8"))
        answers["session_id"] = "S-PA"
        answers["responses"][0]["measure"] = "C4"
        answers["responses"][0]["primary"] = {
            "value": "yes", "explanation": "everyone reads private notes"
        }
        answers["responses"][0].pop("rater2", None)
        answers["responses"][0]["adjudicated"] = "correct"
        answers_path.write_text(json.dumps(answers), encoding="utf-8")
        metrics = evaluator.score_measures(
            [{"session_id": "S-PA", "status": "ok"}], work)
        self.assertEqual(metrics["C4"]["correct"], 0)
        self.assertEqual(metrics["C4"]["missing"], 1)

    def test_c5_latency_starts_at_task_presentation(self):
        import tempfile
        work = Path(tempfile.mkdtemp())
        session = {
            "session_id": "S-SLOW", "participant_id": "P-LLLLLL",
            "role": "owner", "protocol_version": "1.0.0-draft",
            "cohort": "synthetic", "synthetic": True,
        }
        events = {"session_id": "S-SLOW", "events": [
            {"seq": 0, "t_ms": 0, "type": "prompt_displayed",
             "prompt_id": "C5-S1"},
            {"seq": 1, "t_ms": 60000, "type": "stop_requested"},
            {"seq": 2, "t_ms": 61000, "type": "stop_confirmed",
             "acknowledged": True,
             "acknowledgements": [{"agent_id": "A-1", "state": "stopped"}]},
        ]}
        answers = {"session_id": "S-SLOW", "responses": []}
        (work / "slow.session.json").write_text(json.dumps(session), encoding="utf-8")
        (work / "slow.events.json").write_text(json.dumps(events), encoding="utf-8")
        (work / "slow.answers.json").write_text(json.dumps(answers), encoding="utf-8")
        scored = evaluator.score_measures(
            [{"session_id": "S-SLOW", "status": "ok"}], work)
        self.assertEqual(scored["C5"]["n"], 1)
        self.assertEqual(scored["C5"]["correct"], 0)
        self.assertEqual(scored["C5"]["latencies_ms"], [61000])


class TestReplication(unittest.TestCase):
    def test_replicate_matches(self):
        import tempfile
        out = Path(tempfile.mkdtemp()) / "comparison.json"
        old = sys.argv
        sys.argv = ["replicate", "--src",
                    str(S1013 / "synthetic" / "sessions"),
                    "--ticket", str(S1013), "--out", str(out)]
        try:
            code = replicate.main()
        finally:
            sys.argv = old
        self.assertEqual(code, 0)
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertTrue(doc["replicated"])
        self.assertTrue(doc["distinct_processes"])


class TestDependencyGateStrict(unittest.TestCase):
    def test_real_dependencies_proven(self):
        for dep in ({"ticket": "S1-011",
                     "branch": "codex/s1-011-knowledge-gate",
                     "record": "research/tickets/stage-1/S1-011/evaluation-record.json"},
                    {"ticket": "S1-012",
                     "branch": "codex/s1-012-evidence-independence",
                     "record": "research/tickets/stage-1/S1-012/evaluation-record.json"}):
            self.assertEqual(dependency_gate.check(dep)["status"],
                             "PROVEN", dep["ticket"])

    def test_fail_verdict_never_proven(self):
        rec = {"result": "fail", "research_revision": 1,
               "goal_id": "g", "campaign_id": "c", "evaluation_id": "e",
               "artifact_chain_hash": "h",
               "evidence_pack": {"path": "research/tickets/stage-1/S1-011/x.json",
                                 "sha256": "0" * 64,
                                 "payload_sha256": "0" * 64}}
        segment = ("### S1-011 probe\n- **Status:** `FAIL`\n"
                   "research revision 1\n")
        result = dependency_gate.check(
            {"ticket": "S1-011", "branch": "codex/s1-011-knowledge-gate",
             "record": "research/tickets/stage-1/S1-011/evaluation-record.json"},
            rec_override=rec, docs_override=segment)
        self.assertEqual(result["status"], "NOT_PROVEN")

    def test_traversal_path_rejected(self):
        self.assertFalse(dependency_gate.contained(
            "research/tickets/stage-1/S1-011/../../S1-002/x.json", "S1-011"))
        self.assertFalse(dependency_gate.contained(
            "C:\\Windows\\x.json", "S1-011"))
        self.assertTrue(dependency_gate.contained(
            "research/tickets/stage-1/S1-011/results/evidence/x.json",
            "S1-011"))

    def test_forged_override_cannot_replace_dependency_identity(self):
        dep = {"ticket": "S1-011",
               "branch": "codex/s1-011-knowledge-gate",
               "record": "research/tickets/stage-1/S1-011/evaluation-record.json"}
        record = json.loads((
            __import__("subprocess").check_output(
                ["git", "show", f"{dep['branch']}:{dep['record']}"])
            .decode("utf-8")))
        forged = copy.deepcopy(record)
        forged["goal_id"] = "fabricated"
        forged["campaign_id"] = "fabricated"
        forged["evaluation_id"] = "fabricated"
        forged["artifact_chain_hash"] = "f" * 64
        forged["result"] = "pass_with_limits"
        result = dependency_gate.check(dep, rec_override=forged)
        self.assertEqual(result["status"], "NOT_PROVEN")


class TestBundleNative(unittest.TestCase):
    def test_bundle_passes_evaluation_checks(self):
        from agentos.research import (_normalise_config, _normalize_bundle,
                                      _evaluation_checks)
        bundle = json.loads((S1013 / "bundle.json").read_text(
            encoding="utf-8"))
        config, config_errors = _normalise_config(None, bundle)
        self.assertEqual(config_errors, [])
        normalized, bundle_errors = _normalize_bundle(bundle, config)
        self.assertEqual(bundle_errors, [])
        failures, _ = _evaluation_checks(normalized, config)
        self.assertEqual(failures, [])

    def test_bundle_binding_matches_disk(self):
        bundle = json.loads((S1013 / "bundle.json").read_text(
            encoding="utf-8"))
        candidate = json.loads((S1013 / "candidate-record.json").read_text(
            encoding="utf-8"))
        self.assertEqual(sha((S1013 / "bundle.json").read_bytes()),
                         candidate["bundle_sha256"])
        self.assertEqual(len(bundle["artifacts"]), 11)
        self.assertEqual(candidate["status"], "PREPARATION_READY")
        self.assertEqual(candidate["human_phase"], "BLOCKED_HUMAN_PILOT")

    def test_no_human_pass_claimed(self):
        candidate = json.loads((S1013 / "candidate-record.json").read_text(
            encoding="utf-8"))
        problems = make_bundle.check_metrics_consistency(
            {"synthetic": True, "human_n": 0})
        self.assertEqual(problems, [])


class TestBundleRefusal(unittest.TestCase):
    def test_refusal_without_evidence(self):
        import tempfile
        unique = "s1013_make_bundle_refusal"
        spec = importlib.util.spec_from_file_location(
            unique, S1013 / "make_bundle.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique] = module
        spec.loader.exec_module(module)
        work = Path(tempfile.mkdtemp())
        (work / "results").mkdir()
        (work / "dependency-gate.json").write_text(json.dumps(
            {"all_proven": False, "canonical_db_recheck_required": True}))
        module.HERE = work
        module.RESULTS = work / "results"
        code = module.main()
        self.assertEqual(code, 1)
        self.assertFalse((work / "candidate-record.json").exists())


class TestStdlibOnly(unittest.TestCase):
    def test_ticket_modules_import_stdlib_only(self):
        import ast
        allowed = set(sys.stdlib_module_names) | {
            "s1013_runner", "s1013_evaluator", "s1013_dependency_gate",
            "s1013_make_bundle", "s1013_replicate"}
        for name in ("runner.py", "evaluator.py", "dependency_gate.py",
                     "replicate.py", "make_bundle.py",
                     "synthetic/build_synthetic.py"):
            path = S1013 / name
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
        for name in ("runner.py", "evaluator.py", "dependency_gate.py",
                     "replicate.py", "make_bundle.py"):
            text = (S1013 / name).read_text(encoding="utf-8")
            for mod in banned:
                self.assertNotIn(f"import {mod}", text, f"{name}: {mod}")


class TestSecretsAbsent(unittest.TestCase):
    def test_no_credentials_in_ticket_files(self):
        import re
        patterns = [re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
                    re.compile(r"sk-(proj|live)-[A-Za-z0-9]{8,}"),
                    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]{16,}")]
        hits = []
        for path in list(S1013.glob("*.py")) + list(S1013.glob("*.json")) \
                + list(S1013.glob("*.md")) \
                + list((S1013 / "results").rglob("*.json")):
            if "sources" in path.parts or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for pattern in patterns:
                if pattern.search(text):
                    hits.append(f"{path.name}: {pattern.pattern[:30]}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
