"""Engine: goal/task/run lifecycle, dependency-ready scheduling, leases,
checkpoints, bounded retries, crash recovery. See spec/SPEC.md §2, §5."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .context_compiler import ContextCompiler
from .gateway import RunContext, StaleOwnerError
from .ids import canonical_json, new_id, sha256_text
from .journal import Journal
from .machines import Machines
from .workers import StepRequest, WorkerAdapter


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class LeaseHeldError(Exception):
    pass


class Engine:
    def __init__(self, db, root_dir: str | Path):
        self.db = db
        self.root = Path(root_dir)
        self.j = Journal(db)
        self.m = Machines(db, self.j)
        self.compiler = ContextCompiler(db)

    # -- goals -----------------------------------------------------------------
    def create_goal(self, concept_text: str, actor: str = "requester",
                    constraints: dict | None = None,
                    risk_tier: str = "normal", budget: dict | None = None) -> str:
        goal_id = new_id("goal")
        self.db.conn.execute(
            "INSERT INTO goal(id, concept_text, constraints_json, risk_tier,"
            " budget_json) VALUES (?,?,?,?,?)",
            (goal_id, concept_text, canonical_json(constraints or {}), risk_tier,
             canonical_json(budget or {})))
        art_id = self._store_artifact(goal_id, "concept", concept_text)
        self.j.append_event(goal_id, actor, "goal.created",
                            {"goal_id": goal_id, "concept_artifact": art_id})
        return goal_id

    def refine_spec(self, goal_id: str, spec_text: str,
                    criteria: list[dict], actor: str = "requester") -> str:
        row = self.db.conn.execute(
            "SELECT status FROM goal WHERE id=?", (goal_id,)).fetchone()
        if not row or row["status"] not in ("DRAFT", "REJECTED", "ACTIVE"):
            raise RuntimeError("goal not open for spec refinement")
        spec_id = self._store_artifact(goal_id, "specification", spec_text,
                                       supersede_kind=True)
        # F-P0-2: criteria are append-only immutable VERSIONS. A re-refinement
        # adds criterion_version+1 rows instead of deleting history, so old
        # evaluations bind to their (now superseded) version.
        prev_max = {r["criterion_id"]: r["v"] for r in self.db.conn.execute(
            "SELECT criterion_id, MAX(criterion_version) v FROM acceptance_criteria"
            " WHERE goal_id=? GROUP BY criterion_id", (goal_id,)).fetchall()}
        for c in criteria:
            import hashlib
            cfg = canonical_json({"kind": c["kind"],
                                  **c.get("params", {})})
            chash = sha256_text(cfg)
            ver = int(prev_max.get(c["criterion_id"], 0)) + 1
            self.db.conn.execute(
                "INSERT INTO acceptance_criteria(id, goal_id, criterion_id,"
                " criterion_version, kind, params_json, config_hash)"
                " VALUES (?,?,?,?,?,?,?)",
                (new_id("crit"), goal_id, c["criterion_id"], ver, c["kind"],
                 canonical_json(c.get("params", {})), chash))
        self.j.append_event(goal_id, actor, "spec.refined",
                            {"spec_artifact": spec_id, "criteria":
                             [c["criterion_id"] for c in criteria]})
        return spec_id

    def activate_goal(self, goal_id: str, actor: str = "requester") -> None:
        n = self.db.conn.execute(
            "SELECT COUNT(*) FROM artifact_version WHERE goal_id=?"
            " AND kind='specification'", (goal_id,)).fetchone()[0]
        c = self.db.conn.execute(
            "SELECT COUNT(*) FROM acceptance_criteria WHERE goal_id=?",
            (goal_id,)).fetchone()[0]
        if n < 1 or c < 1:
            raise RuntimeError("activate requires a specification and >=1 criterion")
        self.m.goal_transition(goal_id, "DRAFT", "ACTIVE", actor)

    def cancel_goal(self, goal_id: str, actor: str = "requester") -> None:
        status = self.db.conn.execute(
            "SELECT status FROM goal WHERE id=?", (goal_id,)).fetchone()["status"]
        self.m.goal_transition(goal_id, status, "CANCELLED", actor)
        for t in self.db.conn.execute(
                "SELECT id, status FROM task WHERE goal_id=?", (goal_id,)).fetchall():
            if t["status"] in ("PENDING", "READY", "BLOCKED"):
                self.m.task_transition(t["id"], t["status"], "CANCELLED",
                                       actor, goal_id)

    def _store_artifact(self, goal_id: str, kind: str, content: str,
                        supersede_kind: bool = False) -> str:
        ver = (self.db.conn.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM artifact_version"
            " WHERE goal_id=? AND kind=?", (goal_id, kind)).fetchone()[0])
        digest = sha256_text(content)
        rel = f"goals/{goal_id}/artifacts/{kind}-v{ver}.md"
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        aid = new_id("artifact")
        self.db.conn.execute(
            "INSERT INTO artifact_version(id, goal_id, kind, version,"
            " content_sha256, storage_path, status) VALUES (?,?,?,?,?,?,'CURRENT')",
            (aid, goal_id, kind, ver, digest, str(path)))
        if supersede_kind:
            for r in self.db.conn.execute(
                    "SELECT id FROM artifact_version WHERE goal_id=? AND kind=?"
                    " AND id<>? AND status='CURRENT'", (goal_id, kind, aid)).fetchall():
                self.db.conn.execute(
                    "UPDATE artifact_version SET status='SUPERSEDED',"
                    " superseded_by_id=? WHERE id=?", (aid, r["id"]))
                self.db.conn.execute(
                    "INSERT INTO relation_assertion(id, src_type, src_id, rel,"
                    " dst_type, dst_id, asserter) VALUES (?, 'artifact', ?,"
                    " 'SUPERSEDES', 'artifact', ?, 'system')",
                    (new_id("rel"), aid, r["id"]))
        return aid

    # -- planning ------------------------------------------------------------
    def plan_tasks(self, goal_id: str, tasks: list[dict],
                   actor: str = "system") -> list[str]:
        ids: dict[str, str] = {}
        for t in tasks:
            tid = new_id("task")
            ids[t["key"]] = tid
        seen: set[str] = set()

        def resolve(deps: list[str]) -> list[str]:
            out = []
            for d in deps:
                if d not in ids:
                    raise RuntimeError(f"unknown task key '{d}' in dependencies")
                out.append(ids[d])
            return out

        # acyclicity via DFS on keys
        graph = {t["key"]: list(t.get("depends_on", [])) for t in tasks}
        state: dict[str, int] = {}

        def dfs(k: str) -> None:
            if state.get(k) == 1:
                raise RuntimeError(f"dependency cycle at '{k}'")
            if state.get(k) == 2:
                return
            state[k] = 1
            for d in graph[k]:
                dfs(d)
            state[k] = 2

        for k in graph:
            dfs(k)

        for t in tasks:
            tid = ids[t["key"]]
            self.db.conn.execute(
                "INSERT INTO task(id, goal_id, title, depends_on_json,"
                " inputs_json, expected_outputs_json, definition_of_done,"
                " risk_tier, retry_budget, attempts) VALUES (?,?,?,?,?,?,?,?,?,0)",
                (tid, goal_id, t["title"], canonical_json(resolve(t.get("depends_on", []))),
                 canonical_json(t.get("inputs", {})),
                 canonical_json(t.get("expected_outputs", [])),
                 t["definition_of_done"], t.get("risk_tier", "normal"),
                 int(t.get("retry_budget", 2))))
        self._store_artifact(goal_id, "plan",
                             canonical_json({"tasks": [
                                 {"id": ids[t["key"]], "title": t["title"],
                                  "depends_on": t.get("depends_on", [])}
                                 for t in tasks]}))
        self.j.append_event(goal_id, actor, "plan.created",
                            {"task_ids": list(ids.values())})
        return [ids[t["key"]] for t in tasks]

    # -- scheduling ---------------------------------------------------------------
    def schedule_ready_tasks(self, goal_id: str) -> list[str]:
        rows = self.db.conn.execute(
            "SELECT * FROM task WHERE goal_id=?", (goal_id,)).fetchall()
        by_id = {r["id"]: r for r in rows}
        ready: list[str] = []
        for r in rows:
            if r["status"] != "PENDING":
                continue
            deps = json.loads(r["depends_on_json"])
            if all(by_id[d]["status"] == "DONE" for d in deps):
                ready.append(r["id"])
        ready.sort()
        out = []
        for tid in ready:
            res = self.m.task_transition(tid, "PENDING", "READY", "system", goal_id,
                                         transition_key=f"ready:{tid}")
            if not res.get("duplicate"):
                out.append(tid)
        blocked = [r["id"] for r in rows if r["status"] == "BLOCKED"]
        return out

    def runnable_order(self, goal_id: str) -> list[str]:
        """All READY task ids in deterministic execution order."""
        rows = self.db.conn.execute(
            "SELECT id FROM task WHERE goal_id=? AND status='READY' ORDER BY id",
            (goal_id,)).fetchall()
        return [r["id"] for r in rows]

    # -- runs --------------------------------------------------------------------
    def open_run(self, task_id: str, lease_minutes: int = 30) -> tuple[str, RunContext]:
        """Open a live worker session: the task moves to RUNNING and stays there
        across multiple gateway invocations until close_run()/complete/fail.
        This models a real long-lived worker holding its lease while it works."""
        task = self.db.conn.execute(
            "SELECT * FROM task WHERE id=?", (task_id,)).fetchone()
        if not task:
            raise RuntimeError("no such task")
        if task["owner_run_id"]:
            active = self.db.conn.execute(
                "SELECT status FROM run WHERE id=?",
                (task["owner_run_id"],)).fetchone()
            if active and active["status"] == "RUNNING":
                raise LeaseHeldError(
                    f"task {task_id} already owned by run {task['owner_run_id']}")
        goal_id = task["goal_id"]
        run_id = new_id("run")
        ws = self.root / "workspaces" / run_id
        ws.mkdir(parents=True, exist_ok=True)
        expires = _iso(_now() + timedelta(minutes=lease_minutes))
        self.db.conn.execute(
            "INSERT INTO run(id, task_id, goal_id, worker_type, lease_owner,"
            " lease_expires_at, workspace_path, status, resumed_from_run_id)"
            " VALUES (?,?,?,?,?,?,?, 'PLANNED', NULL)",
            (run_id, task_id, goal_id, "interactive", run_id, expires, str(ws)))
        self.m.run_transition(run_id, "PLANNED", "RUNNING", "worker", goal_id)
        prev_owner = task["owner_run_id"]
        self.m.task_transition(task_id, "READY", "RUNNING", "worker", goal_id,
                               extra_sets={"owner_run_id": run_id})
        ctx = RunContext(run_id=run_id, goal_id=goal_id, task_id=task_id,
                         lease_owner=run_id,
                         capabilities=self._capabilities_for(goal_id),
                         workspace_path=str(ws))
        return run_id, ctx

    def complete_live_run(self, ctx: RunContext, outputs: dict | None = None) -> None:
        """Finish an open_run session successfully.

        F-P0-3: when the caller passes no explicit outputs, the code artifact is
        re-derived from the files actually written through the gateway during
        this run (the trusted effect record) — never from worker claims."""
        from .workers import StepResult
        if outputs is None:
            rows = self.db.conn.execute(
                "SELECT args_canonical_json FROM activity"
                " WHERE run_id=? AND op_name LIKE 'fs.write%' AND status='SUCCEEDED'",
                (ctx.run_id,)).fetchall()
            files: dict[str, str] = {}
            for r in rows:
                args = json.loads(r["args_canonical_json"])
                p = Path(args.get("path", ""))
                try:
                    content = p.read_text(encoding="utf-8")
                    rel = str(p.relative_to(ctx.workspace_path)).replace("\\\\", "/")
                    files[rel] = content
                except (OSError, ValueError):
                    continue
            outputs = {"files": files} if files else {}
        task = self.db.conn.execute(
            "SELECT * FROM task WHERE id=?", (ctx.task_id,)).fetchone()
        self.complete_run(ctx, task,
                          StepResult(ok=True, note="live run completed",
                                     outputs=outputs,
                                     next_action={"done": True}))

    def close_run(self, run_id: str) -> None:
        """Abandon a live run without completing the task (worker detached)."""
        row = self.db.conn.execute(
            "SELECT status FROM run WHERE id=?", (run_id,)).fetchone()
        if row and row["status"] == "RUNNING":
            self.fail_run(run_id,
                          self.db.conn.execute(
                              "SELECT goal_id FROM run WHERE id=?",
                              (run_id,)).fetchone()["goal_id"],
                          "detached", "run closed by operator")

    def start_task(self, task_id: str, worker: WorkerAdapter,
                   lease_minutes: int = 30, resumed_from_run: str | None = None,
                   checkpoint_payload_path: str | None = None) -> str:
        task = self.db.conn.execute(
            "SELECT * FROM task WHERE id=?", (task_id,)).fetchone()
        if not task:
            raise RuntimeError("no such task")
        if task["owner_run_id"]:
            active = self.db.conn.execute(
                "SELECT status FROM run WHERE id=?", (task["owner_run_id"],)).fetchone()
            if active and active["status"] == "RUNNING":
                raise LeaseHeldError(f"task {task_id} already owned by run {task['owner_run_id']}")
        goal_id = task["goal_id"]
        run_id = new_id("run")
        ws = self.root / "workspaces" / run_id
        ws.mkdir(parents=True, exist_ok=True)
        expires = _iso(_now() + timedelta(minutes=lease_minutes))
        self.db.conn.execute(
            "INSERT INTO run(id, task_id, goal_id, worker_type, lease_owner,"
            " lease_expires_at, workspace_path, status, resumed_from_run_id)"
            " VALUES (?,?,?,?,?,?,?, 'PLANNED', ?)",
            (run_id, task_id, goal_id, worker.name, run_id, expires, str(ws),
             resumed_from_run))
        self.db.conn.execute(
            "UPDATE task SET owner_run_id=? WHERE id=?", (run_id, task_id))
        self.m.run_transition(run_id, "PLANNED", "RUNNING", "worker", goal_id)
        self.m.task_transition(task_id, "READY", "RUNNING", "worker", goal_id,
                               extra_sets={"owner_run_id": run_id})
        ctx = RunContext(run_id=run_id, goal_id=goal_id, task_id=task_id,
                         lease_owner=run_id,
                         capabilities=self._capabilities_for(goal_id),
                         workspace_path=str(ws))
        self._execute_steps(worker, ctx, task, checkpoint_payload_path)
        return run_id

    def drive_task(self, task_id: str, worker: WorkerAdapter,
                   max_rounds: int = 6) -> str:
        """Convenience driver: one start_task call is one worker attempt, so a
        flaky script needs retry rounds. Loop: DONE/FAILED are terminal; READY
        schedules then runs one attempt; any other status gets one scheduling
        pass and gives up if the task never becomes READY. Returns the final
        task status string."""
        status: str | None = None
        scheduled_once = False
        for _ in range(max_rounds):
            row = self.db.conn.execute(
                "SELECT * FROM task WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise RuntimeError("no such task")
            goal_id = row["goal_id"]
            status = row["status"]
            if status in ("DONE", "FAILED"):
                break  # terminal states
            if status == "READY":
                self.schedule_ready_tasks(goal_id)
                self.start_task(task_id, worker)
                continue
            # PENDING/BLOCKED/...: schedule once, then stop if never READY
            if not scheduled_once:
                self.schedule_ready_tasks(goal_id)
                scheduled_once = True
                continue
            break
        return status

    def _capabilities_for(self, goal_id: str) -> set[str]:
        caps = {"fs.read"}
        g = self.db.conn.execute(
            "SELECT risk_tier FROM goal WHERE id=?", (goal_id,)).fetchone()
        if g and g["risk_tier"] == "normal":
            caps |= {"fs.write_local", "cmd.local"}
        else:
            caps |= {"fs.write_local"}  # sensitive: no local commands without approval
        return caps

    def _execute_steps(self, worker: WorkerAdapter, ctx: RunContext,
                       task, checkpoint_payload_path: str | None) -> None:
        goal_id = ctx.goal_id
        budget = 4
        step = self._attempts_before(ctx.task_id)   # script position across retries
        checkpoint: dict | None = None
        if checkpoint_payload_path:
            # F6: verify the file digest against the DB-recorded sha256 BEFORE
            # using it; any mismatch refuses resume (fail-closed).
            cp_row = self.db.conn.execute(
                "SELECT sha256 FROM checkpoint WHERE payload_path=?"
                " ORDER BY seq DESC LIMIT 1", (str(checkpoint_payload_path),)
            ).fetchone()
            if cp_row is None:
                raise RuntimeError("resume refused: checkpoint not registered in DB")
            raw = json.loads(Path(checkpoint_payload_path).read_bytes().decode("utf-8"))
            stored_sha = raw.get("_sha")
            # the writer hashes the body WITHOUT the _sha field
            body = {k: v for k, v in raw.items() if k != "_sha"}
            if sha256_text(canonical_json(body)) != stored_sha:
                raise RuntimeError("resume refused: checkpoint file self-hash mismatch")
            if stored_sha != cp_row["sha256"]:
                raise RuntimeError(
                    "resume refused: checkpoint file digest != DB sha256")
            checkpoint = raw.get("payload") if isinstance(raw, dict) else None
            if checkpoint is None:
                raise RuntimeError("resume refused: checkpoint payload missing")

        packet = self.compiler.compile(goal_id, task["title"]).render()

        while step < budget:
            req = StepRequest(task_id=ctx.task_id, run_id=ctx.run_id,
                              goal_id=goal_id, title=task["title"],
                              definition_of_done=task["definition_of_done"],
                              inputs=json.loads(task["inputs_json"]),
                              workspace_path=ctx.workspace_path, step=step,
                              checkpoint=checkpoint, context_packet_text=packet)
            res = worker.step(req)
            if not res.ok:
                reason = res.fail_class or "worker"
                self.fail_run(ctx.run_id, goal_id, reason, res.note)
                self._task_fail_or_retry(task["id"], goal_id, reason)
                return
            step += 1
            cp_id = self.record_checkpoint(ctx.run_id, goal_id,
                                           completed=[f"step-{step}"],
                                           in_progress={"next": res.next_action},
                                           next_action=res.next_action,
                                           payload={"steps_done": step})
            checkpoint = {"completed": [f"step-{step}"], "next": res.next_action}
            if res.next_action.get("done"):
                self.complete_run(ctx, task, res)
                return
        self.fail_run(ctx.run_id, goal_id, "budget", "step budget exhausted")

    def _attempts_before(self, task_id: str) -> int:
        """Script position for a retrying task: prior attempts consume script
        entries, so a [fail, ok] script succeeds on the second attempt."""
        row = self.db.conn.execute(
            "SELECT attempts FROM task WHERE id=?", (task_id,)).fetchone()
        return int(row["attempts"]) if row else 0

    def record_checkpoint(self, run_id: str, goal_id: str, *,
                          completed: list, in_progress: dict, next_action: dict,
                          payload: dict) -> str:
        seq_row = self.db.conn.execute(
            "SELECT COALESCE(MAX(seq),0)+1 FROM checkpoint WHERE run_id=?",
            (run_id,)).fetchone()[0]
        body = {"run_id": run_id, "seq": seq_row, "payload": payload}
        digest = sha256_text(canonical_json(body))
        rel = f"workspaces/{run_id}/checkpoint-{seq_row}.json"
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json({**body, "_sha": digest}), encoding="utf-8")
        cid = new_id("cp")
        self.db.conn.execute(
            "INSERT INTO checkpoint(id, run_id, seq, payload_path, sha256,"
            " work_completed_json, work_in_progress_json, next_action_json)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (cid, run_id, seq_row, str(path), digest,
             canonical_json(completed), canonical_json(in_progress),
             canonical_json(next_action)))
        return cid

    def latest_checkpoint(self, run_id: str):
        return self.db.conn.execute(
            "SELECT * FROM checkpoint WHERE run_id=? ORDER BY seq DESC LIMIT 1",
            (run_id,)).fetchone()

    def complete_run(self, ctx: RunContext, task, res) -> None:
        outputs = res.outputs
        code_blob = canonical_json(outputs)
        # Completion is one durable state change: a crash may leave an
        # unreferenced file written before COMMIT, but can never persist
        # run=COMPLETED while task remains RUNNING (or vice versa).
        with self.db.tx() as conn:
            self.j.transition_locked(
                conn, table="run", obj_id=ctx.run_id,
                expect_from="RUNNING", to="COMPLETED", actor="worker",
                goal_id=ctx.goal_id, event_type="run.completed", payload={},
                extra_sets={"terminal_reason": "success"})
            self._store_artifact(
                ctx.goal_id, "code", code_blob, supersede_kind=True)
            self.j.transition_locked(
                conn, table="task", obj_id=ctx.task_id,
                expect_from="RUNNING", to="DONE", actor="system",
                goal_id=ctx.goal_id, event_type="task.done", payload={},
                extra_sets={"owner_run_id": None})

    def fail_run(self, run_id: str, goal_id: str, reason: str, note: str) -> None:
        self.m.run_transition(run_id, "RUNNING", "FAILED", "worker", goal_id,
                              extra_sets={"terminal_reason": f"{reason}: {note}"[:300]})

    def _task_fail_or_retry(self, task_id: str, goal_id: str, reason: str) -> None:
        task = self.db.conn.execute(
            "SELECT * FROM task WHERE id=?", (task_id,)).fetchone()
        attempts = task["attempts"] + 1
        if attempts <= task["retry_budget"]:
            self.m.task_transition(task_id, "RUNNING", "FAILED", "system", goal_id,
                                   extra_sets={"attempts": attempts},
                                   payload={"fail_class": reason})
            self.m.task_transition(task_id, "FAILED", "READY", "system", goal_id,
                                   extra_sets={"owner_run_id": None},
                                   payload={"retry_scheduled": True})
        else:
            self.m.task_transition(task_id, "RUNNING", "FAILED", "system", goal_id,
                                   extra_sets={"attempts": attempts},
                                   payload={"fail_class": reason,
                                            "retries_exhausted": True})

    # -- crash recovery / pause / resume ----------------------------------------------
    def recover_expired_runs(self) -> list[str]:
        """Mark RUNNING runs with expired leases as FAILED(crashed); returns ids."""
        now = _iso(_now())
        rows = self.db.conn.execute(
            "SELECT id, task_id, goal_id FROM run WHERE status='RUNNING'"
            " AND lease_expires_at < ?", (now,)).fetchall()
        crashed = []
        for r in rows:
            self.m.run_transition(r["id"], "RUNNING", "FAILED", "system",
                                  r["goal_id"],
                                  extra_sets={"terminal_reason": "crashed"})
            task = self.db.conn.execute("SELECT status FROM task WHERE id=?",
                                        (r["task_id"],)).fetchone()
            if task and task["status"] == "RUNNING":
                self._task_fail_or_retry(r["task_id"], r["goal_id"], "crashed")
            crashed.append(r["id"])
        return crashed

    def resume_task(self, task_id: str, worker: WorkerAdapter) -> str | None:
        task = self.db.conn.execute(
            "SELECT * FROM task WHERE id=?", (task_id,)).fetchone()
        prev = self.db.conn.execute(
            "SELECT id FROM run WHERE task_id=? ORDER BY created_at DESC LIMIT 1",
            (task_id,)).fetchone()
        if not prev:
            return None
        cp = self.latest_checkpoint(prev["id"])
        return self.start_task(task_id, worker,
                               resumed_from_run=prev["id"],
                               checkpoint_payload_path=cp["payload_path"] if cp else None)

    def pause_run(self, run_id: str, actor: str = "requester") -> None:
        row = self.db.conn.execute(
            "SELECT goal_id FROM run WHERE id=?", (run_id,)).fetchone()
        self.m.run_transition(run_id, "RUNNING", "PAUSED", actor, row["goal_id"])

    def submit_to_gate(self, goal_id: str, actor: str = "system") -> None:
        tasks = self.db.conn.execute(
            "SELECT status FROM task WHERE goal_id=?", (goal_id,)).fetchall()
        if not tasks or any(t["status"] != "DONE" for t in tasks):
            raise RuntimeError("gate submission requires all tasks DONE")
        crits = self.db.conn.execute(
            "SELECT COUNT(DISTINCT e.criterion_id) FROM evaluation e"
            " JOIN acceptance_criteria c ON c.criterion_id=e.criterion_id"
            " AND c.goal_id=e.goal_id AND c.criterion_version=e.criterion_version"
            " WHERE e.goal_id=? AND c.criterion_version = ("
            "   SELECT MAX(c2.criterion_version) FROM acceptance_criteria c2"
            "   WHERE c2.goal_id=c.goal_id AND c2.criterion_id=c.criterion_id)",
            (goal_id,)).fetchone()[0]
        need = self.db.conn.execute(
            "SELECT COUNT(DISTINCT criterion_id) FROM acceptance_criteria"
            " WHERE goal_id=?", (goal_id,)).fetchone()[0]
        if crits < need:
            raise RuntimeError("each current criterion version needs ≥1 evaluation before gate")
        self.m.goal_transition(goal_id, "ACTIVE", "GATE_PENDING", "system")
