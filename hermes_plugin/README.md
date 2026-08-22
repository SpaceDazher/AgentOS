# agentos-harness (Hermes plugin)

Thin-client Hermes tools over the **local AgentOS Python API** (`<repo>/src/agentos`). The plugin prepends `<repo>/src` to `sys.path` itself (computed from `__file__`), so no pip install is needed — but the plugin directory must stay inside the AgentOS repository checkout.

## Tools (toolset: `agentos`)

| Tool | Purpose |
|------|---------|
| `agentos_status` | Counts of goals by status, last 5 audit-journal events, `chain_ok` hash-chain integrity flag. |
| `agentos_create_goal` | Creates a Goal from `concept_text` (+ optional `risk_tier`: `normal`\|`sensitive`) with a placeholder spec and a `tests_present` acceptance criterion. **Returns the goal in state `DRAFT`** until the spec is refined and the goal is activated. |
| `agentos_run_demo` | Runs the full vertical demo via `agentos.cli.run_demo` and returns its JSON result verbatim. `flaky: true` exercises the retry path. |
| `agentos_evidence_pack` | Builds and returns the evidence pack JSON for one goal (truncated to 6000 chars if huge; `sha256` and on-disk path always included). |

All handlers wrap exceptions into `{"success": false, "error": "..."}`.

## Install (3 steps)

1. **Copy** this directory into the Hermes plugins folder:
   `%LOCALAPPDATA%\hermes\plugins\agentos-harness`
2. **Enable** it:
   ```
   hermes plugins enable agentos-harness
   ```
3. **Restart** your Hermes session (plugin enablement and tools take effect on the next session, then check `hermes tools list` for the four `agentos_*` tools).

## Database locations

- Demo runs (`agentos_run_demo` without `db_dir`) write under **`.agentos-demo/`** in the current working directory (`agentos.db`, workspaces, artifacts, evidence packs).
- Otherwise the default DB lives under **`$AGENTOS_HOME`** (falling back to `~/.agentos`).
- Pass `db_dir` to any tool to target an explicit root directory containing `agentos.db`; `agentos_status` auto-prefers whichever of those databases already exists.
