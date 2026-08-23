"""R5: stage gates participate in the release Gate."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agentos.db import open_db  # noqa: E402
from agentos.engine import Engine  # noqa: E402
from agentos.gates import Gates  # noqa: E402
from agentos.gateway import ToolContract, ToolGateway  # noqa: E402
from agentos.journal import Journal  # noqa: E402
from agentos.stage_evals import StageEvals  # noqa: E402

SRC = ("def greet(name):\n"
       "    return f'hello, {name}'\n\n\n"
       "def test_greet():\n"
       "    assert greet('world') == 'hello, world'\n")


def _write(path, content):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"written": str(p)}


class TestStageGateIntegration(unittest.TestCase):
    """A failing stage gate for the goal forces release REJECTED; a passing
    one leaves the outcome ACCEPTED."""

    def _flow(self, gate_pass: bool) -> dict:
        import tempfile
        root = Path(tempfile.mkdtemp())
        db = open_db(root / "agentos.db")
        eng = Engine(db, root)
        j = Journal(db)
        gw = ToolGateway(db, j)
        ev = __import__("agentos.evaluator", fromlist=["Evaluator"]) \
            if False else None
        from agentos.gates import Evaluator
        ev = Evaluator(db, root)
        se = StageEvals(db, root)

        gw.register(ToolContract(
            name="fs.write.handler", version="1.0.0",
            input_schema={"type": "object",
                          "properties": {"path": {"type": "string"},
                                         "content": {"type": "string"}},
                          "required": ["path", "content"]},
            required_capability="fs.write_local",
            effect_class="write_local", idempotency="keyed",
            handler=_write))

        goal_id = eng.create_goal("stage gate integration probe")
        eng.refine_spec(goal_id, "spec v1", criteria=[
            {"criterion_id": "has_code", "kind": "tests_present"}])
        eng.activate_goal(goal_id)
        eng.plan_tasks(goal_id, [{"key": "impl", "title": "Implement greet",
                                  "definition_of_done":
                                      "greet.py via gateway"}])
        eng.schedule_ready_tasks(goal_id)
        task_id = db.conn.execute(
            "SELECT id FROM task WHERE goal_id=?",
            (goal_id,)).fetchone()[0]
        run_id, ctx = eng.open_run(task_id)
        gw.invoke(ctx, gw.resolve("fs.write.handler"),
                  {"path": str(Path(ctx.workspace_path) / "greet.py"),
                   "content": SRC}, idempotency_key=f"{run_id}:w")
        eng.complete_live_run(ctx)
        ev.run(goal_id, "has_code")

        if gate_pass:
            did, _ = se.define(stage="verification", kind="deterministic",
                               metric="conformity", threshold=1.0)
            se.run_case(did, {"id": "sg-case"}, lambda c: (True, {}),
                        goal_id=goal_id)
            se.stage_gate("verification", [did], goal_id=goal_id)
        else:
            se.stage_gate("verification", [], goal_id=goal_id)  # fail-closed

        eng.submit_to_gate(goal_id)
        return Gates(db, j).evaluate_release(goal_id)

    def test_failing_stage_gate_blocks(self):
        res = self._flow(gate_pass=False)
        self.assertEqual(res["result"], "fail")
        self.assertTrue(any("stage gate" in r for r in res["reasons"]),
                        res["reasons"])

    def test_passing_stage_gate_does_not_block(self):
        res = self._flow(gate_pass=True)
        self.assertEqual(res["result"], "pass", res["reasons"])


if __name__ == "__main__":
    unittest.main()
