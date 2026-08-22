# ADR-0004: Relation to ECC-style harness systems

- Status: Accepted
- Date: 2026-08-21

## Context

The user asked whether the harness process can be integrated "into this system
(ECC) together with Hermes". ECC (github.com/affaan-m/ECC) is a skill/agent/hook
pack for coding-agent harnesses: 68 agents, 286 skills, hooks, rules, memory —
installed into Claude Code / Codex etc.

## Decision

**Do not port AgentOS into ECC. Compose instead.** Rationale:

1. Different layer of abstraction. ECC *configures* an agent's behavior inside a
   single conversation (skills, prompts, hooks). AgentOS is a *runtime above*
   agents: durable state machines, transactional audit, leases, gates,
   evidence packs. ECC has no concept of Goal/Run/Checkpoint/Gate as durable
   objects; AgentOS does not care which prompt pack a worker uses. Porting one
   into the other would destroy exactly the properties each provides.
2. Mapping: ECC ≈ "worker-side competence layer"; Hermes = host + worker runtime;
   AgentOS = orchestration/enforcement plane (the three-plane architecture from
   ADR-0002). The clean composition is:

   ```
   User → AgentOS runtime (state, gates, evidence)
              → WorkerAdapter: HermesAgentWorker
                    → hermes CLI session (Hermes skills/plugins/hooks,
                      optionally ECC skills inside Claude Code/Codex sessions)
                          → Tool gateway back into AgentOS for any effect
                            that must outlive the conversation
   ```

3. What we take from ECC's *idea* (not codebase): skills-first packaging and a
   security scanner mindset (AgentShield analog = our gateway policy checks +
   untrusted-content rule). AgentOS skills live as versioned ArtifactVersions /
   MemoryRecords, not as a second filesystem convention.
4. The optional Hermes plugin (`hermes_plugin/`) makes AgentOS callable *from*
   Hermes chats (`agentos_*` tools). ECC remains usable *inside* the worker
   sessions that AgentOS spawns. No cross-installation, no duplicated state:
   the database stays the single source of truth (invariant #2).

## Consequences

- No fork/maintenance coupling to ECC release cadence.
- A future ECC-style "process pack" could be expressed as seed ArtifactVersions
  (spec templates, evaluator checklists) loaded into a fresh AgentOS DB.
