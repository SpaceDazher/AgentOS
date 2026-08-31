"""Unit tests for the optional executable ``probes`` block in research bundles.

Verifies the fail-closed contract introduced by the S1-001/S1-002 review:
  - a probe can drop the evaluation verdict;
  - ``abstain`` is NOT a pass;
  - a probe command cannot escape the workspace (path confinement);
  - an unknown command fails rather than being silently skipped.
All probing is stdlib-only and run in an isolated subprocess.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentos.db import open_db  # noqa: E402
from agentos.research import (  # noqa: E402
    _confine_probe_argv,
    _execute_probes,
    _normalise_probes,
    _run_one_probe,
    fixture_bundle,
    run_research_plan,
)


def _write_probe(root: Path, name: str, observed: str) -> Path:
    path = root / name
    path.write_text(
        "import json,sys\n"
        f"print(json.dumps({{'observed': {observed!r}}}))\n",
        encoding="utf-8")
    return path


class TestProbeConfinement(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()

    def test_bare_program_and_internal_path_are_allowed(self):
        err = _confine_probe_argv(
            ["python", "research/tickets/stage-1/S1-001/promotion_probes.py"],
            self.root)
        self.assertIsNone(err)

    def test_absolute_program_is_refused(self):
        err = _confine_probe_argv(
            ["C:/Windows/System32/cmd.exe", "whoami"], self.root)
        self.assertIsNotNone(err)

    def test_traversal_path_argument_is_refused(self):
        err = _confine_probe_argv(["python", "../../escape.py"], self.root)
        self.assertIsNotNone(err)

    def test_absolute_path_argument_is_refused(self):
        err = _confine_probe_argv(["python", "C:/root/script.py"], self.root)
        self.assertIsNotNone(err)

    def test_dotted_traversal_is_refused(self):
        err = _confine_probe_argv(["python", "../run_me.py"], self.root)
        self.assertIsNotNone(err)


class TestProbeExecution(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()

    def test_passing_probe_returns_pass(self):
        script = _write_probe(self.root, "ok.py", "pass")
        probe = {"name": "p", "command": f"python {script.name}", "expected": "pass"}
        records, failures = _execute_probes(
            {"probes": [probe]}, self.root)
        self.assertEqual(failures, [], failures)
        self.assertEqual(records[0]["observed"], "pass")
        self.assertTrue(records[0]["passed"])

    def test_abstain_is_not_a_pass(self):
        script = _write_probe(self.root, "abs.py", "abstain")
        probe = {"name": "p", "command": f"python {script.name}", "expected": "pass"}
        records, failures = _execute_probes({"probes": [probe]}, self.root)
        self.assertEqual(records[0]["observed"], "abstain")
        self.assertFalse(records[0]["passed"])
        self.assertTrue(any("p" in f for f in failures))

    def test_explicit_abstain_expected_passes(self):
        script = _write_probe(self.root, "abs.py", "abstain")
        probe = {"name": "p", "command": f"python {script.name}", "expected": "abstain"}
        records, failures = _execute_probes({"probes": [probe]}, self.root)
        self.assertTrue(records[0]["passed"])
        self.assertEqual(failures, [])

    def test_expected_fail_with_fail_observed_passes(self):
        script = _write_probe(self.root, "bad.py", "fail")
        probe = {"name": "p", "command": f"python {script.name}", "expected": "fail"}
        records, failures = _execute_probes({"probes": [probe]}, self.root)
        self.assertTrue(records[0]["passed"])
        self.assertEqual(failures, [])

    def test_expected_fail_with_pass_observed_fails(self):
        script = _write_probe(self.root, "ok.py", "pass")
        probe = {"name": "p", "command": f"python {script.name}", "expected": "fail"}
        records, failures = _execute_probes({"probes": [probe]}, self.root)
        self.assertFalse(records[0]["passed"])
        self.assertTrue(failures)

    def test_unknown_command_is_fail_not_silent_skip(self):
        probe = {"name": "p", "command": "definitely-not-a-real-program foo",
                 "expected": "pass"}
        records, failures = _execute_probes({"probes": [probe]}, self.root)
        self.assertEqual(records[0]["observed"], "fail")
        self.assertFalse(records[0]["passed"])
        self.assertEqual(len(records), 1)
        self.assertTrue(failures)

    def test_fail_closed_no_parsable_verdict(self):
        script = self.root / "nojson.py"
        script.write_text("print('hello world')\n", encoding="utf-8")
        probe = {"name": "p", "command": f"python {script.name}", "expected": "pass"}
        records, failures = _execute_probes({"probes": [probe]}, self.root)
        self.assertEqual(records[0]["observed"], "abstain")
        self.assertFalse(records[0]["passed"])
        self.assertTrue(failures)


class TestProbeNormalisation(unittest.TestCase):
    def test_malformed_probe_is_a_validation_error(self):
        probes, errors = _normalise_probes(
            {"probes": [{"name": "", "command": "x", "expected": "pass"},
                        {"name": "a", "command": "", "expected": "pass"},
                        {"name": "b", "command": "x", "expected": "maybe"}]})
        self.assertEqual(probes, [])
        self.assertTrue(errors)

    def test_valid_probes_normalise(self):
        probes, errors = _normalise_probes(
            {"probes": [{"name": "ok", "command": "python a.py", "expected": "pass"}]})
        self.assertEqual(len(probes), 1)
        self.assertEqual(errors, [])


class TestProbeDropsVerdict(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.db = open_db(self.root / "agentos.db")

    def tearDown(self):
        self.db.conn.close()

    def _bundle_with_probe(self, probe_script_rel: str | None, expected: str):
        b = fixture_bundle("probe verdict")
        probes = []
        if probe_script_rel:
            probes.append({"name": "probe-x",
                           "command": f"python {probe_script_rel}",
                           "expected": expected})
        b["probes"] = probes
        return b

    def test_passing_probe_keeps_pass(self):
        script = _write_probe(self.root, "ok.py", "pass")
        result = run_research_plan(
            self.db, self.root, "probe pass", self._bundle_with_probe(script.name, "pass"),
            workspace_root=self.root)
        self.assertEqual(result["status"], "pass", result)
        self.assertEqual(result["probes"][0]["observed"], "pass")

    def test_failing_probe_drops_verdict_to_fail(self):
        script = _write_probe(self.root, "bad.py", "fail")
        result = run_research_plan(
            self.db, self.root, "probe fail", self._bundle_with_probe(script.name, "pass"),
            workspace_root=self.root)
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(any("probe" in r for r in result["evaluation"]["reasons"]))

    def test_abstain_probe_drops_verdict_to_fail(self):
        script = _write_probe(self.root, "abs.py", "abstain")
        result = run_research_plan(
            self.db, self.root, "probe abstain",
            self._bundle_with_probe(script.name, "pass"), workspace_root=self.root)
        self.assertEqual(result["status"], "fail", result)
        self.assertTrue(any("abstain" in r.lower() or "probe" in r.lower()
                            for r in result["evaluation"]["reasons"]))

    def test_probes_absent_has_empty_probe_list_and_passes(self):
        b = self._bundle_with_probe(None, "pass")
        result = run_research_plan(self.db, self.root, "no probes", b,
                                   workspace_root=self.root)
        self.assertEqual(result["status"], "pass", result)
        self.assertEqual(result["probes"], [])


if __name__ == "__main__":
    unittest.main()
