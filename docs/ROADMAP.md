# AgentOS — что дальше (roadmap после E2)

Состояние: reference implementation с измерениями (см. eval/E2_RESULTS.md).
MVP-обязательства исходной задачи выполнены **частично**: вертикальный
сценарий, тесты, evidence packs, ADR и первый измерительный прогон есть, но
протокольный reliability-порог не достигнут (pass⁵ 0.75 < 0.8), recording
contract первого прогона нарушен (packs per-episode отсутствовали — runner
исправлен), а false-completion rate не измерен. Статус «production-ready»
не заявляется; pre-registered порог "harness-reliable" тоже пока не взят.

## Ближний круг (без изменения архитектуры)

0. **Autoresearch на реальных LLM-эпизодах** — каркас готов (ADR-0008,
   `autoresearch.py`, детерминированная fake-кампания); следующий шаг —
   подключить реального candidate-генератора с бюджетом (на этом хосте
   Hermes-CLI отсутствует — путь через `dsh_worker.DshAgentWorker`).
1. ~~GitHub remote + push~~ **ВЫПОЛНЕНО**: remote подключён
   (SpaceDazher/AgentOS), рабочая ветка `agent/dsh-adaptation` запушена;
   CI-матрица сработает на PR.
2. ~~Gold/near-miss корпуса~~ **ВЫПОЛНЕНО** (EPIC phase 2): 30 evaluator-quality
   фикстур + FPR=0/FNR=0 в `tests/test_stage_corpus.py`.
3. ~~Off-host копия `audit_anchor.head`~~ **ВЫПОЛНЕНО (export/verify шаг)**:
   `anchor.py` + CLI `anchor-export`/`anchor-verify` выдают самопроверяемый
   бандл `agentos.anchor-export/v1` с головой цепочки и проверяют его против
   любой копии БД (структура, историческая привязка по seq, полная цепочка).
   Осталось: внешнее расписание (cron/git push), выталкивающее бандл наружу,
   и опциональная нотаризация.
4. ~~Повторный прогон E2 с исправленным runner'ом~~ **ВЫПОЛНЕНО**: E2-v2
   записал packs+env в 100/100 эпизодах (`eval/E2_RESULTS_V2.md`), retry-серия
   закрыла 42 провайдерных отказа (`eval/E2_RETRY_RESULTS.md`); контракт
   записи (pack path+sha256, env, true terminal states, fail class) закреплён
   regression-тестом `tests/test_e2_recording_contract.py` на FakeWorker.
   Открытые остатки §Compliance (provider version identity, cost, checkpoints)
   учтены в GAP_REGISTER.

## Средний круг (новые интерфейсы, ядро стабильно)

5. **Sandbox исполнения кода — ДВА контура**:
   - воркер Hermes (R2-3): restricted token / AppContainer / container per run;
   - **evaluator `command_exit_0`**: сейчас выполняет сгенерированный код
     обычным subprocess с очищенным PATH — это НЕ запрещает доступ к файловой
     системе, сети и дочерним процессам. Нужен тот же sandbox-контур, что и
     для воркера (общая утилита confinement).
6. ~~pyproject.toml + pip install~~ **ВЫПОЛНЕНО**: `pyproject.toml` добавлен
   (консольная команда `agentos`, stdlib-only deps), `pip install -e .`
   проверен; plugin bootstrap теперь вычисляет путь из расположения плагина
   (env `AGENTOS_REPO` остаётся переопределением). Осталось: перевести
   установленный плагин на import из pip-пакета.
7. **OTel exporter** — трейсы по goal/run id поверх существующего audit log.
8. **Secret refs + redaction** — до записи args/events в журнал.

## Дальний круг (изменения хранения/топологии)

9. **Postgres за db.py** — параллельные писатели, бэкапы.
10. **Bounded-parallel scheduler** — несколько живых run'ов на независимых
    задачах DAG; leases/fencing уже готовы.
11. **Compensation registry** — внешние side effects с родной компенсацией.

## Правило

Каждый пункт входит в ядро только с измерением до/после (протокол) и ADR,
если меняет контракт. Никакие компоненты не помечаются production-ready без
измеренных SLO и выполненных reliability-пунктов этого списка.
