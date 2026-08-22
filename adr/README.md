# Architecture Decision Records

Index of ADRs for AgentOS. Statuses as recorded in each file.

| ADR | Title | Status |
| --- | --- | --- |
| [ADR-0001](ADR-0001-stack.md) | Language and stack — Python 3.11 + stdlib, SQLite, zero-core-dependencies | Accepted |
| [ADR-0002](ADR-0002-monolith-journal.md) | Architecture — monolith, three logical planes, transactional journal | Accepted |
| [ADR-0003](ADR-0003-worker-adapters.md) | Worker abstraction — provider-neutral; Hermes as first real adapter | Accepted |
| [ADR-0004](ADR-0004-ecc-hermes-relation.md) | Relation to ECC-style harness systems | Accepted |
| [ADR-0005](ADR-0005-unified-process.md) | Unified process — AgentOS core + Hermes plugin + Hermes worker + ECC-in-worker | Accepted (supersedes the "composition only" framing of ADR-0004; relation unchanged, delivery changed) |

## Research integrity

Integrity check of the evidence-review research artifact.

- File: `research/agentos_confident_result/agentos_evidence_review.md`
- Command: `sha256sum research/agentos_confident_result/agentos_evidence_review.md`
- Actual output:

  ```
  3b1df2d6efe8cedc128d1ccde6f07ae189902e9638548dc09f4263dfe7db0f1c *D:/Project/AgentOS/research/agentos_confident_result/agentos_evidence_review.md
  ```

- Expected: `3b1df2d6efe8cedc128d1ccde6f07ae189902e9638548dc09f4263dfe7db0f1c`
- Result: **PASS** (hashes match, case-insensitive)
- Checked: 2026-08-22
