"""Determinism: the same scripted scenario run twice in fresh roots yields
identical task/run/evaluation/gate sequences; src/agentos imports no network
or LLM client libraries."""
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentos.db import open_db  # noqa: E402
from agentos.engine import Engine  # noqa: E402
from agentos.gates import Evaluator, Gates  # noqa: E402
from agentos.journal import Journal  # noqa: E402
from agentos.workers import FakeWorker  # noqa: E402


def _run_scripted_scenario(root_dir: Path) -> dict:
    """Happy-path script executed against a fresh root + fresh open_db.

    Returns only status/result sequences — no ids, timestamps or digests,
    which are intentionally unique per run.
    """
    db = open_db(root_dir / "det.db")
    try:
        j = Journal(db)
        eng = Engine(db, root_dir)
        ev = Evaluator(db, root_dir)
        from agentos.gateway import ToolContract, ToolGateway
        gw = ToolGateway(db, j)

        goal_id = eng.create_goal("demo concept")
        eng.refine_spec(goal_id, "spec text", criteria=[
            {"criterion_id": "has_code", "kind": "tests_present"},
        ])
        eng.activate_goal(goal_id)
        eng.plan_tasks(goal_id, [
            {"key": "t1", "title": "do it",
             "definition_of_done": "done when scripted success"}])
        eng.schedule_ready_tasks(goal_id)

        task_id = db.conn.execute(
            "SELECT id FROM task WHERE goal_id=?", (goal_id,)).fetchone()[0]
        # F-P0-3: evaluator validates real content — write a real module with a
        # test through the gateway inside a live run, then complete.
        run_id, ctx = eng.open_run(task_id)
        src = ("def greet(name):\n"
               "    return f'hello, {name}'\n\n\n"
               "def test_greet():\n"
               "    assert greet('world') == 'hello, world'\n")

        def _write(path, content):
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"written": str(p)}

        gw.register(ToolContract(
            name="fs.write.handler", version="1.0.0",
            input_schema={"type": "object",
                          "properties": {"path": {"type": "string"},
                                         "content": {"type": "string"}},
                          "required": ["path", "content"]},
            required_capability="fs.write_local", effect_class="write_local",
            idempotency="keyed", handler=_write))
        r = gw.invoke(ctx, gw.resolve("fs.write.handler"),
                      {"path": str(Path(ctx.workspace_path) / "greet.py"),
                       "content": src}, idempotency_key="det1")
        assert r["status"] == "SUCCEEDED", r
        eng.complete_live_run(ctx, outputs={"files": {"greet.py": src}})

        ev_res = ev.run(goal_id, "has_code")
        eng.submit_to_gate(goal_id)
        gate = Gates(db, j).evaluate_release(goal_id)

        return {
            "task_statuses": [r["status"] for r in db.conn.execute(
                "SELECT status FROM task WHERE goal_id=?"
                " ORDER BY created_at, id", (goal_id,))],
            "run_statuses": [r["status"] for r in db.conn.execute(
                "SELECT status FROM run WHERE goal_id=?"
                " ORDER BY created_at, id", (goal_id,))],
            "evaluation_results": [r["result"] for r in db.conn.execute(
                "SELECT result FROM evaluation WHERE goal_id=?"
                " ORDER BY created_at, id", (goal_id,))],
            "gate_result": gate["result"],
            "gate_reasons": gate["reasons"],
        }
    finally:
        db.conn.close()


class TestDeterminism(unittest.TestCase):
    def test_same_scenario_twice_identical_sequences(self):
        with tempfile.TemporaryDirectory() as a, \
                tempfile.TemporaryDirectory() as b:
            first = _run_scripted_scenario(Path(a))
            second = _run_scripted_scenario(Path(b))

        self.assertEqual(first["task_statuses"], second["task_statuses"])
        self.assertEqual(first["run_statuses"], second["run_statuses"])
        self.assertEqual(first["evaluation_results"],
                         second["evaluation_results"])
        self.assertEqual(first["gate_result"], second["gate_result"])
        self.assertEqual(first["gate_reasons"], second["gate_reasons"])

        # sanity: the scripted scenario itself must be a clean release
        self.assertEqual(first["task_statuses"], ["DONE"])
        self.assertEqual(first["evaluation_results"], ["pass"])
        self.assertEqual(first["gate_result"], "pass")

    def test_no_network_or_llm_imports_in_agentos_src(self):
        """grep-level check: no urllib.request / requests imports anywhere
        under src/agentos (comment lines excluded)."""
        src_dir = Path(__file__).resolve().parent.parent / "src" / "agentos"
        banned = {"urllib.request", "requests"}
        offenders = []
        for py in sorted(src_dir.rglob("*.py")):
            for lineno, line in enumerate(
                    py.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]  # strip trailing comment
                m = re.match(r"\s*(?:from|import)\s+([\w.]+)", code)
                if m and m.group(1) in banned:
                    offenders.append(f"{py.name}:{lineno}: {line.strip()}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
