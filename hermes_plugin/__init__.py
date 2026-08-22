"""agentos-harness: thin-client Hermes tools over the local AgentOS Python API.

Registers four tools in the "agentos" toolset:
    agentos_status          — goal counts by status, last 5 audit events, chain_ok
    agentos_create_goal     — Goal + default spec placeholder (stays DRAFT)
    agentos_run_demo        — full vertical demo scenario via agentos.cli.run_demo
    agentos_evidence_pack   — machine-readable evidence pack for one goal

Hermes loads this package as ``hermes_plugins.agentos_harness`` and calls
``register(ctx)``; all imports below are RELATIVE (required — absolute
imports from the plugins directory fail to resolve).
"""
from .schemas import (
    AGENTOS_CREATE_GOAL_SCHEMA,
    AGENTOS_EVIDENCE_PACK_SCHEMA,
    AGENTOS_RUN_DEMO_SCHEMA,
    AGENTOS_STATUS_SCHEMA,
)
from .tools import (
    handle_agentos_create_goal,
    handle_agentos_evidence_pack,
    handle_agentos_run_demo,
    handle_agentos_status,
)
from .tools import tool_adapter  # noqa: F401 — re-exported for clarity

# (tool name, schema, handler, emoji) — handlers take the JSON args dict positionally.
_TOOLS = (
    ("agentos_status", AGENTOS_STATUS_SCHEMA, tool_adapter(handle_agentos_status), "\U0001f4ca"),
    ("agentos_create_goal", AGENTOS_CREATE_GOAL_SCHEMA, tool_adapter(handle_agentos_create_goal), "\U0001f3af"),
    ("agentos_run_demo", AGENTOS_RUN_DEMO_SCHEMA, tool_adapter(handle_agentos_run_demo), "\u25b6\ufe0f"),
    ("agentos_evidence_pack", AGENTOS_EVIDENCE_PACK_SCHEMA, tool_adapter(handle_agentos_evidence_pack), "\U0001f9fe"),
)


def register(ctx) -> None:
    """Register every plugin tool with the Hermes plugin context."""
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="agentos",
            schema=schema,
            handler=handler,
            emoji=emoji,
        )
