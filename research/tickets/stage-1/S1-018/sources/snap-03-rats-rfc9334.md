# Bibliographic record: RATS architecture material (S1-018 evidence role: rats-architecture)

Full-text status: BIBLIOGRAPHIC RECORD ONLY (not a full-text snapshot).
IETF documents are covered by the IETF Trust Legal Provisions; no normative
text is reproduced. Tests run offline and never fetch this source. Status is
stated exactly: this RFC is Informational, NOT Standards Track.

Canonical URI: https://www.rfc-editor.org/info/rfc9334
Publisher: Internet Engineering Task Force (IETF)
Version: RFC 9334, "Remote ATtestation procedureS (RATS) Architecture",
Informational, January 2023 (Birkholz et al.)
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: rats-architecture (roles, conceptual messages, appraisal)
Access/license: IETF Trust Legal Provisions (not vendored)
Availability: RFC Editor page resolvable 2026-09-05

## Concepts relied upon (identifiers, not copied text)

- Roles: Attester (produces Evidence), Verifier (appraises Evidence against
  Reference Values + Endorsements via an Appraisal Policy, produces
  Attestation Results), Relying Party (appraises Results for
  application-specific decisions), Endorser, Reference Value Provider.
- Conceptual messages: Evidence, Attestation Results, Endorsements,
  Reference Values, Appraisal Policy.
- Freshness via nonces/epoch IDs; the RATS passport model and background-check model topologies;
  trust anchors in a trust-anchor store.
- Security Considerations: architecture only, no wire protocol; threats are
  listed as unmitigated without a concrete proposal to compare against.

## S1-018 interpretation (design inference, not RFC text)

- S1-018 attestation appraisal mirrors RATS role separation: Evidence ≠
  Results; the Verifier's appraisal policy is host-owned and versioned;
  the Relying Party (AgentOS Gateway side) NEVER delegates ALLOW/DENY to
  attestation output (PC2).
- Attestation evidence is never policy authorization (explicit RATS-level
  separation the ticket enforces as a hard invariant).

No conformance claim is made; Informational status is never upgraded.
