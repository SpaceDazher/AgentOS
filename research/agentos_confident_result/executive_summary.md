# AgentOS: decision-grade результат исследования

**Дата среза:** 21 августа 2026 года  
**Решение:** **GO для проектирования и измеряемого MVP; NO-GO для production-claims до собственных испытаний.**

**Review status:** AI-assisted evidence synthesis после четырёх независимых AI-аудитов; human source review и sign-off ещё не выполнены.

## Что изменилось после проверки

Первичный handoff содержал сильную концепцию, но не позволял проверить её доказательную базу: заявленные «70+ источников» не сопровождались библиографией, локаторами и связями между источниками и тезисами. Поэтому 24 ключевых утверждения были выделены отдельно и повторно проверены по первичным статьям, benchmark papers, стандартам и официальным engineering reports.

Ядро концепции выдержало проверку, но стало точнее:

> **В предлагаемом AgentOS orchestration/enforcement layer применяет protocol-defined transitions над authoritative versioned state.**

Каноническое состояние необходимо для handoff, recovery и audit, но само по себе оно ничего не координирует. Координацию создаёт явный transition protocol: scheduler, ownership, permissions, budgets, validation и commit semantics.

Вторая ключевая поправка относится к завершению задачи:

> **Accepted episode success = evaluator pass(goal state, invariants, process constraints, evidence).**

Система не доказывает, что работа «готова вообще». Она сохраняет ограниченное evidence соответствия наблюдаемого результата конкретным версиям specification, policy и evaluator с документированным покрытием и residual uncertainty.

## Что можно считать достаточно подтверждённым

| Решение | Опора E / J | Практический вывод |
|---|---:|---|
| Hybrid control: deterministic envelope + bounded LLM decisions | M / H | Код и policy удерживают переходы, права, бюджеты, retries и gates; модель адаптируется внутри границ. |
| Durable versioned state вне отдельного worker process | M / H | Workers заменяемы; artifacts, checkpoints, approvals и progress не живут только в диалоге. |
| Harness влияет на outcome; evaluator — на reported score | H / H | Версионировать model, prompt, context policy, tools, environment, resources и evaluator как одну evaluation configuration. |
| Outcome + invariants + обязательный process + evidence | H / H | Текст агента «готово» никогда не является достаточным основанием acceptance. |
| Idempotency, reconciliation, retry budgets и compensation strategy | L в agent domain / H | Каждый retriable effect объявляет idempotency либо порядок сверки/компенсации; небезопасный retry запрещён. |
| Policy-driven context selection | H / H | Context Compiler остаётся provisional composition; retrieval учитывает authority, freshness, conflicts, provenance и budget. |
| Typed provenance и separately versioned evaluation | L / H | Claims, evidence, decisions, executions и requirements связываются адресуемыми assertions. |
| Enforcement вне модели | H для attacks / H | Model output не выдаёт полномочия; executor проверяет каждый tool call в момент исполнения. |
| Multi-agent только для подходящей топологии | M / H | Candidate predictors проверяются matched-resource ablation; production strategy сравнивается также по SLO/cost/latency. |
| Три логических plane | L / M-H | Execution, assurance и governance разделяются интерфейсами, но MVP может быть монолитом. |

`E` — прямой эмпирический эффект, `J` — инженерное обоснование переноса. Уровни являются экспертной оценкой, а не статистическими вероятностями.

## Что не следует превращать в догму

- четыре отдельные graph databases;
- семь независимых memory services;
- multi-agent по умолчанию;
- отдельная модель или persona для каждой роли Creator/Critic/Verifier;
- автоматическое исправление через self-reflection без нового evidence;
- десятичная epistemic confidence без калибровки;
- полное replay внешних side effects;
- автоматическая causal inference из temporal trace;
- guessed expected-value router;
- буквальная мультипликативная формула capability.

Это не обязательно плохие идеи. Сейчас это проверяемые design hypotheses, а не необходимые свойства AgentOS.

## Защищаемая архитектура MVP

AgentOS следует строить как один deployable runtime с тремя логическими зонами ответственности:

1. **Execution control:** goal lifecycle, task dependencies, ownership, conditional leases/fencing для contended или reassigned mutations, isolated runs, checkpoints, retry/reconciliation/compensation.
2. **Assurance control:** immutable artifact versions, claims/evidence/decisions, requirements, evaluations, gates, staleness и world-state verification.
3. **Governance:** capabilities, exact-action approvals, tool trust, budgets, escalation и policy enforcement.

Общие механизмы: transactional transition/audit journal, provisional Context Compiler, identity/versioning, telemetry и object storage. Для baseline достаточно relational database, object store и общего typed relation layer; его минимальность и tamper-evidence нужно проверить. Отдельный graph database нужен только после измеренного traversal workload.

## Рекомендуемый порядок реализации

1. **Сначала evaluation contract.** Определить goal predicates, invariants, process constraints, evidence requirements и набор adversarial near-misses.
2. **Затем canonical data model.** Реализовать immutable versions, relations, runs, activities, checkpoints, gates, approvals и audit events.
3. **После этого durable execution.** Добавить conditional leases/fencing, bounded retries, idempotency keys, reconciliation и recovery tests.
4. **Далее tool gateway и governance.** Проверять capabilities и exact approval на фактических normalized arguments в момент исполнения.
5. **Затем Context Compiler.** Собирать минимально достаточный evidence packet с freshness, provenance и conflict detection.
6. **Только после baseline — topology experiments.** Сравнить single-agent и multi-agent при одинаковых model, tokens, tools и budget.

## Критерии выхода из MVP

MVP можно считать подтверждённым только если он на собственном наборе goal episodes показывает:

- accepted episode success с task-clustered доверительным интервалом;
- repeated reliability: pass^1 и same-goal pass^3/pass^5;
- низкую false-completion rate;
- отсутствие запрещённых effects в security suite;
- корректное восстановление после crash, timeout и stale lease;
- отсутствие duplicate side effects при ambiguous network outcomes;
- unconditional и conditional-on-success cost/latency, а также cost per accepted success;
- evaluator false-positive/false-negative rates на gold, near-miss и альтернативно корректных результатах;
- выигрыш каждого усложнения в заранее определённой ablation.

## Итоговое решение

Исследование достаточно уверенно обосновывает направление: **durable, policy-enforced, evidence-bearing goal execution runtime с заменяемыми вероятностными workers и отдельно версионируемыми gates, использующими независимые evidence channels там, где этого требует риск**. Оно не доказывает, что предложенная композиция уже эффективна как продукт. Следующий правильный шаг — не расширять taxonomy, а реализовать узкий protocol kernel и проверить его на failure-oriented eval suite.

Полная аргументация и локаторы источников находятся в `agentos_evidence_review.md`; row-level связь 24 claims с evidence и counterevidence — в `claim_evidence_matrix.md`, журнал поиска — в `search_log.md`.
