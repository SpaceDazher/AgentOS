# AgentOS — что дальше (roadmap после E2)

Состояние: reference implementation с измерениями (см. eval/E2_RESULTS.md).
Все MVP-обязательства из исходной задачи выполнены. Ниже — приоритизированный
план перевода в production candidate.

## Ближний круг (без изменения архитектуры)

1. **GitHub remote + push** — CI-матрица уже в репо, но не выполняется без
   remote. 10 минут работы.
2. **Gold/near-miss корпуса для оценщика** — протокольный пункт FPR/FNR:
   ~30 артефактов (10 gold / 10 near-miss / 10 alternative-correct) и прогон
   всех 4 проверок по ним. Закрывает «evaluator coverage» количественно.
3. **Off-host копия `audit_anchor.head`** — cron-задача, выталкивающая якорь
   наружу (git-репо/объектное хранилище). Даёт настоящее внешнее якорение.

## Средний круг (новые интерфейсы, ядро стабильно)

4. **Sandbox воркеров (R2-3)** — Windows: запускающий процесс с restricted
   token + AppContainer; POSIX: namespace/isolation. Самый крупный оставшийся
   security gap.
5. **pyproject.toml + pip install** — снимает PYTHONPATH-хаки в плагине и CLI.
6. **OTel exporter** — трейсы по goal/run id поверх существующего audit log.
7. **Secret refs + redaction** — до записи args/events в журнал.

## Дальний круг (изменения хранения/топологии)

8. **Postgres за db.py** — параллельные писатели, бэкапы.
9. **Bounded-parallel scheduler** — несколько живых run'ов на независимых
   задачах DAG; leases/fencing уже готовы.
10. **Compensation registry** — внешние side effects с родной компенсацией.

## Правило

Каждый пункт входит в ядро только с измерением до/после (протокол) и ADR,
если меняет контракт.
