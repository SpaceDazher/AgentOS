"""T02 evaluator failure must not produce false ACCEPTED."""
from pathlib import Path

from tests.base import AgentOSTestCase
from agentos.gates import Gates
from agentos.journal import TransitionError


class TestEvaluatorFailure(AgentOSTestCase):
    def test_t02_no_false_accept_without_passing_evaluation(self):
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        src = ("def greet(name):\n"
               "    return f'hello, {name}'\n\n\n"
               "def test_greet():\n"
               "    assert greet('world') == 'hello, world'\n")

        def _write(path, content):
            from pathlib import Path
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"written": str(p)}

        self.gw.register(self.write_contract(handler=_write))
        res = self.gw.invoke(ctx, self.gw.resolve("fs.write.handler"),
                             {"path": str(Path(ctx.workspace_path) / "greet.py"),
                              "content": src}, idempotency_key="t02")
        self.assertEqual(res["status"], "SUCCEEDED")
        self.eng.complete_live_run(ctx, outputs={"files": {"greet.py": src}})
        # a FAILING evaluation exists (bound to current version + chain), but no
        # passing one: submission proceeds, the gate must REJECT.
        from agentos.gates import Evaluator as _E
        chain_hash = _artifact_chain_hash_for(self.db, goal_id)
        self.db.conn.execute(
            "INSERT INTO evaluation(id, goal_id, subject_artifact_id, criterion_id,"
            " criterion_version, method, method_version, config_json, result,"
            " detail_json, artifact_chain_hash)"
            " VALUES ('e-fail', ?, NULL, 'has_code', 1, 'tests_present',"
            " 'eval-v2', '{}', 'fail', '{}', ?)", (goal_id, chain_hash))
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


def _artifact_chain_hash_for(db, goal_id: str) -> str:
    rows = db.conn.execute(
        "SELECT kind, version, content_sha256 FROM artifact_version"
        " WHERE goal_id=? AND status='CURRENT' ORDER BY kind, version",
        (goal_id,)).fetchall()
    from agentos.ids import canonical_json, sha256_text
    return sha256_text(canonical_json([dict(r) for r in rows]))

