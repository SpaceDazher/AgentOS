# AgentOS Executable Specification v1.0

Status: **implementation-ready**. Each section names the owning module so code and
spec can be diffed mentally. Where this document and code disagree, either fix code
or amend spec in the same change (see AGENTS.md).

Design inputs: `research/agentos_confident_result/*` (claims C01–C24; adopted /
provisional / deferred decisions recorded there are binding defaults here).

---

## 1. Product contract

**System statement.** AgentOS turns a user's *Concept* into an *Accepted Software
Artifact* through protocol-defined transitions over authoritative versioned state.
Deterministic code owns transitions, authority, budgets and gates; probabilistic
workers (LLM agents) operate only inside that envelope.

| Role | Who | Powers |
|---|---|---|
| **Requester** | human user | creates Goal from Concept, sets constraints/budget, approves/rejects at gates |
| **Approver** | requester or policy-designated actor | consumes exact-action approvals (one-time, bound) |
| **Worker** | `WorkerAdapter` impl (FakeWorker, HermesAgentWorker) | executes Tasks inside isolated workspace; requests tool ops via gateway |
| **Evaluator** | deterministic code (`evaluator.py`) | runs checks/tests, produces Evaluation records; never accepts |
| **Gate** | predicate over state+evidence+policy (`gates.py`) | moves Goal ACCEPTED/REJECTED; sole path to terminal acceptance |

**Input: Concept.** Free text + optional structured constraints: required paths,
acceptance commands (e.g. test suite), budget (max steps/tool calls), deadline,
risk tier (`normal` | `sensitive`). Minimal viable Concept = goal text + ≥1
machine-checkable acceptance criterion.

**Output: software artifact.** A set of immutable ArtifactVersions rooted at the
Goal (specification, plan, code files, test report), plus a machine-readable
Evidence Pack (JSON) covering every transition, evaluation, approval and effect.

**In MVP (in scope):** single-goal episodes; sequential-or-bounded-parallel task
DAG; file-system workspace effects; local command tools; deterministic evaluator;
human gate at release; crash/resume from checkpoint; idempotent retry of declared
idempotent ops.

**Out of scope (MVP):** external SaaS mutations requiring distributed reconciliation;
multi-tenant production authn (single-user local trust boundary); automatic causal
inference; multi-agent topologies; graph DB; decimal confidence (see research §"не
следует превращать в догму").

**Guarantees.** (a) no false ACCEPTED without a passing evaluator record satisfying
the gate predicate; (b) transition+audit atomicity; (c) replay-safe retries only for
declared-idempotent operations; (d) approvals cannot be replayed, extended or
transferred; (e) untrusted content cannot escalate authority; (f) failed attempts
never destroy prior artifact versions.

**Residual risk (explicit).** Evaluator FPR/FNR is unknown until measured
(EVALUATION_PROTOCOL.md); SQLite durability is host-disk-bound; worker prompt
injection can waste budget (denial-of-service) though not gain authority; evidence
pack tamper-evidence relies on filesystem ACLs in MVP.

---

## 2. Lifecycle & state machines

Owner: `machines.py`. Every transition below is executed via
`journal.transition(...)` which enforces precondition, authority and atomic
audit-event emission. Terminal states: `ACCEPTED`, `REJECTED`, `CANCELLED`,
`FAILED` (Run-level), `SUPERSEDED` (artifact-level).

### Goal
```
DRAFT → ACTIVE → GATE_PENDING → ACCEPTED
                      ├──→ REJECTED → ACTIVE (revision loop, new ArtifactVersion)
                      └──→ ESCALATED → ACTIVE (after human resolution)
ACTIVE/DRAFT/GATE_PENDING/REJECTED → CANCELLED
```
Transitions:
- `create_goal` (→DRAFT): auth=requester; emits `goal.created`.
- `activate` (DRAFT→ACTIVE): pre: ≥1 Specification ArtifactVersion exists AND ≥1
  machine-checkable acceptance criterion; emits `goal.activated`.
- `submit_to_gate` (ACTIVE→GATE_PENDING): pre: all tasks DONE AND ≥1 Evaluation
  record EXISTS per acceptance criterion (pass or fail — passing is enforced by
  the Gate at release, so a failing evaluation reaches the gate and is rejected
  there); emits `goal.gate_pending`.
- `gate_accept` (GATE_PENDING→ACCEPTED): authority=**Gate only** (workers and CLI
  short-circuits are denied by `machines.assert_actor`); emits `goal.accepted`;
  freezes Evidence Pack pointer.
- `gate_reject` (GATE_PENDING→REJECTED): authority=Gate; requires gap description;
  emits `goal.rejected`; revision loop creates new spec version (SUPERSEDES).
- `escalate`: authority=Gate/policy; emits `goal.escalated`.
- `cancel`: authority=requester; emits `goal.cancelled`.

### Task
```
PENDING → READY → RUNNING → DONE
                    ├──→ FAILED (retryable within budget → READY)
                    └──→ BLOCKED (missing dependency/input) → READY
PENDING/READY/BLOCKED → CANCELLED   (cascade from Goal cancel)
```
`schedule` PENDING→READY: pre: all `depends_on` tasks DONE; emits `task.ready`.
`start` READY→RUNNING: creates Run, grants lease to worker; emits `task.started`.
`complete` RUNNING→DONE: pre: Run produced declared outputs + checkpoint;
emits `task.completed`. `fail` RUNNING→FAILED: records failure class; auto-
transition FAILED→READY follows while `attempts <= retry_budget` (`attempts+=1`;
the retry-scheduling event carries `retry_scheduled: true`), otherwise terminal
FAILED (`retries_exhausted: true`). Idempotency: transitions
carry client-supplied `transition_key`; duplicate keys are no-ops returning the
original event.

### Run
```
PLANNED → RUNNING → COMPLETED
             ├──→ FAILED(worker|budget|deadline|worker_unavailable)
             ├──→ PAUSED ⇄ RUNNING
             └──→ CANCELLED
```
`resume` on FAILED(recoverable): only from latest consistent Checkpoint; new Run
row references `resumed_from_run_id` (immutable lineage).

### ArtifactVersion
```
DRAFT → CURRENT → SUPERSEDED (by newer version, never deleted)
CURRENT/ DRAFT → WITHDRAWN (only if never depended upon)
```
Immutable content: `(goal_id, kind, version)` unique; content addressed by SHA-256.
Any correction = new row + relation `SUPERSEDES(new→old)`.

### Evaluation
`PLANNED → PASSED | FAILED` (terminal both ways; re-evaluation = new Evaluation row).
Pre: subject ArtifactVersion frozen; method/config versions recorded.

### Gate
`OPEN → PASSED | FAILED | ESCALATED`.

### Approval
`GRANTED → CONSUMED | EXPIRED | REVOKED`. Exactly-once consumption is enforced
by ONE conditional UPDATE (`gateway.consume_approval`): GRANTED→CONSUMED only
where nonce, actor, operation, tool_identity (name@version), args_canonical_json,
target and expiry match in that same WHERE clause; any mismatch ⇒ deny (replay /
expired / binding mismatch). The bound target is the canonical action target
derived from args (`gateway._approval_target`: first of path|target|resource|url,
else the run workspace).

### Tool operation (Activity)
`REQUESTED → AUTHORIZED → EXECUTING → SUCCEEDED | FAILED(known) | UNKNOWN_OUTCOME`
UNKNOWN_OUTCOME → RECONCILED{SUCCEEDED,FAILED} (reconciliation is a separate
authorized operation, never an auto-retry).

### Checkpoint
`CREATED` (append-only; restore = read-only reference, no state change).

---

## 3. Canonical data model

Owner: `db.py` + migrations. All tables have `created_at`; ids are prefixed ULIDs
(`ids.py`). Invariants listed per table are enforced in code and (where cheap) SQL.

- **goal**: id, concept_text, constraints_json, risk_tier, budget_json, status.
- **artifact_version**: id, goal_id, kind (concept|specification|plan|code|test_report|
  evidence_pack|skill_seed), version int (per goal+kind), content_sha256, storage_path,
  status, superseded_by_id NULL. *Invariant:* rows UPDATE-proof — only status may move
  CURRENT→SUPERSEDED/WITHDRAWN; content columns never mutate (trigger-checked).
- **claim**: id, goal_id, text, status (asserted|supported|challenged|defeated),
  validation_plan_json.
- **evidence**: id, goal_id, kind (source|observation|test_result|attestation|world_state),
  uri/storage_path, sha256, freshness_at, provenance_json.
- **decision**: id, goal_id, question, selected_alternative, rationale, supersedes_id.
- **task**: id, goal_id, title, depends_on_json, inputs_json, expected_outputs_json,
  definition_of_done, risk_tier, retry_budget, attempts, status, owner_run_id NULL.
- **run**: id, task_id, worker_type, config_versions_json (model/harness/tools/env),
  lease_owner, lease_expires_at, workspace_path, status, terminal_reason,
  resumed_from_run_id NULL.
- **activity**: id, run_id, op_name, args_canonical_json (sorted-key canonical form),
  effect_class (read|write_local|write_external|dangerous), status, result_digest.
- **world_observation**: id, goal_id, subject, value_json, observed_at, source_evidence_id.
- **acceptance_criteria**: id, goal_id, criterion_id UNIQUE per goal, kind
  (tests_present|invariant|command_exit_0), params_json (migration
  0002_criteria.sql); rewritten by `refine_spec` on each new specification version.
- **evaluation**: id, goal_id, subject_artifact_id, criterion_id, method, method_version,
  config_json, result (pass|fail), detail_json.
- **gate**: id, goal_id, predicate_name, predicate_version, input_fingerprint,
  result, rationale.
- **approval**: id, goal_id, actor, operation, tool_identity, args_canonical_json,
  target, policy_version, limits_json, expires_at, nonce UNIQUE, status.
  *Invariant:* one-time consumption; binding fields immutable after GRANTED.
- **checkpoint**: id, run_id, seq, payload_path, sha256, work_completed_json,
  work_in_progress_json, next_action_json.
- **tool_contract**: name, version, input_schema_json, output_schema_json, server_identity,
  required_capability, side_effects, sensitivity, idempotency (none|keyed|natural),
  retry_policy_json, compensation TEXT NULL, preconditions_json, postconditions_json,
  audit_level. Registry rows are append-only (new version = new row).
- **memory_record**: id, scope_goal_id, kind, content, source_uri, trust (ordinal),
  created_at, ttl_until NULL, invalidated_by_id NULL. *Invariant:* reads filtered by
  scope_goal_id — cross-scope read raises `MemoryScopeViolation`.
- **relation_assertion**: id, src_type/src_id, rel (WAS_GENERATED_BY|USED|WAS_DERIVED_FROM|
  WAS_ASSOCIATED_WITH|IMPLEMENTS|VALIDATES|DEPENDS_ON|SUPERSEDES|SUPPORTS|CHALLENGES…),
  dst_type/dst_id, asserter, status, evidence_ids_json. No transitivity assumed.
- **audit_event** (append-only): seq AUTOINCREMENT, ts, goal_id, actor, event_type,
  payload_json, prev_event_sha256 → hash-chained; `journal.transition` writes object
  mutation + audit_event in ONE sqlite transaction (test T14).
- **idempotency_key**: key_hash UNIQUE (sha256 of key+op+canonical_args),
  first_seen_run_id, outcome_digest NULL. *Invariant:* same key+different canonical args
  → `IdempotencyConflict` (rejected, not retried) — test T05b.

---

## 4. API & event contracts

Owner: package-level functions (`engine.py`, `gateway.py`, thin JSON CLI `cli.py`).
Every mutating call returns the emitted audit events. CLI verbs map 1:1.

| Command | Signature (abridged) | Notes |
|---|---|---|
| create_goal | `create_goal(concept_text, constraints, budget, actor)` | → Goal(DRAFT) + concept ArtifactVersion |
| refine_contract | `refine_spec(goal_id, spec_text, criteria[], actor)` | new specification ArtifactVersion (SUPERSEDES prior) |
| approve_spec | `approve_spec(goal_id, actor)` | activates goal |
| plan_tasks | `plan_tasks(goal_id, tasks[], actor)` | validates DAG acyclicity; creates Task rows |
| start_task / complete / fail / cancel | engine | lease + checkpoint semantics §5 |
| pause_run / resume_run / cancel_run | engine | resume only from consistent checkpoint |
| invoke_tool | `gateway.invoke(run_id, contract_name, args, idempotency_key, approval_nonce?)` | full §6 pipeline |
| record_checkpoint | engine | append-only |
| run_evaluation | `evaluator.run(goal_id, criterion_id)` | deterministic |
| submit_gate | `engine.submit_to_gate(goal_id)` then `gates.evaluate_release(goal_id)` | submission needs ≥1 Evaluation EXISTS per criterion (pass or fail); Gate is sole ACCEPTED/REJECTED authority |
| grant/consume/revoke_approval | gateway | exact-action binding |
| get_evidence_pack | `evidence_pack.build(goal_id)` | JSON artifact + file |

**Atomicity contract:** accepted state transitions and their audit event commit in
the same transaction; `get_evidence_pack` fails loudly if any ACCEPTED goal lacks its
`goal.accepted` event (chain integrity check walks `prev_event_sha256`).

---

## 5. Execution semantics

Owner: `engine.py`.

1. **Dependency-ready scheduling:** loop picks tasks in PENDING whose deps are all
   DONE → READY; deterministic order (topo rank, then id) for reproducibility.
2. **Ownership:** one active Run per Task (lease row on task.owner_run_id);
   second starter gets `LeaseHeldError`.
3. **Conditional leases:** lease has `expires_at`; heartbeats extend. Mutating
   gateway ops check `lease_valid && lease_owner == caller`; expired lease → op
   denied with `StaleOwnerError`. Fencing applies ONLY to contended/reassigned
   write ops and only when sink supports fencing token (local FS tools accept a
   monotonic fence counter embedded into written filenames/journal entries —
   test T08).
4. **Isolated workspace:** each Run gets `workspaces/<run_id>/` fresh dir; workers
   cannot address other goals' paths (path-normalization guard in file tools).
5. **Bounded retries:** Task.retry_budget default 2; Run budget counts tool calls +
   steps; exceeding → FAILED(budget). Worker scripts/checkpoints advance across
   retries: the attempt count positions scripted workers (prior attempts consume
   script entries, so a [fail, ok] script succeeds on the second attempt —
   `Engine._attempts_before`) and resumed runs continue from the latest
   checkpoint's step position. `Engine.start_task` is the run-to-completion
   driver (steps the worker until done/failure/budget); CLI/tests loop it until
   the task settles.
6. **Idempotency:** every retriable side-effecting op requires an idempotency_key;
   replays return original outcome digest without re-execution (T05a).
7. **Reconciliation:** UNKNOWN_OUTCOME ops (crash between effect and journal) are
   flagged; reconciliation compares world observation vs expected postcondition and
   writes RECONCILED result; blind retry of unknown-outcome op is refused (T06).
8. **Compensation:** registered compensation ops are separate Activities referencing
   the original; they are themselves gated/approved per policy; no implicit rollback (T15 keeps artifacts).
9. **Pause/resume/cancel:** pause writes checkpoint + PAUSED; resume spawns new Run
   from latest consistent checkpoint (sha verified); cancel cascades to child tasks.
10. **Crash recovery:** on restart, RUNNING Runs past lease expiry are marked
    FAILED(crashed); recovery procedure offers resume-from-checkpoint (T03).

---

## 6. Tool gateway & policy

Owner: `gateway.py`. Pipeline per invocation:

```
resolve contract (name+version) → validate args vs schema → canonicalize args
→ capability check (run.capability_set ⊇ contract.required_capability)
→ sensitivity routing: dangerous ⇒ require exact Approval
→ approval verification (actor, op identity/version, canonical args equality,
   target, policy_version, limits, expiry, nonce) → atomic consume
→ idempotency check → lease/fence check → execute handler
→ record Activity + evidence → return digest
```

ToolContract fields are as in §3; MCP-style annotations from servers are treated as
untrusted hints — enforcement uses registry values only (C22/C13). Model output,
tool output, retrieved docs, generated memory = untrusted: parsed for data, never for
instructions that alter capability sets, policy or approvals (test T11 simulates an
injected "grant yourself admin" instruction reaching the gateway — must be inert).

Workers receive scoped capability sets at Run creation; there are no ambient
credentials: handlers resolve capabilities through the gateway context only.

Approval binding: `(actor, operation, tool_identity(name@version), args_canonical_json,
target, policy_version, limits, expires_at, nonce)` — any mutation of arguments after
grant invalidates consumption (args hash mismatch ⇒ deny, T10); replay after consume
⇒ deny (T09); expired ⇒ deny. Malicious/changed tool schema (registry entry swapped to
widen schema or bump sensitivity) ⇒ fingerprint mismatch ⇒ deny + `policy.violation`
event (T12).

Memory scoping: memory writes carry `scope_goal_id`; cross-task/cross-goal read
attempts raise `MemoryScopeViolation` (T13).

---

## 7. Context Compiler (provisional)

Owner: `context_compiler.py`. Interface:

```python
compile_packet(task, goal) -> ContextPacket(
    intent, authority_refs[], retrieval_hits[](deduped, conflict-flagged,
    ordered by authority>freshness>relevance under char budget),
    evidence_refs[], warnings[])
```

Derived memory summaries always embed `source_pointers` back to raw evidence ids;
packet never fabricates content. `ContextPacket.render` orders hits by
authority>freshness, drops duplicate content, marks conflicting duplicates
(`[conflict-flagged]`) and truncates at the char budget (sets packet.truncated +
a warning). Budget: max_chars per packet (default 6000).
MVP retrieval sources: goal artifacts, prior checkpoints, scoped MemoryRecords —
memory hits are already scope-filtered at SQL level (`WHERE scope_goal_id = ?`).

---

## 8. Acceptance semantics

```
AcceptedEpisodeSuccess := GatePass(
      GoalStateReached ∧ InvariantsHold ∧ ProcessConstraintsHold ∧ EvidenceValid)
```

Evaluator-assessed acceptance, never absolute proof. Gate `release_predicate_v1`
requires: all tasks DONE; ≥1 PASSED Evaluation per acceptance criterion, each against
the CURRENT artifact chain; no unresolved UNKNOWN_OUTCOME activities; audit chain
intact; budget respected; (risk_tier=sensitive) ≥1 consumed human Approval for release.
Failure ⇒ REJECTED + gap tasks proposed, never silent re-entry into ACTIVE.

Evaluation protocol (sampling frame, repeats pass^k, CI, budgets, evaluator FPR/FNR):
see `docs/EVALUATION_PROTOCOL.md` — fixed before comparisons, not after.

---

## 9. Stage evaluations, wiki projection and autoresearch

### 9.1 Stage Evaluation Framework (module `stage_evals.py`, checks `stage_checks.py`)

Versioned entities (append-only; UPDATE/DELETE refused by triggers — migration
`0007_stage_evals.sql`):

- `eval_definition(id, version, stage, kind, metric, direction, threshold,
  timeout_s, corpus_version, independence_class, required, prompt_version,
  rubric_version)` — corrections create new versions.
- `eval_case(id, corpus_version, stage, label, set_class ∈ {gold,
  near_miss, alternative_correct, adversarial, incomplete}, input_ref,
  expected_outcome, provenance)`.
- `eval_run(...)` — outcome, metrics, env, seed, logs hash, failure class;
  `llm_judge` runs are inadmissible without model_id + prompt_version +
  rubric_version.
- `stage_gate(stage, required_eval_ids_json, decision, rationale, authority,
  goal_id, artifact_chain_hash, corpus_version)`. Required refs are persisted
  as immutable `id@version` pins.

Authority (ADR-0006): deterministic checks may block a stage gate; llm_judge
results are advisory and never satisfy a required criterion. A required
definition with zero recorded runs FAILS the gate (no silent skips). Release
requires every pinned definition to remain latest and to have a passing run for
the same goal, current artifact chain and bound corpus; bare, stale, malformed,
wrong-stage, advisory and wrong-corpus references fail closed.

Six stages covered by 24 deterministic checks (`stage_checks.CHECKS`):
concept ×4, specification ×4, plan ×4, execution ×4, verification ×4,
post_episode ×4. Frozen corpora (`evals/fixtures/`, manifest
`evals/corpus_manifest.json` with SHA-256 per case): 48 stage cases (per
stage: 2 gold / 2 incomplete / 2 near_miss / 1 alternative_correct /
1 adversarial) + 30 evaluator-quality cases (10 gold / 10 near_miss /
10 alternative_correct). Measured on the frozen corpora: FPR = 0, FNR = 0.

### 9.2 Obsidian Knowledge Vault (module `wiki.py`; ADR-0007)

`wiki/` is a deterministic projection of canonical SQLite state:
`wiki-build` regenerates `_generated/` notes (byte-identical on unchanged
state, without history caps, using a same-volume staged swap with rollback);
`wiki-check` validates broken links, duplicate ids/keys, frontmatter shape,
canonical dangling refs and unexpected orphans; `wiki-status`
reports projection vs canonical counts. The wiki is never authoritative;
human-authored notes live in human-owned folders and are imported explicitly
with provenance; secrets/raw provider transcripts never enter the vault.
Goal evidence packs include only note hashes whose frontmatter has the exact
same canonical `goal_id`; the global Home index is never a goal-pack reference.

### 9.3 Harness Autoresearch (module `autoresearch.py`; ADR-0008)

Campaign = immutable `CampaignManifest` (baseline ref, frozen eval/corpus
hashes, mutable scope, budget, seeds, primary metric, hard constraints).
Per experiment: one hypothesis → candidate in an isolated worktree →
candidate apply command in a stripped-environment subprocess (in-process
callbacks are drill-only) → identical dev evals at fixed seeds → separate
holdout/security gate →
decision KEEP / DISCARD / RETEST / CRASH / QUARANTINED recorded durably in
`experiment` (+ evidence pack + wiki note). KEEP requires improvement above
the noise floor, no hard regression, unchanged frozen hashes, constraints
intact; complexity penalty breaks statistical ties toward DISCARD. Stop
rules: budget exhausted, 3 consecutive CRASHes, any QUARANTINED (frozen-hash
change or security violation), ambiguous measurement. Provider failures are
CRASH-classed and never counted as capability signal.

The stripped environment and isolated worktree are not a filesystem/network
sandbox. Kernel-level confinement remains an explicit open GAP_REGISTER item.

## 10. Consistency log

2026-08-22 — spec/code sync (sections not renumbered; claims verified against
`src/agentos/`):
- §2 Task: `fail` retry condition stated as `attempts <= retry_budget`; the auto
  FAILED→READY transition carries `retry_scheduled: true` in its audit event
  (there is no separate `task.retry_scheduled` event type), exhausted retries are
  terminal FAILED (`retries_exhausted: true`) — `engine._task_fail_or_retry`.
- §2 Approval: consumption documented as ONE conditional UPDATE comparing
  nonce/actor/op/tool_identity(name@version)/canonical args/target/expiry;
  target binds to the canonical action target derived from args
  (path|target|resource|url keys) — `gateway._approval_target`.
- §2/§4 Gate submission: `submit_to_gate` precondition corrected to "≥1
  Evaluation EXISTS per acceptance criterion (pass or fail)"; passing is enforced
  by the GATE, letting a failing evaluation reach the gate and be REJECTED there.
- §3 Data model: added `acceptance_criteria` table (migration 0002_criteria.sql),
  rewritten by `refine_spec` per specification version.
- §5 Execution: noted that worker scripts/checkpoints advance across retries
  (attempt count positions scripted workers) and that `Engine.start_task` is the
  run-to-completion driver used by CLI/tests.
- §7 Context Compiler: documented `render()` dedupe/conflict-marking/truncation
  behavior and SQL-level memory scope filtering (`scope_goal_id`).
