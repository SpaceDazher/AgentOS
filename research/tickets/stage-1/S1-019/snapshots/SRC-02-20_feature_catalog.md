# 20 — Каталог фич личного агентного хаба

Статус: v2, независимо проаудирован (раунд 13): **12 эпиков, 64 фичи**. Трассировка: каждая фича несёт `{H…}` (гипотезы базового
документа), `[ID…]` (источники из `research/sources/*.md`), `AC` — проверяемые acceptance
criteria. Приоритеты: **P0** = MVP, **P1** = сразу после MVP, **P2** = профиль B/C / позже.

## EP-01 · Identity и подключение участников {H2,H3,H4} [B3,B19,B20,M5]

| ID | Фича | Описание | AC (пример) | Приоритет |
|---|---|---|---|---|
| F-1.1 | HumanUser accounts | OIDC-аккаунты участников; recovery-код; профиль | создание/удаление пользователя формирует проверяемый план (seed §9.2.11) | P0 |
| F-1.2 | Agent installation identity | каждой установке — собственный principal + ключи, не ключи владельца | запуск shared agent не использует personal connector владельца без явной delegation (§9.2.2) | P0 |
| F-1.3 | Runtime instance identity | короткоживущий workload-ID (SVID/JWT-bound) на run/lease | instance token умирает с lease ≤ TTL 15 мин [B22] | P0 |
| F-1.4 | External agent onboarding | регистрация A2A endpoint: подписанная Agent Card + локальный спонсор | неподписанная/просроченная карта не проходит импорт [A1][A13] | P0 |
| F-1.5 | Device/session management | список активных устройств/сессий, отзыв | отзыв сессии блокирует новые действия ≤5 c (§9.2.4) | P0 |

## EP-02 · Реестр агентов и модулей {H3,H14} [A7,A13,A14,I8,I9,I10,I11,M7]

| ID | Фича | Описание | AC | Приоритет |
|---|---|---|---|---|
| F-2.1 | AgentDefinition store | content-addressed OCI-артефакты, digest-pinning | изменение байтов определения меняет digest; старая версия остаётся доступной | P0 |
| F-2.2 | Publisher signatures | подпись карты/артефакта (JWS/Cosign) + проверка на импорте | импорт без валидной подписи → quarantine | P0 |
| F-2.3 | Capability declaration & diff | заявленные capabilities; diff между версиями | расширение capabilities требует re-approval владельца (threat §8 supply-chain) | P0 |
| F-2.4 | Quarantine workflow | статус quarantine при подозрении/diff; запрет запуска | quarantined installation не инстанцируется (INV §50) | P0 |
| F-2.5 | SBOM/AI-BOM inventory | CycloneDX для модулей/моделей; non-executable formats | pickle-модель отклоняется на гейте [I11] | P1 |

## EP-03 · Делегирование, approvals, квоты {H4,H5,H15} [B4,B5,B6,B12,B13,B17,B18,B26,B27,B29,C5]

| ID | Фича | Описание | AC | Приоритет |
|---|---|---|---|---|
| F-3.1 | DelegationGrant issuance | UI выдачи гранта: субъект, актор, действия, ресурсы, TTL, бюджет | derive() атомарно резервирует child-budget и не допускает ни расширения scope, ни совокупного превышения бюджета родителя (матмодель §3.3) | P0 |
| F-3.2 | Grant lifecycle UI | active/expired/exhausted/revoked; история | все переходы журналируются с policy_version | P0 |
| F-3.3 | Revocation ≤5 c | транзакционный revoke; PEP проверяет на каждом новом действии | тест: после revoke ни одного allow (матмодель §2.3) | P0 |
| F-3.4 | Approval gates | approval_required по риску/классу данных; атомарное потребление | approval привязан к actor+op+args+expiry и потребляется один раз | P0 |
| F-3.5 | Quotas/budgets | token bucket per agent/run + транзакционный ledger parent/child reservations; max fanout/depth | конкурентные derive() не могут зарезервировать в детях больше `parent_remaining`; превышение → отказ/approval [J3] | P0 |
| F-3.6 | Delegation chain depth | ограничение глубины κ_grant производных грантов (стартово 3) | цепочка длиннее κ_grant невозможна API-контрактом | P1 |

## EP-04 · Workspaces и контент-объекты {H2,H8,H13} [D8,F5,F7,F8,C5,C14]

| ID | Фича | Описание | AC | Приоритет |
|---|---|---|---|---|
| F-4.1 | Четыре типа пространств | private/shared/platform-ops/group-knowledge | каждый объект имеет ровно одну located_in (INV2) | P0 |
| F-4.2 | Typed Message | перформатив + payload + scope; untrusted по умолчанию | message от пира создаёт только PROPOSED записи (§9.2.7) | P0 |
| F-4.3 | Immutable Artifacts | content-addressed объекты + digest + PROV | дубликат по digest переиспользуется; изменение невозможно | P0 |
| F-4.4 | Scoped MemoryRecord | автор, TTL, trust label, workspace-scope | memory B невидима агенту A на всех путях (SQL/object/cache/vector — §9.2.1) | P0 |
| F-4.5 | Membership & приглашения | роли viewer/editor/contributor/indexer/curator per workspace (канонический список; concierge — платформенный префикс сервисов, см. 50 §6) | indexer теряет доступ немедленно после revocation membership (§9.2.6) | P0 |
| F-4.6 | Publish/share операция | перенос объекта между пространствами — явная операция | копия получает новую PROV-связь derived_from | P0 |

## EP-05 · Межагентное взаимодействие {H7,H9,H13} [A1,A4,A5,A6,A8,A11,D5,D14,E6,E21]

| ID | Фича | Описание | AC | Приоритет |
|---|---|---|---|---|
| F-5.1 | A2A Agent Gateway | единственная точка control-plane сообщений; policy/audit/quota на пути | direct-обход gateway блокируется egress-политикой (threat §8) | P0 |
| F-5.2 | Task envelopes | A2A task/message/artifact lifecycle + хаб-расширения (delegation_id, purpose) | каждый event хранит actor/subject/delegation/workspace/run/policy_version (§9.2.3) | P0 |
| F-5.3 | Recipient inbox + recipient policy | входящие задачи под политикой получателя; approve exact scope | задача без покрытия грантом получателя не стартует | P0 |
| F-5.4 | Handoff контракт | типизированная передача control+context между агентами | handoff payload валидируется схемой; провал → отказ, не дрейф [E15] | P1 |
| F-5.5 | Protocol adapters | нормализация A2A/MCP за каноническим конвертом (LMOS-паттерн [A11]) | добавление протокола не меняет политику/аудит | P2 |
| F-5.6 | MCP Tasks alignment | durable task objects со status/polling/resume по официальному `io.modelcontextprotocol/tasks` extension (rev 2026-07-28) [A6] | task id недоступен без authorization context; core не предполагается stateful | P1 |

## EP-06 · Инструменты (MCP tool gateway) {H4,H6,H9} [A4,A5,A7,B11,M13,M17,M18]

| ID | Фича | Описание | AC | Приоритет |
|---|---|---|---|---|
| F-6.1 | Tool registry + manifest scanning | реестр tools; скан описаний (tool poisoning) | отравленное описание помечается и блокируется [M18] | P0 |
| F-6.2 | OAuth resource-server модель | MCP-серверы как resource servers; PRM discovery; короткоживущие токены | долгоживущие секреты в конфиге инструмента запрещены схемой [A5][B11] | P0 |
| F-6.3 | Tool output sanitization gate | выходы инструментов — untrusted input (indirect PI) | известные injection-паттерны не попадают в память/knowledge как факты [I3][M17] | P0 |
| F-6.4 | Isolation ladder | Wasm для чистых функций; gVisor/microVM для файловых/сетевых tools | tool вне sandbox-профиля не запускается [I12][I13] | P1 |
| F-6.5 | Egress allowlist | сетевые исходящие только через allowlist вне контроля агента | соединение к не-allowlist host рвётся и журналируется [I14] | P0 |

## EP-07 · Знание и evidence gate {H16} [F4,F6,F7,F8,F14,F16,F18,F19,F20,J9,J13,seed:19]

| ID | Фича | Описание | AC | Приоритет |
|---|---|---|---|---|
| F-7.1 | KnowledgeAssertion lifecycle | proposed→under_review→promoted/challenged/rejected/retracted/superseded | promotion без evidence+evaluation+SHACL невозможен (INV4) | P0 |
| F-7.2 | Evaluation service | отдельный trusted Provenance Resolver immutable назначает canonical_source_id/publisher_id/independence_group; независимые evaluator principals выдают attests | агент не self-assert'ит independence; коррелированные копии считаются одной evidence unit; disagreement > порога эскалирует человеку | P1 |
| F-7.3 | Argumentation view | attack/support граф claims; grounded extension статусы | challenged claim не отдаётся как факт до переоценки | P1 |
| F-7.4 | Retraction propagation | TMS-зависимости; retract тянет зависимые записи | после retract зависимые promoted уходят в under_review [F16] | P1 |
| F-7.5 | SKOS vocabulary alignment | выравнивание тем/терминов group knowledge | маппинг concept↔concept сохраняет провенанс | P2 |
| F-7.6 | Promotion thresholds | Beta-постериор ≥ порога; n_independent≥2 после canonical dedup и publisher-correlation cap (матмодель §5) | копии/зеркала и Sybil-оценки одного источника не промоутят claim | P1 |

## EP-08 · Аудит, провенанс, экспорт {H15} [I8,I15,F7,F8,H3,H4,H6,H16,H17]

| ID | Фича | Описание | AC | Приоритет |
|---|---|---|---|---|
| F-8.1 | Authoritative audit log | append-only события решений/эффектов + append-only Merkle tree и подписанные checkpoints | proof включения/consistency проверяется за O(log n); потеря committed audit events при crash=0 (§9.2.8–9) | P0 |
| F-8.2 | Transactional outbox + effect receipt | состояние+событие атомарно; relay at-least-once; consumer atomарно фиксирует `decision_id` с эффектом либо поддерживает reconciliation | повтор доставки не создаёт второй локальный эффект; неизвестный внешний исход → reconciliation, не blind retry | P0 |
| F-8.3 | Provenance export | definitions/config/artifacts/claims/provenance в JSON-LD пакете | импорт пакета в чистый hub воспроизводит граф (§9.2.10) | P1 |
| F-8.4 | Deletion plan | удаление пользователя → план для canonical/projections/artifacts/secrets/backups | исполнение плана проверяемо чек-листом | P1 |
| F-8.5 | Telemetry vs audit split | OpenTelemetry GenAI для диагностики; audit отдельно | telemetry недоступна как замена audit-записи | P0 |

## EP-09 · Platform agents (scoped services) {H6,H14} [C13,M5,M7,M10,seed:§4.6]

| ID | Фича | Описание | AC | Приоритет |
|---|---|---|---|---|
| F-9.1 | Service principal provisioning | каждый platform agent — отдельный principal, no wildcard grants | health agent видит состояние runs, но не prompt/content (§9.2.5) | P0 |
| F-9.2 | Concierge/Indexer/Evaluator/Triage/Curator | пять ролей с минимальными scope | indexer читает только подключённые workspaces | P0 |
| F-9.3 | Break-glass человеком | операторский доступ — человек + полный журнал | LLM не может вызвать break-glass | P0 |
| F-9.4 | Deterministic services | IAM/PDP/audit/registry/scheduler — код, не LLM | policy engine проходит вектор детерминированных тестов | P0 |

## EP-10 · UX видимости и ментальная модель {H15} [K1,K3,K4,K7,K10,K11,G16,K6,K9]

| ID | Фича | Описание | AC | Приоритет |
|---|---|---|---|---|
| F-10.1 | On-behalf banner | «действует от имени X с правами Y» на каждом агентском действии | скрытие баннера невозможно для high-impact действий | P0 |
| F-10.2 | Progressive disclosure | детали гранта/provenance по запросу | ≤3 кликов от баннера до полного гранта [K7] | P0 |
| F-10.3 | Agent cards для людей | различение personal/shared/platform в UI (§9.2.12) | тип агента виден во всех контекстах | P0 |
| F-10.4 | Approval inbox с бюджетом внимания | пакетирование, severity-ranking, rate-limit промптов | ≤N промптов/час; низкорисковые батчатся [K9] | P1 |
| F-10.5 | Trust calibration surfaces | показатели уверенности/границ рядом с результатами | вывод без confidence-label не показывается как «факт» [K1][K5] | P1 |
| F-10.6 | Workspace activity map | Sensecape-подобная карта «кто с кем/чем» | пользователь находит источник утечки за ≤3 шагов [K6] | P2 |
| F-10.7 | Petname-style naming | локальные понятные имена принципалов | имя всегда отображается рядом с каноническим ID [G16] | P2 |

## EP-11 · Надёжность и benchmark harness {H1,H10,H11} [H1,H2,H4,H5,H8,H9,H10,H13,H14,H17,J1,J2]

| ID | Фича | Описание | AC | Приоритет |
|---|---|---|---|---|
| F-11.1 | WAL archiving + PITR | continuous archiving; восстановление на точку | restore drill < 60 c процесса (seed §5.3 recovery) | P0 |
| F-11.2 | Supervision/restart | crash-only компоненты с restart-стратегиями | kill -9 любого компонента → восстановление без потери audit | P0 |
| F-11.3 | Deterministic simulation harness | сидируемый scheduler + fault injection (FoundationDB-стиль) | 10⁶ операций без нарушений INV1–6/SAF, включая конкурентное ветвление грантов | P1 |
| F-11.4 | Benchmark suite | seed §5.3 envelope автоматизирован; arrival/service distributions и p95 очереди измеряются | целевые, пока не измеренные пороги: p95 authz<20ms; API<250ms; 40 concurrent runs; 1000 adversarial checks=0 | P0 |
| F-11.5 | Migration-ready layout | workspace-scoped IDs, portable export, external gateway | dry-run вынос private workspace в profile B без rewrite | P2 |

## EP-12 · Приватность профили B/C (перспектива) {H12} [G1–G18]

| ID | Фича | Описание | AC | Приоритет |
|---|---|---|---|---|
| F-12.1 | Personal vault node | локальный узел + CRDT sync опубликованного | отключение центра не ломает личные агенты | P2 |
| F-12.2 | E2EE rooms (MLS/MIMI) | комнаты с участниками-агентами; сервер без plaintext | server-side поиск недоступен — документировано честно | P2 |
| F-12.3 | TEE platform agents | attested enclaves (RATS/EAT) для индексации | attestation-claim обязателен перед выдачей ключей | P2 |
| F-12.4 | Metadata minimization | минимизация/retention метаданных взаимодействий | metadata inventory публикуется участникам | P2 |

## Матрица покрытия гипотез фичами

| Гипотеза | Покрывающие фичи |
|---|---|
| H1/H10/H11 | F-11.1–F-11.5 |
| H2 | F-4.1, F-4.5, F-6.5 |
| H3 | F-1.1–F-1.4, F-2.1–F-2.4 |
| H4 | F-1.2, F-3.1, F-6.2 |
| H5 | F-3.1–F-3.3, F-3.6 |
| H6 | F-9.1–F-9.4 |
| H7 | F-5.1–F-5.3, F-6.5 |
| H8 | F-4.2–F-4.4, F-6.3 |
| H9 | F-5.5, F-5.6, F-6.2 |
| H12 | F-12.1–F-12.4 |
| H13 | F-4.5, F-5.1 |
| H14 | F-9.3, F-9.4, F-8.5 |
| H15 | F-10.1–F-10.3, F-8.1 |
| H16 | F-4.2, F-4.6, F-7.1–F-7.6 |

Все 16 гипотез покрыты минимум двумя фичами; критические (H4, H7, H8, H16) — тремя и более.
