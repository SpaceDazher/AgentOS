# S1-015 independent audit

Producer `agentos-s1-015-producer` (importer/runner, bundle assembly) and auditor `agentos-s1-015-independent-verifier` (evaluator plus process-separated replication over frozen inputs) are distinct. The auditor recomputed hard counters, safety rates and probes A-N from frozen corpus/oracle bytes and replicated the 480-observation matrix byte-identical across two processes. Verdict: `pass_with_limits` within the stated limitations; no human-effectiveness claim.
