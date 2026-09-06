# S1-015 privacy plan

- No real names, contact data, consent records, identity mappings, raw browser
  events or secrets enter Git at any stage.
- The corpus uses synthetic canonical IDs (`prin_*`) and synthetic owner IDs
  (`owner_A/B`); petnames are invented labels, including adversarial payloads.
- Operator review stores only 12 structured answer letters, a UTC timestamp,
  an opaque operator ID and artifact SHA-256 bindings. No raw envelopes or
  identity mappings are retained; transient browser exports are deleted after
  aggregate import verification.
- The importer quarantines any envelope matching the PII/secret pattern
  (email-like strings, passport/ssn/consent_text markers, sk-proj-/ghp_ keys)
  or carrying private keys (contact/email/phone/full_name/consent_text/address).
- Probe N verifies quarantine through the real import path with a benign
  control. Publication runs a recursive secret/PII/raw scan and removes stale
  candidate/record/pack outputs on any failure.
- Retention conflict between operator answers resolves to the strictest
  policy (structured answers/aggregates only, raw deleted).
