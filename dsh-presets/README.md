# dsh agent presets for AgentOS

В этой папке — версионируемые копии пресетов (режимов) DeepSeek Harness,
которые используются для работы над AgentOS. Рабочая копия пресета живёт в
установленном dsh-пакете; здесь — источник для повторной установки/переноса.

## Пресеты

| Папка | id мода | Что это |
|---|---|---|
| `integrity/` | `integrity` | **Режим задач (Integrity)**: полный стек standard + обязательный контроль целостности (проверка журнала/хэш-цепочек, пересчёт эвиденс-дайджестов, полный прогон тестов перед сдачей, fail-closed, immutable-артефакты). |

## Установка

Установленный dsh ищет пресеты в `config/agent-presets/` внутри пакета
(`$DSH_ROOT/config/agent-presets/`, trust: system), а также в корнях,
добавленных через patch-слой `agent-presets` (см. `dsh-agent-presets`).

Скопировать мод `integrity` в установленный пакет (PowerShell):

```powershell
$dsh = "C:\Users\nikit\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh"
Copy-Item -Recurse "dsh-presets\integrity" "$dsh\config\agent-presets\integrity"
```

После установки **перезапусти dsh** (хост уже смонтировал пресеты при старте;
новые моды появляются в UI после перезапуска). Мод выбирается в списке
режимов сессии; имя — «Режим задач (Integrity)».

## Особенности `integrity`

- полный инструментарий: файлы, shell (pwsh/bash), web, skills, background
  jobs, goals, plan mode, compaction, subagents, workflows, todo, ask-user;
- `agent-instructions` без `dshHome` — автоматически подхватываются
  user-global `$DSH_HOME/AGENTS.md` и ближайший project-level `AGENTS.md`
  (включая инварианты AgentOS);
- persona задаёт integrity-контракт: верификация перед утверждениями,
  fail-closed на неизвестных исходах, пересчёт хэшей с диска,
  immutable-артефакты, персистентность решений, pre-handoff gate
  (полный прогон тестов и проверок перед завершением задачи).