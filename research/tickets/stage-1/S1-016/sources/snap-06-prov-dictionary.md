# Bibliographic / availability record: W3C PROV Dictionary (S1-016 evidence role: prov-dictionary)

Full-text status: BIBLIOGRAPHIC RECORD ONLY (not a full-text snapshot).
This document is a W3C Working Group Note — it is explicitly NOT a W3C
Recommendation and carries no normative endorsement beyond its informative
content. This status is stated exactly and never upgraded. Unit tests run
offline and never fetch this source.

Canonical URI: https://www.w3.org/TR/prov-dictionary/
Publisher: World Wide Web Consortium (W3C Provenance Working Group)
Version: PROV Dictionary, W3C Working Group Note 30 April 2013
Status: Working Group Note (NOT a Recommendation)
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: prov-dictionary (insertion/deletion membership pattern)
Access/license: public Note under W3C Document License (not vendored)
Availability: canonical URI resolvable 2026-09-05 (Note + worked examples)

## Concepts relied upon (identifiers, not copied text)

- prov:Dictionary, prov:EmptyDictionary; prov:hadDictionaryMember /
  prov:hadMember; prov:DerivedByInsertionFrom, prov:DerivedByRemovalFrom.
- Insertion/removal derive a NEW dictionary entity; the prior entity and its
  memberships persist (the Note's worked newspaper/phone-book examples derive
  successive snapshots rather than mutating).
- Key/Entity-pair membership with pair ordering; removal closes membership
  without deleting the inserted history.

## S1-016 interpretation (design inference, not W3C text)

- Dictionary insertion/removal is the export pattern for collection
  membership; runtime authority stays with the flat scope + append-only
  operation log (representations A/C) or explicit runtime relations (B).
- Removal yields a tombstone/closed interval, never a history rewrite (L5).
- Unsupported PROV constructs in import map to explicit UNSUPPORTED, never
  silent drops (L9 gate).

No conformance claim is made; the Note status is never presented as
Recommendation force.
