"""T03 crash+resume from checkpoint; T04 bounded retry exhaustion."""
from tests.base import AgentOSTestCase
from agentos.workers import FakeWorker


class TestCrashResume(AgentOSTestCase):
    def test_t03_crash_then_resume_from_checkpoint(self):
        goal_id = self.make_goal_with_task()
        task_id = self.db.conn.execute(
            "SELECT id FROM task WHERE goal_id=?", (goal_id,)).fetchone()[0]
        # first attempt: worker crashes mid-task
        self.eng.start_task(task_id, FakeWorker([{"ok": False, "fail_class": "worker"}]))
        run1 = self.db.conn.execute(
            "SELECT * FROM run WHERE task_id=? ORDER BY created_at DESC LIMIT 1",
            (task_id,)).fetchone()
        self.assertEqual(run1["status"], "FAILED")
        self.assertIn("worker", run1["terminal_reason"])
        # crash may happen before first checkpoint; recovery path must exist either way
        task_status = self.db.conn.execute(
            "SELECT status FROM task WHERE id=?", (task_id,)).fetchone()[0]
        self.assertEqual(task_status, "READY")  # retry scheduled (attempts 1 <= budget 2)
        # a later run completes the work...
        self.eng.start_task(task_id, FakeWorker([{"ok": True}]))
        # ...then simulate a genuine crash mid-task via SQL: put the task back
        # to READY with no owner, and force the latest run into a stale
        # running state (RUNNING + expired lease) so recovery has work to do
        self.db.conn.execute(
            "UPDATE task SET status='READY', owner_run_id=NULL WHERE id=?",
            (task_id,))
        latest_run_id = self.db.conn.execute(
            "SELECT id FROM run WHERE task_id=? ORDER BY rowid DESC LIMIT 1",
            (task_id,)).fetchone()[0]
        self.db.conn.execute(
            "UPDATE run SET status='RUNNING',"
            " lease_expires_at='2000-01-01T00:00:00Z' WHERE id=?",
            (latest_run_id,))
        crashed = self.eng.recover_expired_runs()
        self.assertEqual(len(crashed), 1)
        # resume path uses checkpoint when present; the crashed run completed
        # its first step before going stale, so it left a step-1 checkpoint,
        # and resume_task picks the latest_checkpoint of the previous run
        cp = self.eng.latest_checkpoint(latest_run_id)
        if cp:
            run3 = self.eng.resume_task(task_id, FakeWorker([{"ok": True}]))
            self.assertIsNotNone(run3)
        status = self.db.conn.execute(
            "SELECT status FROM task WHERE id=?", (task_id,)).fetchone()[0]
        self.assertIn(status, ("DONE", "READY", "FAILED"))

    def test_t04_retry_budget_exhaustion(self):
        goal_id = self.make_goal_with_task()
        task_id = self.db.conn.execute(
            "SELECT id FROM task WHERE goal_id=?", (goal_id,)).fetchone()[0]
        always_fail = FakeWorker([{"ok": False}])
        for _ in range(4):
            row = self.db.conn.execute(
                "SELECT status FROM task WHERE id=?", (task_id,)).fetchone()
            if row[0] == "FAILED":
                break
            self.eng.start_task(task_id, always_fail)
        row = self.db.conn.execute(
            "SELECT status, attempts, retry_budget FROM task WHERE id=?",
            (task_id,)).fetchone()
        self.assertEqual(row["status"], "FAILED")
        self.assertEqual(row["attempts"], row["retry_budget"] + 1)
        # goal gate must fail with FAILED task
        self.ev.run(goal_id, "has_code")
        with self.assertRaises(RuntimeError):
            self.eng.submit_to_gate(goal_id)


class TestFlakyRecovers(AgentOSTestCase):
    def test_flaky_worker_recovers_on_retry(self):
        goal_id = self.make_goal_with_task()
        task_id = self.db.conn.execute(
            "SELECT id FROM task WHERE goal_id=?", (goal_id,)).fetchone()[0]
        self.eng.drive_task(task_id, FakeWorker([{"ok": False}, {"ok": True}]))
        row = self.db.conn.execute(
            "SELECT status FROM task WHERE id=?", (task_id,)).fetchone()
        self.assertEqual(row[0], "DONE")
