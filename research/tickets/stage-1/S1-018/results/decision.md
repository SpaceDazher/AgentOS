# S1-018 decision: CLIENT_SIDE_INDEX_ONLY

Status: `CLOSED_WITH_LIMITS`. Operator review: `COMPLETE`.

Three architectures execute one observable request/result contract over 48 frozen cases x 3 seeds (432 observations per executor, 864 total). PC1-PC15 counters are zero in every seed/executor; critical false accepts, post-revoke reads and cross-scope reads are zero; leakage channels are measured separately with NO_DATA discipline; probes A-P pass through the real path with benign controls; sensitivity vectors are recorded raw.

Operator answers `1A 2A 3A 4A 5A 6A 7A 8A 9A 10A`. bounded evidence supports CLIENT_SIDE_INDEX_ONLY for the declared research scenarios within ceiling ATTESTED_SCOPE_INDEXER_POC. It does not establish hardware TEE security, absence of side channels, production SLO/conformance, or authorization outside the AgentOS Gateway.
