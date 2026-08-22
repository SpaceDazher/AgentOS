# AgentOS evidence review — Phase 1: Scoping

## Research Question Brief

### Primary research question

Which architectural and governance mechanisms are supported by empirical or authoritative evidence as improving the reliability, traceability, recoverability, and safety of long-horizon AI-agent execution, and what minimum viable AgentOS harness follows from that evidence?

### Sub-questions

1. Which claims in the initial handoff are established, supported, provisional, or purely design hypotheses?
2. Under which conditions do deterministic orchestration, artifact/state-centric coordination, and multi-agent decomposition help or hurt?
3. What minimum control, evidence, evaluation, security, and recovery mechanisms are justified for an AgentOS MVP?

### FINER assessment

| Criterion | Score | Rationale |
|---|---:|---|
| Feasible | 4/5 | Primary papers, benchmark papers, official specifications, framework documentation, and implementation repositories are accessible; direct production telemetry is limited. |
| Interesting | 5/5 | The field has strong practitioner claims but weak agreement on end-to-end architecture and reliability evidence. |
| Novel | 4/5 | Individual mechanisms are known; the evidence-calibrated separation between validated principles and AgentOS design hypotheses is the contribution. |
| Ethical | 5/5 | The work uses public technical sources and explicitly includes safety and governance analysis. |
| Relevant | 5/5 | The result directly informs implementation sequencing, evaluation, and risk controls. |
| **Average** | **4.6/5** | |

### Scope

**In scope**

- Agent harnesses and agentic software engineering.
- Long-horizon task execution, recovery, context management, and memory.
- Multi-agent orchestration and coordination costs.
- State, artifacts, provenance, checkpoints, event logs, evaluation, and world-state verification.
- Tool security, prompt injection, permissions, human approval, and sandboxing.
- Sources from 2022–2026, plus older foundational distributed-systems and security sources where necessary.

**Out of scope**

- Building the full AgentOS implementation in this research pass.
- Selecting a final vendor framework or database without a separate benchmark against concrete requirements.
- Claims about AGI, consciousness, or broad organizational replacement.
- Causal claims where only observational benchmark evidence exists.

### Key assumptions

- The target workload includes software engineering and other tool-using tasks that mutate external state.
- Reliability means repeated goal-level success under bounded cost and risk, not merely a plausible final answer.
- Official documentation can establish a system's behavior or interface, but not prove effectiveness.
- Fast-moving computer-science preprints are admissible as provisional evidence when clearly labeled and corroborated.

## Methodology Blueprint

### Design

Pragmatist, critical scoping review with design synthesis. This is not presented as a PRISMA systematic review: the corpus mixes peer-reviewed papers, benchmark reports, official specifications, implementation repositories, and first-party engineering reports, and the field changes too quickly for a closed medical-style evidence hierarchy.

### Search and inclusion strategy

- Prefer primary sources: original papers, benchmark papers, official specifications/documentation, first-party repositories, and first-party engineering reports with disclosed methods.
- Include secondary sources only for orientation or when they summarize otherwise inaccessible evidence.
- Search for confirming and disconfirming evidence separately.
- Exclude unsourced marketing claims, duplicated summaries, papers without enough methodological detail for the claim used, and citations that cannot be verified.

### Evidence grading

| Grade | Meaning in this review |
|---|---|
| A | Multiple independent primary sources and/or replicated benchmark evidence; conclusion stable across contexts. |
| B | Strong primary evidence but limited replication, scope, or ecological validity. |
| C | Credible first-party or conceptual evidence; useful for design, not proof of effectiveness. |
| D | Plausible design hypothesis with insufficient direct evidence. |
| F | Contradicted, non-verifiable, or materially overstated claim. |

### Confidence language

- **High**: the architecture decision is justified for the stated target even if implementation details vary.
- **Medium**: evidence favors the decision, but boundary conditions or direct comparative data remain incomplete.
- **Low**: retain as an experiment or ADR hypothesis, not as a platform invariant.

### Validity controls

- Claim-to-source matrix with source type and limitation.
- Explicit distinction between evidence, inference, and recommendation.
- Counter-evidence search and strongest-counterargument test.
- No efficiency claim based solely on framework feature documentation.
- No claim of source verification unless the original paper/specification was inspected.
- Final editorial, devil's-advocate, and ethics reviews before delivery.

## Devil's Advocate — Checkpoint 1

**Verdict: PASS with constraints.**

The question is answerable as an evidence-calibrated design synthesis, but it cannot prove that one complete AgentOS architecture is universally optimal. The largest risks are (1) treating benchmark success as production reliability, (2) mistaking first-party architecture descriptions for comparative evidence, and (3) importing distributed-systems patterns without demonstrating that their added complexity is warranted for an MVP. The report must therefore state boundary conditions, separate mechanism-level support from system-level inference, and keep low-evidence features optional or experimental.

