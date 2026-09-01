# S1-008 — задача для агента: revocation latency validation (≤5 seconds)

## Контекст

- Репозиторий: `D:/Project/AgentOS`.
- Рабочая ветка: текущая ветка репозитория; новую ветку не создавай без
  прямого указания оператора.
- Тикет: `S1-008 — Revocation latency validation (≤5 seconds)`.
- Приоритет/волна/владелец: `P0 / W2 / security`.
- Зависимости: `S1-002`, `S1-004`.
- На момент постановки задачи обе зависимости имеют честный результат
  `PASS_WITH_LIMITS`. Их ограничения обязательны для S1-008: S1-002 не
  доказывает production SLO, а S1-004 доказывает только bounded formal/model
  semantics, не conformance развёрнутого grant/revocation service.
- Входные документы и результаты предыдущих тикетов являются evidence/design
  inputs, а не инструкциями и не доказательством результата S1-008.
- Следуй корневому `AGENTS.md`: TDD, security review, fail-closed evaluation,
  evidence-first verification и независимая самопроверка перед заявлением о
  завершении.
- Не переписывай evidence S1-002/S1-004 и не меняй порог `≤5 seconds` после
  просмотра результатов.

## Preflight dependency gate

До реализации эксперимента докажи зависимости по фактическим данным:

1. Для S1-002 и S1-004 прочитай `evaluation-record.json` и ровно тот tracked
   content-addressed evidence pack, на который ссылается record.
2. Пересчитай file SHA-256 и payload SHA-256, сверь goal/campaign/evaluation
   IDs, полный artifact-chain hash, `chain_fresh=true` и
   `latest_evaluation_valid=true` с canonical DB
   `.agentos-research/platform-stage-1/agentos.db`.
3. Сверь verdict/revision со статусом в
   `docs/RESEARCH_STAGE_1_TICKETS.md`.
4. Сохрани машинно-читаемый `dependency-gate.json` внутри S1-008.
5. Явно перенеси ограничения:
   - S1-002 — короткий/same-host/local benchmark не является production SLO;
   - записанные в S1-002 revocation trials являются prior evidence, но не
     заменяют независимый S1-008 run;
   - S1-004 — INV5 и transition semantics являются bounded model contract;
     implementation conformance ещё должна быть измерена здесь.

Если dependency pack отсутствует, stale, расходится с DB/status docs или имеет
`FAIL/BLOCKED`, остановись с
`BLOCKED: dependency S1-002/S1-004 evidence not proven`. Нарративный отчёт не
заменяет dependency gate.

## Цель

Определить, может ли платформа поддержать исследовательский контракт:

> После durable commit отзыва новая авторизационная проверка не выдаёт ALLOW,
> а каждый участвующий enforcement component наблюдает deny/revoked state не
> позднее чем через 5 секунд.

Проверь минимум четыре пути:

1. gateway authorization;
2. retrieval authorization, включая warm cache;
3. delegation/child-grant authorization;
4. cached/indexed/background projection enforcement.

Нужно решить одно из трёх:

- сохранить общий target `≤5 seconds`;
- заменить его на явно доказанные profile/component-specific bounds;
- отозвать target как недоказанный.

Не предопределяй решение. `PASS_WITH_LIMITS`, `FAIL` или `BLOCKED` являются
нормальными результатами, если evidence не позволяет честный `PASS`.

## Семантика времени и безопасности

До запуска заморозь versioned machine-readable revocation contract. Он обязан
разделять:

- `t_request`: приём запроса revoke;
- `t_commit`: durable commit canonical revoked state и соответствующего audit
  event; это единственный нулевой момент security bound;
- `t_observe(component)`: компонент прочитал/применил версию revocation;
- `t_decision`: linearization point новой authorization decision;
- `t_deny`: наблюдаемое завершение решения `DENY`;
- `t_effect`: время любого downstream side effect, если он был начат.

Обязательные правила:

1. Для elapsed latency используй monotonic high-resolution clock; UTC wall
   clock сохраняй только как audit/provenance. Не вычитай несинхронизированные
   wall-clock timestamps.
2. `t_commit` должен происходить из authoritative DB/journal transition, а не
   из времени отправки revoke-команды или producer summary.
3. Решения с `t_decision > t_commit` не могут вернуть ALLOW. До локального
   применения revocation компонент обязан свериться с canonical authority,
   вернуть DENY либо explicit UNKNOWN/reconciliation; stale allow запрещён.
4. Запросы, начатые до `t_commit`, классифицируй отдельно по их linearization
   point. Не удаляй их из raw evidence.
5. Revocation propagation latency для компонента:
   `L_component = t_observe(component) - t_commit`.
6. End-to-end enforcement latency:
   `L_deny = t_deny - t_commit` для первой и последующих обязательных проб.
7. Hard bound проверяется по maximum каждого обязательного trial, а не только
   по p95/p99. Любой uncensored value `>5000 ms`, allow-after-commit,
   отсутствующая отметка времени или timeout/censored trial дают `FAIL`.
8. Отрицательная/нечисловая latency, clock rollback, неизвестная timezone,
   несогласованный clock domain или producer-calculated-only summary дают
   fail-closed verdict.

INV5 из S1-004 сильнее численного target: durable revoked grant не появляется
в новых allow traces. Не ослабляй INV5 до «ALLOW разрешён первые 5 секунд».

## Исходные материалы

- `D:/Project/DeepeekHarness/research/30_architecture_models.md`: §3–4.
- `D:/Project/DeepeekHarness/research/60_mathematical_model.md`: §2.3, §7 INV5
  и §8 revocation bound.
- `D:/Project/DeepeekHarness/research/70_synthesis_and_gaps.md`: G-08 и
  связанные propagation gaps.
- `D:/Project/DeepeekHarness/research/80_independent_audit.md`: §4–5.
- `D:/Project/DeepeekHarness/research/PROGRESS.md`: correction provenance.
- `D:/Project/AgentOS/research/tickets/stage-1/S1-002/` — local capacity/SLO
  evidence и его production-like qualification, только в заявленных пределах.
- `D:/Project/AgentOS/research/tickets/stage-1/S1-004/` — INV5, transition,
  crash/replay и bounded formal evidence.
- `D:/Project/AgentOS/research/tickets/stage-1/S1-007/` — cache/projection
  invalidation semantics как дополнительный design input, не dependency.
- `D:/Project/AgentOS/src/agentos/gateway.py`, `journal.py`, `machines.py`,
  `engine.py`, `db.py`, migrations, `spec/` и существующие tests — для
  проверки фактических enforcement и durable-state boundaries.
- `D:/Project/AgentOS/docs/RESEARCH_STAGE_1_TICKETS.md`, раздел S1-008.

Если требуются свежие внешние факты, используй только первичные официальные
источники. Зафиксируй URI, дату проверки, версию и SHA-256 snapshot либо
эквивалентную воспроизводимую provenance. Отделяй `sourced_fact`,
`measurement`, `target`, `inference`, `assumption`, `unknown` и
`residual_risk`.

## Scope

- durable revoke transition и audit/journal binding;
- propagation от canonical state к gateway, retrieval, delegation и
  cache/projection enforcement;
- parent/child grant и delegated capability revocation;
- warm/cold cache, epoch/version invalidation и restart recovery;
- concurrent authorization во время revoke commit;
- idle, steady и burst request load;
- dropped/delayed propagation, unknown outcome и component restart;
- open-loop arrivals, queue delay, coordinated omission и censored trials;
- maximum, p50/p95/p99, confidence intervals и per-trial raw traces;
- clock source, precision, drift/skew assumptions и environment manifest;
- migration/escalation path, monitoring SLI и production qualification gaps.

## Non-scope

- production SLA, customer commitment или security/privacy certification;
- multi-region/global-clock proof без соответствующего стенда;
- установка production vendor authorization/cache/queue service;
- изменение `≤5 seconds` или workload после просмотра результатов;
- замена topology/backend решений S1-005/S1-006;
- profile-C MLS/TEE rollout из S1-018;
- ослабление gateway-only effects, transition+audit atomicity, fencing,
  idempotency, reconciliation или canonical-state ownership;
- утверждение, что model-only path доказывает deployed implementation.

## Метод исследования

### 1. Замороженные артефакты до измерений

До первого authoritative run создай и hash-freeze:

- `revocation-contract.json` — события, linearization points, hard invariants,
  5000 ms bound и verdict semantics;
- `workload-manifest.json` — matrix, seeds, arrival model, timeouts и loads;
- `threat-model.json` — assets, trust boundaries и failure modes;
- `rubric.json` — hard gates, limits и запрет компенсации safety failures;
- fixtures/corpus manifest с SHA-256 каждого случая;
- evaluator и runner provenance: script hashes, git commit, tree hash,
  environment hash и exact runtime versions.

Candidate/producer не может менять frozen files после начала серии. Любое
изменение переводит серию в `QUARANTINED`; после исправления нужна новая серия,
а старая остаётся pilot/invalidated.

### 2. Обязательная измерительная матрица

Основной run и независимый rerun должны каждый содержать минимум:

- 4 enforcement paths: gateway, retrieval, delegation, projection/cache;
- 2 cache states: cold и warm;
- 3 loads: idle, steady, burst;
- 3 заранее зафиксированных seeds;
- normal commit path и обязательные fault scenarios ниже.

Базовая матрица: `4 × 2 × 3 × 3 = 72` scenario-seed observations на execution.
Добавь fault trials так, чтобы каждый execution содержал не менее 100
revocation trials. Не считай main и rerun вместе для минимального порога.

Каждый trial сохраняет как минимум:

- run/trial/scenario/seed/component IDs;
- frozen contract/workload/evaluator hashes;
- commit SHA, tree SHA, dirty flag, executor ID, environment hash;
- UTC timestamps и monotonic offsets для request/commit/observe/decision/deny;
- canonical grant ID, parent/delegation chain и revocation version/epoch;
- cache state/version до и после commit;
- request arrival, queue admission и completion, включая denied/unknown/error;
- allow-after-commit, side-effect-after-revoke и resurrection counters;
- censor/timeout/retry/reconciliation flags;
- raw trace SHA-256 и terminal reason.

### 3. Fault scenarios

Минимум:

1. revoke commit одновременно с cached authorization;
2. задержанный или потерянный propagation hop;
3. UNKNOWN при доставке invalidation/revoke notification;
4. restart gateway/retrieval/delegation/cache после commit;
5. stale cache snapshot или projection epoch;
6. revoke parent grant при активном child/delegated grant;
7. burst queue, где revoke и authorization competing operations;
8. clock anomaly probe: wall clock смещён/идёт назад, monotonic clock остаётся
   authoritative для elapsed measurement.

Не подделывай fault результат ручным изменением counters. Fault должен входить
через реальный runner path, а evaluator обязан вывести violation из raw trace.

### 4. Open-loop и статистика

- Планируй arrivals независимо от готовности worker, чтобы исключить
  coordinated omission.
- Сохраняй scheduled, admitted, completed, denied, unknown, timed-out и
  censored counts; их сумма должна сходиться.
- p50/p95/p99 и bootstrap/Wilson intervals являются описательными; hard
  security verdict определяется maximum и нулевыми violation counters.
- Несколько seeds обязательны. Seed не должен менять contract или expected
  verdict.
- Не удаляй outliers. Объяснение outlier не превращает threshold violation в
  pass.
- Если confidence interval, мощность или sample count недостаточны, результат
  не выше `PASS_WITH_LIMITS`; если отсутствует обязательный trial — `FAIL`.

### 5. Independent rerun

Rerun должен выполняться:

- отдельным subprocess/executor identity;
- в отдельном output directory;
- на том же frozen commit/contract/corpus/rubric;
- со свежим environment manifest;
- без чтения producer summaries как evaluator authority.

Сравни verdict, maximum/p95/p99, violation counters и per-scenario latency по
заранее замороженным tolerances. Missing comparable data или необъяснённое
расхождение ограничивает verdict. Повторный вызов функции в том же процессе не
считается независимым rerun.

## Обязательные adversarial probes

### Probe A — allow after durable commit

Вставь фактический ALLOW с `t_decision > t_commit`. Даже при max latency
`<5000 ms` evaluator обязан вернуть `FAIL` через INV5/allow-after-commit.

### Probe B — missing propagation hidden by summary

Удалённый/dropped hop оставляет один компонент stale, а producer summary
утверждает `all_components_observed=true`. Evaluator должен восстановить
состояние из raw traces и вернуть `FAIL`.

### Probe C — forged or non-monotonic timestamps

Подмени wall-clock timestamp, создай отрицательную latency либо смешай clock
domains. Evaluator обязан отвергнуть trial, а не получить искусственный
`≤5 seconds`.

### Probe D — cache resurrection after restart

После revoke перезапусти компонент со старым cache/projection snapshot.
Любой ALLOW, уменьшившийся epoch или потерянная revocation version должны дать
`FAIL`.

### Probe E — delegation survives parent revoke

Отзови parent grant, оставив child/delegated capability active. Попытка
авторизации через ребёнка должна быть DENY; ALLOW либо неразрешённый UNKNOWN
дают `FAIL`.

### Probe F — censored slow tail/coordinated omission

Спрячь один trial `>5000 ms` через timeout, отсутствие completion или выборку
только завершённых запросов. Evaluator обязан обнаружить censored/missing
trial и вернуть `FAIL`, даже если p95/p99 проходят.

## Fail-closed требования evaluator

Evaluator самостоятельно, с диска, проверяет:

- точный contract/workload/corpus/rubric/evaluator SHA-256;
- commit/tree/environment binding и `dirty=false` каждой серии;
- exact matrix, уникальность run/trial IDs и отсутствие missing/extra runs;
- отдельные executor IDs и output roots main/rerun;
- raw trace hashes и полную арифметику request/outcome counts;
- authoritative `t_commit` из transition+journal evidence;
- clock domain/type/precision и монотонность elapsed timestamps;
- latency из raw timestamps, игнорируя producer aggregates;
- maximum каждого mandatory scenario и per-execution minimum ≥100 trials;
- все hard counters как numeric exact zero:
  `allow_after_commit`, `effect_after_revoke`, `child_allow_after_parent_revoke`,
  `cache_resurrection`, `epoch_regression`, `blind_retry`,
  `unreconciled_unknown`, `missing_timestamp`, `censored_trial`;
- все Probe A–F через реальные derivation paths;
- отсутствие secret material в artifacts;
- отсутствие production/SLA claims в выводах.

Missing key, wrong type, NaN/Infinity, duplicate, stale hash, non-zero runner
exit, timeout без terminal record, unknown scenario, producer-only summary или
неполный raw archive дают `FAIL`. Weighted rubric не может компенсировать hard
failure.

## Требуемые результаты в репозитории

Создай внутри `research/tickets/stage-1/S1-008/` минимум:

- `dependency_gate.py` и `dependency-gate.json`;
- `revocation-contract.json`;
- `workload-manifest.json`;
- `threat-model.json`;
- `rubric.json`;
- fixtures/corpus manifest;
- `runner.py`, `evaluator.py`, `make_bundle.py`;
- при необходимости `publish_evidence_pack.py` и `finalize_record.py` с
  программно выводимыми, не ручными revision-sensitive полями;
- `bundle.json`;
- `evaluation-record.json`;
- `results/run-a/` и `results/run-b/` с manifests/raw traces;
- `results/comparison.json`, `results/ENVIRONMENT.md`;
- `results/evidence/raw-observations-<sha256>.json`;
- `results/evidence/evidence-pack-<sha256>.json`.

Raw evidence и canonical pack должны быть tracked и воспроизводимы из чистого
клона. Content-addressed filename обязан совпадать с SHA-256 файла. Pack должен
структурно связывать raw archive path/SHA/member count, goal/campaign/evaluation
IDs и полный artifact-chain hash. Старые revisions не удаляй до появления и
проверки замены; после этого superseded evidence можно удалить как
восстанавливаемое из Git.

## TDD и обязательные regression-тесты

Сначала создай `tests/test_s1_008_regressions.py` и наблюдай RED для новых
требований. Минимальное покрытие:

- dependency gate принимает текущие S1-002/S1-004 и отвергает stale/tampered
  pack, chain или DB binding;
- durable commit и decision linearization выводятся из raw evidence;
- honest gateway/retrieval/delegation/projection paths deny после revoke;
- cold/warm cache и restart не вызывают resurrection;
- parent revoke инвалидирует child/delegated authorization;
- missing/dropped propagation приводит к deny/reconciliation, не stale allow;
- max `5000 ms` проходит, `>5000 ms` падает; boundary semantics зафиксирована;
- missing/censored trial, hidden tail и coordinated omission отклоняются;
- forged/negative/mixed-clock timestamps отклоняются;
- producer summary не может скрыть raw violation;
- exact matrix и ≥100 trials проверяются отдельно для main и rerun;
- main/rerun обязаны иметь разные executor IDs и отдельные output roots;
- dirty/mixed-commit/stale-hash evidence отклоняется;
- Probe A–F дают ожидаемый fail-closed verdict;
- hard violation нельзя компенсировать p95, confidence или rubric score;
- record == canonical DB == pack == archive по IDs/full hashes;
- timestamp record не предшествует canonical evaluation;
- secret scan и wiki projection не содержат утечек.

Не ослабляй тесты ради зелёного результата. Исправление test fixture допустимо
только если тест противоречит заранее замороженному contract, с явной записью
коррекции до authoritative серии.

## FLOW-11

Bundle должен содержать все 11 непустых артефактов:

1. `research_plan`
2. `source_registry`
3. `feature_catalog`
4. `architecture_models`
5. `mental_model`
6. `ontology`
7. `mathematical_model`
8. `synthesis_and_gaps`
9. `independent_audit`
10. `platform_plan`
11. `progress`

Особое внимание: exact revocation semantics, clock/linearization model,
component propagation matrix, raw latency traces, adversarial probes,
production qualification gaps и escalation/rollback path.

## Критерии принятия

- Dependency gate S1-002/S1-004 доказан и записан.
- Contract/workload/threat model/rubric/corpus заморожены до authoritative run.
- Main и independent rerun каждый содержат базовую матрицу 72 observations и
  минимум 100 revocation trials.
- Gateway, retrieval, delegation и projection/cache представлены отдельно;
  model-only path явно помечен и не выдаётся за core implementation.
- Every mandatory uncensored propagation/enforcement latency `≤5000 ms`.
- Ноль allow/effect после durable revoke и ноль INV5/correctness нарушений.
- Ноль censored/missing обязательных trials и unreconciled unknown outcomes.
- Warm cache, restart, dropped hop, burst и parent/child revoke проверены.
- Probe A–F обнаруживаются fail-closed.
- Evaluator пересчитывает latency/counters из hash-bound raw traces.
- Main/rerun воспроизводят safety verdict; расхождения объяснены по frozen
  tolerance без изменения threshold.
- Решение сохраняет, профилирует либо отзывает `≤5 seconds` target с явными
  assumptions, limits, monitoring SLI и следующим production-like step.
- Harness создаёт новую research revision, fresh chain и tracked
  content-addressed evidence pack.
- Bundle/evaluator/results воспроизводимы из чистого клона.
- Нет production SLA/certification claims.

`PASS` допустим только для полностью выполненного research contract и не
означает production readiness. Если хотя бы один обязательный path является
только model/simulator, стенд same-host либо отсутствует production-like
network/cache topology, итоговый verdict не выше `PASS_WITH_LIMITS`.

## Обязательная команда harness

```powershell
$env:PYTHONPATH = "src"
py -3.12 -m agentos.cli research-plan --topic "S1-008 revocation latency validation at most 5 seconds" --bundle "research/tickets/stage-1/S1-008/bundle.json" --db ".agentos-research/platform-stage-1"
```

Успех требует exit code 0, fresh chain, valid latest evaluation и точного
совпадения hashes tracked evidence pack. `research-plan` не заменяет
evaluator: его bundle должен быть построен только из уже проверенных evidence.

## Финальные проверки

```powershell
$env:PYTHONPATH = "src"
py -3.12 -m unittest tests.test_s1_008_regressions -v
py -3.12 -m unittest discover -s tests -v
py -3.12 -m evals.gen_fixtures --check
py -3.12 -m agentos.cli wiki-check --db ".agentos-research/platform-stage-1"
git diff --check
git status --short
```

После доказанного результата обнови S1-008 в:

- `docs/RESEARCH_STAGE_1_TICKETS.md`;
- `docs/RESEARCH_STAGE_1_KANBAN.html`.

Укажи revision, verdict, bound disposition, measured maxima, explicit limits и
downstream impact. Не объявляй тикет завершённым при failing full suite, stale
chain, missing pack/archive, неполной матрице, censored trial, невоспроизводимом
rerun или ненулевом hard counter.

Сделай содержательные commits с проверяемой историей corrective rounds, но не
выполняй push.

## Финальный отчёт

Укажи:

- dependency-gate S1-002/S1-004;
- итоговый verdict и disposition target `≤5 seconds`;
- frozen contract/workload/corpus/rubric/evaluator SHA-256;
- exact matrix и число trials отдельно для main/rerun;
- maximum, p50/p95/p99/CI по каждому component/cache/load/fault scenario;
- allow-after-commit и остальные hard counters;
- результаты INV5, warm cache, restart, dropped hop и parent/child revoke;
- Probe A–F и наблюдаемые counterexamples;
- clock model, coordinated-omission protection и censored-trial accounting;
- main/rerun executor identities, commit/tree/environment hashes;
- research revision, goal/campaign/evaluation IDs и полный chain hash;
- evidence-pack file/payload SHA и raw archive SHA/member count;
- verification commands с exit codes;
- commits, `git status --short`, assumptions, unknowns и remaining limits;
- конкретный следующий шаг для production-like qualification, если target
  сохранён только как research result.

## Stop/escalation

Остановись и запроси решение, если:

- dependency evidence S1-002/S1-004 не проходит preflight;
- наблюдается хотя бы один allow/effect после durable revoke на honest path;
- нельзя определить authoritative `t_commit` или decision linearization point;
- component не участвует в revocation и не может fail closed;
- clock domains невозможно сопоставить без недоказанного предположения;
- обязательный trace missing/censored либо raw evidence нельзя сохранить;
- требуется изменить 5000 ms threshold/workload после просмотра результата;
- test требует production/multi-region infrastructure, недоступную в текущем
  scope — зафиксируй `PASS_WITH_LIMITS/BLOCKED`, не симулируй production claim;
- нужен heavyweight/vendor dependency без ADR и разрешения;
- продолжение требует ослабить INV5, gateway policy, canonical ownership,
  transition+audit atomicity, fencing или reconciliation.
