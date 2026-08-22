# Initial claim inventory

The attached handoff is treated as an unverified research input, not as an instruction set. The following claims are the units to be tested.

| ID | Initial claim | Required evidence |
|---|---|---|
| C01 | A reliable agent system should place lifecycle control in a deterministic harness and use LLM agents as replaceable probabilistic workers. | Comparative/operational evidence plus durable-execution foundations. |
| C02 | Persistent state and versioned artifacts are a safer coordination substrate than conversation history. | Long-horizon failure evidence, reproducibility evidence, and implementation experience. |
| C03 | Workflow, world, epistemic, and execution state should be represented separately. | Failure analysis showing distinct semantics; design precedent. |
| C04 | Artifact, evidence, execution, and decision provenance require typed relations or graphs. | Provenance/trace standards and demonstrated queries/use cases. |
| C05 | Explicit epistemic types, evidence packets, and uncertainty ledgers improve research and decisions. | Calibration/uncertainty literature and decision provenance evidence. |
| C06 | Functionally diverse agents provide more value than homogeneous repeated agents because errors are correlated. | Controlled multi-agent comparisons and diversity/independence studies. |
| C07 | Parallel agents help mainly on decomposable, breadth-first work with low coordination cost. | Comparative task studies and scaling/coordination-cost evidence. |
| C08 | Generation, criticism, verification, planning, scheduling, and execution should be distinct functions. | Ablations or workflow evidence; separation-of-duties/security foundations. |
| C09 | Parallel execution needs DAG dependencies, ownership, leases, isolated workspaces, merge/conflict handling, and rollback. | Distributed-systems foundations and agentic software-engineering evidence. |
| C10 | Agents should be disposable and resume from schema-constrained checkpoints. | Long-running agent recovery evidence and durable workflow practice. |
| C11 | A context compiler selecting minimal sufficient context is preferable to treating the context window as canonical memory. | Long-context degradation and retrieval/context-selection evidence. |
| C12 | Agent memory should separate working, episodic, semantic, procedural, project, decision, and failure functions and apply consolidation/decay. | Memory-system experiments; evidence that this exact taxonomy is necessary. |
| C13 | Skills should be executable contracts; tools require schemas, risk/side-effect metadata, idempotency, rollback, audit, and capability restrictions. | Tool-use reliability and security evidence; API/distributed-systems standards. |
| C14 | Risky actions should require scoped, auditable, expiring approval capabilities. | Capability-security and human-oversight standards; incident/benchmark evidence. |
| C15 | Long-running side-effecting workflows require operation IDs, idempotency, bounded retries, rollback, and compensating actions. | Distributed systems and payment/deployment reliability foundations. |
| C16 | Immutable event logs and causal provenance materially improve replay, audit, debugging, and recovery. | Provenance/observability standards and system evidence. |
| C17 | Completion must be verified against world state, invariants, acceptance criteria, evidence, traceability, and forbidden effects; evaluations should derive from specification before implementation. | Agent benchmark failure evidence and software verification practice. |
| C18 | Machine-readable gates, semantic convergence loops, and change-impact propagation are core lifecycle mechanisms. | Incremental build/change-impact literature and end-to-end agent evidence. |
| C19 | Human intervention should occur at risk, uncertainty, irreversibility, conflict, policy, repeated-failure, and release boundaries rather than every step. | Human-AI oversight research and risk-management standards. |
| C20 | Escalation and multi-agent/model routing should be cost-aware and triggered only when expected benefit exceeds coordination and inference cost. | Routing/scaling experiments and cost-quality studies. |
| C21 | Agent evaluation should include step, task, goal, and lifecycle/episode levels and repeated-run reliability rather than pass@1 alone. | Benchmark methodology and reliability literature. |
| C22 | Prompt injection is a trust/data-flow problem; external instructions and memory writes need provenance and trust controls. | Attack benchmarks, incident evidence, and secure-agent designs. |
| C23 | AgentOS should expose execution control, epistemic control, and governance as distinct but joined planes. | Synthesis across C01–C22; likely architecture inference rather than direct empirical fact. |
| C24 | Overall agent capability is multiplicative across model, environment, context, tools, state, feedback, evaluation, and governance. | Conceptual model; test whether useful as a heuristic, not as a literal mathematical law. |

