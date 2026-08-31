"""Regression tests for S1-007 (QA3 retrieval and index isolation).

Positive flow: the frozen contract/corpus/rubric produce a complete
2-variant x 14-case x 3-seed matrix per executor, the evaluator re-derives
ISO1-ISO8 = 0 for both honest variants from raw observations, probes
A/B/C/D are detected through the evaluator's own rules, and the
independent rerun (separate subprocess identity + output directory)
reproduces the safety verdict.

Negative mutations (fail-closed):
- run matrix divergence (missing/extra/duplicate runs), path traversal,
  run digest mismatch, empty/fabricated observations;
- mixed commit/tree provenance, dirty tree, executor identity equality;
- contract hash divergence between runs and frozen files;
- cross-scope content/ID/metadata/count/rank/snippet leakage;
- forged/malformed/unknown scope fail closed (never a default scope);
- stale cache/projection after revoke/move/supersede rejected;
- lost provenance/scope projection rejected;
- runner-side ISO summaries are never trusted (summary tampering);
- timing NO_DATA / signal findings never become passes;
- hard isolation failures are never compensated by weighted scores.

Runner semantics (real code paths):
- authorize before materialize; canonical deny form byte-equality;
- per-scope cache binding prevents cross-scope hits;
- background reindex is scope-bound and preserves provenance;
- deterministic byte-identical reruns per seed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
S1007 = ROOT / "research" / "tickets" / "stage-1" / "S1-007"
sys.path.insert(0, str(S1007))


def _load_ticket_module(name: str):
    """Load an S1-007 research module under a UNIQUE sys.modules name so
    other ticket suites' generic module names never collide inside one
    unittest discovery process."""
    unique = f"s1_007_{name}"
    if unique in sys.modules:
        return sys.modules[unique]
    spec = importlib.util.spec_from_file_location(
        unique, S1007 / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    spec.loader.exec_module(module)
    return module


runner = _load_ticket_module("runner")
evaluator = _load_ticket_module("evaluator")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def seal_manifest(path: Path) -> None:
    """Recompute the runner's manifest digest after a mutation so the
    mutation under test (and not a digest mismatch) is what fires."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.pop("manifest_digest", None)
    digest = sha(json.dumps(doc, sort_keys=True,
                            separators=(",", ":")).encode("utf-8"))
    doc["manifest_digest"] = digest
    path.write_text(json.dumps(doc, indent=2, sort_keys=True),
                    encoding="utf-8")


class GoldenFixture:
    """Builds the full positive pipeline ONCE into a temp dir using the
    real runner (two executor identities) and the real evaluator."""

    state = {}

    @classmethod
    def build(cls) -> None:
        if cls.state:
            return
        base = Path(tempfile.mkdtemp(prefix="s1007-golden-"))
        env_main = dict(os.environ,
                        AGENTOS_EXECUTOR_ID="s1-007-test-producer")
        env_rerun = dict(os.environ,
                         AGENTOS_EXECUTOR_ID="s1-007-test-auditor")
        for mode, out, env in (("main", base / "run-a", env_main),
                               ("rerun", base / "run-b", env_rerun)):
            proc = subprocess.run(
                [sys.executable, str(S1007 / "runner.py"),
                 "--mode", mode, "--out", str(out)],
                capture_output=True, text=True, env=env, cwd=str(ROOT),
                timeout=600)
            if proc.returncode != 0:
                raise RuntimeError(f"runner {mode} failed: {proc.stderr}")
        proc = subprocess.run(
            [sys.executable, str(S1007 / "runner.py"),
             "--mode", "probes", "--out", str(base)],
            capture_output=True, text=True, env=env_main, cwd=str(ROOT),
            timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"runner probes failed: {proc.stderr}")
        manifest_a = base / "run-a" / "run-manifest.json"
        manifest_b = base / "run-b" / "run-manifest.json"
        doc_a = json.loads(manifest_a.read_text(encoding="utf-8"))
        probes_path = base / "probes.json"
        nonce = "s1-007-test-nonce"
        evaluation = evaluator.evaluate(
            manifest_a, manifest_b, doc_a["provenance"]["commit"],
            probes_path, sha(probes_path.read_bytes()),
            base / "evaluation.json", nonce)
        cls.state.update({
            "base": base, "manifest_a": manifest_a,
            "manifest_b": manifest_b, "doc_a": doc_a,
            "probes": probes_path, "evaluation": evaluation})

    @classmethod
    def fresh_copy(cls, dest: Path) -> Path:
        """Copy of the golden base for mutation tests."""
        cls.build()
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(cls.state["base"], dest,
                        ignore=shutil.ignore_patterns("evaluation.json"))
        return dest


class TestPositiveFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        GoldenFixture.build()
        cls.ev = GoldenFixture.state["evaluation"]

    def test_exact_matrix_accepted_with_derived_verdict(self):
        self.assertIn(self.ev["verdict"],
                      ("PASS", "PASS_WITH_LIMITS", "FAIL"))
        self.assertEqual(self.ev["winner"], "per_scope")
        self.assertEqual(self.ev["executor_main"], "s1-007-test-producer")
        self.assertEqual(self.ev["executor_rerun"],
                         "s1-007-test-auditor")

    def test_iso_counters_zero_for_honest_variants(self):
        for variant in ("per_scope", "shared_rls"):
            self.assertEqual(sum(self.ev["iso_counters_main"][variant]
                                 .values()), 0, variant)
            self.assertEqual(sum(self.ev["iso_counters_rerun"][variant]
                                 .values()), 0, variant)

    def test_probes_detected_through_real_rules(self):
        expected = {"A_existence_oracle": "FAIL",
                    "B_stale_cache": "FAIL",
                    "C_postfilter": "FAIL",
                    "D_forged_scope_provenance_loss":
                        "FAIL+INCOMPARABLE"}
        for pid, expect in expected.items():
            self.assertEqual(self.ev["probe_rejections"][pid]["detected"],
                             expect, pid)

    def test_cross_executor_determinism(self):
        for variant in ("per_scope", "shared_rls"):
            self.assertEqual(
                self.ev["metrics"][variant]
                ["determinism_share_cross_executor"], 1.0, variant)

    def test_deny_equivalence_and_no_materialize_before_policy(self):
        for variant in ("per_scope", "shared_rls"):
            self.assertTrue(self.ev["metrics"][variant]["deny_equivalence"])
            self.assertEqual(
                self.ev["metrics"][variant]["materialize_before_policy"], 0)

    def test_timing_within_frozen_tolerance(self):
        for variant in ("per_scope", "shared_rls"):
            self.assertEqual(
                self.ev["timing_analysis"]["variants"][variant]["verdict"],
                "WITHIN_TOLERANCE", variant)

    def test_sensitivity_no_winner_flips(self):
        self.assertEqual(self.ev["sensitivity"]["flip_count"], 0)

    def test_full_run_files_carry_verifiable_provenance(self):
        doc = GoldenFixture.state["doc_a"]
        self.assertFalse(doc["provenance"]["dirty"])
        self.assertEqual(len(doc["runs"]), 84)


class TestMatrixFailClosed(unittest.TestCase):
    """Each test mutates a FRESH copy of the golden base and asserts the
    evaluator fails closed with a non-zero exit path (EvalError) or a
    FAIL verdict derived from its own rules."""

    def _evaluate(self, base: Path):
        doc_a = json.loads((base / "run-a" / "run-manifest.json")
                           .read_text(encoding="utf-8"))
        return evaluator.evaluate(
            base / "run-a" / "run-manifest.json",
            base / "run-b" / "run-manifest.json",
            doc_a["provenance"]["commit"],
            base / "probes.json", sha((base / "probes.json").read_bytes()),
            base / "evaluation.json", "nonce-mutation")

    def _rewrite_manifest(self, base: Path, which: str, mutator) -> None:
        path = base / which / "run-manifest.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        mutator(doc)
        path.write_text(json.dumps(doc, indent=2, sort_keys=True),
                        encoding="utf-8")
        seal_manifest(path)

    def test_missing_run_rejected(self):
        base = GoldenFixture.fresh_copy(
            Path(tempfile.mkdtemp(prefix="s1007-missing-")))
        run_file = next((base / "run-a" / "runs").glob(
            "per_scope__same-scope-authorized__101.json"))
        run_file.unlink()
        manifest = base / "run-a" / "run-manifest.json"
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        doc["runs"] = [r for r in doc["runs"]
                       if "same-scope-authorized__101" not in r["run_id"]]
        manifest.write_text(json.dumps(doc, sort_keys=True))
        seal_manifest(manifest)
        with self.assertRaises(evaluator.EvalError):
            self._evaluate(base)

    def test_extra_run_rejected(self):
        base = GoldenFixture.fresh_copy(
            Path(tempfile.mkdtemp(prefix="s1007-extra-")))
        doc = json.loads((base / "run-a" / "run-manifest.json")
                         .read_text(encoding="utf-8"))
        extra = dict(doc["runs"][0])
        extra["run_id"] = "per_scope|same-scope-authorized|999"
        extra["path"] = "999.json"
        (base / "run-a" / "runs" / "999.json").write_text(
            (base / "run-a" / "runs" / doc["runs"][0]["path"]
             ).read_text(encoding="utf-8"), encoding="utf-8")
        extra["sha256"] = sha((base / "run-a" / "runs" / "999.json")
                              .read_bytes())
        doc["runs"].append(extra)
        (base / "run-a" / "run-manifest.json").write_text(
            json.dumps(doc, sort_keys=True), encoding="utf-8")
        seal_manifest(base / "run-a" / "run-manifest.json")
        with self.assertRaises(evaluator.EvalError):
            self._evaluate(base)

    def test_duplicate_run_rejected(self):
        base = GoldenFixture.fresh_copy(
            Path(tempfile.mkdtemp(prefix="s1007-dup-")))
        doc = json.loads((base / "run-a" / "run-manifest.json")
                         .read_text(encoding="utf-8"))
        doc["runs"].append(dict(doc["runs"][0]))
        (base / "run-a" / "run-manifest.json").write_text(
            json.dumps(doc, sort_keys=True), encoding="utf-8")
        seal_manifest(base / "run-a" / "run-manifest.json")
        with self.assertRaises(evaluator.EvalError):
            self._evaluate(base)

    def test_path_traversal_rejected(self):
        base = GoldenFixture.fresh_copy(
            Path(tempfile.mkdtemp(prefix="s1007-trav-")))
        doc = json.loads((base / "run-a" / "run-manifest.json")
                         .read_text(encoding="utf-8"))
        doc["runs"][0]["path"] = "../../" + doc["runs"][0]["path"]
        (base / "run-a" / "run-manifest.json").write_text(
            json.dumps(doc, sort_keys=True), encoding="utf-8")
        seal_manifest(base / "run-a" / "run-manifest.json")
        with self.assertRaises(evaluator.EvalError):
            self._evaluate(base)

    def test_run_digest_mismatch_rejected(self):
        base = GoldenFixture.fresh_copy(
            Path(tempfile.mkdtemp(prefix="s1007-dig-")))
        run_file = next((base / "run-a" / "runs").glob(
            "shared_rls__foreign-id-valid__101.json"))
        raw = json.loads(run_file.read_text(encoding="utf-8"))
        raw["observations"][0]["decision"] = "deny"
        run_file.write_text(json.dumps(raw, sort_keys=True),
                            encoding="utf-8")
        with self.assertRaises(evaluator.EvalError):
            self._evaluate(base)

    def test_empty_observations_rejected(self):
        base = GoldenFixture.fresh_copy(
            Path(tempfile.mkdtemp(prefix="s1007-empty-")))
        run_file = next((base / "run-a" / "runs").glob(
            "shared_rls__foreign-id-valid__101.json"))
        raw = json.loads(run_file.read_text(encoding="utf-8"))
        raw["observations"] = []
        raw_new = json.dumps(raw, sort_keys=True)
        # rewrite the run file AND its manifest digest so only the empty
        # observations trigger (not a digest mismatch)
        raw["contract_hashes"] = raw["contract_hashes"]
        run_file.write_text(raw_new, encoding="utf-8")
        doc = json.loads((base / "run-a" / "run-manifest.json")
                         .read_text(encoding="utf-8"))
        for r in doc["runs"]:
            if r["run_id"] == "shared_rls|foreign-id-valid|101":
                r["sha256"] = sha(run_file.read_bytes())
        (base / "run-a" / "run-manifest.json").write_text(
            json.dumps(doc, sort_keys=True), encoding="utf-8")
        seal_manifest(base / "run-a" / "run-manifest.json")
        with self.assertRaises(evaluator.EvalError):
            self._evaluate(base)

    def test_mixed_commit_rejected(self):
        base = GoldenFixture.fresh_copy(
            Path(tempfile.mkdtemp(prefix="s1007-commit-")))
        self._rewrite_manifest(
            base, "run-b",
            lambda doc: doc["provenance"].update(
                {"commit": "f" * 40}))
        with self.assertRaises(evaluator.EvalError):
            self._evaluate(base)

    def test_dirty_provenance_rejected(self):
        base = GoldenFixture.fresh_copy(
            Path(tempfile.mkdtemp(prefix="s1007-dirty-")))
        self._rewrite_manifest(
            base, "run-a",
            lambda doc: doc["provenance"].update(
                {"dirty": True, "dirty_lines": [" M src/agentos/db.py"]}))
        with self.assertRaises(evaluator.EvalError):
            self._evaluate(base)

    def test_same_executor_identity_rejected(self):
        base = GoldenFixture.fresh_copy(
            Path(tempfile.mkdtemp(prefix="s1007-exec-")))
        self._rewrite_manifest(
            base, "run-b",
            lambda doc: doc["provenance"].update(
                {"executor_id": "s1-007-test-producer"}))
        with self.assertRaises(evaluator.EvalError):
            self._evaluate(base)

    def test_contract_hash_divergence_rejected(self):
        base = GoldenFixture.fresh_copy(
            Path(tempfile.mkdtemp(prefix="s1007-hash-")))
        run_file = next((base / "run-a" / "runs").glob(
            "per_scope__same-scope-authorized__101.json"))
        raw = json.loads(run_file.read_text(encoding="utf-8"))
        raw["contract_hashes"]["rubric.json"] = "0" * 64
        run_file.write_text(json.dumps(raw, sort_keys=True),
                            encoding="utf-8")
        doc = json.loads((base / "run-a" / "run-manifest.json")
                         .read_text(encoding="utf-8"))
        for r in doc["runs"]:
            if r["run_id"] == "per_scope|same-scope-authorized|101":
                r["sha256"] = sha(run_file.read_bytes())
        (base / "run-a" / "run-manifest.json").write_text(
            json.dumps(doc, sort_keys=True), encoding="utf-8")
        seal_manifest(base / "run-a" / "run-manifest.json")
        with self.assertRaises(evaluator.EvalError):
            self._evaluate(base)

    def test_probes_digest_mismatch_rejected(self):
        base = GoldenFixture.fresh_copy(
            Path(tempfile.mkdtemp(prefix="s1007-probe-")))
        doc_a = json.loads((base / "run-a" / "run-manifest.json")
                           .read_text(encoding="utf-8"))
        with self.assertRaises(evaluator.EvalError):
            evaluator.evaluate(
                base / "run-a" / "run-manifest.json",
                base / "run-b" / "run-manifest.json",
                doc_a["provenance"]["commit"], base / "probes.json",
                "0" * 64, base / "evaluation.json", "nonce-x")


class TestISODerivation(unittest.TestCase):
    """Mutate run observations; the evaluator must detect each violation
    from RAW data even when the runner-side summary lies."""

    def _mutated_run(self, base: Path, run_id: str, mutate) -> Path:
        path = base / "run-a" / "runs" / (
            run_id.replace("|", "__") + ".json")
        raw = json.loads(path.read_text(encoding="utf-8"))
        mutate(raw)
        path.write_text(json.dumps(raw, sort_keys=True),
                        encoding="utf-8")
        doc = json.loads((base / "run-a" / "run-manifest.json")
                         .read_text(encoding="utf-8"))
        for r in doc["runs"]:
            if r["run_id"] == run_id:
                r["sha256"] = sha(path.read_bytes())
        (base / "run-a" / "run-manifest.json").write_text(
            json.dumps(doc, sort_keys=True), encoding="utf-8")
        seal_manifest(base / "run-a" / "run-manifest.json")
        return base

    def _evaluate_verdict(self, base: Path):
        doc_a = json.loads((base / "run-a" / "run-manifest.json")
                           .read_text(encoding="utf-8"))
        return evaluator.evaluate(
            base / "run-a" / "run-manifest.json",
            base / "run-b" / "run-manifest.json",
            doc_a["provenance"]["commit"], base / "probes.json",
            sha((base / "probes.json").read_bytes()),
            base / "evaluation.json", "nonce-iso")

    def test_cross_scope_content_leak_detected_despite_lying_summary(self):
        GoldenFixture.build()
        base = GoldenFixture.fresh_copy(
            Path(tempfile.mkdtemp(prefix="s1007-leak-")))
        run_id = "shared_rls|foreign-id-valid|101"

        def inject(raw):
            # forged allow with foreign content AND a lying runner summary
            raw["iso_counters"] = {k: 0 for k in runner.ISO_KEYS}
            raw["observations"][0]["decision"] = "allow"
            raw["observations"][0]["reason_class"] = None
            raw["observations"][0]["response"] = {
                "objects": [{"id": "mem-0001-alpha", "version": 1,
                             "kind": "memory_record", "scope": "SCP-A",
                             "digest": "x", "content": "SECRET",
                             "provenance": {
                                 "canonical_source_id": "s",
                                 "publisher_id": "p",
                                 "independence_group": "i",
                                 "resolver_version": "r",
                                 "created_by_activity": "a"}}],
                "result": "ok", "meta": {"result_count": 1,
                                         "ranks": [], "snippets": []}}
        self._mutated_run(base, run_id, inject)
        ev = self._evaluate_verdict(base)
        self.assertEqual(ev["verdict"], "FAIL")
        self.assertGreater(sum(ev["iso_counters_main"]["shared_rls"]
                               .values()), 0)

    def test_metadata_and_count_leak_in_deny_detected(self):
        GoldenFixture.build()
        base = GoldenFixture.fresh_copy(
            Path(tempfile.mkdtemp(prefix="s1007-meta-")))

        def inject(raw):
            raw["observations"][0]["response"] = {
                "objects": [], "result": "empty",
                "detail": {"exists": True, "kind": "memory_record",
                           "total_in_index": 8}}
        self._mutated_run(base, "per_scope|nonexistent-id-control|101",
                          inject)
        ev = self._evaluate_verdict(base)
        self.assertEqual(ev["verdict"], "FAIL")

    def test_forged_and_malformed_scope_fail_closed_in_runner(self):
        GoldenFixture.build()
        world = runner.load_world()
        for variant in (runner.PerScopeVariant, runner.SharedRLSVariant):
            v = variant(world)
            forged = v.retrieve("bruno", "q-runbook", "mem-0001-alpha",
                                claimed_scope="t-alpha/w-main/goal-AAAA-1111")
            self.assertEqual(forged["decision"], "deny")
            self.assertEqual(forged["effective_scope"], "SCP-B")
            malformed = v.retrieve("mallory", "q-runbook",
                                   "mem-0001-alpha",
                                   claimed_scope="../../t-alpha")
            self.assertEqual(malformed["decision"], "deny")
            self.assertIsNone(malformed["effective_scope"])
            unknown = v.retrieve("mallory", "q-runbook", "mem-0001-alpha",
                                 claimed_scope="t-none/w-none/goal-none")
            self.assertEqual(unknown["decision"], "deny")
            self.assertIsNone(unknown["effective_scope"])
            self.assertEqual(
                unknown["response"],
                world.fixtures["canonical_deny_body"])

    def test_stale_cache_after_revoke_never_served_by_honest_variants(self):
        GoldenFixture.build()
        world = runner.load_world()
        for variant in (runner.PerScopeVariant, runner.SharedRLSVariant):
            v = variant(world)
            first = v.retrieve("alice", "q-runbook", "mem-0001-alpha")
            self.assertEqual(first["decision"], "allow")
            obs = {"policy_checks": [], "cache_events": []}
            v.op_revoke("SCP-A", "mem-0001-alpha", obs)
            second = v.retrieve("alice", "q-runbook", "mem-0001-alpha")
            self.assertEqual(second["decision"], "deny")
            self.assertEqual(
                second["response"], runner.DENY_BODY)
            self.assertIn("stale_invalidated", second["cache_events"])

    def test_lost_provenance_detected(self):
        GoldenFixture.build()
        base = GoldenFixture.fresh_copy(
            Path(tempfile.mkdtemp(prefix="s1007-prov-")))

        def inject(raw):
            raw["observations"][0]["response"]["objects"][0][
                "provenance"] = {}
        self._mutated_run(base, "per_scope|same-scope-authorized|101",
                          inject)
        ev = self._evaluate_verdict(base)
        self.assertEqual(ev["verdict"], "FAIL")
        self.assertGreater(ev["iso_counters_main"]["per_scope"]["ISO5"], 0)

    def test_background_reindex_scope_bound_and_provenance_preserved(self):
        GoldenFixture.build()
        world = runner.load_world()
        for variant in (runner.PerScopeVariant, runner.SharedRLSVariant):
            v = variant(world)
            obs = {"policy_checks": []}
            result = v.op_background_reindex("SCP-A", obs)
            self.assertTrue(result["provenance_preserved"])
            for entry in result["entries"]:
                self.assertEqual(entry["scope"], "SCP-A")
                self.assertEqual(len(entry["provenance"]), 5)

    def test_timing_no_data_is_limitation_not_pass(self):
        analysis = evaluator.analyze_timing({}, {})
        self.assertIn("NO_DATA", analysis)
        # a signal above tolerance is a finding, never silently a pass
        synthetic = {"variants": {"per_scope": {
            "arms": {"valid_foreign_id": {"median_ns": 5000},
                     "nonexistent_id": {"median_ns": 2000}}}}}
        contract = json.loads((S1007 / "isolation-contract.json")
                              .read_text(encoding="utf-8"))
        out = evaluator.analyze_timing(synthetic, contract)
        self.assertEqual(
            out["variants"]["per_scope"]["verdict"],
            "SIGNAL_ABOVE_TOLERANCE")

    def test_supersede_and_move_invalidation_semantics(self):
        GoldenFixture.build()
        world = runner.load_world()
        for variant in (runner.PerScopeVariant, runner.SharedRLSVariant):
            v = variant(world)
            obs = {"policy_checks": []}
            v.op_supersede("SCP-A", "mem-0003-alpha", 2, obs)
            old = v.retrieve("alice", "q-rotation", "mem-0003-alpha",
                             version=1)
            self.assertEqual(old["decision"], "deny")
            new = v.retrieve("alice", "q-rotation", "mem-0003-alpha",
                             version=2)
            self.assertEqual(new["decision"], "allow")
            move_obs = {"policy_checks": []}
            v.op_move("SCP-A", "SCP-B", "art-0002-alpha", move_obs)
            gone = v.retrieve("alice", "q-bench", "art-0002-alpha")
            self.assertEqual(gone["decision"], "deny")
            moved = v.retrieve("bruno", "q-bench", "art-0002-alpha")
            self.assertEqual(moved["decision"], "allow")
            self.assertEqual(moved["response"]["objects"][0]["scope"],
                             "SCP-B")

    def test_cross_scope_cache_collision_never_hits(self):
        GoldenFixture.build()
        world = runner.load_world()
        for variant in (runner.PerScopeVariant, runner.SharedRLSVariant):
            v = variant(world)
            v.retrieve("alice", "q-common", "mem-0001-alpha")
            other = v.retrieve("bruno", "q-common", "mem-0101-beta")
            self.assertNotIn("hit", other["cache_events"])
            self.assertEqual(other["decision"], "allow")
            self.assertEqual(other["response"]["objects"][0]["scope"],
                             "SCP-B")

    def test_aggregates_only_over_authorized_rows(self):
        GoldenFixture.build()
        world = runner.load_world()
        for variant in (runner.PerScopeVariant, runner.SharedRLSVariant):
            v = variant(world)
            obs = v.op_aggregate("bruno", "q-common")
            meta = obs["response"]["meta"]
            ids = {r["id"] for r in meta["ranks"]} | \
                  {s["id"] for s in meta["snippets"]}
            self.assertTrue(ids <= {"mem-0101-beta", "art-0102-beta"})
            self.assertEqual(meta["total_count"], 2)

    def test_deterministic_rerun_same_seed_is_byte_identical(self):
        GoldenFixture.build()
        manifest = json.loads(
            (S1007 / "corpus-manifest.json").read_text(encoding="utf-8"))
        case = {c["id"]: c for c in manifest["cases"]}[  # noqa: C416
            "same-scope-authorized"]
        digests = set()
        for _ in range(2):
            v = runner.PerScopeVariant(runner.load_world())
            run = runner.execute_case(v, case, 101)
            digests.add(evaluator.sha_json(run["observations"]))
        self.assertEqual(len(digests), 1)

    def test_hard_isolation_failure_not_compensated_by_score(self):
        """Even a maximal score must not lift a FAIL verdict: the verdict
        rule checks ISO counters before the winner is named."""
        GoldenFixture.build()
        base = GoldenFixture.fresh_copy(
            Path(tempfile.mkdtemp(prefix="s1007-hard-")))
        run_id = "shared_rls|cache-collision-cross-scope|202"

        def inject(raw):
            for obs in raw["observations"]:
                if obs.get("op") == "retrieve" and \
                        obs.get("decision") == "allow":
                    obs["response"] = {
                        "objects": [{"id": "mem-0001-alpha", "version": 1,
                                     "kind": "memory_record",
                                     "scope": "SCP-A",
                                     "digest": "x",
                                     "content": "alpha secret",
                                     "provenance": {
                                         "canonical_source_id": "s",
                                         "publisher_id": "p",
                                         "independence_group": "i",
                                         "resolver_version": "r",
                                         "created_by_activity": "a"}}],
                        "result": "ok",
                        "meta": {"result_count": 1, "ranks": [],
                                 "snippets": []}}
        self._mutated_run(base, run_id, inject)
        ev = self._evaluate_verdict(base)
        self.assertEqual(ev["verdict"], "FAIL")


class TestFrozenContracts(unittest.TestCase):
    def test_frozen_files_parse_and_are_consistent(self):
        contract = json.loads((S1007 / "isolation-contract.json")
                              .read_text(encoding="utf-8"))
        rubric = json.loads((S1007 / "rubric.json").read_text(
            encoding="utf-8"))
        corpus = json.loads((S1007 / "corpus-manifest.json").read_text(
            encoding="utf-8"))
        fixtures = json.loads((S1007 / "fixtures.json").read_text(
            encoding="utf-8"))
        self.assertEqual(len(rubric["dimensions"]), 11)
        self.assertAlmostEqual(
            sum(d["weight"] for d in rubric["dimensions"]), 1.0, places=6)
        self.assertEqual(contract["hard_invariants"]["ISO1"],
                         "the caller never receives content bytes of "
                         "another scope")
        self.assertGreaterEqual(len(fixtures["scopes"]), 3)
        self.assertGreaterEqual(len(corpus["cases"]), 12)
        self.assertGreaterEqual(len(corpus["seeds"]), 3)

    def test_iso_keys_complete(self):
        self.assertEqual(len(runner.ISO_KEYS), 8)
        self.assertEqual(set(runner.ISO_KEYS), set(evaluator.ISO_KEYS))


if __name__ == "__main__":
    unittest.main()
