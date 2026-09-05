# Bibliographic record: ATL / strategic ability semantics (primary source) (S1-017 evidence role: atl-primary)

Full-text status: BIBLIOGRAPHIC RECORD ONLY (not a full-text snapshot).
The paper below is ACM-copyrighted scholarship; no text is reproduced. Tests
run offline and never fetch this source. Primary formal semantics is
separated from surveys: this entry is the primary source.

Canonical URI: https://doi.org/10.1145/646836.646878
Publisher: Association for Computing Machinery (Journal of the ACM)
Version: Rajeev Alur, Thomas A. Henzinger, Orna Kupferman —
"Alternating-time Temporal Logic", J. ACM 49(5), 2002, pp. 672–713
(concurrent game structures; coalition strategy quantifiers <<A>>;
temporal objectives; model checking ATL)
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: atl-primary (coalition ability, strategy quantification)
Access/license: ACM Digital Library (not vendored)
Availability: DOI resolvable 2026-09-05 (citation metadata, authors, venue)

## Concepts relied upon (identifiers, not copied text)

- Concurrent game structures: states, agents, moves per agent, transition
  function; a play results from all agents' simultaneous moves.
- `<<A>> φ` (A coalition has a collective strategy forcing φ): existential
  strategy quantification over the coalition, universal over environment
  (opponent) moves; temporal objectives (next/eventually/always/until).
- Ability is relative to the declared move repertoire: unmodeled moves are
  not capability evidence, and environment moves must be modeled explicitly
  (adversarial by default for ability claims).

## S1-017 interpretation (design inference, not the paper's text)

- ATL ability in S1-017 requires an explicit environment-move model;
  coalition ability computed without environment moves is UNDERDETERMINED
  (probe K).
- The bounded implementation covers finite deterministic concurrent games
  with declared objectives only; full ATL* / incomplete-information
  extensions are out of scope and never claimed.

No conformance claim to the full logic is made.
