# AgentOS GAP Register

Status: 2026-08-22 (updated after E1/E2 measurement series). Reference
implementation — **not production-ready**. Each gap: area / current state /
risk / next step. Items closed by recent work are listed at the bottom.

| Area | Current state | Gap / risk | Next step |
|---|---|---|---|
| Storage concurrency | SQLite WAL, single process | concurrent writers serialize on one DB; no backup/PITR | Postgres port behind `db.py`; WAL archiving |
| AuthN/AuthZ | single-user local trust boundary; actors are strings | multi-user spoofing trivial; no real identity | real authn + actor registry; sign approvals with keys |
| External side effects | local FS tools only | HTTP/SaaS mutations have no reconciliation/compensation sinks | compensation registry + sink adapters with native idempotency |
| Fencing | persisted monotonic counter + sink-side validation (`fence_sink.py`); handlers declare `_fence`/`_sink` | built-in fs.write is fence-aware; third-party handlers must opt in | migrate remaining handlers to fence-aware form |
| Reconciliation semantics | RECONCILED_SUCCEEDED/FAILED distinct; rowcount enforced; FAILED blocks gate | — | — |
| Registry immutability | append-only INSERT; fingerprint conflict refused; invoke() re-resolves from registry (forged contracts inert); DB triggers refuse UPDATE/DELETE | — | — |
| Tamper evidence | SHA-256 chain + in-DB anchor + external mirror `audit_anchor.head`; pack build fails loudly on tamper/inconsistent ACCEPTED | mirror lives on same host | periodic off-host/notarized copy of `audit_anchor.head` |
| Worker sandbox (R2-3) | Hermes worker returns INTENTS only; effects replayed via gateway; path confinement at parse + handler level; Job Object limits lifetime/memory | Job Object does NOT confine filesystem/network/process access | real sandbox: restricted token / container per run |
| Evaluator coverage | 3 acceptance checks + 24 stage checks; frozen corpora (78 cases); measured FPR=0/FNR=0 on evaluator-quality corpus; false-completion rate и FPR/FNR на LLM-эпизодах не измерены | evaluator subprocess has no FS/network confinement | sandbox for evaluator execution; human gold-set |
| Secrets | none handled | gateway handlers receive raw args; no secret redaction in journal | secret refs + redaction layer before persisting args/events |
| Observability | unsampled audit log only | no OTel traces/metrics; debugging is manual | OTel exporter keyed by goal/run ids |
| Packaging | repo layout, PYTHONPATH=src | not pip-installable; plugin install is manual copy | pyproject.toml + console_scripts entry points |
| Hermes plugin | **installed & enabled** (`%LOCALAPPDATA%\hermes\plugins\agentos-harness`); 4 tools live in chat, verified end-to-end | bootstrap pins repo path via AGENTOS_REPO default | pip packaging removes the path pin |
| DAG at scale | sequential demos; scheduler untested beyond linear/2-node DAGs | no parallel execution | property tests + bounded-parallel executor behind leases |
| CI | GitHub Actions matrix (3.11/3.12 × win/ubuntu): tests + SHA pin + demo smoke + plugin import check | runs only when a GitHub remote exists | add remote and push |
| Eval evidence | **executed**: harness drills pass⁵=1.0; E2 N=20×5: pass¹=0.93, pass⁵=0.75 (порог не взят); stage gates интегрированы в release Gate (6 этапов, latest-wins); eval_run привязан к goal+case+artifact-chain+corpus | human gold-set для false-completion; LLM-judge FPR/FNR | protocol §Compliance items |

## Closed gaps (history)

- Terminal acceptance bypass (R1/R2): bound GateAuthority + in-transaction
  gate-row + evaluation-presence; Journal refuses terminal transitions.
- Idempotency blind-retry (F5): EXECUTING-before-effect + UNKNOWN_OUTCOME on
  incomplete intents; reconciliation required, never re-executed.
- Lease validity (F7): status=RUNNING + expiry enforced against the persisted row.
- Reconciliation outcome (F8): RECONCILED_FAILED blocks the gate.
- Registry handler loss (F9): runtime handler registry re-attached on resolve;
  invoke() re-resolves contracts (forged objects inert).
- Evidence pack global chain (F10): full-chain verify + fail-loudly on broken
  chain or inconsistent ACCEPTED.

Known code/spec drift: AGENTS.md lists `demo/` scenario definitions which live
in `cli.py` (and now `eval/`); tracked rather than silently ignored.
