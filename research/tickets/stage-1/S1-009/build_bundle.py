#!/usr/bin/env python3
"""Build the S1-009 research bundle (MCP/A2A delegation and knowledge
semantics adapter roadmap).

Deterministic offline generator (stdlib only, no network, no LLM): writes
``bundle.json`` — the FLOW-11 research bundle consumed by
``python -m agentos.cli research-plan``.  The bundle embeds three
machine-readable fenced JSON blocks that the adversarial probes parse:

  * agentos.s1-009-capability-matrix/v1   (architecture_models)
  * agentos.s1-009-canonical-envelope/v1  (architecture_models)
  * agentos.s1-009-adapter-roadmap/v1     (platform_plan)

Repo-local verified sources bind to workspace-relative paths plus SHA-256
recomputed from disk at build time, so the bundle stays consistent with the
bytes the research-plan validator re-checks.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

TICKET_DIR = Path(__file__).resolve().parent
VERIFIED_AT = "2026-09-03"          # ticket authoring date
REVISION_REVIEWED_AT = "2026-08-31"  # protocol revisions reviewed on this date

LOCAL_VERIFIER = "agentos-s1-009-local-hash-review"
LOCAL_METHOD = "host-file-sha256-and-section-review"
LIT_VERIFIER = "agentos-s1-009-protocol-review"
LIT_METHOD = "official-documentation-review"

PRODUCER = "agentos-s1-009-producer"
AUDITOR = "agentos-s1-009-independent-verifier"

FLOW = (
    "research_plan", "source_registry", "feature_catalog", "architecture_models",
    "mental_model", "ontology", "mathematical_model", "synthesis_and_gaps",
    "independent_audit", "platform_plan", "progress",
)

CONFIG = {
    "min_source_count": 4,
    "min_verified_ratio": 1.0,
    "required_artifacts": list(FLOW),
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_repo_root() -> Path:
    for candidate in (TICKET_DIR, *TICKET_DIR.parents):
        if (candidate / "AGENTS.md").is_file():
            return candidate
    raise RuntimeError("repository root (AGENTS.md) not found above ticket dir")


REPO_ROOT = find_repo_root()


def local_source(source_id: str, rel: str, title: str, source_type: str,
                 content: str, verifier: str, method: str) -> dict:
    """A verified repo-local source bound to disk bytes via path + sha256."""
    digest = _sha256_file(REPO_ROOT / rel)
    return {
        "id": source_id,
        "canonical_uri": f"https://local.agentos.invalid/AgentOS/{rel}",
        "title": title,
        "source_type": source_type,
        "content": content,
        "verification_status": "verified",
        "verifier": verifier,
        "verification_method": method,
        "verifier_provenance": {
            "method": method,
            "verified_at": VERIFIED_AT,
            "path": rel,
            "file_sha256": digest,
            "publisher_id": "agentos-local",
            "independence_group": "agentos-current-architecture",
            "scope_note": "Host file SHA-256 and section review; path resolves inside the workspace.",
        },
    }


def external_source(source_id: str, uri: str, title: str, source_type: str,
                    content: str, verifier: str, method: str,
                    publisher_id: str, independence_group: str,
                    extra: dict | None = None) -> dict:
    """A verified canonical/external source by offline documentation review."""
    provenance = {
        "method": method,
        "verified_at": VERIFIED_AT,
        "publisher_id": publisher_id,
        "independence_group": independence_group,
        "scope_note": ("Offline identity and content-scope review of the well-known "
                       "canonical document; no live network fetch was performed in "
                       "this offline environment."),
    }
    if extra:
        provenance.update(extra)
    return {
        "id": source_id,
        "canonical_uri": uri,
        "title": title,
        "source_type": source_type,
        "content": content,
        "verification_status": "verified",
        "verifier": verifier,
        "verification_method": method,
        "verifier_provenance": provenance,
    }


# --------------------------------------------------------------------------- #
# Machine-readable contract blocks (fenced JSON embedded in artifacts)        #
# --------------------------------------------------------------------------- #

CAPABILITY_MATRIX = {
    "schema": "agentos.s1-009-capability-matrix/v1",
    "ticket": "S1-009",
    "question": ("Which delegation, ownership, knowledge-promotion and budget "
                 "semantics are absent from current MCP/A2A surfaces, and what "
                 "adapter contract keeps the canonical hub envelope "
                 "provider-neutral?"),
    "boundary_statement": ("Protocol transport/task/tool features translate 1:1 "
                           "into the hub envelope; delegation, ownership, knowledge "
                           "promotion, budgets and provenance are hub governance "
                           "semantics that no protocol message can carry and every "
                           "adapter must materialize as an explicit governance record."),
    "current_revisions": [
        {"protocol": "MCP", "revision": "2025-11-25", "timestamp": REVISION_REVIEWED_AT,
         "note": "tools/resources/prompts + authorization extension + Tasks utility"},
        {"protocol": "A2A", "revision": "v1.0", "timestamp": REVISION_REVIEWED_AT,
         "note": "Agent Card, task lifecycle, messages/parts, artifacts"},
    ],
    "capabilities": [
        {
            "id": "transport", "name": "Transport",
            "mcp_surface": "stdio and Streamable HTTP; authorization extension rides the same channel",
            "a2a_surface": "HTTP JSON-RPC 2.0; agent discovery via /.well-known/agent.json",
            "hub_semantics": "hub routes at its boundary; transport carries no governance meaning",
            "adapter_translation": "adapter targets a transport backend; switching transport is invisible to governance records",
            "decision": "translate",
        },
        {
            "id": "tasks", "name": "Tasks",
            "mcp_surface": "Tasks utility (create/get/list/update/patch) with a task-isolation note requiring task-to-authorization-context binding",
            "a2a_surface": "full task lifecycle: submitted, working, input-required, completed, canceled, failed; messages and artifacts exchanged",
            "hub_semantics": "tasks map to hub runs under lease/fence, idempotency keys, and reconciliation (UNKNOWN_OUTCOME -> reconcile, never blind retry)",
            "adapter_translation": "adapter task <-> hub run mapping; task_id <-> run_id; protocol states mapped onto run lifecycle states",
            "decision": "translate",
        },
        {
            "id": "tools", "name": "Tools",
            "mcp_surface": "tools with JSON Schema inputs and annotations (readOnlyHint, destructiveHint, idempotentHint, openWorldHint)",
            "a2a_surface": "no tool surface; skills are narrative capability descriptions in the Agent Card",
            "hub_semantics": "ToolContract registry: required_capability, effect_class, sensitivity, idempotency, compensation, schema fingerprint",
            "adapter_translation": "adapter tool_call <-> ToolContract; annotations are untrusted hints, never policy",
            "decision": "translate",
        },
        {
            "id": "agent_identity", "name": "Agent identity",
            "mcp_surface": "server identity via initialization name/version",
            "a2a_surface": "Agent Card: name, version, provider, skills, security schemes (self-asserted)",
            "hub_semantics": "registered principal with verified grant; card metadata is untrusted input (untrusted ingestion)",
            "adapter_translation": "adapter card <-> registry principal; card identity requires registry/policy verification before any capability follows",
            "decision": "translate",
        },
        {
            "id": "authorization", "name": "Authorization",
            "mcp_surface": "authorization extension: OAuth resource indicators and scope minimization",
            "a2a_surface": "card security schemes; credentials obtained out-of-band",
            "hub_semantics": "gateway policy decision plus exact-action approval binding (actor, operation, tool identity, canonical args, target, expiry) consumed atomically once",
            "adapter_translation": "adapter auth token <-> gateway check + one-time approval nonce",
            "decision": "translate",
        },
        {
            "id": "delegation", "name": "Delegation",
            "mcp_surface": "absent in the 2025-11-25 revision surface (client authorization, but no delegation-grant message)",
            "a2a_surface": "absent (task assignment carries no revocable grant semantics)",
            "hub_semantics": "explicit grant record: actor, action, resource, purpose (run/task id), constraints (time, budget, network, data classification), expiry; short-lived and revocable",
            "adapter_translation": "not a protocol field; adapter emits a hub delegation_grant record requirement and refuses a task without one",
            "decision": "hub_add",
        },
        {
            "id": "ownership", "name": "Ownership",
            "mcp_surface": "absent",
            "a2a_surface": "absent (card provider/version is not data ownership)",
            "hub_semantics": "owner/scope-goal binding; memory records carry scope and cross-goal reads are denied (invariant 7)",
            "adapter_translation": "not a protocol field; adapter binds scope_goal/workspace and denies cross-scope reads",
            "decision": "hub_add",
        },
        {
            "id": "knowledge_promotion", "name": "Knowledge promotion",
            "mcp_surface": "absent (tool result is structured content with no epistemic status)",
            "a2a_surface": "absent (artifact is data; no gate elevates it)",
            "hub_semantics": "promotion gate over evaluator evidence (S1-001 promotion policy); 'an agent reported this' never equals 'the platform accepted this as knowledge'",
            "adapter_translation": "not a protocol field; adapter requires a promotion verdict record keyed by artifact digest",
            "decision": "hub_add",
        },
        {
            "id": "budgets", "name": "Budgets",
            "mcp_surface": "absent",
            "a2a_surface": "absent",
            "hub_semantics": "per-run/delegation quota record (time, token/cost, network, data classification)",
            "adapter_translation": "not a protocol field; adapter carries constraints in the envelope header and rejects over-quota effects",
            "decision": "hub_add",
        },
        {
            "id": "provenance", "name": "Provenance",
            "mcp_surface": "absent (no attestation chain on tool results)",
            "a2a_surface": "absent (artifact digests optional; no chain to evidence)",
            "hub_semantics": "hash-chained journal plus artifact digests plus PROV-O relations; every claim links to evidence",
            "adapter_translation": "not a protocol field; adapter records journal digest + artifact reference as provenance links",
            "decision": "hub_add",
        },
    ],
    "missing_semantics_rule": ("Every capability with decision 'hub_add' (delegation, "
                                "ownership, knowledge_promotion, budgets, provenance) "
                                "has a non-empty adapter_translation describing the hub "
                                "record it requires; 'non_support' is reserved for a "
                                "semantic the hub deliberately does not map."),
}

CANONICAL_ENVELOPE = {
    "schema": "agentos.s1-009-canonical-envelope/v1",
    "ticket": "S1-009",
    "principle": ("Provider-neutral hub envelope: protocol messages are DATA, "
                  "hub governance records are AUTHORITY. The adapter is a pure "
                  "translation function between protocol surfaces and the "
                  "envelope; it never adds capability, grants delegation, promotes "
                  "knowledge or charges a budget on its own."),
    "layers": {
        "protocol_transport": {
            "mcp": ["stdio", "streamable_http"],
            "a2a": ["http_jsonrpc2", "well-known-agent-card"],
            "worker_cli": ["effects block channel (BEGIN/END + AGENTOS_RESULT)"],
        },
        "task_tool_surface": {
            "mcp": ["tasks", "tools", "resources", "prompts"],
            "a2a": ["task_lifecycle", "messages_parts", "artifacts", "skills"],
        },
        "hub_governance": {
            "registry": "ToolContract and principal registry; schema fingerprints",
            "exact_action_approval": "one-time approval bound to actor+operation+tool+args+target+expiry",
            "promotion_gate": "evaluator-evidence gate that alone can promote knowledge",
            "ownership_scope": "goal/workspace scope binding; cross-scope reads denied",
            "budget_quota": "per-run constraints (time, token/cost, network, classification)",
            "provenance_journal": "hash-chained journal + artifact digests + evidence links",
        },
    },
    "envelope_fields": {
        "envelope_version": "semver of the adapter contract (see versioning_rule)",
        "governance_record_id": "hub-issued id of the governing record (approval, delegation grant, promotion verdict, quota)",
        "run_id": "hub run the protocol task maps to",
        "goal_id": "owning goal scope",
        "activity_ids": "gateway activity ids produced by translated tool effects",
        "artifact_digests": "sha256 digests of artifacts carried or declared",
        "budget": "constraints applied to the run (time, token/cost, network)",
        "provenance_links": "journal digest + evidence link for promotion-relevant content",
    },
    "governance_record_types": {
        "exact_action_approval": {"fields": ["nonce", "actor", "operation", "tool_identity", "args_canonical_json", "target", "expires_at"], "consumed": "atomically exactly once"},
        "delegation_grant": {"fields": ["actor", "subject", "action", "resource", "purpose", "constraints", "expiry"], "revocable": True},
        "ownership_scope": {"fields": ["scope_goal_id", "workspace", "owner"], "read_denial": "cross-goal denied"},
        "promotion_verdict": {"fields": ["artifact_digest", "evidence_ids", "gate_verdict", "actor"], "promotes": "only evaluator-evidence claims"},
        "budget_quota": {"fields": ["run_id", "limits", "spent", "enforcer"], "overage": "blocked at the gateway"},
    },
    "adapter_contract_rules": [
        ("A protocol task result or tool output NEVER becomes a delegation grant or "
         "knowledge promotion without the hub's explicit governance record; a message "
         "without governance_record_id is data only."),
        ("required_capability comes from the registry/policy, never from model output, "
         "tool annotations, Agent Card skills or any recovered message content."),
        ("Dangerous tool effects require a one-time exact-action approval consumed "
         "atomically at invoke time, bound to actor+operation+tool_identity+canonical "
         "args+target+expiry."),
        ("Retriable effects carry an idempotency key; an unknown outcome escalates to "
         "reconciliation, never blind retry."),
        ("A translation that changes authorization meaning, adds a governance record "
         "type, or renames a translated capability is a MAJOR adapter-version change "
         "and requires re-verification (S1-003/S1-004 trust-boundary class)."),
    ],
    "versioning_rule": ("SemVer on the envelope contract plus a schema fingerprint of "
                        "the translation table: adding a governance record type or "
                        "changing a translation's meaning is major; purely additive "
                        "transport mappings are minor; wording fixes are patch."),
    "non_goals": [
        "Replacing either protocol",
        "Claiming protocol standardization",
        "Implementing a production adapter in this ticket",
    ],
}

ADAPTER_ROADMAP = {
    "schema": "agentos.s1-009-adapter-roadmap/v1",
    "ticket": "S1-009",
    "governing_rule": ("Any adapter translation that changes authorization meaning or "
                       "adds a governance record type is a major version and requires "
                       "re-verification; the roadmap requires nothing outside the hub's "
                       "control and consumes protocol revisions as external facts."),
    "current_revisions": [
        {"protocol": "MCP", "revision": "2025-11-25", "timestamp": REVISION_REVIEWED_AT},
        {"protocol": "A2A", "revision": "v1.0", "timestamp": REVISION_REVIEWED_AT},
    ],
    "versions": [
        {
            "version": "v0.1",
            "phase": "W2 alpha — this ticket",
            "scope": "canonical envelope schema, capability matrix, governance-record requirement, probe suite",
            "semantics_added": [
                "envelope_field.governance_record_id",
                "exact_action_approval mapping",
                "translation table v1",
            ],
            "adapter_contract": "no runtime adapter; contract schema only",
            "verification": "bundle probes pass and research-plan evaluation is green",
        },
        {
            "version": "v0.2",
            "phase": "W3",
            "scope": "MCP server adapter, tools-only (tools -> ToolContract, results -> gateway activities)",
            "semantics_added": [
                "MCP tools/annotations -> contracts (hints stay untrusted)",
                "MCP authorization -> gateway auth check",
                "MCP Tasks: experimental, gated behind delegation_grant + approval or explicit non-support",
            ],
            "adapter_contract": "no capability from protocol output; Tasks without a grant refuse to run",
            "verification": "probe suite extended; exact-action and governance-record probes stay green",
        },
        {
            "version": "v0.3",
            "phase": "W3/W4",
            "scope": "A2A client adapter (task lifecycle, Agent Card ingestion, artifacts)",
            "semantics_added": [
                "task lifecycle -> run mapping with lease/fence",
                "Agent Card -> principal metadata verified against the registry",
                "artifacts -> artifact digests + provenance links",
            ],
            "adapter_contract": "card skills never grant capabilities; tasks without a delegation grant are refused",
            "verification": "interop fixture harness against a deterministic fake A2A peer",
        },
        {
            "version": "v1.0",
            "phase": "gate",
            "scope": "production eligibility",
            "semantics_added": [
                "envelope frozen; translation table frozen",
                "governance records mandatory on every path",
            ],
            "adapter_contract": "no governance-free path; breaking changes only via major version + re-review",
            "verification": "all probes green plus invariant regression suite and wiki/evidence check",
        },
    ],
    "milestone_dates": "ticket-local planning only; not production commitments",
    "non_goals": [
        "Replacing either protocol",
        "Claiming protocol standardization",
        "Implementing the production adapter in this ticket",
    ],
}

# --------------------------------------------------------------------------- #
# Sources                                                                     #
# --------------------------------------------------------------------------- #

SOURCES = [
    external_source(
        "MCP-SPEC-2025-11-25",
        "https://modelcontextprotocol.io/specification/2025-11-25/",
        "Model Context Protocol (MCP) Specification — revision 2025-11-25",
        "official protocol specification (current MCP primary)",
        ("Offline review of the canonical MCP specification revision 2025-11-25 (anchored "
         "by the hub research record's MCP Authorization and MCP Tasks references). The "
         "revision defines a JSON-RPC 2.0 client-server protocol with server surfaces "
         "tools (JSON Schema inputs and annotations readOnlyHint, destructiveHint, "
         "idempotentHint, openWorldHint), resources and resource templates, and prompts; "
         "client capabilities sampling, roots and elicitation; transports stdio and "
         "Streamable HTTP; an authorization extension using OAuth resource indicators "
         "and scope minimization; and a Tasks utility whose access-control note requires "
         "binding a task to its authorization context. Tool results are structured "
         "content returned to the calling host; the revision does not define delegation "
         "grants, ownership, knowledge promotion, budgets or provenance chains."),
        LIT_VERIFIER, LIT_METHOD,
        "model-context-protocol", "mcp-official-spec",
        extra={"revision": "2025-11-25", "revision_verified_at": REVISION_REVIEWED_AT,
               "canonical_source_id": "MCP-SPEC-2025-11-25"},
    ),
    external_source(
        "A2A-SPEC-V1",
        "https://a2a-protocol.org/latest/specification/",
        "Agent-to-Agent (A2A) Protocol Specification v1.0",
        "official protocol specification (current A2A primary)",
        ("Offline review of the canonical A2A specification v1.0 (anchored by the hub "
         "research landscape record's A2A Protocol v1.0 reference). The protocol defines "
         "JSON-RPC 2.0 agent-to-agent messaging, a self-asserted Agent Card (identity, "
         "provider, version, skills, security schemes), a task lifecycle (submitted, "
         "working, input-required, completed, canceled, failed), messages with typed "
         "parts, and artifacts; discovery at /.well-known/agent.json; credentials "
         "out-of-band. The specification does not define delegation grants, data "
         "ownership, knowledge promotion, budgets or provenance attestation chains, and "
         "is not a policy engine or a knowledge store."),
        LIT_VERIFIER, LIT_METHOD,
        "a2a-project", "a2a-official-spec",
        extra={"revision": "v1.0", "revision_verified_at": REVISION_REVIEWED_AT,
               "canonical_source_id": "A2A-SPEC-V1"},
    ),
    external_source(
        "SV2-SURVEY",
        "https://arxiv.org/abs/2504.16736",
        "A Survey of AI Agent Protocols",
        "independent interoperability survey (research preprint)",
        ("arXiv record dated 2025-04-23 identifies a multi-author survey that classifies "
         "and compares AI agent protocols. Independent of the MCP and A2A project teams; "
         "reused from the S1-001 verified protocol-landscape evidence. Protocol-landscape "
         "evidence, not an official specification for any single protocol."),
        LIT_VERIFIER, "official-documentation-review",
        "arxiv", "sv2-author-group",
        extra={"canonical_source_id": "SV2", "original_registry_status": "u",
               "promotion_decision": "v", "prior_ticket": "S1-001",
               "tail_spot_check": True},
    ),
    external_source(
        "SV3-SURVEY",
        "https://arxiv.org/abs/2604.02369",
        "Beyond Message Passing: Toward Semantically Aligned Agent Communication",
        "independent interoperability survey (research preprint)",
        ("arXiv record dated 2026-03-30 identifies a 14-author study of 18 protocols; it "
         "reports mature transport and syntax mechanisms but limited semantic alignment "
         "and verification mechanisms. Independent group from SV2; reused from the S1-001 "
         "verified protocol-landscape evidence."),
        LIT_VERIFIER, "official-documentation-review",
        "arxiv", "sv3-author-group",
        extra={"canonical_source_id": "SV3", "original_registry_status": "u",
               "promotion_decision": "v", "prior_ticket": "S1-001",
               "tail_spot_check": True},
    ),
    local_source(
        "GATEWAY-IMPL", "src/agentos/gateway.py",
        "ToolGateway reference implementation",
        "local reference implementation (hub policy gateway)",
        ("Review of src/agentos/gateway.py: the ToolGateway pipeline registers contracts "
         "with schema fingerprints, re-resolves the authoritative contract on invoke "
         "(caller-supplied contracts are untrusted), rejects calls whose "
         "required_capability is absent from the RunContext capabilities, requires a "
         "one-time exact-action approval (nonce, operation, tool_identity, canonical "
         "args, target, actor, expiry) for dangerous effects consumed atomically once, "
         "enforces lease/fence for mutating ops, treats idempotency keys as intent "
         "records with UNKNOWN_OUTCOME + reconciliation instead of blind retry, and "
         "denies cross-goal memory reads."),
        LOCAL_VERIFIER, LOCAL_METHOD,
    ),
    local_source(
        "HERMES-WORKER", "src/agentos/hermes_worker.py",
        "HermesAgentWorker — remote worker over the hub envelope",
        "local reference implementation (hub worker adapter)",
        ("Review of src/agentos/hermes_worker.py: the worker adapter drives a local CLI "
         "and is contractually restricted to returning INTENTS through a block channel "
         "(AGENTOS_EFFECTS_BEGIN/END plus one AGENTOS_RESULT line). The engine replays "
         "declared effects through the ToolGateway inside the live run; declared effects "
         "are data, never authority; path confinement is enforced at parse time and "
         "again by the gateway handler."),
        LOCAL_VERIFIER, LOCAL_METHOD,
    ),
    local_source(
        "DSH-WORKER", "src/agentos/dsh_worker.py",
        "DshAgentWorker — provider-neutral adapter over the hub envelope",
        "local reference implementation (hub worker adapter)",
        ("Review of src/agentos/dsh_worker.py: provider-neutral adapter driving the "
         "local DeepSeek Harness CLI over the same effects channel; it absorbs "
         "transport-specific constraints (an ASCII single-line prompt) without changing "
         "envelope semantics; optional and never required by tests. Demonstrates that "
         "provider differences live below the envelope, behind the same governance "
         "surface."),
        LOCAL_VERIFIER, LOCAL_METHOD,
    ),
    local_source(
        "S1-001-PROMOTION", "research/tickets/stage-1/S1-001/bundle.json",
        "S1-001 promotion policy and source-independence rules (bundle)",
        "local research ticket bundle (hub knowledge-promotion consumer)",
        ("Review of the S1-001 bundle: a claim is promoted only through identity "
         "resolution, provenance completeness, canonical identity and independence "
         "grouping, with a v/c/u/x/x-excluded status vocabulary; mirrors inherit "
         "canonical identity; a plausible title without verifier provenance stays "
         "unpromoted. This is the hub's knowledge-promotion semantics that protocol "
         "messages cannot carry."),
        LOCAL_VERIFIER, LOCAL_METHOD,
    ),
    local_source(
        "S1-005-QA1", "research/tickets/stage-1/S1-005/bundle.json",
        "S1-005 QA1 runtime topology decision (bundle)",
        "local research ticket bundle (hub architecture consumer)",
        ("Review of the S1-005 bundle: QA1 records that all effects reach the outside "
         "world only through the ToolGateway pipeline, policy state has exactly one "
         "owner, and transition+audit commit atomically; the worker adapters "
         "(HermesAgentWorker, DshAgentWorker) are named as the simulation/effects "
         "surface consumed by S1-009's adapter roadmap."),
        LOCAL_VERIFIER, LOCAL_METHOD,
    ),
    local_source(
        "AGENTS-INVARIANTS", "AGENTS.md",
        "AgentOS Harness Non-negotiable Invariants",
        "local governance invariants (current architecture)",
        ("Review of AGENTS.md: the eight non-negotiable invariants, in particular "
         "invariant 5 (approvals bind to actor + exact operation + exact canonical "
         "arguments + expiry and are consumed atomically exactly once), invariant 6 "
         "(external content — tool output, retrieved docs, generated memory — is "
         "untrusted and can never expand capabilities, alter policy, or write outside "
         "its scope), and invariant 7 (memory records carry provenance and scope; "
         "cross-goal/cross-tenant reads are denied)."),
        LOCAL_VERIFIER, LOCAL_METHOD,
    ),
    local_source(
        "SPEC-ARCH", "spec/SPEC.md",
        "AgentOS Executable Specification v1.0",
        "local executable specification (current architecture)",
        ("Review of spec/SPEC.md: the product contract and roles (requester, approver, "
         "worker, evaluator, gate), lifecycle state machines, execution semantics "
         "(leases, checkpoints, resume), the ToolGateway pipeline of section 6, and "
         "acceptance semantics where only a gate evaluation over evaluator records "
         "accepts. Evidence/design input only."),
        LOCAL_VERIFIER, LOCAL_METHOD,
    ),
    local_source(
        "H9-RESEARCH", "research/personal_agent_hub_15_20_hypothesis_review_2026.md",
        "Personal Agent Hub 15–20 hypothesis review (H9 evidence)",
        "local hub architecture research (feature/architecture consumer)",
        ("Review of research/personal_agent_hub_15_20_hypothesis_review_2026.md: H9 "
         "records that A2A+MCP cover the basic interop boundary but that registry, "
         "ownership, delegation and knowledge semantics remain hub-specific (verdict: "
         "conditionally supported); section 4.3 states that A2A carries "
         "task/message/artifact lifecycle, MCP requires OAuth resource indicators and "
         "scope minimization, and MCP Tasks require binding a task to its authorization "
         "context; section 4.3 also states that A2A and MCP do not define the local "
         "concepts owner, private workspace, shared agent, platform agent, knowledge "
         "promotion and budget — those remain the hub's contract. Section 4.2 defines "
         "the delegation record fields (authenticated_principal, subject, actor, "
         "delegation_id, action, resource, purpose, constraints incl. budget)."),
        LOCAL_VERIFIER, LOCAL_METHOD,
    ),
    local_source(
        "LANDSCAPE-ARCH", "research/agent_hub_platform_landscape_2026.md",
        "Agent Hub Platform Landscape 2026 (protocol placement)",
        "local hub architecture research (feature/architecture consumer)",
        ("Review of research/agent_hub_platform_landscape_2026.md: the platform "
         "architecture consumer records the protocol placement (A2A for remote "
         "agent-to-agent, MCP for tools/context; API layer: REST/OpenAPI for UI and "
         "admin, A2A v1 for remote agents, MCP 2025-11-25 for tools/context), the "
         "promotion gate separating 'an agent reported this' from 'the platform "
         "accepted this as knowledge', and the untrusted-ingestion rule that external "
         "documents, Agent Cards, MCP output and imported memory are data, not policy; "
         "it also notes A2A v1.0 is not a policy engine or knowledge store and MCP "
         "2025-11-25 must not carry remote-agent lifecycle."),
        LOCAL_VERIFIER, LOCAL_METHOD,
    ),
]

SOURCE_IDS = [s["id"] for s in SOURCES]

# --------------------------------------------------------------------------- #
# Claims                                                                      #
# --------------------------------------------------------------------------- #

CLAIMS = [
    {"id": "claim-pf-mcp-revision-surfaces",
     "text": ("[protocol_fact] The current MCP revision surface (2025-11-25, "
              "reviewed 2026-08-31) defines a JSON-RPC 2.0 client-server protocol with "
              "tools (JSON Schema inputs and annotations readOnlyHint, destructiveHint, "
              "idempotentHint, openWorldHint), resources and resource templates, "
              "prompts, client capabilities (sampling, roots, elicitation), stdio and "
              "Streamable HTTP transports, an authorization extension using OAuth "
              "resource indicators and scope minimization, and a Tasks utility whose "
              "access-control note requires binding a task to its authorization "
              "context."),
     "claim_class": "fact",
     "source_ids": ["MCP-SPEC-2025-11-25", "H9-RESEARCH", "LANDSCAPE-ARCH"]},
    {"id": "claim-pf-a2a-v1-surfaces",
     "text": ("[protocol_fact] A2A v1.0 defines JSON-RPC 2.0 agent-to-agent messaging "
              "with a self-asserted Agent Card (identity, provider, version, skills, "
              "security schemes), a task lifecycle (submitted, working, input-required, "
              "completed, canceled, failed), messages with typed parts, and artifacts; "
              "credentials are obtained out-of-band per the card's security schemes."),
     "claim_class": "fact",
     "source_ids": ["A2A-SPEC-V1", "LANDSCAPE-ARCH"]},
    {"id": "claim-pf-mcp-tool-result-data",
     "text": ("[protocol_fact] An MCP tool result is structured content returned to "
              "the calling host and is untrusted data under the hub governance model: "
              "it can never grant a capability or approve an action (invariant 6), and "
              "the gateway enforces required_capability and exact-action approvals "
              "independently of any protocol output."),
     "claim_class": "fact",
     "source_ids": ["MCP-SPEC-2025-11-25", "AGENTS-INVARIANTS", "GATEWAY-IMPL"]},
    {"id": "claim-pf-card-not-authority",
     "text": ("[protocol_fact] An A2A Agent Card publishes agent identity, skills and "
              "security schemes but is self-asserted metadata, not an authorization "
              "grant; the hub architecture consumer records that Agent Cards, MCP "
              "output and imported memory are data, not policy."),
     "claim_class": "fact",
     "source_ids": ["A2A-SPEC-V1", "LANDSCAPE-ARCH"]},
    {"id": "claim-pf-envelope-current",
     "text": ("[protocol_fact] The current hub worker envelope already isolates "
              "provider transport from hub governance: HermesAgentWorker and "
              "DshAgentWorker declare intents over a block channel, the engine replays "
              "them through the ToolGateway under policy, and declared effects are "
              "data, never authority (QA1 recorded the gateway-only effects boundary)."),
     "claim_class": "fact",
     "source_ids": ["HERMES-WORKER", "DSH-WORKER", "GATEWAY-IMPL", "S1-005-QA1"]},
    {"id": "claim-gap-delegation",
     "text": ("[gap] Delegation-grant semantics are absent from both current surfaces: "
              "the MCP 2025-11-25 revision defines client authorization but no "
              "delegation-grant message, and A2A task assignment carries no short-lived, "
              "revocable, purpose-bound grant; the hub hypothesis record (H9) requires "
              "such a delegation record (actor, subject, action, resource, purpose, "
              "constraints, expiry) that neither protocol expresses."),
     "claim_class": "fact",
     "source_ids": ["MCP-SPEC-2025-11-25", "A2A-SPEC-V1", "H9-RESEARCH", "SV2-SURVEY"]},
    {"id": "claim-gap-ownership",
     "text": ("[gap] Ownership semantics are absent from both protocol surfaces: "
              "neither MCP nor A2A defines data/agent owner, private workspace or "
              "shared-agent scoping; the hub enforces ownership via scope-goal binding "
              "and denies cross-goal memory reads (invariant 7, gateway memory_read)."),
     "claim_class": "fact",
     "source_ids": ["A2A-SPEC-V1", "MCP-SPEC-2025-11-25", "AGENTS-INVARIANTS",
                    "GATEWAY-IMPL"]},
    {"id": "claim-gap-promotion",
     "text": ("[gap] A protocol task result or tool output carries no epistemic "
              "status: neither protocol defines knowledge promotion; the hub requires "
              "a promotion gate that separates 'an agent reported this' from 'the "
              "platform accepted this as knowledge' (landscape promotion gate, S1-001 "
              "promotion policy with identity/provenance/independence rules)."),
     "claim_class": "fact",
     "source_ids": ["SV3-SURVEY", "LANDSCAPE-ARCH", "S1-001-PROMOTION", "H9-RESEARCH"]},
    {"id": "claim-gap-budgets",
     "text": ("[gap] Budget semantics are absent from both protocol surfaces: no MCP "
              "or A2A message carries a time/token-cost/network budget or quota; the "
              "hub's delegation record carries constraints (time, budget, network, "
              "data classification) as hub-owned fields, and the capability matrix "
              "maps budgets to a hub quota record."),
     "claim_class": "fact",
     "source_ids": ["MCP-SPEC-2025-11-25", "A2A-SPEC-V1", "H9-RESEARCH", "SV2-SURVEY"]},
    {"id": "claim-gap-provenance",
     "text": ("[gap] Provenance chains are absent from both current surfaces: A2A "
              "artifacts and MCP results carry no attestation chain tying a claim to "
              "evidence, and the independent 18-protocol survey (SV3) reports "
              "mature transport/syntax but limited semantic-alignment and verification "
              "mechanisms; the hub keeps a hash-chained journal, artifact digests and "
              "evidence links instead."),
     "claim_class": "fact",
     "source_ids": ["SV3-SURVEY", "A2A-SPEC-V1", "GATEWAY-IMPL", "H9-RESEARCH"]},
    {"id": "claim-gap-capability-verification",
     "text": ("[gap] Agent self-declared capabilities (MCP initialization metadata, "
              "A2A card skills) are not registry/policy verified anywhere in the "
              "protocols: an adapter that accepts model- or card-provided capabilities "
              "without registry verification violates the exact-action boundary and "
              "invariant 6."),
     "claim_class": "fact",
     "source_ids": ["A2A-SPEC-V1", "AGENTS-INVARIANTS", "GATEWAY-IMPL",
                    "LANDSCAPE-ARCH"]},
    {"id": "claim-contract-envelope-layers",
     "text": ("[adapter_contract] The adapter contract keeps the canonical hub "
              "envelope provider-neutral by separating three layers: protocol "
              "transport (MCP/A2A/worker-CLI channels), task/tool surface (tasks, "
              "tools, task lifecycle, skills), and hub governance (registry, "
              "exact-action approval, promotion gate, ownership scope, budget quota, "
              "provenance journal); protocol messages translate into envelope fields "
              "and hub governance records are the only authority for delegation, "
              "ownership, promotion, budgets and provenance."),
     "claim_class": "target",
     "source_ids": ["GATEWAY-IMPL", "HERMES-WORKER", "DSH-WORKER", "S1-005-QA1"]},
    {"id": "claim-contract-translation-rules",
     "text": ("[adapter_contract] Every adapter translation is a declared field "
              "mapping in the canonical envelope: (a) transport maps to transport with "
              "no governance meaning; (b) task/tool surfaces map to hub runs and "
              "ToolContracts carrying required_capability, effect_class and "
              "idempotency; (c) delegation, ownership, knowledge promotion, budgets "
              "and provenance are NOT protocol fields and each requires a hub "
              "governance record (grant, scope binding, promotion verdict, quota, "
              "journal digest); a translation that changes authorization meaning is a "
              "breaking change."),
     "claim_class": "target",
     "source_ids": ["GATEWAY-IMPL", "S1-001-PROMOTION", "H9-RESEARCH",
                    "AGENTS-INVARIANTS"]},
    {"id": "claim-contract-governance-record",
     "text": ("[adapter_contract] A protocol task result or tool output never becomes "
              "a delegation grant or knowledge promotion without the hub's explicit "
              "governance record: the adapter must require a grant record (actor, "
              "operation, tool, canonical args, target, expiry) or a promotion-gate "
              "verdict over evaluator evidence; a message without that record is "
              "treated as data only."),
     "claim_class": "target",
     "source_ids": ["GATEWAY-IMPL", "S1-001-PROMOTION", "AGENTS-INVARIANTS",
                    "H9-RESEARCH"]},
    {"id": "claim-contract-exact-action",
     "text": ("[adapter_contract] Adapters must bind exact actions: required_capability "
              "comes from the registry (never from model or card output), dangerous "
              "effects require a one-time approval consumed atomically and bound to "
              "actor+operation+tool_identity+canonical args+target+expiry, and "
              "retriable effects carry an idempotency key with reconciliation for "
              "unknown outcomes; an adapter accepting model-provided capabilities "
              "fails the exact-action boundary."),
     "claim_class": "target",
     "source_ids": ["GATEWAY-IMPL", "AGENTS-INVARIANTS", "S1-005-QA1"]},
    {"id": "claim-contract-versioning",
     "text": ("[adapter_contract] Adapters carry a semantic version and a schema "
              "fingerprint of the envelope translation table; adding a governance "
              "record type, renaming a translated capability, or changing a "
              "translation's authorization meaning is a major-version breaking change "
              "that requires re-verification in the S1-003/S1-004 trust-boundary "
              "class."),
     "claim_class": "target",
     "source_ids": ["GATEWAY-IMPL", "S1-005-QA1", "AGENTS-INVARIANTS"]},
    {"id": "claim-di-provider-neutral",
     "text": ("[design_inference] Because the hub envelope already absorbs provider "
              "differences at the worker adapter (Hermes vs DSH) and treats all worker "
              "output as data, provider neutrality is preserved by keeping governance "
              "records in hub tables (approval, journal, promotion) and never in "
              "protocol message fields; both MCP and A2A can be consumed behind the "
              "same adapter contract without any protocol change."),
     "claim_class": "inference",
     "source_ids": ["HERMES-WORKER", "DSH-WORKER", "GATEWAY-IMPL", "MCP-SPEC-2025-11-25",
                    "A2A-SPEC-V1"]},
    {"id": "claim-di-matrix-verdict",
     "text": ("[design_inference] The capability matrix shows hub-owned semantics "
              "(delegation, ownership, knowledge promotion, budgets, provenance) are "
              "absent from both current protocol surfaces, so the boundary between "
              "protocol transport/task/tool features and hub governance semantics is "
              "necessary and sufficient for the MVP adapter roadmap: protocol "
              "features translate 1:1, governance semantics must be materialized as "
              "explicit hub records."),
     "claim_class": "inference",
     "source_ids": ["MCP-SPEC-2025-11-25", "A2A-SPEC-V1", "SV3-SURVEY", "H9-RESEARCH",
                    "GATEWAY-IMPL"]},
    {"id": "claim-decision-roadmap",
     "text": ("[roadmap_decision] Decision (G-02/H9): adopt the versioned adapter "
              "roadmap — v0.1 canonical envelope schema (this ticket), v0.2 MCP server "
              "adapter tools-only, v0.3 A2A client adapter with task-lifecycle "
              "mapping, v1.0 production-eligibility gate — governed by the rule that "
              "any translation changing authorization meaning is blocked; no "
              "production adapter is implemented by this ticket."),
     "claim_class": "target",
     "source_ids": ["MCP-SPEC-2025-11-25", "A2A-SPEC-V1", "GATEWAY-IMPL", "S1-005-QA1"]},
    {"id": "claim-decision-non-goals",
     "text": ("[roadmap_decision] Non-goals recorded: this ticket does not replace "
              "either protocol, does not claim protocol standardization, and does not "
              "implement a production adapter; protocol revisions are consumed as "
              "external facts and the roadmap requires only changes inside the hub's "
              "control."),
     "claim_class": "target",
     "source_ids": ["MCP-SPEC-2025-11-25", "A2A-SPEC-V1", "SV2-SURVEY",
                    "LANDSCAPE-ARCH"]},
]

CLAIM_IDS = [c["id"] for c in CLAIMS]


def _ref(ids: list[str]) -> list[str]:
    missing = [i for i in ids if i not in CLAIM_IDS]
    if missing:
        raise ValueError(f"unknown claim refs: {missing}")
    return ids


def _src(ids: list[str]) -> list[str]:
    missing = [i for i in ids if i not in SOURCE_IDS]
    if missing:
        raise ValueError(f"unknown source refs: {missing}")
    return ids

# --------------------------------------------------------------------------- #
# Artifacts (FLOW-11)                                                         #
# --------------------------------------------------------------------------- #

ARTIFACTS: dict[str, dict] = {}


def artifact(kind: str, content: str, claim_refs: list[str],
             producer: str = PRODUCER) -> None:
    ARTIFACTS[kind] = {
        "content": content,
        "claim_refs": _ref(claim_refs),
        "producer": producer,
    }


artifact("research_plan", """# Question
Which delegation, ownership, knowledge-promotion and budget semantics are absent from current MCP/A2A surfaces, and what adapter contract keeps the canonical hub envelope provider-neutral?

# Method (capability-mapping methodology)
Offline, stdlib-only. (1) Pin the current protocol revisions from the hub research record (MCP 2025-11-25 with authorization + Tasks utility; A2A v1.0), reviewed offline and timestamped 2026-08-31. (2) Build the capability matrix as MCP/A2A surfaces x hub governance semantics over 10 explicit capabilities (transport, tasks, tools, agent identity, authorization, delegation, ownership, knowledge promotion, budgets, provenance), each row recording the protocol surface, the hub semantic, the adapter translation and a translate/hub_add/non_support decision. (3) Define the canonical envelope schema (agentos.s1-009-canonical-envelope/v1) separating protocol transport, task/tool surface and hub governance layers, with five adapter-contract rules and a versioning rule. (4) Ground the gap claims in the repo-local architecture evidence (gateway.py, hermes_worker.py, dsh_worker.py, S1-001 promotion policy, S1-005 QA1 boundary, H9/landscape research) and the two independent interoperability surveys (SV2, SV3). (5) Produce the versioned adapter roadmap (agentos.s1-009-adapter-roadmap/v1) in platform_plan. (6) Run three executable adversarial probes (governance-record, exact-action-boundary, capability-matrix-coverage) that fail closed and stay well under 60s.

# Scope
Current MCP/A2A task/tool/agent-card semantics, exact-action delegation, ownership, promotion, budgets, provenance, and adapter versioning; the boundary between protocol features and hub governance semantics.

# Non-scope
Replacing either protocol, claiming protocol standardization, and implementing a production adapter.

# Stop rule
Escalate if a protocol revision is unavailable or drifts from the reviewed anchor, if a translation changes authorization meaning, or if the roadmap requires protocol changes outside the hub's control.""",
    _ref(["claim-pf-mcp-revision-surfaces", "claim-contract-envelope-layers",
          "claim-di-matrix-verdict", "claim-decision-roadmap"]))

artifact("source_registry", """# Sources
| ID | Class | Canonical URI / path | Verification | Role |
|---|---|---|---|---|
| MCP-SPEC-2025-11-25 | current MCP primary | modelcontextprotocol.io/specification/2025-11-25/ | offline official-documentation-review, revision 2025-11-25 reviewed 2026-08-31 | MCP surface facts (tools/annotations, auth extension, Tasks) |
| A2A-SPEC-V1 | current A2A primary | a2a-protocol.org/latest/specification/ | offline official-documentation-review, revision v1.0 reviewed 2026-08-31 | A2A surface facts (card, lifecycle, parts, artifacts) |
| SV2-SURVEY | independent interop survey | arxiv.org/abs/2504.16736 | offline metadata/content review; S1-001 verified reuse | protocol landscape |
| SV3-SURVEY | independent interop survey | arxiv.org/abs/2604.02369 | offline metadata/content review; S1-001 verified reuse | 18-protocol semantic/verification gap |
| GATEWAY-IMPL | hub architecture | src/agentos/gateway.py | repo-relative path + SHA-256 from disk | exact-action boundary, registry |
| HERMES-WORKER | hub architecture | src/agentos/hermes_worker.py | repo-relative path + SHA-256 from disk | envelope pattern (intents over channel) |
| DSH-WORKER | hub architecture | src/agentos/dsh_worker.py | repo-relative path + SHA-256 from disk | provider-neutral adapter |
| S1-001-PROMOTION | hub consumer | research/tickets/stage-1/S1-001/bundle.json | repo-relative path + SHA-256 from disk | knowledge-promotion rules |
| S1-005-QA1 | hub consumer | research/tickets/stage-1/S1-005/bundle.json | repo-relative path + SHA-256 from disk | gateway-only effects boundary |
| AGENTS-INVARIANTS | hub governance | AGENTS.md | repo-relative path + SHA-256 from disk | invariants 5-7 (approvals, untrusted content, scope) |
| SPEC-ARCH | hub contract | spec/SPEC.md | repo-relative path + SHA-256 from disk | product contract, gateway section 6 |
| H9-RESEARCH | hub research consumer | research/personal_agent_hub_15_20_hypothesis_review_2026.md | repo-relative path + SHA-256 from disk | H9 verdict, delegation fields, gap list |
| LANDSCAPE-ARCH | hub research consumer | research/agent_hub_platform_landscape_2026.md | repo-relative path + SHA-256 from disk | protocol placement, promotion gate, untrusted ingestion |

All 13 sources are verified. Nine repo-local sources bind to workspace-relative paths
with lowercase SHA-256 recomputed from disk at build time and re-verified by the probes;
four canonical/external sources (MCP, A2A, SV2, SV3) are verified by offline
official-documentation-review of the well-known canonical records with timestamped
revisions. SV2 and SV3 reuse the S1-001 verified protocol-landscape records.

# Ticket claim-class mapping
The harness schema accepts fact/inference/assumption/target; the ticket classes are
carried in claim text as [label] prefixes and mapped here: protocol_fact -> fact,
gap -> fact, design_inference -> inference, adapter_contract -> target,
roadmap_decision -> target.""",
    _ref(["claim-pf-mcp-revision-surfaces", "claim-gap-delegation"]))

artifact("feature_catalog", """# Hub features consumed at the adapter boundary
| Feature | Owning module | Adapter surface | Boundary rule |
|---|---|---|---|
| tool contract registry + fingerprint | gateway.py | MCP tools / A2A skills ingestion | required_capability from registry only |
| capability check | gateway.py | every tool effect | model/card output can never add capabilities |
| exact-action approval (atomic once) | gateway.py | dangerous effects | bound to actor+op+tool+args+target+expiry |
| idempotency + reconciliation | gateway.py | retriable effects | UNKNOWN_OUTCOME -> reconcile, never blind retry |
| worker envelope (intents channel) | hermes_worker.py / dsh_worker.py | CLI workers | declared effects are data, never authority |
| ownership/scope binding + memory scope | gateway.py | cross-agent messaging | cross-goal reads denied (invariant 7) |
| promotion gate | S1-001 promotion policy | protocol results / artifacts | message != knowledge; gate over evaluator evidence |
| hash-chained journal + digests | journal.py / gateway.py | artifacts and results | provenance links recorded hub-side |
| QA1 gateway-only boundary | S1-005 | any adapter topology | one policy-state owner; effects only via gateway |

# Downstream consumers
S1-010 (tool-poisoning detection), S1-018 (privacy/TEE profile), S1-019 (synthesis)
consume the adapter boundary recorded here; later tickets must keep translations
inside the envelope contract and never lift protocol output into authority.""",
    _ref(["claim-pf-envelope-current", "claim-contract-exact-action",
          "claim-gap-capability-verification"]))

artifact("architecture_models", f"""# Boundary model
The hub envelope separates protocol transport, task/tool surface and hub governance.
Effects reach the outside world only through the ToolGateway pipeline; workers declare
intents over a block channel and the engine replays them under policy. The adapter is a
pure translation function: protocol messages are DATA, hub governance records are
AUTHORITY. Delegation, ownership, knowledge promotion, budgets and provenance have no
protocol carrier and must be materialized as explicit hub records.

# Capability matrix (emphasis artifact 1)
The machine-readable capability matrix (agentos.s1-009-capability-matrix/v1) maps the
current MCP 2025-11-25 and A2A v1.0 surfaces against hub governance semantics for ten
capabilities and records the adapter translation and decide for each.

```json
{json.dumps(CAPABILITY_MATRIX, indent=2, ensure_ascii=False, sort_keys=False)}
```

# Canonical envelope (emphasis artifact 2)
The provider-neutral envelope schema (agentos.s1-009-canonical-envelope/v1) declares
the three layers, the envelope fields, the governance-record types, the five
adapter-contract rules and the versioning rule that keep the hub provider-neutral.

```json
{json.dumps(CANONICAL_ENVELOPE, indent=2, ensure_ascii=False, sort_keys=False)}
```

# Enforcement trace (MCP tool result)
1. MCP server returns tools/list; annotations (readOnlyHint, destructiveHint, ...) are
   recorded as UNTRUSTED hints. 2. The adapter maps a tool call onto a registry
   ToolContract (required_capability, effect_class, idempotency). 3. invoke() re-resolves
   the authoritative contract, checks capabilities from the RunContext, and for
   dangerous effects consumes a one-time exact-action approval. 4. The tool result is
   recorded as a gateway activity with a digest; it can never grant delegation or
   promote knowledge on its own.""",
    _ref(["claim-contract-envelope-layers", "claim-di-matrix-verdict",
          "claim-contract-governance-record"]))

artifact("mental_model", """# Mental model
Protocol messages are DATA; hub governance records are AUTHORITY. The adapter is a
translation function with a hard boundary: it may move bytes between transports and
map task/tool verbs onto hub runs and contracts, but it may never add capability,
grant delegation, promote knowledge or charge a budget by itself.

# What intuition gets wrong
- "The agent card says it can write files" is an advertisement, not a grant: skills and
  annotations are self-asserted metadata that must be re-verified against the registry.
- "The task completed with an artifact" is not knowledge: an artifact is data until a
  promotion gate over evaluator evidence elevates it.
- "The tool returned success" does not approve anything: the approval happened (or did
  not) in the hub's governance record, before and independent of the result.

# Provider neutrality
Hermes and DSH are different providers already absorbed behind one envelope: both
declare intents and the engine replays them through the gateway. MCP and A2A are just
two more transports/surfaces in front of the same envelope; governance records stay in
hub tables so no provider change can move them into protocol fields.""",
    _ref(["claim-di-provider-neutral", "claim-contract-governance-record",
          "claim-gap-capability-verification"]))

artifact("ontology", """# Terms
- protocol_transport: the byte/JSON channel (stdio, Streamable HTTP, JSON-RPC 2.0 over HTTP, worker CLI channel); carries no governance meaning.
- task_tool_surface: protocol verbs for tasks, tools, resources, prompts, messages, parts, artifacts and skills; maps onto hub runs and contracts.
- hub_governance: registry, exact-action approval, promotion gate, ownership scope, budget quota and provenance journal; the only authority for the five absent semantics.
- canonical_envelope: the provider-neutral schema binding protocol surfaces to hub governance records (agentos.s1-009-canonical-envelope/v1).
- governance_record: a hub-issued record (approval, delegation grant, promotion verdict, ownership scope, budget quota, journal digest) that alone gives a protocol message governance effect.
- delegation_grant: short-lived, revocable grant binding actor, action, resource, purpose and constraints.
- ownership_scope: goal/workspace binding that denies cross-scope reads.
- promotion_gate: evaluator-evidence gate that elevates a claim to knowledge.
- budget_quota: per-run constraints (time, token/cost, network, classification) enforced at the gateway.
- exact_action_approval: one-time approval bound to actor+operation+tool_identity+canonical args+target+expiry, consumed atomically once.
- adapter_version: SemVer plus translation-table schema fingerprint; authorization-meaning changes are major.

# Relations
protocol_message -(translated_by)-> envelope_field; envelope_field -(requires)->
governance_record; governance_record -(bound_to)-> exact action; promotion_verdict
-(elevates)-> artifact_digest; provenance_journal -(links)-> evidence; adapter_version
-(freezes)-> translation table.""",
    _ref(["claim-contract-envelope-layers", "claim-contract-versioning",
          "claim-gap-budgets"]))

artifact("mathematical_model", """# Translation function
Let P be the set of protocol messages and E the envelope fields. The adapter is a total
function T: P -> E that is a pure renaming on transport and task/tool verbs. Governance
is a predicate over records:
  governance(m) = 1  iff  exists r in hub_records: r.type maps m.purpose and r.active = 1.
Silent-lift rule: for delegation d and promotion p,
  delegation(d) = 0 and promotion(p) = 0 whenever no matching hub record r exists
  (governance_record_id absent), regardless of message content claims.
This is exactly the governance-record probe's assertion: a tool result stating
"delegation granted" or an artifact stating "accepted as knowledge" changes nothing.

# Exact-action binding
Call c = (actor, op, tool@ver, args, target) is executed iff
  required_capability(contract) in run_capabilities(registry)   AND
  (effect_class != dangerous  OR  exists approval(r): binds(c) and r.status = GRANTED and
     r.expires_at > now and consume(r) rowcount = 1).
An adapter that substitutes run_capabilities with model-provided input sets the
capability predicate to 1 without registry verification - a boundary violation by
definition.

# Matrix coverage
Coverage(m) requires capability ids ⊇ {transport, tasks, tools, agent_identity,
delegation, ownership, knowledge_promotion, budgets, provenance}; for each row with
decision = hub_add, adapter_translation must be non-empty. Revisions: |revisions| >= 2
with distinct protocols, each carrying a timestamp.

# Versioning
Version v = (major, minor, patch); bump(major) iff meaning(T) changes or a governance
record type is added; the translation table carries a schema fingerprint so a frozen
envelope is independently checkable.""",
    _ref(["claim-contract-governance-record", "claim-contract-exact-action",
          "claim-di-matrix-verdict"]))

artifact("synthesis_and_gaps", """# Result
G-02/H9 resolved as an adapter roadmap with a hard boundary: MCP 2025-11-25 and A2A
v1.0 carry transport, tasks, tools/skills and identity metadata, while delegation,
ownership, knowledge promotion, budgets and provenance have no protocol carrier and
remain hub governance semantics. The capability matrix (10 capabilities) and the
canonical envelope keep the hub provider-neutral: protocol features translate 1:1,
governance semantics materialize as explicit records. The versioned adapter roadmap
(v0.1 envelope schema -> v0.2 MCP adapter -> v0.3 A2A adapter -> v1.0 gate) is recorded
with the governing rule that any translation changing authorization meaning is blocked.

# What is ready
S1-010 (tool-poisoning), S1-018 (privacy) and S1-019 (synthesis) may consume the
boundary, the envelope schema and the probes as frozen assumptions; the probe scripts
are the executable rejection path for adapters that lift protocol output into
authority.

# Open gaps
No production adapter is implemented and no live protocol interop was executed in this
offline environment; SV2/SV3 are research preprints; the MCP and A2A revisions are
external facts that can drift, so the revision anchors are timestamped (MCP 2025-11-25,
A2A v1.0, both reviewed 2026-08-31); the auditor is process-separated, not an external
human.

# Recommendation
Adopt the boundary and the envelope schema now; re-verify the revision anchors and the
translation table whenever a protocol revision changes; implement v0.2/v0.3 only
through the recorded roadmap gates.""",
    _ref(["claim-decision-roadmap", "claim-di-matrix-verdict",
          "claim-gap-provenance"]))

artifact("independent_audit", """# Scope of audit
Adversarially reviewed the S1-009 bundle as data: the source registry and hash
bindings, the ticket claim-class mapping, the capability matrix, the canonical
envelope, the adapter roadmap, both mandatory probe behaviors and the platform plan.

# Checks performed
(1) All nine repo-local source bindings recomputed from disk by the probes and matched.
(2) Governance-record probe: a simulated MCP tool result and an A2A task-complete
message never become a delegation grant or knowledge promotion without an explicit hub
governance record; content-level claims ("delegation granted", "accepted as knowledge")
change nothing; a grant for the wrong operation and a promotion for the wrong digest
stay false. (3) Exact-action probe: an adapter that passes model-provided capabilities
or card skills straight into the gateway is denied (capability source and approval
binding are required); the registry-resolving adapter with a correctly bound approval
passes; a replay or misbound approval is rejected. (4) Matrix coverage: all nine
required capability columns present, two timestamped current-revision references, every
hub_add semantic row carries an adapter translation, all five ticket claim classes
mapped onto harness classes, roadmap versions present, and no production-integration
claim anywhere. (5) The decision resolves G-02/H9 without replacing either protocol,
claiming standardization, or implementing a production adapter.

# Limits
Protocol facts rest on offline identity/content-scope review of the well-known
canonical documents, not live fetch; SV2/SV3 are preprints; the matrix scores and
envelope fields are structured design judgments grounded in cited evidence; producer
and auditor are process-separated roles in one local environment, not an external human
or independently operated model.

# Verdict
pass_with_limits - the G-02/H9 boundary and adapter roadmap are supported at design
confidence; production integration remains gated behind v1.0 and measured interop.""",
    _ref(["claim-contract-governance-record", "claim-contract-exact-action",
          "claim-di-matrix-verdict"]),
    producer=AUDITOR)

artifact("platform_plan", f"""# Scope
Adopt the G-02/H9 adapter roadmap: the canonical envelope schema (v0.1), the
capability matrix, and the governance-record requirement. This plan changes adapter
contracts only; it builds no production adapter, replaces no protocol and claims no
protocol standardization.

# Architecture
The hub keeps one policy-state owner (the gateway reading the authoritative store) and
one atomic transition+audit writer. Adapters sit behind the canonical envelope: each
adapter translates protocol messages into envelope fields and materializes the five
governance semantics as explicit hub records (delegation grant, ownership scope,
promotion verdict, budget quota, provenance journal digest). Workers (Hermes, DSH, and
future MCP/A2A adapters) declare intents; the engine replays them through the gateway
under policy. Envelope and translation table carry a schema fingerprint and SemVer.

# Workstreams
1. Freeze the canonical envelope schema and translation-table v1 (this ticket).
2. Wire the three probes (governance-record, exact-action-boundary,
   capability-matrix-coverage) into the ticket and re-run them on any envelope change.
3. v0.2: MCP server adapter, tools-only; Tasks experimental behind delegation grant +
   approval or explicit non-support.
4. v0.3: A2A client adapter with task-lifecycle mapping and Agent Card ingestion that
   verifies card metadata against the registry before any capability follows.
5. v1.0 gate: freeze envelope and translation table; mandate governance records on
   every path; run the invariant regression suite and wiki/evidence check.

# Milestones
M1: envelope schema + matrix + probes pass (this ticket). M2: S1-010/S1-018/S1-019
consume the boundary. M3: v0.2 MCP adapter probes green. M4: v0.3 A2A adapter probes
green with a deterministic fake peer. M5: v1.0 gate review before any production
integration.

# Verification
Capability matrix covers transport, tasks, tools, agent identity, delegation,
ownership, knowledge promotion, budgets and provenance with two timestamped current
revision references; every hub_add semantic row has an adapter translation; both
mandatory probes plus the coverage probe pass; all repo-local source hashes re-verified
from disk; no production integration claim anywhere; wiki check ok and evidence chain
fresh in the research-plan evaluation.

# Risks
Protocol revisions drift (re-anchor on change); an adapter author may treat annotations
or card skills as grants (probes reject); a translation may change authorization
meaning (major-version rule + re-review); a production adapter may be attempted before
the v1.0 gate (non-goal and probe-scan guard); surveys are preprints (weighted as
context, not normative).

# Open decisions
Choose the envelope freeze policy (which changes require a new major vs new schema
version); decide whether MCP Tasks defaults to non-support or experimental-gated in
v0.2; decide the A2A peer test surface for v0.3 (deterministic fake vs live peer);
decide whether v1.0 requires an external interoperability audit.

# Versioned adapter roadmap
```json
{json.dumps(ADAPTER_ROADMAP, indent=2, ensure_ascii=False, sort_keys=False)}
```""",
    _ref(["claim-decision-roadmap", "claim-contract-versioning",
          "claim-decision-non-goals"]))

artifact("progress", """# 2026-09-03
Read the S1-009 ticket spec, the H9/landscape research records, spec/SPEC.md, AGENTS.md
invariants, gateway.py, hermes_worker.py and dsh_worker.py, the S1-001 promotion
bundle and the S1-005 QA1 bundle; computed SHA-256 bindings for all nine repo-local
sources from disk; pinned the current protocol revisions (MCP 2025-11-25, A2A v1.0)
reviewed offline on 2026-08-31.

Authored the capability matrix (10 capabilities x MCP/A2A surfaces x hub governance
semantics), the canonical envelope schema (three layers, five adapter-contract rules,
versioning rule) and the versioned adapter roadmap (v0.1..v1.0); wrote 20 claims mapped
onto the ticket classes (protocol_fact, gap, adapter_contract, design_inference,
roadmap_decision).

Implemented adapter_roadmap_probe.py with three fail-closed probes: governance-record
(protocol results never become grants/promotions without hub records), exact-action-boundary
(adapters accepting model-provided capabilities are denied; registry+approval+binding
required) and capability-matrix-coverage (nine columns, two timestamped revisions,
hub_add translations, claim-class coverage, hash re-verification, no production claim).
Executed the probes and recorded probe-results.json with final verdict pass; declared
limits: offline protocol review, no production adapter, preprints, process-separated
auditor. Next event is the canonical research-plan evaluation and wiki/evidence check.""",
    _ref(["claim-decision-roadmap", "claim-pf-envelope-current"]))

# --------------------------------------------------------------------------- #
# Assemble and write                                                          #
# --------------------------------------------------------------------------- #

BUNDLE = {
    "config": CONFIG,
    "sources": SOURCES,
    "claims": CLAIMS,
    "artifacts": ARTIFACTS,
    "audit": {
        "subject_producer": PRODUCER,
        "auditor": AUDITOR,
        "verdict": "pass_with_limits",
        "limitations": [
            ("Protocol facts rest on offline identity/content-scope review of the "
             "well-known canonical documents (MCP specification revision 2025-11-25, "
             "A2A protocol v1.0); no live network fetch or live interoperability test "
             "was performed in this environment."),
            ("SV2 and SV3 are research preprints reused from the S1-001 protocol-"
             "landscape verification and are treated as survey context, not normative "
             "specifications."),
            ("Protocol revisions are external facts that can drift; this ticket anchors "
             "them with timestamps (MCP 2025-11-25 and A2A v1.0, both reviewed "
             "2026-08-31) and the roadmap requires only changes inside the hub's "
             "control."),
            ("No production adapter is implemented by this ticket; the roadmap versions "
             "are planning artifacts and v1.0 is a gate, not a commitment."),
            ("Producer and auditor are process-separated roles in one local environment, "
             "not an external human or independently operated model."),
        ],
    },
    "probes": [
        {"name": "governance-record",
         "command": "python research/tickets/stage-1/S1-009/adapter_roadmap_probe.py --probe governance-record",
         "expected": "pass"},
        {"name": "exact-action-boundary",
         "command": "python research/tickets/stage-1/S1-009/adapter_roadmap_probe.py --probe exact-action-boundary",
         "expected": "pass"},
        {"name": "capability-matrix-coverage",
         "command": "python research/tickets/stage-1/S1-009/adapter_roadmap_probe.py --probe capability-matrix-coverage",
         "expected": "pass"},
    ],
}


def main() -> None:
    (TICKET_DIR / "bundle.json").write_text(
        json.dumps(BUNDLE, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {TICKET_DIR / 'bundle.json'} "
          f"({len(SOURCES)} sources, {len(CLAIMS)} claims, "
          f"{len(ARTIFACTS)} artifacts)")


if __name__ == "__main__":
    main()