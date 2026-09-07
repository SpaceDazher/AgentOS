# S1-019 technical independent audit

Verdict: **TECHNICAL_CANDIDATE**, ceiling **PASS_WITH_LIMITS**. Canonical
publication is deliberately blocked until a real operator answers the frozen
questionnaire.

The audit recomputed the dependency and wall-clock gates, inspected the
separate corpus/oracle binding, and compared two child-process runs. Run A
used agentos-s1-019-producer (PID 4252, nonce s1019-A-001) and Run B used
agentos-s1-019-independent-verifier (PID 34544, nonce s1019-B-001) at commit
857b88c0c23e560f332be090fed69861de95172f.

- 18/18 dependency records are proven from immutable commit
  19ff320adfe7153267fb634268038ae16ba25a16.
- Wall-clock preflight is PASS_WITH_LIMITS; wall-clock is absent from the
  cross-ticket decision rule.
- 72 unique cases ran once in each process: 144 complete observations.
- SYN1-SYN18 recompute to zero for each run.
- Probes A-P were all created and detected through the evaluator path.
- Semantic digest is identical:
  741f9f031739f88c04ecb5d7f04c945be8677d84e863aef8b7ca49c54e144a24.
- Deterministic sensitivity executed 264 perturbations with zero flips and
  zero unknown-dependent decisions.

Residual limits: evidence is bounded, same-host and process-separated; the ten
source snapshots are local research inputs; production-like, external-audit,
population-human, legal and hardware-attestation evidence is absent. This
audit authorizes neither production rollout nor Goal acceptance.
