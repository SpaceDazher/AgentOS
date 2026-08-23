# 80 — Независимый аудит и evidence closure

Статус: **PASS WITH EXPLICIT LIMITS** для design research (раунд 13). Это не PASS для
непроведённых benchmark, user study или юридической квалификации конкретного deployment.

## 1. Вердикт и границы

Первый adversarial-проход дал `REVISE`: механическое покрытие было высоким, но реестр,
SHACL и safety-модель содержали существенные противоречия. После корректирующего раунда
закрыты все найденные critical/major дефекты, которые можно закрыть на уровне исследования.

Исходный DoD «100–200 уникальных в одном field-complete файле» буквально не выполнен и не
маскируется: полный набор — 247 позиций / 246 валидных уникальных, curated core — 118★,
а field-complete metadata составлена из индекса `10_source_registry.md` и
`sources/*.md`. Это controlled deviation; удалять источники ради числа было бы хуже.

## 2. Методы

1. Структурный пересчёт реестра, статусов, core, фич, H1–H16, citation closure и UTF-8.
2. Browser/primary-source проверка шести спорных записей и текущей ревизии MCP.
3. Adversarial model review: branching delegation, delivery uncertainty, TOCTOU boundary,
   Merkle proofs, ontology/SQL/math alignment, promotion independence и Art.14 applicability.
4. Независимый Luna-review исходного состояния, затем correction review той же копии.

## 3. Закрытие шести спорных источников

| ID | Итог | Canonical evidence | Что изменено |
|---|---|---|---|
| C1 | `c` | https://doi.org/10.1109/2.485845 | RBAC0–3 подтверждено; role explosion явно помечен design inference |
| C8 | `c` | https://doi.org/10.1145/3649835 | venue исправлен на OOPSLA/PACMPL 2024 |
| C9 | `c`, replacement | https://doi.org/10.1145/3663529.3663854 | несуществующая SOSP'23 запись заменена FSE'24 с provenance note |
| D12 | `c` | https://doi.org/10.2307/2216075 | исправлены venue (Noûs) и DOI; notification claim ослаблен |
| L17 | `c`, replacement | https://doi.org/10.1145/1998441.1998450 | чужой DOI заменён Fong & Siahaan SACMAT'11 с provenance note |
| J4 | `c` | https://netflixtechblog.medium.com/performance-under-load-3e6fa9a60581 | найден официальный migrated post |

Дополнительно MCP Tasks обновлён с experimental core 2025-11-25 на официальный
`io.modelcontextprotocol/tasks` extension ревизии 2026-07-28.

## 4. Закрытые model defects

| Дефект | Закрытие |
|---|---|
| Branching grants размножали budget | parent ledger + serializable child reservation + I5/INV6 и schema/AC |
| Общая exactly-once/TOCTOU гарантия | at-least-once outbox, atomic local effect receipt, fencing/precondition, reconciliation unknown outcome |
| Hash chain обещала O(log n) Merkle proof | append-only Merkle tree, signed tree heads, inclusion/consistency proofs |
| Platform subject расходился между слоями | PlatformOpsSubject + subject_kind/ref + `P_ops` в authorize |
| SHACL отклонял proposed/наследуемые свойства | shapes открыты; evidence/activity условны только для promoted; budget обязателен и неотрицателен |
| `n_src≥2` допускал mirrors/Sybil | canonical_source_id, publisher_id, independence_group и correlation cap |
| Phantom `K16` и stale counts | ссылка заменена G16; каталог пересчитан: 12 эпиков / 64 фичи |
| A15/E17 исчезли обе при dedup | восстановлен канонический E17; итог 247 позиций / 246 валидных |
| Art.14 звучал как универсальная обязанность | добавлена high-risk applicability/voluntary-benchmark оговорка |

Финальный Luna correction review отдельно подтвердил: shared-workspace subject согласован
во всех слоях; status single-valued, TTL typed, EvidenceShape полный; provenance metadata
назначает immutable trusted resolver с evaluator separation и транзакционным distinct-count.
Оставшихся blockers не найдено.

## 5. Наблюдаемая верификация

- Mechanical PASS: strict UTF-8 — 10 top-level файлов; registry — 247 rows / 246 valid;
  `v44/c26/u176/x0/x-excluded1`; core — 118★; features — 64; H1–H16 — 16/16;
  orphan citations — 0; stale model tokens — 0.
- `git diff --no-index --check`: whitespace errors отсутствуют (код 1 вызван наличием diff;
  вывод содержал только Windows line-ending warnings).
- Python 3.11 доступен, но `rdflib`, `pyshacl` и `llm_verifier` не установлены.
  Поэтому реальный SHACL execution и package-backed verifier не заявляются; shapes
  проверены структурно и должны быть прогнаны в implementation-фазе.
- Числа 34 events/s, 41 820 pairs, `L_auth≈0.68` и SLO остаются planning assumptions;
  benchmark evidence отсутствует и в текстах это явно указано.

## 6. Best-of-3 self-verification (1–20)

| Pass | Requirement coverage | Model correctness | Regression risk | Verification evidence | Security/operational |
|---|---:|---:|---:|---:|---:|
| A — structural/traceability | 20 | 19 | 19 | 19 | 19 |
| B — adversarial failure paths | 19 | 18 | 18 | 18 | 19 |
| C — independent Luna correction review | 20 | 19 | 18 | 18 | 18 |

Минимум по критичным критериям — 18/20. Решение: исследовательскую/design-фазу закрыть с
явными limits; benchmark, SHACL execution, pilot HCI и массовая проверка 176 `u` остаются
последующими эмпирическими работами, а не скрытым долгом текущего отчёта.
