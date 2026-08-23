# Sources A (protocols) + M (prior art)

Provenance: subagent 63e82ce5-ad16-44d7-9247-7e1370648f63, collected offline.
ALL rows Conf=u (web_search unavailable: missing DEEPSEEK_API_KEY; egress blocked).
Gap flagged by collector: no dedicated 2024–2026 interop-survey citation yet (backfill when search works).

## Domain A — protocols

| ID | Title | Org/Authors | Year | Type | URL | Key claim | Informs | Conf |
|---|---|---|---|---|---|---|---|---|
| A1 | A2A Protocol Specification | Linux Foundation / A2A Project (orig. Google) | 2025 | spec | https://a2a-protocol.org/ | Agent↔agent task exchange: Agent Card discovery, message/task/artifact lifecycle, streaming, push notifications; multiple transports. | feat | u |
| A2 | A2A reference implementation & release notes | a2aproject (GitHub) | 2025 | spec | https://github.com/a2aproject/A2A | Version history 0.2.x→0.3.x: transport-agnostic design with gRPC and JWS-signed Agent Cards; extensions mechanism. | arch | u |
| A3 | A2A donation to Linux Foundation | Google Developers Blog | 2025 | blog | https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/ | Neutral foundation governance; positions A2A as complement to MCP (agent tasks vs tool access). | arch | u |
| A4 | MCP specification (latest) | MCP community | 2026 | spec | https://modelcontextprotocol.io/specification/2026-07-28/ | Stateless core primitives: tools, resources, prompts; sampling and elicitation as negotiated capabilities. | feat | u |
| A5 | MCP Authorization specification | MCP authors | 2026 | spec | https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization | OAuth resource-server profile with issuer validation and credential binding; authorization remains separate from tool semantics. | arch | u |
| A6 | MCP Tasks extension | MCP community | 2026 | extension | https://modelcontextprotocol.io/extensions/tasks/overview | Durable asynchronous task lifecycle moved from the 2025 experimental core into the `io.modelcontextprotocol/tasks` extension. | feat | u |
| A7 | Official MCP Registry | modelcontextprotocol (GitHub) | 2025 | product | https://github.com/modelcontextprotocol/registry | Public registry of MCP server metadata; federated/sub-registry model — template for hub private mirror. | feat | u |
| A8 | Agent Communication Protocol (ACP) docs | IBM Research / BeeAI | 2025 | spec | https://agentcommunicationprotocol.dev/ | REST-based multimodal agent messaging for offline-capable teams; contributed to Linux Foundation; leaves identity/delegation to platforms. | arch | u |
| A9 | Agent Network Protocol (ANP) | Chao Wang / ANP community | 2024 | spec | https://github.com/agent-network-protocol/AgentNetworkProtocol | Inter-agent networking on DIDs (did:wba): decentralized identity, discovery, negotiation across boundaries. | arch | u |
| A10 | Agora: A Protocol for Cooperative Multi-Agent LLMs | Ye et al., Oxford | 2024 | paper | https://arxiv.org/abs/2410.11905 | Inter-agent communication as retrieval/routing: natural language, structured templates, or executable routines per context. | arch | u |
| A11 | Eclipse LMOS / Arcadia multi-protocol adapter | Eclipse Foundation | 2025 | product | https://eclipse.dev/lmos/ | One adapter exposes agents via MCP, A2A, ACP simultaneously; registry plus routing between specialists. | arch | u |
| A12 | Decentralized Identifiers (DIDs) v1.0 | W3C | 2024 | spec | https://www.w3.org/TR/did-core/ | DID syntax, documents, verification methods — account-independent substrate for long-lived agent identity. | arch | u |
| A13 | AGNTCY Internet of Agents (Agent Directory Service, OASF) | Cisco + AGNTCY collective | 2025 | product | https://agntcy.org/ | Directory service and Open Agentic Schema Framework: signed agent identity/exposure records for discovery/attestation. | arch | u |
| A14 | kagent — Kubernetes-native agent framework | Solo.io / CNCF sandbox | 2025 | product | https://kagent.dev/ | Agent definitions packaged as OCI artifacts with versioned pushes/pulls — precedent for immutable AgentDefinition storage. | arch | u |
| A15 | Building Effective Agents | Anthropic engineering | 2024 | blog | https://www.anthropic.com/engineering/building-effective-agents | Workflows vs autonomous agents; composable patterns; simple deterministic orchestration beats heavy frameworks. | arch | u |

## Domain M — prior art

| ID | Title | Org/Authors | Year | Type | URL | Key claim | Informs | Conf |
|---|---|---|---|---|---|---|---|---|
| M1 | Introducing ChatGPT agent | OpenAI | 2025 | product | https://openai.com/index/introducing-chatgpt-agent/ | Virtual-worker mode that browses/acts; enterprise admin enablement + explicit prompt-injection risk disclosure. | feat | u |
| M2 | Gemini Enterprise (ex-Agentspace) docs | Google Cloud | 2025 | docs | https://cloud.google.com/agentspace/docs | Governed agent platform: no-code builders, connectors, centralized catalog, tenant-scoped access control and audit. | feat | u |
| M3 | Microsoft Copilot Studio docs | Microsoft Learn | 2025 | docs | https://learn.microsoft.com/en-us/microsoft-copilot-studio/ | Low-code authoring; environment isolation, connector DLP policies, authentication options, per-agent analytics. | feat | u |
| M4 | Microsoft 365 Agents SDK | Microsoft Learn | 2025 | docs | https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/ | Channel-agnostic agents; transport adapters abstract delivery; identity via registered app principals. | arch | u |
| M5 | Microsoft Entra Agent ID | Microsoft Learn | 2025 | docs | https://learn.microsoft.com/en-us/entra/agent-id/ | First-class directory identity for AI agents: lifecycle, credentials, Conditional Access, ownership linked to creator. | arch | u |
| M6 | Claude Code documentation | Anthropic | 2025 | docs | https://docs.anthropic.com/en/docs/claude-code/overview | Terminal coding agent: permission modes gating tools, hooks, subagents, MCP servers — approval-bound autonomy. | feat | u |
| M7 | Amazon Bedrock Agents docs | AWS | 2025 | docs | https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html | Action groups, knowledge bases, memory; each agent under its own IAM role — per-agent least privilege by construction. | arch | u |
| M8 | Amazon Bedrock AgentCore | AWS | 2025 | product | https://aws.amazon.com/bedrock/agentcore/ | Runtime, Identity (agent identities + credential vault), MCP-compatible Gateway, Memory, Browser, Code Interpreter. | arch | u |
| M9 | Salesforce Agentforce (Atlas) dev docs | Salesforce | 2025 | docs | https://developer.salesforce.com/docs/einstein/genai/ | Atlas reasoning engine over company metadata; Trust Layer: audit trail, guardrails, topic-scoped action allowlists. | feat | u |
| M10 | ServiceNow AI Agents / AI Agent Studio | ServiceNow | 2025 | product | https://www.servicenow.com/products/ai-agents.html | Agents orchestrated on workflow engine with human-approval steps; inherits existing RBAC governance. | arch | u |
| M11 | LibreChat documentation | LibreChat (OSS) | 2025 | docs | https://www.librechat.ai/docs | Self-hosted multi-provider chat hub: per-user agents, MCP client support, message persistence — closest OSS analog to hub UX tier. | feat | u |
| M12 | Dify documentation | LangGenius (OSS) | 2025 | docs | https://docs.dify.ai | LLM-app platform with team workspaces, provider management, agent workflows; app-level tenant isolation self-hosted. | feat | u |
| M13 | n8n documentation (AI/LangChain nodes) | n8n | 2025 | docs | https://docs.n8n.io | Workflow automation with agent nodes and human-in-the-loop approvals; credentials scoped per workflow/user. | arch | u |
| M14 | Open WebUI documentation | Open WebUI community | 2025 | docs | https://docs.openwebui.com | Self-hosted chat UI with multi-user RBAC, model ACLs, tools/functions pipelines — lightweight personal-hub baseline. | feat | u |
| M15 | AutoGen Studio | Microsoft / AutoGen project | 2025 | docs | https://microsoft.github.io/autogen/ | Declarative multi-agent prototyping UI: component/team galleries, session playback; strong orchestration, thin tenancy/quota controls. | feat | u |
| M16 | CrewAI AMP | CrewAI | 2025 | product | https://www.crewai.com/ | Managed multi-agent platform: crews/flows deployment, observability, enterprise control-plane option. | feat | u |
| M17 | MCP security notification (GitHub MCP prompt injection) | Invariant Labs | 2025 | blog | https://invariantlabs.ai/blog/mcp-security-notification | Indirect prompt injection via GitHub MCP tool outputs could leak private repository data — motivates tool-output sanitization gates. | arch | u |
| M18 | mcp-scan: tool poisoning attacks | Invariant Labs | 2025 | blog | https://invariantlabs.ai/blog/introducing-mcp-scan | Malicious text hidden in MCP tool descriptions triggers cross-server actions; continuous manifest scanning proposed. | feat | u |

## Insights (collector)
- No surveyed protocol owns delegation: DelegationGrant remains hub-specific contract.
- Signed Agent Cards + DID/AGNTCY directories → hub registry stores publisher-signed cards, verify on import.
- MCP OAuth-resource-server model maps onto short-lived attenuated workspace-scoped tokens.
- MCP Tasks legitimizes durable async task objects — align scheduler/outbox to task-object semantics.
- Entra Agent ID / AgentCore Identity validate platform agents as dedicated service principals with creator-linked accountability.
- Documented incidents justify evidence gate: provenance tags, output sanitization, manifest scanning before KnowledgeAssertion promotion.
- Per-agent least privilege is industry-converged — adopt as quota/scoping features.
- Normalize A2A+MCP behind one canonical internal envelope with swappable adapters (LMOS Arcadia precedent).

## Verification verdicts (V2, subagent 77b31b8f, раунд 7; 18/36 проверенных строк)

v = URL подтверждён поиском; c = подтверждён с канонической правкой URL; u = не проверено (вне объёма V2); x = не подтвердилось (не обязательно мертво).

| ID | Verdict | Финальный URL / правка | Примечание |
|---|---|---|---|
| A1 | c | https://a2a-protocol.org/latest/specification/ | спецификация канонически под `/latest/` |
| A2 | v | https://github.com/a2aproject/A2A | репозиторий жив (`/releases`) |
| A4 | c | https://modelcontextprotocol.io/specification/2026-07-28/index.md | актуальная ревизия 2026-07-28; `/specification/latest` не индексируется |
| A5 | c | https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization | актуальная ревизия; issuer validation и credential binding сверены с official release notes |
| A6 | c | https://modelcontextprotocol.io/extensions/tasks/overview | в ревизии 2026-07-28 Tasks вынесены из core в официальное extension-пространство |
| A7 | v | https://github.com/modelcontextprotocol/registry | README в репо |
| A8 | v | https://agentcommunicationprotocol.dev/ | хост жив (quickstart/core-concepts) |
| A9 | v | https://github.com/agent-network-protocol/AgentNetworkProtocol | README; старый chgaowei репо ведёт сюда |
| A10 | v | https://arxiv.org/abs/2410.11905 | arXiv листинг + корроборация scirate/HF |
| A11 | v | https://eclipse.dev/lmos/ | точно |
| A13 | v | https://agntcy.org/ | корень подтверждён через agntcy.org/articles |
| A14 | v | https://kagent.dev/ | точно |
| M2 | v | https://cloud.google.com/agentspace/docs | дерево docs живо (create-app) |
| M5 | v | https://learn.microsoft.com/en-us/entra/agent-id/ | локали-варианты видны |
| M6 | c | https://code.claude.com/docs/ | миграция с docs.anthropic.com |
| M8 | c | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html | devguide подтверждён; маркетинговый URL не индексируется |
| M17 | v | https://invariantlabs.ai/blog/mcp-security-notification | точно |
| M18 | v | https://invariantlabs.ai/blog/introducing-mcp-scan | точно |

Не покрыто V2 (остаются u, проверить при сборке реестра): A3, A12, A15, M1, M3, M4, M7, M9–M16.
