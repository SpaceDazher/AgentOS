"""Phase 1 tests: versioned stage-eval entities, append-only semantics,
advisory-vs-required authority, judge provenance admissibility."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos.db import open_db
from agentos.stage_evals import StageEvalError, StageEvals


class StageEvalsCase(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = Path(tempfile.mkdtemp())
        self.db = open_db(self.root / "t.db")
        self.se = StageEvals(self.db, self.root)

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass


class TestDefinitions(StageEvalsCase):
    def test_define_and_version_bump(self):
        did, v1 = self.se.define(stage="concept", kind="deterministic",
                                 metric="clarity", threshold=0.8)
        did2, v2 = self.se.define(stage="concept", kind="deterministic",
                                  metric="clarity", threshold=0.9,
                                  def_id=did)
        self.assertEqual((did, did2), (did, did))
        self.assertEqual(v2, 2)
        latest = self.se.latest(did)
        self.assertEqual(latest["threshold"], 0.9)
        self.assertEqual(latest["version"], 2)
        # v1 row still intact (append-only history)
        old = self.db.conn.execute(
            "SELECT threshold FROM eval_definition WHERE id=? AND version=?",
            (did, 1)).fetchone()
        self.assertEqual(old["threshold"], 0.8)

    def test_update_delete_refused(self):
        did, _ = self.se.define(stage="plan", kind="deterministic",
                                metric="dag_valid", threshold=1.0)
        with self.assertRaises(Exception):
            self.db.conn.execute(
                "UPDATE eval_definition SET threshold=0 WHERE id=?", (did,))
        with self.assertRaises(Exception):
            self.db.conn.execute(
                "DELETE FROM eval_definition WHERE id=?", (did,))

    def test_llm_judge_requires_provenance_versions(self):
        with self.assertRaises(StageEvalError):
            self.se.define(stage="verification", kind="llm_judge",
                           metric="conformity", threshold=0.9)

    def test_unknown_stage_refused(self):
        with self.assertRaises(StageEvalError):
            self.se.define(stage="cooking", kind="deterministic",
                           metric="x", threshold=1.0)


class TestCases(StageEvalsCase):
    def test_add_and_query_cases_by_set_class(self):
        for i in range(2):
            self.se.add_case(case_id=f"gold{i}", corpus_version="c1",
                             stage="concept", label=f"g{i}",
                             set_class="gold", input_ref=f"fixtures/g{i}.json",
                             expected_outcome="pass")
        self.se.add_case(case_id="nm0", corpus_version="c1", stage="concept",
                         label="near miss", set_class="near_miss",
                         input_ref="fixtures/nm0.json", expected_outcome="fail")
        self.assertEqual(len(self.se.cases("c1", "gold")), 2)
        self.assertEqual(len(self.se.cases("c1")), 3)


class TestRunsAndGates(StageEvalsCase):
    def setUp(self):
        super().setUp()
        for gid in ("goal_A", "goal_B"):
            self.db.conn.execute(
                "INSERT INTO goal(id, concept_text, status) VALUES (?,?,?)",
                (gid, "probe", "ACTIVE"))

    def _defn(self, required=True, kind="deterministic", metric="traceability"):
        return self.se.define(stage="specification", kind=kind,
                              metric=metric, threshold=0.9,
                              required=required,
                              prompt_version="p1" if kind == "llm_judge" else None,
                              rubric_version="r1" if kind == "llm_judge" else None)

    def test_run_case_records_pass_and_fail(self):
        did, _ = self._defn()
        case = {"id": "c1", "label": "x"}
        r1 = self.se.run_case(did, case, lambda c: (True, {}),
                              goal_id="goal_A")
        r2 = self.se.run_case(did, case, lambda c: (False, {"why": "gap"}),
                              goal_id="goal_A")
        self.assertEqual(r1["outcome"], "pass")
        self.assertEqual(r2["outcome"], "fail")

    def test_required_failure_fails_gate_advisory_does_not(self):
        req_id, _ = self._defn(required=True)
        adv_id, _ = self._defn(required=False, metric="polish")
        bad = {"id": "c"}
        # both fail once (same goal)
        self.se.run_case(req_id, bad, lambda c: (False, {}), goal_id="goal_A")
        self.se.run_case(adv_id, bad, lambda c: (False, {}), goal_id="goal_A")
        gate = self.se.stage_gate("specification", [req_id, adv_id],
                                  goal_id="goal_A")
        self.assertEqual(gate["decision"], "fail")
        self.assertTrue(any("eval.specification.traceability" in r
                            for r in gate["reasons"]))
        # advisory failure alone must not fail the gate
        gate2 = self.se.stage_gate("specification", [adv_id],
                                   goal_id="goal_A")
        self.assertEqual(gate2["decision"], "pass")
        self.assertTrue(gate2["reasons"])   # but it is recorded

    def test_gate_fails_when_required_eval_has_no_runs(self):
        did, _ = self._defn(required=True)
        gate = self.se.stage_gate("specification", [did], goal_id="goal_B")
        self.assertEqual(gate["decision"], "fail")
        self.assertTrue(any("no eval runs" in r for r in gate["reasons"]))

    def test_llm_judge_without_model_id_inadmissible(self):
        did, _ = self._defn(kind="llm_judge", required=False)
        case = {"id": "c"}
        with self.assertRaises(StageEvalError):
            self.se.run_case(did, case, lambda c: (True, {}),
                             goal_id="goal_A",
                             judge={"prompt_version": "p1"})  # no model_id
        # with full provenance it runs and the judge block is persisted
        r = self.se.run_case(did, case, lambda c: (True, {}), goal_id="goal_A",
                             judge={"model_id": "m", "prompt_version": "p1",
                                    "rubric_version": "r1"})
        self.assertEqual(r["outcome"], "pass")
        row = self.db.conn.execute(
            "SELECT judge_json FROM eval_run WHERE id=?",
            (r["eval_run_id"],)).fetchone()
        self.assertEqual(json.loads(row["judge_json"])["model_id"], "m")


if __name__ == "__main__":
    unittest.main()
