# ADR-0006: Stage-eval authority and the anti-reward-hacking boundary

Date: 2026-08-22. Status: Accepted.

## Context

The EPIC adds stage evaluations (Concept → Specification → Plan → Execution →
Verification → Post-episode). An agent that can edit its own exams and then
take them can always produce ACCEPTED. The existing invariant — only a Gate
over evaluator records accepts a Goal — must extend to stage evals and to the
autoresearch loop.

## Decision

1. **EvalDefinition rows are append-only and versioned.** A correction creates
   a new version row; nothing is updated or deleted (DB triggers refuse
   UPDATE/DELETE, mirroring tool_contract).
2. **Deterministic checks are blocking; LLM-judge checks are advisory-only**
   at the Gate: an advisory result can add reasons but never satisfies a
   required criterion by itself.
3. **Authority matrix extension:** StageGate decisions carry the same
   authority discipline as goal gates — decided only by the bound
   GateAuthority over persisted EvalRun records in one transaction.
4. **Frozen sets for autoresearch:** holdout corpora, thresholds, policy,
   capabilities and the acceptance rule are outside the mutable scope of any
   experiment; hashes of frozen inputs are recorded in CampaignManifest and
   re-verified before KEEP.
5. **Every model judge record stores model id, prompt version and rubric
   version**; missing provenance makes the record inadmissible at any gate.

## Consequences

- Reward hacking via self-modified evals is structurally impossible inside
  the process; an agent may propose eval changes, which land as new versions
  requiring human approval outside its scope.
- Advisory judges cannot be silently promoted: promotion = new required
  EvalDefinition version = ADR + human approval.
- Cost: more ceremony per eval change; accepted for integrity.
