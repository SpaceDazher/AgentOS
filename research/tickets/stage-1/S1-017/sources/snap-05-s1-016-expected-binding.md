# S1-016 expected lineage/audit binding (S1-017 evidence role: lineage-binding)

Status: EXPECTED BINDING DESCRIPTION ONLY — S1-016 is not canonicalized in
`origin/main` (verified 2026-09-05: no evaluation-record.json at
`origin/main:research/tickets/stage-1/S1-016/`). NO goal/campaign/evaluation
IDs, revision, chain, result, pack hashes or decision values are stated here:
inventing them is explicitly forbidden and the Phase B gate must obtain them
programmatically after merge/canonicalization.

Canonical URI: https://local.agentos.invalid/AgentOS/research/tickets/stage-1/S1-017/sources/snap-05-s1-016-expected-binding.md
Publisher: AgentOS S1-017 Phase A (binding expectation, not evidence)
Version: expectation freeze 2026-09-05
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: lineage-binding (what Phase B will verify)
Access/license: internal preparation note

## What Phase B will prove from immutable bytes (no values assumed)

- S1-016 branch `codex/s1-016-workspace-lineage` merged/canonicalized into a
  verifiable ref; exact ticket/revision/goal/campaign/evaluation/result/full
  64-hex chain read from the canonical evaluation record (never typed by hand).
- File/payload/self SHA-256 of canonical and ticket packs, content-addressed
  filenames, pack bindings, and `git archive <verified-commit>` bytes for the
  record and frozen artifacts.
- The SELECTED lineage representation among FLAT_RUNTIME_PROV_EXPORT,
  RICH_RUNTIME_PROV_DICTIONARY, HYBRID_MINIMAL_LINEAGE (or INCONCLUSIVE),
  with L1–L12 counters, reconstruction/export semantics and every inherited
  limitation carried without status upgrade.
- The S1-016 decision gives provenance edges ZERO policy authority (a
  contrary decision would trip S1-017 stop/escalation and block Phase B).
- Absence of path traversal, symlink escape, stale/missing/extra refs.

## S1-017 independence guard

Phase A proceeds without S1-016 bytes. S1-017 scenarios carry their own
bounded transition systems and audit event sequences; S1-016 lineage is
consumed only as frozen input in Phase B, never as an oracle for S1-017
scenario outcomes. Copying artifacts across branches to bypass the gate is
forbidden.
