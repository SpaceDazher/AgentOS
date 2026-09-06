# S1-015 analysis plan (frozen before measurement)

- Evaluator recomputes from frozen corpus/oracle plus validated envelope bytes.
  Producer summaries, displayed labels, saved `all_passed`, saved metrics,
  operator decisions and verdicts are never trusted.
- Hard counters (10, §9): each must be an integer equal to 0 in every
  seed/executor. Any nonzero is a FAIL uncompensated by convenience scores.
- Safety rates reported as raw numerator/denominator: canonical-ID visibility
  and reveal; collision/confusable detection; correct canonical
  selection/approval rejection; rename/delete history preservation;
  keyboard/screen-reader completeness; benign acceptance/quarantine;
  task/action counts and technical latency by variant; missing/timeout/censored.
- Mandatory safety rates must be 100% for any provisional petname decision.
- Run A and Run B (distinct PID/executor/nonce/output root, one frozen
  commit/contract/corpus) must agree on canonical decisions, hard counters,
  observation hashes and probe outcomes (480 observations total).
- Technical speed/action counts never support a human recognition claim.
  `recognition_improvement=NOT_MEASURED`, `human_study_n=0`.
- Probes A-N each run through the same importer/evaluator/approval path with
  an unmodified benign control; probe K verifies fresh recomputation detects
  tampered metrics; probe L hard-fails any human-N/recognition claim; probe M
  fails on extra/missing fixtures or changed schema/version/digest; probe N
  quarantines nested PII/secrets.
