# Preliminary evidence matrix

> **Superseded:** use `claim_evidence_matrix.md` for the audited E/J ratings, row-level evidence, counterevidence and final decisions.

This matrix is a working synthesis and will be revised after independent source streams return.

| ID | Preliminary verdict | Confidence | Design consequence |
|---|---|---|---|
| C01 | Supported with correction | High | Use a hybrid control model: deterministic code/policy owns invariants, transitions, budgets, and gates; LLMs choose non-predefinable actions inside that envelope. |
| C02 | Supported | High | Canonical state and versioned artifacts live outside prompts; conversation remains useful context but not the system of record. |
| C03 | Useful synthesis, not established taxonomy | Medium | Separate these semantics in the schema, but they need not be four stores or services. |
| C04 | Typed provenance supported; exactly four graphs unproven | Medium | Implement one typed provenance relation model and expose artifact/evidence/execution/decision views. |
| C05 | Evidence packets and explicit uncertainty are supported; numeric confidence is risky | Medium | Store claim status, evidence, counterevidence, owner, freshness, and validation plan; use calibrated numbers only after empirical calibration. |
| C06 | Functional diversity is plausible and sometimes useful; homogeneous-agent correlation is under-measured | Medium-Low | Diversify tasks, tools, prompts, and evidence channels; do not treat repeated outputs as independent votes. |
| C07 | Supported with clear boundary conditions | High | Parallelize independent breadth-first work; default to sequential or single-agent execution for shared mutable state and dependency-heavy coding. |
| C08 | Functional separation supported; separate model instances not always needed | Medium-High | Separate generator, critic, and verifier contracts and evidence; co-locate them when risk/cost permits. |
| C09 | Strong distributed-systems transfer; direct agent evidence varies | High for mutating parallel work | Add DAG dependencies, ownership/lease, isolated workspace, and merge policy only when concurrency or recovery requires them. |
| C10 | Supported for long-running work | High | Persist run state, checkpoint meaningful units, make workers replaceable, and test resume after process/container loss. |
| C11 | Supported | High | Build context from task-relevant state and identifiers; use just-in-time retrieval, recency, compaction, and explicit budgets. |
| C12 | External memory is supported; exact seven-layer taxonomy is not | Medium | MVP: working context, project/decision memory, episodic/failure records, and retrieval policy; split further only from measured failure modes. |
| C13 | Strongly supported as interface/security design | High | Tool schemas, clear semantics, side-effect metadata, permissions, audit, and idempotency become platform contracts; a skill is a procedure + pre/postconditions + verification. |
| C14 | Supported as a security mechanism, not a complete policy | High | Approval is scoped to operation/arguments/resource/version and serialized with the run; use policy automation for low-risk cases. |
| C15 | Established distributed-systems requirement for side effects | High | Every retriable mutation needs an operation identity and declared retry/compensation semantics; never blind-retry unknown effects. |
| C16 | Trace/provenance strongly supported; full event sourcing is optional | Medium-High | Keep an append-only audit/event stream and causal IDs; do not require every domain object to be rebuilt solely by replay in the MVP. |
| C17 | Strongly supported | High | Gate completion on observable end state and invariants; combine deterministic graders, targeted LLM graders, and human review. |
| C18 | Gates and iterative convergence supported; universal change-propagation engine is a design hypothesis | Medium | Implement dependency-based stale marking for core artifacts first; validate whether automatic propagation reduces defects before expanding. |
| C19 | Risk-based oversight supported; exact triggers need domain policy | Medium-High | Human gates at high-impact or ambiguous decisions, irreversible effects, capability expansion, and release; avoid approval fatigue. |
| C20 | Budget-aware routing supported; expected-value arithmetic is not yet robust | Medium | Enforce hard budgets and empirical escalation rules; learn routing thresholds from eval data rather than guessed probabilities. |
| C21 | Strongly supported | High | Report end-state success, repeated-run `pass^k`, policy compliance, recovery under faults, latency/cost, and infrastructure configuration. |
| C22 | Strongly supported | High | Treat external content as untrusted data; isolate credentials/compute, minimize capabilities, gate side effects, and control memory writes. Trust labels alone are insufficient. |
| C23 | Coherent architecture inference | Medium-High | Keep execution, assurance/epistemic, and governance responsibilities distinct in interfaces, while using one shared identity/provenance model. |
| C24 | Not a literal law | Low as science; Medium as heuristic | Retain only as a checklist or bottleneck heuristic; remove multiplication signs from formal claims and metrics. |
