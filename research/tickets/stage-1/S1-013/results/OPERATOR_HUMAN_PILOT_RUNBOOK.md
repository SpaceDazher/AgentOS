# S1-013 — полное ТЗ оператору для утверждения и проведения human pilot

Версия runbook: 1.0, 2026-09-04. Связанный протокол:
`pilot-protocol.json`, версия `1.1.0-draft`.

## 1. Что вы можете утвердить один

Как владелец проекта вы можете единолично принять **операционное решение**:

- утвердить или отклонить текст протокола;
- назначить себя research owner и data steward;
- утвердить consent/privacy/retention правила;
- разрешить разработку human-mode;
- после его проверки разрешить набор участников;
- остановить исследование при инциденте;
- утвердить итоговую публикацию обезличенных агрегатов.

Это разрешение не является результатом исследования. Один человек не может
одновременно заменить:

- выборку из 15–20 участников;
- отдельного второго оценщика ответов;
- независимую проверку результатов;
- требования законодательства, организации или этического комитета, если они
  применимы в вашей юрисдикции.

Если вы лично проходите сценарий, записывайте его как `SELF_PILOT`. Такой сеанс
не входит в human N, C1–C5, fatigue metrics или итоговый выбор интерфейса.

## 2. Текущее состояние и запрет преждевременного запуска

Сейчас техническая подготовка имеет статус:

```text
PREPARATION_READY
human_phase = BLOCKED_HUMAN_PILOT
```

Текущий browser prototype — ускоренный synthetic mock. Текущий importer
намеренно отклоняет human records. Это правильная граница безопасности.
Реальных участников нельзя приглашать в текущий интерфейс до реализации и
отдельной проверки human-mode.

До human-mode можно выполнить только:

- чтение и утверждение документов;
- выбор параметров хранения и удаления;
- назначение ролей;
- подготовку recruitment текста;
- собственный synthetic/self smoke test без включения в данные;
- постановку инженерной задачи на human-mode.

## 3. Результат, который должен получить оператор

Правильный итог работы состоит из четырёх последовательных решений:

1. `PROTOCOL_APPROVED` — документы и правила утверждены.
2. `HUMAN_MODE_VERIFIED` — отдельный human-mode реализован и проверен.
3. `RECRUITMENT_AUTHORIZED` — можно набирать участников.
4. `PILOT_COMPLETE` — 15–20 человек проведены, grading и аудит завершены.

Только после пункта 4 AgentOS может создать каноническую research revision и
рассматривать S1-013 как закрытый. Пропускать решения нельзя.

## 4. Пакет документов для вашего утверждения

Прочитайте полностью и согласуйте между собой:

- `pilot-protocol.json` — authoritative machine-readable protocol;
- `protocol.md` — описание исследования для человека;
- `consent-template.md` — текст информированного согласия;
- `privacy-plan.md` — данные, доступ, хранение, удаление;
- `facilitator-guide.md` — неизменяемый сценарий ведущего;
- `analysis-plan.md` — denominators, scoring и uncertainty;
- `rubric.json` — правила C1–C5 и dual rating;
- `scenario-manifest.json` — задачи и approval prompts;
- `schemas/*.schema.json` — форматы записей;
- `results/CORRECTIVE_R1.md` — доказательства подготовки и ограничения.

При расхождении prose и JSON приостановите утверждение. Сначала создаётся новая
версия протокола и tests, затем новый freeze. Нельзя исправлять только один из
дублирующих документов после начала сбора.

## 5. Решения, которые вы должны заполнить

Ниже обязательные поля. Не оставляйте `TBD`, квадратные скобки или устные
договорённости к моменту `PROTOCOL_APPROVED`.

### 5.1 Владельцы

- Research owner: ваш **неперсональный operator ID**, например `OP-OWNER-01`.
- Data steward: operator ID; может совпадать с research owner.
- Facilitator: operator ID; может быть вами.
- Primary rater: operator ID; может быть вами, если вы не видите оценку rater 2
  до фиксации собственного решения.
- Second rater: **другой человек**, не вы и не участник; blind к оценке rater 1.
- Release reviewer: желательно другой человек; если его пока нет, итоговая
  публикация остаётся заблокированной.
- Контакт для вопросов/withdrawal: частный канал вне Git.

ФИО, email и телефон не записываются в репозиторий. В Git используются только
operator IDs. Соответствие ID ↔ человек хранится отдельно под вашим контролем.

### 5.2 Состав выборки

Текущий target: 16 завершивших участников:

- 8 в роли `owner`;
- 8 в роли `reviewer`.

Допустимый итоговый диапазон протокола: 15–20. До набора выберите правило для
нечётного N и replacements. Рекомендуемая фиксация:

```text
target_completed = 16
owner_target = 8
reviewer_target = 8
recruitment_cap = 20
replacement = только новый pseudonymous ID после exclusion/dropout
```

Нельзя исключать человека за плохое понимание или ради красивого процента.
Каждый starter, exclusion, dropout и completed отражается в participant flow.

### 5.3 Eligibility

Подтвердите текущие условия:

- совершеннолетний участник;
- базовая компьютерная грамотность;
- ранее не использовал AgentOS;
- дал информированное согласие;
- понимает язык сценариев;
- не является автором/оценщиком данного исследования.

Если условия меняются, выпускается новая версия до recruitment.

### 5.4 Компенсация и recruitment

До приглашения зафиксируйте:

- источник участников;
- будет ли компенсация и её одинаковое правило для всех;
- что компенсация не зависит от правильности ответов;
- что отказ/withdrawal не наказывается;
- текст приглашения без обещания пользы или «правильного результата»;
- процедуру предотвращения duplicate enrollment;
- способ присвоения `P-XXXXXX`, не раскрывающий личность.

### 5.5 Privacy, retention и deletion

Выберите и запишите конкретные сроки:

- срок хранения контактных данных;
- срок хранения signed consent;
- срок хранения re-identification key;
- withdrawal window и канал запроса;
- срок хранения restricted raw records;
- какие агрегаты можно хранить бессрочно;
- дата уничтожения каждой категории;
- кто имеет доступ и как доступ отзывается;
- место encrypted backup и кто проверяет восстановление.

Минимизируйте срок и объём. Не используйте Git, wiki, issue tracker, чат агента
или evidence pack для контактов, подписей, consent originals и ключа
реидентификации.

### 5.6 Recording и free text

По текущему плану:

- audio/video — выключены;
- screen recording — выключена;
- реальные credentials/files — запрещены;
- наружная telemetry — запрещена;
- verbatim free text не публикуется по умолчанию;
- coded answers и monotonic timings разрешены;
- потенциально идентифицирующий free text удаляется/обобщается перед release.

Если нужна запись, это новая privacy scope и новая consent version. Остановитесь
и выполните применимую локальную legal/ethics проверку; этот runbook не является
юридическим заключением.

### 5.7 Stop conditions и incident owner

Назначьте себя или другого operator ID владельцем инцидентов. Сбор немедленно
останавливается при:

- отказе/withdrawal участника;
- дискомфорте;
- PII или secret в экспортируемом record;
- ошибке consent/version/assignment;
- недоступности безопасного хранилища;
- утечке или ошибочном доступе;
- подсказке правильного ответа до первичной фиксации;
- невозможности подтвердить остановку обоих mock agents;
- изменении frozen protocol во время серии.

Возобновление — только отдельным append-only решением с причиной.

## 6. Лист вашего утверждения

Создайте sanitized `operator-approval-record.json`; приватную подпись или полное
ФИО храните отдельно. Рекомендуемая структура:

```json
{
  "schema": "agentos.s1-013.operator-approval/v1",
  "ticket": "S1-013",
  "decision": "PROTOCOL_APPROVED",
  "approver_id": "OP-OWNER-01",
  "approved_at_utc": "YYYY-MM-DDTHH:MM:SSZ",
  "protocol_version": "1.1.0-draft",
  "consent_version": "consent-v1",
  "git_commit": "<40 hex>",
  "approved_hashes": {
    "pilot-protocol.json": "<sha256>",
    "rubric.json": "<sha256>",
    "scenario-manifest.json": "<sha256>",
    "consent-template.md": "<sha256>",
    "privacy-plan.md": "<sha256>",
    "facilitator-guide.md": "<sha256>",
    "analysis-plan.md": "<sha256>"
  },
  "roles": {
    "research_owner": "OP-OWNER-01",
    "data_steward": "OP-OWNER-01",
    "facilitator": "OP-OWNER-01",
    "primary_rater": "OP-OWNER-01",
    "second_rater": null,
    "release_reviewer": null
  },
  "data_policy_ref": "<private policy record id, not a path with PII>",
  "retention_policy_id": "<approved policy id>",
  "ethics_or_local_review": {
    "status": "reviewed|not-required|required-pending",
    "private_reference": "<reference or reason>"
  },
  "conditions": [
    "human-mode must pass independent verification",
    "second rater must be assigned before grading",
    "recruitment needs a separate RECRUITMENT_AUTHORIZED decision"
  ]
}
```

`second_rater=null` допустим для `PROTOCOL_APPROVED`, но блокирует grading и
closure. `required-pending` блокирует recruitment.

Перед commit checker обязан пересчитать hashes с диска и отказать при
placeholder, unknown field, неверном commit или несовпадении bytes.

## 7. Инженерное ТЗ перед набором участников

После `PROTOCOL_APPROVED` поручите агенту отдельный corrective implementation:

1. Добавить **human-mode**, не ослабляя synthetic boundary.
2. Human-mode включается только exact approval record + hashes, а не CLI flag.
3. Browser показывает утверждённую consent version и полный 75-minute flow:
   training 10, comprehension 20, approval A 15, rest 5, approval B 15,
   debrief 10 минут.
4. Реализовать AB/BA по enrollment parity и seed `13013`.
5. Экспортировать versioned envelope; не отправлять данные по сети.
6. Не помещать oracle/rater verdict в participant UI.
7. Реализовать pause/resume/withdrawal и остановку записи после withdrawal.
8. C5 начинает время на `task_presented` и требует acknowledgements `A-1` и
   `A-2`; timeout/missing остаются failures.
9. Approval rate использует только active interval, исключает rest,
   comprehension, pauses и infeasible probe.
10. Human importer проверяет consent/approval hashes, unique session и
    participant, chronology, assignment, schema, privacy и storage destination.
11. Human records записываются только в approved restricted location. В Git
    разрешены schema, code, synthetic fixtures и approved aggregates.
12. Реализовать отдельные blinded rater-1/rater-2 inputs, disagreement record и
    adjudication. Никакой rater не переписывает первичный ответ.
13. Publisher fail closed при отсутствии participant flow, rater 2, privacy
    release, protocol deviation log, frozen hashes или complete denominators.

Обязательные negative tests:

- CLI flag без signed/hashed approval не включает human-mode;
- self-pilot не входит в human N;
- один человек не может быть participant и rater своего ответа;
- один rater или `adjudicated=true` не дают correctness;
- consent/version/hash mismatch отклоняется;
- duplicate participant/session отклоняется;
- PII/secret/raw consent карантинируется и не попадает в Git;
- missing/timeout/slow C5 остаётся в denominator/distribution;
- pause/rest/comprehension не увеличивают active approval time;
- withdrawal прекращает дальнейшие events;
- stale saved summary/verdict не проходит fresh recomputation.

## 8. Проверка human-mode до recruitment

До первого приглашения выполните по порядку:

1. Full automated suite — exit 0.
2. Реальный browser → export → human importer → evaluator dry run.
3. Synthetic adversarial probes A–H — все обнаружены.
4. Privacy scan по всем artifact paths — zero releases.
5. Freeze exact code/protocol/schema/fixtures hashes.
6. Два process-separated replay дают одинаковые synthetic results.
7. Один `SELF_PILOT` лично вами — только usability smoke, всегда excluded.
8. После self-pilot либо подтверждается frozen version, либо создаётся amendment
   и все проверки повторяются. Нельзя исправить интерфейс после начала human N
   без новой cohort/version.
9. Второй человек проверяет, что consent, withdrawal и rater separation реально
   работают. Если второго человека пока нет — `RECRUITMENT_AUTHORIZED` нельзя
   выставлять.

## 9. Отдельное разрешение на recruitment

Когда human-mode и документы готовы, создайте второе sanitized решение:

```text
decision = RECRUITMENT_AUTHORIZED
protocol_version = <точная версия>
human_mode_commit = <40 hex>
human_mode_verification_pack_sha256 = <64 hex>
recruitment_cap = 20
target_completed = 16
owner_target = 8
reviewer_target = 8
second_rater_id = <другой человек>
private_storage_policy_id = <id>
incident_owner_id = <id>
```

Если хотя бы одного поля нет, статус остаётся `BLOCKED_HUMAN_PILOT`.

## 10. Проведение каждой сессии

### До прихода участника

- Создать случайный pseudonymous ID `P-XXXXXX`.
- Проверить отсутствие duplicate enrollment в приватной таблице.
- Назначить role и AB/BA order по frozen rule.
- Проверить protocol/consent/human-mode hashes.
- Открыть локальный mock; никаких production permissions/data.
- Подготовить private consent storage и restricted record destination.

### Перед началом

- Дать участнику consent-v1 и время задать вопросы.
- Явно сказать: добровольно, можно пропускать/останавливать, без штрафа.
- Получить согласие до любой записи.
- Подписанный документ убрать в private storage, не фотографировать в Git.
- В research record записать только pseudonym, consent version и факт согласия.

### Сценарий 75 минут

1. Training — 10 минут.
2. Comprehension C1–C5 — 20 минут.
3. Approval block A/B — 15 минут.
4. Rest — 5 минут.
5. Approval block B/A — 15 минут.
6. Debrief — 10 минут.

Facilitator читает scripted intro дословно и не подсказывает правильный ответ
до фиксации primary response. Timings берутся только из monotonic browser
events; ручная оценка времени запрещена.

### При проблеме

- Withdrawal: немедленно остановить collection; partial record сохранить или
  удалить согласно consent/withdrawal rule; participant flow обновить.
- Technical failure: остановить task, записать deviation, не повторять скрытно.
- Discomfort: остановить session без давления продолжать.
- PII: карантин, уведомление data steward, запрещена публикация.
- Нельзя создавать новую «успешную» session вместо плохой под тем же человеком.

### После сессии

- Проверить число/последовательность events и hashes.
- Записать completed/dropout/excluded строго по frozen rule.
- Отделить contact/consent mapping от pseudonymous record.
- Не смотреть aggregate score для изменения сценария/threshold.
- Сделать encrypted backup и проверить manifest.

## 11. Grading C1–C5

### Независимое кодирование

1. Rater 1 получает pseudonymous answers без identity и без rater-2 результатов.
2. Rater 2 получает те же answers в другом blind package.
3. Оба применяют frozen `rubric.json`.
4. Decisions append-only; не редактировать прошлую оценку.
5. Disagreement сохраняется явно.
6. Research owner выполняет предусмотренную adjudication по validity
   explanation. Неразрешённое disagreement остаётся missing, не correct.

C4: ответ `no` без правильного объяснения не считается пониманием.
C5: correct только когда оба mock agents подтверждены не позднее 30000 ms от
presentation; click без confirmation, timeout и missing — failure.

Ни LLM, ни participant UI, ни producer summary не являются human rater.

## 12. Анализ

Основная единица N — человек, не clicks/prompts.

Для каждого C1–C5 сохранить:

- presentations `n`;
- correct, incorrect, missing, timeout/failure;
- rate и Wilson 95% interval;
- `target_met`, `not_met` или `inconclusive`;
- raw denominator reconciliation.

Approval-load по participant и role:

- prompts shown;
- approve/deny/abstain;
- oracle accuracy;
- median/p90 latency;
- active minutes;
- prompts per active hour;
- fatigue отдельно от behavioural errors;
- A/B order/learning effect;
- missingness и incomplete blocks.

Short 15-minute block, пересчитанный в час, не доказывает hour-long stamina.
Маленькие strata 8+8 не называются representative.

Если final N вне 15–20, denominators не сходятся, rater 2 отсутствует или
protocol versions смешаны, итог — `INCONCLUSIVE/BLOCKED`, а не PASS.

## 13. Privacy release review

Перед переносом чего-либо в tracked evidence:

- просканировать все nested fields, filenames и free text;
- удалить contacts, consent originals, signatures, reidentification key;
- проверить редкие комбинации role/error, которые могут идентифицировать;
- suppress/coarsen risky cells;
- подтвердить, что withdrawal/deletion requests исполнены;
- записать withheld artifacts и причину;
- сформировать manifest и hashes разрешённых агрегатов;
- получить release approval от назначенного reviewer.

Если независимого release reviewer нет, публикуйте только минимальные агрегаты
после ручного self-review и оставляйте limitation; raw human data не помещайте
в Git ни при каких обстоятельствах.

## 14. Canonicalization и закрытие

После grading, анализа, privacy review и независимого rerun:

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-013 mental-model comprehension and approval-fatigue pilot" --bundle "research/tickets/stage-1/S1-013/bundle.json" --db ".agentos-research/platform-stage-1"
python -m agentos.cli wiki-check --db ".agentos-research/platform-stage-1"
```

Команды выполняются один раз над финальным reviewed bundle. Затем проверить:

- research result совпадает с audit verdict;
- `latest_evaluation_valid=true`;
- `chain_fresh=true`;
- IDs goal/campaign/evaluation совпадают с DB и pack;
- pack content-addressed и tracked;
- все разрешённые artifact hashes совпадают с Git bytes;
- полный test suite и corpus check exit 0;
- `git diff --check` clean;
- wiki check `ok=true`;
- документация/Kanban не завышают вывод.

Допустимые исследовательские исходы:

- targets met;
- targets not met;
- mixed;
- inconclusive.

Все четыре могут закрыть **исследование**, если процесс и evidence полны.
Нельзя менять плохой результат на PASS только ради закрытия тикета.

## 15. Финальный Definition of Done

S1-013 закрыт только если все пункты отмечены:

- [ ] Protocol approval записан с exact hashes.
- [ ] Consent/privacy/retention заполнены без placeholders.
- [ ] Применимая local ethics/legal проверка выполнена или документированно не
      требуется компетентным владельцем.
- [ ] Human-mode реализован и отдельно проверен.
- [ ] Recruitment authorization записан.
- [ ] Второй независимый rater назначен.
- [ ] 15–20 реальных участников учтены в participant flow.
- [ ] Target role quotas/отклонения объяснены.
- [ ] Все missing/dropout/exclusion/timeout сохранены.
- [ ] Dual rating и adjudication завершены.
- [ ] Frozen analysis выполнен без post-hoc threshold changes.
- [ ] Independent process replay совпал.
- [ ] Privacy release review завершён; raw PII отсутствует в Git.
- [ ] FLOW-11 bundle прошёл evaluator.
- [ ] Canonical IDs/chain/evidence pack проверены.
- [ ] Full suite, corpus, wiki и diff checks зелёные.
- [ ] Ограничения N=15–20 и same-context pilot явно записаны.

## 16. Что вы можете сделать сегодня без других людей

1. Прочитать документы из §4.
2. Заполнить решения §5 без персональных данных в Git.
3. Выбрать retention/deletion, private storage и incident process.
4. Определить recruitment source/compensation и target 8+8.
5. Решить применимость local ethics/legal review.
6. Сформировать sanitized `PROTOCOL_APPROVED` record с hashes.
7. Заказать реализацию human-mode по §7.
8. После её проверки пройти один `SELF_PILOT`, не включая себя в N.
9. Найти второго rater и release reviewer.
10. Только затем подписать `RECRUITMENT_AUTHORIZED`.

Пока пункт 9 не выполнен и нет участников, правильный статус:

```text
S1-013 technical preparation = READY
S1-013 protocol approval = может быть выполнено одним operator
S1-013 human evidence = NOT COLLECTED
S1-013 ticket = OPEN / BLOCKED_HUMAN_PILOT
```
