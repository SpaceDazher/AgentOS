# S1-014 privacy plan

- No participants are recruited. The only human is the operator acting as
  owner/reviewer (design approval). `human_study_n=0`.
- The browser prototype is static and offline: no network telemetry, no
  external scripts/fonts, CSP `default-src 'none'`, opaque random IDs, no name
  or contact fields, no free text.
- Git may contain only: structured questionnaire answers
  (`operator-decision.json`), aggregate results, hashes, and synthetic
  technical envelopes (`synthetic/sessions`, role `synthetic_technical_replay`).
- Forbidden in Git: operator raw browser envelope, PII, secrets, raw consent,
  free text, identity mapping. The importer quarantines any payload with PII
  or secret patterns and forbidden keys; quarantined payloads are never copied
  into tracked evidence.
- Retention: the operator's own export stays outside the repository and is
  deleted after the aggregate is recorded (stricter option always wins if
  answers 9A/9B conflict).
- Accessibility accommodations are disclosed in the decision record without
  excluding any result.
