# S1-013 pilot protocol (human companion to pilot-protocol.json)

Version 1.1.0-draft (R1 correction). The JSON file is authoritative; this
document explains it. Internal preregistration, not a public registry.

## What we study

Whether 15–20 people (target N=16, quotas 8 owners + 8 reviewers)
understand delegation, scope, provenance, the knowledge gate and stop
controls after a 20-minute session (QM2, G-01, G-09), and how approval
load affects accuracy and fatigue (N_prompts/hour by role).

## Proposed human session flow (75 minutes total)

Training (10) → comprehension C1–C5 (20) → approval block A (15) →
rest (5) → approval block B (15, AB/BA counterbalanced, seed 13013) →
debrief (10). Facilitator reads the scripted intro verbatim and never
hints answers before the primary response is recorded.

This sequence is a human-protocol proposal, not the current synthetic browser
mode. The preparation UI permits rapid manual progression through 12 and 24
prompts and records actual active intervals; it makes no 15-minute endurance or
human-session-duration claim. Human collection stays disabled until approval,
blinded grading and human-mode implementation are independently reviewed.

C5 begins at the presentation event. Two mock agents must acknowledge stopping;
the participant cannot self-confirm them. Slow outcomes remain in latency arrays,
and missing outcomes remain in the denominator. Synthetic stop-fault injection
is a tooling check, not a production revocation measurement.

## Measures and targets (hypotheses, not gates)

C1 ≥90%, C2 ≥95%, C3 ≥85%, C4 ≥95% correct "no" with valid
explanation, C5 confirmed stop ≤30s. Targets are reported as
met/not-met/inconclusive from raw counts with uncertainty; N=16
never proves universal accuracy. A failed UX hypothesis is valid
research, not a passed gate.

## Roles and fairness

Two roles with fixed quotas; small strata are not called
representative. All starters, exclusions and completers appear in the
participant flow; poor understanding is never an exclusion reason.
Dropouts stay in every denominator they entered.

## Privacy and consent

Pseudonymous random ids; contacts, consent originals and the
reidentification key stay with the operator, never in Git/wiki/packs.
No audio/video, no external transmission, no verbatim publication by
default. Pseudonymisation is not anonymity for small roles and free
text — manual review required. See consent-template.md, privacy-plan.md.
