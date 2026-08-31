# S1-011 — Minimal knowledge gate: promote/challenge versus argumentation/TMS

Research ticket bundle (Stage 1, W1, P0, owner `knowledge`, dependencies
S1-001 + S1-003). Research question: is a minimal two-status promote/challenge
gate safer and more operable for the first knowledge layer than a full
argumentation or truth-maintenance system, while preserving retraction and
provenance (G-06)?

## Files

| File | Purpose |
|---|---|
| `bundle.json` | The bounded research bundle: config, 9 verified sources, 23 claims, 11 FLOW-11 artifacts, audit block, probes block. |
| `lifecycle_probe.py` | Deterministic stdlib state machine over the seven S1-003 statuses; adversarial probes P1/P2 plus transition-completeness P3. Writes `probe-results.json`. |
| `comparison_probe.py` | Machine-checks the acceptance criteria: >=5-dimension design comparison, MVP recommendation fields, no-truth-oracle language, S1-003 vocabulary alignment, probes wiring. Writes `comparison-results.json`. |
| `probe-results.json` | Output of `lifecycle_probe.py` (31/31 checks). |
| `comparison-results.json` | Output of `comparison_probe.py` (12/12 checks). |

## Lifecycle (MVP decision)

States are exactly the S1-003 `shapes-v3.ttl` KnowledgeAssertion vocabulary:
`proposed, under_review, promoted, challenged, retracted, superseded, rejected`
(the ticket's "pending" maps to `under_review`; `retracted/superseded/rejected`
are terminal). Ten defined transitions with named guards are tabled in the
`ontology` artifact and executed by `lifecycle_probe.py`. The evidence gate
reuses the S1-003 promoted preconditions verbatim (>=2 Evidence, >=2 distinct
canonical sources, >=2 independence groups, complete EvidenceShape provenance,
scope match, one PromotionActivity with matching actor scope) plus S1-001
independence rules (mirrors inherit identity; text agreement is not provenance).
Challenge removes an assertion from the promoted-only derived view immediately;
retraction appends a marker and deletes nothing. No truth oracle is claimed;
reputation is never enforcement authority.

## Run

```powershell
# probes (stdlib only)
python research/tickets/stage-1/S1-011/lifecycle_probe.py
python research/tickets/stage-1/S1-011/comparison_probe.py

# harness evaluation (from repo root)
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-011 minimal knowledge gate promote challenge versus argumentation TMS" --bundle "research/tickets/stage-1/S1-011/bundle.json" --db ".agentos-research/platform-stage-1"
```

## Notes and limits

- Repo-local sources are hash-bound by host-recomputed SHA-256 in
  `verifier_provenance.path` / `file_sha256`; literature identity (Doyle, Dung,
  PROV-O) is inherited from the S1-001 verified queue records F16/F18/F8 plus a
  local hash check of the S1-001 bundle — no new live page review was performed.
- Audit verdict is `pass_with_limits`: process-separated (not external) auditor;
  operator-load statements are hypotheses until S1-013; calibration and dispute
  UX are deferred to S1-012/S1-014.
- The state machine is a deterministic research model, not a production
  knowledge graph; nothing here sets a Goal to ACCEPTED.
