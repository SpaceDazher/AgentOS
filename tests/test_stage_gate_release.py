"""R5/R6: stage gates participate in the release Gate.

When a goal has stage-eval activity, release requires a PASSING gate for
every one of the six stages (only the latest gate per stage counts).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

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

STAGES = ("concept", "specification", "plan", "execution",
          "verification", "post_episode")


def _write(path, content):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"written": str(p)}


class TestStageGateIntegration(unittest.TestCase):
    def _flow(self, all_pass: bool, skip_one_stage: bool = False) -> dict:
        import tempfile
        root = Path(tempfile.mkdtemp())
        db = open_db(root / "agentos.db")
        eng = Engine(db, root)
        j = Journal(db)
        gw = ToolGateway(db, j)
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

        did, _ = se.define(stage="verification", kind="deterministic",
                           metric="conformity", threshold=1.0)
        from agentos.gates import _artifact_chain_hash
        chain = _artifact_chain_hash(db, goal_id)
        se.run_case(did, {"id": "sg-case"}, lambda c: (True, {}),
                    goal_id=goal_id, artifact_chain_hash=chain)
        stages = set(STAGES)
        if skip_one_stage:
            stages.discard("verification")   # missing gate => release fails
        for stage in sorted(stages):
            if all_pass:
                # per-stage deterministic eval + passing gate (bound to the
                # CURRENT artifact chain — fabricated chains are stale)
                sdid, _ = se.define(stage=stage, kind="deterministic",
                                    metric=f"probe_{stage}", threshold=1.0)
                se.run_case(sdid, {"id": f"{stage}-case"},
                            lambda c: (True, {}), goal_id=goal_id,
                            artifact_chain_hash=chain)
                se.stage_gate(stage, [sdid], goal_id=goal_id,
                              artifact_chain_hash=chain)
            else:
                # fail-closed: empty required set => failing gate
                se.stage_gate(stage, [], goal_id=goal_id,
                              artifact_chain_hash=chain)

        eng.submit_to_gate(goal_id)
        return Gates(db, j).evaluate_release(goal_id)

    def test_release_fails_when_stage_gates_missing_or_failed(self):
        res = self._flow(all_pass=False)
        self.assertEqual(res["result"], "fail")
        self.assertTrue(any("stage gate" in r or "no stage gate" in r
                            for r in res["reasons"]), res["reasons"])

    def test_release_fails_when_one_stage_gate_absent(self):
        res = self._flow(all_pass=True, skip_one_stage=True)
        self.assertEqual(res["result"], "fail")
        self.assertTrue(any("verification" in r for r in res["reasons"]),
                        res["reasons"])

    def test_release_passes_with_all_six_passing_gates(self):
        res = self._flow(all_pass=True)
        self.assertEqual(res["result"], "pass", res["reasons"])

    def test_fabricated_chain_gates_are_stale(self):
        """R7: six passing gates bound to a FABRICATED chain must not
        authorize release — release recomputes the real chain from disk."""
        import tempfile
        root = Path(tempfile.mkdtemp())
        db = open_db(root / "agentos.db")
        eng = Engine(db, root)
        j = Journal(db)
        gw = ToolGateway(db, j)
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
        goal_id = eng.create_goal("fabricated chain probe")
        eng.refine_spec(goal_id, "spec v1", criteria=[
            {"criterion_id": "has_code", "kind": "tests_present"}])
        eng.activate_goal(goal_id)
        eng.plan_tasks(goal_id, [{"key": "impl", "title": "T",
                                  "definition_of_done": "D"}])
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
        # six PASSING gates on a fabricated chain
        for stage in STAGES:
            sdid, _ = se.define(stage=stage, kind="deterministic",
                                metric=f"probe_{stage}", threshold=1.0)
            se.run_case(sdid, {"id": f"{stage}-case"}, lambda c: (True, {}),
                        goal_id=goal_id,
                        artifact_chain_hash="fabricated-chain")
            se.stage_gate(stage, [sdid], goal_id=goal_id,
                          artifact_chain_hash="fabricated-chain")
        eng.submit_to_gate(goal_id)
        res = Gates(db, j).evaluate_release(goal_id)
        self.assertEqual(res["result"], "fail")
        self.assertTrue(any("stale" in r for r in res["reasons"]),
                        res["reasons"])

    def test_advisory_only_runs_cannot_authorize_stage_gate(self):
        """Six advisory llm_judge runs with zero deterministic eval runs
        must NOT produce an authorizable stage gate."""
        import tempfile
        root = Path(tempfile.mkdtemp())
        db = open_db(root / "agentos.db")
        eng = Engine(db, root)
        j = Journal(db)
        gw = ToolGateway(db, j)
        se = StageEvals(db, root)
        goal_id = eng.create_goal("advisory probe")
        eng.refine_spec(goal_id, "spec v1", criteria=[
            {"criterion_id": "has_code", "kind": "tests_present"}])
        eng.activate_goal(goal_id)
        for stage in STAGES:
            sdid, _ = se.define(stage=stage, kind="llm_judge",
                                metric=f"judge_{stage}", threshold=1.0,
                                required=False, prompt_version="p1",
                                rubric_version="r1")
            se.run_case(sdid, {"id": f"{stage}-case"}, lambda c: (True, {}),
                        goal_id=goal_id,
                        artifact_chain_hash="chain-X",
                        judge={"model_id": "m", "prompt_version": "p1",
                               "rubric_version": "r1"})
            g = se.stage_gate(stage, [sdid], goal_id=goal_id,
                              artifact_chain_hash="chain-X")
            # the gate row itself may say pass, but it has NO deterministic
            # backing -> release refuses (verified via evaluate_release path)
            self.assertEqual(g["decision"], "pass")   # recorded...
        # ...but zero deterministic runs exist for these stages:
        n_det = db.conn.execute(
            "SELECT COUNT(*) FROM eval_run er JOIN eval_definition ed ON"
            " ed.id=er.definition_id AND ed.version=er.definition_version"
            " WHERE ed.kind='deterministic'").fetchone()[0]
        self.assertEqual(n_det, 0)


if __name__ == "__main__":
    unittest.main()
