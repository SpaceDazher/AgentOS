# S1-013 independent audit (preparation)

Role: agent-implemented audit path independent from the producer
(importer) path: the scorer recomputes every measure from session
files plus frozen oracle files, never from producer summaries.

Checked pre-pilot:
- Protocol/rubric/scenario/schema hashes match the frozen manifest.
- Importer boundaries: duplicate/malformed/no-consent rejected, PII
  quarantined, event vocabulary exact, sequence monotonic.
- Scorer rules: C4 needs valid explanation, C5 needs confirmed
  acknowledgement in window with failures kept in denominators,
  approval oracle exact, N/hour clustered with load probes excluded.
- Probes A-H pass through the real importer/scorer path, each with
  a passing unmutated control and a specific assertion.
- Replication: a separate process pair reproduces metrics, probes
  and observations byte-identical (see comparison.json).
- Bundle: native schema passes the real normalizer and evaluation
  checks; claim classes mapped explicitly; producer/auditor
  distinct; verdict derived, never constant.
- Privacy: no PII, contacts, consent originals or reidentification
  keys in tracked files (scanner test green); quarantine path
  exercised by probe H.

Explicitly NOT covered by agent-only audit (requires humans):
second human rater coding, consent administration, session
facilitation, privacy release review, ethics consideration.
