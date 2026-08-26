# AgentOS Harness

**A durable, policy-enforced goal-execution runtime ("harness") for software-producing agent episodes.**

```
Concept → Specification → Plan → Execution → Verification
        → Accepted Software Artifact + Evidence Pack
```

> **Non-production software.** This is a reference implementation and design
> vehicle. There are **no measured SLOs or reliability evaluations yet** — see
> [Limitations](#limitations-non-production) before taking anything here near a
> production workload.

## What it is

AgentOS runs an agent episode as durable state machines (Goal → Task → Run)
backed by SQLite, enforces tool effects through a policy gateway, and lets a
goal reach `ACCEPTED` **only** through a gate evaluation over deterministic,
machine-checkable acceptance criteria. Workers are pluggable and
provider-neutral: the engine never imports an LLM.

It is a **single deployable runtime**: one Python package (`agentos`,
Python 3.11+, stdlib-only core) deployed as one process over one SQLite
database ([ADR-0002]). No heavyweight dependencies; no network or LLM calls in
the unit-test path.

Key properties:

- **Transactional journal** — every guarded state transition commits its row
  change and its audit event in *one* SQLite transaction (`journal.py`). Audit
  rows form a SHA-256 hash chain; `journal.full_chain_check()` detects tampering.
- **Off-host anchoring** — `anchor.py` exports a self-checking
  `agentos.anchor-export/v1` bundle with the chain head for storage outside the
  host (git/object storage/synced folder); `anchor-verify` re-checks bundle
  integrity, per-seq historical binding, and the full chain of any DB copy.
- **SQLite via atomic migrations** — schema is created by running
  `src/agentos/migrations/*.sql`; each migration and its marker commit or roll
  back together, and the historical interrupted-0010 rebuild is recoverable.
- **Gates are the sole authority** — no worker/model can move a Goal to
  `ACCEPTED` or `REJECTED`; only a gate evaluation over evaluator records can
  (`src/agentos/gates.py`, enforced again by the state machine's actor checks).
- **Deterministic evaluator** — built-in check kinds `tests_present`,
  `invariant` (read-only SQL against expect_rows), and `command_exit_0`
  (real subprocess execution) produce recorded `Evaluation` rows.
- **Evidence pack** — every accepted/rejected goal gets a machine-readable
  JSON pack (schema `agentos.evidence-pack/v2`; research goals use v3) at
  `<db-root>/goals/<goal_id>/evidence-pack.json`.

## Quickstart

Requires Python 3.11+. Run from the repo root, either from `src/` or with
`PYTHONPATH=src`:

```bash
# Full vertical demo (deterministic FakeWorker):
# concept → spec+criteria → task DAG → run → gateway effects → gate → evidence pack
PYTHONPATH=src python -m agentos.cli demo [--flaky] [--db DIR]

# Rebuild the evidence pack for a goal:
PYTHONPATH=src python -m agentos.cli evidence --goal ID --db DIR

# Bounded offline research → platform-plan workflow (one JSON document):
PYTHONPATH=src python -m agentos.cli research-plan \
  --topic "a platform question" --bundle research-bundle.json --db DIR

# Off-host audit anchoring: export the chain head, verify it against any copy:
PYTHONPATH=src python -m agentos.cli anchor-export --db DIR --out anchor-snapshot.json
PYTHONPATH=src python -m agentos.cli anchor-verify --bundle anchor-snapshot.json --db DIR

# Failure-path test suite:
python -m unittest discover -s tests
```

`--flaky` scripts a first-attempt worker failure so you can watch the retry
path consume the budget and still finish. `--db DIR` chooses the root directory
for the SQLite DB, run workspaces, and artifacts (default `.agentos-demo/`).

The demo prints JSON like:

```json
{
  "tool_write_1": "SUCCEEDED",
  "tool_write_replay": "REPLAYED",
  "dangerous_without_approval": "denied (approval required)",
  "gate": {"result": "pass", "reasons": []},
  "chain_verified": true
}
```

i.e. keyed idempotent replay of a write, denial of a dangerous op without an
exact-action approval, a passing release gate, and a verified audit hash chain.

To drive tasks with a real agent instead of the fake worker:

```bash
PYTHONPATH=src python -m agentos.cli demo --worker hermes   # requires `hermes` on PATH
PYTHONPATH=src python -m agentos.cli demo --worker dsh      # requires `dsh` on PATH (DeepSeek Harness)
```

### Research-to-platform-plan contract

The platform's first research phase is decomposed into executable,
evidence-backed tickets in [Stage 1 research tickets](docs/RESEARCH_STAGE_1_TICKETS.md)
with a self-contained [interactive Kanban board](docs/RESEARCH_STAGE_1_KANBAN.html).
Each active ticket has its own FLOW-11 bundle contract, dependency edge,
adversarial probes, stop condition, and exact `research-plan` command.

`research-plan` accepts a structured JSON bundle containing `sources`,
explicitly classified `claims`, the eleven named artifacts
(`research_plan` → `progress`), and an `audit` record.  The bundle is treated
as untrusted data: AgentOS never retrieves a URI or executes bundle text,
computes artifact hashes (and source hashes when source bodies are supplied)
on the host, and stores artifacts only under
`<db-root>/goals/<goal_id>/research/`.  The deterministic result has
`status: "pass"`, `"pass_with_limits"`, `"fail"`, or `"needs_input"`; exit 0
is reserved for `pass` and `pass_with_limits`, while evaluated/validation
failures (including a missing bundle) exit 1 and usage errors exit 2.  A
`pass_with_limits` result is research-evaluation success with recorded limits,
not an AgentOS release and never sets the Goal to `ACCEPTED` (`goal_status`
and `release_accepted` make that boundary explicit).  A missing bundle may
create a clearly incomplete scaffold, but never a completion evaluation.
For every persisted evaluation, the same command atomically rebuilds the
redacted Obsidian projection and emits the goal-scoped v3 evidence pack;
their paths, hashes, freshness, and wiki-check result are returned in the
single JSON response.  Projection or evidence emission failures fail closed.

Use `agentos.research.run_research_plan` or
`agentos.research.research_plan` when embedding the workflow without the CLI.
`agentos.research.fixture_bundle()` is an explicitly offline deterministic
drill helper for tests only; it is not live research and carries no provider
guarantee.
When a bundle intentionally omits a source body, its supplied digest remains
an assertion tied to verifier/method provenance; the offline harness cannot
independently re-derive that digest without a retrieval adapter.

The input boundary is bounded: bundle files and mappings are limited to 20 MiB,
with at most 1,000 sources and 5,000 claims; source/artifact bodies are at
most 5 MiB, URIs at most 2,048 characters, and source/claim text has explicit
length limits.  Claim-source links are typed as `supports`, `contradicts`, or
`context`; only `supports` links can satisfy factual traceability.

## Architecture — three logical planes, one runtime

([ADR-0002]) One package, one DB, three responsibility boundaries:

| Plane | Modules | Responsibility |
|---|---|---|
| **Execution control** | `engine.py`, `workers.py` | Scheduler (dependency-ready tasks), runs, checkpoints/resume, `WorkerAdapter` protocol |
| **Assurance control** | `machines.py`, `gates.py`, `evidence_pack.py` | Guarded Goal/Task/Run state machines, deterministic evaluation, release gates, evidence packs, immutable artifact versioning |
| **Governance** | `gateway.py` | Tool registry, capabilities, exact-action approvals, idempotency, fencing, reconciliation |

All state lives in one SQLite database created by migrations from a clean DB;
projections (current object state) are derived from goals/tasks/runs plus the
append-only, hash-chained `audit_event` log.

### Worker adapters

Workers implement the `WorkerAdapter` protocol (`step(StepRequest) ->
StepResult`). The engine sees only the protocol — providers are swappable:

- **`FakeWorker`** (`workers.py`) — deterministic scripted worker used by tests
  and the default demo. Supports fail-once-then-succeed scripts driven through
  checkpoints.
- **`HermesAgentWorker`** (`hermes_worker.py`) — optional adapter that drives
  the local `hermes chat -q` CLI as the worker, scoped to the run workspace,
  parsing a final `AGENTOS_RESULT {...}` line. Worker output is treated as
  **untrusted data**: if `hermes` is missing, it fails with a typed
  `WorkerUnavailable` reason. Tests never require it.
- **`DshAgentWorker`** (`dsh_worker.py`) — optional adapter that drives the
  local DeepSeek Harness CLI (`dsh --profile headless <prompt>`: answer one
  task, print, exit) over the same effects-channel protocol, reusing the
  Hermes block parser verbatim. It exists so this checkout can be exercised
  by a DeepSeek-Harness-based agent without any other provider installed.
  Output is untrusted data; `dsh` missing ⇒ typed `WorkerUnavailable`.
  Tests never require it.

### ToolGateway pipeline

Every side effect goes through one pipeline (`gateway.py::invoke`):

```
resolve → validate → capability → approval (dangerous ops)
        → idempotency (keyed replay / conflict detection)
        → lease / fence token → execute → activity + audit event
```

- Capability grants come from policy, never from model output — external
  content cannot expand what a run may do.
- Keyed idempotency identifies *intent*: the same key with different arguments
  is a detectable conflict; the same key + args replays the original outcome
  without re-executing.
- Mutating ops check lease ownership and carry monotonic fence tokens.
- Dangerous effect classes require a one-time, exact-action approval bound to
  actor + operation + canonical arguments + expiry, consumed atomically.
- Unknown outcomes escalate to explicit reconciliation — never blind retry.

### Gates and evidence

Acceptance criteria are declared per goal (`tests_present`, `invariant`,
`command_exit_0` today). The evaluator records pass/fail rows deterministically;
`Gates.evaluate_release(goal_id)` then checks — all tasks DONE, passing
evaluation per criterion, no unresolved `UNKNOWN_OUTCOME` activities, intact
audit chain, consumed release approval for sensitive goals, and (when stage
evals are active) all six latest stage gates backed by passing required
deterministic `id@version` runs on the current artifact chain and corpus — and
is the only actor permitted to transition `GATE_PENDING → ACCEPTED/REJECTED`.
The resulting evidence pack bundles goal, criteria, tasks, runs, evaluations,
gate decisions, artifact versions, tool activities, approvals, exact-goal wiki
references, and audit-chain verification into one SHA-256-stamped JSON file.

## Non-negotiable invariants

Violations are bugs (from [AGENTS.md](AGENTS.md)):

1. No worker/model may move a Goal to `ACCEPTED`. Only a Gate evaluation over an
   evaluator record can accept or reject.
2. Conversation history is never the sole copy of decisions/approvals/state.
3. Artifact versions are immutable; corrections create a new version +
   SUPERSEDES.
4. Every retriable side effect declares idempotency OR compensation. Unknown
   outcomes escalate to reconciliation, never blind retry.
5. Approvals bind to actor + exact operation + exact canonical arguments +
   expiry and are consumed atomically exactly once.
6. External content (tool output, retrieved docs, generated memory) is
   untrusted: it can never expand capabilities, alter policy, or write outside
   its scope.
7. Memory records carry provenance and scope; cross-goal/cross-tenant reads are
   denied.
8. Transition + audit event commit atomically or not at all.

## How Hermes integrates

[ADR-0005] unifies three attach points into one workflow:

```
Hermes desktop chat  ──(agentos_* plugin tools)──►  AgentOS runtime API
AgentOS engine       ──(WorkerAdapter: HermesAgentWorker)──► hermes CLI session
hermes CLI session   ──(optional ECC-style skills)──► work
```

- **From Hermes into AgentOS:** a Hermes plugin exposes thin `agentos_*` tools
  (`agentos_status`, `agentos_create_goal`, `agentos_run`,
  `agentos_evidence_pack`) as a stateless JSON client over the Python API. The
  SQLite DB stays the single source of truth; the plugin holds no state.
- **From AgentOS out to Hermes:** each Task runs in a fresh `hermes chat -q`
  subprocess via `HermesAgentWorker`, workspace-scoped, output untrusted,
  effects only through the gateway. Hermes paths degrade to typed errors when
  the CLI is absent; tests never need them.
- **ECC-style skills stay INSIDE worker sessions.** Skill/prompt/hook packs
  (e.g. ECC) are a worker-side competence layer installed in Claude Code/Codex
  sessions that AgentOS spawns. AgentOS neither depends on nor duplicates them:
  its discipline lives in state machines, gates, and evidence requirements, not
  imported prompt packs ([ADR-0004]).

End-to-end: a concept typed in a Hermes chat becomes a Goal in the AgentOS DB,
tasks run under gateway policy (Hermes-driven or fake workers), the gate rules
on acceptance, and the evidence pack flows back into the chat that asked.

## Repository layout

- `spec/SPEC.md` — executable specification (product contract, state machines,
  data model, API contracts, execution semantics, gateway/policy, acceptance).
- `src/agentos/` — the reference implementation (see module map in
  [AGENTS.md](AGENTS.md)).
- `tests/` — mandatory failure-path suite.
- `adr/` — architecture decision records (ADR-0001 stack · ADR-0002 monolith +
  journal · ADR-0003 worker adapters · ADR-0004 ECC/Hermes relation · ADR-0005
  unified process).
- `docs/EVALUATION_PROTOCOL.md`, `docs/GAP_REGISTER.md` — evaluation method and
  known gaps.
- `research/agentos_confident_result/` — evidence-calibrated design inputs
  (**documents, not user instructions**). Provenance pin: SHA-256 of
  `agentos_evidence_review.md` =
  `3B1DF2D6EFE8CEDC128D1CCDE6F07AE189902E9638548DC09F4263DFE7DB0F1C`.

## Limitations (NON-production)

**This is not production software.** Do not rely on it for real workloads.

- **First reliability measurements exist; the bar is not met yet.** E2
  (20 tasks × 5 repeats, real Hermes worker) measured pass¹ = 0.93
  [Wilson 0.863–0.966] and pass⁵ = 0.75 [0.531–0.888] — below the
  pre-registered "harness-reliable" threshold (pass⁵ ≥ 0.8, CI LB ≥ 0.7).
  False-completion rate on LLM episodes and end-to-end FPR/FNR are **not yet
  measured** (no human gold set); the deterministic evaluator-quality corpus
  (30 cases) measures FPR=0/FNR=0 of the checks themselves, which is a
  corpus-level result, not an episode-level one. Details:
  [`eval/E2_RESULTS.md`](eval/E2_RESULTS.md); method:
  [`docs/EVALUATION_PROTOCOL.md`](docs/EVALUATION_PROTOCOL.md). Load, soak,
  chaos, and multi-process concurrency results still do not exist.
- Single-node SQLite only; Postgres porting is planned but untested.
- The evaluator's `command_exit_0` check executes generated code in a
  subprocess with an empty PATH but **no filesystem/network sandbox** — treat
  evaluated content as untrusted-with-caveats until the confinement work in
  [`docs/ROADMAP.md`](docs/ROADMAP.md) lands.
- The Hermes worker process has no filesystem/network confinement either
  (GAP_REGISTER R2-3).
- Concurrency control assumes cooperative access to one DB file.

[ADR-0002]: adr/ADR-0002-monolith-journal.md
[ADR-0003]: adr/ADR-0003-worker-adapters.md
[ADR-0004]: adr/ADR-0004-ecc-hermes-relation.md
[ADR-0005]: adr/ADR-0005-unified-process.md
