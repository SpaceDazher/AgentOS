# ADR-0003: Worker abstraction — provider-neutral; Hermes as first real adapter

- Status: Accepted
- Date: 2026-08-21

## Context

AgentOS must be provider-neutral: the runtime owns lifecycle, policy and
evidence; probabilistic workers are replaceable. The user runs Hermes Agent
(Nous Research) locally, which itself drives CLI coding agents (Claude Code,
Codex). The question "can this be integrated with Hermes" is answered here.

## Decision

1. **`WorkerAdapter` protocol** (`workers.py`): `start(run) -> None`,
   `run.step(...) -> StepResult`, `shutdown()`. The engine never imports an LLM.
2. **`FakeWorker`** (deterministic): executes scripted steps; used by all tests.
   LLM-free unit/integration tests are a hard requirement.
3. **`HermesAgentWorker`** (`hermes_worker.py`): real adapter that invokes the
   local `hermes` CLI (`hermes chat -q "<task prompt>" --cwd <workspace>`) in a
   subprocess with a per-run workspace and a compiled task prompt. Output text
   is treated as **untrusted worker output**: it can request tool calls only via
   AgentOS gateway calls recorded in the run journal — it cannot mutate state
   directly. If `hermes` is not installed or fails to launch, the adapter
   raises a typed error and the Run goes to `FAILED(worker_unavailable)`; the
   system stays fully functional with FakeWorker.
4. Integration surface for the *host agent* (Hermes driving AgentOS, rather than
   AgentOS driving Hermes) is provided separately by the optional Hermes plugin
   (`hermes_plugin/`) exposing `agentos_*` tools; it is a thin client over the
   same Python API and is not required for tests.

## Consequences

- The same vertical scenario runs with FakeWorker (tests/demo) or HermesAgentWorker
  (real episodes) without touching engine code.
- Prompt-injection containment: even if the worker model is compromised, its only
  path to effects is the gateway (capabilities + exact approvals), matching C22.

## Alternatives considered

- Direct OpenAI/Anthropic SDK adapter: couples core to a vendor SDK and needs
  API keys for anything to run; rejected for MVP (can be added later behind the
  same protocol).
- Making Hermes a hard dependency of the runtime: violates provider-neutrality;
  rejected.
