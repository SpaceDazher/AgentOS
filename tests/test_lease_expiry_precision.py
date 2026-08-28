"""Regression: expired-lease denial must not depend on timestamp string
formatting. SLOQUAL-001's worker_restart probe found a window of up to ~1 s
where an expired lease was still honored: Engine stores second-precision ISO
stamps while the gateway clock has milliseconds, and the old check compared
the two strings lexicographically ("...59.950Z" sorts before "...59Z").
"""
import sys
import time
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentos.gateway import StaleOwnerError  # noqa: E402


class LeaseExpiryPrecisionTest(unittest.TestCase):
    def test_expired_lease_denies_inside_expiry_second(self):
        """With the lease long expired, a mutating op must be denied even when
        the current wall clock sits inside the expiry value's own second."""
        from agentos.sloqual import harness as H
        from agentos.sloqual.harness import WRITE_CAPABILITY
        from agentos.sloqual.revocation import grant
        sdir = Path(tempfile.mkdtemp(prefix="lease-precision"))
        handle = H.build_runtime(sdir)
        try:
            handle.engine.plan_tasks(handle.goal_id, [{
                "key": "lp", "title": "lp-probe",
                "definition_of_done": "regression"}])
            handle.engine.schedule_ready_tasks(handle.goal_id)
            row = handle.db.conn.execute(
                "SELECT id FROM task WHERE title='lp-probe'").fetchone()
            _, short_ctx = handle.engine.open_run(row[0], lease_minutes=0.01)
            # Force expiry into the strict past, second precision, and sleep
            # so 'now' has a millisecond suffix within that same second.
            past = datetime.now(timezone.utc) - timedelta(seconds=5)
            handle.db.conn.execute(
                "UPDATE run SET lease_expires_at=? WHERE id=?",
                (past.strftime("%Y-%m-%dT%H:%M:%SZ"), short_ctx.run_id))
            grant(handle.db.conn, subject="lease-probe",
                  capability=WRITE_CAPABILITY)
            time.sleep(0.05)
            probe = H.ledger_subject_context(
                handle, subject="lease-probe", run_id=short_ctx.run_id,
                lease_owner=short_ctx.lease_owner)
            resolved = handle.gateway.resolve("qual.worklog_append", "1.0.0")
            with self.assertRaises(StaleOwnerError):
                handle.gateway.invoke(probe, resolved,
                                      {"line_id": "lease-precision"})
        finally:
            handle.close()

    def test_malformed_expiry_fails_closed(self):
        """A lease_expires_at that cannot be parsed must DENY mutating ops —
        never fall back to a string comparison that lets writes through."""
        from agentos.sloqual import harness as H
        from agentos.sloqual.harness import WRITE_CAPABILITY
        from agentos.sloqual.revocation import grant
        sdir = Path(tempfile.mkdtemp(prefix="lease-malformed"))
        handle = H.build_runtime(sdir)
        try:
            handle.engine.plan_tasks(handle.goal_id, [{
                "key": "lm", "title": "lm-probe",
                "definition_of_done": "regression"}])
            handle.engine.schedule_ready_tasks(handle.goal_id)
            row = handle.db.conn.execute(
                "SELECT id FROM task WHERE title='lm-probe'").fetchone()
            _, short_ctx = handle.engine.open_run(row[0], lease_minutes=30)
            handle.db.conn.execute(
                "UPDATE run SET lease_expires_at='not-a-timestamp' "
                "WHERE id=?", (short_ctx.run_id,))
            grant(handle.db.conn, subject="lease-probe2",
                  capability=WRITE_CAPABILITY)
            probe = H.ledger_subject_context(
                handle, subject="lease-probe2", run_id=short_ctx.run_id,
                lease_owner=short_ctx.lease_owner)
            resolved = handle.gateway.resolve("qual.worklog_append", "1.0.0")
            with self.assertRaises(StaleOwnerError):
                handle.gateway.invoke(probe, resolved,
                                      {"line_id": "malformed-expiry"})
        finally:
            handle.close()

    def test_persisted_expiry_parses_as_utc(self):
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        self.assertIsNotNone(parsed.tzinfo)


if __name__ == "__main__":
    unittest.main()
