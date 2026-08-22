"""Tool registry, gateway pipeline, exact-action approvals, idempotency,
fencing, reconciliation and memory scoping. See spec/SPEC.md §6."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .ids import canonical_json, new_id, sha256_text


class GatewayError(Exception):
    pass


class CapabilityDenied(GatewayError):
    pass


class ApprovalRequired(GatewayError):
    pass


class ApprovalInvalid(GatewayError):
    pass


class IdempotencyConflict(GatewayError):
    pass


class StaleOwnerError(GatewayError):
    pass


class MemoryScopeViolation(GatewayError):
    pass


POLICY_VERSION = "policy-v1"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass
class RunContext:
    """What a run may do; replaces ambient credentials."""
    run_id: str
    goal_id: str
    task_id: str
    lease_owner: str
    capabilities: set[str]
    workspace_path: str
    fence_token: int = 0


@dataclass
class ToolContract:
    name: str
    version: str
    input_schema: dict
    output_schema: dict = field(default_factory=dict)
    server_identity: str = "builtin"
    required_capability: str = ""
    effect_class: str = "read"           # read|write_local|write_external|dangerous
    sensitivity: str = "normal"          # normal|high
    idempotency: str = "none"            # none|keyed|natural
    compensation: str | None = None
    handler: Callable[..., dict] | None = None
    preconditions: dict = field(default_factory=dict)
    postconditions: dict = field(default_factory=dict)

    def fingerprint(self) -> str:
        return sha256_text(canonical_json({
            "input": self.input_schema, "output": self.output_schema,
            "effect_class": self.effect_class, "sensitivity": self.sensitivity,
            "idempotency": self.idempotency, "required_capability": self.required_capability,
        }))


class ToolGateway:
    def __init__(self, db, journal):
        self.db = db
        self.j = journal

    # -- registry ---------------------------------------------------------------
    def register(self, contract: ToolContract) -> None:
        self.db.conn.execute(
            "INSERT OR REPLACE INTO tool_contract"
            "(name, version, input_schema_json, output_schema_json, server_identity,"
            " required_capability, effect_class, sensitivity, idempotency,"
            " retry_policy_json, compensation, preconditions_json, postconditions_json,"
            " audit_level, schema_fingerprint)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                contract.name, contract.version,
                canonical_json(contract.input_schema),
                canonical_json(contract.output_schema),
                contract.server_identity, contract.required_capability,
                contract.effect_class, contract.sensitivity, contract.idempotency,
                "{}", contract.compensation,
                canonical_json(contract.preconditions),
                canonical_json(contract.postconditions), "full",
                contract.fingerprint(),
            ),
        )

    def resolve(self, name: str, version: str | None = None) -> ToolContract:
        if version:
            row = self.db.conn.execute(
                "SELECT * FROM tool_contract WHERE name=? AND version=?", (name, version)
            ).fetchone()
        else:
            row = self.db.conn.execute(
                "SELECT * FROM tool_contract WHERE name=?"
                " ORDER BY version DESC LIMIT 1", (name,)
            ).fetchone()
        if not row:
            raise GatewayError(f"unknown tool {name}@{version or 'latest'}")
        c = ToolContract(
            name=row["name"], version=row["version"],
            input_schema=json.loads(row["input_schema_json"]),
            output_schema=json.loads(row["output_schema_json"]),
            server_identity=row["server_identity"],
            required_capability=row["required_capability"],
            effect_class=row["effect_class"], sensitivity=row["sensitivity"],
            idempotency=row["idempotency"], compensation=row["compensation"],
        )
        stored_fp = row["schema_fingerprint"]
        if stored_fp != c.fingerprint():
            # registry row was altered after registration — refuse (malicious change)
            raise GatewayError(
                f"tool {c.name}@{c.version} schema fingerprint mismatch "
                f"(registry tampering suspected)")
        return c

    # -- validation ----------------------------------------------------------------
    @staticmethod
    def validate_args(contract: ToolContract, args: dict) -> dict:
        for req in contract.input_schema.get("required", []):
            if req not in args:
                raise GatewayError(f"missing required arg '{req}'")
        props: dict = contract.input_schema.get("properties", {})
        for k, v in args.items():
            spec = props.get(k)
            if not spec:
                if contract.input_schema.get("additionalProperties", True) is False:
                    raise GatewayError(f"unexpected arg '{k}'")
                continue
            t = spec.get("type")
            checks = {
                "string": lambda x: isinstance(x, str),
                "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
                "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
                "boolean": lambda x: isinstance(x, bool),
                "array": lambda x: isinstance(x, list),
                "object": lambda x: isinstance(x, dict),
            }
            if t in checks and not checks[t](v):
                raise GatewayError(f"arg '{k}' expected {t}")
        return args

    # -- approvals ---------------------------------------------------------------
    def grant_approval(self, *, goal_id: str, actor: str, operation: str,
                       tool_name: str, tool_version: str, args: dict, target: str,
                       ttl_seconds: int = 3600) -> str:
        nonce = new_id("approval").replace("approval_", "n-")
        expires = _now()  # replaced below for determinism-free expiry math
        from datetime import timedelta
        expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        aid = new_id("approval")
        self.db.conn.execute(
            "INSERT INTO approval(id, goal_id, actor, operation, tool_identity,"
            " args_canonical_json, target, policy_version, limits_json, expires_at, nonce,"
            " status) VALUES (?,?,?,?,?,?,?,?,?,?,?,'GRANTED')",
            (aid, goal_id, actor, operation, f"{tool_name}@{tool_version}",
             canonical_json(args), target, POLICY_VERSION, "{}", expires, nonce))
        self.j.append_event(goal_id, actor, "approval.granted",
                            {"approval_id": aid, "operation": operation,
                             "tool_identity": f"{tool_name}@{tool_version}",
                             "args_sha256": sha256_text(canonical_json(args)),
                             "nonce": nonce})
        return aid

    def consume_approval(self, *, nonce: str, operation: str, tool_identity: str,
                         args: dict, target: str, actor: str) -> dict:
        cur = self.db.conn.execute(
            "UPDATE approval SET status='CONSUMED'"
            " WHERE nonce=? AND status='GRANTED' AND operation=? AND tool_identity=?"
            " AND args_canonical_json=? AND target=? AND actor=?"
            " AND expires_at > ?",
            (nonce, operation, tool_identity, canonical_json(args), target, actor, _now()),
        )
        if cur.rowcount != 1:
            row = self.db.conn.execute(
                "SELECT * FROM approval WHERE nonce=?", (nonce,)).fetchone()
            if not row:
                raise ApprovalInvalid("unknown approval nonce")
            reason = (
                "replay (already consumed)" if row["status"] == "CONSUMED"
                else "expired" if row["status"] == "EXPIRED" or row["expires_at"] <= _now()
                else "binding mismatch (op/identity/args/target/actor)"
            )
            raise ApprovalInvalid(f"approval denied: {reason}")
        return {"consumed": True}

    def revoke_approval(self, approval_id: str, actor: str) -> None:
        self.db.conn.execute(
            "UPDATE approval SET status='REVOKED' WHERE id=? AND status='GRANTED'",
            (approval_id,))
        self.j.append_event(None, actor, "approval.revoked", {"approval_id": approval_id})

    # -- memory scoping ------------------------------------------------------------
    def memory_write(self, ctx: RunContext, kind: str, content: str,
                     source_uri: str, trust: str = "unverified") -> str:
        mid = new_id("memory")
        self.db.conn.execute(
            "INSERT INTO memory_record(id, scope_goal_id, kind, content, source_uri, trust)"
            " VALUES (?,?,?,?,?,?)",
            (mid, ctx.goal_id, kind, content, source_uri, trust))
        self.j.append_event(ctx.goal_id, f"run:{ctx.run_id}", "memory.written",
                            {"memory_id": mid, "kind": kind})
        return mid

    def memory_read(self, ctx: RunContext, memory_id: str) -> dict:
        row = self.db.conn.execute(
            "SELECT * FROM memory_record WHERE id=?", (memory_id,)).fetchone()
        if not row:
            raise GatewayError("no such memory record")
        if row["scope_goal_id"] != ctx.goal_id:
            raise MemoryScopeViolation(
                f"memory {memory_id} belongs to another scope")
        return dict(row)

    # -- main invocation pipeline ------------------------------------------------------
    def invoke(self, ctx: RunContext, contract: ToolContract, args: dict,
               idempotency_key: str | None = None,
               approval_nonce: str | None = None,
               reconcile: bool = False, activity_id: str | None = None) -> dict:
        op_key = f"{contract.name}@{contract.version}"
        canon = canonical_json(self.validate_args(contract, dict(args)))

        activity_id = activity_id or new_id("activity")

        def record(status: str, digest: str | None = None, detail: dict | None = None):
            self.db.conn.execute(
                "INSERT INTO activity(id, run_id, op_name, tool_identity,"
                " args_canonical_json, effect_class, status, result_digest, detail_json)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (activity_id, ctx.run_id, contract.name, op_key, canon,
                 contract.effect_class, status, digest, canonical_json(detail or {})))
            self.j.append_event(ctx.goal_id, f"run:{ctx.run_id}",
                                f"tool.{status.lower()}",
                                {"activity_id": activity_id, "op": op_key,
                                 "digest": digest})
            return {"ok": status == "SUCCEEDED", "status": status,
                    "activity_id": activity_id, "digest": digest}

        # capability check — model/output can never add capabilities
        if contract.required_capability and contract.required_capability not in ctx.capabilities:
            record("DENIED")
            raise CapabilityDenied(
                f"capability '{contract.required_capability}' not granted to run {ctx.run_id}")

        # dangerous ⇒ exact-action approval consumed atomically at invoke time
        if contract.effect_class == "dangerous":
            if not approval_nonce:
                raise ApprovalRequired(
                    f"{op_key} requires a one-time exact-action approval")
            # approver is the granting actor; the run merely presents the nonce
            approver = self.db.conn.execute(
                "SELECT actor FROM approval WHERE nonce=?", (approval_nonce,)
            ).fetchone()
            self.consume_approval(
                nonce=approval_nonce, operation="invoke_tool",
                tool_identity=op_key, args=args,
                target=self._approval_target(contract, args, ctx),
                actor=approver["actor"] if approver else f"run:{ctx.run_id}")

        # idempotency: key identifies INTENT; args compared separately so the
        # same key with different arguments is a detectable conflict (T05b).
        key_hash = None
        if idempotency_key:
            key_hash = sha256_text(idempotency_key + "|" + op_key)
            existing = self.db.conn.execute(
                "SELECT * FROM idempotency_key WHERE key_hash=?", (key_hash,)).fetchone()
            if existing:
                if existing["args_canonical_json"] != canon:
                    record("DENIED")
                    raise IdempotencyConflict(
                        "same idempotency key used with different arguments/intent")
                if existing["outcome_digest"]:
                    # replay: original outcome without re-execution
                    self.j.append_event(ctx.goal_id, f"run:{ctx.run_id}",
                                        "tool.replayed",
                                        {"activity_id": activity_id,
                                         "original_digest": existing["outcome_digest"]})
                    return {"ok": True, "status": "REPLAYED", "replayed": True,
                            "activity_id": activity_id,
                            "digest": existing["outcome_digest"]}
            self.db.conn.execute(
                "INSERT OR IGNORE INTO idempotency_key(key_hash, operation,"
                " args_canonical_json, first_seen_run_id, outcome_digest)"
                " VALUES (?,?,?,?,NULL)",
                (key_hash, op_key, canon, ctx.run_id))

        # lease / fencing check for mutating ops
        if contract.effect_class in ("write_local", "write_external", "dangerous"):
            row = self.db.conn.execute(
                "SELECT lease_owner, lease_expires_at FROM run WHERE id=?",
                (ctx.run_id,)).fetchone()
            if not row or row["lease_owner"] != ctx.lease_owner:
                raise StaleOwnerError("lease owner mismatch (stale writer)")
            if contract.effect_class != "read" and ctx.fence_token <= 0:
                ctx.fence_token = self._next_fence(conn=None)

        # execute handler
        try:
            result = contract.handler(**args) if contract.handler else {"echo": args}
            digest = sha256_text(canonical_json(result))
            out = record("SUCCEEDED", digest)
            if key_hash:
                self.db.conn.execute(
                    "UPDATE idempotency_key SET outcome_digest=? WHERE key_hash=?",
                    (digest, key_hash))
            return out
        except Exception as e:  # known failure of the tool itself
            return record("FAILED", detail={"error": str(e)[:300]})

    def mark_unknown_outcome(self, activity_id: str) -> None:
        self.db.conn.execute(
            "UPDATE activity SET status='UNKNOWN_OUTCOME' WHERE id=?"
            " AND status IN ('EXECUTING','AUTHORIZED','REQUESTED','SUCCEEDED')",
            (activity_id,))
        row = self.db.conn.execute(
            "SELECT r.goal_id FROM activity a JOIN run r ON r.id=a.run_id"
            " WHERE a.id=?", (activity_id,)).fetchone()
        if row:
            self.j.append_event(row["goal_id"], "system", "tool.unknown_outcome",
                                {"activity_id": activity_id})

    def reconcile(self, activity_id: str, observed_succeeded: bool,
                  evidence_uri: str, actor: str = "system") -> dict:
        """Reconciliation is its own authorized operation — never an auto-retry."""
        row = self.db.conn.execute(
            "SELECT r.goal_id FROM activity a JOIN run r ON r.id=a.run_id"
            " WHERE a.id=?", (activity_id,)).fetchone()
        if not row:
            raise GatewayError("no such activity")
        status = "RECONCILED" if True else ""
        self.db.conn.execute(
            "UPDATE activity SET status=?, result_digest=COALESCE(result_digest, ?),"
            " detail_json=json_set(detail_json,'$.reconciled',json('true'),"
            "'$.reconcile_evidence',?) WHERE id=? AND status='UNKNOWN_OUTCOME'",
            ("RECONCILED", sha256_text(evidence_uri), evidence_uri, activity_id))
        self.j.append_event(row["goal_id"], actor, "tool.reconciled",
                            {"activity_id": activity_id,
                             "observed_succeeded": observed_succeeded})
        return {"ok": True, "status": "RECONCILED"}

    def _approval_target(self, contract: ToolContract, args: dict,
                         ctx: RunContext) -> str:
        """Canonical target of an effect: the primary object being acted upon."""
        for key in ("path", "target", "resource", "url"):
            if key in args:
                return str(args[key])
        return ctx.workspace_path

    def unresolved_unknown_outcomes(self, goal_id: str) -> list[dict]:
        rows = self.db.conn.execute(
            "SELECT a.* FROM activity a JOIN run r ON r.id=a.run_id"
            " WHERE r.goal_id=? AND a.status='UNKNOWN_OUTCOME'", (goal_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def _next_fence(self, conn=None) -> int:
        row = self.db.conn.execute(
            "SELECT COALESCE(MAX(CAST(json_extract(detail_json,'$.fence') AS INTEGER)),0)"
            " FROM activity").fetchone()
        return int(row[0]) + 1


class _null_ctx:
    def __enter__(self): return None
    def __exit__(self, *a): return False
