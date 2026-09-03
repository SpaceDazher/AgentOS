"""Independent acceptance probes for the nine S1-011 R2 findings."""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_s1_011_regressions import (
    S1011, runner, evaluator, compare_runs, dependency_gate, make_bundle,
    load, run_design,
)


def positive():
    case = copy.deepcopy(next(c for c in load("cases.json")["cases"]
                              if c["case_id"] == "S1-011-V01"))
    for ev in case["evidence"]:
        ev.update(source_status="ACTIVE", scope=case["scope"],
                  claim_version=case["assertion"]["claim_version"])
    return case


def rehash(row):
    previous = "0" * 64
    for rec in row["ledger"]:
        rec["prev"] = previous
        rec["hash"] = evaluator.sha(evaluator.canonical({
            k: rec[k] for k in ("kind", "id", "prev", "payload")}))
        previous = rec["hash"]
    row["output_sha256"] = evaluator.sha(evaluator.canonical({
        k: v for k, v in row.items() if k != "output_sha256"}))


class IndependentReviewR3(unittest.TestCase):
    def test_read_without_bound_evidence_hidden(self):
        case = positive()
        case.update(action="read_view", prior_status="PROMOTED", evidence=[])
        self.assertFalse(runner.decide_minimal(runner.Case(case), 11011)["view_visible"])

    def test_r1_missing_binding_cannot_promote(self):
        for field in ("source_status", "scope", "claim_version"):
            for value in (None, "missing", False):
                with self.subTest(field=field, value=value):
                    case = positive()
                    for ev in case["evidence"]:
                        if value == "missing":
                            ev.pop(field)
                        else:
                            ev[field] = value
                    row = runner.decide_minimal(runner.Case(case), 11011)
                    self.assertNotEqual(row["decision"], "PROMOTED")
                    self.assertFalse(row["view_visible"])

    def test_r2_derived_challenged_claim_cannot_promote(self):
        case = positive()
        case.update(action="derive_claim", derive={"own_evidence": True},
                    challenge={"state": "open", "in_scope": True})
        row = runner.decide_minimal(runner.Case(case), 11011)
        self.assertNotEqual(row["decision"], "PROMOTED")
        self.assertFalse(row["view_visible"])

    def test_r3_revoked_and_superseded_views_hidden(self):
        for mode in ("revoked", "superseded"):
            with self.subTest(mode=mode):
                case = positive()
                case.update(action="read_view", prior_status="PROMOTED")
                if mode == "revoked":
                    for ev in case["evidence"]:
                        ev["source_status"] = "REVOKED"
                else:
                    case["superseded_by"] = "successor-claim"
                self.assertFalse(runner.decide_minimal(
                    runner.Case(case), 11011)["view_visible"])

    def test_r4_rehashed_record_deletion_rejected(self):
        for kind in ("assertion", "evidence", "audit"):
            with self.subTest(kind=kind):
                rows = copy.deepcopy(run_design("minimal-gate"))
                row = next(r for r in rows if r["case_id"] == "S1-011-V01")
                row["ledger"] = [r for r in row["ledger"] if r["kind"] != kind]
                rehash(row)
                raw = {"design": "minimal-gate", "seed": 11011, "rows": rows}
                original = evaluator.load_json
                with patch.object(evaluator, "load_json", side_effect=lambda p:
                                  raw if Path(p).name == "raw-observations.json"
                                  else original(p)):
                    result = evaluator.evaluate(Path("unused-run"))
                self.assertEqual(result["verdict"], "FAIL")

    def test_r5_empty_seed_cells_rejected_by_main(self):
        roots = [compare_runs.load_root(S1011 / "results" / name)
                 for name in ("run-a", "run-b")]
        for root in roots:
            for cell in root.values():
                if cell["manifest"]["seed"] != 11011:
                    cell["rows"] = []
        with tempfile.TemporaryDirectory() as td:
            args = ["compare", "--a", "A", "--b", "B", "--out", td + "/c",
                    "--metrics", td + "/m", "--probes", td + "/p",
                    "--sensitivity", td + "/s"]
            with patch.object(sys, "argv", args), patch.object(
                    compare_runs, "load_root", side_effect=roots), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertNotEqual(compare_runs.main(), 0)

    def test_r6_nonexistent_git_objects_rejected(self):
        a = compare_runs.load_root(S1011 / "results/run-a")
        b = compare_runs.load_root(S1011 / "results/run-b")
        for root in (a, b):
            for cell in root.values():
                cell["manifest"].update(commit="0" * 40, tree="0" * 40)
        self.assertTrue(compare_runs.check_series(a, b, load("corpus-manifest.json")))

    def test_r7_dependency_identity_bound(self):
        record = json.loads((S1011.parent / "S1-001/evaluation-record.json")
                            .read_text(encoding="utf-8"))
        for field in ("ticket_id", "goal_id", "campaign_id", "evaluation_id",
                      "artifact_chain_hash"):
            with self.subTest(field=field):
                altered = copy.deepcopy(record)
                altered[field] = "FAKE"
                result = dependency_gate.check("S1-001", rec_override=altered)
                self.assertNotEqual(result["status"], "PROVEN")

    def test_r8_inconsistent_summary_blocks_publication(self):
        original = make_bundle.load_result

        def altered(name):
            doc = copy.deepcopy(original(name))
            if name == "metrics.json":
                metrics = doc["designs"]["minimal-gate"]
                metrics["admissible"] = False
                metrics["hard_counters"]["authority_expansion_count"] = 1
                metrics["verdict"] = "PASS"
            return doc

        with patch.object(make_bundle, "load_result", side_effect=altered), \
                patch.object(Path, "write_text") as output, \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(make_bundle.main(), 0)
            output.assert_not_called()

    def test_r9_simultaneous_unknowns_flagged(self):
        result = compare_runs.sensitivity(
            {"A": {"x": .9, "y": None}, "B": {"x": .8, "y": None}},
            {"x": .9, "y": .1})
        self.assertTrue(result["unknown_dependent"])
