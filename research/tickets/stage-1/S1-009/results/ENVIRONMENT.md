# S1-009 Research Environment

**Ticket:** S1-009 — MCP/A2A delegation and knowledge semantics adapter roadmap
**Frozen at:** 2026-09-02T00:00:00Z
**Host:** Windows (DSH danger-full-access)

## Runtime

| Component | Value |
|---|---|
| Host OS | Windows |
| Python | 3.11 |
| Working dir | `research/tickets/stage-1/S1-009/` |
| Stdlib only | Yes — evaluator, runner, tests use no external packages |
| Network | No network during tests/runner |
| LLM | No LLM during tests/runner |

## File Policy

- **DSH file policy:** `danger-full-access` — sandbox does not restrict file
  modifications by available operations.
- **Approval prompts:** Disabled. Do not request sandbox escalation.
- **Git operations:** No `git push` authorized. Commits are local only.

## Files and Hashes (post-freeze)

All hashes are SHA-256 of file bytes as computed by `make_bundle.py` from the
clean tree at `2026-09-02T00:00:00Z`.

| Artifact | SHA-256 |
|---|---|
| cases.json | (computed by make_bundle) |
| evaluator.py | (computed by make_bundle) |
| runner.py | (computed by make_bundle) |
| make_bundle.py | (computed by make_bundle) |
| canonical-envelope.schema.json | (computed by make_bundle) |
| adapter-contract.json | (computed by make_bundle) |
| capability-matrix.json | (computed by make_bundle) |
| rubric.json | (computed by make_bundle) |
| semantic-model.json | (computed by make_bundle) |
| protocol-snapshot-manifest.json | (computed by make_bundle) |
| corpus-manifest.json | (computed by make_bundle) |
| evaluation-record.json | (computed by make_bundle) |
| dependency-gate.json | (computed by make_bundle) |
| bundle.json | (computed by make_bundle) |
| results/comparison.json | (computed by make_bundle) |
| results/probes.json | (computed by make_bundle) |
| results/version-skew.json | (computed by make_bundle) |
| results/adapter-roadmap.md | (computed by make_bundle) |
| tests/test_s1_009_regressions.py | (computed by make_bundle) |

## Execution Matrix

| Run | Executor | Nonce | Output Root | Verdict | PASS | FAIL |
|---|---|---|---|---|---|---|
| A | verifier-A | run-a-nonce | results/run-a | PASS | 40 | 0 |
| B | verifier-B | run-b-nonce | results/run-b | PASS | 40 | 0 |

## Determinism Properties

- Same corpus/contract/rubric/evaluator hash for main and rerun.
- Two process-separated runs with different executor IDs and output roots.
- Identical decisions, verdicts, and envelope hashes across both runs.
- Process separation: each run uses a separate subprocess (`subprocess.run`).

## Process Separation

The runner (`runner.py`) invokes the evaluator as a separate Python subprocess with:
- Different `executor_id` (verifier-A vs verifier-B)
- Different `nonce` (run-a-nonce vs run-b-nonce)
- Different output root (results/run-a vs results/run-b)

This satisfies the requirement that "producer, independent verifier, and run
executors have distinguishable identities; repeating the function in one
process is not an independent rerun."

## Secrets Policy

- No fixture contains secrets, tokens, auth headers, credentials, or raw
  sensitive payloads.
- No API key-like tokens in case data.
- The regression test suite includes a secrets scanner check.
