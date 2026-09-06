# S1-018 operator architecture-decision questionnaire (single message)

Format: `1A 2A ... 10A`. One operator may close bounded architecture
research; this never replaces an external auditor, a security
certification, or production qualification. Legal/moral blame and
production claims are always out of scope.

1. Is a server-side plaintext index inside a TEE acceptable at all?
   - **A:** no, plaintext stays client-side (architecture A);
   - **B:** yes, inside one attested boundary (architecture B);
   - **C:** yes, only per scope/epoch shard (architecture C).
2. Which architecture may remain a research-only candidate?
   - **A:** client-side index only;
   - **B:** single attested indexer PoC;
   - **C:** scope/epoch-sharded attested indexer PoC.
3. Is scope/epoch sharding mandatory for any server-side index?
   - **A:** yes;
   - **B:** no, one boundary suffices;
   - **C:** undecided on current evidence.
4. Without hardware-backed evidence, what follows?
   - **A:** research-only PoC at most, `hardware_tee_evidence=NOT_MEASURED`;
   - **B:** production pilot allowed;
   - **C:** park Profile C entirely.
5. Which leakage channels are blocking when measured?
   - **A:** content/scope leaks block; access-pattern/timing are limitations;
   - **B:** every measured channel blocks;
   - **C:** none block; document only.
6. Attestation freshness/TCB/reference-value policy?
   - **A:** exact appraisal on every session (nonce, measurement, TCB, endorsement);
   - **B:** session caching across epochs allowed;
   - **C:** attestation optional when MLS membership holds.
7. Revocation and rollback thresholds?
   - **A:** revoke dominates cache/session immediately; rollback always detected;
   - **B:** lazy invalidation within the epoch acceptable;
   - **C:** operator override may restore revoked access.
8. Acceptable fail-closed behavior and availability cost?
   - **A:** DENY/QUARANTINE on unknown, availability cost accepted;
   - **B:** degrade to best-effort reads to preserve availability;
   - **C:** retry until success regardless of outcome state.
9. Conditions for PARK-04/production re-entry?
   - **A:** hardware evidence + certification + new ticket;
   - **B:** operator approval alone suffices;
   - **C:** never, Profile C is permanently parked.
10. Which status is allowed?
    - **A:** `PASS_WITH_LIMITS` maximum;
    - **B:** production-ready `PASS`;
    - **C:** `INCONCLUSIVE` remains open.

Safety-compatible closure requires answers consistent with hard gates and
the evidence ceiling (e.g. 1A with A-only evidence; no answer may grant
production, authorization, or hardware claims). An incompatible answer is
not applied: the conflict is explained and the ticket stays
`INCONCLUSIVE` or stops.
