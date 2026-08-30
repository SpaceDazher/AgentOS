# S1-004 — Review R1

Вердикт: **REVISE — пока не пушить и не считать S1-004 закрытым.** Формальные движки действительно выполнялись, но evidence pipeline содержит несколько fail-open путей.

## Findings

1. **[P1] Evidence pack не воспроизводим.** `evaluation-record.json` фиксирует SHA `22cf…`, фактический локальный pack сейчас имеет SHA `4f03…`; сам pack находится в игнорируемой `.agentos-research/` и отсутствует в коммите. Независимый аудитор из GitHub-клона не сможет проверить `chain_fresh=true`.
2. **[P1] Formal runner может принять неполный/аварийный Alloy-прогон.** Код не проверяет `proc.returncode` и не требует точного множества из 12 команд. Один распознанный `Run Valid… SAT` уже способен дать `PASS`.
3. **[P1] TLC может получить `PASS` без temporal verification.** `temporal_properties_checked` записывается, но отсутствие маркера не блокирует вердикт.
4. **[P1] Acceptance runner не обеспечивает заявленный контракт.** Он принимает один seed, а `--skip-rerun` всё равно создаёт manifest с `verdict=PASS`. «Independent rerun» фактически является повторным вызовом `simulate()` в том же процессе.
5. **[P1] INV6 проверяется неполно.** Проверяется каждый ребёнок отдельно, а не сумма резервов всех детей. Наблюдаемый repro: два child по 2 при parent=2 дают сумму 4, но `audit()` проходит.
6. **[P1] Probe B сам подтверждает ожидаемый результат.** Он вручную повторяет guard, искусственно увеличивает и затем уменьшает `SAF3`, вместо вызова реальных `op_publish`, `op_reconcile`, `op_retry_after_reconcile` и `op_reserve_child`. Поэтому поломка настоящего пути может остаться незамеченной.
7. **[P2] Команда wiki-проверки неверна.** `wiki-check` без `--db` возвращает `missing_generated_projection`; корректная команда — с `--db .agentos-research/platform-stage-1`.

## Проверено

- свежий Alloy replay: 12 команд, exit 0;
- свежий TLC replay: 271 168 состояний, exit 0;
- S1-004 tests: 13/13;
- полный suite: повторный прогон 310 OK, 1 skipped; первый прогон обнаружил невоспроизведённый concurrency-flake;
- corpus: 78/78;
- `wiki-check --db .agentos-research/platform-stage-1`: `ok=true`;
- полный 3×1M acceptance-run заново не выполнялся, проверялись записанные результаты и их локальные хеши.

## Resolution R2 — 2026-08-30

Исходный `REVISE` сохранён выше как исторический вердикт и superseded этим
корректирующим раундом. Все семь findings закрыты наблюдаемыми проверками:

1. Evidence pack revision 7 сохранён в Git по content-addressed пути; SHA
   файла `98f6b998…8841` совпадает с байтами. Harness теперь отдельно выдаёт
   `file_sha256` и payload self-hash, поэтому путь больше не связывается с
   неоднозначным digest.
2. Alloy runner требует exit 0, ровно 12 уникальных команд, отсутствие
   missing/extra и точное соответствие frozen verdict matrix.
3. TLC runner требует exit 0, точный набор 10 invariants, `LiveDelivery`,
   frozen bounds/spec, положительные state counters, no-error completion и
   temporal verification marker.
4. Acceptance runner требует минимум 3 разных seed, не имеет `--skip-rerun`
   и всегда повторяет каждый seed в новом Python interpreter subprocess со
   stripped environment; non-zero/invalid/incomplete output fail closed.
5. INV6 сравнивает с parent ledger сумму резервов всех immediate children;
   исходный repro 2+2>2 теперь поднимает `Violation("INV6")`.
6. Probe B вызывает настоящие `reserve_child`, `allow`, `publish`,
   `delivery_timeout`, `reconcile` и `retry`; ручной SAF3 counter bypass
   удалён.
7. Wiki-команда исправлена на `wiki-check --db
   .agentos-research/platform-stage-1`.

Финальные доказательства: Alloy 12/12 и TLC 271 168 states — exit 0;
acceptance 3×1M + 3 subprocess reruns = 6M операций, 0 violations, digest
совпали; S1-004 suite 24/24; полный suite 321 tests OK (1 skipped); harness
revision 7 `PASS_WITH_LIMITS`, `chain_fresh=true`, wiki 1787 files / 5008
links / 0 issues. Сохранённые bounded/same-host/simulator-as-contract limits
остаются действующими.
