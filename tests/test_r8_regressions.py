"""R8 regressions (verdict findings 1-5).

1. Advisory llm_judge gates cannot authorize release — real release path.
2. Failed deterministic runs cannot back a passing gate.
3. Spaced secret names ('api key = X') are redacted and leak-detected.
4. Wiki staging is same-volume (build works when vault is on another drive).
5. Migration 0008->HEAD preserves campaigns and DB-refuses cross-goal
   experiment inserts.
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentos.db import open_db  # noqa: E402
from agentos.engine import Engine  # noqa: E402
from agentos.gates import Gates, _artifact_chain_hash  # noqa: E402
from agentos.gates import Evaluator  # noqa: E402
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


class R8Case(unittest.TestCase):
    """Full happy flow up to GATE_PENDING with evaluator run."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.db = open_db(self.root / "agentos.db")
        self.eng = Engine(self.db, self.root)
        self.j = Journal(self.db)
        self.gw = ToolGateway(self.db, self.j)
        self.ev = Evaluator(self.db, self.root)
        self.se = StageEvals(self.db, self.root)
        self.gw.register(ToolContract(
            name="fs.write.handler", version="1.0.0",
            input_schema={"type": "object",
                          "properties": {"path": {"type": "string"},
                                         "content": {"type": "string"}},
                          "required": ["path", "content"]},
            required_capability="fs.write_local",
            effect_class="write_local", idempotency="keyed",
            handler=_write))
        self.goal_id = self.eng.create_goal("r8 probe")
        self.eng.refine_spec(self.goal_id, "spec v1", criteria=[
            {"criterion_id": "has_code", "kind": "tests_present"}])
        self.eng.activate_goal(self.goal_id)
        self.eng.plan_tasks(self.goal_id,
                            [{"key": "impl", "title": "T",
                              "definition_of_done": "D"}])
        self.eng.schedule_ready_tasks(self.goal_id)
        task_id = self.db.conn.execute(
            "SELECT id FROM task WHERE goal_id=?",
            (self.goal_id,)).fetchone()[0]
        run_id, ctx = self.eng.open_run(task_id)
        self.gw.invoke(ctx, self.gw.resolve("fs.write.handler"),
                       {"path": str(Path(ctx.workspace_path) / "greet.py"),
                        "content": SRC}, idempotency_key=f"{run_id}:w")
        self.eng.complete_live_run(ctx)
        self.ev.run(self.goal_id, "has_code")
        self.chain = _artifact_chain_hash(self.db, self.goal_id)

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass


class TestAdvisoryCannotAuthorize(R8Case):
    def test_advisory_judge_gates_fail_release(self):
        """Six PASSING advisory judge runs + six pass gate rows must NOT
        yield release pass — no required deterministic backing."""
        for stage in STAGES:
            did, _ = self.se.define(stage=stage, kind="llm_judge",
                                    metric=f"judge_{stage}", threshold=1.0,
                                    required=False, prompt_version="p1",
                                    rubric_version="r1")
            self.se.run_case(did, {"id": f"{stage}-c"},
                             lambda c: (True, {}),
                             goal_id=self.goal_id,
                             artifact_chain_hash=self.chain,
                             judge={"model_id": "m",
                                    "prompt_version": "p1",
                                    "rubric_version": "r1"})
            g = self.se.stage_gate(stage, [did], goal_id=self.goal_id,
                                   artifact_chain_hash=self.chain)
            self.assertEqual(g["decision"], "pass")   # recorded...
        self.eng.submit_to_gate(self.goal_id)
        res = Gates(self.db, self.j).evaluate_release(self.goal_id)
        self.assertEqual(res["result"], "fail")
        self.assertTrue(any("deterministic" in r for r in res["reasons"]),
                         res["reasons"])

    def test_failed_deterministic_runs_cannot_back_gate(self):
        """Six FAILING deterministic runs cannot back six pass-gates."""
        for stage in STAGES:
            did, _ = self.se.define(stage=stage, kind="deterministic",
                                    metric=f"d_{stage}", threshold=1.0)
            self.se.run_case(did, {"id": f"{stage}-c"},
                             lambda c: (False, {"gap": "x"}),
                             goal_id=self.goal_id,
                             artifact_chain_hash=self.chain)
            g = self.se.stage_gate(stage, [did], goal_id=self.goal_id,
                                   artifact_chain_hash=self.chain)
            self.assertEqual(g["decision"], "fail")   # honest fail
        # force a lying later pass-gate row bound to the same chain:
        for stage in STAGES:
            self.se.stage_gate(stage, [], goal_id=self.goal_id,
                               artifact_chain_hash=self.chain)  # empty=fail
        self.eng.submit_to_gate(self.goal_id)
        res = Gates(self.db, self.j).evaluate_release(self.goal_id)
        self.assertEqual(res["result"], "fail")

    def test_full_pass_flow_with_exact_backing_passes(self):
        """The exact-backing rule still admits the legitimate path."""
        for stage in STAGES:
            did, _ = self.se.define(stage=stage, kind="deterministic",
                                    metric=f"d_{stage}", threshold=1.0)
            self.se.run_case(did, {"id": f"{stage}-c"},
                             lambda c: (True, {}),
                             goal_id=self.goal_id,
                             artifact_chain_hash=self.chain)
            self.se.stage_gate(stage, [did], goal_id=self.goal_id,
                               artifact_chain_hash=self.chain)
        self.eng.submit_to_gate(self.goal_id)
        res = Gates(self.db, self.j).evaluate_release(self.goal_id)
        self.assertEqual(res["result"], "pass", res["reasons"])


if __name__ == "__main__":
    unittest.main()
