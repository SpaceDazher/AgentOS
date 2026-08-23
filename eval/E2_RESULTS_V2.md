# E2 v2 re-run results (recording contract partially closed; provider instability documented)

Run date: 2026-08-22 (second full series, same frozen frame `eval/e2_tasks.py`,
same protocol). Purpose: close the §Compliance deviations of the first run —
evidence packs + env recorded per episode. Raw:
`.agentos-e2-full-v2/results.json`.

## Headline

| Estimand | Value | Wilson 95% CI |
|---|---|---|
| pass¹ | **0.51** (51/100) | — |
| **pass⁵ (task-clustered, strict)** | **0.05 — 1/20 задача (`clamp-num`)** | **[0.009, 0.236]** |
| Evidence packs | 100/100 episodes (path + sha256 recorded) | — |
| env capture | python / hermes_bin_name / platform / harness_version | — |

NOTE (v1 correction): в отчёте v1 был указан ошибочный pass⁵=0.10 «2/20» —
`greet-basic` прошёл 4/5 и по определению pass⁵ не считается. Корректно: 1/20.
Исправлено и покрыто regression-тестом `tests/test_r4_regressions.py`
(strict-AND семантика проверена на hand-computed примере).

## Failure attribution (автоматическая, из записанных fail_class/note)

| Mode | Episodes |
|---|---|
| provider empty replies ("no AGENTOS_RESULT line") | **42** |
| evaluator-rejected worker omissions (has_code) | 7 |

Verification of provider attribution: 12 of the first 26 session transcripts
contain the provider's own "No reply" banner; every failed episode records
`worker_fail_class`, sanitised trace digest/excerpt and repo-relative trace
ref (patched in R4). The harness handled every failure safely: no known false
accepts, all runs left in FAILED terminal states with reasons, audit chains
intact.

**Scope caveat:** «нарушений политики не наблюдалось» относится к локальным
audit DB этой серии (все effects — разрешённые write_local/SUCCEEDED); это не
adversarial security suite.

## Recording contract status after this run

Closed by this run: evidence pack path+sha256 per episode; env identity;
run terminal state + reason per episode; worker fail class + trace digest.
Still open (tracked in GAP_REGISTER): model/provider version identity (hermes
CLI не отдаёт стабильную machine-readable версию), observations snapshots,
policy/capability snapshots, checkpoints, cost accounting, human
interventions.

## Interpretation

The two series bracket real-world variance: E2-v1 (healthy provider window)
= pass¹ 0.93; E2-v2 (degraded window) = 0.51. Neither number is a capability
claim for the system; both are measurements of the pipeline under different
upstream conditions. A fair estimate requires retrying the 42
provider-failed episodes in a healthy window (methodologically clean now
that runs record true failure states).

## Honesty notes

Same as v1 plus: pass numbers from this run are contaminated by an external
incident and must not be quoted as capability metrics; use them only as
stress-test evidence of safe degradation. Raw workspaces are gitignored —
provider attribution is reproducible from committed digests only against the
local episode directories.
