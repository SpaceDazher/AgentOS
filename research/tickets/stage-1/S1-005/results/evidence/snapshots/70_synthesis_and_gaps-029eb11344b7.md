# 70 — Синтез исследования и карта пробелов

Статус: v2, независимо проаудирован (раунд 13). Сводит доменные каталоги (`sources/*.md`, 13 доменов,
235 первичных строк до дедупликации) и пять модельных артефактов в единые выводы; фиксирует пробелы
для будущих итераций. Трассировка: `{H…}` гипотезы, `[домен:ID]` источники.

## 1. Сквозные выводы по доменам

| Домен | Главный вывод для хаба | Ключевые источники |
|---|---|---|
| A протоколы | A2A+MCP покрывают transport/task/tool, но не delegation/ownership/knowledge → хаб-контракт обязателен {H9} | [A1,A6,A11] |
| B identity/delegation | Полный стек OAuth+SPIFFE+macaroons/biscuit даёт все примитивы attenuated delegation без долгоживущих секретов {H4} | [B4–B6,B17,B18,B20,B22] |
| C авторизация | ReBAC-граф + decidable policy core + RLS как второй рубеж; отрицательные права через deny-by-default, не материализованные denies {H5,H14} | [C5,C8,C10,C13,C14] |
| D/E MAS+LLM | Ошибки координации и injection распространяются топологией; gateway-only control plane и typed messages обязательны {H7,H8} | [D5,D14,E6,E15,E16,E21] |
| F/L онтология+формал | PROV-O/SHACL/SKOS достаточны для переносимого слоя знаний; Datalog/Alloy/TLA дают проверяемые инварианты {H16} | [F4,F6,F8,F16,F18,F19,L3,L10,C8,C10] |
| G/H приватность+распределённость | E2EE (MLS/MIMI) и CRDT/local-first — зрелые пути профилей B/C; admin-blind privacy несовместима с server-side индексацией {H12} | [G1,G3,G3b,G12,G14,G15] |
| I угрозы | Prompt injection/tool poisoning/supply-chain — подтверждённые классы атак; изоляция+сканирование+digest pinning обязательны | [I3,I8,I9,I11,I12,I13,I14] |
| J математика | Token bucket/Little/M-M-c/Beta — аппарат для плановых квот, capacity и promotion; параметры требуют benchmark/pilot {H1,H10} | [J1,J2,J3,J9,J13] |
| K HCI | Calibration>trust; permission fatigue подтверждён; Art.14 используется как voluntary benchmark, если система не классифицирована high-risk {H15} | [K1,K3,K4,K7,K9,K10] |
| M prior art | Индустрия сходится к per-agent principals и scoped credentials; ни один продукт не решает delegation+knowledge gate целиком | [M2,M5,M6,M8,M17,M18] |

## 2. Что глубокое исследование изменило в исходном концепте

| Гипотеза | До углубления | После (вердикт) | Драйвер изменения |
|---|---|---|---|
| H4 | «не передавать пароли» | точный механизм: token exchange + authorization_details + DPoP/mTLS cnf | [B4,B5,B6]; инцидент OpenAI connectors |
| H5 | «RBAC мало» | конкретная замена: Zanzibar-tuples ⊕ Cedar-decidable core ⊕ capability grants; отрицательные права только как deny-by-default | [C1,C5,C8,C10,C15] |
| H7 | «всё через gateway» | уточнение: control-plane через gateway; большие артефакты — signed URL напрямую | [A1,E21] |
| H9 | «A2A+MCP хватит» | условно: задачи/инструменты — да; delegation, ownership, promotion, budgets — нет | [A1,A4,A6,A11] |
| H12 | спорная опция | отклонена для baseline: четыре выхода (local exec / key to instance / TEE / отказ от обработки) | [G1,G12] |
| H16 | «нужен evidence gate» | конкретика: lifecycle статусов, Beta-пороги, argumentation attacks, TMS retraction propagation | [F6,F16,F18,F19,J13] |
| H15 | «показывать on-behalf» | дизайн-обязательства: banner+progressive disclosure+attention budget+comprehension-тест | [K7,K9,K10,K3,K4] |

Новые требования, которых не было в исходном документе:
- tool-manifest scanning и output-sanitization gate [M17,M18,I3];
- SBOM/AI-BOM + non-executable model formats [I11];
- deterministic simulation harness как acceptance-инструмент [H17];
- append-only Merkle tree с подписанными checkpoints и inclusion/consistency proofs [I15];
- comprehension-тест UI (метрики §7 `40_mental_model.md`).

## 3. Карта пробелов (gaps)

| # | Пробел | Влияние | Возможный путь закрытия |
|---|---|---|---|
| G-01 | Нет peer-reviewed исследований UX делегирования агентам (только смежные: permission dialogs, XAI) | риски H15-дизайна вслепую | пилотное юзер-исследование на 15–20 участниках; метрики §7 mental model |
| G-02 | MCP/A2A не выражают delegation/knowledge semantics {H9} | hub-контракт остаётся кастомным | следить за roadmap MCP Tasks/A2A extensions; держать канонический конверт адаптируемым |
| G-03 | Количественных моделей agent-hub нагрузок в литературе нет | H1/H10 остаются условными до benchmark | выполнить envelope seed §5.3; опубликовать методику |
| G-04 | TEE/confidential computing для multi-agent систем слабо исследован | профиль C недопроектирован | PoC: MLS + attested enclave indexer [G7–G12] |
| G-05 | Beta/EigenTrust-репутация не валидирована на LLM-агентах (sybil/collusion специфика) | параметры порогов promotion — гипотеза | canary-тесты disagreement [I16]; калибровка на пилоте |
| G-06 | Argumentation/TMS в production knowledge bases почти не встречается | риск переусложнения F-7.3/7.4 | начать с двухстатусного promote/challenge; граф позже |
| G-07 | Tool-poisoning detection — открытая проблема; сканеры эвристичны | остаточный риск EP-06 | layered defense + quarantine + human approval новых tools |
| G-08 | Нет стандарта cross-component revocation latency ≤5 c (SSF emerging) | SLA отзыва — собственная гарантия | транзакционный revoke state; тест revocation latency |
| G-09 | HCI-метрик comprehension для агентных интерфейсов нет | acceptance-критерий UI эвристический | A/B на пилоте; зафиксировать пороги как гипотезы |
| G-10 | Deterministic simulation для LLM-агентных систем — нет готовых harness | F-11.3 придётся строить | FoundationDB-подход вручную; сидируемый scheduler + fault injection |

## 4. Ограничения и статус верификации источников

- Реестр (`10_source_registry.md`): 247 позиций, 246 валидных после исключения I4;
  ядро цитирования — 118. Текущие статусы: 44 `v` / 26 `c` / 176 `u` /
  0 `x` / 1 `x-исключён`. Шесть прежних `x` проверены: C1/C8/D12/J4
  канонизированы, C9/L17 явно заменены корректными работами с сохранением provenance ошибки.
- Все количественные оценки — планировочная модель, не измерение (честно отражено в H1/H10).
- Vendor-документация подтверждает функции, не comparative effectiveness.
- Браузерная проверка выполнена для шести приоритетных спорных строк; 176 `u` не проходили
  построчную первичную проверку (AI-assisted pipeline, disclosure соответствует §11
  базового документа).

## 5. Рекомендуемые следующие шаги

1. Benchmark envelope seed §5.3 → измерить distributions/p95 и снять «условно» с H1/H10
   либо пересмотреть capacity assumptions.
2. Прототип P0-среза фич (EP-01..EP-05, EP-08) на PostgreSQL/RLS + outbox/effect receipts.
3. Пилот comprehension-теста и N_prompts/час на реальной группе.
4. Отдельное мини-исследование профиля C: MLS + TEE PoC (закрытие G-04).
5. По мере использования claims в реализации переводить соответствующие `u`-источники
   в `v/c`; массовая ручная проверка всех 176 `u` не объявляется выполненной.

## 6. Соответствие DoD плана

| Артефакт плана | Статус |
|---|---|
| Мастер-реестр 100–200 источников | закрыт с контролируемым отклонением: 118★ curated core, 246 валидных / 247 позиций; field-complete данные составные (`10` + `sources/*`) |
| Каталог фич | готов v2: 12 эпиков, 64 фичи |
| Архитектурные модели | готово v2; performance/recovery числа помечены targets |
| Ментальная модель | готова v2; добавлена оговорка применимости Art.14 |
| Онтологическая модель | готова v2; SHACL lifecycle, platform subject и budget conservation согласованы |
| Математическая модель | готова v2; branching budgets, delivery/reconciliation и Merkle tree исправлены |
| Синтез + гэпы | этот документ v2; benchmark/pilot остаются последующей эмпирической фазой |
