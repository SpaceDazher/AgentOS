# SRC-05 ontology input, sections 4/9, question Q1 (S1-016 evidence role: ontology)

Provenance: no standalone SRC-05 file exists in this repository (searched
`research/**`, 2026-09-05). This snapshot freezes the locally available
formulation of the ontology question Q1 plus the repo ontology it constrains.
Absence of a separate SRC-05 document is recorded here, not hidden.

Canonical URI: https://local.agentos.invalid/AgentOS/research/tickets/stage-1/S1-016/sources/snap-01-src05-ontology-q1.md
Publisher: AgentOS research (local ontology formulation)
Version: freeze 2026-09-05 (base commit 091ade2)
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: ontology (Q1 lineage representation question)
Access/license: internal design input, full-text excerpt authorized locally

## Q1 (workspace lineage representation question, verbatim from ticket lineage)

S1-016 QM (ontology Q1): should the runtime keep workspace lineage as one
flat canonical scope with PROV-Dictionary insertion/deletion derived only in
export; is a rich PROV-Dictionary runtime needed; or is a minimal hybrid
justified?

S1-007 (QA3, same ontology family): per-scope index/projection versus shared
index with row-level retrieval filtering; canonical scope id composition
`tenant_id + '/' + workspace_id + '/' + goal_id` (frozen in
`research/tickets/stage-1/S1-007/isolation-contract.json`).

## Repo ontology constrained by Q1 (spec/SPEC.md sections 2-3, verbatim)

"ArtifactVersion: DRAFT → CURRENT → SUPERSEDED (by newer version, never
deleted). Immutable content: (goal_id, kind, version) unique; content
addressed by SHA-256. Any correction = new row + relation
SUPERSEDES(new→old)."

"Transition + audit event commit atomically or not at all."
(get_evidence_pack fails loudly if any ACCEPTED goal lacks its goal.accepted
event; chain integrity walks prev_event_sha256.)

"Memory records carry provenance and scope; cross-goal/cross-tenant reads are
denied." Memory scoping is enforced at SQL level
(`WHERE scope_goal_id = ?`).

S1-016 use: Q1 asks which runtime representation of lineage satisfies L1-L12.
The ontology above fixes the non-negotiables (single scope per version,
immutable history, atomic audit). No recognition or population claim is
sourced here.
