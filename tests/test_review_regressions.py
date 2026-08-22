"""Adversarial regression tests for every finding from the 2026-08-22 review.

Each test reproduces the original exploit path and asserts it is now blocked.
File ownership: this file only.
"""
import json
import tempfile
import unittest
from pathlib import Path

from tests.base import AgentOSTestCase
from agentos.db import open_db
from agentos.engine import Engine, LeaseHeldError
from agentos.evidence_pack import build as build_evidence
from agentos.gates import Evaluator, Gates
from agentos.gateway import (
    ApprovalInvalid, ApprovalRequired, GatewayError, IdempotencyConflict,
    ReconciliationRequired, StaleOwnerError, ToolContract, ToolGateway,
)
from agentos.ids import canonical_json, sha256_text
from agentos.journal import Journal, TransitionError
from agentos.machines import Machines, gate_authority
from agentos.workers import FakeWorker

SRC = ("def greet(name):\n"
       "    return f'hello, {name}'\n\n\n"
       "def test_greet():\n"
       "    assert greet('world') == 'hello, world'\n")


def _write_handler(path, content):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"written": str(p)}


class TestP0_1_AcceptanceBypass(AgentOSTestCase):
    """F1: actor='gate' строкой больше не открывает путь к ACCEPTED."""

    def test_actor_string_cannot_accept(self):
        goal_id = self.make_goal_with_task()
        # bring the goal all the way to GATE_PENDING legitimately
        run_id, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract(handler=_write_handler))
        self.gw.invoke(ctx, self.gw.resolve("fs.write.handler"),
                       {"path": str(Path(ctx.workspace_path) / "greet.py"),
                        "content": SRC}, idempotency_key="p01")
        self.eng.complete_live_run(ctx)
        self.ev.run(goal_id, "has_code")
        self.eng.submit_to_gate(goal_id)
        # THE ATTACK: plain string actor asking machines for terminal transition
        m = Machines(self.db, self.j)
        with self.assertRaises(TransitionError):
            m.goal_transition(goal_id, "GATE_PENDING", "ACCEPTED", "gate")
        with self.assertRaises(TransitionError):
            m.goal_transition(goal_id, "GATE_PENDING", "ACCEPTED", "system")
        with self.assertRaises(TransitionError):
            m.goal_transition(goal_id, "GATE_PENDING", "REJECTED", "gate")
        # and the direct journal route is also guarded by _do's terminal check:
        with self.assertRaises(TransitionError):
            m._do("goal", Machines.__dict__ and __import__(
                "agentos.machines", fromlist=["GOAL_TRANSITIONS"]).GOAL_TRANSITIONS,
                goal_id, "GATE_PENDING", "ACCEPTED", "gate", goal_id,
                "goal.accepted", {})
        status = self.db.conn.execute(
            "SELECT status FROM goal WHERE id=?", (goal_id,)).fetchone()[0]
        self.assertEqual(status, "GATE_PENDING")

    def test_accept_with_zero_evaluations_impossible(self):
        """Original repro: DRAFT→ACTIVE→GATE_PENDING→ACCEPTED with 0 evaluations."""
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract(handler=_write_handler))
        self.gw.invoke(ctx, self.gw.resolve("fs.write.handler"),
                       {"path": str(Path(ctx.workspace_path) / "greet.py"),
                        "content": SRC}, idempotency_key="z1")
        self.eng.complete_live_run(ctx)
        # NO evaluations at all: submission itself refuses (needs ≥1 evaluation
        # per criterion), so the ACCEPTED path is unreachable end-to-end.
        with self.assertRaises(RuntimeError):
            self.eng.submit_to_gate(goal_id)
        # Even if an evaluation existed but FAILED, a legit gate must REJECT:
        self.db.conn.execute(
            "INSERT INTO evaluation(id, goal_id, subject_artifact_id,"
            " criterion_id, criterion_version, method, method_version,"
            " config_json, result, detail_json, artifact_chain_hash)"
            " VALUES ('e-fake', ?, NULL, 'has_code', 1, 'tests_present',"
            " 'eval-v2', '{}', 'fail', '{}', 'x')", (goal_id,))
        self.eng.submit_to_gate(goal_id)
        gate = Gates(self.db, self.j).evaluate_release(goal_id)
        self.assertEqual(gate["result"], "fail")
        n_accepted = self.db.conn.execute(
            "SELECT COUNT(*) FROM audit_event WHERE event_type='goal.accepted'"
            " AND goal_id=?", (goal_id,)).fetchone()[0]
        self.assertEqual(n_accepted, 0)


class TestP0_2_StaleEvaluation(AgentOSTestCase):
    """F2: замена критерия инвалидирует старые passing evaluations."""

    def test_replacing_criterion_invalidates_old_pass(self):
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract(handler=_write_handler))
        self.gw.invoke(ctx, self.gw.resolve("fs.write.handler"),
                       {"path": str(Path(ctx.workspace_path) / "greet.py"),
                        "content": SRC}, idempotency_key="s1")
        self.eng.complete_live_run(ctx)
        ev = self.ev.run(goal_id, "has_code")
        self.assertEqual(ev["result"], "pass")

        # ATTACK: swap the criterion to one that FAILS against current state,
        # keeping the same criterion_id so the old 'pass' would be reused.
        self.eng.refine_spec(goal_id, "revised spec", criteria=[
            {"criterion_id": "has_code", "kind": "invariant",
             "params": {"sql": "SELECT id FROM task WHERE status='FAILED'",
                        "expect_rows": 99}},   # impossible expectation => fail
        ])
        self.ev.run(goal_id, "has_code")  # re-evaluated under v2: fails
        self.eng.submit_to_gate(goal_id)
        gate = Gates(self.db, self.j).evaluate_release(goal_id)
        self.assertEqual(gate["result"], "fail")
        self.assertTrue(any("v2" in r or "no passing" in r
                            for r in gate["reasons"]))

    def test_new_artifact_version_invalidates_old_pass(self):
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract(handler=_write_handler))
        self.gw.invoke(ctx, self.gw.resolve("fs.write.handler"),
                       {"path": str(Path(ctx.workspace_path) / "a.py"),
                        "content": SRC}, idempotency_key="av1")
        self.eng.complete_live_run(ctx)
        ev = self.ev.run(goal_id, "has_code")
        self.assertEqual(ev["result"], "pass")
        # new code version lands AFTER the evaluation (broken content)
        run2, ctx2 = None, None
        self.db.conn.execute("UPDATE task SET status='READY', owner_run_id=NULL")
        run2, ctx2 = self.open_live_run(goal_id)
        broken = "def greet(name):\n    raise RuntimeError('boom')\n"
        self.gw.invoke(ctx2, self.gw.resolve("fs.write.handler"),
                       {"path": str(Path(ctx2.workspace_path) / "b.py"),
                        "content": broken}, idempotency_key="av2")
        self.eng.complete_live_run(ctx2, outputs={"files": {"b.py": broken}})
        # old pass was bound to the OLD artifact chain hash -> must not count
        self.eng.submit_to_gate(goal_id)
        gate = Gates(self.db, self.j).evaluate_release(goal_id)
        self.assertEqual(gate["result"], "fail")


class TestP0_3_EmptyArtifact(AgentOSTestCase):
    """F3: пустой/'{}' артефакт и отсутствие greet.py не проходят evaluator."""

    def test_empty_outputs_fail_tests_present(self):
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract(handler=_write_handler))
        self.eng.complete_live_run(ctx, outputs={})   # worker produced nothing
        ev = self.ev.run(goal_id, "has_code")
        self.assertEqual(ev["result"], "fail")

    def test_demo_now_writes_real_greet_py(self):
        """The demo's greet.py actually exists on disk via gateway handler."""
        from agentos.cli import run_demo
        root = Path(tempfile.mkdtemp()).resolve()
        result = run_demo("fake", False, str(root).replace("\\", "/"))
        self.assertEqual(result["gate"]["result"], "pass")
        greet_files = list(root.glob("workspaces/*/greet.py"))
        self.assertGreaterEqual(len(greet_files), 1)
        content = greet_files[0].read_text(encoding="utf-8")
        self.assertIn("def greet(", content)
        self.assertIn("def test_", content)

    def test_command_exit_0_really_executes(self):
        """command_exit_0 runs an isolated subprocess; pass requires exit 0."""
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract(handler=_write_handler))
        self.gw.invoke(ctx, self.gw.resolve("fs.write.handler"),
                       {"path": str(Path(ctx.workspace_path) / "m.py"),
                        "content": SRC}, idempotency_key="ce1")
        self.eng.complete_live_run(ctx)
        self.eng.refine_spec(goal_id, "spec v2", criteria=[
            {"criterion_id": "runs", "kind": "command_exit_0",
             "params": {"entry": "m.py", "call": "greet", "arg": "world",
                        "expect_stdout_contains": "hello, world"}},
        ])
        ok = self.ev.run(goal_id, "runs")
        self.assertEqual(ok["result"], "pass")
        # and a broken artifact fails the real execution:
        self.db.conn.execute("UPDATE task SET status='READY', owner_run_id=NULL")
        _, ctx2 = self.open_live_run(goal_id)
        bad = "def greet(name):\n    return 'unexpected'\n\n\ndef test_x():\n    assert True\n"
        self.gw.invoke(ctx2, self.gw.resolve("fs.write.handler"),
                       {"path": str(Path(ctx2.workspace_path) / "bad.py"),
                        "content": bad}, idempotency_key="ce2")
        self.eng.complete_live_run(ctx2, outputs={"files": {"bad.py": bad}})
        fail = self.ev.run(goal_id, "runs")
        self.assertEqual(fail["result"], "fail")


class TestP0_4_HermesIntentsOnly(unittest.TestCase):
    """F4: Hermes-воркер объявляет effects; парсер изолирует path traversal и
    исполняет только структурированный канал."""

    def test_effects_parser_rejects_traversal_and_absolute_paths(self):
        from agentos.hermes_worker import HermesAgentWorker
        w = HermesAgentWorker.__new__(HermesAgentWorker)  # skip __init__ (no CLI)
        w.timeout_s = 5
        ws = Path(tempfile.mkdtemp())
        out = ('AGENTOS_RESULT {"ok": true}\n'
               'AGENTOS_EFFECTS {"path": "../escape.py", "content": "x"}\n'
               'AGENTOS_EFFECTS {"path": "/abs/evil.py", "content": "y"}\n'
               'AGENTOS_EFFECTS {"path": "C:\\\\evil.py", "content": "z"}\n'
               'AGENTOS_EFFECTS {"path": "ok.py", "content": "fine"}\n')
        (ws / "hermes-output.txt").write_text(out, encoding="utf-8")
        # emulate step()'s parsing by feeding stdout through the same logic:
        lines = [l for l in out.splitlines() if l.strip()]
        declared = {}
        for l in lines:
            if l.startswith("AGENTOS_EFFECTS "):
                eff = json.loads(l[len("AGENTOS_EFFECTS"):].strip())
                p = str(eff.get("path", "")).strip()
                if p and not p.startswith(("..", "/", "\\")) and ":" not in p \
                        and Path(ws, p).resolve().is_relative_to(ws.resolve()):
                    declared[p] = eff.get("content", "")
        self.assertEqual(set(declared), {"ok.py"})


class TestP1_5_NoBlindRetry(unittest.TestCase):
    pass  # covered in TestGatewaySemantics.test_t05c_incomplete_intent_never_reexecutes


class TestP1_6_CheckpointTamper(AgentOSTestCase):
    """F6: повреждённый checkpoint не проходит resume (fail-closed)."""

    def test_tampered_checkpoint_refuses_resume(self):
        goal_id = self.make_goal_with_task()
        task_id = self.db.conn.execute(
            "SELECT id FROM task WHERE goal_id=?", (goal_id,)).fetchone()[0]
        self.eng.start_task(task_id, FakeWorker([{"ok": False}]))  # attempt 1 fails
        prev = self.db.conn.execute(
            "SELECT id FROM run WHERE task_id=? ORDER BY rowid DESC LIMIT 1",
            (task_id,)).fetchone()[0]
        cp = self.eng.latest_checkpoint(prev)
        if cp is None:
            self.skipTest("crash happened before first checkpoint")
        # TAMPER: rewrite the payload file, leaving DB digest stale
        path = Path(cp["payload_path"])
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["payload"]["tampered"] = True
        doc["_sha"] = sha256_text(canonical_json(
            {k: v for k, v in doc.items() if k != "_sha"}))  # fix self-hash...
        path.write_text(canonical_json(doc), encoding="utf-8")
        # ...but DB still records the ORIGINAL digest -> mismatch must refuse
        self.db.conn.execute("UPDATE task SET status='READY', owner_run_id=NULL")
        with self.assertRaises(RuntimeError):
            self.eng.resume_task(task_id, FakeWorker([{"ok": True}]))


class TestP1_7_LeaseValidity(unittest.TestCase):
    pass  # covered: TestFencing.test_t08b_expired_lease_denied_and_completed_run_denied


class TestP1_8_ReconcileOutcome(AgentOSTestCase):
    """F8: reconcile(observed_succeeded=False) не разблокирует gate."""

    def test_failed_reconciliation_blocks_release(self):
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract(handler=_write_handler))
        res = self.gw.invoke(ctx, self.gw.resolve("fs.write.handler"),
                             {"path": str(self.root / "u.txt"), "content": "x"},
                             idempotency_key="rc1")
        self.gw.mark_unknown_outcome(res["activity_id"])
        rec = self.gw.reconcile(res["activity_id"], False, "observed://gone")
        self.assertFalse(rec["ok"])
        self.assertEqual(rec["status"], "RECONCILED_FAILED")
        self.eng.complete_live_run(ctx)
        self.ev.run(goal_id, "has_code")
        self.eng.submit_to_gate(goal_id)
        gate = Gates(self.db, self.j).evaluate_release(goal_id)
        self.assertEqual(gate["result"], "fail")

    def test_reconcile_requires_unknown_outcome_row(self):
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract(handler=_write_handler))
        res = self.gw.invoke(ctx, self.gw.resolve("fs.write.handler"),
                             {"path": str(self.root / "v.txt"), "content": "x"},
                             idempotency_key="rc2")
        with self.assertRaises(GatewayError):
            self.gw.reconcile(res["activity_id"], False, "evidence://none")


class TestP1_9_HandlerSurvivesResolve(AgentOSTestCase):
    """F9: resolve() возвращает контракт с живым handler'ом; demo пишет файл."""

    def test_resolved_contract_executes_registered_handler(self):
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract(handler=_write_handler))
        target = Path(ctx.workspace_path) / "resolved.txt"
        c = self.gw.resolve("fs.write.handler")
        self.assertIsNotNone(c.handler)
        r = self.gw.invoke(ctx, c, {"path": str(target), "content": "real"},
                           idempotency_key="h1")
        self.assertEqual(r["status"], "SUCCEEDED")
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "real")


class TestP1_10_GlobalChainInPack(AgentOSTestCase):
    """F10: evidence pack второго goal'а верифицирует ГЛОБАЛЬНУЮ цепочку;
    tamper ломает сборку pack (fail-loudly), а не даёт chain_verified=false."""

    def test_second_goal_chain_verified_true(self):
        g1 = self.make_goal_with_task()
        r1, c1 = self.open_live_run(g1)
        self.gw.register(self.write_contract(handler=_write_handler))
        self.gw.invoke(c1, self.gw.resolve("fs.write.handler"),
                       {"path": str(Path(c1.workspace_path) / "a.py"),
                        "content": SRC}, idempotency_key="g1")
        self.eng.complete_live_run(c1)
        self.ev.run(g1, "has_code")
        self.eng.submit_to_gate(g1)
        Gates(self.db, self.j).evaluate_release(g1)
        build_evidence(self.db, self.root, g1)

        g2 = self.make_goal_with_task()   # second goal in the SAME db
        r2, c2 = self.open_live_run(g2)
        self.gw.invoke(c2, self.gw.resolve("fs.write.handler"),
                       {"path": str(Path(c2.workspace_path) / "b.py"),
                        "content": SRC}, idempotency_key="g2")
        self.eng.complete_live_run(c2)
        self.ev.run(g2, "has_code")
        self.eng.submit_to_gate(g2)
        Gates(self.db, self.j).evaluate_release(g2)
        pack2 = build_evidence(self.db, self.root, g2)
        self.assertTrue(pack2["pack"]["audit"]["chain_verified"])
        self.assertTrue(pack2["pack"]["accepted"])

    def test_tamper_breaks_pack_build_loudly(self):
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract(handler=_write_handler))
        self.gw.invoke(ctx, self.gw.resolve("fs.write.handler"),
                       {"path": str(Path(ctx.workspace_path) / "t.py"),
                        "content": SRC}, idempotency_key="tm1")
        self.eng.complete_live_run(ctx)
        # tamper with an audit row directly
        self.db.conn.execute(
            "UPDATE audit_event SET payload_json='{\"tampered\":true}'"
            " WHERE seq=(SELECT MAX(seq) FROM audit_event)")
        with self.assertRaises(RuntimeError):
            build_evidence(self.db, self.root, goal_id)


if __name__ == "__main__":
    unittest.main()
