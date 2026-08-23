# Sources G (privacy/E2EE/local-first/confidential) + H (distributed foundations)

Provenance: subagent 967797b0-1a94-4ba2-b97e-e8885db0338b (final tables from its closing message).
Its own web_search calls failed ("Insufficient Balance") mid-run; port-80 host liveness observed only.
ALL rows Conf=u unless noted in «Верификация родителем» below. Exclusions honored (Ink&Switch dup omitted;
Matrix Olm/Megolm instead of seed module page; Temporal deep page instead of main docs).

## Domain G — privacy / E2EE / local-first / confidential computing

| ID | Title | Authors/Org | Year | Type | URL | Key claim | Informs | Conf |
|----|-------|-------------|------|------|-----|-----------|---------|------|
| G1 | The Double Ratchet Algorithm | Marlinspike, Perrin (Signal) | 2016 | spec | https://signal.org/docs/specifications/doubleratchet/ | Per-message forward-secure ratchet; compromise exposes neither past nor future messages. | feat | u |
| G2 | The X3DH Key Agreement Protocol | Marlinspike, Perrin (Signal) | 2016 | spec | https://signal.org/docs/specifications/x3dh/ | Asynchronous prekey handshake; offline peers establish deniable sessions. | feat | u |
| G3 | Messaging Layer Security Protocol (RFC 9420) | Barnes et al. (IETF MLS WG) | 2023 | rfc | https://www.rfc-editor.org/info/rfc9420 | TreeKEM group keys ~O(log n) per member change — scalable E2EE rooms beyond pairwise ratchets. | arch | v (parent) |
| G3b | MLS Architecture (RFC 9750) | IETF MLS WG | 2025 | rfc | https://datatracker.ietf.org/doc/rfc9750/ | Companion architecture document for MLS deployments (found April 2025 publication during verification). | arch | v (parent) |
| G4 | MIMI protocol using MLS (draft) | IETF MIMI WG | 2023–25 | draft | https://datatracker.ietf.org/doc/draft-ietf-mimi-protocol/ | MLS applied to interactive messaging with room semantics — blueprint incl. agent participants. | feat | u |
| G5 | Olm/Megolm specs (+vodozemac) | Matrix.org Foundation | 2016–24 | spec | https://gitlab.matrix.org/matrix-org/olm/-/blob/master/docs/megolm.md | Olm pairwise + Megolm sender ratchet for rooms; audited Rust impl; server never sees plaintext. | feat | u |
| G6 | Cwtch metadata-resistant messaging | S.J. Lewis / Open Privacy | 2018–23 | paper+docs | https://docs.cwtch.im/ | Servers relay opaque blobs; social graph hidden even from operators. | feat | u |
| G7 | Intel TDX / SGX overview | Intel | 2023–24 | docs | https://www.intel.com/content/www/us/en/developer/tools/trust-domain-extensions-overview.html | VM/enclave TEE with remote attestation — admin-blind indexing option. | arch | u |
| G8 | SEV-SNP strengthening island integrity (whitepaper) | AMD | 2020–21 | whitepaper | https://www.amd.com/system/files/TechDocs/SEV-SNP-strengthening-island-integrity-whitepaper.pdf | Memory integrity protection + firmware-signed attestation excludes cloud operator from guest state. | arch | u |
| G9 | AWS Nitro Enclaves User Guide | AWS | 2020–24 | docs | https://docs.aws.amazon.com/enclaves/latest/user/nitro-enclave.html | Operator-less enclave compute; KMS attestation-scoped decryption for sensitive processing. | feat | u |
| G10 | RATS Architecture (RFC 9334) | Birkholz et al. (IETF) | 2023 | rfc | https://www.rfc-editor.org/info/rfc9334 | Attester/Verifier/Relying-Party roles + Evidence vocabulary for runtime integrity claims. | arch | u |
| G11 | Entity Attestation Token (EAT, RFC 9711) | Lundblade et al. (IETF) | 2025 | rfc | https://www.rfc-editor.org/info/rfc9711 | Compact signed attestation token consumable by authorization decisions. | feat | u |
| G12 | Confidential AI inferencing (Azure engineering) | Microsoft | 2024 | blog/paper | https://techcommunity.microsoft.com/category/azure/azure-confidential-computing | Prompt/response processing inside attested enclaves; keys released only to measured code. | arch | u |
| G13 | A Pragmatic Introduction to Secure MPC (background) | Evans, Kolesnikov, Rosulek | 2018 | survey/book | https://www.securecomputation.org/ | Frames feasibility/costs of computing on encrypted data without hardware trust. | math | u |
| G14 | Automerge documentation | Automerge team (Ink&Switch lineage) | 2017–25 | docs | https://automerge.org/ | Mature CRDT library merging JSON-like docs peer-to-peer without central authority. | feat | u |
| G15 | Conflict-Free Replicated JSON Datatype | Kleppmann, Beresford (IEEE TPDS) | 2017 | paper | https://arxiv.org/abs/1608.05371 | Formal JSON-tree CRDT with convergence proofs — replication base for sovereign nodes. | arch | u |
| G16 | Introduction to Petname Systems | Stiegler; Spritely/Miller lineage | 2005 | essay | http://www.skyhunter.com/marcs/petnames/IntroPetNames.html | Local human names bound to keys via introduction — naming without CA/global registry. | mental | u |
| G17 | Solid Technical Reports (Solid-OIDP, WAC/ACP) | W3C Solid CG | 2020–25 | spec | https://solidproject.org/TR/ | Personal pods with WebID identity and delegated app access — prior art for profile B vaults. | arch | u |
| G18 | IPFS content addressing concepts | Protocol Labs | 2015–24 | docs | https://docs.ipfs.tech/concepts/content-addressing/ | CID-addressed immutable blocks with dedup — verifiable artifact exchange between nodes. | feat | u |

## Domain H — distributed foundations

| ID | Title | Authors/Org | Year | Type | URL | Key claim | Informs | Conf |
|----|-------|-------------|------|------|-----|-----------|---------|------|
| H1 | Raft consensus | Ongaro & Ousterhout (USENIX ATC'14) | 2014 | paper | https://www.usenix.org/conference/atc14/technical-sessions/presentation/ongaro | Understandable replicated log incl. membership changes — HA upgrade path past one node. | arch | u |
| H2 | PACELC | Abadi (IEEE Computer) | 2012 | paper | https://doi.org/10.1109/MC.2012.33 | Latency-vs-consistency trade even without partitions — justifies single-node ACID default. | math | u |
| H3 | Event Sourcing | Fowler | 2005 | pattern | https://martinfowler.com/eaaDev/EventSourcing.html | Facts as source of truth; state by replay — audit-native storage. | arch | u |
| H4 | Transactional Outbox | Richardson (microservices.io) | 2018–24 | pattern | https://microservices.io/patterns/data/transactional-outbox.html | Entity change + event committed atomically; relay publishes later. | arch | u |
| H5 | Saga pattern | Richardson (microservices.io) | 2018–24 | pattern | https://microservices.io/patterns/data/saga.html | Long workflows as local transactions with compensations — no distributed locks. | arch | u |
| H6 | Idempotency Keys | Stripe | 2017 | blog/API docs | https://stripe.com/blog/idempotency (+ https://docs.stripe.com/api/idempotent_requests) | Client-supplied keys deduplicate retried effectful writes. | feat | u |
| H7 | Kafka delivery semantics | Apache | 2011–24 | docs | https://kafka.apache.org/documentation/#semantics | At-least-once + idempotent producers; end-to-end exactly-once = consumer-side dedup. | math | u |
| H8 | Temporal durable execution (durability page) | Temporal Technologies | 2021–24 | docs | https://docs.temporal.io/evaluate/durability | State persisted as append-only event history; deterministic crash-resume replays. | arch | u |
| H9 | Durable Functions checkpointing/replay | Microsoft Learn | 2019–24 | docs | https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-checkpointing | Orchestrator deterministically replays from checkpoints; activities at-least-once. | feat | u |
| H10 | OTP Design Principles (supervision trees) | Ericsson | 1996–24 | docs | https://www.erlang.org/doc/system/design_principles.html | Supervision hierarchies restart failed children in isolation; let-it-crash containment. | arch | u |
| H11 | Universal Modular ACTOR Formalism | Hewitt, Bishop, Steger (IJCAI'73) | 1973 | paper | https://www.ijcai.org/Proceedings/73/Papers/027B.pdf | Encapsulated actors + async messages, no shared state — concurrency foundation. | math | u |
| H12 | Orleans virtual actors MSR-TR-2014-41 | Bernstein et al. (MSR) | 2014 | techreport | https://www.microsoft.com/en-us/research/publication/orleans-distributed-virtual-actors-for-programmability-and-scalability/ | Always-available grains activated on demand, transparent persistence — one-node-to-many model. | arch | u |
| H13 | Litestream how-it-works | B. Johnson | 2021–24 | docs | https://litestream.io/how-it-works/ | Continuous WAL shipping to object storage; near-instant whole-DB restore for small nodes. | feat | u |
| H14 | PostgreSQL continuous archiving / PITR | PostgreSQL GDG | 1996–25 | docs | https://www.postgresql.org/docs/current/continuous-archiving.html | WAL archive enables point-in-time restore — recovery contract mechanics. | feat | u |
| H15 | CRDTs (SSS'11 / INRIA RR-7687) | Shapiro et al. | 2011 | paper/TR | https://inria.hal.science/inria-00555588 | Coordination-free convergence under eventual consistency — future profile-B sync formal base. | math | u |
| H16 | Time, Clocks, and Ordering of Events | Lamport (CACM 21(7)) | 1978 | paper | https://doi.org/10.1145/359563.359569 | Happened-before logical ordering — causal order for event logs/messages. | math | u |
| H17 | FoundationDB SIGMOD'21 | Zhou et al. (Apple) | 2021 | paper | https://doi.org/10.1145/3448016.3452805 (см. также dl.acm.org/doi/10.1145/3448016.3452831) | Deterministic simulation testing under fault injection found most bugs pre-production. | math,arch | u |

## Верификация родителем (обновляется)

- Раунд 4: G3 RFC 9420 подтверждён поиском ([inline-errata страница](https://www.rfc-editor.org/rfc/inline-errata/rfc9420.html));
  обнаружен и добавлен G3b RFC 9750 (MLS Architecture, апрель 2025).

## Insights (коллектор)

- Профиль C не может обещать серверную индексацию/поиск: шифрованные комнаты оставляют серверу только ciphertext + метаданные; честное решение H12 — локальные индексы участников или TEE-обработка.
- Профиль B обещает суверенитет контента, но не анонимность: control-plane видит identity/ACL/routing/timing без Cwtch-минимизации метаданных.
- TEE — третий путь для platform agents: attested enclaves (RATS/EAT) дают «admin-blind, attestation-verifiable», оплаченное TCB и ops-нагрузкой.
- Single-node envelope защитим: PACELC за ACID по умолчанию; Raft откладывается на неопределённый срок при 15–20 пользователях; WAL/PITR/Litestream дают RPO ≈ минуты.
- Exactly-once — контракт API (outbox+saga+idempotency keys), не свойство транспорта.
- Триггеры миграции к B: ёмкость, мультирегион, резидентность, RPO/RTO SLA, потеря доверия оператору, требование E2EE комнат; event sourcing + Lamport clocks делают подъём аддитивным.
- Детерминизм с первого дня: Lamport ordering в событиях + FoundationDB-style deterministic simulation как метод верификации ядра.
