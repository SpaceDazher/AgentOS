# Bibliographic / availability records: W3C PROV-DM and PROV-O (S1-016 evidence role: prov-standard)

Full-text status: BIBLIOGRAPHIC RECORDS ONLY (not full-text snapshots).
W3C Recommendations are copyrighted by W3C under the W3C Document License.
No normative text is reproduced here. Unit tests run offline and never fetch
these sources. Normative status is stated exactly as published.

Canonical URI (PROV-DM): https://www.w3.org/TR/prov-dm/
Publisher: World Wide Web Consortium (W3C)
Version: PROV-DM: The PROV Data Model, W3C Recommendation 30 April 2013
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: prov-standard (Entity/Activity/Agent, derivation/generation)
Access/license: public Recommendation under W3C Document License (not vendored)
Availability: canonical URI resolvable 2026-09-05 (Overview + DM + constraints)

Canonical URI (PROV-O): https://www.w3.org/TR/prov-o/
Publisher: World Wide Web Consortium (W3C)
Version: PROV-O: The PROV Ontology, W3C Recommendation 30 April 2013
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: prov-standard (OWL2 ontology mapping for RDF export)
Access/license: public Recommendation under W3C Document License (not vendored)
Availability: canonical URI resolvable 2026-09-05 (ontology + examples)

## Concepts relied upon (identifiers, not copied text)

- prov:Entity (ArtifactVersion), prov:Activity (operation/run),
  prov:Agent (actor); prov:wasGeneratedBy, prov:wasDerivedFrom,
  prov:wasAttributedTo, prov:wasInvalidatedBy, prov:actedOnBehalfOf.
- PROV constraints (uniqueness, ordering, impossibility): identifiers denote
  one thing; generation precedes invalidation; derivation implies provenance.
- PROV-O classes/properties mirror the DM for RDF; S1-016 exports a declared
  subset plus an AgentOS extension namespace for scope/version fields.

## S1-016 interpretation (design inference, not W3C text)

- wasInvalidatedBy models membership closure/tombstones, never history edits.
- Derivation edges never authorize (L6); scope remains a separate mandatory
  property on every Entity (L1).
- AgentOS scope/version/interval fields live in the extension namespace so a
  PROV-only consumer still sees valid core PROV.

No W3C conformance claim is made.
