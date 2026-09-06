# Bibliographic record: TEE platform TCB/quote material — AMD SEV-SNP, explicitly chosen (S1-018 evidence role: tee-platform)

Full-text status: BIBLIOGRAPHIC RECORD ONLY (not a full-text snapshot, no
test vectors vendored). AMD documents are AMD-copyrighted technical
publications; nothing is reproduced. Tests run offline and never fetch this
source. Exactly ONE platform is chosen below; no claim covers any other TEE.

Canonical URI: https://www.amd.com/content/dam/amd/en/documents/epyc-technical-docs/specifications/56860.pdf
Publisher: Advanced Micro Devices, Inc. (AMD)
Version: "SEV Secure Nested Paging Firmware ABI Specification",
AMD Publication #56860; Revision 1.55, September 2023 as normatively cited
by the IETF SEV-SNP CoRIM profile draft; AMD portal lists newer revisions
(up to Rev 1.59, August 2026). Snapshot pins the cited revision only.
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: tee-platform (report structure, TCB versioning, VCEK model)
Access/license: AMD technical publication, public PDF (not vendored)
Availability: AMD portal + IETF draft citation resolvable 2026-09-05

## Concepts relied upon (identifiers, not copied text)

- SNP_GUEST_REQUEST attestation flow: guest supplies 512 bits of arbitrary
  data (nonce binding); the report carries launch identity, TCB version,
  migration policy and is signed by the chip-unique VCEK for the TCB.
- ReportedTcb vs CurrentTcb decoupling; VCEK certificate chain for verifier
  appraisal; ATTESTATION_REPORT structure with measurement fields.
- SEV-SNP CoRIM profile draft (IETF, deeglaze): normative translation of
  report fields into reference-triple records for appraisal — cited as a
  DRAFT, never as a standard.

## S1-018 interpretation and hard boundary (design inference, not AMD text)

- Mock quotes in the PoC mirror the FIELD SHAPE discipline (measurement,
  TCB version, nonce, signer id) WITHOUT hardware backing, VCEK chain, or
  report-byte compatibility; `hardware_tee_evidence=NOT_MEASURED` always.
- Public attestation test vectors were NOT executed in this ticket (no
  offline vector bundle was frozen); all appraisal runs are protocol
  validation over mock evidence. A software-emulated quote proves nothing
  about any hardware TEE.

No platform security claim is made; no other TEE is covered.
