# S1-015 decision: CANONICAL_ID_ONLY

Status: `CLOSED_WITH_LIMITS` (cap: PASS_WITH_LIMITS at most). Operator review: `COMPLETE`.

Prototype exports the same envelope accepted by the Python importer for BASELINE and PETNAME variants across 40 frozen cases x 3 seeds (240 observations per executor, 480 total). Hard counters are zero in every seed/executor; mandatory safety rates are 100%; probes A-N pass through the real path with benign controls; the real-browser probe (Edge/Chromium) walks both variants and round-trips through the importer.

Operator answers `1A 2B 3A 4A 5A 6A 7A 8A 9A 10A 11A 12A`.  Operator answers prohibit a petname contract; the fail-closed product decision is CANONICAL_ID_ONLY. Human recognition improvement remains NOT_MEASURED.
