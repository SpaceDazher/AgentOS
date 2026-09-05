# Bibliographic / availability record: digital-identity guidance + naming/recognition context (S1-015 evidence role: naming-context)

Full-text status: BIBLIOGRAPHIC RECORD ONLY (not a full-text snapshot).
NIST publications are U.S. public-domain works; no normative text is
reproduced here beyond the citation. Unit tests run offline and never fetch
this source. This source is CONTEXT ONLY: it never overrides the AgentOS
identity invariants and no product-truth claim is derived from it.

Canonical URI: https://pages.nist.gov/800-63-4/
Publisher: National Institute of Standards and Technology (NIST)
Version: NIST SP 800-63-4 (second public draft and final-issue series;
identity-proofing, authentication and federation guidance; retrieved
2026-09-05). Naming/recognition context additionally informed by the
long-standing petname-system literature (e.g. Stajano "The Resurrecting
Duckling" / " cámaras" discussion of user-chosen local names bound to
cryptographic identity, 2002-2004) — cited as hypothesis context only.
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: naming-context (digital-identity guidance + petname hypothesis)
Access/license: NIST works are U.S. public domain; petname literature remains
with its original publishers; nothing vendored here
Availability: canonical NIST URI resolvable 2026-09-05 (SP 800-63-4 overview,
parts -63A/-63B/-63C). Petname-system papers available through academic
publishers; no PDF archived.

## Principles relied upon (citations, not copied text)

- Identity is established through proofing and bound to an authenticator;
  local nicknames are presentation aids and never the authenticator.
- Identifiers used in authorization decisions must be unique and resolvable
  to exactly one subject within their scope; ambiguity must be resolved to a
  canonical identifier before any authorization.
- Federation carries explicit scope/issuer bindings; a name valid in one
  scope is meaningless (and must fail) in another without re-binding.
- Human-recognition effects (whether nicknames help users) are empirical
  claims requiring human studies; they cannot be inferred from a technical
  prototype or from synthetic trials.

## S1-015 interpretation (design inference, not NIST text)

- Petnames are owner-local, versioned, display-only projections scoped to
  (owner, tenant/scope); cross-scope reuse is a collision, not a migration.
- Reverse lookup petname→principal never authorizes; collision returns an
  explicit candidate set and requires canonical selection.
- Any recognition-improvement claim stays NOT_MEASURED in this ticket
  (human_study_n=0); a future multi-participant study with a frozen analysis
  would be required. Synthetic observations are technical only.

No NIST conformance and no human-effectiveness claim is made.
