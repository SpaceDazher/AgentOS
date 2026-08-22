# Evidence-calibrated AgentOS architecture draft

## Corrected design thesis

AgentOS should be a durable, policy-enforced goal-execution runtime in which versioned artifacts and observable world state coordinate bounded probabilistic workers. Deterministic code owns invariants, authorization, state transitions, budgets, retries, and gates. An LLM chooses or proposes steps only where the path cannot be fixed in advance. A human resolves high-impact ambiguity and authorizes exceptional effects.

This is a hybrid, not a fully deterministic pipeline. It also corrects the slogan “state coordinates agents”: state is the shared substrate, while the scheduler and policy engine perform coordination.

## Logical architecture

```text
User / external requester
          |
          v
Goal + success contract
          |
  +-------+---------------------------+
  |                                   |
  v                                   v
Execution control               Assurance control
- lifecycle/state machine       +- artifacts and versions
- task DAG and scheduler        +- claims/evidence/decisions
- leases and checkpoints        +- requirements/evaluations
- run/workspace manager         +- gates and stale marking
- retry/compensation            +- world-state verification
  |                                   |
  +---------------+-------------------+
                  v
        Policy and governance
        +- capabilities / tool policy
        +- scoped approvals
        +- trust / provenance policy
        +- cost and escalation budgets
                  |
                  v
        Disposable agent workers
                  |
                  v
            Tool gateway
                  |
                  v
    Isolated workspace / external world

Cross-cutting: append-only events, trace correlation, identity/versioning,
context compiler, memory retrieval, and telemetry.
```

The three planes are interface boundaries, not necessarily separate services. An MVP can implement them in one deployable system and one transactional database.

## Minimal canonical model

The initial handoff lists more than 20 top-level object kinds. The MVP can reduce them without losing semantics:

| Canonical object | Purpose |
|---|---|
| `Goal` | Intent, measurable success state, constraints, budget, risk, lifecycle status. |
| `ArtifactVersion` | Immutable version of requirements, specification, architecture, plan, code, test, report, or other work product. |
| `Claim` | Addressable proposition with epistemic status, support, counterevidence, freshness, and validation plan. |
| `Evidence` | Source, observation, test result, attestation, or world-state measurement, with provenance. |
| `Decision` | Question, alternatives, criteria/assessments, selection, rationale, consequences, and supersession. |
| `Task` | Bounded unit of work with dependencies, ownership, inputs, expected outputs, risk, and definition of done. |
| `Run` | One worker attempt, including model/config/tool versions, lease, budget, workspace, and terminal reason. |
| `Activity` | Tool call, evaluation, state mutation, or other execution step. |
| `WorldObservation` | Versioned measurement of external state used to validate success or detect drift. |
| `Evaluation` | Executed check with subject, method/configuration, result, evidence, and reproducibility metadata. |
| `Gate` | Machine-readable predicate over state/evidence/policy that yields pass, fail, or escalate. |
| `Approval` | Scoped authorization for a concrete operation/resource/arguments/version, actor, expiry, and use status. |
| `Checkpoint` | Consistent recoverable snapshot plus completed/in-progress/blocked work and next action. |
| `ToolContract` | Input/output schema, capabilities, side effects, trust boundary, idempotency, retry, rollback, and audit policy. |
| `MemoryRecord` | Scoped, provenance-bearing retrievable record with type, freshness/TTL, trust, and invalidation rules. |
| `RelationAssertion` | Typed, versioned, attributable edge with its own status and supporting evidence. |

`Requirement`, `Specification`, `Architecture`, `ADR`, `Plan`, `Skill`, and similar items can initially be typed `ArtifactVersion` records. Promote one to a dedicated table only when it has distinct invariants or query volume.

## Provenance kernel

Use a single canonical typed relation model and derive Artifact, Evidence, Execution, and Decision projections. Four independent physical graphs would duplicate shared identities and create consistency risk.

Base provenance relations follow W3C PROV semantics:

```text
WAS_GENERATED_BY(Entity -> Activity)
USED(Activity -> Entity)
WAS_DERIVED_FROM(new Entity -> prior Entity)
WAS_ASSOCIATED_WITH(Activity -> Agent)
WAS_INFORMED_BY(downstream Activity -> upstream Activity)
```

AgentOS relations add domain semantics:

```text
IMPLEMENTS(work product/activity -> Requirement)
VALIDATES(TestResult/Evidence -> Requirement|Claim)
DEPENDS_ON(dependent -> prerequisite)
SUPERSEDES(new -> old)
SUPPORTS(Evidence|Claim -> Claim)
CHALLENGES(Evidence|Claim -> Claim)
CONTEXT_FOR(context -> Claim|Decision|Assertion)
ADDRESSES(Decision -> Question)
CONSIDERS(Decision -> Alternative)
SELECTS(Decision -> Alternative)
JUSTIFIED_BY(Decision -> Claim|CriterionAssessment)
HAS_CONSEQUENCE(Decision -> Consequence)
```

Every relation has an ID, schema version, source and target, asserter, time, source reference, status, qualifiers, and evidence references. `SUPPORTED_BY` is an asserted relationship, not proof. `CAUSED` should not be a generic edge: represent causality as a claim with method and evidence. `INVALIDATED_BY` should not mean “counterevidence” because W3C PROV uses invalidation for an entity ceasing to exist or be usable. Use `CHALLENGES` or a defeated assertion. No relation is transitive by default.

## Execution semantics

1. A goal enters only with an explicit success contract and constraints.
2. The harness creates or updates versioned artifacts and derives acceptance evaluations before risky implementation begins.
3. The scheduler releases only dependency-ready tasks.
4. A mutating task has one active owner and an expiring lease. Parallel read-only work can be less restrictive.
5. Each run receives compiled context, a capability set, tool contracts, an isolated workspace, a budget, and stop conditions.
6. Every mutation goes through the tool gateway with an operation ID and recorded effect class.
7. Meaningful units end at consistent checkpoints. A replacement worker can resume without hidden conversational context.
8. Evaluators inspect observable end state, required process/policy constraints, invariants, forbidden effects, and evidence freshness.
9. Failed gates create explicit gap tasks or escalate. They do not trigger an unbounded “try again.”
10. Release requires goal-level convergence and a scoped human approval when policy demands it.

## Non-negotiable MVP invariants

- An agent cannot set its own task or goal to `SUCCEEDED` without an evaluator record that satisfies the gate.
- Conversation history is never the sole copy of a decision, requirement, approval, or progress state.
- Every artifact and state snapshot is immutable by version; corrections supersede rather than erase.
- Every retriable side effect declares idempotency or compensation semantics. Unknown-effect failures escalate instead of blind retry.
- Every approval binds to the exact operation, resource, arguments or artifact version, actor, and expiry.
- External content enters as untrusted data and cannot expand capabilities or rewrite policy.
- Memory writes retain provenance, scope, trust, freshness, and invalidation information.
- Evaluations record model, harness, tool, environment, resource, dataset, and grader versions.
- Reliability reporting includes repeated runs and fault conditions, not only a best or single run.
- Trace sampling may support observability, but the authoritative audit log for decisions, approvals, effects, and gates is unsampled.

## MVP storage and deployment

Start with one relational database for current objects, versions, typed relations, tasks, runs, leases, approvals, idempotency keys, and append-only audit events. Store large artifacts and logs in object storage. Add a search index for retrieval only when necessary. Add a graph database only after real traversal workload or scale demonstrates that relational recursive queries/materialized views are insufficient.

The append-only event stream supports audit, debugging, and rebuilding selected projections. Do not make irreversible external effects replayable. This is an event-backed architecture, not a requirement that every domain object be implemented through pure event sourcing.

## Deferred or experimental features

- Four physical graph databases.
- Seven independent memory services.
- Uncalibrated decimal confidence scores.
- Automatic invalidation of every descendant on any change.
- Generic causal edges inferred from trace order.
- Multi-agent execution by default.
- Dynamic expected-value routing based on guessed probabilities.
- Full replay of external side effects.
- Self-modifying global skills or automatic promotion of agent reflections to project truth.

Each may become useful, but none should be a platform invariant before an ablation or operational failure justifies it.

