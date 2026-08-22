"""P1-tail regressions: sink-side fence rejection, registry append-only at the
DB layer, external head anchor."""
import json
import unittest
from pathlib import Path

from tests.base import AgentOSTestCase
from agentos.db import open_db
from agentos.gateway import GatewayError, ToolContract
from agentos.ids import canonical_json, sha256_text
from agentos.journal import Journal


class TestSinkFence(AgentOSTestCase):
    def _fence_contract(self, db):
        from agentos.fence_sink import make_fs_write_handler
        return ToolContract(
            name="fs.write.handler", version="1.0.0",
            input_schema={"type": "object",
                          "properties": {"path": {"type": "string"},
                                         "content": {"type": "string"}},
                          "required": ["path", "content"]},
            required_capability="fs.write_local", effect_class="write_local",
            idempotency="keyed", handler=make_fs_write_handler(db))

    def test_stale_fence_rejected_by_sink(self):
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        contract = self._fence_contract(self.db)
        self.gw.register(contract)
        c = self.gw.resolve("fs.write.handler")
        # two sequential writes advance the sink counter
        r1 = self.gw.invoke(ctx, c, {"path": str(self.root / "f1.txt"),
                                     "content": "1"}, idempotency_key="sf1")
        self.assertEqual(r1["status"], "SUCCEEDED")
        r2 = self.gw.invoke(ctx, c, {"path": str(self.root / "f2.txt"),
                                     "content": "2"}, idempotency_key="sf2")
        self.assertEqual(r2["status"], "SUCCEEDED")
        # a STALE token (fence 1) replayed directly against the sink is refused
        from agentos.fence_sink import make_fs_write_handler, StaleFenceError
        h = make_fs_write_handler(self.db)
        with self.assertRaises(StaleFenceError):
            h(path=str(self.root / "f3.txt"), content="3", _fence=1,
              _sink=ctx.workspace_path)
        # a token equal to the last accepted is also stale (strictly monotonic)
        cur_fence = json.loads(self.db.conn.execute(
            "SELECT detail_json FROM activity WHERE id=?",
            (r2["activity_id"],)).fetchone()[0])["fence"]
        with self.assertRaises(StaleFenceError):
            h(path=str(self.root / "f4.txt"), content="4",
              _fence=cur_fence, _sink=ctx.workspace_path)
        # only a strictly NEWER token is accepted
        h(path=str(self.root / "f5.txt"), content="5",
          _fence=cur_fence + 1, _sink=ctx.workspace_path)

    def test_gateway_injects_fence_into_declaring_handlers(self):
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        seen = {}

        def handler(path, content, _fence=None, _sink=None):
            seen["fence"] = _fence
            seen["sink"] = _sink
            return {"ok": True}

        self.gw.register(ToolContract(
            name="fs.write.handler", version="1.0.0",
            input_schema={"type": "object",
                          "properties": {"path": {"type": "string"},
                                         "content": {"type": "string"}},
                          "required": ["path", "content"]},
            required_capability="fs.write_local", effect_class="write_local",
            idempotency="keyed", handler=handler))
        self.gw.invoke(ctx, self.gw.resolve("fs.write.handler"),
                       {"path": str(self.root / "inj.txt"), "content": "x"},
                       idempotency_key="inj")
        self.assertIsNotNone(seen["fence"])
        self.assertGreater(seen["fence"], 0)
        self.assertEqual(seen["sink"], ctx.workspace_path)


class TestRegistryImmutableAtDB(AgentOSTestCase):
    def test_update_and_delete_refused_by_triggers(self):
        self.gw.register(self.write_contract())
        with self.assertRaises(Exception):
            self.db.conn.execute(
                "UPDATE tool_contract SET effect_class='read'"
                " WHERE name='fs.write.handler'")
        with self.assertRaises(Exception):
            self.db.conn.execute(
                "DELETE FROM tool_contract WHERE name='fs.write.handler'")
        # row untouched: fingerprint still verifies through resolve()
        c = self.gw.resolve("fs.write.handler")
        self.assertEqual(c.effect_class, "write_local")


class TestExternalAnchor(AgentOSTestCase):
    def test_anchor_file_mirrors_head(self):
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        self.gw.register(self.write_contract())
        self.gw.invoke(ctx, self.gw.resolve("fs.write.handler"),
                       {"path": str(self.root / "a.txt"), "content": "x"},
                       idempotency_key="an1")
        anchor_file = self.db.path.parent / "audit_anchor.head"
        self.assertTrue(anchor_file.exists())
        seq, digest = anchor_file.read_text(encoding="utf-8").split()
        last = self.db.conn.execute(
            "SELECT seq, prev_event_sha256 FROM audit_event"
            " ORDER BY seq DESC LIMIT 1").fetchone()
        self.assertEqual(int(seq), last["seq"])
        # recompute the head digest and compare with the mirrored file
        row = self.db.conn.execute(
            "SELECT * FROM audit_event ORDER BY seq DESC LIMIT 1").fetchone()
        j = Journal(self.db)
        self.assertEqual(digest, j.digest_of_row(row))
        ok, bad = j.full_chain_check()
        self.assertTrue(ok)

    def test_last_row_rewrite_detected_via_anchor(self):
        """Rewriting ONLY audit_event (not the mirror file) breaks the check —
        this closes the 'rewrite the tail' hole from review round 1."""
        goal_id = self.make_goal_with_task()
        self.make_goal_with_task()   # second goal => multiple events
        self.db.conn.execute(
            "UPDATE audit_event SET payload_json='{\"evil\":true}'"
            " WHERE seq=(SELECT MAX(seq) FROM audit_event)")
        ok, bad = Journal(self.db).full_chain_check()
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
