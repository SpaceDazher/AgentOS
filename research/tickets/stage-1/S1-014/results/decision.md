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
_Pending. The 12 questionnaire answers will be recorded in `operator-decision.json` and verified by `publisher.py verify-decision` before any status change._
