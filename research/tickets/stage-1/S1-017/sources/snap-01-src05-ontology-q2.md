# SRC-05 ontology input, sections 4/9, question Q2 (S1-017 evidence role: ontology)

Provenance: no standalone SRC-05 file exists in this repository (searched
`research/**`, `docs/**`, 2026-09-05). This snapshot freezes the locally
available formulation of ontology question Q2 plus the repo ontology it
constrains. The absence of a separate SRC-05 document is recorded here, not
hidden. Follows the same local-formulation precedent as prior tickets.

Canonical URI: https://local.agentos.invalid/AgentOS/research/tickets/stage-1/S1-017/sources/snap-01-src05-ontology-q2.md
Publisher: AgentOS research (local ontology formulation)
Version: freeze 2026-09-05 (base commit 091ade2)
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: ontology (Q2 responsibility-analytics placement question)
Access/license: internal design input, full-text excerpt authorized locally

## Q2 (verbatim ticket lineage)

Can STIT/ATL annotations explain who could have done what, which alternatives
were available, and why a result occurred; and where must these computations
live so they never become a second, hidden authorization mechanism?

## Repo ontology constrained by Q2 (spec/SPEC.md, verbatim)

Roles: Requester (human user) creates Goals and approves/rejects at gates;
Approver consumes exact-action approvals (one-time, bound); Worker executes
Tasks inside isolated workspaces; Evaluator runs checks and produces records
but never accepts; Gate moves Goals to ACCEPTED/REJECTED and is the sole path
to terminal acceptance.

"Conversation history is never the sole copy of decisions/approvals/state."
"Artifact versions are immutable; corrections create a new version +
SUPERSEDES." "Approvals bind to actor + exact operation + exact canonical
arguments + expiry and are consumed atomically exactly once."

S1-017 use: Q2 asks where STIT/ATL computation lives. The ontology above fixes
the non-negotiables: only Gate/Gateway decide; annotations are derived data.
No legal/moral/production claim is sourced here.
