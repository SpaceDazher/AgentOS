# Bibliographic / availability record: Unicode security, confusables, normalization (S1-015 evidence role: unicode-security)

Full-text status: BIBLIOGRAPHIC RECORD ONLY (not a full-text snapshot).
The Unicode Standard and UTS #39 are copyrighted by Unicode, Inc. and
distributed under the Unicode Terms of Use. No normative table bytes are
reproduced here. Unit tests run offline and never fetch this source.

Canonical URI: https://www.unicode.org/reports/tr39/
Publisher: Unicode Consortium
Version: Unicode Technical Standard #39, "Unicode Security Mechanisms";
normative data version: Unicode 16.0.0 (UTS #39 revision tied to 16.0.0,
retrieved 2026-09-05; data files: confusables.txt, confusablesSummary.txt,
intentional.txt, mixed-script handling per Section 5)
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: unicode-security (confusable / mixed-script / normalization)
Access/license: public specification; full text available at canonical URI
under Unicode Terms of Use; not vendored here
Availability: canonical URI resolvable 2026-09-05 (landing page + Section 5
mixed-script detection, Section 4 confusable detection, Section 3 identifier
robustness). Offline verification uses the section numbers below, not bytes.

## Sections relied upon (section numbers, not copied text)

- UTS #39 Section 3: identifier robustness — case, normalization (NFC/NFKC),
  whitespace and delimiter handling for security-sensitive comparison.
- UTS #39 Section 4: confusable detection — whole-script and mixed-script
  confusables (e.g. Latin "a" U+0061 vs Cyrillic "а" U+0430); skeleton
  comparison as a detection aid, never as an identity key.
- UTS #39 Section 5: mixed-script and restriction levels — Highly Restrictive
  vs Minimally Restrictive identifier policies; mixed-script labels are
  suspicious by default in authority contexts.
- UTS #39 Section 6+: invisible / control characters — bidi controls
  (U+202A-U+202E, U+2066-U+2069), joiners (U+200C-U+200D), zero-width space
  (U+200B), and their display hazards.
- Unicode Standard Annex #15 (normalization): NFC/NFKC equivalence classes
  relied upon for comparison only; the original label bytes are preserved for
  display through a safe text API.

## S1-015 interpretation (design inference, not Unicode text)

- Compare petnames with NFC + casefold for collision detection; never
  silently merge distinct principals on skeleton equality.
- Flag mixed-script, confusable, bidi/invisible labels as ambiguous or
  quarantined; keep the canonical ID visible regardless.
- Store the original label bytes; render only through a safe text API
  (textContent), never innerHTML.

No conformance claim to Unicode is made; the standard is used only to name
the attack classes exercised by the S1-015 corpus and probes C/D.
