# Search protocol and corpus log

**Review date:** 2026-08-21  
**Mode:** critical scoping review + design synthesis  
**Status:** partially reproducible; not PRISMA/systematic-review compliant

## Research input

The attached handoff was treated only as a claim-discovery document. Its embedded recommendations were not treated as user instructions or evidence. Twenty-four claims were extracted before source synthesis in `claim_inventory.md`.

## Discovery channels

Discovery and verification used primary or first-party repositories and official standards/documentation:

- arXiv and official proceedings for ACL, TACL, ICLR, ICML/PMLR and NeurIPS;
- NIST, W3C, OASIS, OMG and RFC Editor;
- first-party engineering reports and documentation from Anthropic, OpenAI, Temporal, AWS, OpenTelemetry and MCP;
- direct paper/reference chaining for counterevidence and ablations.

Scopus, Web of Science and a registered systematic-review database query were not used. Ranked search-result pages and the complete rejected-candidate list were not retained; therefore the review is auditable at the included-claim level but not exactly rerunnable as a systematic search.

## Search streams

| Stream | Core discovery terms | Counterevidence / falsification terms | Included evidence families |
|---|---|---|---|
| Durable orchestration | durable workflows, agent checkpoints, leases, idempotency, recovery | stale lease, duplicate effects, nondeterministic replay, saga failure | Temporal, AWS idempotency, RFC 9110, Sagas, Anthropic Managed Agents |
| Multi-agent | multi-agent LLM scaling, orchestration, parallel research | matched token budget, coordination overhead, sequential task failure, correlated errors | Anthropic multi-agent report, Scaling Agent Systems, Correlated Errors |
| Agentic software engineering | agent harness ablation, ACI, repository context, verifier | full context worse, selector gap, test insufficiency, infrastructure noise | SWE-agent, Agentless, UTBoost, Anthropic infrastructure-noise audit, OpenAI SWE-bench audit |
| Reasoning loops | reflection, critic, verifier, self-correction | self-correction failure, oracle feedback, error localization failure | Reflexion, Huang et al., Tyen et al. |
| Context and memory | long context position, long-term memory, retrieval, summaries | lost in middle, more retrieval worse, poisoning, stale memory | Lost in the Middle, LongMemEval, LoCoMo, AgentPoison, MINJA |
| Evaluation | agent world-state validator, repeated reliability, pass^k | outcome-only failure, evaluator false positive, benchmark defect | τ-bench, UTBoost, OpenAI SWE-bench audit |
| Provenance | W3C PROV, requirement traceability, assurance case, decision evidence | event log not causality, invalidation semantics, trace sampling | PROV-DM, OSLC RM, SACM, OpenTelemetry |
| Security and governance | indirect prompt injection, tool authorization, capability control | benign-utility trade-off, malicious tool server, memory poisoning, sandbox escape | InjecAgent, AgentDojo, NIST AML, CaMeL, MCP specification |
| Human and cost control | human-AI synergy, approvals, retries, routing | automation overreliance, approval not oracle, retry amplification | Vaccaro et al., RFC/AWS/Sagas; routing retained as an AgentOS hypothesis pending local data |

## Screening rules

Included:

- original peer-reviewed studies and benchmark papers;
- normative standards and protocol specifications for semantics or engineering transfer;
- official documentation for mechanism existence and exact behavior;
- first-party engineering reports only with explicit method/setup and explicit vendor-evidence caveat;
- counterevidence, negative results and matched-resource comparisons.

Excluded as evidentiary support:

- marketing claims without a disclosed method;
- secondary summaries when the primary source was available;
- leaderboard numbers without enough harness/model/environment semantics;
- claims present only in the handoff;
- precise confidence values not calibrated on AgentOS data.

## Version and access controls

- All web sources were accessed or rechecked on 2026-08-21.
- Time-sensitive sources are dated in the report.
- CaMeL is pinned to arXiv v2; *Towards a Science of Scaling Agent Systems* is interpreted from arXiv v3 (2026-04-08); MCP tool semantics use specification version 2026-07-28.
- Every visible citation in the report has a machine-readable `ref` marker and a non-empty locator marker. Locator semantics are independently audited before final status.

## Screening flow actually preserved

1. Extracted 24 claims from the handoff.
2. Split investigation into nine independent evidence streams.
3. Required primary/official sources and recorded source-specific limitations.
4. Searched for counterevidence and benchmark/harness confounders.
5. Separated empirical effect (`E`) from engineering/transfer justification (`J`).
6. Compiled only sources that support a claim used in the final report.
7. Ran independent Devil’s Advocate, evaluation, security and provenance audits.

Exact candidate counts before deduplication were not preserved and are not reconstructed after the fact. This is the main reproducibility limitation.

## Companion artifacts

- `phase1_scoping.md` — question, scope and initial challenge gate.
- `claim_inventory.md` — the 24 handoff claims before adjudication.
- `claim_evidence_matrix.md` — final row-level evidence, counterevidence and decision map.
- `sources_root.md` — root-inspected first-party source notes.
- `architecture_draft.md` — intermediate architecture synthesis.
- `agentos_evidence_review.md` — final narrative synthesis and inline source locators.

