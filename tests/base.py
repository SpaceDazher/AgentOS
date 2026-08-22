"""Shared test fixtures: fresh in-memory-ish DB per test."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentos.db import open_db  # noqa: E402
from agentos.engine import Engine  # noqa: E402
from agentos.gates import Evaluator, Gates  # noqa: E402
from agentos.gateway import RunContext, ToolContract, ToolGateway  # noqa: E402
from agentos.journal import Journal  # noqa: E402
from agentos.workers import FakeWorker  # noqa: E402


class AgentOSTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = open_db(self.root / "test.db")
        self.j = Journal(self.db)
        self.eng = Engine(self.db, self.root)
        self.gw = ToolGateway(self.db, self.j)
        self.ev = Evaluator(self.db, self.root)

    def tearDown(self):
        try:
            self.db.conn.close()
        finally:
            self.tmp.cleanup()

    # -- helpers -------------------------------------------------------------
    def make_goal_with_task(self, flaky: FakeWorker | None = None,
                            risk_tier: str = "normal"):
        goal_id = self.eng.create_goal("demo concept", risk_tier=risk_tier)
        self.eng.refine_spec(goal_id, "spec text", criteria=[
            {"criterion_id": "has_code", "kind": "tests_present"},
        ])
        if not flaky:
            self.eng.activate_goal(goal_id)
            self.eng.plan_tasks(goal_id, [
                {"key": "t1", "title": "do it",
                 "definition_of_done": "done when scripted success"}])
            self.eng.schedule_ready_tasks(goal_id)
        return goal_id

    def run_simple_task(self, goal_id: str, worker=None) -> str:
        task_id = self.db.conn.execute(
            "SELECT id FROM task WHERE goal_id=?", (goal_id,)).fetchone()[0]
        return self.eng.start_task(task_id, worker or FakeWorker())

    def ctx_for(self, run_id: str, goal_id: str):
        from agentos.gateway import RunContext
        row = self.db.conn.execute("SELECT * FROM run WHERE id=?",
                                   (run_id,)).fetchone()
        return RunContext(run_id=run_id, goal_id=goal_id,
                          task_id=row["task_id"], lease_owner=run_id,
                          capabilities=self.eng._capabilities_for(goal_id),
                          workspace_path=row["workspace_path"])

    def write_contract(self, handler=None) -> ToolContract:
        return ToolContract(
            name="fs.write.handler", version="1.0.0",
            input_schema={"type": "object",
                          "properties": {"path": {"type": "string"},
                                         "content": {"type": "string"}},
                          "required": ["path", "content"]},
            required_capability="fs.write_local", effect_class="write_local",
            idempotency="keyed", handler=handler)
