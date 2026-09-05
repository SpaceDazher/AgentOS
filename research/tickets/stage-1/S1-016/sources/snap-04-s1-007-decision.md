# S1-007 scope-isolation decision and evidence (S1-016 evidence role: scope-isolation)

Provenance: excerpts of `origin/main` tracked bytes (evaluation record,
isolation contract, decision matrix, probes). Record: result
`pass_with_limits`, revision 7,
goal `goal_5FX22ZHCEAW0G2B501M1DDTYSA`,
campaign `rcamp_9AGA2BWAQ70FQQ5401M1DDTYSA`,
evaluation `reval_6BH3G062B38G3WHH01M1DDTYW2`,
chain `4c344ab2e83b231e4cd14c2f69f9eb95b9b0f374f7fab3bf8651eda682390692`.

Canonical URI: https://local.agentos.invalid/AgentOS/research/tickets/stage-1/S1-007/results/decision-evidence
Publisher: AgentOS S1-007 (canonical rev 7)
Version: branch codex/s1-007-qa3-isolation (frozen contract v1), retrieved 2026-09-05
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: scope-isolation (single-scope decision precedent)
Access/license: local repo bytes, excerpt authorized

## Single-scope isolation decision

- Canonical scope id composition: `tenant_id + '/' + workspace_id + '/' +
  goal_id` (S1-016 reuses this exact tuple as the lineage scope).
- Decision matrix winner with sensitivity analysis precedent (dimensions
  D1-D11, normalized scores, score margins, near-tie analysis).
- Zero-tolerance contract ISO1-ISO8: no foreign content/metadata/counts,
  byte-identical deny bodies, epoch-bound invalidation, provenance survival.
- Run matrix: `results/run-a` + `results/run-b` run manifests with per-case
  run records across 3 seeds (101/202/303); probes file with fault-injection
  and equivalence-class evidence.

## Same-host/model limits carried

- All results are local-model measurements from a deterministic simulation;
  no production latency, storage or privacy certification.
- Timing probe is bounded same-host paired-interleaved wall-clock evidence,
  not absence-of-side-channel proof.
- Storage overhead uses a declared per-index constant (model assumption).
- Producer/verifier labels are process-separated roles in one local
  environment, not external human auditors.
- S1-003/S1-005 evidence reused only within stated limits.
