# S1-014 protocol — card versus graph, operator design review

**Status:** Phase A autonomous preparation; Phase B = one operator design review
(`operator_review_n=1`, `human_study_n=0`). This is not a user study.

## Question (QM1, SRC-04 §8)
Do users resolve claim disputes more accurately and with less overload via a
compact evidence card or an argumentation graph? This round cannot answer the
population question; it can only approve a provisional design contract.

## Variants
- **CARD** — focal claim, status, gate state, always-visible challenge, source
  cue (publisher + origin + state), independence cue; three one-action button disclosures.
- **GRAPH** — claim/evidence nodes (source/origin/group labelled), support and
  challenge edges, keyboard-focusable nodes, linear equivalent list; same disclosures.

Both are rendered from the same canonical document (`contract.py`,
`schemas/dispute.schema.json`); parity is machine-checked per task
(`results/task-equivalence.json`).

## Tasks
8 frozen disputes stratified simple/medium/complex (`task-manifest.json`),
covering: direct claim vs one challenge; several supports from one independence
group; genuinely independent corroboration; strong winner with visible
challenge; rejected/revoked/unknown state; publisher ≠ origin; near-miss with
many nodes; small card with complex logic. Correct answers live only in
`oracle/oracle.json` (never served to the browser).

## Assignment
Deterministic counterbalancing (`assignment-table.json`): 4 CARD + 4 GRAPH,
alternating, no dispute repeated, order by seed × executor.

## Session
Consent → practice (unrecorded) → 8 trials → export. Presentation time = focus
lands on the first answer control; end = submit or 180 s timeout. Pause/resume
and withdrawal are available; withdrawn/unpresented trials remain in the
denominator as explicit `missing`/`withdrawn` rows.

## Measures
See `rubric.json` and `decision-rule.json` (frozen before results).

## Stop conditions
Variants cannot be made equivalent; any variant hides source, challenge or
independence group; a threshold change is requested after seeing results; a
human pilot, PII or consent storage is requested.
