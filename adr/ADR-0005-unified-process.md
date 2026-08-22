# ADR-0005: Unified process — AgentOS core + Hermes plugin + Hermes worker + ECC-in-worker

- Status: Accepted
- Date: 2026-08-21
- Supersedes: the "composition only" framing of ADR-0004 (relation unchanged,
  delivery changed: both directions ship together as one process).

## Context

User decision: keep **both** integration directions and merge them into a single
workflow: (1) drive AgentOS from Hermes chats, (2) let AgentOS execute tasks via
Hermes workers, (3) allow ECC-style skills inside those worker sessions.

## Decision

One process, three attach points:

```
Hermes desktop chat  ──(agentos_* tools, hermes_plugin/)──►  AgentOS runtime API
AgentOS engine       ──(WorkerAdapter: HermesAgentWorker)──► hermes CLI session
hermes CLI session   ──(optional ECC skills inside Claude Code/Codex)──► work
```

1. **`hermes_plugin/`** — a Hermes plugin exposing `agentos_status`,
   `agentos_create_goal`, `agentos_run`, `agentos_evidence_pack`. Thin JSON client
   over the Python API (`src/agentos`). The SQLite DB stays the single source of
   truth; the plugin holds no state.
2. **`hermes_worker.py`** — `HermesAgentWorker(WorkerAdapter)` runs each Task in a
   fresh `hermes chat -q` subprocess scoped to the run workspace. Worker output is
   untrusted; effects only through the gateway.
3. **ECC stays an optional worker-side skill pack** installed in Claude Code/Codex;
   AgentOS neither depends on it nor duplicates it. Its process discipline
   (plan→test→review→verify) is expressed in our task templates/evidence
   requirements instead of being imported as code.
4. Single demo command exercises the whole chain with FakeWorker; Hermes paths are
   opt-in (`--worker hermes`) and degrade to typed errors when `hermes` is absent.

## Consequences

- Tests never require Hermes or ECC (deterministic core).
- The unified process is: Concept typed in Hermes → Goal in AgentOS DB → tasks run
  by Hermes(-driven or fake) workers under gateway policy → gate → evidence pack
  back into the chat that asked.
