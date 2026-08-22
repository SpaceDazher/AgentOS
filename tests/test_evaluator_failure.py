"""T02 evaluator failure must not produce false ACCEPTED."""
from tests.base import AgentOSTestCase
from agentos.gates import Gates
from agentos.journal import TransitionError


class TestEvaluatorFailure(AgentOSTestCase):
    def test_t02_no_false_accept_without_passing_evaluation(self):
        goal_id = self.make_goal_with_task()
        self.run_simple_task(goal_id)
        # a FAILING evaluation exists, but no passing one
        self.db.conn.execute(
            "INSERT INTO evaluation(id, goal_id, subject_artifact_id, criterion_id,"
            " method, method_version, result) VALUES ('e-fail', ?, NULL,"
            " 'has_code', 'tests_present', 'eval-v1', 'fail')", (goal_id,))
        # submit_to_gate requires an evaluation per criterion; the failing one
        # satisfies the submission precondition but the gate must still REJECT.

        self.eng.submit_to_gate(goal_id)
        gate = Gates(self.db, self.j).evaluate_release(goal_id)
        self.assertEqual(gate["result"], "fail")
        self.assertIn("has_code", " ".join(gate["reasons"]))
        status = self.db.conn.execute(
            "SELECT status FROM goal WHERE id=?", (goal_id,)).fetchone()[0]
        self.assertEqual(status, "REJECTED")
        # worker cannot force acceptance even from GATE_PENDING
        with self.assertRaises(TransitionError):
            self._worker_try_accept(goal_id)
        # revision loop: REJECTED → ACTIVE with new spec version
        self.eng.m.goal_transition(goal_id, "REJECTED", "ACTIVE", "requester")
        spec_count = self.db.conn.execute(
            "SELECT COUNT(*) FROM artifact_version WHERE goal_id=?"
            " AND kind='specification'", (goal_id,)).fetchone()[0]
        self.eng.refine_spec(goal_id, "revised spec", criteria=[
            {"criterion_id": "has_code", "kind": "tests_present"}])
        spec_count2 = self.db.conn.execute(
            "SELECT COUNT(*) FROM artifact_version WHERE goal_id=?"
            " AND kind='specification'", (goal_id,)).fetchone()[0]
        self.assertEqual(spec_count2, spec_count + 1)

    def _worker_try_accept(self, goal_id):
        from agentos.machines import Machines
        m = Machines(self.db, self.j)
        m.goal_transition(goal_id, "GATE_PENDING", "ACCEPTED", "worker")

