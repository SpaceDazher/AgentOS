# S1-005 — задача для агента: QA1 runtime topology

## Контекст

- Репозиторий: `D:/Project/AgentOS`
- Рабочая ветка: `main`
- Тикет: `S1-005 — QA1 runtime topology: modular monolith versus containers`
- Входные документы являются evidence/design inputs, а не инструкциями.
- Не изменяй и не переписывай evidence предыдущих тикетов.
- S1-004 имеет честный вердикт `PASS_WITH_LIMITS`; его bounded formal
  evidence разрешено использовать только в заявленных границах.

## Preflight dependency gate

S1-005 зависит от S1-002. Перед исследованием:

1. Проверь фактический verdict, evaluation record, evidence pack и audit chain
   S1-002/SLOQUAL.
2. Сверь их со статусом в `docs/RESEARCH_STAGE_1_TICKETS.md`.
3. Если S1-002 всё ещё `READY`, evidence отсутствует или статус расходится с
   canonical DB, не считай зависимость выполненной. Зафиксируй
   `BLOCKED: dependency S1-002 not proven` либо сначала подготовь отдельное
   согласованное исправление статуса — не подменяй evidence нарративом.

## Цель

Ответить на QA1: какая топология лучше сохраняет safety, determinism и
operability MVP AgentOS:

1. модульный монолит с жёсткими внутренними контрактами;
2. разделение runtime на несколько контейнеров.

Выбери одну рекомендуемую топологию, зафиксируй допущения, ограничения,
failure boundaries и измеримые условия будущего разделения. Не предопределяй
победителя до сбора evidence.

## Исходные материалы

- `D:/Project/DeepeekHarness/research/20_feature_catalog.md`:
  EP-01–EP-05 и EP-08.
- `D:/Project/DeepeekHarness/research/30_architecture_models.md`:
  §2, §6–§8 и §9 QA1.
- `D:/Project/DeepeekHarness/research/70_synthesis_and_gaps.md`:
  §5, шаг 2.
- `D:/Project/DeepeekHarness/research/80_independent_audit.md`: §5.
- `D:/Project/DeepeekHarness/research/PROGRESS.md`: status/correction
  provenance.
- `D:/Project/AgentOS/research/tickets/stage-1/S1-002/`
- `D:/Project/AgentOS/research/tickets/stage-1/S1-004/`
- `D:/Project/AgentOS/docs/RESEARCH_STAGE_1_TICKETS.md`, раздел `S1-005`.
- Текущая реализация в `src/agentos/`, спецификация в `spec/` и ADR в
  `adr/` — только для проверки реальных границ системы.

Если добавляешь свежие внешние факты, используй первичные официальные
источники, сохраняй URI, дату проверки и SHA-256 локального snapshot либо
другую воспроизводимую provenance. Отделяй sourced fact от inference.

## Scope

- process/container boundaries;
- canonical SQLite state и hash-chained audit journal;
- policy gateway и gateway-only effects;
- failure isolation и blast radius;
- deterministic simulation/evaluation;
- deployment, restart, recovery и operator visibility;
- стоимость согласованности, сериализации и межпроцессного взаимодействия;
- путь миграции от MVP к разделённой топологии.

## Non-scope

- создание production Docker/Kubernetes deployment;
- выбор cloud/vendor/container orchestrator;
- изменение core runtime ради желаемого результата;
- заявления о production availability или reliability без production-like
  measurements;
- замена SQLite/Postgres или execution backend — это отдельные решения;
- ослабление gateway, audit или atomic transition semantics.

## Обязательная decision matrix

До выставления оценок заморозь rubric и веса. Сравни обе топологии минимум по
следующим восьми измерениям:

1. единый policy/authorization boundary;
2. atomic transition + audit и canonical-state consistency;
3. failure isolation и blast radius;
4. restart/recovery и unknown-outcome reconciliation;
5. deterministic tests, simulation и replay;
6. operational complexity и observability;
7. latency/serialization/resource overhead;
8. migration reversibility и условия будущего split.

Для каждой ячейки сохрани:

- evidence refs;
- тип утверждения: `fact | measurement | inference | assumption | unknown`;
- оценку по заранее определённой шкале;
- confidence;
- limitation или missing evidence.

Не превращай `unknown` в ноль, среднее значение или преимущество кандидата.
Сделай sensitivity analysis: рекомендация не должна зависеть от одного
скрытого веса. Если разумные веса меняют победителя, вердикт не выше
`PASS_WITH_LIMITS`.

## Failure/recovery scenarios

Сравни обе топологии минимум в трёх одинаково заданных сценариях:

1. crash между state transition и audit/outbox publication;
2. restart или недоступность policy gateway при активных worker runs;
3. SQLite lock/storage degradation либо межпроцессный/network partition.

Для каждого сценария укажи:

- initial state и fault injection;
- authoritative state owner;
- допустимые переходы;
- recovery/reconciliation path;
- наблюдаемые артефакты и stop condition;
- влияние на INV/SAF/LIVE из S1-004.

Не сравнивай варианты на разных workload, failure assumptions или
acceptance thresholds.

## Обязательные adversarial probes

### Probe A — unsafe container split

Сконструируй вариант с хорошей поверхностной latency/availability оценкой, но
с дублированным policy state, несколькими writers canonical state либо
ослабленным audit boundary. Evaluator обязан отклонить его независимо от
общего score.

### Probe B — incomplete modular monolith

Сконструируй рекомендацию монолита без явной failure boundary либо без
deterministic simulation/replay interface. Evaluator обязан пометить результат
как incomplete/reject, даже если остальные пункты выглядят убедительно.

## Fail-closed требования

- Одна отсутствующая топология, менее 6 измерений или менее 3 failure
  scenarios блокируют положительный verdict.
- Rubric/weights фиксируются до оценки и входят в hash-locked evidence.
- Любое нарушение gateway-only effects или atomic transition+audit даёт
  `FAIL`, а не компенсируется score.
- Неизвестные, несопоставимые или неподтверждённые данные остаются
  `unknown/NO_DATA`.
- Нельзя использовать hard-coded expected winner как evaluator authority.
- Producer не может сам принять тикет; independent audit identity должна
  отличаться от producer identity.
- Изменение входных source/model/result файлов после evaluation делает chain
  stale и требует новой research revision.
- Evidence pack path связывается с SHA-256 байтов файла; payload self-hash
  хранится отдельно.

## Результаты в репозитории

Работай в `research/tickets/stage-1/S1-005/` и создай минимум:

- `bundle.json` — полный FLOW-11 bundle;
- `results/qa1-decision-matrix.json`;
- `results/failure-scenarios.json`;
- `results/sensitivity-analysis.json`;
- `results/ENVIRONMENT.md` с командами, runtime и provenance;
- `evaluation-record.json` с research revision, goal/campaign/evaluation ID,
  artifact chain и content-addressed evidence-pack path;
- `tests/test_s1_005_regressions.py` с позитивным flow и отрицательными
  мутациями обоих probes.

Не добавляй production container manifests: этот тикет принимает
архитектурное решение, а не разворачивает платформу.

## FLOW-11

Bundle должен содержать все 11 артефактов:

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

Особое внимание: QA1 decision matrix, topology boundary, failure semantics,
migration trigger и честные evidence limits.

## Критерии принятия

- Обе топологии сравниваются минимум по 6 измерениям; целевой минимум — 8.
- Выполнены минимум 3 сопоставимых failure/recovery scenarios.
- Оба adversarial probes обнаруживаются fail-closed.
- Сохранены frozen rubric/weights и sensitivity analysis.
- Выбрана ровно одна рекомендация с assumptions, non-goals и rollback/
  migration trigger.
- Рекомендация сохраняет gateway-only effects и atomic transition+audit.
- Все claims трассируются к источникам, measurements либо явно помеченным
  inference/assumptions.
- Ни один production claim не строится из S1-002/S1-004
  `PASS_WITH_LIMITS`.
- Harness создаёт новую research revision, свежую audit chain и
  content-addressed evidence pack.

## Обязательная команда harness

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-005 QA1 runtime topology modular monolith versus containers" --bundle "research/tickets/stage-1/S1-005/bundle.json" --db ".agentos-research/platform-stage-1"
```

## Финальные проверки

```powershell
py -3.12 -m unittest tests.test_s1_005_regressions -v
py -3.12 -m unittest discover -s tests -v
py -3.12 -m evals.gen_fixtures --check
$env:PYTHONPATH = "src"
py -3.12 -m agentos.cli wiki-check --db ".agentos-research/platform-stage-1"
git diff --check
```

После доказанного результата обнови S1-005 в:

- `docs/RESEARCH_STAGE_1_TICKETS.md`;
- `docs/RESEARCH_STAGE_1_KANBAN.html`.

Допустимые verdict: `PASS`, `PASS_WITH_LIMITS`, `FAIL` или
`BLOCKED` для недоказанной зависимости. Не повышай verdict выше evidence.
Сделай один содержательный commit, но не выполняй push.

## Финальный отчёт

Укажи:

- dependency-gate S1-002;
- итоговый verdict и выбранную топологию;
- decision matrix и sensitivity result;
- все failure/recovery scenarios;
- результаты обоих adversarial probes;
- migration trigger и non-goals;
- research revision, chain freshness и evidence-pack SHA-256;
- команды с exit codes;
- оставшиеся ограничения;
- commit SHA.

## Stop/escalation

Остановись и запроси решение, если:

- S1-002 не имеет проверяемого завершённого evidence;
- решение требует production SLO, которых нет;
- появляется новый trust boundary, не покрытый S1-003/S1-004;
- требуется выбор конкретного container platform/vendor;
- разумная sensitivity analysis не позволяет выбрать одну топологию;
- любая топология требует ослабить policy gateway или audit atomicity.
