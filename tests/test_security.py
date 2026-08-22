"""T09 approval replay; T10 args change after approval; T11 prompt injection
authority expansion; T12 malicious/changed tool schema; T13 memory scoping."""
from tests.base import AgentOSTestCase
from agentos.gateway import (
    ApprovalInvalid, ApprovalRequired, CapabilityDenied, GatewayError,
    MemoryScopeViolation,
)
from agentos.ids import new_id


class TestApprovals(AgentOSTestCase):
    def setUp(self):
        super().setUp()
        self.goal_id = self.make_goal_with_task()
        # F7: dangerous ops are mutating — invoke against a LIVE run
        self.run_id, self.ctx = self.open_live_run(self.goal_id)
        self.gw.register(
            type(self.gw) and __import__("agentos.gateway", fromlist=["ToolContract"])
            .ToolContract(
                name="deploy.prod", version="1.0.0",
                input_schema={"type": "object",
                              "properties": {"target": {"type": "string"}},
                              "required": ["target"]},
                required_capability="cmd.local", effect_class="dangerous",
                idempotency="none"))

    def test_t09_replay_denied_and_required(self):
        c = self.gw.resolve("deploy.prod")
        with self.assertRaises(ApprovalRequired):
            self.gw.invoke(self.ctx, c, {"target": "prod"})
        # target binds to the canonical action target ('prod'), not the workspace
        self.gw.grant_approval(goal_id=self.goal_id, actor="requester",
                               operation="invoke_tool", tool_name="deploy.prod",
                               tool_version="1.0.0", args={"target": "prod"},
                               target="prod")
        nonce = self.db.conn.execute(
            "SELECT nonce FROM approval WHERE goal_id=?", (self.goal_id,)
        ).fetchone()[0]
        r1 = self.gw.invoke(self.ctx, c, {"target": "prod"}, approval_nonce=nonce)
        self.assertTrue(r1["ok"])
        with self.assertRaises(ApprovalInvalid):
            self.gw.invoke(self.ctx, c, {"target": "prod"}, approval_nonce=nonce)

    def test_t10_changed_args_after_grant_denied(self):
        c = self.gw.resolve("deploy.prod")
        self.gw.grant_approval(goal_id=self.goal_id, actor="requester",
                               operation="invoke_tool", tool_name="deploy.prod",
                               tool_version="1.0.0", args={"target": "prod"},
                               target="prod")
        nonce = self.db.conn.execute(
            "SELECT nonce FROM approval WHERE goal_id=? AND status='GRANTED'",
            (self.goal_id,)).fetchone()[0]
        with self.assertRaises(ApprovalInvalid):
            self.gw.invoke(self.ctx, c, {"target": "prod-EVIL"}, approval_nonce=nonce)

    def test_sensitive_goal_requires_release_approval_at_gate(self):
        g2 = self.eng.create_goal("sensitive concept", risk_tier="sensitive")
        self.eng.refine_spec(g2, "spec", criteria=[
            {"criterion_id": "has_code", "kind": "tests_present"}])
        self.eng.activate_goal(g2)
        self.eng.plan_tasks(g2, [{"key": "t", "title": "work",
                                  "definition_of_done": "x"}])
        self.eng.schedule_ready_tasks(g2)
        task_id = self.db.conn.execute(
            "SELECT id FROM task WHERE goal_id=?", (g2,)).fetchone()[0]
        from agentos.workers import FakeWorker
        self.eng.start_task(task_id, FakeWorker())
        self.ev.run(g2, "has_code")
        self.eng.submit_to_gate(g2)
        from agentos.gates import Gates
        gate = Gates(self.db, self.j).evaluate_release(g2)
        self.assertEqual(gate["result"], "fail")
        self.assertTrue(any("release approval" in r for r in gate["reasons"]))


class TestInjectionAndSchema(AgentOSTestCase):
    def test_t11_injected_instruction_cannot_escalate(self):
        """Untrusted 'tool output' asks for admin capability — must stay inert."""
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract())
        # simulate model output trying to rewrite its own capability set:
        ctx.capabilities.add("admin.all")  # even if the worker mutates the object...
        # ...the registry still gates by contract requirement; admin is meaningless
        # and unknown tools are unavailable.
        with self.assertRaises(GatewayError):
            self.gw.resolve("admin.grant")
        # policy objects are not exposed via any invoke path: nothing to assert but non-crash
        res = self.gw.invoke(ctx, self.gw.resolve("fs.write.handler"),
                             {"path": str(self.root / "z.txt"),
                              "content": "ok"}, idempotency_key="i1")
        self.assertTrue(res["ok"])

    def test_t12_registry_tamper_detected(self):
        self.gw.register(self.write_contract())
        c = self.gw.resolve("fs.write.handler")
        # attacker tries the DB-level tamper — now refused by trigger outright
        with self.assertRaises(Exception):
            self.db.conn.execute(
                "UPDATE tool_contract SET input_schema_json='{\"type\":\"object\"}',"
                " effect_class='read' WHERE name='fs.write.handler'")
        # registry row intact: resolve still verifies and returns honest contract
        c2 = self.gw.resolve("fs.write.handler")
        self.assertEqual(c2.effect_class, "write_local")
        self.assertEqual(c.fingerprint(), c2.fingerprint())


class TestMemoryScoping(AgentOSTestCase):
    def test_t13_cross_scope_memory_read_denied(self):
        g1 = self.make_goal_with_task()
        r1 = self.run_simple_task(g1)
        ctx1 = self.ctx_for(r1, g1)
        mid = self.gw.memory_write(ctx1, "note", "secret of goal1", "file://a")
        g2 = self.make_goal_with_task()
        r2 = self.run_simple_task(g2)
        ctx2 = self.ctx_for(r2, g2)
        with self.assertRaises(MemoryScopeViolation):
            self.gw.memory_read(ctx2, mid)
        got = self.gw.memory_read(ctx1, mid)
        self.assertEqual(got["content"], "secret of goal1")

    def test_capability_denied_without_grant(self):
        goal_id = self.make_goal_with_task(risk_tier="sensitive")
        run_id = self.run_simple_task(goal_id)
        ctx = self.ctx_for(run_id, goal_id)
        self.gw.register(
            __import__("agentos.gateway", fromlist=["ToolContract"]).ToolContract(
                name="cmd.exec", version="1.0.0",
                input_schema={"type": "object",
                              "properties": {"cmdline": {"type": "string"}},
                              "required": ["cmdline"]},
                required_capability="cmd.local", effect_class="write_local",
                idempotency="keyed"))
        from agentos.gateway import CapabilityDenied
        with self.assertRaises(CapabilityDenied):
            self.gw.invoke(ctx, self.gw.resolve("cmd.exec"),
                           {"cmdline": "echo hi"}, idempotency_key="c1")
