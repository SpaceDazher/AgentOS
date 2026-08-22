"""Tool schemas for the agentos-harness plugin.

Each schema is a dict with `name`, `description`, and `parameters`
(JSON Schema object) — passed verbatim to ctx.register_tool().
"""

COMMON_DB_DIR = {
    "type": "string",
    "description": (
        "Optional AgentOS root directory containing agentos.db "
        "(workspaces/artifacts live here too). Omit to use $AGENTOS_HOME "
        "(or ~/.agentos); pass '.agentos-demo' for data written by demo runs."
    ),
}

AGENTOS_STATUS_SCHEMA = {
    "name": "agentos_status",
    "description": (
        "Inspect the local AgentOS database: counts of goals by status, "
        "the last 5 audit-journal events, and whether the audit hash chain "
        "verifies (chain_ok). Read-only."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "db_dir": COMMON_DB_DIR,
        },
    },
}

AGENTOS_CREATE_GOAL_SCHEMA = {
    "name": "agentos_create_goal",
    "description": (
        "Create a new AgentOS Goal from a free-text concept, with a "
        "placeholder specification and a single 'tests_present' acceptance "
        "criterion. The goal stays in state DRAFT until the spec is refined "
        "and the goal is activated. risk_tier: 'normal' (default) grants "
        "local-command capability; 'sensitive' restricts it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "concept_text": {
                "type": "string",
                "description": "Free-text concept describing what the goal should achieve.",
            },
            "risk_tier": {
                "type": "string",
                "enum": ["normal", "sensitive"],
                "description": "Risk tier for the goal. Defaults to 'normal'.",
            },
            "db_dir": COMMON_DB_DIR,
        },
        "required": ["concept_text"],
    },
}

AGENTOS_RUN_DEMO_SCHEMA = {
    "name": "agentos_run_demo",
    "description": (
        "Run the full AgentOS vertical demo scenario (concept -> goal -> "
        "spec -> tasks -> gateway effects -> evaluations -> release gate -> "
        "evidence pack) via agentos.cli.run_demo and return its JSON result "
        "verbatim. Set flaky=true to exercise the retry path with a scripted "
        "first-attempt worker failure."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "flaky": {
                "type": "boolean",
                "description": "Script a first-attempt worker failure to exercise bounded retries.",
            },
            "db_dir": COMMON_DB_DIR,
        },
    },
}

AGENTOS_EVIDENCE_PACK_SCHEMA = {
    "name": "agentos_evidence_pack",
    "description": (
        "Build and return the machine-readable evidence pack for one AgentOS "
        "goal (goal record, criteria, tasks, runs, evaluations, gates, "
        "artifacts, tool activities, approvals, audit-chain summary). Output "
        "is truncated to 6000 characters if larger; sha256 and on-disk path "
        "are always included."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {
                "type": "string",
                "description": "The AgentOS goal id (e.g. 'goal_...').",
            },
            "db_dir": COMMON_DB_DIR,
        },
        "required": ["goal_id"],
    },
}
