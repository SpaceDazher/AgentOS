# AgentOS / Traceable Goal Execution Harness

## Доказательно откалиброванный синтез и защищаемая baseline-архитектура

**Дата среза:** 21 августа 2026 года  
**Статус:** provisional decision-grade synthesis после независимых AI-аудитов; не implementation specification и не human peer review

## Аннотация

Первичный handoff содержал сильную архитектурную гипотезу, но не являлся аудируемым исследовательским результатом: в нём отсутствовали библиография, поисковый журнал, критерии включения, локаторы и связи claim → source. Проверка была поэтому выполнена заново как критический scoping review первичных статей, benchmark papers, стандартов и официальных engineering reports.

Главная идея выдержала проверку в уточнённой форме. Long-horizon agent harness следует строить как гибридную систему: детерминированный control plane удерживает полномочия, инварианты, durable state, бюджеты, переходы, retries и gates; LLM выбирает действия там, где путь нельзя надёжно задать заранее. Каноническое состояние, версии артефактов, checkpoints, изоляция среды, idempotency, world-state verification, process constraints и provenance имеют хорошую доказательную или инженерную основу.

Несколько исходных тезисов оказались слишком сильными. Не доказаны обязательность четырёх физических графов, семи независимых memory layers, multi-agent по умолчанию, универсальная польза self-reflection, числовая epistemic confidence без калибровки и буквальная мультипликативная формула capability. Более защищаемая формула такова:

> **Within the proposed AgentOS, orchestration and enforcement coordinate workers by applying protocol-defined transitions over authoritative versioned state.**

Готовность также нельзя доказать абсолютно. Система может принять episode только по наблюдаемому соответствию конкретным версиям specification, policy и evaluator:

> **Accepted episode success = evaluator pass(goal state, invariants, process constraints, evidence).**

## 1. Исследовательский вопрос

Какие механизмы имеют прямые эмпирические свидетельства влияния на reliability, traceability, recoverability и safety long-horizon agent execution, какие имеют сильное инженерное обоснование для переноса, и какая проверяемая baseline-архитектура AgentOS следует из этих двух классов оснований?

Подвопросы:

1. Какие тезисы первичного handoff являются подтверждёнными, условно поддержанными, проектными гипотезами или переобобщениями?
2. Когда deterministic workflow, adaptive agent loop и multi-agent decomposition полезны либо вредны?
3. Какие control, evidence, evaluation, security и recovery механизмы входят в provisional MVP baseline и как проверить их необходимость?

## 2. Метод

Работа выполнена как критический scoping review с design synthesis. PRISMA-статус не заявляется: корпус смешивает peer-reviewed papers, benchmark papers, нормативные спецификации, официальную документацию и first-party engineering reports, а поле быстро меняется.

Поиск был разделён на независимые потоки:

- durable orchestration, checkpoints, leases, retries и compensation;
- multi-agent systems и coordination tax;
- agentic software engineering и влияние harness;
- reasoning, reflection, critic и verifier loops;
- context management, memory и staleness;
- operational evals, world state и repeated reliability;
- provenance, evidence и decision traceability;
- prompt injection, capabilities, approvals и sandboxing;
- human oversight, cost и model routing.

Включались оригинальные статьи, стандарты, официальные спецификации, first-party repositories и engineering reports с описанной методикой. Marketing claims без метода, вторичные пересказы и непроверяемые ссылки не использовались как основание выводов. Для спорных тезисов отдельно искались counterevidence и matched-budget comparisons.

Reproducibility package: [search protocol](search_log.md), [initial scope](phase1_scoping.md), [24-claim inventory](claim_inventory.md), [final claim-to-evidence matrix](claim_evidence_matrix.md), [root-inspected source notes](sources_root.md) и [intermediate architecture synthesis](architecture_draft.md). Точный ranked search history и полный rejected-candidate count не были сохранены, поэтому работа является partially reproducible critical scoping review, а не systematic review.

Для каждого тезиса раздельно оценивались две оси:

| Ось | High | Medium | Low |
|---|---|---|---|
| **E: empirical effect** | Несколько прямых исследований либо сильная контролируемая абляция. | Одиночное, узкое, vendor-specific или benchmark-specific сравнение. | Прямого сравнительного эффекта нет либо evidence противоречиво. |
| **J: engineering justification / transfer** | Зрелый стандарт или механизм с прямой семантической применимостью и понятными failure modes. | Правдоподобный перенос с существенными domain caveats. | Design hypothesis, чья необходимость или композиция ещё не проверена. |

`E` отвечает на вопрос «показан ли эффект», а `J` — «насколько защищаемо инженерное решение». Стандарт может дать `J=High`, не давая `E=High`. Уровни не являются вероятностями. Десятичные confidence values не использовались, поскольку они не откалиброваны на собственных данных AgentOS.

## 3. Итоговый аудит 24 тезисов handoff

| ID | Вердикт | E | J | Что делать |
|---|---|---:|---:|---|
| C01 | Поддержан с поправкой | Medium | High | Использовать гибрид: deterministic envelope и bounded agent inference, а не полностью фиксированный pipeline. |
| C02 | Поддержан | Medium | High | Versioned state и artifacts являются system of record; dialogue остаётся средством clarification. |
| C03 | Полезная taxonomy | Low | Medium | Развести workflow, world, epistemic и execution semantics в schema, но не создавать четыре сервиса автоматически. |
| C04 | Split verdict | Low | High для typed provenance; Low для четырёх физических графов | Один canonical relation model с несколькими projections. |
| C05 | Частично поддержан | Low | Medium | Claim packet, counterevidence, freshness и validation plan нужны; не использовать ложную точность confidence. |
| C06 | Не доказан в исходной форме | Medium | Medium | Role labels не создают независимость. Разнообразить evidence channels, tools, models и procedures; измерять covariance ошибок. |
| C07 | Поддержан условно | Medium | High | Рассматривать parallelization для independent, verifiable work с дешёвой интеграцией; проверять matched-resource ablation. |
| C08 | Поддержано разделение функций | Medium | High | Разделять Creator, Critic и Verifier contracts; отдельные agent personas необязательны. |
| C09 | Поддержан условно | Low в agent domain | High | DAG, ownership, leases с fencing и workspace isolation включать при реальной конкуренции или reassignment. |
| C10 | Поддержан | Medium | High | Durable logical state не зависит от конкретного worker/container; resume только из safe checkpoint. |
| C11 | Policy-driven selection поддержан | High | High | Context Compiler является provisional composition для минимально достаточного, свежего и provenance-bearing context. |
| C12 | Exact taxonomy не подтверждена | Medium для external memory; Low для семи stores | Medium | Начать с provisional logical views поверх общего versioned substrate и проверить их ablation. |
| C13 | Инженерно поддержан | Low | High | Tools и skills становятся проверяемыми contracts с pre/postconditions, side effects и audit. |
| C14 | Инженерно поддержан с поправкой | Low | High | Approval должен быть exact-action capability и лишь одним из controls. |
| C15 | Инженерно поддержан | Low в agent domain | High | Каждый retriable side effect требует явной idempotency либо стратегии reconciliation/compensation для ambiguous или partial outcome. |
| C16 | Поддержан частично | Low | High для append-only audit; Medium для full event sourcing | Event-backed architecture, но не replay внешних необратимых эффектов. |
| C17 | Поддержан с важной поправкой | High | High | Accepted success проверяет outcome, invariants, policy-relevant trajectory и evidence validity. |
| C18 | Mixed | Low | Medium | Начать с stale marking по типизированным зависимостям; расширять после eval. |
| C19 | Поддержан условно | Medium, mixed | Medium | Human gate применять на значимых границах, но локально измерять overreliance и approval fatigue. |
| C20 | Design hypothesis | Low в этом корпусе | Medium | Routing обучать на измеренном quality-cost frontier; guessed expected value недостаточен. |
| C21 | Поддержан | High для repeated evaluation | High | Измерять pass^k, false completion, recovery, forbidden effects, cost и environment configuration. |
| C22 | Поддержан | High для attacks | High | Внешние данные недоверенны; capability и policy enforcement живут вне модели. |
| C23 | Защищаемый design synthesis | Low | Medium-High | Execution, assurance/epistemic и governance разделить интерфейсами, но можно развернуть одним сервисом. |
| C24 | Не является научным законом | Low | Low | Оставить как checklist bottlenecks; заменить произведение на измеряемую функцию взаимодействий. |

## 4. Основные результаты

### 4.1 Harness является частью capability

Controlled benchmark ablations показывают, что интерфейс, контекст и feedback могут менять результат при фиксированной модели. На SWE-bench Lite (`n=300`) custom SWE-agent Agent-Computer Interface дал 18,0% против 11,0% у shell-only варианта (Table 1); полный просмотр файла снизил результат до 12,7% относительно окна в 100 строк, а удаление lint feedback снизило его до 15,0% (Table 3) ([Yang et al., 2024](https://arxiv.org/pdf/2405.15793)) <!--ref:yang2024sweagent--><!--anchor:page:6-->. В Agentless (`n=300`) majority selection дал 25,67%, regression testing повысил результат до 27,0%, а reproduction test до 32,0%; candidate-set oracle upper bound, где верен хотя бы один из 40 сгенерированных кандидатов, достигал 42,0% (Figure 6) ([Xia et al., 2024](https://arxiv.org/pdf/2407.01489)) <!--ref:xia2024agentless--><!--anchor:page:14-->.

Это подтверждает два вывода в пределах данных benchmark setups. Во-первых, наблюдаемый outcome зависит от связки model + harness + environment, а не от модели отдельно. Evaluator определяет reported score; он влияет на execution capability только если включён в feedback loop. Во-вторых, больше контекста, planning или candidates не гарантируют улучшения. Selection и verification становятся самостоятельными bottlenecks.

Даже инфраструктура eval влияет на headline score. Во внутреннем first-party experiment Terminal-Bench 2.0 разница между крайними resource configurations достигла 6 процентных пунктов ([Anthropic, 2026, “How we got here”](https://www.anthropic.com/engineering/infrastructure-noise)) <!--ref:anthropic2026infranoise_terminal--><!--anchor:section:How%20we%20got%20here-->. SWE-bench setup из 227 задач × 10 samples изменился на 1,54 пункта при изменении RAM ([Anthropic, 2026, “How this affects measurement”](https://www.anthropic.com/engineering/infrastructure-noise)) <!--ref:anthropic2026infranoise_swe--><!--anchor:section:How%20this%20affects%20measurement-->. AgentOS должен поэтому version-control не только prompt и model, но также action schema, context policy, tool versions, environment image, resource limits и evaluator.

Защищаемое разделение capability и measurement:

> **OutcomeCapability(task) = f(model, harness, tools, context, environment, policy, budget, topology).**  
> **ReportedScore = g(observed outcomes, evaluator, sampling, evaluation infrastructure).**

Эти факторы взаимодействуют. Буквальное умножение из handoff создаёт видимость математического закона без данных.

### 4.2 Нужен hybrid control, а не абсолютный determinism

Определённые задачи выигрывают от заранее заданных workflows, а open-ended задачи требуют model-driven decisions. Practitioner evidence рекомендует predictable workflows для хорошо определённых процессов, agents для путей, которые нельзя заранее зафиксировать, и добавление сложности только когда она нужна ([Anthropic, 2024, “When (and when not) to use agents”](https://www.anthropic.com/engineering/building-effective-agents)) <!--ref:anthropic2024effectiveagents--><!--anchor:section:When%20%28and%20when%20not%29%20to%20use%20agents-->. Более строгий gate «добавлять только после измеренного выигрыша» является локальной policy AgentOS.

Durable workflow systems уточняют, где проходит граница. Orchestrator code должен быть детерминирован относительно записанной history, а недетерминированные LLM, HTTP, database и tool calls выполняются как activities, результаты которых фиксируются и при replay не вызываются заново ([Temporal, Workflow Definition](https://github.com/temporalio/documentation/blob/main/docs/encyclopedia/workflow/workflow-definition.mdx)) <!--ref:temporalworkflow--><!--anchor:section:Deterministic%20constraints-->. Этот принцип переносится на AgentOS:

- deterministic code контролирует allowed transitions, capability grants, budgets, stop conditions, retries и gates;
- модель предлагает decomposition, strategy и next action внутри разрешённого пространства;
- каждое model/tool result становится записанным input следующего перехода;
- replay восстанавливает control flow из истории, но не делает модель детерминированной.

AgentOS не должен запрещать адаптацию. Он должен превращать адаптивное решение в адресуемое событие с inputs, authority и consequences.

### 4.3 Persistent state и artifacts нужны для long horizon

First-party long-horizon experiments обнаружили два повторяющихся отказа: агент пытался выполнить весь проект за одну сессию, либо преждевременно объявлял работу завершённой. Anthropic сообщает снижение этих отказов после введения пакета из structured feature list, progress file, incremental work, git checkpoints и end-to-end browser tests; индивидуальный вклад компонентов не изолирован ([Anthropic, 2025, “Agent failure modes and solutions”](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)) <!--ref:anthropic2025longharness--><!--anchor:section:Agent%20failure%20modes%20and%20solutions-->. Более поздняя архитектура Managed Agents прямо разделяет durable append-only session и заменяемые harness/sandbox activations ([Anthropic, 2026, “Decouple the brain from the hands”](https://www.anthropic.com/engineering/managed-agents)) <!--ref:anthropic2026managed--><!--anchor:section:Decouple%20the%20brain%20from%20the%20hands-->.

Из этого не следует, что conversation бесполезна. Верная граница такова:

- dialogue подходит для ambiguity resolution, negotiation и локального reasoning;
- durable artifact подходит для handoff, audit, recovery, versioning и machine checks;
- conversation summary никогда не является единственной копией требования, решения, approval или progress.

Фраза “Agent ≠ State” также требует точности. Physical worker должен быть disposable, но logical agent/session identity может включать persistent state, как в virtual actor systems. Защищаемое требование: **durable logical state не зависит от конкретной process activation**.

### 4.4 Multi-agent полезен условно и дорог

Лучшее положительное свидетельство относится к breadth-first research. Anthropic сообщает 90,2% improvement внутренней multi-agent системы против single-agent baseline, но также около 15-кратного token use относительно chat и плохую пригодность shared-context или dependency-heavy tasks ([Anthropic, 2025, “Benefits of a multi-agent system”](https://www.anthropic.com/engineering/multi-agent-research-system)) <!--ref:anthropic2025multiagent--><!--anchor:section:Benefits%20of%20a%20multi-agent%20system-->. Публичный отчёт не раскрывает raw scores, N, confidence intervals и matched compute. Он лучше подтверждает пользу дополнительного parallel test-time compute, чем самостоятельную coordination synergy.

Matched-budget studies усиливают ограничение. На декомпозируемой Finance Agent task centralized multi-agent получил сильный выигрыш, но на последовательной PlanCraft все multi-agent топологии потеряли 39-70% ([Kim et al., 2026, arXiv v3, §§4-5](https://arxiv.org/html/2512.08296)) <!--ref:scalingagents2025--><!--anchor:section:4-->. Ошибки моделей также могут быть коррелированы: работа исследовала более 350 моделей в нескольких settings, а на одном leaderboard dataset при условии ошибки обеих моделей одинаковый неправильный ответ выбирался примерно в 60% случаев ([Kim et al., 2025](https://proceedings.mlr.press/v267/kim25e.html)) <!--ref:kim2025correlated--><!--anchor:section:Abstract-->.

Следующие признаки являются candidate predictors положительного эффекта, а не доказанными необходимыми и достаточными условиями:

- branches независимы или слабо связаны;
- каждая ветвь получает полезный отдельный context/tool budget;
- результат ветви имеет локальный verifier;
- integration cost ниже сэкономленного поиска;
- shared mutation редка или изолирована;
- coordination effect сохраняется при matched model, tokens, tools и resource budget.

Matched-resource ablation нужна для причинного вывода о coordination. Production decision затем сравнивает целые стратегии по episode utility, total cost, wall time, risk и SLO; heterogeneous multi-agent система может быть рациональна, даже если она не проходит equal-token ablation.

Canonical state само по себе не координирует. Оно хранит progress и evidence, но не назначает работу, не разрешает конфликт и не определяет sufficiency. Это делает transition protocol: scheduler, ownership, routing, validation и commit semantics.

### 4.5 Creator, Critic и Verifier должны быть функциями, а не “персонами”

Reflexion демонстрирует полезную, но benchmark-specific абляцию. На selected hardest-50 HumanEval Rust base дал 60%, reflection без tests снизила результат до 52%, tests без reflection оставили 60%, а tests + reflection повысили результат до 68% — разница между последними режимами составляет четыре задачи и не сопровождается confidence interval ([Shinn et al., 2023, Table 3](https://proceedings.nips.cc/paper_files/paper/2023/file/1b44b878bb782e6954cd888628510e90-Paper-Conference.pdf)) <!--ref:shinn2023reflexion--><!--anchor:page:8-->. В независимой критике intrinsic self-correction ухудшала GSM8K и CSQA, тогда как oracle correctness feedback улучшал их ([Huang et al., 2024, Tables 2-6](https://proceedings.iclr.cc/paper_files/paper/2024/file/8b4add8b0aa8749d80a34ca5d941c355-Paper-Conference.pdf)) <!--ref:huang2024selfcorrect--><!--anchor:page:4-5-->. Исследование error localization показало, что GPT-4 находил место ошибки примерно в 39,8-52,9% случаев в зависимости от prompting mode; oracle location улучшала исправление ошибочных traces, но correction могла повредить ранее правильные ответы ([Tyen et al., 2024, Tables 4-7](https://aclanthology.org/2024.findings-acl.826.pdf)) <!--ref:tyen2024errorlocation--><!--anchor:page:4-9-->.

Предлагаемый conservative baseline для semantic iteration выглядит так:

1. Verifier возвращает наблюдаемое нарушение, test result, invariant failure или source mismatch.
2. Critic локализует defect и формулирует ремонтопригодную гипотезу.
3. Creator создаёт новую версию, не уничтожая лучший подтверждённый artifact.
4. Полный regression gate повторяется, включая ранее пройденные checks.
5. Новая версия принимается только после независимого evidence.

Три роли могут исполняться одной моделью с разными contracts. Декорреляция ошибок требует разных evidence channels, procedures, deterministic tools, human labels или отдельно обученных verifiers и должна измеряться; смена role name сама по себе её не создаёт.

### 4.6 Policy-driven context selection поддержан; exact memory architecture не подтверждена

Большой context window сам по себе не гарантирует надёжный доступ к информации. Lost in the Middle обнаружил U-shaped positional effect в controlled multi-document QA ([Liu et al., 2024, Fig. 5](https://aclanthology.org/2024.tacl-1.9.pdf)) <!--ref:liu2024lostmiddle_qa--><!--anchor:page:5--> и synthetic retrieval ([Liu et al., 2024, Fig. 7](https://aclanthology.org/2024.tacl-1.9.pdf)) <!--ref:liu2024lostmiddle_retrieval--><!--anchor:page:7-->. LongMemEval декомпозирует систему на indexing, retrieval и reading ([Wu et al., 2025, Fig. 4 and §4.1](https://proceedings.iclr.cc/paper_files/paper/2025/file/d813d324dbf0598bbdc9c8e79740ed01-Paper-Conference.pdf)) <!--ref:wu2025longmemeval_model--><!--anchor:page:7-->. Fact-augmented keys, time-aware query expansion и structured reading давали отдельные улучшения ([Wu et al., 2025, Tables 3-4 and Fig. 6](https://proceedings.iclr.cc/paper_files/paper/2025/file/d813d324dbf0598bbdc9c8e79740ed01-Paper-Conference.pdf)) <!--ref:wu2025longmemeval_results--><!--anchor:page:9-10-->, что поддерживает policy-driven context selection. В single-run GPT-3.5 RAG setup LoCoMo больше retrieved context могло повышать recall, но ухудшать answer quality; summary теряло детали относительно extracted observations ([Maharana et al., 2024, Table 3 and §6.1](https://aclanthology.org/2024.acl-long.747.pdf)) <!--ref:maharana2024locomo--><!--anchor:section:6.1-->.

Предлагаемый Context Compiler и taxonomy остаются design synthesis. MVP может начать с четырёх provisional logical views поверх общего versioned substrate; число четыре не является подтверждённым optimum и проверяется удаляющими ablations:

1. active working context;
2. immutable raw events, artifacts и trajectories;
3. derived facts, summaries, decisions и failure records;
4. procedures, skills и runbooks.

Context Compiler выполняет:

> task intent → authority/freshness filter → multi-path retrieval → rerank/dedupe/conflict detection → budget/order/compress → evidence packet.

Derived record всегда хранит source pointers и не заменяет raw evidence. Update создаёт новую версию и supersession relation, а не стирает прежнюю. Promotion, decay и archive rules должны появляться только после task-specific ablations.

Memory poisoning делает write path частью security boundary. AgentPoison использовал poisoning rate менее 0,1% ([Chen et al., 2024, Abstract](https://proceedings.neurips.cc/paper_files/paper/2024/file/eb113910e9c3f6242541c1652e30dfd6-Paper-Conference.pdf)) <!--ref:chen2024agentpoison_rate--><!--anchor:section:Abstract--> и в своей threat model сообщил mean `ASR-r = 81,2%` и `ASR-t = 62,6%` ([Chen et al., 2024, §4.2](https://proceedings.neurips.cc/paper_files/paper/2024/file/eb113910e9c3f6242541c1652e30dfd6-Paper-Conference.pdf)) <!--ref:chen2024agentpoison_results--><!--anchor:section:4.2-->. MINJA описал query-only persistent injection в shared memory ([Dong et al., 2025, §3](https://proceedings.neurips.cc/paper_files/paper/2025/file/42a97bbd9844d2bf68596730af80bcdf-Paper-Conference.pdf)) <!--ref:dong2025minja_method--><!--anchor:section:3-->; величина результата в Tables 4-5 зависит от архитектуры и benchmark ([Dong et al., 2025](https://proceedings.neurips.cc/paper_files/paper/2025/file/42a97bbd9844d2bf68596730af80bcdf-Paper-Conference.pdf)) <!--ref:dong2025minja_results--><!--anchor:page:8-9-->. Model-generated memory поэтому по умолчанию является derived/untrusted, проходит admission, tenant checks, provenance, TTL и revocation.

### 4.7 Completion требует гибридной verification

Outcome-first evaluation предпочтительна, потому что разные допустимые пути могут приводить к одному правильному состоянию. Обзор всех agent benchmarks не входил в scope этого review; количественный вывод здесь опирается на τ-bench и software-evaluation studies, выбранные для проверки конкретных механизмов. Авторы τ-bench прямо называют совпадение конечной БД necessary but not sufficient: агент может выполнить правильное изменение без обязательного подтверждения пользователя ([Yao et al., 2024, §3](https://arxiv.org/html/2406.12045)) <!--ref:yao2024taubench--><!--anchor:section:3-->.

Итоговый acceptance gate:

~~~text
AcceptedEpisodeSuccess = EvaluatorPass(
    GoalState
AND Invariants
AND ProcessConstraints
AND EvidenceValidity)
~~~

- **GoalState** проверяет наблюдаемый требуемый outcome в пределах доступного oracle.
- **Invariants** защищают unrelated state, regressions и forbidden changes.
- **ProcessConstraints** применяются только там, где путь имеет нормативный смысл: authorization, confirmation-before-write, limits, provenance.
- **EvidenceValidity** требует verifiable receipt, test result, observation или source, а не текст “готово”.

Trace similarity с human path не должна быть общей метрикой. Trace используется для policy-relevant temporal constraints, diagnosis и recovery analysis.

Для заявлений о consistent reliability одной попытки недостаточно. Для task `i` с `c_i` успешными запусками из `n_i` повторов τ-bench оценивает вероятность успеха всех `k` случайно выбранных запусков как:

~~~text
pass^k = mean_i [ C(c_i, k) / C(n_i, k) ],  n_i >= k
~~~

([Yao et al., 2024, §3](https://arxiv.org/html/2406.12045)) <!--ref:yao2024taubench_definition--><!--anchor:section:3-->

Это не `pass@k` («хотя бы один из k») и не следует автоматически приравнивать к `(pass^1)^k`. Оценка предполагает одинаковую семантику задачи, resettable environment и exchangeable repeats. В τ-retail GPT-4o function-calling имел `pass^1 = 61,2%` ([Yao et al., 2024, Table 2 and §5.1](https://arxiv.org/html/2406.12045)) <!--ref:yao2024taubench_pass1--><!--anchor:section:5.1-->, тогда как `pass^8 < 25%` в reported setup ([Yao et al., 2024, Fig. 4 and §5.1](https://arxiv.org/html/2406.12045)) <!--ref:yao2024taubench_pass8--><!--anchor:section:5.1-->. Product reporting должен включать task-clustered confidence intervals для каждого `k`; `pass^10` допустим только при `n_i >= 10` для каждой включённой задачи.

Наконец, evaluator сам является объектом проверки. UTBoost выявил 36 уникальных task instances с недостаточным покрытием в перекрывающихся Lite/Verified splits; после test augmentation и исправления parser были переклассифицированы 176 Lite + 169 Verified patch entries = 345 ранее отмеченных passed submissions ([Yu et al., 2025, §§4.2-4.4](https://aclanthology.org/2025.acl-long.189.pdf)) <!--ref:yu2025utboost--><!--anchor:section:4.2-4.4-->. OpenAI прекратила рекомендовать SWE-bench Verified после аудита 138/500 задач, которые o3 не решал стабильно в 64 независимых runs; как минимум 59,4% этого failure-conditioned subset имели material test/spec problems, и долю нельзя экстраполировать на все 500 tasks ([OpenAI, 2026](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/)) <!--ref:openai2026swebench--><!--anchor:section:Too%20narrow%20and%20too%20wide%20tests-->. Gate сохраняет ограниченное evidence соответствия конкретной specification и evaluator coverage; это не доказательство фактической готовности вне их области.

### 4.8 Provenance нужен, но event log не равен causal proof

W3C PROV-DM определяет Entity, Activity, Agent и соответствующие отношения в нормативных §§5.1-5.3 ([W3C PROV-DM](https://www.w3.org/TR/prov-dm/)) <!--ref:w3cprov--><!--anchor:section:5.1-5.3-->. OSLC Requirements Management §3.1.2 задаёт implementedBy, validatedBy, satisfiedBy и affectedBy ([OASIS OSLC RM 2.1](https://docs.oasis-open-projects.org/oslc-op/rm/v2.1/os/requirements-management-vocab.html)) <!--ref:oslcrm--><!--anchor:section:3.1.2-->. SACM моделирует Claim, ArtifactReference, AssertedInference, AssertedEvidence и AssertedContext; counterevidence задаётся `AssertedEvidence.isCounter=true`, а assumption/defeat — `AssertionDeclaration=assumed|defeated` ([OMG SACM 2.3, §§11.8-11.16](https://www.omg.org/spec/SACM/2.3/PDF)) <!--ref:sacm23--><!--anchor:section:11.8-11.16-->. Эти источники подтверждают typed traceability semantics, но не их эффект на AgentOS outcomes.

Они не подтверждают необходимость четырёх физических графов. Один canonical relation layer с общими IDs и Artifact, Evidence, Execution и Decision projections — совместимая с ними AgentOS design hypothesis, но не требование стандартов. Обязательные edge ID, attribution и lifecycle fields являются более строгим локальным контрактом AgentOS; в PROV идентификаторы многих relations опциональны.

Два исходных edge names требуют изменения:

- Domain/world-effect **CAUSED** нельзя устанавливать только по timestamps, correlation ID или instrumented OpenTelemetry parent/link. OTel parent/child задаёт causal topology самой instrumented trace ([OpenTelemetry Overview, “Traces”](https://opentelemetry.io/docs/specs/otel/overview/#traces)) <!--ref:otel_traces--><!--anchor:section:Traces-->, как и Links между spans ([OpenTelemetry Overview, “Links between spans”](https://opentelemetry.io/docs/specs/otel/overview/#links-between-spans)) <!--ref:otel_links--><!--anchor:section:Links%20between%20spans-->. Эта topology может быть evidence, но не является независимой валидацией domain/world effect; такой effect хранится отдельным Claim с method, scope и evidence.
- `wasInvalidatedBy` в PROV относится к lifecycle Entity. Для опровержения AgentOS моделирует SACM-style AssertedEvidence/AssertedInference с `isCounter=true`; `CHALLENGES` является локальным alias, а Claim получает `assertionDeclaration=defeated` только после adjudication counterevidence.

OpenTelemetry является instrumentation/telemetry model и export pipeline. Telemetry, чей capture/export path допускает `DROP`, non-recording, `RECORD_ONLY` или collector-stage sampling, нельзя без отдельного completeness proof считать полным audit record ([OpenTelemetry Trace SDK, “Sampling”](https://opentelemetry.io/docs/specs/otel/trace/sdk/#sampling)) <!--ref:otel_sampling--><!--anchor:section:Sampling-->. Для обязательных decisions, approvals, effect receipts и gate outcomes AgentOS использует отдельный fail-closed journal без sampling/drop этих record classes; слово `authoritative` применимо только при заданных durability, write authority, tamper-evidence, retention и redaction controls. Event log является evidence лишь внутри объявленной instrumentation/capture boundary; отсутствие записи не доказывает отсутствие события при известных gaps.

### 4.9 Prompt injection является control/data-flow проблемой

В 1 054 synthetic cases InjecAgent base setup ReAct/GPT-4 имел `ASR-valid = 23,6%` при valid rate 98,8% (`ASR-all = 23,3%`); это setup-specific attack rate, не общая вероятность уязвимости ([Zhan et al., 2024, Tables 2-3 and §§2.3, 3.2](https://aclanthology.org/2024.findings-acl.624.pdf)) <!--ref:zhan2024injecagent--><!--anchor:page:6-7-->. В AgentDojo defense comparison с Important Message attack на 629 security cases GPT-4o без защиты имел targeted ASR `57,69% ± 3,9 п.п.`; защиты давали разные trade-offs между security, benign utility и utility under attack ([Debenedetti et al., 2024, Table 5](https://papers.neurips.cc/paper_files/paper/2024/file/97091a5177d8dc64b1da8bf3e1f6fb54-Paper-Datasets_and_Benchmarks_Track.pdf)) <!--ref:debenedetti2024agentdojo--><!--anchor:page:19-->. NIST связывает prompt injection со смешением instruction и data channels и рекомендует проектировать систему с допущением, что model output может быть malicious ([NIST AI 100-2e2025, §§3.4-3.5](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-2e2025.pdf)) <!--ref:nist2025aml--><!--anchor:page:61-66-->.

CaMeL показывает работоспособность одного архитектурного паттерна: trusted control flow отделяется от untrusted data, а capability policy проверяет поток перед tool call. В arXiv v2 для o3 High benign utility составила `77,3% ± 8,3` с CaMeL против `84,5% ± 7,2` у native tool calling ([Debenedetti et al., 2025, Table 2](https://arxiv.org/pdf/2503.18813v2)) <!--ref:google2025camel_utility--><!--anchor:page:32-->. Security оценивалась отдельно: в stated PI-SEC threat model система показала 0 successful attacks в 949 cases ([Debenedetti et al., 2025, Fig. 9](https://arxiv.org/pdf/2503.18813v2)) <!--ref:google2025camel_security--><!--anchor:page:13-14-->. Это поддерживает гипотезу для локальной проверки AgentOS, но не покрывает недоверенный user prompt или memory, text-only manipulation, все side channels и compromised interpreter.

Минимальная threat-model baseline для MVP:

- **Assets:** canonical state, approvals, credentials, tenant data, audit integrity и возможность менять внешний мир.
- **Untrusted by default:** model output, retrieved/external content, tool output, model-generated memory и MCP annotations; атакующий может контролировать внешнее содержимое и использовать штатные memory/tool write surfaces.
- **Trusted computing base:** authenticated identity, policy engine, executor/tool gateway, credential broker, audit sink и выбранная isolation boundary.
- **Обязательные adversarial cases:** malicious/changed tool server, cross-tenant access, credential theft, approval spoof/replay/TOCTOU, gateway bypass, SSRF/egress и policy/audit tampering.
- **Не доказано этим design:** защита от compromised host/kernel, malicious administrator, всех side channels и social engineering.

Предлагаемые security properties, которые нужно enforce и тестировать в пределах этой threat model:

- output модели никогда не создаёт новых полномочий;
- executor проверяет каждый tool call в момент исполнения;
- untrusted content не расширяет task, tool set, scope или approval;
- classified sensitive value не попадает в mediated open-world sink без точной declassification policy; side channels остаются residual risk;
- memory read/write не обходит tenant и capability boundaries;
- worker не получает ambient/bearer credentials, способные обойти gateway;
- authenticated tool server identity, namespace, version и schema hash входят в trust decision;
- при отказе policy, approval или audit high-risk execution закрывается;
- audit фиксирует intent, receipt, доступные pre/post observations и статус `applied`, `rejected`, `unknown` или `reconciled`; world-state diff утверждается только после observation.

Tool metadata не гарантирует поведение сервера. MCP annotations являются hints, которые следует считать недоверенными без установленной server trust ([MCP Tools specification, 2026, “Tool”](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)) <!--ref:mcp2026tool--><!--anchor:section:Tool-->. Tool names не являются глобальной identity вне server namespace ([MCP Tools specification, 2026, “Tool Names”](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)) <!--ref:mcp2026toolnames--><!--anchor:section:Tool%20Names-->. Поэтому локальная policy AgentOS требует pinned server identity, `{server, tool}` namespace и review schema/version с новым consent там, где меняется authority или effect.

“Capabilities лучше RBAC” было переобобщением. Практичная схема комбинирует RBAC/ABAC как базовые права пользователя и task-scoped capability как дополнительное сужение на конкретный run.

### 4.10 Human oversight полезен только как часть системы

Мета-анализ 106 экспериментальных исследований и 370 effect sizes показал, что human+AI в среднем уступал лучшему из человека и AI, Hedges’ g = -0,23, 95% CI [-0,39; -0,07], особенно в decision tasks, при существенной гетерогенности designs ([Vaccaro et al., 2024](https://www.nature.com/articles/s41562-024-02024-1)) <!--ref:vaccaro2024synergy--><!--anchor:section:Overall%20levels%20of%20human-AI%20synergy-->. Исследование не проверяло adversarial agent approvals; тезис «human gate не является oracle» является осторожным design inference, а overreliance и approval fatigue должны измеряться локально.

Approval нужен, когда действие высокорисково или выходит за preauthorization, но он должен быть:

- привязан к actor, task, exact tool version, normalized arguments, target, state/artifact version и policy version;
- ограничен лимитом и expiry;
- invalidated при изменении arguments, target или relevant state;
- защищён nonce/replay control;
- показан authenticated approver через trusted renderer как точное canonical action, target, diff, consequence и reversibility; preview не формируется моделью;
- потребляется атомарно и однократно для exact actor/task/tool/target/arguments/state/policy tuple.

Одномерной шкалы “read → write → external → irreversible” недостаточно. Read private data может быть высокорисковым, а заранее разрешённый idempotent external write может не требовать нового prompt. Policy должна учитывать effect, target, reversibility, idempotency, sensitivity, privilege, blast radius, open-world input и наличие verifiable postcondition.

### 4.11 Retries и cost routing должны быть измеряемыми

RFC 9110 говорит, что client `SHOULD NOT` автоматически повторять non-idempotent request, если он не знает, что операция фактически идемпотентна или первая попытка точно не была применена; для proxy действует `MUST NOT` ([RFC 9110, §9.2.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2)) <!--ref:rfc9110--><!--anchor:section:9.2.2-->. AWS рекомендует caller-generated operation ID и атомарную запись idempotency key вместе с mutation ([Featonby, “Reducing client complexity”](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)) <!--ref:awsidempotency_atomic--><!--anchor:section:Reducing%20client%20complexity-->. Повтор того же key с другим intent должен давать validation error, а initial parameters сохраняются вместе с identifier ([Featonby, “Same client request ID, different intent”](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)) <!--ref:awsidempotency_intent--><!--anchor:section:Same%20client%20request%20ID%2C%20different%20intent-->. Compensation является отдельной business operation и сама может отказать; она не гарантирует буквальный rollback ([Garcia-Molina & Salem, 1987, §4](https://doi.org/10.1145/38713.38742)) <!--ref:sagas1987--><!--anchor:section:4-->.

Retry policy:

- transient transport, throttling и 5xx: bounded exponential backoff с jitter и общим retry budget, только для safe/idempotent action;
- validation, authorization и policy denial: не retry, а correction или новая authority;
- version conflict: reread state и replan;
- unknown mutation outcome: reconcile по operation ID и world state;
- model failure: новый evidence, strategy, model или verifier, но отдельный semantic retry budget;
- failed compensation: pause и human escalation.

Routing literature не была систематически синтезирована в этом review, поэтому конкретный cost-aware router остаётся AgentOS design hypothesis. Защищаемое decision rule: выбирать самую дешёвую стратегию, у которой нижняя confidence bound локально измеренного качества выше SLO, а residual risk ниже tolerance. Multi-agent является одной из оцениваемых стратегий, не автоматической следующей ступенью.

## 5. Provisional reference architecture

### 5.1 Три логических plane

~~~text
User / requester
       |
       v
Goal + success contract
       |
 +-----+----------------------+
 |                            |
 v                            v
Execution control         Assurance control
- lifecycle              +- artifact versions
- task DAG/scheduler     +- claims/evidence/decisions
- lease/checkpoint       +- requirements/evaluations
- workspace/run          +- gates/stale marking
- retry/compensation     +- world-state verification
 |                            |
 +-------------+--------------+
               v
       Policy and governance
       +- capabilities
       +- scoped approvals
       +- trust/provenance
       +- budgets/escalation
               |
               v
       Disposable workers
               |
               v
          Tool gateway
               |
               v
   Sandbox / external world

Cross-cutting: transition/audit journal, context compiler, memory retrieval,
identity/versioning and telemetry.
~~~

Planes являются responsibility boundaries, а не обязательными microservices. MVP может использовать один deployable application и одну transactional database. Для tamper-evident assurance одного application principal недостаточно: accepted transition и audit event фиксируются атомарно, sensitive payload хранится через encrypted/content-addressed reference, correction создаёт superseding event, а high-risk deployment использует отдельную write authority или remote/WORM sink.

### 5.2 Candidate logical objects

| Object | Обязательная семантика |
|---|---|
| Goal | Intent, success predicates, constraints, budget, risk, lifecycle. |
| ArtifactVersion | Immutable version requirements, spec, architecture, plan, code, tests или report. |
| Claim | Proposition, epistemic status, support, counterevidence, freshness, validation plan. |
| Evidence | Source, observation, test result, attestation или world-state measurement с provenance. |
| Decision | Question, alternatives, criteria, assessments, selection, rationale, consequences. |
| Task | Dependencies, owner, lease, inputs, expected outputs, risk, definition of done. |
| Run | Worker attempt, model/harness/tool versions, budget, workspace, terminal reason. |
| Activity | Tool call, evaluation, state mutation или execution step. |
| WorldObservation | Versioned external-state measurement. |
| Evaluation | Subject, method/configuration, result, evidence и reproducibility metadata. |
| Gate | Predicate over state, evidence and policy, yielding PASS, FAIL or ESCALATE. |
| Approval | Issuer/audience, authenticated approver, actor, task, exact tool identity/version, target, canonical arguments, state/policy version, limits, expiry, nonce and one-time atomic consumption. |
| Checkpoint | Consistent recoverable snapshot plus progress and next action. |
| ToolContract | Schema, authority, side effects, trust, retry, rollback and audit policy. |
| MemoryRecord | Provenance, scope, tenant, trust, freshness/TTL and invalidation. |
| RelationAssertion | Typed, attributable and versioned assertion with `sources[1..*]`, target, status and evidence; binary edge is only a projection. |

Requirement, Specification, Architecture, ADR, Plan и Skill можно сначала хранить как typed ArtifactVersion. Отдельная таблица появляется только при distinct invariants или измеренном query volume. Этот список является candidate schema; минимальность проверяется removal ablations и реальными query/invariant requirements.

В модели SLSA attestation — authenticated, machine-readable metadata об одном или нескольких software artifacts; Signature denotes the attester, создавшего attestation ([SLSA v1.2 Attestation Model](https://slsa.dev/spec/v1.2/attestation-model)) <!--ref:slsa12--><!--anchor:section:Model%20and%20Terminology-->. Поэтому AgentOS не трактует успешную authentication как доказательство истинности Predicate. Локальное правило AgentOS: хранить attestation как Evidence вместе с statement subject, predicate payload, explicit predicate type, проверенной signer/attester identity и отдельной Evaluation, фиксирующей verification result.

### 5.3 Candidate provenance kernel

Canonical relation model:

~~~text
WAS_GENERATED_BY(Entity -> Activity)
USED(Activity -> Entity)
WAS_DERIVED_FROM(new Entity -> prior Entity)
WAS_ASSOCIATED_WITH(Activity -> Agent)
WAS_INFORMED_BY(downstream Activity -> upstream Activity)

IMPLEMENTED_BY(Requirement -> WorkProduct|Activity)
VALIDATED_BY(Requirement -> TestResult|Evidence)
DEPENDS_ON(dependent -> prerequisite)
SUPERSEDES(new -> old)
SUPPORTS(Evidence|Claim -> Claim)
CHALLENGES(Evidence|Claim -> Claim)
CONTEXT_FOR(context -> Claim|Decision|Assertion)

ADDRESSES(Decision -> Question)
CONSIDERS(Decision -> Alternative)
SELECTS(Decision -> Alternative)
JUSTIFIED_BY(Decision -> Claim|CriterionAssessment)
HAS_CONSEQUENCE(Decision -> Consequence)
~~~

OSLC predicates выше сохраняют native requirement-to-resource direction. `VALIDATED_BY` является traceability relation, а не PASS assertion; execution result и verdict фиксируются отдельной Evaluation/Evidence. SACM-style support/challenge связи в AgentOS являются reified RelationAssertion с собственной attribution и status, а не утверждением, что упрощённые names являются native SACM vocabulary. `sources[1..*]` сохраняют совместную inference: несколько premises нельзя разложить в независимые pairwise `SUPPORTS` без premise-group semantics. Общий ID/relation layer — MVP-гипотеза, не требование стандартов. Каждая relation имеет assertion ID, schema version, sources and target IDs, asserter, asserted time, valid time, status, qualifiers и evidence refs. Ни одна relation не считается transitive по умолчанию.

### 5.4 Execution semantics

1. Goal получает measurable success contract и constraints; exploratory goal может начать с uncertainty/output contract, но acceptance должен быть уточнён до high-risk execution или release.
2. Harness создаёт versioned artifacts и acceptance evaluations до рискованной implementation.
3. Scheduler выпускает только dependency-ready tasks.
4. Mutating task, допускающий contention либо reassignment после timeout, имеет не более одной valid commit authority; lease используется для liveness, а fencing epoch обязателен, только если authoritative sink умеет отклонять stale owner. Для non-fenceable API применяются serialization, idempotency и reconciliation.
5. Run получает compiled context, capability set, tool contracts, isolated workspace, budget и stop conditions.
6. Mutation проходит tool gateway с operation ID и policy decision.
7. Meaningful unit завершается consistent checkpoint.
8. Evaluator проверяет outcome, invariants, process constraints и evidence freshness.
9. Failed gate создаёт gap task или escalation, но не unbounded retry.
10. Release требует goal-level convergence и human approval только там, где этого требует policy.

## 6. Provisional MVP: что строить, а что отложить

### 6.1 Baseline для удаляющих ablations

- Одна relational database для objects, versions, typed relations, tasks, conditional leases, approvals, idempotency keys и transactional transition/audit journal.
- Object storage для крупных artifacts, traces и snapshots.
- Single-agent execution по умолчанию.
- Parallel read-only research и изолированные mutating workspaces только для dependency-independent tasks.
- Durable run state, checkpoints, bounded retries и reconciliation; fencing только на fenceable contended sinks.
- Context Compiler с provenance, freshness, conflict detection и token budget.
- Tool Registry с authenticated/pinned server identity, `{server, tool}` namespace, reviewed schema/version и host-owned policy metadata; MCP annotations только untrusted hints.
- Exact-action approvals и multi-dimensional risk descriptor.
- Deterministic evaluators first там, где существует valid oracle; иначе calibrated rubric/LLM/human evaluation с измеренными FPR/FNR.
- Workspace isolation для concurrency не считается security sandbox. NIST описывает container risks, связанные с host OS, runtime и management stack ([NIST SP 800-190, §§3.5.2, 4.4-4.5](https://nvlpubs.nist.gov/nistpubs/specialpublications/nist.sp.800-190.pdf)) <!--ref:nist2017containers--><!--anchor:section:3.5.2%3B%204.4-4.5-->. Локальное усиление AgentOS: non-root, read-only base, minimal mounts, no host/runtime socket or inherited credentials, per-run credentials, OS/syscall policy и default-deny egress. Container ограничивает blast radius, но не предотвращает abuse разрешённого tool.
- Controlled eval track и product track с разными compute semantics.
- Три provisional gates: goal/spec ready, execution accepted, release approved.

Каждый baseline-компонент удаляется или упрощается в ablation; только измеренный прирост либо failure prevention переводит его из provisional baseline в обязательный core.

### 6.2 Отложить до собственных ablations

- четыре physical graph databases;
- семь independent memory services;
- uncalibrated decimal confidence scores;
- multi-agent by default;
- automatic invalidation всех descendants;
- generic causal edges;
- full replay внешних side effects;
- dynamic expected-value router на guessed probabilities;
- self-modifying global skills;
- автоматическую promotion agent reflection в project truth.

## 7. Программа валидации AgentOS

Архитектура остаётся гипотезой, пока не измерена на собственных goal episodes. Минимальная experiment program:

| Experiment | Сравнение | Основные метрики |
|---|---|---|
| Hybrid control | Free-form agent loop vs deterministic skeleton + bounded loops | episode success, false completion, cost, forbidden effects |
| Durable handoff | Chat summary only vs structured artifact/checkpoint | resume success, duplicated work, recovery time |
| Multi-agent topology | (a) causal: single vs multi при equal total resources; (b) deployment: стратегии при equal SLO или wall time | accepted success, pass^k, integration defects, total cost/latency |
| Context policy | Full context vs RAG vs adaptive compiler | retrieval recall, reader accuracy, task success, tokens |
| Iteration | Factorial ablation: new evidence, critic, preservation gate и full regression | net correction, regressions introduced, selector precision |
| Recovery | Crash, timeout, stale lease, partial side effect | checkpoint resume, duplicate effects, reconciliation, compensation |
| Security | AgentDojo, InjecAgent, poisoning и local threat cases как отдельные tracks | per-threat-model benign utility, ASR, unauthorized world change, exfiltration |
| Evaluator quality | Blind, double-labeled, adjudicated gold; near-miss, alternative valid solutions, reward hacks | component/overall FPR/FNR, flakiness, agreement |

Перед запуском каждого experiment фиксируются:

- sampling frame локальных задач, стратифицированный по horizon, risk, reversibility, side effects и human interaction, плюс held-out set;
- число задач и repeats, power rationale либо pre-specified precision target, seeds, stopping rule и exclusions;
- paired/randomized allocation на одинаковых tasks, reset environments и порядок прогонов;
- primary estimand, decision threshold и uncertainty analysis с task-clustered confidence intervals;
- для matched resources — input/output/cached tokens, tool calls, tool/CPU runtime, context allocation и parallel calls; equal-total-cost и equal-wall-time являются разными estimands;
- evaluator gold labels создаются независимо от системы и самого evaluator и проходят adjudication.

Каждый goal episode сохраняет:

- observed initial and final world-state snapshots with measurement method, scope/boundary and freshness;
- goal and acceptance predicates;
- policy, capabilities and budget;
- model, harness, prompt, tool, schema and environment versions;
- action/event trace with correlation IDs, OTel parent/link topology where used, declared capture contract and completeness indicators (instrumented components/signals, sampler configuration/decision, recording/sampled state, export outcome and known gaps); domain/world-effect causal Claims сохраняются отдельно вместе с method, scope and evidence;
- checkpoints, retries and recovery events;
- artifacts, evidence and evaluator results;
- cost, wall time, tool calls and human interventions.

Headline metrics публикуются с явными numerator, denominator, exclusions и confidence interval:

- accepted episode success и отдельный partial progress;
- pass^1 с task-clustered 95% confidence interval;
- same-goal pass^3, pass^5 и pass^10;
- false-completion rate;
- invariant and forbidden-effect violation rate;
- checkpoint-resume, reconciliation and compensation correctness;
- duplicate-side-effect rate;
- recovery under injected faults;
- unconditional cost/latency, conditional-on-success cost/latency и cost per accepted success;
- p95/p99 только при достаточном effective sample size и с uncertainty; иначе они остаются exploratory.

## 8. Решение по результатам review

Первичный handoff был концептуально сильным, но доказательно незавершённым. После проверки предлагаемая reference architecture формулируется так:

> **The proposed AgentOS is intended to be a durable, policy-enforced goal-execution runtime in which an orchestration/enforcement layer coordinates replaceable probabilistic workers by applying protocol-defined transitions over canonical versioned state, while separately versioned evaluation uses independent evidence channels where risk requires them.**

По-русски:

> **Предлагаемый AgentOS — durable runtime управления целями, где orchestration/enforcement layer координирует заменяемых вероятностных workers через protocol-defined transitions над каноническим версионируемым состоянием, а отдельно версионируемая проверка использует независимые evidence channels там, где этого требует риск.**

Самые сильные основания относятся к execution plane, context/interface и verification. Provenance, governance и epistemic control хорошо поддержаны стандартами и security research, но их точная композиция в AgentOS остаётся design synthesis. Multi-agent, memory taxonomy, change propagation и cost routing должны быть опциями, включаемыми после собственных matched-budget evals.

Главное практическое изменение относительно handoff:

> **Не “state coordinates agents”, а “в AgentOS enforcement layer применяет protocol-defined transitions над authoritative state”.**

И второе:

> **Не “system proves done”, а “system records bounded evidence of conformance as assessed by a versioned evaluator with documented coverage, TCB assumptions and residual uncertainty”.**

## 9. Ограничения

- Review не является exhaustive systematic review и не имеет PRISMA flow.
- Exact ranked search history, pre-deduplication candidate count и полный exclusion log не сохранены; воспроизводимость частичная.
- AI-specific evidence часто представлено vendor reports без независимой replication и component ablation.
- Некоторые 2025-2026 работы остаются preprints.
- Benchmark tasks короче, безопаснее и чище production workloads.
- Harness, model, tools, environment и evaluator часто меняются одновременно, что мешает причинной атрибуции.
- Benchmark contamination и evaluator defects ограничивают точность headline scores.
- Исследование не запускало собственный AgentOS prototype и поэтому не доказывает performance предложенной композиции.
- Security properties ограничены заявленной threat model и TCB; они не являются certification и не покрывают compromised host/kernel, malicious administrator или все side channels.
- `E/J` labels являются экспертной калибровкой доказательств, не статистическими вероятностями.
- Четыре независимых research streams/audits были AI-to-AI; human source verification и accountability sign-off остаются внешним gate.

## 10. AI and review disclosure

Отчёт подготовлен в Codex desktop с AI-assisted multi-agent research. AI использовался для извлечения claims из handoff, разделения поисковых потоков, discovery и чтения первичных источников, cross-source synthesis, drafting и четырёх независимых AI-аудитов: Devil’s Advocate, evaluation/reliability, security/integrity и provenance. Pipeline сопоставлял количественные claims с оригинальными статьями, официальными спецификациями или first-party reports; это AI-to-AI control, а не human verification или security certification.

Точный backend model snapshot и полный ranked search history не экспортированы в artifacts, что ограничивает воспроизводимость. Ответственным за принятие и публикацию результата остаётся владелец проекта; независимый human source review и sign-off ещё не выполнены. Перед внешней публикацией владелец также должен подтвердить допустимость раскрытия исходного handoff и применимые confidentiality/provider terms.

## 11. References

Featonby, M. (n.d.). *Making retries safe with idempotent APIs*. Amazon Web Services Builders’ Library. https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/

Anthropic. (2024). *Building effective agents*. https://www.anthropic.com/engineering/building-effective-agents

Anthropic. (2025a). *Effective harnesses for long-running agents*. https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents

Anthropic. (2025b). *How we built our multi-agent research system*. https://www.anthropic.com/engineering/multi-agent-research-system

Anthropic. (2026a). *Quantifying infrastructure noise in agentic coding evals*. https://www.anthropic.com/engineering/infrastructure-noise

Anthropic. (2026b). *Scaling Managed Agents: Decoupling the brain from the hands*. https://www.anthropic.com/engineering/managed-agents

Chen, Z., et al. (2024). *AgentPoison: Red-teaming LLM agents via poisoning memory or knowledge bases*. *Advances in Neural Information Processing Systems, 37*. https://proceedings.neurips.cc/paper_files/paper/2024/file/eb113910e9c3f6242541c1652e30dfd6-Paper-Conference.pdf

Debenedetti, E., et al. (2024). *AgentDojo: A dynamic environment to evaluate prompt injection attacks and defenses for LLM agents*. *Advances in Neural Information Processing Systems, 37*. https://papers.neurips.cc/paper_files/paper/2024/file/97091a5177d8dc64b1da8bf3e1f6fb54-Paper-Datasets_and_Benchmarks_Track.pdf

Debenedetti, E., et al. (2025). *Defeating prompt injections by design* (Version 2). arXiv. https://arxiv.org/abs/2503.18813v2

Dong, Y., et al. (2025). *MINJA: Memory injection attacks on LLM agents via query-only interaction*. *Advances in Neural Information Processing Systems, 38*. https://proceedings.neurips.cc/paper_files/paper/2025/file/42a97bbd9844d2bf68596730af80bcdf-Paper-Conference.pdf

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110). RFC Editor. https://www.rfc-editor.org/rfc/rfc9110.html

García-Molina, H., & Salem, K. (1987). Sagas. In *Proceedings of the 1987 ACM SIGMOD International Conference on Management of Data* (pp. 249–259). ACM. https://doi.org/10.1145/38713.38742

Huang, J., et al. (2024). *Large language models cannot self-correct reasoning yet*. *International Conference on Learning Representations*. https://proceedings.iclr.cc/paper_files/paper/2024/file/8b4add8b0aa8749d80a34ca5d941c355-Paper-Conference.pdf

Kim, E. M., Garg, A., Peng, K., & Garg, N. (2025). Correlated errors in large language models. In *Proceedings of the 42nd International Conference on Machine Learning* (pp. 30038–30066). PMLR. https://proceedings.mlr.press/v267/kim25e.html

Kim, Y., et al. (2026). *Towards a science of scaling agent systems* (Version 3). arXiv. https://arxiv.org/abs/2512.08296v3

Liu, N. F., et al. (2024). Lost in the middle: How language models use long contexts. *Transactions of the Association for Computational Linguistics, 12*, 157–173. https://aclanthology.org/2024.tacl-1.9.pdf

Maharana, A., et al. (2024). Evaluating very long-term conversational memory of LLM agents. In *Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics*. https://aclanthology.org/2024.acl-long.747.pdf

Model Context Protocol. (2026). *Tools: Specification 2026-07-28*. https://modelcontextprotocol.io/specification/2026-07-28/server/tools

National Institute of Standards and Technology. (2025). *Adversarial machine learning: A taxonomy and terminology of attacks and mitigations* (NIST AI 100-2e2025). https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-2e2025.pdf

National Institute of Standards and Technology. (2017). *Application container security guide* (NIST SP 800-190). https://nvlpubs.nist.gov/nistpubs/specialpublications/nist.sp.800-190.pdf

OASIS Open Project. (n.d.). *OSLC Requirements Management Version 2.1: Part 2, Vocabulary*. https://docs.oasis-open-projects.org/oslc-op/rm/v2.1/os/requirements-management-vocab.html

Object Management Group. (n.d.). *Structured Assurance Case Metamodel, Version 2.3*. https://www.omg.org/spec/SACM/2.3/PDF

OpenAI. (2026). *Why SWE-bench Verified no longer measures frontier coding capabilities*. https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/

OpenTelemetry. (n.d.). *Trace SDK: Sampling*. https://opentelemetry.io/docs/specs/otel/trace/sdk/#sampling

OpenTelemetry. (n.d.). *Overview: Tracing signal*. https://opentelemetry.io/docs/specs/otel/overview/#tracing-signal

Shinn, N., et al. (2023). Reflexion: Language agents with verbal reinforcement learning. *Advances in Neural Information Processing Systems, 36*. https://proceedings.nips.cc/paper_files/paper/2023/file/1b44b878bb782e6954cd888628510e90-Paper-Conference.pdf

SLSA. (2025). *Attestation model, Version 1.2*. https://slsa.dev/spec/v1.2/attestation-model

Temporal Technologies. (n.d.). *Workflow definition*. https://github.com/temporalio/documentation/blob/main/docs/encyclopedia/workflow/workflow-definition.mdx

Tyen, G., et al. (2024). LLMs cannot find reasoning errors, but can correct them given the error location. In *Findings of the Association for Computational Linguistics: ACL 2024*. https://aclanthology.org/2024.findings-acl.826.pdf

Vaccaro, M., Almaatouq, A., & Malone, T. W. (2024). When combinations of humans and AI are useful: A systematic review and meta-analysis. *Nature Human Behaviour, 8*, 2293–2303. https://www.nature.com/articles/s41562-024-02024-1

World Wide Web Consortium. (2013). *PROV-DM: The PROV data model*. https://www.w3.org/TR/prov-dm/

Wu, D., et al. (2025). LongMemEval: Benchmarking chat assistants on long-term interactive memory. *International Conference on Learning Representations*. https://proceedings.iclr.cc/paper_files/paper/2025/file/d813d324dbf0598bbdc9c8e79740ed01-Paper-Conference.pdf

Xia, C. S., et al. (2024). *Agentless: Demystifying LLM-based software engineering agents*. arXiv. https://arxiv.org/abs/2407.01489

Yang, J., et al. (2024). SWE-agent: Agent-computer interfaces enable automated software engineering. *Advances in Neural Information Processing Systems, 37*. https://arxiv.org/abs/2405.15793

Yao, S., Shinn, N., Razavi, P., & Narasimhan, K. (2024). *τ-bench: A benchmark for tool-agent-user interaction in real-world domains*. arXiv. https://arxiv.org/abs/2406.12045

Yu, J., et al. (2025). UTBoost: Rigorous evaluation of coding agents on SWE-bench. In *Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics*. https://aclanthology.org/2025.acl-long.189.pdf

Zhan, Q., et al. (2024). InjecAgent: Benchmarking indirect prompt injections in tool-integrated large language model agents. In *Findings of the Association for Computational Linguistics: ACL 2024*. https://aclanthology.org/2024.findings-acl.624/
