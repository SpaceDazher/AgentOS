# AgentOS — что дальше (roadmap после E2)

Состояние: reference implementation с измерениями (см. eval/E2_RESULTS.md).
MVP-обязательства исходной задачи выполнены **частично**: вертикальный
сценарий, тесты, evidence packs, ADR и первый измерительный прогон есть, но
протокольный reliability-порог не достигнут (pass⁵ 0.75 < 0.8), recording
contract первого прогона нарушен (packs per-episode отсутствовали — runner
исправлен), а false-completion rate не измерен. Статус «production-ready»
не заявляется; pre-registered порог "harness-reliable" тоже пока не взят.

## Ближний круг (без изменения архитектуры)

0. ~~Autoresearch на реальных LLM-эпизодах~~ **ВЫПОЛНЕНО**: `apply_host`
   (host-owned генератор кандидата) в `autoresearch.py` + CLI
   `eval/run_autoresearch.py`; первая живая кампания с реальным dsh-эпизодом
   завершилась **KEEP** (baseline_dev 0.6 → candidate_dev 0.0, обязательный
   holdout пройден; сырой эпизод в `candidate-episodes/`). Попутно измерены и
   задокументированы транспортные ограничения dsh (cp1251-перекодировка
   не-ASCII argv; доставляется только первая строка) — промпт однострочный
   ASCII, нарушения отбиваются typed-ошибкой; `dsh-output.txt` вынесен из
   worktree (`raw_dir`), чтобы evidence адаптера не ломал scope-проверку.
1. ~~GitHub remote + push~~ **ВЫПОЛНЕНО**: remote подключён
   (SpaceDazher/AgentOS), рабочая ветка `agent/dsh-adaptation` запушена;
   CI-матрица сработает на PR.
2. ~~Gold/near-miss корпуса~~ **ВЫПОЛНЕНО** (EPIC phase 2): 30 evaluator-quality
   фикстур + FPR=0/FNR=0 в `tests/test_stage_corpus.py`.
3. ~~Off-host копия `audit_anchor.head`~~ **ВЫПОЛНЕНО (полностью)**:
   export/verify — `anchor.py` + CLI `anchor-export`/`anchor-verify` (бандл
   `agentos.anchor-export/v1`, историческая привязка по seq); транспорт —
   `anchor-mirror`: идемпотентное зеркало в произвольный каталог
   (immutable content-addressed бандлы `anchors/<seq>-<head16>.json` +
   append-only `history.ndjson` + указатель `latest.json`, отказ при
   расхождении состояния) и `scripts/anchor-mirror-task.ps1` — регистрация
   часовой задачи Windows. Осталось только опциональное: нотаризация и
   git-push зеркала на внешний remote (выбор оператора).
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
