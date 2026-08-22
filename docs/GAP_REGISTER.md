# AgentOS GAP Register

Status: 2026-08-22. Reference implementation — **not production-ready**. Each gap:
area / current MVP state / risk if shipped as-is / next milestone.

| Area | Current state | Gap / risk | Next step |
|---|---|---|---|
| Storage concurrency | SQLite WAL, single process | concurrent writers serialize on one DB; no backup/PITR | Postgres port behind `db.py`; WAL archiving |
| AuthN/AuthZ | single-user local trust boundary; actors are strings | multi-user spoofing trivial; no real identity | real authn + actor registry; sign approvals with keys |
| External side effects | local FS tools only | HTTP/SaaS mutations have no reconciliation/compensation sinks | compensation registry + sink adapters with native idempotency |
| Fencing | fence tokens generated (`_next_fence`), sinks ignore them; counter reads a field nothing writes | stale writer can still touch FS after reassignment | wire tokens into file tools (filename/journal embed) or drop claim |
| Reconciliation semantics | `reconcile()` marks RECONCILED but ignores `observed_succeeded` value | false "resolved" records possible | store observed outcome; gate treats unresolved-vs-failed differently |
| Registry immutability | `INSERT OR REPLACE` contradicts spec append-only rule | tampered contract versions can overwrite silently | make new version = new row; forbid UPDATE on tool_contract |
| Tamper evidence | SHA-256 hash chain over audit events | chain detectable but not anchored externally; attacker can rewrite whole tail | periodic anchor hash to external storage/notary |
| Evaluator coverage | 3 built-in checks; no FPR/FNR measurements | false accepts/rejects unquantified | execute docs/EVALUATION_PROTOCOL.md (E8) |
| Secrets | none handled | gateway handlers receive raw args; no secret redaction in journal | secret refs + redaction layer before persisting args/events |
| Observability | unsampled audit log only | no OTel traces/metrics; debugging is manual | OTel exporter keyed by goal/run ids |
| Packaging | repo layout, PYTHONPATH=src | not pip-installable; plugin install is manual copy | pyproject.toml + console_scripts entry points |
| Hermes plugin | scaffolded in `hermes_plugin/`, NOT installed/enabled | tools unavailable in chat until installed | copy to `%LOCALAPPDATA%\hermes\plugins\agentos-harness`, `hermes plugins enable agentos-harness` |
| DAG at scale | 1–3 task demos | scheduler untested beyond toy DAGs; no parallel execution | property tests + bounded-parallel executor behind leases |
| CI | none | regressions land unnoticed | GitHub Actions: unittest matrix on 3.11/3.12 |
| Eval evidence | protocol drafted, never executed | zero reliability numbers | first eval batch per protocol |

Known code/spec drift: AGENTS.md lists `demo/` scenario definitions which do not
exist yet (the demo lives in `cli.py`). Tracked here rather than silently ignored.
