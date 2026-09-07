# S1-019 technical independent audit

Verdict: **PASS_WITH_LIMITS** after the technical candidate and the real
operator decision. Canonical publication remains pending until the FLOW-11
bundle is committed and recorded in the canonical database.

The audit recomputed the dependency and wall-clock gates, inspected the
separate corpus/oracle binding, and compared two child-process runs. Run A
used agentos-s1-019-producer (PID 24056, nonce s1019-A-001) and Run B used
agentos-s1-019-independent-verifier (PID 32844, nonce s1019-B-001) at commit
b36db460093b04a4e3c3a92a033c603ad65c0208.

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
- Operator `operator-daniil-2026-09-06` selected `1A` through `10A`; the
  decision is bound to the frozen questionnaire, manifest, comparison and
  decision matrix. It cannot override hard gates and grants no production or
  Goal-acceptance authority.

Residual limits: evidence is bounded, same-host and process-separated; the ten
source snapshots are local research inputs; production-like, external-audit,
population-human, legal and hardware-attestation evidence is absent. This
audit authorizes neither production rollout nor Goal acceptance.
