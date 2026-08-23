# Sources B (identity & delegation) + C (authorization)

Provenance: subagent 1ddc6e78-fede-42d5-8b1b-d1d4922a6d40, collected offline.
ALL rows Conf=u (no web_search key; egress blocked). Verify-first flags: B18 biscuitsec path, B21 spiffe.io docs path,
C2 ANSI store slug, C6 SpiceDB docs path, C9 Amazon Science slug, C15 OpenFGA docs path; IEEE/ACM records B25–B27, C4 correct DOIs but publisher-gated.

## Domain B — identity & delegation

| ID | Title | Org/Authors | Year | Type | URL | Key claim | Informs | Conf |
|----|-------|-------------|------|------|-----|-----------|---------|------|
| B1 | Best Current Practice for OAuth 2.0 Security (BCP 240) | IETF | 2025 | rfc | https://www.rfc-editor.org/rfc/rfc9700 | Exact redirect matching, sender-constrained tokens, PKCE, no implicit flow. | feat | u |
| B2 | The OAuth 2.0 Authorization Framework | IETF | 2012 | rfc | https://www.rfc-editor.org/rfc/rfc6749 | Resource owner grants client scoped, revocable access without sharing credentials. | arch | u |
| B3 | OpenID Connect Core 1.0 | OpenID Foundation | 2014 | spec | https://openid.net/specs/openid-connect-core-1_0.html | Identity layer on OAuth: authenticated human subject + id_token claims. | arch | u |
| B4 | OAuth 2.0 Token Exchange | IETF | 2020 | rfc | https://www.rfc-editor.org/rfc/rfc8693 | Distinguishes act-as (delegation) from impersonation; derived narrowed tokens with actor chains. | arch | u |
| B5 | OAuth 2.0 Rich Authorization Requests | IETF | 2023 | rfc | https://www.rfc-editor.org/rfc/rfc9396 | authorization_details JSON encodes fine-grained permissions inside the grant itself. | feat | u |
| B6 | OAuth 2.0 DPoP | IETF | 2023 | rfc | https://www.rfc-editor.org/rfc/rfc9449 | Tokens bound to agent keypairs via per-request JWT proofs; sender-constrained, replay-resistant. | feat | u |
| B7 | OAuth 2.0 Mutual-TLS Client Auth and Certificate-Bound Tokens | IETF | 2020 | rfc | https://www.rfc-editor.org/rfc/rfc8705 | Transport-layer token binding via TLS client certs for service-to-service auth. | feat | u |
| B8 | JWT Profile for OAuth 2.0 Access Tokens | IETF | 2021 | rfc | https://www.rfc-editor.org/rfc/rfc9068 | Standard auditable JWT access tokens enabling offline verification. | feat | u |
| B9 | OAuth 2.0 Device Authorization Grant | IETF | 2019 | rfc | https://www.rfc-editor.org/rfc/rfc8628 | Input-limited agents obtain user consent cross-device without embedded credentials. | feat | u |
| B10 | GNAP | IETF | 2024 | rfc | https://www.rfc-editor.org/rfc/rfc9635 | Next-gen delegation protocol negotiating instance-level, key-bound grants with continuous user interaction. | arch | u |
| B11 | OAuth 2.0 Protected Resource Metadata | IETF | 2025 | rfc | https://www.rfc-editor.org/rfc/rfc9728 | Machine-readable discovery of resource-server requirements: scopes, issuers, sender-constraining. | feat | u |
| B12 | OAuth 2.0 Token Revocation | IETF | 2012 | rfc | https://www.rfc-editor.org/rfc/rfc7009 | Explicit endpoint invalidates tokens, bounding delegated authority lifetime. | feat | u |
| B13 | OAuth 2.0 Token Introspection | IETF | 2015 | rfc | https://www.rfc-editor.org/rfc/rfc7662 | Live token state query enabling near-real-time revocation enforcement. | feat | u |
| B14 | Verifiable Credentials Data Model v2.0 | W3C | 2025 | spec | https://www.w3.org/TR/vc-data-model-2.0/ | Cryptographically verifiable holder-mediated attestations for cross-domain credential presentation. | arch | u |
| B15 | Decentralized Identifiers (DIDs) v1.0 | W3C | 2022 | spec | https://www.w3.org/TR/did-core/ | Resolvable decentralized identifiers with verification methods independent of central IdP. | arch | u |
| B16 | Bitstring Status List v1.0 | W3C | 2025 | spec | https://www.w3.org/TR/vc-bitstring-status-list/ | Compact privacy-preserving revocation/suspension mechanism for VCs. | feat | u |
| B17 | Macaroons | Birgisson et al. — USENIX NSDI | 2014 | paper | https://www.usenix.org/system/files/conference/nsdi14/nsdi14-paper-birgisson.pdf | Bearer tokens attenuated by verifiable caveats forming delegable attenuation chains. | arch | u |
| B18 | Biscuit Token Specification | Clever Cloud / biscuitsec.org | 2020 | spec | https://www.biscuitsec.org/docs/specification/ | Offline attenuable bearer tokens with Datalog caveats; delegation only narrows rights. | arch | u |
| B19 | SPIFFE Identity Specification | CNCF SPIFFE | 2021 | spec | https://github.com/spiffe/spiffe/blob/main/standards/SPIFFE-ID.md | Stable URI workload identity naming non-human runtimes independent of infrastructure. | arch | u |
| B20 | SPIFFE Workload API Specification | CNCF SPIFFE | 2022 | spec | https://github.com/spiffe/spiffe/blob/main/standards/workload-api.md | Short-lived SVID X.509/JWT identities with automatic rotation. | feat | u |
| B21 | SPIRE Documentation | CNCF SPIFFE | 2024 | docs | https://spiffe.io/docs/latest/ | Reference implementation issuing/rotating SVIDs via attestation; model for runtime identity registry. | feat | u |
| B22 | Bound Service Account Tokens (Kubernetes) | Kubernetes (CNCF) | 2021 | docs | https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/ | Audience-, expiry-, pod-bound JWTs replaced eternal secrets. | feat | u |
| B23 | AWS IAM Roles Anywhere User Guide | AWS | 2022 | docs | https://docs.aws.amazon.com/rolesanywhere/latest/userguide/introduction.html | External X.509 workloads exchange certs into scoped STS credentials. | feat | u |
| B24 | Kerberos Constrained Delegation Overview (S4U) | Microsoft | 2016 | docs | https://learn.microsoft.com/en-us/windows-server/security/kerberos/kerberos-constrained-delegation-overview | Historic contrast: S4U proxying restricted to whitelisted services; unconstrained-delegation risk. | arch | u |
| B25 | Decentralized Trust Management | Blaze, Feigenbaum, Lacy — IEEE S&P | 1996 | paper | https://ieeexplore.ieee.org/document/502676 | PolicyMaker founded trust management: signed assertions + policy logic without central ACLs. | math | u |
| B26 | Delegation Logic (D1LP) | Li, Grosof, Feigenbaum — ACM TISSEC 6(1) | 2003 | paper | https://dl.acm.org/doi/10.1145/605420.605424 | Monotonic logic of delegation depth with grant/revoke semantics. | math | u |
| B27 | RT Role-Based Trust-Management Framework | Li, Mitchell, Winsborough — IEEE S&P | 2002 | paper | https://ieeexplore.ieee.org/document/1004362 | Role-based credential chains with delegation across trust domains. | math | u |
| B28 | Proof-Carrying Authentication | Appel & Felten — ACM CCS | 1999 | paper | https://www.cs.princeton.edu/~appel/papers/pca.pdf | Clients carry machine-checkable authorization proofs; cheap verification decoupled from proof search. | math | u |
| B29 | Capability Myths Demolished | Miller, Yee, Shapiro — JHU SRL TR 2003-02 | 2003 | paper | https://srl.cs.jhu.edu/pubs/SRL2003-02.pdf | Unforgeable, attenuable, delegable capabilities outperform ACLs on confinement; POLA rules. | math | u |

## Domain C — authorization

| ID | Title | Org/Authors | Year | Type | URL | Key claim | Informs | Conf |
|----|-------|-------------|------|------|-----|-----------|---------|------|
| C1 | RBAC96 Models | Sandhu, Coyne, Feinstein, Youman — IEEE Computer | 1996 | paper | https://www.profsandhu.com/cscc537/sandhu_comp96.pdf | Canonical RBAC0–3; fine-grained per-agent delegation causes role explosion. | math | u |
| C2 | ANSI INCITS 359-2012 RBAC Standard | INCITS/NIST | 2012 | spec | https://webstore.ansi.org/standards/incits/ansincits3592012 | Core/hierarchical/administrative RBAC vocabulary. | math | u |
| C3 | Guide to ABAC (NIST SP 800-162) | Hu, Ferraiolo, Kuhn et al. | 2014 | docs | https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-162.pdf | Subject/resource/action/environment attributes; deny-by-default composition. | arch | u |
| C4 | UCON_ABC Usage Control Model | Park & Sandhu — ACM TISSEC 7(1) | 2004 | paper | https://dl.acm.org/doi/10.1145/984334.984339 | Mutable attributes and ongoing decisions during use — fits long-running agent tasks. | math | u |
| C5 | Zanzibar | Pang et al. — USENIX ATC | 2019 | paper | https://www.usenix.org/conference/atc19/presentation/pang | ReBAC relation tuples, recursive graph evaluation, zigzag snapshot consistency, exclusion tuples. | arch | u |
| C6 | SpiceDB Consistency Concepts | Authzed | 2024 | docs | https://authzed.com/docs/spicedb/concepts/consistency | minimizeLatency/bounded-staleness/fullyConsistent check modes — quantifies staleness/revocation latency. | arch | u |
| C7 | OpenFGA Documentation | OpenFGA (CNCF) | 2024 | docs | https://openfga.dev/docs | Open-source Zanzibar-style FGA: modeling language, consistency options, graph checks. | arch | u |
| C8 | Cedar (PLDI 2024) | Eline et al. (AWS/UCSD) | 2024 | paper | https://cedar-pldi.github.io/ | Decidable, sound, complete policy evaluation with polynomial-time checking. | math | u |
| C9 | Verified: Cedar (SOSP 2023) | Nelson et al. (AWS) | 2023 | paper | https://www.amazon.science/publications/verified-cedar-memory-safety-for-a-cloud-scale-authorization-engine | Dafny-verified engine: parser/evaluator memory- and panic-safe. | math | u |
| C10 | Cedar Policy Language Documentation | AWS | 2024 | docs | https://docs.cedarpolicy.com/ | Attribute/context-conditioned permit/forbid; deny-by-default; deliberately no role hierarchy. | arch | u |
| C11 | Rego Policy Language Docs | Styra / OPA | 2024 | docs | https://www.openpolicyagent.org/docs/policy-language | Datalog-derived context-rich policy language for general-purpose PDP. | arch | u |
| C12 | XACML 3.0 Core Specification | OASIS | 2013 | spec | https://docs.oasis-open.org/xacml/3.0/xacml-3.0-core-spec-os-en.html | Canonical PDP/PEP/PIP architecture, combining algorithms, obligations. | arch | u |
| C13 | Zero Trust Architecture (NIST SP 800-207) | Rose et al. | 2020 | docs | https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-207.pdf | PDP/PEP separation; policy engine + administrator as control plane. | arch | u |
| C14 | PostgreSQL Row Security Policies | PostgreSQL GDG | 2024 | docs | https://www.postgresql.org/docs/current/ddl-rowsecurity.html | CREATE POLICY row filters as in-database defense-in-depth beneath application PDP. | feat | u |
| C15 | Modeling Exclusions (negative relations) | OpenFGA (CNCF) | 2024 | docs | https://openfga.dev/docs/modeling/exclusions | Exclusion relations express negative permissions; graph-evaluation complexity pitfalls. | arch | u |

## Insights (collector)
- DelegationGrant ≈ RFC 8693 token exchange (subject+actor chain) + RFC 9396 authorization_details payload + DPoP/mTLS cnf binding: {owner_id, actor_id, details, aud, exp, jti, cnf}.
- Attenuation must be monotonic-only (macaroons/biscuit caveats conjoin; D1LP/RT chains monotone); POLA argument = B29.
- Short TTL beats clever revocation: SPIFFE/K8s bound tokens pattern + RFC 7009/7662 registry revocation at PEP.
- Formal choice: Zanzibar-style ReBAC tuples + Cedar-style decidable core with forbid; avoid role explosion (C1).
- Negative permissions are the weak spot: prefer stored-allow + deny-by-default composition over materialized denies.
- Consistency: zigzag ordering gives snapshot reads; bounded staleness + short max-token-TTL bounds stale-grant exposure.
- VC 2.0/PCA enable machine-checkable off-platform authority; DID/SPIFFE supply stable non-human identifiers.
- Layering: PDP/PEP at API edge + Postgres RLS second gate + deterministic IAM issuing/introspecting grants.

## Verification verdicts (V2, subagent 77b31b8f, раунд 7; 18/36 проверенных строк)

| ID | Verdict | Финальный URL / правка | Примечание |
|---|---|---|---|
| B10 | c | https://www.rfc-editor.org/info/rfc9635/ | GNAP; видна форма `/info/` |
| B11 | v | https://www.rfc-editor.org/rfc/rfc9728 | вариант `.html`, та же запись |
| B16 | v | https://www.w3.org/TR/vc-bitstring-status-list/ | точно, Rec v1.0 |
| B17 | c | https://research.google/pubs/macaroons-cookies-with-contextual-caveats-for-decentralized-authorization-in-the-cloud/ | запись Google Research; usenix PDF-путь не индексируется |
| B18 | c | https://doc.biscuitsec.org/usage/swift | docs переехали на doc.biscuitsec.org |
| B21 | v | https://spiffe.io/docs/latest/ | docs живы |
| B22 | v | https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/ | исходник страницы в kubernetes/website |
| B26 | c | https://dl.acm.org/doi/10.1145/605434.605438 | **исправлен DOI** (был 10.1145/605420.605424 — неверный) |
| B27 | c | http://theory.stanford.edu/~ninghui/abstracts/rt_oakland02.html | Oakland'02 подтверждён; IEEE 1004362 не проверен |
| B28 | c | https://collaborate.princeton.edu/en/publications/proof-carrying-authentication/ | запись Princeton-портала; путь pca.pdf не индексируется |
| B29 | c | https://papers.agoric.com/papers/capability-myths-demolished/full-text/ | полный текст на Agoric; JHU SRL pdf не индексируется |
| C1 | x | — | sandhu_comp96 PDF не индексируется (×3 попытки); profsandhu.com жив — проверить вручную |
| C2 | c | https://webstore.ansi.org/standards/incits/incits3592012 | slug без `ans`; есть R2022 reaffirm |
| C4 | c | https://www.mendeley.com/catalogue/627e6bc7-486b-36f8-b90f-f1d708b6b93a/ | UCON подтверждён (TISSEC 7(1)); ACM DOI не проверен ×3 |
| C6 | v | https://authzed.com/docs/spicedb/concepts/consistency | точно |
| C8 | x | — | cedar-pldi.github.io не surfaced ×3; есть sigplan/cedar-policy — проверить вручную |
| C9 | x | — | amazon.science жив, страница verified-cedar не индексируется ×5 — проверить вручную |
| C15 | c | https://openfga.dev/docs/modeling/blocklists | гайд exclusions заменён Blocklists |

Не покрыто V2 (остаются u): B1–B9, B12–B15, B19, B20, B23–B25, C3, C5, C7, C10–C14.
Примечание: B26 DOI-исправление обязательно учесть в реестре; C1/C8/C9 — unverified, не удалять без ручной проверки.
