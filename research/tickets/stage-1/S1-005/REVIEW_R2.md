# S1-005 — Review R2

Проверен corrective-коммит ea9e73c относительно его родителя.

## Вердикт

**REVISE — ea9e73c пока не пушить и S1-005 не закрывать.**

Статус PASS_WITH_LIMITS формально не завышен, но четыре fail-open пути остались.

## Findings

### 1. [P1] Experiment evidence всё ещё можно сфабриковать

make_bundle.py не запускает experiments.py, а читает готовый JSON. Проверка допускает произвольный schema suffix и минимальный набор придуманных чисел.

Наблюдаемая негативная проба: полностью искусственный документ с положительными latency values и committed_rows_complete=true был принят production-validator.

Требуется:

- запускать experiments.py в свежем subprocess;
- требовать exit code 0;
- проверять точную schema, а не prefix;
- проверять rounds, response_semantics_validated и обязательные raw observations;
- связывать результат с environment manifest, commit SHA и SHA-256 выходного файла;
- запрещать публикацию сохранённого результата без свежей верификации.

### 2. [P1] Evidence refs и claim classification самоподтверждаются

Любая непустая строка, не похожая на путь, считается существующим доказательством.

Наблюдаемые негативные пробы:

- замена всех evidence_refs на invented non-path evidence прошла validation;
- переклассификация unknown в fact с числовым score прошла;
- unknown limitation исчезла из результата без появления настоящего доказательства.

Требуется:

- разрешать только host-resolved source IDs или hash-bound repository paths;
- запрещать произвольные free-form evidence references;
- проверять source existence, ownership и digest;
- выполнять claim classification на стороне harness, а не доверять полю из decision matrix;
- запрещать изменение unknown в scored claim без нового канонического evidence.

### 3. [P1] Пустые topology-ветви принимаются

Production-validator проверяет наличие ключей monolith и containers, но не проверяет содержимое значений.

Наблюдаемая негативная проба: authoritative_state_owner.monolith, allowed_transitions.monolith и recovery_path.monolith заменены пустыми строками — validate_scenarios завершился без ошибки.

Дополнительно tests/test_s1_005_review_r1.py использует собственную копию scenario-validator вместо evaluator.validate_scenarios. Поэтому тесты могут оставаться зелёными при более слабой production-реализации.

Требуется:

- проверять ожидаемый тип каждой branch;
- рекурсивно запрещать пустые строки, списки и словари;
- вызывать production-validator непосредственно из regression-тестов;
- добавить случаи empty branch, wrong type и partially empty branch.

### 4. [P2] Sensitivity evidence неполное

Результат сохраняет 200 s2_vector_digests, но не сохраняет сами weight vectors. Требование REVIEW_R1 «vector + digest» не выполнено.

Без векторов независимый аудитор не может проверить соответствие каждого digest фактическим весам только по опубликованному результату.

Требуется:

- сохранять для каждого запуска run index, полный weight vector, total и SHA-256;
- проверять digest при чтении;
- либо публиковать отдельный content-addressed artifact с векторами и привязывать его к sensitivity result.

### 5. [P2] IPC-тесты оставляют открытые pipe handles

Полный test suite выдаёт ResourceWarning для corrupt, crash и healthy child в measure_pipe_child.

Требуется:

- гарантированно закрывать stdin и stdout;
- при timeout выполнять terminate, затем kill при необходимости;
- всегда дожидаться завершения дочернего процесса;
- добавить проверку отсутствия ResourceWarning.

### 6. [P2] F2 regression-тесты проверяют текст исходника, а не поведение

Тесты подтверждают только наличие строк evaluator.py, subprocess, returncode и committed_rows_complete в make_bundle.py. Это не доказывает фактический запуск evaluator и experiments и не проверяет реакцию на stale или fabricated results.

Требуется:

- подменять subprocess контролируемым fake executable;
- проверять отказ при non-zero exit, malformed JSON, stale output и schema mismatch;
- проверять, что experiments действительно запускаются;
- проверять, что bundle verdict невозможно получить из заранее записанного файла.

## Что закрыто

Finding F3 из REVIEW_R1 закрыт:

- evidence pack находится в tracked results/evidence;
- file SHA-256 совпадает с evaluation record;
- normalized payload SHA-256 совпадает с self-hash pack;
- research_revision равна 3;
- рабочее дерево после проверки чистое.

Функциональная часть IPC semantic validation также работает: неверные ответы и non-zero child exit отклоняются. Остаётся operational leak файловых дескрипторов.

## Наблюдаемая верификация

    py -3.12 -m unittest tests.test_s1_005_regressions tests.test_s1_005_review_r1 -v
    Ran 47 tests — OK

    py -3.12 -m unittest discover -s tests -v
    Ran 368 tests — OK (1 skipped)

    py -3.12 -m evals.gen_fixtures --check
    78 checked, 0 violations

    py -3.12 -m agentos.cli wiki-check --db .agentos-research/platform-stage-1
    files=1906, links=5296, issues=0, ok=true

    git diff --check ea9e73c^ ea9e73c
    clean

    git status --short
    clean before creation of this review file

Проверка выполнялась на Python 3.12. Python 3.11 в текущей shell-среде отсутствовал.

## Результаты независимых негативных проб

    PROBE_BRANCH_EMPTY=ACCEPTED
    PROBE_FREEFORM_EVIDENCE=ACCEPTED
    PROBE_UNKNOWN_RECLASSIFIED=ACCEPTED
    PROBE_FABRICATED_EXPERIMENTS=ACCEPTED
    S2_HAS_VECTORS=False
    DIGESTS=200

## Self-verification

- requirement coverage: 13/20;
- functional correctness: 12/20;
- regression safety: 15/20;
- verification evidence: 14/20;
- operational and security safety: 14/20.

Критические критерии ниже 18/20. Независимую пробу коммит не проходит.

## Условия следующего corrective round

1. Добавить production-facing негативные тесты для всех findings R2.
2. Сначала наблюдать RED на текущем ea9e73c.
3. Убрать free-form evidence authority и self-classification claims.
4. Исполнять experiments как обязательный свежий subprocess.
5. Усилить production scenario schema.
6. Сохранять weight vectors вместе с digest.
7. Закрыть subprocess resources и timeout cleanup.
8. Повторно выполнить experiments, evaluator, bundle и research-plan.
9. Выпустить новую research revision и новый tracked evidence pack.
10. До успешной независимой пробы сохранять REVISE и не выполнять push.
