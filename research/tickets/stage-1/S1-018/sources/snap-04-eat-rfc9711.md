# Bibliographic record: evidence/claims format (EAT) (S1-018 evidence role: eat-format)

Full-text status: BIBLIOGRAPHIC RECORD ONLY (not a full-text snapshot).
IETF documents are covered by the IETF Trust Legal Provisions; no normative
text is reproduced. Tests run offline and never fetch this source.

Canonical URI: https://www.rfc-editor.org/info/rfc9711
Publisher: Internet Engineering Task Force (IETF)
Version: RFC 9711, "The Entity Attestation Token (EAT)", Standards Track,
April 2025 (Lundblade et al.)
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: eat-format (attested claims-set envelope shape)
Access/license: IETF Trust Legal Provisions (not vendored)
Availability: RFC Editor page resolvable 2026-09-05

## Concepts relied upon (identifiers, not copied text)

- EAT as a claims-set envelope (CWT/JWT) carrying attestation-oriented
  claims from attester to relying party/verifier; authenticity + integrity
  protection required; nonce/freshness claims for replay resistance.
- EAT profiles specialize the base format per use case; verification is
  profile-bound (a token verifies only against its declared profile).

## S1-018 interpretation (design inference, not RFC text)

- S1-018 mock evidence envelopes mirror the EAT shape discipline (claims
  set + nonce + profile id) WITHOUT claiming EAT conformance, hardware
  backing, or cross-system acceptance.
- Profile binding in the PoC (declared profile/version checked on every
  appraisal) follows the same principle at model scale.

No EAT conformance claim is made; mock quotes are never presented as EATs.
