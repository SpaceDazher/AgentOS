# S1-017 independent audit

Producer `agentos-s1-017-producer` (analyzer/runner) and auditor `agentos-s1-017-independent-verifier` (evaluator, replication, recomputation) are distinct. The auditor recomputed every observation from corpus bytes, checked R1-R14, compared verdicts against a construction-intent oracle that never ran the analyzer, and replicated the 864-observation matrix across two processes. Verdict: `pass_with_limits` within the stated limitations; no human, legal or production claim.
