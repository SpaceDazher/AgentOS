# Bibliographic / availability record: accessible names, labels, non-visual identification (S1-015 evidence role: accessibility)

Full-text status: BIBLIOGRAPHIC RECORD ONLY (not a full-text snapshot).
W3C Recommendations are copyrighted by W3C and available under the W3C
Document License. No normative WCAG success-criterion text is reproduced
here. Unit tests run offline and never fetch this source.

Canonical URI: https://www.w3.org/TR/WCAG22/
Publisher: World Wide Web Consortium (W3C)
Version: Web Content Accessibility Guidelines (WCAG) 2.2, W3C Recommendation
11 December 2023; supporting notes: WAI "Accessible Names" guidance and
WAI-ARIA accessible-name computation (retrieved 2026-09-05)
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: accessibility (accessible names / non-visual identification)
Access/license: public recommendation; full text at canonical URI under the
W3C Document License; not vendored here
Availability: canonical URI resolvable 2026-09-05 (WCAG 2.2 Overview,
Understanding docs for Name/Role/Value and Labels, WAI-ARIA name computation).

## Guidance relied upon (principle numbers, not copied text)

- Every interactive control exposes a programmatically determinable
  accessible name (name/role/value); the name must identify the control's
  purpose without relying on vision alone.
- Visible labels and accessible names must be consistent: a sighted user and
  a screen-reader user must be able to identify the same principal.
- Color and iconography alone are never the sole means of conveying identity
  or state; text alternatives carry the authoritative value.
- Keyboard operability: all identity-selection and approval actions are
  reachable and operable by keyboard with a visible focus indicator.
- On-behalf and approval views expose the canonical actor/beneficiary identity
  both visually and in the accessibility tree.

## S1-015 interpretation (design inference, not W3C text)

- Each principal-display envelope carries an accessibility_text field that
  always contains the canonical principal ID, type and scope in plain text.
- Ambiguous petnames expose every matching canonical identity as selectable
  text (no auto-select, no invisible suffix).
- Copy-canonical-ID is a keyboard-reachable control whose accessible name
  contains the canonical ID.
- Hiding or truncating the canonical ID in the visual or accessibility tree
  is an identity gate FAIL (probe I).

No WCAG conformance claim is made; the guidance is used only to define the
accessibility identity-omission counter and the keyboard/screen-reader cases.
