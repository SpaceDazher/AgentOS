# Sources D (classic MAS) + E (LLM agent engineering)

Provenance: subagent 8af0986e-e93c-44a1-b85f-477abde877bf, collected offline. ALL rows Conf=u.
Older classics use dblp search URLs (deterministic bibliographic records) where DOIs not confidently known.
arXiv IDs to batch-verify when network returns: 2210.03629, 2303.11366, 2308.08155, 2411.04468, 2308.00352,
2303.17760, 2304.03442, 2310.08560, 2404.13501, 2502.12110, 2503.13657, 2406.12045, 2311.12983, 2402.01680, 2307.07924.

## Domain D — classic MAS

| ID | Title | Authors | Year | Type | URL | Key claim | Informs | Conf |
|---|---|---|---|---|---|---|---|---|
| D1 | Modeling Rational Agents within a BDI-Architecture | Rao & Georgeff | 1991 | paper | https://dblp.org/search?q=Modeling+rational+agents+within+a+BDI+architecture | Belief–desire–intention theory; intentions persist and filter adoption — goal-commitment lifecycle basis. | math | u |
| D2 | BDI Agents: From Theory to Practice | Rao & Georgeff | 1995 | paper | https://dblp.org/search?q=BDI+agents:+From+theory+to+practice | Implemented interpreter loop over beliefs/desires/plans — hub agent runtime cycle blueprint. | arch | u |
| D3 | AgentSpeak(L) | Rao | 1996 | paper | https://dblp.org/search?q=Rao+AgentSpeak+%28L%29 | Executable agent language with operational semantics; inspectable deliberation traces. | math | u |
| D4 | Programming MAS in AgentSpeak Using Jason | Bordini, Hübner, Wooldridge | 2007 | book | https://dblp.org/search?q=Programming+Multi-Agent+Systems+in+AgentSpeak | Engineering guide: plans/environments/interaction; role-coded programs as persona templates. | arch | u |
| D5 | FIPA ACL Message Structure (SC00061G) | FIPA | 2002 | spec | http://www.fipa.org/specs/fipa00061/SC00061G.html | Speech-act ACL standard: communicative acts, protocols, content languages — typed Message envelope vocabulary. | onto | u |
| D6 | KQML — An Agent Communication Language | Finin et al. | 1994 | paper | https://doi.org/10.1145/191246.191269 | Performatives + facilitator broking; cautionary tale on underspecified semantics. | onto | u |
| D7 | JaCaMo | Boissier, Bordini, Hübner, Ricci, Santi | 2013 | paper | https://dblp.org/search?q=JaCaMo+platform+for+multi-agent+programming | Agents / coordination medium / organization as orthogonal layers — mirrors hub split. | arch | u |
| D8 | CArtAgO | Ricci, Viroli, Omicini | 2007 | paper | https://dblp.org/search?q=CArtAgO+framework+for+prototyping+artifact-based+environments | Typed artifacts inside workspaces accessed via usage operations — workspace-scoped shared objects precedent. | arch | u |
| D9 | MOISE+ Model | Hübner, Sichman, Boissier | 2007 | paper | https://dblp.org/search?q=developing+organised+multi-agent+systems+using+the+MOISE%2B+model | Organizational schema: goals→missions→roles with deontic links, checkable at runtime — governance template. | onto | u |
| D10 | ISLANDER Electronic Institution Editor | Esteva, de la Cruz, Sierra | 2004 | paper | https://dblp.org/search?q=ISLANDER+an+electronic+institution+editor | Scenes/roles/dialogic frames/norms constraining permitted illocutions; governor enforces legality. | onto | u |
| D11 | Towards Flexible Teamwork (STEAM) | Tambe | 1997 | paper | https://dblp.org/search?q=Towards+Flexible+Teamwork+Tambe | Joint intentions operationalized with mutual-responsibility monitoring and conflict resolution. | arch | u |
| D12 | Teamwork | Cohen & Levesque | 1991 | paper | https://doi.org/10.1016/0004-3702(91)90043-Q | Joint persistent goal + mutual belief; obligatory success/failure/infeasibility announcements. | math | u |
| D13 | Intention Is Choice with Commitment | Cohen & Levesque | 1990 | paper | https://doi.org/10.1207/s15516709cog1403_1 | Intention = committed choice with drop-conditions — goal expiry/quota release vocabulary. | math | u |
| D14 | Contract Net Protocol | Smith | 1980 | paper | https://doi.org/10.1109/TSMC.1980.4508720 | Announce–bid–award task distribution with result sharing — canonical allocation protocol. | arch | u |
| D15 | Hearsay-II | Erman, Hayes-Roth, Lesser, Reddy | 1980 | paper | https://dblp.org/search?q=Hearsay-II+speech-understanding+system+integrating+knowledge | Blackboard architecture under central scheduling — control policy dominates capability. | arch | u |
| D16 | Survey of MAS Organizational Paradigms | Horling & Lesser | 2004 | survey | https://dblp.org/search?q=Horling+Lesser+survey+multi-agent+organizational+paradigms | Hierarchies/markets/coalitions trade-offs: overhead vs quality — topology per workload. | arch | u |
| D17 | Aalaadin Meta-Model | Ferber & Gutknecht | 1998 | paper | https://dblp.org/search?q=Ferber+meta-model+analysis+design+of+organizations | Groups/roles/structures first-class with compatibility/authority links — role ontology foundation. | onto | u |
| D18 | Ontology for Commitments in MAS | Singh | 1999 | paper | https://dblp.org/search?q=An+ontology+for+commitments+in+multiagent+systems | Directed debtor–creditor commitments with detachment/discharge/cancel — publicly checkable social semantics. | onto | u |
| D19 | Normative Multiagent Systems intro | Boella & van der Torre | 2006 | survey | https://dblp.org/search?q=Introduction+to+normative+multiagent+systems | Norms constrain AND enable behavior — norm layer above raw permissions. | onto | u |

## Domain E — LLM agents

| ID | Title | Authors/Org | Year | Type | URL | Key claim | Informs | Conf |
|---|---|---|---|---|---|---|---|---|
| E1 | ReAct | Yao et al. | 2022 | paper | https://arxiv.org/abs/2210.03629 | Interleaved reasoning+grounded action cuts hallucination; default inner cycle. | arch | u |
| E2 | Reflexion | Shinn et al. | 2023 | paper | https://arxiv.org/abs/2303.11366 | Verbal self-critique in episodic buffer improves retries without weight updates. | feat | u |
| E3 | AutoGen | Wu et al. | 2023 | paper | https://arxiv.org/abs/2308.08155 | Conversable agents via typed/group chats with HITL and code execution. | arch | u |
| E4 | CrewAI docs | CrewAI Inc. | 2025 | docs | https://docs.crewai.com/introduction | Role/goal/backstory crews, ordered tasks, hierarchical processes incl. delegation controls. | arch | u |
| E5 | LangGraph docs | LangChain Inc. | 2025 | docs | https://langchain-ai.github.io/langgraph/ | Graph-state orchestration with checkpointing/persistence/HITL interrupts; supervisor recipes. | arch | u |
| E6 | OpenAI Agents SDK — Handoffs | OpenAI | 2025 | docs | https://openai.github.io/openai-agents-python/handoffs/ | First-class handoff transfers control plus context between agents. | feat | u |
| E7 | Swarm framework | OpenAI | 2024 | docs | https://github.com/openai/swarm | Routines+handoffs validate client-side lightweight orchestration. | feat | u |
| E8 | Magentic-One | Fourney et al. (Microsoft) | 2024 | paper | https://arxiv.org/abs/2411.04468 | Orchestrator-worker with task ledger tracking facts/progress drives replanning. | arch | u |
| E9 | MetaGPT | Hong et al. | 2023 | paper | https://arxiv.org/abs/2308.00352 | SOPs as pipeline stages emitting structured artifacts; reduces cascading errors. | arch | u |
| E10 | CAMEL | Li et al. | 2023 | paper | https://arxiv.org/abs/2303.17760 | Role-played autonomous cooperation; documents dialogue drift/degradation. | feat | u |
| E11 | Generative Agents | Park et al. | 2023 | paper | https://arxiv.org/abs/2304.03442 | Per-agent memory stream + reflection + planning → emergent behavior; canonical memory isolation. | feat | u |
| E12 | MemGPT / Letta | Packer et al. | 2023 | paper | https://arxiv.org/abs/2310.08560 | OS-style tiered memory paged via self-editing function calls. | arch | u |
| E13 | Memory Mechanism Survey | Zhang et al. | 2024 | survey | https://arxiv.org/abs/2404.13501 | Taxonomy of what/how memory is written/managed/read — MemoryRecord store policy map. | arch | u |
| E14 | A-MEM | Xu et al. | 2025 | paper | https://arxiv.org/abs/2502.12110 | Autonomous Zettelkasten-like linked memory evolution outperforms fixed pipelines. | feat | u |
| E15 | Why Do Multi-Agent LLM Systems Fail? (MAST) | Cemri et al. | 2025 | paper | https://arxiv.org/abs/2503.13657 | 17 failure modes over 500+ traces: specification, inter-agent misalignment, verification; majority failed. | math | u |
| E16 | Anthropic multi-agent research system | Anthropic Engineering | 2025 | docs | https://www.anthropic.com/engineering/built-multi-agent-research-system | Parallel subagents under token budgets/scoped tools; ~90% quality gain at ~15× token cost. | arch | u |
| E17 | Building Effective Agents (dup A15) | Anthropic Engineering | 2024 | docs | https://www.anthropic.com/engineering/building-effective-agents | Workflow vs autonomy patterns; complexity only when measurably justified. | feat | u |
| E18 | τ-bench | Yao et al. | 2024 | paper | https://arxiv.org/abs/2406.12045 | Policy-compliant tool use benchmark; pass^k consistency exposes run-to-run variance. | math | u |
| E19 | GAIA | Mialon et al. | 2023 | paper | https://arxiv.org/abs/2311.12983 | Real-world assistant tasks where humans beat models; multi-step tool chain fragility. | math | u |
| E20 | LLM Multi-Agents survey | Guo et al. | 2024 | survey | https://arxiv.org/abs/2402.01680 | Profiling/communication/memory/planning structure; consensus/scalability/evaluation challenges. | arch | u |
| E21 | OpenAI Agents SDK — Guardrails | OpenAI | 2025 | docs | https://openai.github.io/openai-agents-python/guardrails/ | Parallel input/output tripwires independent of agent logic enforce policy before side effects. | feat | u |
| E22 | Semantic Kernel Agent Framework | Microsoft | 2025 | docs | https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/ | Enterprise runtime: sequential/concurrent/handoff/group-chat patterns atop governed infra. | arch | u |
| E23 | ChatDev | Qian et al. | 2023 | paper | https://arxiv.org/abs/2307.07924 | Phase-gated dual-agent chat chains limit error propagation between stages. | arch | u |

## Insights (collector)
- Ontology carry-over: Role/Group/mission decomposition (MOISE+, Aalaadin) + directed commitments (debtor→creditor, deadline, discharge — Singh) become first-class typed objects; platform agents bound to role schemas.
- Norms above permissions: electronic institutions give machine-checkable interaction legality per workspace feeding the evidence gate.
- Typed talk, no shared brain: FIPA/KQML validate performatives but show mental-state semantics under-specify meaning → commitment-based message semantics keep the deterministic scheduler auditable.
- CArtAgO artifacts-in-workspaces ≈ workspace-scoped typed objects; Hearsay-II: deterministic scheduler integrating partial results wins; Horling–Lesser: topology must match workload shape.
- MAST: most failures are spec/misalignment defects → strictly typed handoff payloads + explicit completion contracts.
- Fan-out is a correctness knob: ~15× token cost for multi-agent (Anthropic), subagent breadth caps (~10); quotas/rate limits are reliability devices, not just cost control.
- Memory isolation: per-agent append-only streams with retrieval/self-editing; promotion = provenance-bearing assertion pipeline (= KnowledgeAssertion + evidence gate).
- Evaluation: τ-bench pass^k + GAIA variance → repeated trials + rubric graders; guardrails live in deterministic services outside the model.

## Verification verdicts (V1, subagent 64c8b59c, раунд 8)

| ID | Verdict | Финальный URL / правка | Примечание |
|---|---|---|---|
| D6 | v | https://doi.org/10.1145/191246.191269 | CIKM'94; dblp FininFMM94 + копия UMBC |
| D12 | x | — | DOI/название/dblp/ScienceDirect не surfaced ×неск.; статья классическая, проверить вручную |
| D13 | v | https://doi.org/10.1207/s15516709cog1403_1 | CogSci 14(3) 1990; Scilit + EDS |
| D14 | v | https://doi.org/10.1109/TSMC.1980.4508720 | IEEE Xplore 1675516, точное название |
| E15 | v | https://arxiv.org/abs/2503.13657 | arXiv зеркало + Semantic Scholar + dblp |
| E16 | c | https://www.anthropic.com/engineering/multi-agent-research-system | без префикса `built-` |

Не покрыто V1 (остаются u): D1–D5, D7–D11, D15–D19, E1–E14, E17–E23.
