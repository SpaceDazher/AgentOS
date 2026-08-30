# S1-005 — Review R1

Проверены коммиты:

- 571fdfc — выравнивание статусов W0;
- 5c5dcb5 — заявленное закрытие S1-005.

## Вердикт

**REVISE — пока не пушить и не считать S1-005 закрытым.**

Тесты и локальные проверки зелёные, но независимые негативные пробы обнаружили несколько fail-open путей. Текущий evidence pipeline позволяет получить положительный вердикт при нарушенных ограничениях или неполных доказательствах.

## Findings

### 1. [P1] Нарушение hard constraints не блокирует кандидата

Evaluator собирает нарушения ограничений, но фактически отклоняет только сценарий Probe A. Реальный кандидат может содержать другое нарушение и остаться победителем.

Наблюдаемый repro: добавление нарушения «single canonical state owner» в monolith не помешало выбрать его победителем со score 3.72.

Требуется:

- зафиксировать полный перечень hard constraints;
- отклонять любой реальный кандидат при любом таком нарушении;
- добавить негативные тесты для обоих кандидатов и каждого ограничения.

### 2. [P1] Bundle сам назначает себе положительный вердикт

make_bundle.py не запускает и не разбирает evaluator и experiments как обязательные внешние доказательства. Вместо этого audit verdict, scores и часть narrative записываются заранее как PASS_WITH_LIMITS.

Требуется:

- запускать evaluator отдельным subprocess;
- требовать exit code 0, валидный JSON, ожидаемую schema и корректные hashes;
- вычислять итоговый verdict из результатов, а не задавать константой;
- проверять результаты экспериментов до включения их в bundle.

### 3. [P1] Evidence packs не воспроизводимы из Git-клона

Evaluation records S1-001, S1-002, S1-003 и S1-005 ссылаются на файлы внутри игнорируемого каталога .agentos-research. Локальные хеши совпадают, но независимый аудитор не получит эти пакеты из GitHub.

Дополнительно: в базе S1-005 последняя research revision равна 2, но evaluation-record не фиксирует research_revision.

Требуется:

- публиковать tracked content-addressed evidence pack;
- различать SHA файла и SHA нормализованного payload;
- записывать точную research revision;
- добавить тест воспроизводимости pack из чистого клона.

### 4. [P1] Decision matrix допускает манипуляцию

Дублированное измерение принимается и меняет итоговый score monolith с 3.72 до 3.7627. Удаление evidence_refs и confidence также не блокирует оценку.

Тест test_unknown_mapped_to_score_fails не доказывает fail-closed поведение: он заменяет unknown на inference и проверяет успешное исчезновение unknown, а не отказ при числовом score для неизвестного значения.

Требуется:

- обеспечить уникальность dimensions и ровно одну строку на candidate × dimension;
- требовать evidence_refs, confidence и statement;
- проверять существование всех source references;
- выполнять классификацию claims на стороне harness;
- запрещать преобразование unknown в числовой score.

### 5. [P1] Failure scenarios проверяются только на присутствие

Три сценария с пустыми fault, transition, recovery, artifacts, stop condition, invariant и state owner всё равно дают PASS_WITH_LIMITS и победу monolith.

Требуется:

- ввести строгую schema failure scenarios;
- запрещать пустые обязательные поля и ветви;
- требовать уникальные scenario IDs;
- проверять сопоставимость одного и того же fault между архитектурами;
- требовать ссылки на INV, SAF и LIVE;
- добавить негативные тесты типов и пустых значений.

### 6. [P2] Sensitivity analysis не сохраняет заданные веса

Генератор S2 независимо обрезает значения и применяет max(1), поэтому сумма весов получается от 100 до 102. В наблюдаемой серии 33 из 200 векторов не суммировались в 100. При равенстве score победитель зависит от порядка insertion через max.

Требуется:

- генерировать точную положительную целочисленную композицию с суммой 100;
- валидировать сумму перед оценкой;
- классифицировать ties как indeterminate;
- сохранять каждый weight vector и его digest;
- добавить тесты суммы и независимости от порядка.

### 7. [P2] IPC measurements не проверяют семантику ответа

Измерения IPC учитывают время вызова, но не требуют корректного response JSON, ожидаемого allow/reason/count и успешного завершения дочернего процесса или сервера.

Требуется:

- строго валидировать response JSON и обязательные поля;
- проверять exit code;
- доказывать одинаковый semantic outcome для сравниваемых вариантов;
- добавить негативные тесты для crashed child и corrupt response.

## Наблюдаемая верификация

    python -m unittest tests.test_s1_005_regressions -v
    17/17 OK

    python -m unittest discover -s tests -v
    Ran 338 tests, OK (1 skipped)

    python -m evals.gen_fixtures --check
    78 checked, 0 violations

    python -m agentos.cli wiki-check --db .agentos-research/platform-stage-1
    files=1853, links=5165, issues=0, ok=true

    credential-signature scan
    17 files, 0 hits

    git diff --check 92b311e..5c5dcb5
    clean

Зелёные штатные тесты подтверждают отсутствие известных регрессий, но не закрывают независимые негативные пробы выше.

## Условия закрытия corrective round

1. Добавить тесты на каждый finding и сначала наблюдать RED.
2. Исправить authority boundaries, schemas и sensitivity semantics.
3. Подключить make_bundle к фактическим evaluator и experiment outputs без hardcoded verdict.
4. Повторно выполнить experiments и evaluator.
5. Пересобрать FLOW-11 bundle.
6. Выполнить research-plan с новой revision.
7. Добавить отслеживаемый evidence pack и обновить evaluation record.
8. Повторить полный набор проверок и независимые негативные пробы.
9. До выполнения всех пунктов сохранять статус REVISE и не выполнять push.
