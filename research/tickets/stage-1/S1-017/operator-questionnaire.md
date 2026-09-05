# S1-017 operator architecture-decision questionnaire (Phase B, single message)

Format: `1A 2A ... 10A`. One operator may accept a research architecture
decision; this never replaces an external auditor or a human-subject study.
Legal/moral blame is always OUT_OF_SCOPE.

1. Где выполнять responsibility analytics?
   - **A:** offline only;
   - **B:** при export/audit query;
   - **C:** bounded runtime annotation;
   - **D:** inconclusive.
2. Может ли annotation влиять на authorization?
   - **A:** никогда;
   - **B:** только как advisory input;
3. Что делать при неполном trace?
   - **A:** `UNDERDETERMINED`;
   - **B:** best-effort attribution;
4. Что считать authoritative actor identity?
   - **A:** canonical principal ID;
   - **B:** display name/petname;
5. Как трактовать revoked grant?
   - **A:** unavailable после durable commit;
   - **B:** available до observation worker-ом;
6. Как хранить corrections?
   - **A:** append-only `supersedes`;
   - **B:** overwrite annotation;
7. Допустимо ли утверждать legal/moral blame?
   - **A:** нет, out of scope;
   - **B:** да, если model уверен;
8. Что делать при disagreement STIT/ATL моделей?
   - **A:** показать assumptions и ограничить вывод;
   - **B:** выбрать лучший score silently;
9. Как хранить derived annotation?
   - **A:** content-addressed/versioned, `authority=false`;
   - **B:** обычное mutable поле policy record;
10. Какой статус допустим?
    - **A:** `PASS_WITH_LIMITS` максимум;
    - **B:** production-ready `PASS`.

Safety-compatible answers: `1A/1B/1C/1D`, `2A 3A 4A 5A 6A 7A 8A 9A 10A`.
An incompatible answer is not applied: the conflict is explained and the
ticket stays `INCONCLUSIVE` or stops.
