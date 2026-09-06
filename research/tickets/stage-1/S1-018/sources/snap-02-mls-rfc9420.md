# Bibliographic record: MLS primary standard (S1-018 evidence role: mls-standard)

Full-text status: BIBLIOGRAPHIC RECORD ONLY (not a full-text snapshot).
IETF documents are covered by the IETF Trust Legal Provisions / BCP 78; no
normative text is reproduced here. Tests run offline and never fetch this
source. MLS group/key semantics are separated from any AgentOS index/search
overlay; the standard defines no search index.

Canonical URI: https://www.rfc-editor.org/info/rfc9420
Publisher: Internet Engineering Task Force (IETF)
Version: RFC 9420, "The Messaging Layer Security (MLS) Protocol",
Standards Track, July 2023 (Barnes et al.)
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: mls-standard (group lifecycle, epochs, key schedule)
Access/license: IETF Trust Legal Provisions (not vendored)
Availability: RFC Editor page resolvable 2026-09-05 (status, authors, formats)

## Concepts relied upon (identifiers, not copied text)

- MLS groups with epochs: Add/Update/Remove/Commit proposals advance the
  group epoch; each epoch has fresh key material via the key schedule.
- Removed members must not access post-removal epochs (forward secrecy /
  post-compromise security design goals).
- Security Considerations section: the standard's own statement of what it
  does and does not guarantee (delivery, authentication service, group
  agreement assumptions).

## S1-018 interpretation (design inference, not RFC text)

- MLS epochs model the S1-018 group/index epoch monotonicity (PC7) and the
  removed-member-gets-no-new-keys rule (PC9).
- MLS says nothing about searchable indexes, access-pattern leakage, or
  attestation; those overlays need their own evidence and must not borrow
  MLS authority.

No conformance claim to MLS is made.
