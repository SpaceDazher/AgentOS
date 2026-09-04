# Retrieval record (not a source claim)

- snapshot: snap-01-prov-overview.md
- canonical_uri: https://www.w3.org/TR/prov-overview/
- version: W3C Working Group Note 30 April 2013 (versioned URI
  http://www.w3.org/TR/2013/NOTE-prov-overview-20130430/)
- retrieved_at: 2026-09-04T00:00:00Z (UTC)
- method: webfetch-text of the versioned NOTE; substantive fragment
  archived below (Abstract, family table, Introduction, Namespace).
  Navigation chrome and the member list are omitted; see the
  reproducibility limit.
- reproducibility_limit: fragment, not the full page bytes. The
  archived statements are verbatim excerpts; section numbers and the
  versioned URI allow byte-level re-verification against the source.
- license_note: W3C document use rules apply (see source snippet).

# Archived fragment (verbatim)

Title: PROV-Overview — An Overview of the PROV Family of Documents
Editors: Paul Groth (VU University Amsterdam), Luc Moreau (University
of Southampton)

## Abstract

Provenance is information about entities, activities, and people
involved in producing a piece of data or thing, which can be used to
form assessments about its quality, reliability or trustworthiness.
The PROV Family of Documents defines a model, corresponding
serializations and other supporting definitions to enable the
inter-operable interchange of provenance information in heterogeneous
environments such as the Web.

## PROV Family of Documents

- PROV-OVERVIEW (Note), an overview of this family (this document);
- PROV-PRIMER (Note), a primer for the PROV data model;
- PROV-O (Recommendation), the PROV ontology, an OWL2 ontology allowing
  the mapping of the PROV data model to RDF;
- PROV-DM (Recommendation), the PROV data model for provenance;
- PROV-N (Recommendation), a notation for provenance aimed at human
  consumption;
- PROV-CONSTRAINTS (Recommendation), constraints applying to the PROV
  data model;
- PROV-XML (Note), an XML schema for the PROV data model;
- PROV-AQ (Note), mechanisms for accessing and querying provenance;
- PROV-DICTIONARY (Note), key-entity pair collections;
- PROV-DC (Note), mapping between PROV-O and Dublin Core Terms;
- PROV-SEM (Note), declarative first-order-logic specification;
- PROV-LINKS (Note), linking across bundles.

## 1. Introduction (excerpt)

"Provenance is information about entities, activities, and people
involved in producing a piece of data or thing, which can be used to
form assessments about its quality, reliability or trustworthiness. ...
At its core is a conceptual data model (PROV-DM), which defines a
common vocabulary used to describe provenance."

"The design of PROV stems from the recommendations of the Provenance
Incubator Group ... 8 broad recommendations were defined. Summarizing,
the report recommends that a provenance framework should support: the
core concepts of identifying an object, attributing the object to
person or entity, and representing processing steps; ... the provenance
of provenance; reproducibility; versioning; representing procedures;
and representing derivation."

## 3. Namespace

"All terms defined within PROV are defined within the namespace
http://www.w3.org/ns/prov#. The prefix convention that is used is
prov."
