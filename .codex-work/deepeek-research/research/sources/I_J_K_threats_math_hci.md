# Sources I (threats & controls) + J (quantitative models) + K (human factors)

Provenance: subagent 730718d9-dd27-41ea-b3eb-c99455778653, collected offline. ALL rows Conf=u.
Verify-first flags: I4 arXiv id/authors, I6 DOI, J4 slug, J9 AISel path, J10–J12 DOI suffixes, K2 IEEE doc#, K5 arXiv id, I16 CSRC path.

## Domain I — threats & controls

| ID | Title | Authors/Org | Year | Type | URL | Key claim | Informs | Conf |
|----|-------|-------------|------|------|-----|-----------|---------|------|
| I1 | OWASP Top 10 for LLM Applications 2025 | OWASP GenAI | 2025 | guide | https://genai.owasp.org/llm-top-10/ | Prompt injection, sensitive-data disclosure, excessive agency, system-prompt leakage; baseline threat vocabulary. | arch | u |
| I2 | Agentic AI — Threats and Mitigations v1.0 | OWASP GenAI | 2025 | guide | https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/ | Memory poisoning, tool misuse, privilege compromise, cascading hallucination, identity spoofing, oversight bypass. | arch | u |
| I3 | Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection | Greshake et al. | 2023 | paper | https://arxiv.org/abs/2302.12173 | Retrieved/hosted content silently hijacks LLM-integrated apps; indirect PI is first-class attack surface. | arch | u |
| I4 | Prompt Injection Attacks on LLMs: A Survey | (verify authors) | 2024 | paper | https://arxiv.org/abs/2406.06852 | Systematizes direct/indirect injection taxonomies, vectors, defenses. | arch | u |
| I5 | Lethal trifecta for LLM agents | Simon Willison | 2025 | blog | https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/ | Private data + untrusted content + exfiltration channel ≈ practically undefendable; design must break one leg. | feat | u |
| I6 | The Confused Deputy | Norman Hardy | 1988 | paper | https://dl.acm.org/doi/10.1145/54289.87171 | Authorized program tricked into misusing its authority — motivates capability-bound authorization. | arch | u |
| I7 | CWE-367: TOCTOU Race Condition | MITRE | 2023 | spec | https://cwe.mitre.org/data/definitions/367.html | Check-then-act races void authorization; decisions and effects must bind atomically. | feat | u |
| I8 | in-toto | in-toto project | 2023 | spec | https://in-toto.io/ | Signed layout+link attestations prove who did what to artifacts when — provenance template. | arch | u |
| I9 | SLSA v1.x (dup base #30) | OpenSSF | 2023 | spec | https://slsa.dev/spec/v1.0 | Build-integrity levels covering models/tools platform agents consume. | arch | u |
| I10 | CycloneDX BOM Specification | OWASP CycloneDX | 2024 | spec | https://cyclonedx.org/spec/bom/latest/ | Machine-readable SBOM extendable to model-and-tool bills for hub inventory. | feat | u |
| I11 | Pickle file security / safetensors rationale | Hugging Face | 2024 | docs | https://huggingface.co/docs/hub/security-pickle | Pickle deserialization executes arbitrary code; safetensors eliminates it — model-ingestion gate grounding. | feat | u |
| I12 | WebAssembly Sandbox Security | WebAssembly WG | 2024 | docs | https://webassembly.org/docs/security/ | Fault-isolated capability-scoped execution — cheap isolation tier for agent tool calls. | arch | u |
| I13 | gVisor: Application Kernel in Userspace | Google | 2024 | docs | https://gvisor.dev/docs/ | User-space kernel intercepting syscalls reduces attack surface for semi-trusted agent containers. | arch | u |
| I14 | Firewall for AI | Cloudflare | 2024 | blog | https://blog.cloudflare.com/firewall-for-ai/ | Network-tier inspection/policy before model traffic — pattern for egress allow-lists and DLP gates. | feat | u |
| I15 | Certificate Transparency (RFC 6962) | Laurie et al. | 2013 | rfc | https://www.rfc-editor.org/rfc/rfc6962 | Append-only Merkle logs with consistency proofs — blueprint for tamper-evident audit logs. | arch | u |
| I16 | SP 800-92 Rev.1 draft (log management) | NIST | 2023 | guide | https://csrc.nist.gov/pubs/sp/800/92/r1/ipd | Logging planning, protection, retention, SIEM integration — compliance anchor for audit design. | feat | u |
| I17 | MITRE ATLAS | MITRE | 2025 | guide | https://atlas.mitre.org/ | ATT&CK-style matrix of real-world ML attacks with mitigations/case studies — threat-model backbone. | arch | u |

## Domain J — quantitative models

| ID | Title | Authors/Org | Year | Type | URL | Key claim | Informs | Conf |
|----|-------|-------------|------|------|-----|-----------|---------|------|
| J1 | A Proof for the Queuing Formula L = λW | Little | 1961 | paper | https://doi.org/10.1287/opre.9.3.383 | Steady-state concurrency = arrival rate × residence time — links budgets, latency, parallelism. | math | u |
| J2 | M/M/c queue (Kleinrock Vol.1 anchor) | Kleinrock 1975; summary | 1975 | paper | https://en.wikipedia.org/wiki/M/M/c_queue | Closed-form wait probability/latency vs load ρ sizes authorize() worker pools below saturation cliff. | math | u |
| J3 | tc-tbf(8) Token Bucket Filter | Linux man-pages | 2023 | docs | https://man7.org/linux/man-pages/man8/tc-tbf.8.html | Token-bucket semantics: sustained rate + burst depth + queue limit — vocabulary for per-agent quotas. | math | u |
| J4 | Performance Under Load: Adaptive Concurrency Limits @ Netflix | Netflix Tech Blog | 2018 | blog | https://netflixtechblog.medium.com/performance-under-load-3e6fa9a60581 | Derive limits from latency gradients instead of static concurrency caps to prevent collapse under variable load. | math | u |
| J5 | Timeouts, retries, backoff with jitter | Marc Broberg (AWS Builders' Library) | 2019 | blog | https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/ | Uncoordinated retries amplify outages; jitter + bounded timeouts stabilize retry storms across fan-out. | math | u |
| J6 | Orca (OSDI'22) | Yu et al. | 2022 | paper | https://www.usenix.org/conference/osdi22/presentation/yu | Continuous batching + iteration-level scheduling raise utilization for concurrent generations. | math | u |
| J7 | vLLM PagedAttention (SOSP'23) | Kwon et al. | 2023 | paper | https://arxiv.org/abs/2309.06180 | Paged KV-cache cuts fragmentation multiplying concurrent sessions per GPU — unit economics of shared inference. | math | u |
| J8 | Splitwise (ISCA'24) | Patel et al. | 2024 | paper | https://arxiv.org/abs/2311.18677 | Phase splitting lowers per-token cost/latency — hub inference budget model. | math | u |
| J9 | The Beta Reputation System | Jøsang & Ismail | 2002 | paper | https://aisel.aisnet.org/bled2002/41/ | Bayesian beta updates with decay turn feedback events into posterior trust scores. | math | u |
| J10 | EigenTrust (WWW'03) | Kamvar, Schlosser, Garcia-Molina | 2003 | paper | https://dl.acm.org/doi/10.1145/775152.775242 | Global trust as principal eigenvector of normalized ratings — collusion-resistant aggregation. | math | u |
| J11 | AutoScale (TOCS) | Gandhi & Harchol-Balter | 2012 | paper | https://dl.acm.org/doi/10.1145/2382555.2382562 | Queueing-theoretic autoscaling from predicted demand avoids oscillation — hub capacity controller template. | math | u |
| J12 | The Tail at Scale | Dean & Barroso, CACM | 2013 | paper | https://dl.acm.org/doi/10.1145/2486017 | Fan-out amplifies tail latency; hedged requests/partitioned aggregation bound p99. | math | u |
| J13 | How Not To Sort By Average Rating | Evan Miller | 2009 | blog | https://evanmiller.org/how-not-to-sort-by-average-rating.html | Wilson/Bayesian lower bounds stop small-sample items outranking solid evidence in rankings. | math | u |

## Domain K — human factors

| ID | Title | Authors/Org | Year | Type | URL | Key claim | Informs | Conf |
|----|-------|-------------|------|------|-----|-----------|---------|------|
| K1 | Trust in Automation: Designing for Appropriate Reliance | Lee & See, Human Factors 46(1) | 2004 | paper | https://journals.sagepub.com/doi/10.1518/hfes.46.1.50_30392 | Target calibrated—not maximal—trust; displayed cues must match actual capability boundaries. | mental | u |
| K2 | Types and Levels of Human Interaction with Automation | Parasuraman, Sheridan, Wickens, IEEE SMC-A | 2000 | paper | https://ieeexplore.ieee.org/document/844354 | Allocate automation per POOR'CT stage balancing workload vs complacency — oversight levels scaffold. | mental | u |
| K3 | EU AI Act Article 14 Human Oversight (Reg. 2024/1689) | European Union | 2024 | spec | https://eur-lex.europa.eu/eli/reg/2024/1689/oj | High-risk AI needs measures for understanding limits, countering automation bias, intervening, overriding, stopping. | feat | u |
| K4 | Meaningful Human Control | Santoni de Sio & van den Hoven, Frontiers Robotics AI | 2018 | paper | https://www.frontiersin.org/articles/10.3389/frobt.2018.00015/full | Meaningful control = tracking + tracing: steer outcomes and remain identifiable as responsible. | mental | u |
| K5 | Should I Follow AI-based Advice? Measuring Appropriate Reliance in Human-AI Decision-Making | Schemmer et al. | 2022 | paper | https://arxiv.org/abs/2204.06916 | Defines and measures appropriate reliance; it is not a meta-analysis. | mental | u |
| K6 | Sensecape (UIST'23) | Suh et al. | 2023 | paper | https://dl.acm.org/doi/10.1145/3586183.3606766 | Spatial/multimodal interfaces help users form usable mental models of opaque LLM behavior. | mental | u |
| K7 | Progressive Disclosure | Nielsen Norman Group | 2006 | guide | https://www.nngroup.com/articles/progressive-disclosure/ | Show essentials first, defer detail until requested — on-whose-behalf banner + provenance drill-down pattern. | feat | u |
| K8 | The Design of Everyday Things (rev.) | Don Norman | 2013 | book | https://www.basicbooks.com/titles/don-norman/the-design-of-everyday-things/9780465050659/ | Affordances/signifiers/mapping to system image let users predict behavior — requirement for delegable-agent UIs. | mental | u |
| K9 | Monitoring Distributed Systems (Google SRE book) | Beyer et al., O'Reilly/Google | 2016 | docs | https://sre.google/sre-book/monitoring-distributed-systems/ | Alerts compete for scarce attention; symptom-based paging with budgets prevents desensitization — applies to approval prompts. | feat | u |
| K10 | Android Permissions: Attention, Comprehension, Behavior (SOUPS'12) | Felt et al. | 2012 | paper | https://dl.acm.org/doi/10.1145/2335356.2335360 | Install-time permission dialogs largely unread/misunderstood — warns against one-shot blanket delegation screens. | feat | u |
| K11 | Guidelines for Human-AI Interaction (CHI'19) | Amershi et al. | 2019 | paper | https://dl.acm.org/doi/10.1145/3290605.3300233 | 18 validated guidelines (capabilities, timing, feedback, dismissal) — checklist for delegation UX. | feat | u |

## Insights (collector)
- Adoptable controls: lethal-trifecta test per capability; confused-deputy fix = subject-bound capabilities atomically bound to authorize() decisions (I6+I7); in-toto-style signed provenance feeding RFC 6962-style Merkle audit logs; non-executable model formats + SBOM inventory; MITRE ATLAS + OWASP guides as threat-model skeleton.
- Isolation ladder: Wasm for pure tool functions → gVisor/microVM for anything touching user files/network, with egress allow-lists enforced outside the agent's control plane.
- 205 agents @ 34 events/s (~0.17/s/agent): Little's Law sets in-flight actions = 34 × decision+execution latency; M/M/c sizes authorize() pool below ρ≈0.8 knee.
- Budgets: token bucket per agent (rate+burst); adaptive concurrency where downstream latency varies; mandatory jittered retries.
- Serving economics: continuous batching/PagedAttention set concurrent turns per GPU; Splitwise lets cheap evaluators share decode hardware; tail-at-scale hedging bounds p99 under fan-out.
- Trust math: decayed Beta posteriors for member→agent and agent→tool scores; EigenTrust aggregation resists collusion; Wilson/Bayesian lower bounds gate knowledge promotion.
- Delegation UX: Art.14 + tracking/tracing → visible override, stop, attributable responsibility; progressive disclosure shows on-whose-behalf first, provenance on demand.
- Calibration over persuasion: surface confidence/limits with outputs; permission research warns one-click blanket delegation produces rubber-stamping.
- Anti-alarm-fatigue: authorization prompts as attention-budgeted symptom alerts — rate-limited, batched, severity-ranked; Sensecape-style spatial views keep 20 people's models of 205 agents accurate.

## Verification verdicts (V1, subagent 64c8b59c, раунд 8)

| ID | Verdict | Финальный URL / правка | Примечание |
|---|---|---|---|
| I3 | v | https://arxiv.org/abs/2302.12173 | abs v2, точное название Greshake et al. |
| I4 | x | — | **ID доказуемо неверен**: 2406.06852 = обзор бэкдоров LLM (виден дважды); авторов строки подтвердить нельзя → ИСКЛЮЧИТЬ из реестра; таксономию injection брать из I1/I2/I3 |
| I6 | v | https://dl.acm.org/doi/10.1145/54289.87171 | запись Hardy через Semantic Scholar/Mendeley |
| I16 | v | https://csrc.nist.gov/pubs/sp/800/92/r1/ipd | csrc ipd-страница + nvlpubs ipd PDF напрямую |
| J4 | c | https://netflixtechblog.medium.com/performance-under-load-3e6fa9a60581 | официальный Netflix Tech Blog переехал на Medium; title и content подтверждены |
| J9 | v | https://aisel.aisnet.org/bled2002/41/ | BLED 2002 через Mendeley/researchr/dblp |
| J10 | v | https://dl.acm.org/doi/10.1145/775152.775242 | страница ACM DL видна напрямую, WWW 2003 |
| J11 | v | https://dl.acm.org/doi/10.1145/2382555.2382562 | dblp TOCS GandhiHRK12 (30(4) 2012) |
| J12 | v | https://dl.acm.org/doi/10.1145/2486017 | CACM 2013 запись через Mendeley + EDS |
| K2 | v | https://ieeexplore.ieee.org/document/844354 | TSMC-A PDF, Dimensions, DOI 10.1109/3468.844354 |
| K5 | c | https://arxiv.org/abs/2204.06916 | **исправлен ID**: правильная работа Schemmer et al. — 2204.06916 «Should I Follow AI-based Advice?»; измеряет reliance, НЕ мета-анализ (скорректировать формулировку при цитировании) |

Не покрыто V1 (остаются u): I1, I2, I5, I7–I15, I17, J1–J3, J5–J8, K1, K3, K4, K6–K11.
