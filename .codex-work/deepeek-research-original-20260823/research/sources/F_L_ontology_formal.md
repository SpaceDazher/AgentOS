# Sources F (KR/provenance/argumentation) + L (logics/formal verification)

Provenance: subagent 25581627-af5a-4fb0-b089-2e740d972b01, collected offline. ALL rows Conf=u.
URL forms chosen rot-resistant: w3.org/TR/<short-name>, SEP entries, DOIs, dblp records, publisher pages.

## Domain F — KR & provenance

| ID | Title | Authors/Org | Year | Type | URL | Key claim | Informs | Conf |
|----|-------|-------------|------|------|-----|-----------|---------|------|
| F1 | RDF 1.1 Concepts and Abstract Syntax | Cyganiak, Wood, Lanthaler (eds.), W3C | 2014 | spec | https://www.w3.org/TR/rdf11-concepts/ | Triples as IRIs/literals/graphs; global identification of entities. | onto | u |
| F2 | RDF Schema 1.1 | Brickley, Guha (eds.), W3C | 2014 | spec | https://www.w3.org/TR/rdf-schema/ | Class/property hierarchy vocabulary — minimal typing for hub taxonomy. | onto | u |
| F3 | OWL 2 Profiles | Motik, Patel-Schneider, Grau (eds.), W3C | 2012 | spec | https://www.w3.org/TR/owl2-profiles/ | EL/QL/RL tractable profiles with polynomial reasoning — keep reasoning decidable/fast. | onto,math | u |
| F4 | SHACL | Knublauch, Kontokostas (eds.), W3C | 2017 | spec | https://www.w3.org/TR/shacl/ | Closed-shape validation with severities — structural promotion gate enforcing provenance fields. | onto,arch | u |
| F5 | JSON-LD 1.1 | Sporny et al. (eds.), W3C | 2020 | spec | https://www.w3.org/TR/json-ld11/ | JSON-native serialization with @context — wire format preserving semantics. | onto | u |
| F6 | SKOS Reference | Baker et al. (eds.), W3C | 2009 | spec | https://www.w3.org/TR/skos-reference/ | Concepts/labels/broader-narrower/mappings — align heterogeneous vocabularies into group knowledge. | onto | u |
| F7 | PROV-DM | Moreau, Missier (eds.), W3C | 2013 | spec | https://www.w3.org/TR/prov-dm/ | Entity–Activity–Agent provenance with derivation/attribution/delegation — lineage template. | onto | u |
| F8 | PROV-O | Lebo, Sahoo, McGuinness (eds.), W3C | 2013 | spec | https://www.w3.org/TR/prov-o/ | OWL encoding: prov:Agent, wasAttributedTo, actedOnBehalfOf maps human↔agent delegation natively. | onto | u |
| F9 | PROV-Dictionary | Huynh, Moreau (W3C WG Note) | 2013 | spec | https://www.w3.org/TR/prov-dictionary/ | Provenance for keyed collections — evolving Workspace contents lineage. | onto | u |
| F10 | Knowledge Graphs (survey) | Hogan et al., ACM CSUR 54(4):71 | 2021 | survey | https://doi.org/10.1145/3447772 | KG lifecycle: modeling, extraction, quality, embedding, maintenance — group-knowledge construction blueprint. | onto | u |
| F11 | Reasoning About Knowledge | Fagin, Halpern, Moses, Vardi, MIT Press | 1995 | book | https://mitpress.mit.edu/9780262562003/reasoning-about-knowledge/ | Kripke semantics for knowledge; distributed-systems knowledge axioms; common knowledge. | math | u |
| F12 | Dynamic Epistemic Logic | van Ditmarsch, van der Hoek, Kooi, Springer | 2008 | book | https://doi.org/10.1007/978-1-4020-5839-4 | Action-model updates over epistemic models — message-driven knowledge change semantics. | math | u |
| F13 | Epistemic Logic (SEP) | Hendricks, Symons, SEP | 2004– | survey | https://plato.stanford.edu/entries/logic-epistemic/ | Modal epistemic logic survey: K, common knowledge, multi-agent systems. | math | u |
| F14 | On the Logic of Theory Change (AGM) | Alchourrón, Gärdenfors, Makinson, JSL 50(2) | 1985 | paper | https://doi.org/10.2307/2273922 | Contraction/revision postulates over deductively closed belief sets — claim retraction baseline. | math | u |
| F15 | Updating vs Revising a Knowledge Base | Katsuno & Mendelzon, AIJ 48(2) | 1991 | paper | https://dblp.org/rec/journals/ai/KatsunoM91.html | Revision (static world/new facts) vs update (changing world) — corrected claims vs workspace-state change. | math | u |
| F16 | A Truth Maintenance System | Doyle, AIJ 12(3) | 1979 | paper | https://dblp.org/rec/journals/ai/Doyle79.html | Justification-based beliefs with dependency-directed retraction — dependency graph for retracting claims. | math,onto | u |
| F17 | A Logic for Default Reasoning | Reiter, AIJ 13(1–2) | 1980 | paper | https://dblp.org/rec/journals/ai/Reiter80.html | Default rules with consistency prerequisites — defeasible inference beneath pre-promotion claims. | math | u |
| F18 | On the Acceptability of Arguments… | Dung, AIJ 77(2) | 1995 | paper | https://dblp.org/rec/journals/ai/Dung95.html | Abstract argumentation frameworks; grounded/preferred/stable extensions define accepted claims. | math | u |
| F19 | Argument-Based Extended Logic Programming | Prakken & Sartor, J. Logic Computation 7(1) | 1997 | paper | https://dblp.org/rec/journals/jigpal/PrakkenS97.html | Structured arguments with strict/defeasible rules and priority attacks — ASPIC+ ancestor. | math | u |
| F20 | Carneades Model of Argument and Burden of Proof | Gordon, Prakken, Walton, AIJ 171(10–15) | 2007 | paper | https://doi.org/10.1016/j.artint.2007.04.010 | Proof standards/burden of proof over argument graphs — audit-friendly promotion gate. | math,arch | u |

## Domain L — logics & verification

| ID | Title | Authors/Org | Year | Type | URL | Key claim | Informs | Conf |
|----|-------|-------------|------|------|-----|-----------|---------|------|
| L1 | Deontic Logic (SEP) | McNamara, SEP | 2006– | survey | https://plato.stanford.edu/entries/logic-deontic/ | KD operators, obligations/permissions, paradoxes overview — normative vocabulary. | math | u |
| L2 | Deontic Logic | von Wright, Mind 60(238) | 1951 | paper | https://doi.org/10.1093/mind/LX.1.4 | Founding paper; O(p)=¬P(¬p), permission/obligation duality. | math | u |
| L3 | Contrary-to-Duty Imperatives | Chisholm, Analysis 24(2) | 1963 | paper | https://doi.org/10.1093/analys/24.2.33 | CTD paradox: violated obligations spawn further obligations — trap for naive violation rules. | math | u |
| L4 | Input/Output Logics | Makinson & van der Torre, JPL 29(4) | 2000 | paper | https://doi.org/10.1023/A:1004746222424 | Norms as input→output constraints; handles CTD without explosion — candidate norm engine. | math | u |
| L5 | Agency and Deontic Logic | Horty, OUP | 2001 | book | https://global.oup.com/academic/product/agency-and-deontic-logic-9780195134613 | Stit agency + obligation: who-deliberately-ensures-what — responsibility modeling. | math | u |
| L6 | Alternating-Time Temporal Logic | Alur, Henzinger, Kupferman, JACM 49(5) | 2002 | paper | https://doi.org/10.1145/562112.562114 | Strategic ability ⟨A⟩ψ model-checked over concurrent game structures — coalition capability semantics. | math,arch | u |
| L7 | Authentication in Distributed Systems | Lampson, Abadi, Burrows, Wobber, TOCS 10(4) | 1992 | paper | https://doi.org/10.1145/138873.138874 | Speaks-for modal logic: principals, delegations, handoff certificates — delegation algebra ancestor. | math,arch | u |
| L8 | Logic in Access Control | Abadi, FMSE 2003 | 2003 | paper | https://doi.org/10.1145/986608.986614 | Survey of access-control logics (speaks-for, says) and pitfalls — map of formal authorization languages. | math | u |
| L9 | RT Framework (dup B27) | Li, Mitchell, Winsborough, IEEE S&P | 2002 | paper | https://doi.org/10.1109/SECPRI.2002.1004371 | Roles as Datalog-style predicates; linked roles bound delegation depth. | math,arch | u |
| L10 | Software Abstractions (Alloy) | Jackson, MIT Press rev. ed. | 2012 | book | https://mitpress.mit.edu/9780262527364/software-abstractions/ | Relational logic + SAT-bounded analysis of structural invariants — counterexample hunting on hub schemas. | math,arch | u |
| L11 | Specifying Systems (TLA+) | Lamport | 2002 | book | https://lamport.azurewebsites.net/tla/book.html | Temporal specification and refinement — lifecycle/state-machine rigor for grants/installs/promotions. | math,arch | u |
| L12 | Principles of Model Checking | Baier & Katoen, MIT Press | 2008 | book | https://mitpress.mit.edu/9780262026499/principles-of-model-checking/ | CTL/LTL model checking algorithms and complexity — primer for verifying authorize() protocols. | math | u |
| L13 | Cedar language papers (dup C8/C10) | AWS Cedar team | 2023–24 | paper/docs | https://docs.cedarpolicy.com/ | Decidable core without negative permissions, machine-checked proofs — verified production authz existence proof. | arch | u |
| L14 | Datalog and Recursive Query Processing | Green, Huang, Loo, Zhou, FTDB 5(2) | 2013 | survey | https://doi.org/10.1561/1900000017 | Datalog semantics/complexity/applications incl. security policies — substrate for policy services. | math,arch | u |
| L15 | Foundations of Databases ("Alice") | Abiteboul, Hull, Vianu | 1995 | book | http://webdam.inria.fr/Alice/ | Canonical datalog/conjunctive-query theory, stratified negation, complexity — decidability toolkit. | math | u |
| L16 | Zanzibar (dup C5) | Pang et al., USENIX ATC | 2019 | paper | https://www.usenix.org/conference/atc19/presentation/pang | Production ReBAC tuples + watch configs for consistent external authorization. | arch | u |
| L17 | Relationship-Based Access Control (Fong) | Fong, SACMAT | 2009 | paper | https://doi.org/10.1145/1542207.1542220 | Path-type analysis of relationship chains; composition operators — formal core for graph-reachability authz. | math,arch | u |
| L18 | NIST SP 800-162 ABAC guide (dup C3) | Hu, Ferraiolo, Kuhn et al., NIST | 2014 | spec | https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-162.pdf | Attribute half of relationships+attributes+context model. | arch | u |
| L19 | Raft TLA+ Specification | Ongaro (ongardie/raft.tla) | 2014– | spec | https://github.com/ongardie/raft.tla | Real consensus system specified and model-checked in TLA+ — precedent for hub lifecycle verification. | arch | u |

## Insights (collector)
- Ontology backbone: RDF(S)/OWL 2 RL-or-EL profile for entity taxonomy; SKOS to align vocabularies; JSON-LD 1.1 wire format.
- Provenance structural: promoted KnowledgeAssertion = PROV entity ← promotion Activity used evidence entities, attributed via actedOnBehalfOf; closed SHACL shapes enforce completeness; PROV-Dictionary covers workspace evolution.
- FHMPV Kripke semantics for what installations know; DEL action models for message-driven change; AGM revision ≠ KM update — conflating them is a classic bug.
- Promotion gates as argumentation: Dung minimal; ASPIC+/Prakken–Sartor adds priorities; Carneades adds proof standards auditors understand.
- authorize()/delegation backbone: stratified positive Datalog (RT-style atoms, Zanzibar-style expansion): polynomial data complexity, monotone, composable; RT linked roles cap chain depth. Avoid nonmonotonic/full-FOL policy languages at runtime.
- Verification plan: Alloy bounded checks at design time; TLA+/PlusCal for concurrent lifecycles (raft.tla precedent); Cedar playbook — tiny kernel machine-checked once.
- CTD risk: prefer Input/Output logic for normative relations (decidable, no explosion).
- Negative permissions risk: deny-rules break monotonicity (Cedar omits them); stance = positive grants + precedence-ranked exception channel with SHACL severities; STIT/ATL reserved for offline analysis only.

## Verification verdicts (V1, subagent 64c8b59c, раунд 8)

| ID | Verdict | Финальный URL / правка | Примечание |
|---|---|---|---|
| F12 | v | https://doi.org/10.1007/978-1-4020-5839-4 | Springer; ISBN подтверждён в каталогах |
| F14 | c | https://doi.org/10.2307/2274239 | **исправлен DOI AGM**: 2274239 (две независимые записи SLUB), был 2273922 |
| F20 | v | https://doi.org/10.1016/j.artint.2007.04.010 | ScienceDirect S0004370207000677 + PhilPapers |
| L2 | v | https://doi.org/10.1093/mind/LX.1.4 | Mind LX(237), янв. 1951; страница выпуска OUP |
| L3 | v | https://doi.org/10.1093/analys/24.2.33 | запись PhilArchive CHICIA-2 |
| L4 | v | https://doi.org/10.1023/A:1004746222424 | собственная библиография van der Torre |
| L6 | c | https://dl.acm.org/doi/10.1145/585265.585270 | **исправлен DOI ATL**: каноничная запись ACM DL JACM, был 562112.562114 |
| L7 | v | https://doi.org/10.1145/138873.138874 | официальная страница абстракта Lampson |
| L8 | v | https://doi.org/10.1145/986608.986614 | IEEE Xplore 1210062 «Logic in access control» |
| L14 | v | https://doi.org/10.1561/1900000017 | FnT Databases монография; Emerald abstract |
| L17 | x | — | SACMAT'09 не surfaced (только варианты 2011 «policy language»); статья реальна, проверить вручную на ACM DL |

Не покрыто V1 (остаются u): F1–F11, F13, F15–F19, L1, L5, L10–L12, L15, L18, L19.
