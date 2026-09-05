# S1-016 privacy plan

- No real content, contact data, credentials, identity mappings, raw traces
  or secrets enter Git at any stage. Corpus content strings are synthetic
  (`hello`, `c1`, single adversarial canary for the quarantine probe).
- The quarantine probe (P/X-11) uses one synthetic canary staging token that
  matches the detector pattern; it is not a real credential and is handled
  only inside quarantined observations, never published.
- Operator review stores only 10 structured answer letters, a UTC timestamp,
  an opaque operator ID and artifact SHA-256 bindings.
- The importer quarantines envelopes matching the PII/secret pattern or
  carrying private keys; probe P verifies quarantine through the real path.
- Publication runs a recursive secret/private-data scan and removes stale
  candidate/record/pack outputs on any failure.
