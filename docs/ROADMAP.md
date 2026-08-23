# AgentOS — что дальше (roadmap после E2)

Состояние: reference implementation с измерениями (см. eval/E2_RESULTS.md).
MVP-обязательства исходной задачи выполнены **частично**: вертикальный
сценарий, тесты, evidence packs, ADR и первый измерительный прогон есть, но
протокольный reliability-порог не достигнут (pass⁵ 0.75 < 0.8), recording
contract первого прогона нарушен (packs per-episode отсутствовали — runner
исправлен), а false-completion rate не измерен. Статус «production-ready»
не заявляется; pre-registered порог "harness-reliable" тоже пока не взят.

## Ближний круг (без изменения архитектуры)

1. **GitHub remote + push** — CI-матрица уже в репо, но не выполняется без
   remote. 10 минут работы.
2. **Gold/near-miss корпуса для оценщика** — протокольный пункт FPR/FNR:
   ~30 артефактов (10 gold / 10 near-miss / 10 alternative-correct) и прогон
   всех проверок по ним. Закрывает «evaluator coverage» количественно.
3. **Off-host копия `audit_anchor.head`** — cron-задача, выталкивающая якорь
   наружу (git-репо/объектное хранилище). Даёт настоящее внешнее якорение.
4. **Повторный прогон E2 с исправленным runner'ом** (packs + env в каждом
   эпизоде) — закрывает recording-contract отклонения из §Compliance.

## Средний круг (новые интерфейсы, ядро стабильно)

5. **Sandbox исполнения кода — ДВА контура**:
   - воркер Hermes (R2-3): restricted token / AppContainer / container per run;
   - **evaluator `command_exit_0`**: сейчас выполняет сгенерированный код
     обычным subprocess с очищенным PATH — это НЕ запрещает доступ к файловой
     системе, сети и дочерним процессам. Нужен тот же sandbox-контур, что и
     для воркера (общая утилита confinement).
6. **pyproject.toml + pip install** — снимает PYTHONPATH-хаки в плагине и CLI.
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
