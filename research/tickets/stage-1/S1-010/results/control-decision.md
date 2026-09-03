# S1-010 Control Decision — Tool-Poisoning Detection (Phase A, cloud)

## Decision

**PASS** (proposed; cloud Phase A evidence only, round 2 after an
independent REVISE review) — recorded as `READY_FOR_CANONICALIZATION` in
`candidate-record.json`.  The branch stays `IN_REVIEW`; local canonical
Phase B is required before any ticket closure.  Round 2 closed all ten
review findings (fail-open aggregation/records/provenance, decision-contract
gaps, wrong tamper-sandbox repo-root, fail-open dependency-gate pack
verification, Windows path/arcchive portability, and the non-native FLOW-11
bundle); two fresh process-separated A/B runs with full binding schemas
reproduced identical decisions with zero critical escapes and zero authority
expansions.  Registered-context revocation now routes to QUARANTINE before
any permissive branch, and the approval model limitation (boolean
pre_approved; exact-action/expiry binding is a production-gateway duty) is
recorded explicitly.

## Answer to the research question

Layered controls that **decide** (structural validation, digest/provenance
verification, registry capability diff, exact policy/effect gate, output-taint
guard) detected every malicious class in the frozen corpus, while controls that
only **observe** (entropy, keyword, obfuscation heuristics) stayed advisory:
they add reason codes and can escalate to quarantine/human review, but can
never produce an ALLOW, never solely DENY a benign unusual tool, and never
compensate for an authorization or provenance violation. Uncertain
effect-capable behavior, detector faults (timeout, crash, malformed,
disagreement), and obfuscated or indirect output injection all resolve
fail-closed (DENY / QUARANTINE / HUMAN_REVIEW / UNSUPPORTED), never to a
permissive allow. External content — manifests, tool output, governance
claims — can never expand capabilities, policy, approvals, ownership, budgets,
knowledge state, or goal acceptance: `authority_mutations` is empty by
construction in every decision record and is re-derived from raw records by
both runs.

## Evidence summary

- Frozen 56-case corpus (14 benign / 14 malicious manifest / 14 malicious
  output / 14 near-miss; 31 critical), hash-bound via `corpus-manifest.json`.
- Two process-separated runs on commit `77e81738b4b3b49d3281885cbe15a15f41e8a02d` (clean tree):
  verifier-A PID 3237 and verifier-B PID 3248, distinct nonces and output
  roots, byte-identical decision sets (`decisions_sha256` equal).
- Confusion matrix (truth × treatment): TP=34, FN=0, raw FP=3, TN=19. All
  three raw benign "blocked" cases are oracle-sanctioned routings
  (quarantine/human review) — hard-gate benign FPR = 0.0.
- Precision 0.9189 (Wilson 95% [0.7866, 0.9716]); recall 1.0 (Wilson 95%
  [0.8973, 1.0]); per-class recall floors 0.9 met by manifest and output
  classes at 1.0.
- Critical escapes 0; authority expansions (capability/policy/approval/budget/
  knowledge/acceptance) all 0; decision mismatches 0.
- Probes A–F all detected through the production evaluator path (see
  `results/probes.json`): benign unusual capability not silently denied (A);
  valid manifest with poisoned output denied (B); capability drift detected
  despite valid digest (C); obfuscated/indirect poison never expands authority
  (D); governance/terminal claims remain inert (E); detector degradation fails
  closed (F).

## Assumptions

- The registered-context blocks inside frozen cases faithfully model what a
  real registry would hold (trusted publisher set, registered capabilities,
  dependency digests, pre-approval flags).
- Declared deterministic detector faults adequately exercise aggregation
  logic; no statistical detector was simulated beyond disagreement.
- Pattern families in the frozen contract represent the 2026 threat surface
  documented by MITRE ATLAS and CWE-74 at freeze time.

## Unknowns

- Behavior against adaptive adversaries that mutate between detection families
  was not measured (out of scope for a deterministic corpus).
- Interaction with live MCP/A2A transports was not evaluated (S1-009 boundary
  preserved; those semantics remain unsupported by design).

## Residual risks

- Unseen obfuscation families (novel encodings, semantic paraphrase) may pass
  advisory layers; the compensating control is routing-level: uncertain
  effect-capable cases quarantine or require human review.
- The corpus measures declared classes only; metrics do not generalize to
  production scale or distribution shift.
- Same-host process separation is not an external audit.

## Rollback triggers

- Any critical malicious case passing unquarantined in a re-run → revert to
  the prior frozen contract version and re-open the ticket.
- Any non-empty `authority_mutations` observed in raw records → immediate
  FAIL and rollback of the admitting gateway change.
- Run A/B divergence on identical frozen inputs → treat as compromised
  determinism; quarantine the release and investigate before any Phase B.
- Dependency packs for S1-001/S1-009 failing hash or semantics re-check during
  Phase B → BLOCKED until re-published.

## Limitations

See `candidate-record.json` `limitations` — cloud Git-evidence scope only, no
canonical-DB claims, deterministic detectors, frozen corpus bounds.
