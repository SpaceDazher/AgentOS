# S1-018 independent audit

Producer `agentos-s1-018-producer` (model/runner, bundle assembly) and auditor `agentos-s1-018-independent-verifier` (evaluator plus process-separated replication and sensitivity) are distinct. The auditor recomputed PC1-PC15, Wilson intervals, leakage ledgers and probes A-P from frozen corpus bytes and replicated the 864-cell matrix byte-identical across two processes. Verdict: `pass_with_limits` within the stated limitations; no production, hardware or authorization claim.
