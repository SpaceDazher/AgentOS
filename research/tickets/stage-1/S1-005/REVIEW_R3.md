# S1-005 — Review R3

Проверен corrective-коммит 4aeeeb7 относительно его родителя.

## Вердикт

**REVISE — 4aeeeb7 не пушить и S1-005 пока не закрывать.**

Коммит содержит устаревший evidence pack и несколько воспроизведённых fail-open путей.

## Findings

### 1. [P1] Committed evidence уже stale

Текущий results/boundary-experiments.json имеет SHA-256:

    141eb7f4ecc54c155197e5f68b42de08e276f227300007b18d7ec82d16847522

Bundle и evidence pack привязаны к другому SHA-256:

    0a38fee26105ac065c4a58883de60b6c9d350878e7e8da328ea19b3c23bde7c6

При этом evaluation-record сохраняет chain_fresh=true. Этот флаг относится к более раннему состоянию файлов и не подтверждает свежесть текущего committed tree.

Причина воспроизводится тестом test_run_experiments_overwrites_fabricated_file: он пишет непосредственно в tracked boundary-experiments.json, запускает новый benchmark и не восстанавливает исходный файл.

Требуется:

- выполнять benchmark-тесты только в TemporaryDirectory;
- никогда не изменять tracked evidence из unit tests;
- после всех тестов повторно строить bundle, research revision и evidence pack;
- перед коммитом проверять совпадение всех текущих file hashes с bundle и pack;
- требовать чистое рабочее дерево.

### 2. [P1] В production-вызове остался stale-verdict bypass

make_bundle.run_evaluator поддерживает параметр expect_fresh_write, но по умолчанию он равен false. Production-функция _main вызывает run_evaluator без включения freshness.

Наблюдаемая негативная проба: подставной subprocess завершился с exit code 0, ничего не записал и успешно вернул сохранённый PASS_WITH_LIMITS.

    PROBE_PRODUCTION_DEFAULT_STALE_VERDICT=ACCEPTED PASS_WITH_LIMITS

Требуется:

- удалить optional freshness;
- всегда удалять или атомарно заменять старый sensitivity output перед evaluator run;
- требовать новый файл, созданный данным subprocess;
- связывать файл с nonce/run id и временем запуска;
- запрещать publishing path без fresh-write semantics.

### 3. [P1] Fresh experiments запускаются после evaluator

Текущий порядок make_bundle._main:

    eval_result = run_evaluator()
    experiments_data = run_experiments()
    build bundle

Evaluator читает предыдущий boundary-experiments.json. После этого experiments.py создаёт новую серию, и именно её значения используются в bundle. Следовательно, evaluator verdict и опубликованные experiment results не относятся к одному входу.

Требуется:

1. Запустить experiments.py.
2. Проверить exit code, schema, provenance и hashes.
3. Заморозить полученный experiment artifact.
4. Передать точный путь и digest evaluator.
5. Запустить evaluator против замороженного artifact.
6. Включить те же hashes в bundle и evidence pack.

### 4. [P1] Experiment provenance не привязан к исполняемому коду

Сохранённый experiment result содержит:

    commit = ea9e73c433de6db5a04b5a467bd285da9e956fe1

Текущий HEAD:

    4aeeeb77c66f67fdd9db5ef5eee44fd29d51a41d

Benchmark был выполнен из изменённого working tree, но записал только предыдущий HEAD. Dirty state, tree hash и hashes исполняемых scripts отсутствуют.

validate_experiments_data требует только непустые commit и environment. Негативная проба с commit=not-a-real-commit, произвольным environment и отсутствующим output_sha256 была принята:

    PROBE_BOGUS_COMMIT_NO_OUTPUT_DIGEST=ACCEPTED

Дополнительно bundle содержит три несовместимые серии метрик:

- source description: 4.86 / 25.71 / 18.20;
- claim c1-experiments: 4.15 / 17.38 / 26.87;
- текущий boundary-experiments.json: 5.7 / 24.84 / 28.05.

Требуется:

- запускать benchmark только на clean frozen commit;
- сверять recorded commit с ожидаемым commit;
- записывать git tree SHA и dirty=false;
- записывать hashes experiments.py, evaluator.py и configuration;
- вычислять source descriptions и claims из одного immutable result;
- запрещать hardcoded measurement values в make_bundle.py.

### 5. [P1] Standalone evaluator принимает сфабрикованные experiments

evaluator.validate_experiments использует prefix-match schema и не проверяет:

- environment;
- commit;
- rounds;
- response_semantics_validated;
- output SHA-256;
- hashes исполняемых scripts;
- raw observations.

Минимальный искусственный JSON снова был принят:

    PROBE_EVALUATOR_FABRICATED_EXPERIMENTS=ACCEPTED

Требуется:

- использовать одну общую строгую validation-функцию для evaluator и bundle;
- требовать точную schema;
- проверять payload digest;
- проверять commit/tree/script hashes;
- проверять semantic counters и raw observations;
- отклонять старые и неизвестные schema versions.

### 6. [P1] Самопереклассификация claim остаётся возможной

Harness проверяет только общую категорию evidence artifact, но не связь доказательства с конкретным statement.

Наблюдаемая негативная проба:

- containers restart/recovery изменён с unknown на fact;
- score установлен в 4;
- limitation удалена;
- evidence_refs заменены на несвязанный ADR-0002;
- matrix validation прошла;
- unknown dimensions стали пустыми.

    PROBE_UNKNOWN_TO_FACT_WITH_UNRELATED_ADR=ACCEPTED

Требуется:

- заморозить host-owned classification для каждого candidate × dimension;
- связать claim с конкретными source assertions, section anchors и digests;
- запрещать смену unknown без нового канонического evidence record;
- отделить candidate-supplied narrative от host-authoritative score inputs;
- добавить негативный тест unrelated-but-valid evidence.

### 7. [P2] Evidence registry непереносим

evidence-ref-index.json содержит абсолютные пути:

    D:/Project/DeepeekHarness/research/30_architecture_models.md
    D:/Project/DeepeekHarness/research/70_synthesis_and_gaps.md

Evaluator eagerly проверяет все registry entries. В чистом GitHub-клоне без соседнего DeepeekHarness evaluation завершится ошибкой.

Требуется:

- публиковать content-addressed snapshots необходимых external sources внутри tracked evidence;
- использовать repository-relative paths;
- хранить original URI/path только как provenance metadata;
- добавить clean-clone portability test.

## Что закрыто относительно REVIEW_R2

- Recursive validation topology branches реализована.
- S2 weight vectors сохраняются вместе с digest и воспроизводят winner.
- Free-form evidence strings отклоняются.
- IPC pipe handles закрываются; ResourceWarning в безопасной выборке не обнаружен.
- Evidence pack является tracked и его внутренние file/payload hashes совпадают.

Эти исправления не закрывают findings R3 выше.

## Наблюдаемая верификация

Безопасная подвыборка, не изменяющая tracked benchmark output:

    py -3.12 -m unittest +      tests.test_s1_005_regressions +      tests.test_s1_005_review_r1 +      tests.test_s1_005_review_r2.F2EvidenceAuthorityTests +      tests.test_s1_005_review_r2.F3ScenarioStrictnessTests +      tests.test_s1_005_review_r2.F4WeightVectorPersistenceTests +      tests.test_s1_005_review_r2.F5PipeHandleTests -v

    Ran 63 tests — OK

Corpus:

    py -3.12 -m evals.gen_fixtures --check
    78 checked, 0 violations

Wiki:

    py -3.12 -m agentos.cli wiki-check --db .agentos-research/platform-stage-1
    files=1959, links=5427, issues=0, ok=true

Evidence pack:

    PACK_FILE_SHA_MATCH=True
    PACK_PAYLOAD_SHA_MATCH=True
    PACK_CHAIN_FRESH_FLAG=True

Последний флаг является записанным историческим утверждением и опровергается несовпадением текущего experiment file SHA с bundle/pack binding.

Git:

    git diff --check
    clean

Полный suite не считается зелёным: заявленный прогон завершился четырьмя ошибками test_autoresearch. Независимо полный suite не запускался, поскольку обнаруженный R2-тест изменяет tracked evidence.

## Результаты независимых негативных проб

    PROBE_UNKNOWN_TO_FACT_WITH_UNRELATED_ADR=ACCEPTED
    PROBE_EVALUATOR_FABRICATED_EXPERIMENTS=ACCEPTED
    PROBE_BOGUS_COMMIT_NO_OUTPUT_DIGEST=ACCEPTED
    PROBE_PRODUCTION_DEFAULT_STALE_VERDICT=ACCEPTED PASS_WITH_LIMITS

## Self-verification

Три независимых подхода — state consistency, adversarial probes и test-authority audit — дали одинаковый вердикт REVISE.

- requirement coverage: 14/20;
- functional correctness: 11/20;
- regression safety: 13/20;
- verification evidence: 10/20;
- operational and security safety: 12/20.

Критические критерии ниже 18/20.

## Условия следующего corrective round

1. Перенести изменяющий evidence benchmark-тест в TemporaryDirectory.
2. Сделать fresh evaluator output обязательным во всех production paths.
3. Выполнять experiments до evaluator.
4. Связать evaluator с точным experiment digest.
5. Требовать clean frozen commit, tree SHA и script hashes.
6. Удалить hardcoded measurement values из bundle generator.
7. Усилить evaluator.validate_experiments до общей строгой schema.
8. Закрыть unrelated-evidence claim reclassification.
9. Сделать evidence registry переносимым из чистого клона.
10. После всех тестов повторно выполнить experiments, evaluator, bundle и research-plan.
11. Выпустить новую revision и новый tracked evidence pack.
12. Проверить текущие hashes после последнего теста.
13. Получить полный test suite с exit code 0.
14. До успешной независимой пробы сохранять REVISE и не выполнять push.
