# S1-016 analysis plan (frozen before measurement)

- Evaluator re-executes every cell from frozen corpus bytes and recomputes
  L1-L12 from events plus frozen initial states. Producer digests, saved
  metrics, engine banners and verdicts are never trusted (probe M verifies
  forgery detection by fresh recomputation).
- Hard gates: every invariant count 0, orphans 0, authority expansions 0,
  supported round-trip 100%, audit reconstruction 100%, required invalid
  rejections 100% in every representation/seed/executor. A missing
  metric/case/seed/CI field is not zero and fails closed.
- Real pySHACL (rdflib 7.6.0, pyshacl 0.40.1) validates the exact frozen
  shape set over all 144 (scenario, representation) exports; unclassified
  violations fail closed. `pyshacl_executed=true` without process
  exit/version/report graph is not proof.
- Run A/B (distinct PID/executor/nonce/output root, one clean commit/frozen
  input) must agree on canonical terminal states, digests, counters,
  round-trip hashes and probe outcomes (864 observations).
- Sensitivity: equal base weights, +-50% per dimension, leave-one-dimension
  out, 729-vector deterministic grid (748 vectors total). Safety gates are
  unweighted. Any winner flip is recorded and caps the verdict.
- Latencies are same-host technical measurements (export/import/reconstruct
  ns, p50/p95/max), never production SLOs.
