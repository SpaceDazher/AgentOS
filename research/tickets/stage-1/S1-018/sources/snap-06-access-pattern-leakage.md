# Bibliographic record: confidential-computing / encrypted-search / access-pattern leakage analysis (S1-018 evidence role: leakage-analysis)

Full-text status: BIBLIOGRAPHIC RECORD ONLY (not a full-text snapshot).
The paper below is NDSS-copyrighted scholarship; no text is reproduced.
Tests run offline and never fetch this source.

Canonical URI: https://www.ndss-symposium.org/ndss2012/ndss-2012-programme/access-pattern-disclosure-searchable-encryption-ramification-attack-and-mitigation/
Publisher: NDSS Symposium 2012 (Internet Society)
Version: Mohammad Saiful Islam, Mehmet Kuzu, Murat Kantarcioglu —
"Access Pattern disclosure on Searchable Encryption: Ramification, Attack
and Mitigation", NDSS 2012 (6 February 2012)
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: leakage-analysis (access-pattern inference discipline)
Access/license: NDSS proceedings (not vendored)
Availability: NDSS programme page resolvable 2026-09-05 (title, authors, date)

## Findings relied upon (citations, not copied text)

- Searchable-encryption protocols that reveal access patterns leak
  significant confidential information to modest prior-knowledge attackers,
  demonstrated empirically on a real dataset with high accuracy.
- Oblivious-RAM-class hiding is computationally heavy and scales poorly;
  noise-based mitigation raises cost and only makes inference harder.
- Consequence for any encrypted index: content confidentiality NEVER implies
  metadata/access-pattern confidentiality; the channels must be measured
  separately.

## S1-018 interpretation (design inference, not the paper's text)

- S1-018 leakage accounting separates content/scope/query-equality/result-
  size/access-pattern/timing channels; each cell reports measured or
  NO_DATA, never a blended `secure=true`.
- TEE memory confidentiality (even if it held) would not cover the
  observer-visible query equality, result sizes or access patterns of the
  index protocol — the PoC measures exactly these channels at model scale.

No deployment-security claim is made.
