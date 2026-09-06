# S1-015 operator design-review protocol (structured, single review)

Scope: one operator design review of the frozen BASELINE vs PETNAME prototype
and the candidate FLOW-11 bundle. This is NOT a human study: no recognition,
comprehension or effectiveness data is collected, `human_study_n=0`,
`recognition_improvement=NOT_MEASURED`.

## Viewing

1. Serve the prototype locally (no network):
   `py -3.12 -m http.server --directory research/tickets/stage-1/S1-015/prototype 8077`
   then open `http://127.0.0.1:8077/index.html`.
2. Toggle Variant BASELINE and PETNAME across cases COL-01 (collision),
   LIF-01 (rename), UNI-01 (confusable), UNI-05 (injection), APR-01
   (approval), APR-02 (on-behalf).
3. Confirm: canonical ID/type/scope visible in both variants; ambiguous
   petname lists every matching canonical identity with no auto-select;
   rename shows version/lifecycle; history stays canonical.

## Questions (exactly 12, one message, answer format `1A 2A ... 12A`)

1. Разрешать petnames? A: да, только display-only рядом с canonical identity; B: нет, canonical ID only; C: petname как principal key.
2. Что показывать по умолчанию? A: petname + canonical ID/type/scope; B: petname, ID после раскрытия; C: только petname.
3. Одинаковые petnames? A: explicit ambiguity + canonical selection; B: auto first/last; C: невидимый suffix.
4. При rename? A: новая versioned projection, audit canonical; B: переписать историю; C: заменить canonical ID.
5. При delete? A: удалить подпись, оставить canonical audit/tombstone; B: удалить историю; C: переиспользовать без history.
6. В approval? A: canonical actor/target, scope, action + petname annotation; B: только petname; C: petname + действие без target.
7. В on-behalf banner? A: petname + canonical actor/beneficiary + scope; B: только petname; C: friendly sentence.
8. Unicode/confusables? A: normalize для сравнения, flag/block ambiguity, original безопасно; B: доверять любой строке; C: скрывать canonical ID.
9. Поиск по petname? A: кандидаты + canonical selection; B: auto best match; C: petname = authorization target.
10. Хранение после review? A: structured answers/aggregates, raw удалить; B: de-identified raw вне Git; C: raw в Git.
11. Claim? A: только provisional display-contract, recognition не измерено; B: INCONCLUSIVE; C: users распознают лучше.
12. Статус? A: PASS_WITH_LIMITS после gates; B: OPEN/INCONCLUSIVE; C: PASS.

## Recording

Only structured answers (12 letters), timestamp (UTC), opaque operator ID and
SHA-256 of the reviewed contract/UI/bundle artifacts are stored in
`operator-decision.json`. Raw envelopes, if any transient browser files exist,
are deleted after aggregate verification; no raw identity mapping enters Git.

## Fail-closed bindings (enforced by the verifier)

- 1C, 2B/2C, 3B/3C, 4B/4C, 5B/5C, 6B/6C, 7B/7C, 8B/8C, 9B/9C, 10C block petname closure.
- 11C, 12C forbidden at human_study_n=0.
- 1B or 11B/12B yields CANONICAL_ID_ONLY or INCONCLUSIVE.
- Retention conflict resolves to the strictest policy.
- Verifier rejects missing/extra answers, unknown letters, stale artifact
  hashes, forged operator counts and manual verdict substitution.
