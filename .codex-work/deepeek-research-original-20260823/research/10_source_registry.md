# 10 — Мастер-реестр источников

Статус: v1 (раунд 8). Решение по нумерации: **перенумерация в S### отменена** — сохранены
стабильные доменные ID (A…M), синтез-документы остаются валидными без правок. Новые серии:
**Z#** — источники базового концепта, не покрытые доменными каталогами; **SV#** —
межпротокольные обзоры (раунд 3).

## 1. Учёт и политика дедупликации

| Метрика | Значение |
|---|---|
| Сырых строк доменных каталогов | 235 |
| Снято внутренних дублей | 6 (см. карту ниже) |
| Исключено (неверный идентификатор) | 1 — I4 (arXiv 2406.06852 доказуемо другой обзор) |
| Валидных уникальных из каталогов | 228 |
| Серия Z (seed-only) | 15 |
| Серия SV (обзоры) | 3 |
| **Всего позиций в реестре** | **246** уникальных (252 строки таблицы: 6 — указатели дубликатов; 245 валидных после исключения I4) |
| **Ядро цитирования модельных артефактов (★)** | **118** — внутри целевого диапазона 100–200 |

Правила: (а) одинаковая работа под разными URL → один вход, алиас в карте дедупликации;
(б) разные документы одного семейства (OWASP Top-10-Agentic vs Threats-and-Mitigations;
Temporal main docs vs durability page) → отдельные входы; (в) `x` = «не подтвердилось
поиском», не «мёртвая ссылка»: строки с пометкой «ручная проверка» не удаляются.

## 2. Карта дедупликации (дубль → канонический вход)

| Дубль | Канон | Основание |
|---|---|---|
| A12 | B15 | W3C DID Core v1.0 |
| A15 | E17 | Anthropic Building Effective Agents |
| L9 | B27 | RT framework IEEE S&P 2002 |
| L16 | C5 | Zanzibar USENIX ATC'19 |
| L13 | C8+C10 | Cedar PLDI-пейпер + docs (сборный дубль) |
| L18 | C3 | NIST SP 800-162 |
| seed1/2/4/5/7/8/11/12/14/16/30/32/33 | B17/B6/B4/B5/B7/C13/C5/C14/B14/A1/I9/F8/F4 | повторное использование стандартов базового отчёта |
| seed13 | G17 | Solid Protocol → solidproject.org/TR |
| seed21 | E5 | LangGraph docs (index.html = /) |
| seed31 | H8 | Temporal durability page |

## 3. Статусы верификации (V1+V2+родитель)

| Статус | Значение | Кол-во |
|---|---|---|
| v | URL подтверждён поиском как есть | 45 |
| c | подтверждён с канонической правкой URL/DOI | 19 |
| x | не подтвердился ×неск. попыток — ручная проверка | 6 (C1,C8,C9,D12,L17,J4) |
| x-исключён | неверный идентификатор | 1 (I4) |
| u | вне объёма верификации | 175 |

Ключевые исправления: DOI AGM → 10.2307/2274239 (F14); DOI ATL → 10.1145/585265.585270 (L6);
DOI Delegation Logic → 10.1145/605434.605438 (B26); K5 → arXiv 2204.06916 (Schemmer,
reliance-исследование, НЕ мета-анализ); E16 без `built-`; M6 → code.claude.com/docs/;
MCP актуальная ревизия 2026-07-28 (A4).

## 4. Домен A — протоколы (13 валидных)

| ID | Источник | Вер. | Ядро | Правка/примечание |
|---|---|---|---|---|
| A1 | A2A Specification | c | ★ | канонично /latest/specification/ |
| A2 | A2A reference impl (GitHub) | v | | |
| A3 | A2A → Linux Foundation (blog) | u | | |
| A4 | MCP specification | c | ★ | rev 2026-07-28 |
| A5 | MCP Authorization | c | ★ | офиц. ревизия 2025-06-18 подтверждена |
| A6 | MCP Tasks 2025-11-25 | v | ★ | |
| A7 | Official MCP Registry | v | ★ | |
| A8 | IBM ACP docs | v | ★ | |
| A9 | ANP (GitHub) | v | | |
| A10 | Agora (arXiv 2410.11905) | v | | |
| A11 | Eclipse LMOS | v | ★ | |
| A13 | AGNTCY | v | ★ | |
| A14 | kagent | v | ★ | |

## 5. Домен M — prior art (18)

| ID | Источник | Вер. | Ядро | Правка/примечание |
|---|---|---|---|---|
| M1 | ChatGPT Agent | u | | |
| M2 | Gemini Enterprise docs | v | ★ | |
| M3 | Copilot Studio | u | | |
| M4 | M365 Agents SDK | u | | |
| M5 | Entra Agent ID | v | ★ | |
| M6 | Claude Code docs | c | ★ | миграция на code.claude.com/docs/ |
| M7 | Bedrock Agents | u | ★ | |
| M8 | Bedrock AgentCore | c | | devguide URL |
| M9 | Agentforce | u | | |
| M10 | ServiceNow AI agents | u | ★ | |
| M11 | LibreChat | u | | |
| M12 | Dify | u | | |
| M13 | n8n | u | ★ | |
| M14 | Open WebUI | u | | |
| M15 | AutoGen Studio | u | | |
| M16 | CrewAI AMP | u | | |
| M17 | Invariant: MCP security notification | v | ★ | |
| M18 | Invariant: mcp-scan | v | ★ | |

## 6. Домен B — identity/delegation (29)

| ID | Источник | Вер. | Ядро | Правка/примечание |
|---|---|---|---|---|
| B1 | RFC 9700 OAuth BCP | u | | |
| B2 | RFC 6749 | u | | |
| B3 | OIDC Core 1.0 | u | ★ | |
| B4 | RFC 8693 Token Exchange | u | ★ | |
| B5 | RFC 9396 RAR | u | ★ | |
| B6 | RFC 9449 DPoP | u | ★ | |
| B7 | RFC 8705 mTLS bound tokens | u | ★ | |
| B8 | RFC 9068 JWT access tokens | u | | |
| B9 | RFC 8628 Device grant | u | | |
| B10 | RFC 9635 GNAP | c | | форма /info/ |
| B11 | RFC 9728 PRM | v | ★ | |
| B12 | RFC 7009 Revocation | u | ★ | |
| B13 | RFC 7662 Introspection | u | ★ | |
| B14 | W3C VC 2.0 | u | ★ | |
| B15 | W3C DID Core (алиас A12) | u | | |
| B16 | Bitstring Status List | v | | Rec v1.0 |
| B17 | Macaroons NSDI'14 | c | ★ | запись Google Research |
| B18 | Biscuit spec | c | ★ | doc.biscuitsec.org |
| B19 | SPIFFE ID spec | u | ★ | |
| B20 | SPIFFE Workload API | u | ★ | |
| B21 | SPIRE docs | v | | |
| B22 | K8s bound service tokens | v | ★ | |
| B23 | AWS IAM Roles Anywhere | u | | |
| B24 | Kerberos constrained delegation | u | | |
| B25 | PolicyMaker S&P'96 | u | | |
| B26 | Delegation Logic TISSEC | c | ★ | **DOI → 10.1145/605434.605438** |
| B27 | RT framework S&P'02 (алиас L9) | c | ★ | Oakland'02 подтверждена |
| B28 | Proof-Carrying Authentication | c | | Princeton portal record |
| B29 | Capability Myths Demolished | c | ★ | полный текст на papers.agoric.com |

## 7. Домен C — авторизация (15)

| ID | Источник | Вер. | Ядро | Правка/примечание |
|---|---|---|---|---|
| C1 | RBAC96 Sandhu et al. | x | ★ | PDF не индексируется ×3 — ручная проверка; статья каноническая |
| C2 | ANSI INCITS 359-2012 | c | | slug incits3592012 |
| C3 | NIST SP 800-162 ABAC (алиас L18) | u | ★ | |
| C4 | UCON TISSEC 7(1) | c | | Mendeley record; DOI не проверен ×3 |
| C5 | Zanzibar ATC'19 (алиасы L16,seed11) | u | ★ | |
| C6 | SpiceDB consistency | v | | |
| C7 | OpenFGA docs | u | | |
| C8 | Cedar PLDI'24 | x | ★ | cedar-pldi.github.io не surfaced — ручная проверка |
| C9 | Verified Cedar SOSP'23 | x | | amazon.science запись не индексируется ×5 |
| C10 | Cedar language docs | u | ★ | |
| C11 | Rego/OPA docs | u | | |
| C12 | XACML 3.0 | u | | |
| C13 | NIST SP 800-207 Zero Trust | u | ★ | |
| C14 | PostgreSQL Row Security | u | ★ | |
| C15 | OpenFGA blocklists | c | | заменил exclusions guide |

## 8. Домен D — классические MAS (19)

| ID | Источник | Вер. | Ядро | Правка/примечание |
|---|---|---|---|---|
| D1 | BDI architecture '91 | u | | dblp-search URL |
| D2 | BDI theory→practice '95 | u | | |
| D3 | AgentSpeak(L) | u | | |
| D4 | Jason book | u | | |
| D5 | FIPA ACL SC00061G | u | ★ | |
| D6 | KQML CIKM'94 | v | | |
| D7 | JaCaMo | u | | |
| D8 | CArtAgO | u | ★ | |
| D9 | MOISE+ | u | ★ | |
| D10 | ISLANDER | u | | |
| D11 | STEAM Tambe | u | | |
| D12 | Teamwork Cohen&Levesque | x | | ручная проверка AIJ 1991 |
| D13 | Intention=choice CogSci'90 | v | | |
| D14 | Contract Net TSMC'80 | v | ★ | |
| D15 | Hearsay-II | u | | |
| D16 | Horling&Lesser survey | u | | |
| D17 | Aalaadin meta-model | u | | |
| D18 | Singh commitments | u | ★ | |
| D19 | Normative MAS intro | u | | |

## 9. Домен E — LLM-агенты (22)

| ID | Источник | Вер. | Ядро | Правка/примечание |
|---|---|---|---|---|
| E1 | ReAct | u | | |
| E2 | Reflexion | u | | |
| E3 | AutoGen | u | | |
| E4 | CrewAI docs | u | | |
| E5 | LangGraph docs | u | | |
| E6 | OpenAI SDK Handoffs | u | ★ | |
| E7 | Swarm | u | | |
| E8 | Magentic-One | u | | |
| E9 | MetaGPT | u | | |
| E10 | CAMEL | u | | |
| E11 | Generative Agents | u | | |
| E12 | MemGPT/Letta | u | | |
| E13 | Memory mechanisms survey | u | | |
| E14 | A-MEM | u | | |
| E15 | MAST (why MAS fail) | v | ★ | |
| E16 | Anthropic multi-agent research | c | ★ | без `built-` |
| E18 | τ-bench | u | | |
| E19 | GAIA | u | | |
| E20 | LLM MAS survey | u | | |
| E21 | OpenAI SDK Guardrails | u | ★ | |
| E22 | Semantic Kernel agents | u | | |
| E23 | ChatDev | u | | |

(E17 — дубликат A15, снят.)

## 10. Домены F/L — KR, провенанс, логики (35 валидных)

### F (20)

| ID | Источник | Вер. | Ядро | Правка/примечание |
|---|---|---|---|---|
| F1 | RDF 1.1 Concepts | u | | |
| F2 | RDF Schema 1.1 | u | | |
| F3 | OWL 2 Profiles | u | | |
| F4 | SHACL | u | ★ | |
| F5 | JSON-LD 1.1 | u | ★ | |
| F6 | SKOS | u | ★ | |
| F7 | PROV-DM | u | ★ | |
| F8 | PROV-O | u | ★ | |
| F9 | PROV-Dictionary | u | | |
| F10 | Knowledge Graphs CSUR | u | | |
| F11 | Reasoning About Knowledge | u | | |
| F12 | Dynamic Epistemic Logic | v | ★ | ISBN подтверждён |
| F13 | Epistemic Logic (SEP) | u | | |
| F14 | AGM JSL'85 | c | ★ | **DOI → 10.2307/2274239** |
| F15 | Katsuno–Mendelzon | u | | |
| F16 | Doyle TMS | u | ★ | |
| F17 | Reiter defaults | u | | |
| F18 | Dung argumentation | u | ★ | |
| F19 | Prakken–Sartor | u | ★ | |
| F20 | Carneades AIJ'07 | v | ★ | |

### L (15 после снятия L9/L13/L16/L18)

| ID | Источник | Вер. | Ядро | Правка/примечание |
|---|---|---|---|---|
| L1 | Deontic logic (SEP) | u | | |
| L2 | von Wright Mind'51 | v | | |
| L3 | Chisholm CTD | v | | |
| L4 | Input/Output logics | v | ★ | |
| L5 | Horty Agency&Deontic | u | | |
| L6 | ATL JACM'02 | c | ★ | **DOI → 10.1145/585265.585270** |
| L7 | Lampson speaks-for TOCS'92 | v | ★ | |
| L8 | Logic in Access Control | v | | |
| L10 | Alloy (Jackson) | u | ★ | |
| L11 | TLA+ (Lamport) | u | ★ | |
| L12 | Principles of Model Checking | u | | |
| L14 | Datalog FTDB survey | v | ★ | |
| L15 | Foundations of Databases | u | | |
| L17 | Fong RelBAC SACMAT'09 | x | | ручная проверка ACM DL |
| L19 | raft.tla | v | ★ | репозиторий корроборирован relatedrepos и форками |

## 11. Домены G/H — приватность и распределённость (36)

### G (19)

| ID | Источник | Вер. | Ядро | Правка/примечание |
|---|---|---|---|---|
| G1 | Double Ratchet | u | ★ | |
| G2 | X3DH | u | | |
| G3 | MLS RFC 9420 | v | ★ | подтверждено родителем (раунд 4) |
| G3b | MLS Architecture RFC 9750 | v | ★ | добавлен при верификации |
| G4 | MIMI protocol draft | u | | |
| G5 | Olm/Megolm | u | | |
| G6 | Cwtch | u | | |
| G7 | Intel TDX/SGX | u | ★ | |
| G8 | AMD SEV-SNP | u | ★ | |
| G9 | AWS Nitro Enclaves | u | ★ | |
| G10 | RATS RFC 9334 | u | ★ | |
| G11 | EAT RFC 9711 | u | ★ | |
| G12 | Azure confidential AI | u | ★ | |
| G13 | Pragmatic MPC | u | | |
| G14 | Automerge | u | ★ | |
| G15 | CRDT JSON TPDS | u | ★ | |
| G16 | Petname systems | v | ★ | оригинальный URL подтверждён (Wayback + анонс FC'05) |
| G17 | Solid TR (алиас seed13) | u | | |
| G18 | IPFS content addressing | u | | |

### H (17)

| ID | Источник | Вер. | Ядро | Правка/примечание |
|---|---|---|---|---|
| H1 | Raft ATC'14 | u | ★ | |
| H2 | PACELC | u | ★ | |
| H3 | Event Sourcing (Fowler) | u | ★ | |
| H4 | Transactional Outbox | u | ★ | |
| H5 | Saga pattern | u | ★ | |
| H6 | Idempotency keys (Stripe) | u | ★ | |
| H7 | Kafka delivery semantics | u | | |
| H8 | Temporal durability (алиас seed31) | u | ★ | |
| H9 | Durable Functions checkpointing | u | ★ | |
| H10 | OTP supervision | u | ★ | |
| H11 | ACTOR formalism '73 | u | | |
| H12 | Orleans virtual actors | u | | |
| H13 | Litestream | u | ★ | |
| H14 | PostgreSQL PITR | u | ★ | |
| H15 | CRDT SSS'11 | u | | |
| H16 | Lamport clocks | u | | |
| H17 | FoundationDB SIGMOD'21 | u | ★ | |

## 12. Домены I/J/K — угрозы, математика, HCI (40 валидных)

### I (17, одна исключена)

| ID | Источник | Вер. | Ядро | Правка/примечание |
|---|---|---|---|---|
| I1 | OWASP LLM Top-10 | u | | |
| I2 | OWASP Agentic Threats | u | | |
| I3 | Greshake indirect PI | v | ★ | |
| I4 | ~~Prompt injection survey~~ | x-исключён | — | arXiv 2406.06852 = другой обзор; строку не использовать |
| I5 | Lethal trifecta | u | | |
| I6 | Confused Deputy (Hardy) | v | | |
| I7 | CWE-367 TOCTOU | u | | |
| I8 | in-toto | u | ★ | |
| I9 | SLSA (алиас seed30) | u | ★ | |
| I10 | CycloneDX | u | | |
| I11 | Pickle/safetensors | u | ★ | |
| I12 | Wasm security | u | ★ | |
| I13 | gVisor | u | ★ | |
| I14 | Firewall for AI | u | ★ | |
| I15 | Certificate Transparency | u | ★ | |
| I16 | SP 800-92 Rev.1 ipd | v | | |
| I17 | MITRE ATLAS | u | | |

### J (13)

| ID | Источник | Вер. | Ядро | Правка/примечание |
|---|---|---|---|---|
| J1 | Little's Law | u | ★ | |
| J2 | M/M/c | u | ★ | |
| J3 | tc-tbf token bucket | u | ★ | |
| J4 | Netflix adaptive concurrency | x | | ручная проверка TechBlog |
| J5 | Timeouts/jitter (AWS) | u | | |
| J6 | Orca OSDI'22 | u | | |
| J7 | vLLM PagedAttention | u | | |
| J8 | Splitwise | u | | |
| J9 | Beta reputation | v | ★ | |
| J10 | EigenTrust | v | ★ | |
| J11 | AutoScale TOCS | v | | |
| J12 | Tail at Scale | v | | |
| J13 | Evan Miller rating bounds | u | ★ | |

### K (11)

| ID | Источник | Вер. | Ядро | Правка/примечание |
|---|---|---|---|---|
| K1 | Lee & See trust calibration | u | ★ | |
| K2 | POOR'CT levels | v | ★ | |
| K3 | EU AI Act Art.14 | u | ★ | |
| K4 | Meaningful human control | u | ★ | |
| K5 | Appropriate reliance (Schemmer) | c | ★ | **ID → 2204.06916; reliance-исследование, НЕ мета-анализ** |
| K6 | Sensecape UIST'23 | u | ★ | |
| K7 | Progressive disclosure NN/g | u | ★ | |
| K8 | Design of Everyday Things | u | ★ | |
| K9 | SRE monitoring/alert fatigue | u | ★ | |
| K10 | Android permissions SOUPS'12 | u | ★ | |
| K11 | MS Human-AI guidelines | u | ★ | |

## 13. Серия Z — seed-only источники (15)

| ID | Источник | Вер. |
|---|---|---|
| Z1 | Ink & Switch Local-first (2019) | u |
| Z2 | Matrix specification (spec.matrix.org) | u |
| Z3 | OpenAI workspace agent controls | u |
| Z4 | OpenID Shared Signals Framework 1.0 | u |
| Z5 | Google Cloud Agent Registry | u |
| Z6 | CloudEvents 1.0.2 | u |
| Z7 | Dapr Agents | u |
| Z8 | Scientist One: Chain-of-Evidence | v ★ |
| Z9 | Kim et al., scaling agent systems (2512.08296) | v |
| Z10 | NATS JetStream concepts | u |
| Z11 | OCI Image Spec | u |
| Z12 | OTel GenAI conventions | u |
| Z13 | OWASP Top 10 Agentic 2026 | u |
| Z14 | Shahroz et al., Agents under siege ACL'25 | u |
| Z15 | Sigstore Cosign verify docs | u |

## 14. Серия SV — межпротокольные обзоры (3)

| ID | Источник | Вер. |
|---|---|---|
| SV1 | Ehtesham et al., agent interoperability protocols (2505.02279) | v |
| SV2 | A Survey of AI Agent Protocols (2504.16736) | u |
| SV3 | Beyond Message Passing (2604.02369) | u |

## 15. Хвостовые действия

1. Ручная проверка шести `x`-строк браузером: C1 (profsandhu.com), C8 (cedar-pldi.github.io),
   C9 (amazon.science verified-cedar), D12 (AIJ 1991 Teamwork), L17 (ACM DL SACMAT'09),
   J4 (Netflix TechBlog).
2. Спот-чек Z/SV-серий: выполнен родителем в раунде 10 для приоритетных Z8, Z9, SV1
   (все три v; Z8 — точный URL research.google/pubs в выдаче; Z9 — HF Papers/Semantic Scholar;
   SV1 — Semantic Scholar, заголовок совпадает). Остальные Z/SV остаются u — некритично.
