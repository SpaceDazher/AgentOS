# SRC-04 mental model excerpt (S1-015 evidence role: mental-model / QM3)

Provenance: excerpt of the locally authorized S1-013 snapshot
`research/tickets/stage-1/S1-013/sources/snap-06-src04-mental-model.md`
(SHA-256 cf4789616c2465389db58a645deed39a26f1f79f6a7272632bd6fe5fb73b4eab,
11322 bytes, inspected 2026-09-04). Internal design input, not a public URI.
Canonical URI below is a local stable identifier for the excerpt.

Canonical URI: https://local.agentos.invalid/AgentOS/research/tickets/stage-1/S1-015/sources/snap-01-src04-mental-model.md
Publisher: AgentOS research (internal SRC-04, v2, independently audited round 13)
Version: SRC-04 v2 excerpt, sections 2/3/7/8 (S1-015 freeze 2026-09-05)
Retrieved at: 2026-09-05T00:00:00Z
Evidence role: mental-model (QM3 petname question)
Access/license: internal design input, full-text snapshot authorized locally

## Verbatim excerpts (sections relevant to principal recognition)

Section 2 (conceptual objects, abridged to identity rows):

- "Мой агент" = AgentInstallation (+ RuntimeInstance); key question: "что ему можно прямо сейчас?"
- "Поручение" = DelegationGrant + Run; key question: "на что я его уполномочил?"
- "Системный помощник" = PlatformAgent; key question: "что именно он обслуживает?"
- "Чужой внешний агент" = ExternalAgent; key question: "кто за него отвечает?"
- Rule: each metaphor has exactly one visual form; hybrid images are forbidden.

Section 3 (delegation visibility, identity-critical rules):

1. On-behalf banner: every agent action is tagged "от имени X · права: Y · в Z";
   for high-impact actions the banner cannot be disabled (F-10.1).
2. Progressive disclosure: banner -> grant card -> full journal within 3 clicks.
3. No persuasion: confidence and boundaries next to results, never "trust it".
5. Audit symmetry: any agent action is showable to the owner AND the affected party.
6. Stop line: global "stop all my agents" and per-run cancel from one place.

Section 7 (comprehension metrics, MVP acceptance):

1. Delegation vs password (>=90%).
2. Who sees private space contents (>=95%).
3. Foreign-agent message vs group knowledge (>=85%).
4. Can a system agent read personal data without explicit connection (>=95% "no").
5. How to stop all owned agents (<=30 s).

Section 8 (open questions, QM3 verbatim):

- "QM3: petname-словарь [G16] — персональные псевдонимы принципалов в UI при канонических ID."

S1-015 use: QM3 is the exact research question of this ticket. The mental model
requires that the UI show exactly the ontology entities with no hidden
participants, and that on-behalf/approval views carry canonical actor identity.
A petname may therefore only be an additional owner-local display projection;
it can never replace the canonical principal ID in authority-relevant views.
No recognition-improvement claim is sourced from this excerpt.
