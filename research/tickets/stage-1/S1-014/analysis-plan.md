# S1-014 analysis plan (frozen before results)

- Unit of report: variant × task and variant × complexity stratum.
- Raw counts always accompany rates; denominator = assigned trials.
- Correctness against the frozen oracle; provenance recall as exact/partial/none
  set match; challenge seen/not/missing; overload counts.
- Time: submitted-only median and censored-inclusive median; timeouts stay in
  the distribution; missing trials are reported as missing, never imputed.
- Disclosure actions and keyboard steps: medians plus raw lists.
- Technical replay: two processes (distinct PID/executor/nonce/output root)
  must match on observation and metric digests over three seeds.
- Operator answers: one descriptive observation; no CI, no power, no
  participant inference, no winner. Synthetic or operator data always yields
  `comparative_human_effectiveness=NOT_MEASURED`.
- Decision: only `decision-rule.json`; hard-gate violation blocks a variant
  regardless of speed; `NO_DEFAULT` → INCONCLUSIVE.
