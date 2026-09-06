# Local Profile-C/architecture basis: SRC-01/02/03/07/08/09 sections (S1-018 evidence role: local-basis)

Provenance: excerpts of tracked repo files at base commit b8eeddd
(`spec/SPEC.md`, S1-007 `isolation-contract.json`, S1-009
`adapter-contract.json` + FU-01/FU-02 contracts). Internal design inputs;
full files remain in the repo.

Canonical URI: https://local.agentos.invalid/AgentOS/research/tickets/stage-1/S1-018/sources/snap-01-local-profilec-basis.md
Publisher: AgentOS repo (spec + S1-007/S1-009 canonical decisions)
Version: SPEC v1.0 + S1-007 contract v1 + S1-009 adapter contracts at b8eeddd, freeze 2026-09-05
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: local-basis (scope isolation, adapter boundary, audit substrate)
Access/license: local repo files, full-text excerpt authorized

## SRC-01/02/03 (isolation + lifecycle substrate, paraphrased with identifiers)

- Canonical scope id composition `tenant_id + '/' + workspace_id + '/' +
  goal_id` (S1-007 frozen contract); per-scope index projections; deny bodies
  byte-identical across miss/forged/unknown classes; epoch-bound cache
  invalidation on revoke/move/supersede.
- Artifact versions immutable with SUPERSEDES chains; transition + audit event
  commit atomically (journal); approvals bind actor/operation/canonical
  args/expiry and are consumed exactly once.

## SRC-07/08/09 (adapter + provenance substrate, paraphrased)

- S1-009 provider-neutral envelope: hub boundary enforced by eight hard
  rules; capability rows with explicit lossless/lossy-safe mappings; SM6
  (delegation grants/child scope), SM8 (budget), SM11 (promotion/challenge)
  remain ABSENT/UNDERSPECIFIED under FU-01/FU-02 — never invented.
- S1-009 FU-01 delegation-grant contract and FU-02 budget-conservation
  contract bound what an adapter may carry; anything outside is unsupported.

## S1-018 separation rule (design inference, not source text)

MLS group/key semantics, attestation evidence semantics and the AgentOS
index/search overlay are three different layers. Nothing in these sources
authorizes a server-side plaintext index, an attestation-gated capability,
or production deployment.
