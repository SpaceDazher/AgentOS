# S1-014 decision record (append-only)

## Phase A — autonomous preparation
- Status: **PREPARATION_READY**; S1-014 remains **OPEN** until the operator design review.
- operator_review = REQUIRED · human_study_n = 0 · comparative_human_effectiveness = NOT_MEASURED · winner = none
- Dependency gate: PROVEN for S1-011 @0e794c4e, S1-012 @14564354, S1-013 @091ade23 (phase_a_dependencies_proven=true, operator_review_dependencies_proven=true, population_human_claims_proven=false).
- Frozen manifest sha256: `ebf247de10b5d32992fb009fac7b2b9c5f9a5fd6edf9746e4f23988cd7934d4d`; browser contract sha256: `f3013c1cd507384dbd536996ef350474f0ccd4d9eb13bf66d7ff9b60b726fcf2`.
- Metrics sha256: `981c5eb972811c2ba5d9041dcfa67b12fc1bd321a9c0e2b171dcd6520f70be6b`; bundle sha256: `60cd68ddce73644f17d713407c6dbe8452eb59a6edda408682bff31ba94ad9b4`.
- Probes A–J: all detected with passing control (10/10).
- Replay: two processes (PIDs 6777/6779, executors EXEC-RUN-A/EXEC-RUN-B, distinct nonces and output roots) — digests match. Same-host replay, not external audit.
- Hard gates: content parity, disclosure symmetry, provenance/challenge/independence visible at level 0, graph linear equivalent, accessibility — all green on the frozen corpus.

## Technical replay counts (synthetic sessions, NOT human data)
Synthetic sessions: 5 (ok ×2, timeout, withdrawn, missing_answer scenarios). Answers are oracle-free deterministic patterns; correctness numbers below are tooling checks only.

| variant | stratum | assigned | submitted | timeout | withdrawn+missing | correct | incorrect | unscored | recall exact/partial/none | challenge seen | time median ms (incl. censored) | disclosure median | keyboard median |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CARD | simple | 6 | 5 | 0 | 1 | 3 | 2 | 1 | 5/0/1 | 5 | 1500 | 1 | 14 |
| CARD | medium | 5 | 5 | 0 | 0 | 1 | 4 | 0 | 0/5/0 | 5 | 1500 | 1 | 12 |
| CARD | complex | 9 | 6 | 1 | 2 | 0 | 6 | 3 | 3/3/3 | 6 | 1500 | 1 | 10 |
| GRAPH | simple | 4 | 4 | 0 | 0 | 1 | 3 | 0 | 4/0/0 | 4 | 1750 | 1 | 13 |
| GRAPH | medium | 10 | 8 | 0 | 2 | 3 | 5 | 2 | 4/4/2 | 8 | 1750 | 1 | 11 |
| GRAPH | complex | 6 | 6 | 0 | 0 | 1 | 4 | 1 | 1/4/1 | 5 | 1750 | 1 | 14 |

No comparison between the CARD and GRAPH rows is permitted: they are not human observations.

## Phase B — operator design review
Recorded 2026-09-05T02:56:02Z · operator `OPR-7c41d9a2f6` (opaque id, no identity mapping) · operator_review_n=1 · human_study_n=0.

**Answers:** `1A 2A 3A 4A 5A 6A 7A 8A 9A 10B 11B 12A`
**Outcome (frozen rule, Q1=A):** provisional default **CARD_WITH_GRAPH_DRILLDOWN** — card first, graph via explicit disclosure; graph keeps the mandatory linear keyboard/screen-reader equivalent (Q6=A).
**Status:** S1-014 **PASS_WITH_LIMITS** — operator approved a design contract only; this is NOT a human-effectiveness finding; `comparative_human_effectiveness=NOT_MEASURED`; no card/graph winner exists.

Bindings: frozen manifest `ebf247de10b5d32992fb009fac7b2b9c5f9a5fd6edf9746e4f23988cd7934d4d` · browser contract `f3013c1cd507384dbd536996ef350474f0ccd4d9eb13bf66d7ff9b60b726fcf2` · reviewed Phase-A bundle `60cd68ddce73644f17d713407c6dbe8452eb59a6edda408682bff31ba94ad9b4` · published bundle `bab3e9a45ee720421f2a15faf4fd99260562205eac317ba34acf81f079a12ff7`.
Verification: `publisher.py verify-decision` → OK; `publisher.py publish` re-ran the full pipeline (import, probes A–J, two-process replay, fresh evaluation, saved-vs-fresh comparison) — PASS_WITH_LIMITS; `research-plan` on `.agentos-research/platform-stage-1` → exit 0, `chain_fresh=true`, `latest_evaluation_valid=true`, tracked evidence pack payload `9f97ddfe010f71ea0bac7fe6c349c1010af1abde8f56b2c0696740ba803d47c5`; `wiki-check` → ok.

## Deviation log (append-only)

1. 2026-09-05T02:56:02Z — Operator's first answer string contained `6B`. The fail-closed verifier rejected it (`question 6=B violates hard contract`). The operator corrected it to `6A` before any status change. Recorded here instead of silent editing; all other 11 answers unchanged.
2. 2026-09-05T02:56:02Z — Operator review was a design walkthrough of both variants (CARD, GRAPH) via the delivered prototype and walkthrough page; no operator browser envelope was exported or imported, so no operator trials exist in metrics (by design: operator judgment is never participant data).
3. 2026-09-05T02:56:02Z — Accessibility accommodations: none requested or reported.
