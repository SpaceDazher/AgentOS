# ADR-0007: Canonical DB → Obsidian materialized knowledge graph

Date: 2026-08-22. Status: Accepted.

## Context

Humans need to browse goals, evals, experiments, incidents and lessons;
agents need the same graph machine-readably. Obsidian gives a zero-dependency
browsing UI over Markdown with `[[wiki links]]`, but Markdown must never
become the source of truth (existing invariant: conversation and notes are
not authoritative copies of state).

## Decision

1. `wiki/` is a **deterministic projection** of canonical SQLite records.
   `wiki-build` regenerates generated notes; running it twice on unchanged
   canonical state yields a byte-identical tree (zero diff).
2. Generated notes carry a header marking them non-editable; manual edits are
   overwritten on rebuild. Human-authored notes enter only via an explicit
   import command that stamps provenance, and live in human-owned folders.
3. Frontmatter carries stable ids and canonical refs (goal_id, run_id,
   eval_id, experiment_id, artifact_sha256). Links use stable ids, so the
   graph survives renames.
4. `wiki-check` validates: broken `[[links]]`, duplicate ids, invalid
   frontmatter, dangling canonical references, unexpected orphans. Exit code 1
   on any violation.
5. Secrets, raw prompts and provider transcripts are redacted before they can
   appear in a note; the vault never stores raw provider output.

## Consequences

- No Obsidian/plugin requirement for build or tests (plain files + stdlib).
- The wiki can be deleted and rebuilt at any time — it is a cache, like the
  evidence pack, not a record.
- Slight duplication of data as text; accepted for browsability.
