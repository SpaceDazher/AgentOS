# S1-014 independent audit (agentos-s1-014-independent-verifier)

Scope: recomputation from tracked bytes only; producer code (`build_fixtures.py`, `importer.py`) and audit path (`evaluator.py`, `publisher.py` probes/replay/compare) are separate code reading the same frozen inputs.

| check | result |
|---|---|
| frozen manifest covers sources, protocol, rubric, corpus, schemas, renderer contract, UI assets, importer/evaluator/replicator/publisher, fixtures | yes (41 files) |
| corpus == `build_corpus()`; oracle absent from browser contract | yes |
| parity CARD == GRAPH == canonical for 8/8 tasks; disclosure rule symmetric | yes |
| probes A–J detected through production importer/evaluator with unchanged control | 10/10 |
| two-process replay digests equal | yes |
| denominators keep timeout/withdrawn/missing rows | yes |
| privacy scan: no PII/secret/free text in tracked artifacts | yes |
| forbidden phrases (winner, superiority, human N>0) absent | yes |
| FLOW-11 bundle passes real normalizer in a temporary DB (pass_with_limits, chain_fresh, latest_evaluation_valid) | yes |

Verdict on the preparation evidence: **pass_with_limits** (preparation only). Ticket status stays PREPARATION_READY until the operator decision.
