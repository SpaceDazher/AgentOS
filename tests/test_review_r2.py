"""Regression tests for review round 2 (R2) findings.

R2-1: terminal goal transitions unreachable via actor strings, raw journal,
      or a self-made gate_authority(); ACCEPTED requires passing gate row +
      evaluation records verified in ONE transaction.
R2-2: invoke() re-resolves the contract from the registry; a forged
      ToolContract (effect_class="read" + write handler) cannot bypass
      mutating-policy.
"""
import unittest
from pathlib import Path

from tests.base import AgentOSTestCase
from agentos.gates import Gates
from agentos.gateway import GatewayError, ToolContract, ToolGateway
from agentos.ids import new_id
from agentos.journal import Journal, TransitionError
from agentos.machines import Machines, gate_authority

SRC = ("def greet(name):\n"
       "    return f'hello, {name}'\n\n\n"
       "def test_greet():\n"
       "    assert greet('world') == 'hello, world'\n")


def _write_handler(path, content):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"written": str(p)}


def _drive_to_gate_pending(t, goal_id: str):
    run_id, ctx = t.open_live_run(goal_id)
    t.gw.register(t.write_contract(handler=_write_handler))
    t.gw.invoke(ctx, t.gw.resolve("fs.write.handler"),
                {"path": str(Path(ctx.workspace_path) / "greet.py"),
                 "content": SRC}, idempotency_key="r21")
    t.eng.complete_live_run(ctx)
    t.ev.run(goal_id, "has_code")
    t.eng.submit_to_gate(goal_id)
    return ctx


class TestR2_1_TerminalAuthority(AgentOSTestCase):
    def test_self_made_authority_cannot_accept(self):
        """gate_authority() is just bytes — it must NOT authorize acceptance."""
        goal_id = self.make_goal_with_task()
        _drive_to_gate_pending(self, goal_id)
        # attacker builds their own Machines + fresh authority object:
        rogue = Machines(self.db, self.j)
        auth = gate_authority()
        with self.assertRaises(TransitionError):
            rogue.accept_by_gate_record(goal_id, "ACCEPTED", auth=auth,
                                        gate_id="whatever", reasons=[])
        status = self.db.conn.execute(
            "SELECT status FROM goal WHERE id=?", (goal_id,)).fetchone()[0]
        self.assertEqual(status, "GATE_PENDING")

    def test_raw_journal_cannot_execute_terminal_transition(self):
        goal_id = self.make_goal_with_task()
        _drive_to_gate_pending(self, goal_id)
        j = Journal(self.db)
        with self.assertRaises(TransitionError):
            j.transition(table="goal", obj_id=goal_id,
                         expect_from="GATE_PENDING", to="ACCEPTED",
                         actor="gate", goal_id=goal_id)

    def test_passing_gate_row_without_evaluations_is_refused(self):
        """Corrupt state: a pass gate row with zero evaluations must not accept."""
        goal_id = self.make_goal_with_task()
        # drive the task to DONE but record NO evaluations at all
        run_id, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract(handler=_write_handler))
        self.gw.invoke(ctx, self.gw.resolve("fs.write.handler"),
                       {"path": str(Path(ctx.workspace_path) / "greet.py"),
                        "content": SRC}, idempotency_key="r21b")
        self.eng.complete_live_run(ctx)
        # forge a passing gate row directly (simulating corrupted writer)
        gid = new_id("gate")
        self.db.conn.execute(
            "INSERT INTO gate(id, goal_id, predicate_name, predicate_version,"
            " input_fingerprint, result, rationale)"
            " VALUES (?, ?, 'release_predicate_v2', 'v2', 'forged', 'pass', 'x')",
            (gid, goal_id))
        # move goal to GATE_PENDING via the legitimate scheduling path
        # (submit requires evaluations, so set the state directly to emulate
        # the corrupted-state scenario under test)
        self.db.conn.execute("UPDATE goal SET status='GATE_PENDING' WHERE id=?",
                             (goal_id,))
        gates = Gates(self.db, self.j)   # holds the REAL bound authority
        with self.assertRaises(TransitionError):
            gates.m.accept_by_gate_record(goal_id, "ACCEPTED",
                                          auth=gates.m._gate_auth,
                                          gate_id=gid, reasons=[])
        status = self.db.conn.execute(
            "SELECT status FROM goal WHERE id=?", (goal_id,)).fetchone()[0]
        self.assertEqual(status, "GATE_PENDING")

    def test_legitimate_path_still_works(self):
        """The real flow (evaluations + gate row + bound authority) accepts."""
        goal_id = self.make_goal_with_task()
        _drive_to_gate_pending(self, goal_id)
        gate = Gates(self.db, self.j).evaluate_release(goal_id)
        self.assertEqual(gate["result"], "pass")
        status = self.db.conn.execute(
            "SELECT status FROM goal WHERE id=?", (goal_id,)).fetchone()[0]
        self.assertEqual(status, "ACCEPTED")


class TestR2_2_RegistryReResolve(AgentOSTestCase):
    def test_forged_read_contract_cannot_write(self):
        """A caller hands in a write handler disguised as effect_class='read':
        the gateway executes only the registry's authoritative contract, so
        the mutating policy (lease check) applies and the forged effect class
        is ignored."""
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        # register the honest contract (mutating, keyed, with handler)
        self.gw.register(self.write_contract(handler=_write_handler))
        # forge: same name/version but declared read-only
        forged = ToolContract(
            name="fs.write.handler", version="1.0.0",
            input_schema={"type": "object",
                          "properties": {"path": {"type": "string"},
                                         "content": {"type": "string"}},
                          "required": ["path", "content"]},
            required_capability="",          # try to dodge capability checks
            effect_class="read",             # try to dodge lease/fence policy
            idempotency="none",
            handler=_write_handler)
        target = Path(ctx.workspace_path) / "forged.txt"
        r = self.gw.invoke(ctx, forged, {"path": str(target), "content": "x"},
                           idempotency_key="f1")
        # The gateway re-resolved fs.write.handler@1.0.0 from the registry:
        # effect_class=write_local ⇒ lease/fence policy applied (ctx is live so
        # this SUCCEEDS but through the REAL contract path), capability was
        # checked against the registry value, not the forged one.
        self.assertIn(r["status"], ("SUCCEEDED", "REPLAYED"))
        # decisive assertion: activity row carries the REGISTRY's effect class
        row = self.db.conn.execute(
            "SELECT tool_identity, effect_class FROM activity WHERE id=?",
            (r["activity_id"],)).fetchone()
        self.assertEqual(row["tool_identity"], "fs.write.handler@1.0.0")
        self.assertEqual(row["effect_class"], "write_local")

    def test_forged_contract_on_stale_run_is_denied_despite_read_disguise(self):
        """Same forgery against an expired-lease run: registry policy denies."""
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract(handler=_write_handler))
        self.db.conn.execute(
            "UPDATE run SET lease_expires_at='2000-01-01T00:00:00Z' WHERE id=?",
            (run_id,))
        forged = ToolContract(
            name="fs.write.handler", version="1.0.0",
            input_schema={"type": "object",
                          "properties": {"path": {"type": "string"},
                                         "content": {"type": "string"}},
                          "required": ["path", "content"]},
            required_capability="", effect_class="read", idempotency="none",
            handler=_write_handler)
        from agentos.gateway import StaleOwnerError
        with self.assertRaises(StaleOwnerError):
            self.gw.invoke(ctx, forged,
                           {"path": str(Path(ctx.workspace_path) / "no.txt"),
                            "content": "x"}, idempotency_key="f2")

    def test_unregistered_tool_never_resolves(self):
        goal_id = self.make_goal_with_task()
        _, ctx = self.open_live_run(goal_id)
        ghost = ToolContract(name="ghost.tool", version="9.9.9",
                             input_schema={"type": "object"},
                             effect_class="dangerous",
                             handler=lambda **kw: {"pwned": True})
        with self.assertRaises(GatewayError):
            self.gw.invoke(ctx, ghost, {}, idempotency_key="g1")


class TestR2_3_HermesIntents(unittest.TestCase):
    def test_parse_effects_confined(self):
        from agentos.hermes_worker import HermesAgentWorker
        ws = str(Path(tempfile.mkdtemp()).resolve())
        lines = [
            'AGENTOS_RESULT {"ok": true}',
            'AGENTOS_EFFECTS {"path": "../up.py", "content": "a"}',
            'AGENTOS_EFFECTS {"path": "/etc/passwd", "content": "b"}',
            'AGENTOS_EFFECTS {"path": "D:\\\\evil.py", "content": "c"}',
            'AGENTOS_EFFECTS {"path": "sub/ok.py", "content": "d"}',
        ]
        declared = HermesAgentWorker.parse_effects(lines, ws)
        self.assertEqual(set(declared), {"sub/ok.py"})


import tempfile  # noqa: E402


if __name__ == "__main__":
    unittest.main()
