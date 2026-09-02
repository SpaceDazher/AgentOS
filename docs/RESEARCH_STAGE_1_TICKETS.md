---
title: AgentOS — Stage 1 Research Tickets
id: research-stage-1-tickets
aliases:
  - Platform Research Stage 1
  - Stage 1 Research Backlog
tags:
  - agentos/research
  - agentos/stage-1
  - agentos/tickets
created_at: 2026-08-24
updated_at: 2026-08-30
stage: 1
status: PLANNING_ONLY
owner: research-planning
db_root: .agentos-research/platform-stage-1
bundle_root: research/tickets/stage-1
flow: FLOW-11
active_ticket_count: 20
parked_item_count: 4
evidence_sources:
  SRC-00: "D:/Project/DeepeekHarness/research/00_research_plan.md"
  SRC-01: "D:/Project/DeepeekHarness/research/10_source_registry.md"
  SRC-02: "D:/Project/DeepeekHarness/research/20_feature_catalog.md"
  SRC-03: "D:/Project/DeepeekHarness/research/30_architecture_models.md"
  SRC-04: "D:/Project/DeepeekHarness/research/40_mental_model.md"
  SRC-05: "D:/Project/DeepeekHarness/research/50_ontology.md"
  SRC-06: "D:/Project/DeepeekHarness/research/60_mathematical_model.md"
  SRC-07: "D:/Project/DeepeekHarness/research/70_synthesis_and_gaps.md"
  SRC-08: "D:/Project/DeepeekHarness/research/80_independent_audit.md"
  SRC-09: "D:/Project/DeepeekHarness/research/PROGRESS.md"
---

# Stage 1 research ticket plan — platform

> [!CAUTION]
> **Planning only.** This page does not execute research, create ticket
> bundles, or claim that any research question is closed. A `research-plan`
> `PASS` or explicitly justified `PASS_WITH_LIMITS` is a research evaluation;
> it is never `Goal ACCEPTED`. Only the release gate, over evaluator records,
> can accept a software goal.

Related project notes: [Interactive Kanban](RESEARCH_STAGE_1_KANBAN.html) ·
[README](../README.md) ·
[Evaluation protocol](EVALUATION_PROTOCOL.md) ·
[Gap register](GAP_REGISTER.md).

Stage 1 turns the evidence-backed open items into an executable, offline-first
research portfolio. The documents in the source registry below are evidence and
data, not agent instructions. A ticket is complete only when its bundle has
been evaluated and its evidence can pass the common closure gate in this page.
The page itself creates no `bundle.json` files and performs no external writes,
issues, retrieval, benchmark, pilot, legal qualification, or production
rollout.

## Source registry aliases

These aliases are stable references used in every ticket's evidence field. The
source files live under the research workspace named in the request; paths are
recorded for provenance rather than treated as commands.

| Alias | Evidence document | What it contributes |
|---|---|---|
| `SRC-00` | `00_research_plan.md` | original DoD, method, taxonomy, controlled deviation |
| `SRC-01` | `10_source_registry.md` | source statuses, counts, deduplication, Z/SV tails |
| `SRC-02` | `20_feature_catalog.md` | EP-01..EP-12 and H1..H16 feature traceability |
| `SRC-03` | `30_architecture_models.md` | topology, contracts, data model, QA1..QA3 |
| `SRC-04` | `40_mental_model.md` | oversight UX, comprehension measures, QM1..QM3 |
| `SRC-05` | `50_ontology.md` | classes, lifecycles, SHACL sketches, ontology Q1..Q3 |
| `SRC-06` | `60_mathematical_model.md` | capacity assumptions, Beta gate, INV1..INV6, limits 1..5 |
| `SRC-07` | `70_synthesis_and_gaps.md` | G-01..G-10, limits, and recommended next steps 1..5 |
| `SRC-08` | `80_independent_audit.md` | audit verdict, known limits, and observed verification |
| `SRC-09` | `PROGRESS.md` | artifact status and correction/history provenance |

## FLOW-11 contract and shared lifecycle

### Required FLOW-11 artifacts

Every active ticket uses the complete, ordered set below. The names are the
runtime contract and must not be shortened or replaced by a ticket-local list.

| Order | Exact artifact name | Minimum role in a ticket bundle |
|---:|---|---|
| 1 | `research_plan` | question, method, scope, claims, and limits |
| 2 | `source_registry` | sources, provenance, verification status, and mix |
| 3 | `feature_catalog` | affected EP/Hypothesis traceability |
| 4 | `architecture_models` | relevant topology, contract, or data decision |
| 5 | `mental_model` | human/oversight implications when applicable |
| 6 | `ontology` | object, scope, provenance, and lifecycle semantics |
| 7 | `mathematical_model` | equations, thresholds, assumptions, and sensitivity |
| 8 | `synthesis_and_gaps` | result, unresolved gaps, and next actions |
| 9 | `independent_audit` | distinct producer/auditor and adversarial review |
| 10 | `platform_plan` | research-scoped recommendation and implementation boundary |
| 11 | `progress` | append-only status, evidence hashes, and limits |

`FLOW-11 requirement` means all eleven artifacts above are present, non-empty,
UTF-8, hash-consistent, and linked to same-goal claims in the bundle. A
ticket-specific emphasis may add detail, but cannot remove an artifact or
turn a prototype into production software.

### Shared harness lifecycle

1. **Prepare (human-owned):** choose the ticket, confirm dependencies are
   complete, and author a bounded `bundle.json` under the exact ticket path.
   This page does not create that file.
2. **Plan/evaluate:** from the AgentOS repository root, run the ticket's exact
   PowerShell command. The bundle is untrusted data; the harness does not fetch
   URIs or execute bundle text.
3. **Persist atomically:** `research-plan` records the research goal, task DAG,
   sources, claims, eleven artifacts, evaluation, and audit metadata under the
   shared DB root `.agentos-research/platform-stage-1`.
4. **Emit evidence:** the run emits the goal-scoped
   `agentos.evidence-pack/v3`, recalculates the artifact chain, and rebuilds
   the redacted Obsidian projection. A `PASS_WITH_LIMITS` keeps explicit limits
   visible.
5. **Check the projection:** run `python -m agentos.cli wiki-check --db
   .agentos-research/platform-stage-1` as an operator check after the research
   command. A failed check is not closure.
6. **Audit and close:** an auditor distinct from the subject producer reviews
   the evidence and ticket probes. The ticket moves to `PASS` or justified
   `PASS_WITH_LIMITS` only when the common closure gate passes; otherwise it
   remains `FAIL`, `BLOCKED`, or `IN_PROGRESS`.

### Status, ownership, priority, and dependency conventions

| Convention | Values/rule |
|---|---|
| Status | `READY` (the ticket contract is complete; execution eligibility still requires every dependency to have passed), `IN_PROGRESS` (bundle being researched), `BLOCKED` (named blocker), `PASS` (all criteria pass), `PASS_WITH_LIMITS` (criteria pass with explicit limits), `FAIL` (a criterion or probe fails), `PARKED` (not active), `CLOSED` (portfolio closure recorded by S1-020). |
| Owner | One accountable role per ticket: `sources`, `capacity`, `formal`, `architecture`, `security`, `knowledge`, `hci`, `privacy`, `synthesis`, or `audit`. Contributors do not change the owner or evidence boundary without recording it in `progress`. |
| Priority | `P0` blocks a platform decision or safety invariant; `P1` is required for an architecture/UX decision; `P2` is a calibration or follow-up study. Priority is not evidence strength. |
| Wave | `W0` foundations, `W1` formal/topology choices, `W2` backend/isolation/revocation/knowledge, `W3` security and pilot preparation, `W4` UX/ontology/privacy decisions, `W5` synthesis, `W6` independent closure. |
| Dependencies | Comma-separated active ticket IDs only; `—` means none. A dependency must be listed in this page, must complete before the ticket starts, and may point only to an earlier wave. No dependency points to a parked item. |
| Bundle | Exactly `research/tickets/stage-1/<TICKET-ID>/bundle.json` relative to the repo root. One ticket has one bundle path; revisions are new artifact versions in the same scoped DB, not overwrites. |

### Common exit/closure gate

A ticket or the Stage 1 portfolio may exit only when all of the following are
observed in the canonical DB/evidence, not merely stated in prose:

- `status` is `PASS`, or is `PASS_WITH_LIMITS` with an explicit, bounded
  justification and follow-up condition;
- an `agentos.evidence-pack/v3` evidence pack exists for the ticket goal;
- `chain_fresh=true` and `latest_evaluation_valid=true`;
- the wiki projection check is `ok=true`;
- the independent auditor is distinct from the subject/platform producer;
- every ticket-specific adversarial/near-miss probe passes, with any abstention
  or limitation recorded rather than silently treated as a pass.

This gate closes a research evaluation only. It does not set a Goal to
`ACCEPTED`, does not certify production readiness, and does not erase parked
items or explicit limits.

## Wave and dependency DAG

| Wave | Active tickets | Dependency rule |
|---|---|---|
| W0 | S1-001, S1-002, S1-003 | no dependencies; establish source, capacity, and ontology baselines |
| W1 | S1-004, S1-005, S1-011 | depend only on W0; establish formal, topology, and minimal knowledge-gate options |
| W2 | S1-006, S1-007, S1-008, S1-009, S1-012 | depend on W0/W1 results; select backend, isolation, revocation, protocol, and evidence semantics |
| W3 | S1-010, S1-013, S1-016 | depend on security/knowledge/topology foundations; prepare threat, pilot, and lineage evidence |
| W4 | S1-014, S1-015, S1-017, S1-018 | depend on pilot/lineage/formal results; decide dispute UX, naming, responsibility analytics, and profile C research |
| W5 | S1-019 | synthesizes the completed portfolio and may use a bounded prototype as evidence only |
| W6 | S1-020 | depends on every active ticket S1-001..S1-019 and makes the independent closure decision |

The explicit dependency list in each ticket is the authoritative edge list;
the table above is a navigational view. It is acyclic because all edges point
from a lower wave to a higher wave, and S1-020 is the sole closure sink.

## Active ticket summary

| ID | Wave | Priority | Owner | Status | Dependencies | Decision focus |
|---|---|---|---|---|---|---|
| S1-001 | W0 | P0 | sources | PASS_WITH_LIMITS | — | targeted promotion policy for `u` and Z/SV tails |
| S1-002 | W0 | P0 | capacity | PASS_WITH_LIMITS | — | benchmark, capacity, storage, and SLO assumptions |
| S1-003 | W0 | P0 | formal | PASS | — | executable SHACL/ontology validation |
| S1-004 | W1 | P0 | formal | PASS_WITH_LIMITS | S1-002, S1-003 | bounded formal/simulation checks for INV1–INV6 and delivery safety |
| S1-005 | W1 | P1 | architecture | PASS_WITH_LIMITS | S1-002 | QA1 modular monolith versus containers |
| S1-006 | W2 | P1 | architecture | PASS_WITH_LIMITS | S1-002, S1-005 | QA2 in-process versus durable execution backend |
| S1-007 | W2 | P0 | security | PASS_WITH_LIMITS | S1-003, S1-005 | QA3 retrieval/index scope isolation |
| S1-008 | W2 | P0 | security | PASS_WITH_LIMITS | S1-002, S1-004 | revocation propagation bound of ≤5 seconds |
| S1-009 | W2 | P1 | architecture | READY | S1-001, S1-005 | MCP/A2A delegation and knowledge adapter roadmap |
| S1-010 | W3 | P0 | security | READY | S1-001, S1-009 | tool-poisoning detection and quarantine evidence |
| S1-011 | W1 | P0 | knowledge | READY | S1-001, S1-003 | minimal promote/challenge knowledge gate |
| S1-012 | W2 | P0 | knowledge | READY | S1-001, S1-003, S1-011 | evidence independence and Beta/Sybil calibration |
| S1-013 | W3 | P1 | hci | READY | S1-011, S1-012 | 15–20-person comprehension and approval-fatigue pilot |
| S1-014 | W4 | P1 | hci | READY | S1-011, S1-013 | claim-dispute card versus graph |
| S1-015 | W4 | P2 | hci | READY | S1-013 | petname principal naming study |
| S1-016 | W3 | P1 | formal | READY | S1-003, S1-007 | flat workspace scope versus PROV-Dictionary lineage |
| S1-017 | W4 | P2 | formal | READY | S1-004, S1-016 | STIT/ATL responsibility analytics placement |
| S1-018 | W4 | P1 | privacy | READY | S1-007, S1-008, S1-009 | profile-C MLS + TEE attested-indexer PoC research |
| S1-019 | W5 | P0 | synthesis | READY | S1-004, S1-005, S1-006, S1-007, S1-008, S1-009, S1-010, S1-011, S1-012, S1-013, S1-014, S1-015, S1-016, S1-017, S1-018 | P0 architecture decision synthesis/prototype evidence |
| S1-020 | W6 | P0 | audit | READY | S1-001..S1-019 (expanded in ticket) | independent phase audit and closure decision |

## Active tickets

Each ticket below is an executable research contract. The command is shown but
is intentionally not run here; it will fail closed until the operator provides
the ticket's bounded bundle.

### S1-001 — Targeted source promotion and verification policy

- **Status:** `PASS_WITH_LIMITS` — aligned 2026-08-30 with the canonical
  research series (revision 1): goal `goal_DXHSJM6981DBYCTD01M0TDDN5X`,
  evaluation `reval_1DG5Q6WEAY6A40A901M0TDDN6N`, artifact chain
  `4f524c48…b01e9`, evidence-pack/v3 `chain_fresh=true`. Limits:
  process-separated (not external) auditor; frozen 12-record queue only,
  not the 176 `u` tail; live canonical review without full third-party
  archiving.
- **Priority:** `P0`
- **Wave:** `W0`
- **Owner:** `sources`
- **Dependencies:** `—`
- **Research question:** What targeted verification and promotion policy is
  sufficient to move only decision-critical `u` sources toward `v`/`c`, while
  preserving provenance for the 176 unverified entries and the Z/SV tails?
- **Decision enabled:** Approve a repeatable promotion queue, independence
  rules, and tail-handling policy for claims used by later tickets; explicitly
  decide what remains `u`.
- **Source evidence:** `SRC-00` §Controlled deviation (round 13); `SRC-01` §1,
  §3, §13–15 (247 positions, 176 `u`, Z/SV tail); `SRC-07` §3 G-05 and §5
  step 5; `SRC-08` §1 and §5; `SRC-09` round-13 journal.
- **Scope:** Targeted claims that later tickets actually cite; canonical
  source ID, publisher, independence group, verification status, and a finite
  Z/SV spot-check queue.
- **Non-scope:** Mass manual verification of every 176 `u` source, live
  retrieval adapters, and changing the historical registry in place.
- **Required source mix/count:** At least 3 sources per promoted high-risk
  claim (at least 2 independent canonical/publisher groups plus 1 context or
  contradiction source); include every source status class used by the policy
  and at least 2 targeted Z/SV entries.
- **Claim classes:** `fact`, `design_inference`, `hypothesis`, `risk`, and
  `verification_status`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is source
  provenance, promotion rules, and explicit controlled deviation.
- **Adversarial/near-miss eval probes (≥2):**
  - A mirror URL with a different publisher label must not count as an
    independent source or satisfy the promotion threshold.
  - A source marked `u` with a plausible title but no verifier provenance must
    remain unpromoted; a corrected DOI must preserve the original error note.
- **Acceptance criteria (binary/quantitative):**
  - Binary: the policy enumerates `v`, `c`, `u`, `x`, and `x-excluded`, and
    records `canonical_source_id`, `publisher_id`, and `independence_group` for
    every promotion candidate.
  - Quantitative: the bundle contains a finite target list covering all
    decision-critical `u` claims and at least 2 Z/SV tail spot checks; it does
    not state or imply that all 176 `u` sources were verified.
  - Binary: both probes pass and the independent auditor confirms no
    mirror/Sybil double-count.
- **Stop/escalation condition:** Stop and escalate to `BLOCKED` if a promoted
  claim has no two independent canonical groups, if a source identity cannot
  be disambiguated, or if the work would require mass verification outside the
  targeted queue.
- **Bundle path:** `research/tickets/stage-1/S1-001/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-001 targeted source promotion and verification policy" --bundle "research/tickets/stage-1/S1-001/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-002 — Benchmark, capacity, storage, and SLO assumptions

- **Status:** `PASS_WITH_LIMITS` — aligned 2026-08-30 with the canonical
  research series (revision 1): goal `goal_8CTE14C6Q2E1TV8801M0TEN900`,
  evaluation `reval_N96W6BG39C3TPZZT01M0TEN90T`, artifact chain
  `c03fe887…b7c4`, evidence-pack/v3 `chain_fresh=true`; SLOQUAL-001
  qualification recorded separately (`pass_with_limits`,
  `reval_AN6GAVADQGF8926701M15N67X7`). Limits: short single-process local
  SQLite/WAL baseline, not production traffic; distributed workers,
  external calls, revocation, fan-out unverified; process-separated (not
  external) auditor; 20 ms p95 is an internal target, not a production
  SLO.
- **Priority:** `P0`
- **Wave:** `W0`
- **Owner:** `capacity`
- **Dependencies:** `—`
- **Research question:** Do the planning assumptions around 34 events/s,
  p95 authorization latency, queueing, concurrency, and annual storage survive
  a reproducible workload envelope, and which values can be carried forward as
  targets rather than measurements?
- **Decision enabled:** Set the benchmark envelope, capacity model, and
  evidence labels for the later topology/backend and P0 decisions.
- **Source evidence:** `SRC-06` §8–9 (34 events/s, p95/Little, storage,
  limitations 1 and 4); `SRC-03` §3.1 and §9 QA2; `SRC-07` §3 G-03 and §5
  step 1; `SRC-08` §5 (planning numbers); `SRC-09` round-13 journal.
- **Scope:** Authorization/control-plane load, principal/agent cardinality,
  burst behavior, p95/p99, queueing, worker count, external-call rate,
  fan-out caps, event/storage projection, and reproducible benchmark seed
  definitions.
- **Non-scope:** Production SLO commitment, multi-region reliability claims,
  customer traffic, or a production deployment.
- **Required source mix/count:** At least 3 evidence classes: one mathematical
  source, one architecture/runtime source, and one benchmark method or
  empirical result; at least 3 load levels including the 34 events/s planning
  point and a 100 events/s burst, with warm/cold runs recorded separately.
- **Claim classes:** `planning_assumption`, `measurement`, `design_inference`,
  `uncertainty`, and `SLO_target`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is the workload
  matrix, distributions, p95/queueing evidence, and assumption ledger.
- **Adversarial/near-miss eval probes (≥2):**
  - A report that repeats 34 events/s but has no measured distribution or
    timestamped run must be classified as an assumption, not benchmark proof.
  - A burst result that reports mean latency while omitting p95/p99 or queue
    saturation must fail the capacity claim.
- **Acceptance criteria (binary/quantitative):**
  - Binary: every number is labelled `measured`, `derived`, `target`, or
    `unverified`; the bundle includes workload, environment, seed, and raw
    result references.
  - Quantitative: at least 3 load levels, p95 and p99 latency, utilization,
    queue depth, and storage projection are reported; the 34 events/s and
    100 events/s points are included as planning/benchmark cases, and the
    complete `SRC-06` §8 numeric profile has a measured/derived/target/
    unverified disposition.
  - Binary: no production SLO is claimed without observed benchmark evidence.
- **Stop/escalation condition:** Escalate if the harness cannot capture
  reproducible timestamps, if queueing parameters are unidentifiable, or if a
  stakeholder asks to publish a production SLO from planning numbers alone.
- **Bundle path:** `research/tickets/stage-1/S1-002/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-002 benchmark capacity storage and SLO assumptions" --bundle "research/tickets/stage-1/S1-002/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-003 — Executable SHACL and ontology validation

- **Status:** `PASS` — aligned 2026-08-30 with the canonical research
  series (revision 24): goal `goal_RVX89EP2SEQ94MSZ01M0VAVECK`, evaluation
  `reval_KHXH2JAY5JFW8YJM01M0VAVEEM`, artifact chain `b9c9e2fb…3157`,
  evidence-pack/v3 `chain_fresh=true`.
- **Priority:** `P0`
- **Wave:** `W0`
- **Owner:** `formal`
- **Dependencies:** `—`
- **Research question:** Can the ontology lifecycle and open SHACL shapes be
  executed against valid, invalid, proposed, promoted, rejected, superseded,
  and revoked fixtures without rejecting intended inheritance or allowing an
  orphan promotion?
- **Decision enabled:** Decide whether the SHACL/ontology contract is ready for
  downstream formal, isolation, lineage, and knowledge-gate work, and record
  which checks remain structural-only.
- **Source evidence:** `SRC-05` §3, §5, §7, and §9 Q1–Q3; `SRC-01` §10
  (`F4`, `F7`–`F9`); `SRC-08` §4 and §5 (SHACL defects and no runtime
  `pySHACL`); `SRC-09` rounds 11–13.
- **Scope:** SHACL shapes, lifecycle status vocabulary, scope/provenance,
  EvidenceShape, promotion/rejection/supersession, and near-miss fixtures.
- **Non-scope:** Production ontology service, RDF store selection, semantic
  reasoning beyond the stated shapes, or a claim that runtime `pySHACL` has
  already run when it has not.
- **Required source mix/count:** At least 3 source classes: ontology/SHACL,
  audit correction history, and one feature or data-model consumer; at least 8
  fixtures covering 4 valid and 4 invalid lifecycle/ownership cases.
- **Claim classes:** `schema_fact`, `constraint`, `design_inference`,
  `near_miss`, and `tool_availability_limit`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is executable
  shapes, lifecycle fixtures, and an explicit `pySHACL` runtime limitation.
- **Adversarial/near-miss eval probes (≥2):**
  - A `proposed` assertion without promotion evidence must remain valid under
    open shapes but must not pass a promoted-only EvidenceShape.
  - A promoted assertion with two mirror URLs, no independent group, or no
    `PromotionActivity` must fail rather than being counted as grounded.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: at least 8 fixtures cover the lifecycle states and at least 2
    ownership/scope failures; 100% of expected lifecycle states are represented.
  - Binary: all invalid fixtures fail for the intended reason and all valid
    fixtures pass the available execution path; any unavailable runtime is
    reported as `PASS_WITH_LIMITS`, never silently as executed.
  - Binary: no shape uses the previously rejected constraint spelling or stale
    status vocabulary.
- **Stop/escalation condition:** Escalate if a required runtime dependency is
  unavailable, a fixture needs closed-world semantics not in the contract, or a
  shape change would alter an invariant consumed by S1-004/S1-011.
- **Bundle path:** `research/tickets/stage-1/S1-003/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-003 executable SHACL and ontology validation" --bundle "research/tickets/stage-1/S1-003/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-004 — Alloy/TLA+ and seeded deterministic invariant simulation

- **Status:** `PASS_WITH_LIMITS` — recorded 2026-08-30: goal
  `goal_Z9TP87YGTAMDPD9801M18BSRXE`, evaluation
  `reval_5JJ8C83TCA8CNQ5Q01M18BSRZX`, revision 7, artifact chain
  `ce1fcfd5…1d349`, evidence-pack/v3 `chain_fresh=true`, wiki-check ok
  (1787 files, 5008 links, 0 issues). The byte-for-byte pack is tracked at
  `research/tickets/stage-1/S1-004/results/evidence/evidence-pack-98f6b998909983706ea993e6877b56b003bb64f5228a50559bdb4e01feb98841.json`.
  Executed: Alloy 5.1.0.201908141853 (sat4j) over
  `agentos_structural_v2.als` — 2 valid SAT / 5 near-miss UNSAT / 5 mutant
  SAT; TLC2 2.15 (tla2tools 1.7.0, Java 8 pin) exhaustive 271,168-state
  check — 10 invariants + LiveDelivery hold; deterministic simulator —
  seeds 11/22/33 × 1,000,000 operations plus three fresh-interpreter
  subprocess reruns (6,000,000 total), 0 violations of INV1–INV6 and SAF,
  all digests reproduced; both adversarial probes pass through real
  operations; 24 S1-004 regression tests incl. 12 negative mutations and
  11 fail-closed review cases pass. Limits: bounded
  scopes only; simulator models the design contract, not deployed code;
  LIVE one-tick activation/replay stays an implementation obligation;
  stale-ack fencing evidenced deterministically (probe A + SAF2 mutation),
  not by random runs; process-separated (not external) auditor.
- **Priority:** `P0`
- **Wave:** `W1`
- **Owner:** `formal`
- **Dependencies:** `S1-002, S1-003`
- **Research question:** Can bounded Alloy/TLA+ models and a seeded scheduler
  exercise INV1–INV6, outbox delivery, fencing, effect receipts,
  reconciliation, and crash recovery without a safety violation?
- **Decision enabled:** Decide whether the invariant set and deterministic
  simulation envelope are sufficient acceptance evidence for the platform
  design, and which liveness claims remain design obligations.
- **Source evidence:** `SRC-06` §7 (INV1–INV6, SAF/LIVE), §9 limitation 4;
  `SRC-07` §2 and §3 G-10; `SRC-01` §10 (`L10`, `L11`, `L19`); `SRC-08` §4;
  `SRC-09` rounds 9 and 13.
- **Scope:** Identity separation, single scope, attenuation, no orphan
  promotion, revocation monotonicity, budget conservation, outbox/replay,
  unknown outcome reconciliation, and deterministic fault injection.
- **Non-scope:** Proof of arbitrary LLM behavior, production distributed
  consensus, unbounded model checking, or treating a planned spec as a passed
  implementation test.
- **Required source mix/count:** At least 3 source classes: mathematical
  invariants, architecture/effect semantics, and formal-method references; at
  least 3 deterministic seeds and 1,000,000 simulated operations per reported
  acceptance run.
- **Claim classes:** `invariant`, `safety`, `liveness`, `simulation_measurement`,
  `failure_mode`, and `design_obligation`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is the formal
  property map, seeded trace, and explicit outbox/reconciliation evidence.
- **Adversarial/near-miss eval probes (≥2):**
  - Inject a crash after local transition but before publish; the replay must
    produce one local effect receipt and no duplicate effect.
  - Interleave child-budget reservation, revoke, and retry; any over-allocation,
    post-revoke allow, or unknown outcome that does not enter reconciliation is
    a failure.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: at least 3 seeds and 1,000,000 operations per acceptance run;
    0 violations of INV1–INV6 and SAF in the reported traces.
  - Binary: every LIVE claim has a trace or is explicitly labelled a design
    obligation; unknown external outcomes never become blind retries.
  - Binary: both probes pass and the auditor can reproduce the seed/configuration.
- **Stop/escalation condition:** Escalate if a counterexample cannot be reduced
  to a deterministic trace, if a property depends on an unbounded state space,
  or if the model and implementation contract disagree on ownership/budget.
- **Bundle path:** `research/tickets/stage-1/S1-004/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-004 Alloy TLA plus seeded deterministic invariant simulation" --bundle "research/tickets/stage-1/S1-004/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-005 — QA1 runtime topology: modular monolith versus containers

- **Status:** `PASS_WITH_LIMITS` - corrective round R4 recorded
  2026-08-31 (research revision 7; experiments re-executed on the clean
  committed tree `1812d0563069...`, dirty=false, commit-derived tree and the
  exact producer/evaluator script-hash set
  bound, evaluator nonce-bound to the frozen experiment digest):
  goal `goal_Q661VGKGFZC95QMH01M1AS9PRW`, evaluation
  `reval_QN4TWY89FAA5QDHX01M1AS9PTK`, artifact chain
  `580d570fe81485ae...`, tracked content-addressed evidence-pack/v3
  `chain_fresh=true` at `results/evidence/`. Decision: modular monolith
  (3.72 vs containers 2.07 normalized under the frozen rubric; scores
  host-frozen per candidate x dimension); sensitivity 218 deterministic
  runs with zero flips/ties; every S2 weight vector persisted with
  total and SHA-256; hard-constraint violations reject ANY candidate
  (positive verdict requires both topologies valid); evidence refs
  resolve only via hash-bound registry ids or tracked snapshots
  (portable from a clean clone); failure scenarios under a strict
  production schema with INV/SAF/LIVE references; boundary experiments
  re-executed before the evaluator with semantically validated responses,
  exact transport observation keys, and fail-closed Git provenance.
  Autoresearch worktree copy now ignores only explicit generated/cache
  paths; all other copy failures stop execution. Limits: same-host measurements
  only; containers restart/recovery unknown (bounded in sensitivity
  S3); no production claims; split triggers symbolic until the
  follow-up benchmark.
- **Priority:** `P1`
- **Wave:** `W1`
- **Owner:** `architecture`
- **Dependencies:** `S1-002`
- **Research question:** For the MVP, does a modular monolith with hard
  internal contracts provide a better safety, determinism, and operability
  boundary than splitting the runtime into containers?
- **Decision enabled:** Resolve QA1 and record the chosen topology plus the
  conditions that would justify a later split.
- **Source evidence:** `SRC-03` §2, §6–8, and §9 QA1; `SRC-02` EP-01–EP-05
  and EP-08; `SRC-07` §5 step 2; `SRC-08` §5; `SRC-09` §Status artifacts.
- **Scope:** Process/container boundaries, failure isolation, policy gateway,
  SQLite/audit constraints, deterministic simulation, deployment and recovery
  implications.
- **Non-scope:** Building production containers, selecting a cloud vendor, or
  claiming measured reliability from the design comparison.
- **Required source mix/count:** At least 4 evidence classes: current
  architecture, feature consumers, formal/simulation needs, and operational
  evidence; compare both options across at least 6 explicit dimensions.
- **Claim classes:** `architecture_fact`, `tradeoff`, `design_inference`,
  `risk`, and `decision`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is the QA1
  decision matrix and boundary-preserving deployment recommendation.
- **Adversarial/near-miss eval probes (≥2):**
  - A container split that duplicates policy state or weakens the audit boundary
    must fail even if it improves a superficial latency score.
  - A modular-monolith recommendation that omits a failure boundary or
    deterministic-simulation interface must be marked incomplete.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: compare both topologies on at least 6 dimensions and include
    at least 3 failure/recovery scenarios.
  - Binary: one topology is recommended with explicit assumptions, migration
    trigger, and non-goals; no production build is claimed.
  - Binary: both probes pass and the recommendation preserves gateway-only
    effects and atomic transition/audit semantics.
- **Stop/escalation condition:** Escalate if the choice requires unmeasured
  production SLOs, a new trust boundary not covered by S1-003/S1-004, or a
  container platform decision outside Stage 1 research scope.
- **Bundle path:** `research/tickets/stage-1/S1-005/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-005 QA1 runtime topology modular monolith versus containers" --bundle "research/tickets/stage-1/S1-005/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-006 — QA2 execution backend: in-process versus durable engine

- **Status:** `PASS_WITH_LIMITS` - corrective round R2 recorded
  2026-08-31 (research revision 5; 90+90 runs re-executed on clean
  committed tree `30cdd80...`, dirty=false, disk bytes and commit blobs
  bound for every evidence script, evaluator derived all counters and
  metrics from the manifest-named raw runs): goal
  `goal_2T78EACBA51SH24M01M1CKXMNW`, evaluation
  `reval_3R5R2WNN81E4ZMWW01M1CKXMRE`, artifact chain `f5e45f4f...`,
  tracked content-addressed evidence-pack/v3 `chain_fresh=true` at
  `results/evidence/`. Decision: in-process scheduler (3.88 vs durable
  engine 3.20 normalized under the frozen 11-dimension rubric);
  sensitivity 222 deterministic runs (22 perturbations + 200 seeded
  compositions), zero flips/ties; 90 main runs + 90 isolated rerun runs
  (separate process, output, executor id), all seven
  safety counters zero on every accepted run; probes A (unsafe resume),
  B (incomparable workload) and C (blind retry) detected fail-closed
  from digest-bound behavioral traces; S1 records atomic transition +
  outbox commit, crash, and replay; S3 resumes into a new run only via
  registered content-hash-verified checkpoints; S4 records a stale
  fencing rejection and deduplicated redelivery; every S2 run injects
  and reconciles an unknown outcome before retry. Repeated DAG instances
  are dependency-valid and high load creates observed queue pressure.
  Limits: model-based same-host comparison (durable-engine
  costs combine S1-005 E1/E2 measurements with documented 100 ms lease
  assumption); the 20,000/s saturation load is a simulator stress probe,
  not a production profile; no vendor engine installed; multi-host
  partition and vendor timer semantics unknown and excluded from
  scoring; migration triggers remain unmeasured design obligations.
- **Priority:** `P1`
- **Wave:** `W2`
- **Owner:** `architecture`
- **Dependencies:** `S1-002, S1-005`
- **Research question:** Which execution backend best preserves task/run
  durability, checkpoint/resume, deterministic testing, and acceptable
  latency: the in-process scheduler or a durable-execution engine?
- **Decision enabled:** Resolve QA2 and set a backend boundary, migration
  trigger, and evidence requirements for the Coordinator.
- **Source evidence:** `SRC-03` §3.2, §5, §9 QA2; `SRC-06` §7 SAF/LIVE and §9
  limitation 4; `SRC-07` §3 G-03/G-10; `SRC-02` EP-11; `SRC-08` §5.
- **Scope:** Checkpoint/resume, crash/retry, idempotency, scheduling latency,
  operator visibility, test determinism, and dependency-ready task execution.
- **Non-scope:** Integrating a production vendor, changing the current core
  runtime, or claiming durability beyond the tested evidence.
- **Required source mix/count:** At least 3 source classes: architecture,
  formal lifecycle, and benchmark/method evidence; compare both backends in at
  least 4 crash/replay scenarios and 3 load levels.
- **Claim classes:** `architecture_fact`, `benchmark_measurement`, `tradeoff`,
  `failure_mode`, and `decision`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is QA2 evidence,
  replay semantics, and a bounded migration plan.
- **Adversarial/near-miss eval probes (≥2):**
  - A backend that resumes a task but duplicates an external effect must fail
    unless the outcome is reconciled and the receipt is unique.
  - A latency comparison that uses different task DAGs or omits crash recovery
    must be rejected as incomparable.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: at least 4 crash/replay scenarios, 3 load levels, p95/p99,
    and recovery-time observations or explicit unavailable labels.
  - Binary: QA2 has one recommendation, assumptions, rollback/migration trigger,
    and no production backend is installed by this ticket.
  - Binary: both probes pass and S1-004 safety semantics remain intact.
- **Stop/escalation condition:** Escalate if the durable option requires
  provider-specific semantics not represented in the evidence, or if no test can
  distinguish duplicate effects from reconciled unknown outcomes.
- **Bundle path:** `research/tickets/stage-1/S1-006/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-006 QA2 execution backend in process versus durable engine" --bundle "research/tickets/stage-1/S1-006/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-007 — QA3 retrieval and index isolation

- **Status:** `PASS_WITH_LIMITS` - corrective round R4 recorded
  2026-09-01 UTC (research revision 7; closes all REVIEW_R1, REVIEW_R2,
  and REVIEW_R3 P1/P2 findings): goal
  `goal_5FX22ZHCEAW0G2B501M1DDTYSA`, evaluation
  `reval_6BH3G062B38G3WHH01M1DDTYW2`, artifact chain `4c344ab2...`
  (full 64-hex value verified equal across record, canonical DB and
  pack), tracked content-addressed evidence-pack/v3 `chain_fresh=true`
  plus a bound raw-observations archive `243ce6a6...` (172 byte-exact
  members: 168 run records + 2 manifests + 2 timing artifacts; archive
  sha256 carried inside the bundle as source RAW-OBSERVATIONS / claim
  c8-raw-archive and asserted by the clean-clone probe). Dependency
  gate proved S1-003 (rev 24, pass) and S1-005 (rev 7,
  pass_with_limits). Decision: **per-scope index projections** bound to
  the canonical (tenant, workspace, goal) scope win under the frozen
  11-dimension rubric (3.8503 vs shared-RLS 3.5999, per-variant cells;
  D10 uses the frozen inverse normalization - lower measured cost
  scores strictly higher, per-component direction asserted).
  Sensitivity: 222 executed weight perturbations, zero winner flips.
  Evidence: 2 variants x 14 cases x 3 seeds x 2 executors = 168 runs on
  one frozen contract/corpus/rubric; evaluator re-derived ISO1-ISO8 = 0
  for both honest variants; deny bodies byte-identical across all
  equivalence classes; timing statistic/tolerance/verdict recomputed by
  the evaluator from BOTH raw hash-bound arms (foreign-control
  differences derived in-evaluator; disagreeing or missing derived
  arrays fail closed); probes bound to the frozen A/B/C/D matrix and
  detected fail-closed. The tracked evaluation record is now derived
  from the current evaluator and pack, validates the structured archive
  binding in both bundle and pack, and uses a canonical timestamp that
  cannot predate the evaluation. Limits: local model only; timing cannot prove
  absence of all side channels; D9/D11 remain inference; profile C
  stays S1-018, the <=5s revocation SLO stays S1-008. Migration trigger
  away from per-scope projections requires documented cross-scope
  ranked federation inside one trust boundary PLUS measured maintenance
  evidence at equal ISO compliance; rollback is a projection rebuild
  from the canonical object store.
- **Priority:** `P0`
- **Wave:** `W2`
- **Owner:** `security`
- **Dependencies:** `S1-003, S1-005`
- **Research question:** Is per-scope indexing safer and sufficiently useful
  than a shared index with row-level retrieval filtering, and can either design
  prove no cross-scope reads or leakage?
- **Decision enabled:** Resolve QA3 and choose the retrieval isolation contract
  for each profile, including the threat model and test boundary.
- **Source evidence:** `SRC-03` §4, §6, and §9 QA3; `SRC-05` §1, §4, and §9
  Q1/Q3; `SRC-06` §1–2; `SRC-02` EP-04/EP-07; `SRC-07` §3 G-04/G-08.
- **Scope:** Scope identifiers, per-scope versus shared index, retrieval-time
  policy checks, RLS/projection boundaries, provenance, cache behavior, and
  cross-tenant adversarial tests.
- **Non-scope:** Production search service, ranking quality optimization, or
  profile-C rollout.
- **Required source mix/count:** At least 4 source classes: ontology/scope,
  architecture/data model, authorization/security, and one retrieval isolation
  test method; at least 3 scopes and 6 isolation test cases.
- **Claim classes:** `security_invariant`, `architecture_tradeoff`,
  `scope_fact`, `test_measurement`, and `residual_risk`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is QA3 scope
  contract, leakage probes, and profile-specific isolation limits.
- **Adversarial/near-miss eval probes (≥2):**
  - A query with a valid object ID but a caller from another scope must return
    deny/empty without revealing existence through timing or error detail.
  - A shared-index cache hit for a revoked or moved object must not return stale
    content to the old scope.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: at least 3 scopes and 6 cross-scope/caching/revocation cases;
    0 unauthorized content disclosures in the reported fixture set.
  - Binary: QA3 selects per-scope, shared-RLS, or a profile split with explicit
    policy, residual risk, and migration trigger.
  - Binary: both probes pass and provenance/scope fields survive projection.
- **Stop/escalation condition:** Escalate on any cross-scope disclosure,
  unverifiable cache invalidation, or requirement for admin-blind indexing that
  conflicts with the documented profile-C boundary.
- **Bundle path:** `research/tickets/stage-1/S1-007/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-007 QA3 retrieval and index isolation per scope versus shared RLS" --bundle "research/tickets/stage-1/S1-007/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-008 — Revocation latency validation (≤5 seconds)

- **Status:** `PASS_WITH_LIMITS` — measured 2026-09-02 (research revision 13):
  goal `goal_R1HBV59V3M5K2NQA01M1FR8JFG`, campaign
  `rcamp_HDQSGD00K22QGT7601M1FR8JFG`, evaluation
  `reval_5KWTDGVVXHB1M2VG01M1FR8JJC`, artifact chain
  `e5ce35fe9c0acc46771f5b925918b65ad9f9c113bff513024fc60b942c5ab4a9`,
  evidence-pack content-addressed at
  `results/evidence/evidence-pack-ba5e689d8d61ca304e99f4caac028ffd89a05e6b31b41d218b95041b2d72637c.json`.
  Main and independent rerun each: 4 paths × 2 cache × 3 loads × 3 seeds ×
  5 trials = 360 matrix trials, plus 24 fault scenarios = **384 mandatory**;
  18 probes A–F = **402 total** per run. Both raw A/B archives contain 402
  content-digested members, with 0 hard-counter violations; measured max
  latency was 1.125 ms (A) / 1.169 ms (B), below the 5000 ms research bound.
  All adversarial probes A–F detected fail-closed. Limits: same-host model-only
  enforcement (no production topology); process-separated (not external)
  auditor; local model cannot prove absence of all network/cache side channels.
- **Priority:** `P0`
- **Wave:** `W2`
- **Owner:** `security`
- **Dependencies:** `S1-002, S1-004`
- **Research question:** Can the platform enforce the contract that new
  authorization decisions observe revocation within ≤5 seconds across gateway,
  retrieval, delegation, and cached projections?
- **Decision enabled:** Decide whether the ≤5-second value remains a bounded
  research target, needs a profile-specific limit, or must be withdrawn.
- **Source evidence:** `SRC-07` §3 G-08 and §5 step 1; `SRC-06` §2.3,
  §7 INV5, §8 revocation bound; `SRC-03` §3–4; `SRC-08` §4–5; `SRC-09`
  round-13 corrections.
- **Scope:** Revoke state transition, propagation path, cache invalidation,
  deny decision timestamp, clock assumptions, and unknown/outage behavior.
- **Non-scope:** A production SLA, legal/security certification, or revocation
  semantics outside the documented grant state machine.
- **Required source mix/count:** At least 3 source classes: authorization
  model, runtime propagation, and measured/trace method; at least 30 revocation
  traces spanning 3 components and cold/warm cache cases.
- **Claim classes:** `security_invariant`, `latency_measurement`, `target`,
  `failure_mode`, and `operational_limit`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is the revocation
  trace, clock/availability assumptions, and escalation path.
- **Adversarial/near-miss eval probes (≥2):**
  - Revoke immediately before a cached authorization check; any new allow after
    the stated bound, or an unmeasured clock assumption, must be surfaced.
  - Drop one propagation hop and return an unknown result; the system must deny
    or reconcile rather than silently allow.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: at least 30 traces across gateway, retrieval, and delegation,
    with observed revoke-to-deny latency and clock assumptions; every observed
    value must be ≤5 seconds to support the target.
  - Binary: failures, outages, and unknown outcomes have explicit deny or
    reconciliation behavior; no production SLA language appears.
  - Binary: both probes pass and INV5 remains true.
- **Stop/escalation condition:** Escalate immediately on any unauthorized allow
  after the bound, missing timestamp provenance, or a component that cannot
  participate in revocation.
- **Bundle path:** `research/tickets/stage-1/S1-008/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-008 revocation latency validation at most 5 seconds" --bundle "research/tickets/stage-1/S1-008/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-009 — MCP/A2A delegation and knowledge semantics roadmap

- **Status:** `READY`
- **Priority:** `P1`
- **Wave:** `W2`
- **Owner:** `architecture`
- **Dependencies:** `S1-001, S1-005`
- **Research question:** Which delegation, ownership, knowledge-promotion, and
  budget semantics are absent from current MCP/A2A surfaces, and what adapter
  contract keeps the canonical hub envelope provider-neutral?
- **Decision enabled:** Resolve G-02/H9 with an adapter roadmap and boundary
  between protocol transport/task/tool features and hub governance semantics.
- **Source evidence:** `SRC-07` §1 and §3 G-02; `SRC-01` §4 A1/A4/A6 and
  §14 SV1–SV3; `SRC-03` §5; `SRC-02` EP-03/EP-05/EP-06; `SRC-09` round-13
  MCP Tasks update.
- **Scope:** Current MCP/A2A task/tool/agent-card semantics, exact-action
  delegation, ownership, promotion, budgets, provenance, and adapter versioning.
- **Non-scope:** Replacing either protocol, claiming protocol standardization,
  or implementing a production adapter.
- **Required source mix/count:** At least 4 sources: one current MCP primary,
  one current A2A primary, one independent interoperability survey, and one
  hub feature/architecture consumer; map at least 7 semantic capabilities.
- **Claim classes:** `protocol_fact`, `gap`, `adapter_contract`,
  `design_inference`, and `roadmap_decision`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is the
  capability matrix, canonical envelope, and versioned adapter roadmap.
- **Adversarial/near-miss eval probes (≥2):**
  - A protocol task or tool result must not be interpreted as a delegation grant
    or knowledge promotion without the hub's explicit governance record.
  - An adapter that accepts model-provided capabilities without registry/policy
    verification must fail the exact-action boundary.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: matrix covers transport, tasks, tools, agent identity,
    delegation, ownership, knowledge promotion, budgets, and provenance, with at
    least 2 current revision references.
  - Binary: each missing semantic has an adapter field/translation or an
    explicit non-support decision; no production integration is claimed.
  - Binary: both probes pass and source revisions are timestamped.
- **Stop/escalation condition:** Escalate if a protocol revision is unavailable,
  if a translation changes authorization meaning, or if the roadmap requires
  protocol changes outside the hub's control.
- **Bundle path:** `research/tickets/stage-1/S1-009/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-009 MCP A2A delegation and knowledge semantics adapter roadmap" --bundle "research/tickets/stage-1/S1-009/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-010 — Tool-poisoning detection evaluation

- **Status:** `READY`
- **Priority:** `P0`
- **Wave:** `W3`
- **Owner:** `security`
- **Dependencies:** `S1-001, S1-009`
- **Research question:** Which layered controls detect malicious or misleading
  tool manifests and outputs, and when must the gateway quarantine or require
  human approval rather than trust a scanner?
- **Decision enabled:** Resolve G-07 with a detection/evidence contract for
  EP-06, including false-positive/false-negative reporting and quarantine.
- **Source evidence:** `SRC-07` §2 and §3 G-07; `SRC-01` §11 I-domain and
  §4 M17/M18; `SRC-02` EP-06; `SRC-03` §3.4; `SRC-08` §2 and §4; `SRC-09`
  round-13 journal.
- **Scope:** Manifest scanning, digest/SBOM signals, output sanitization,
  capability diff, quarantine, approval, and tool supply-chain near misses.
- **Non-scope:** A universal detector, production tool registry rollout, or
  treating heuristic scan output as proof of safety.
- **Required source mix/count:** At least 4 sources: threat taxonomy, primary
  tool/security guidance, gateway architecture, and an evaluation method; at
  least 12 cases (4 benign, 4 malicious, 4 near-miss/ambiguous).
- **Claim classes:** `threat_fact`, `detection_measurement`, `risk`,
  `abstention`, and `control_decision`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is threat corpus,
  layered controls, quarantine semantics, and residual risk.
- **Adversarial/near-miss eval probes (≥2):**
  - A benign tool with an unusual but declared capability must not be quarantined
    solely by a high-entropy or keyword heuristic.
  - A malicious output that asks the model to expand capabilities or exfiltrate
    a secret must be rejected/quarantined even when its manifest is valid.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: at least 12 fixed cases with per-class precision/recall or
    abstention counts; 0 critical malicious cases pass unquarantined.
  - Binary: every uncertain case has human approval or quarantine, and external
    content cannot expand capabilities.
  - Binary: both probes pass and limitations of heuristic detection are explicit.
- **Stop/escalation condition:** Escalate on any critical poison that reaches an
  effect-capable path, on unavailable case provenance, or on a request to claim
  universal detection from a small corpus.
- **Bundle path:** `research/tickets/stage-1/S1-010/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-010 tool poisoning detection evaluation" --bundle "research/tickets/stage-1/S1-010/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-011 — Minimal knowledge gate: promote/challenge versus argumentation/TMS

- **Status:** `READY`
- **Priority:** `P0`
- **Wave:** `W1`
- **Owner:** `knowledge`
- **Dependencies:** `S1-001, S1-003`
- **Research question:** Is a minimal two-status promote/challenge gate safer
  and more operable for the first knowledge layer than a full argumentation or
  truth-maintenance system, while preserving retraction and provenance?
- **Decision enabled:** Resolve G-06 and choose the MVP knowledge-gate state
  machine, deferring or accepting richer argumentation with explicit evidence.
- **Source evidence:** `SRC-07` §3 G-06; `SRC-06` §5 and §9 limitation 3;
  `SRC-05` §3.2, §7, and §9 Q3; `SRC-02` EP-07; `SRC-08` §4.
- **Scope:** Promote/challenge/retract states, evidence gate, independence,
  challenge handling, TMS/argumentation comparison, operator load, and
  downstream audit/provenance.
- **Non-scope:** Building a production knowledge graph, autonomous truth
  resolution, or treating reputation as enforcement authority.
- **Required source mix/count:** At least 4 sources: knowledge/provenance,
  argumentation/TMS, current ontology, and UX/operator evidence; compare at
  least 2 designs across 5 dimensions.
- **Claim classes:** `knowledge_fact`, `design_inference`, `hypothesis`,
  `operator_risk`, and `decision`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is the lifecycle,
  evidence independence, challenge/retraction path, and MVP tradeoff.
- **Adversarial/near-miss eval probes (≥2):**
  - A message with one source and no independent provenance must not promote,
    even if its text agrees with an existing claim.
  - A challenge/retraction must invalidate the derived knowledge view without
    deleting the immutable assertion or audit history.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: compare promote/challenge and argumentation/TMS across at
    least 5 dimensions and define every lifecycle transition.
  - Binary: one MVP recommendation states evidence threshold, challenge action,
    retraction behavior, and operator escalation; no truth oracle is claimed.
  - Binary: both probes pass and S1-003 shape/lifecycle semantics remain aligned.
- **Stop/escalation condition:** Escalate if no design can preserve immutable
  provenance and retraction, if operator work is unbounded, or if a proposal
  would let external content change policy/capabilities.
- **Bundle path:** `research/tickets/stage-1/S1-011/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-011 minimal knowledge gate promote challenge versus argumentation TMS" --bundle "research/tickets/stage-1/S1-011/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-012 — Evidence granularity, independence, and Beta/Sybil calibration

- **Status:** `READY`
- **Priority:** `P0`
- **Wave:** `W2`
- **Owner:** `knowledge`
- **Dependencies:** `S1-001, S1-003, S1-011`
- **Research question:** What evidence unit (document, span, or digest) and
  provenance/independence rule gives a defensible promotion gate, and how should
  Beta/reputation parameters be calibrated against Sybil and collusion cases?
- **Decision enabled:** Resolve ontology Q3 and G-05; choose evidence
  granularity, correlation caps, and whether Beta/EigenTrust is recommendation
  only rather than enforcement.
- **Source evidence:** `SRC-07` §3 G-05 and §5 step 5; `SRC-06` §5–6 and §9
  limitations 2, 3, and 5; `SRC-05` §7 and §9 Q3; `SRC-01` §1/§3; `SRC-08`
  §4; `SRC-09` rounds 9 and 13.
- **Scope:** Evidence units, canonical/publisher provenance, independence
  groups, dedup/correlation caps, Beta prior/decay, Sybil/collusion scenarios,
  and calibration metrics.
- **Non-scope:** Production reputation service, automatic trust enforcement,
  or a claim that current numeric thresholds are empirically validated.
- **Required source mix/count:** At least 5 sources: provenance/ontology,
  reputation mathematics, threat/collusion evidence, source registry policy,
  and knowledge-gate design; at least 3 granularity options and 3 Sybil/
  collusion scenarios.
- **Claim classes:** `provenance_fact`, `measurement`, `model_parameter`,
  `security_risk`, `design_inference`, and `calibration_limit`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is granularity,
  independence/correlation, Beta sensitivity, and Sybil/collusion limits.
- **Adversarial/near-miss eval probes (≥2):**
  - Two mirrors from the same publisher must collapse to one independent unit,
    not satisfy `n_independent ≥ 2`.
  - A colluding cluster with high positive ratings but no pretrusted anchor must
    not raise an enforcement allow decision; it may only produce a flagged
    recommendation.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: compare document/span/digest granularity, run at least 3
    Sybil/collusion scenarios, and report sensitivity for `a0=b0=1`, decay, and
    the planning threshold `P[θ>0.9] ≥ 0.95` as assumptions unless measured.
  - Binary: every accepted evidence unit carries canonical source, publisher,
    independence group, and provenance; Beta/EigenTrust is explicitly outside
    enforcement.
  - Binary: both probes pass and the auditor confirms no mirror/Sybil double count.
- **Stop/escalation condition:** Escalate if independence cannot be established,
  if numeric calibration depends on a missing corpus, or if anyone proposes
  reputation as a substitute for policy authorization.
- **Bundle path:** `research/tickets/stage-1/S1-012/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-012 evidence granularity independence and Beta reputation Sybil collusion calibration" --bundle "research/tickets/stage-1/S1-012/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-013 — 15–20-person comprehension and approval-fatigue pilot

- **Status:** `READY`
- **Priority:** `P1`
- **Wave:** `W3`
- **Owner:** `hci`
- **Dependencies:** `S1-011, S1-012`
- **Research question:** Can 15–20 representative participants understand
  delegation, scope, provenance, and stop controls, and what approval volume
  causes fatigue by role (QM2, G-01, G-09)?
- **Decision enabled:** Calibrate the comprehension thresholds, approval
  packaging, N_prompts/hour hypotheses, and pilot evidence needed for UX gates.
- **Source evidence:** `SRC-04` §3, §7, and §8 QM2; `SRC-07` §3 G-01/G-09
  and §5 step 3; `SRC-08` §1/§5 (no user study); `SRC-02` EP-10; `SRC-01`
  §11 K-domain.
- **Scope:** A bounded human-subject comprehension/approval-fatigue pilot,
  five stated comprehension questions, role/task framing, consent and
  anonymized results, and attention-budget observations.
- **Non-scope:** General population claims, legal/medical conclusions, product
  launch, or claiming the pilot represents all deployments.
- **Required source mix/count:** At least 3 evidence classes: current mental
  model, HCI/permission-fatigue literature, and a preregistered pilot protocol;
  exactly 15–20 participants, with role balance and a documented exclusion rule.
- **Claim classes:** `HCI_measurement`, `user_observation`, `hypothesis`,
  `design_inference`, and `limitation`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is protocol,
  comprehension measures, approval-fatigue data, and participant limits.
- **Adversarial/near-miss eval probes (≥2):**
  - A participant who can repeat a banner but cannot identify who may read a
    private space must fail comprehension rather than be counted as calibrated.
  - A high approval count produced by an intentionally impossible task must not
    be used as a general N_prompts/hour threshold.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: exactly 15–20 participants; report the five measures with
    targets ≥90%, ≥95%, ≥85%, ≥95% “no”, and stop-control time ≤30 seconds as
    hypotheses/observations, not universal facts.
  - Quantitative: report N_prompts/hour by role with confidence/uncertainty and
    approval-fatigue observations; missing data is explicit.
  - Binary: consent, anonymization, both probes, and distinct audit are recorded.
- **Stop/escalation condition:** Stop if consent/role framing is inadequate,
  sample size falls outside 15–20, a participant-risk issue appears, or a
  stakeholder asks for a legal/high-risk classification (re-enter PARK-01).
- **Bundle path:** `research/tickets/stage-1/S1-013/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-013 15 to 20 person comprehension and approval fatigue pilot" --bundle "research/tickets/stage-1/S1-013/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-014 — Claim-dispute visualization: card versus graph

- **Status:** `READY`
- **Priority:** `P1`
- **Wave:** `W4`
- **Owner:** `hci`
- **Dependencies:** `S1-011, S1-013`
- **Research question:** Do users resolve claim disputes more accurately and
  with less overload using a compact evidence card or an argumentation graph
  (QM1)?
- **Decision enabled:** Select the default dispute visualization and progressive
  disclosure pattern, or retain a justified split by task complexity.
- **Source evidence:** `SRC-04` §3, §4, §7, and §8 QM1; `SRC-07` §3 G-01/G-09;
  `SRC-02` EP-07/EP-10; `SRC-01` §11 K6–K10; `SRC-08` §5 (no user study).
- **Scope:** Two visualization variants, equivalent dispute tasks, evidence
  provenance visibility, comprehension/error/latency measures, and overload
  observations.
- **Non-scope:** Building a production UI, replacing the knowledge model, or
  treating a card/graph preference as a security guarantee.
- **Required source mix/count:** At least 3 sources: mental model, HCI
  visualization/permission evidence, and S1-011/S1-012 decision artifacts; at
  least 2 variants and 4 matched dispute tasks.
- **Claim classes:** `HCI_measurement`, `usability_observation`,
  `design_inference`, `accessibility_risk`, and `decision`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is the matched
  card/graph experiment, progressive disclosure, and error taxonomy.
- **Adversarial/near-miss eval probes (≥2):**
  - A graph that exposes more nodes but hides the canonical source or
    independence group must fail provenance visibility.
  - A card that shows only the winning claim and hides a challenge must fail
    dispute comprehension even if task time is lower.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: at least 2 variants and 4 matched tasks; report accuracy,
    provenance recall, task time, and overload/error counts by variant.
  - Binary: choose card, graph, or task-dependent split with explicit evidence;
    no production UI is shipped.
  - Binary: both probes pass and results are linked to S1-013 sample limits.
- **Stop/escalation condition:** Escalate if variants are not task-equivalent,
  provenance is hidden by either design, or a request exceeds the pilot's
  consent/scope boundary.
- **Bundle path:** `research/tickets/stage-1/S1-014/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-014 claim dispute visualization card versus graph" --bundle "research/tickets/stage-1/S1-014/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-015 — Petname principal naming study

- **Status:** `READY`
- **Priority:** `P2`
- **Wave:** `W4`
- **Owner:** `hci`
- **Dependencies:** `S1-013`
- **Research question:** Can personal petnames make canonical principal IDs
  easier to recognize without creating ambiguity, spoofing, or an authorization
  path that bypasses canonical identity (QM3)?
- **Decision enabled:** Decide whether petnames are a display-only aid, which
  disambiguation cues are required, and when the feature should be deferred.
- **Source evidence:** `SRC-04` §2, §3, §7, and §8 QM3; `SRC-01` §11 G16/K
  references; `SRC-07` §3 G-01/G-09; `SRC-02` EP-01/EP-10; `SRC-08` §2.
- **Scope:** Display-only naming, collision/disambiguation, on-behalf banners,
  canonical-ID reveal, recognition tasks, and accessibility/forgetting cases.
- **Non-scope:** Changing principal identity, authorization lookup keys,
  cross-tenant naming, or production directory rollout.
- **Required source mix/count:** At least 3 sources: mental model, naming/
  recognition evidence, and identity/security contract; at least 20 naming
  cases including collisions and stale/renamed petnames.
- **Claim classes:** `HCI_measurement`, `identity_invariant`,
  `design_inference`, `spoofing_risk`, and `decision`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is display-only
  mapping, canonical-ID cues, collision evidence, and QM3 limits.
- **Adversarial/near-miss eval probes (≥2):**
  - Two principals with the same petname must remain distinguishable by stable
    canonical ID and scope; a name-only approval must fail.
  - A renamed or deleted petname must not change historical audit identity or
    make a previous on-behalf action appear to belong to another principal.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: at least 20 cases with collision, rename, stale-cache, and
    accessibility variants; report recognition/error rates.
  - Binary: petname is display-only, canonical IDs are always available, and no
    auth/policy record keys on the petname.
  - Binary: both probes pass and any improvement is labelled a pilot observation.
- **Stop/escalation condition:** Escalate on any identity ambiguity, approval
  spoofing, or requirement to use petnames as canonical identifiers.
- **Bundle path:** `research/tickets/stage-1/S1-015/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-015 petname principal naming study" --bundle "research/tickets/stage-1/S1-015/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-016 — Workspace lineage: flat scope versus PROV-Dictionary

- **Status:** `READY`
- **Priority:** `P1`
- **Wave:** `W3`
- **Owner:** `formal`
- **Dependencies:** `S1-003, S1-007`
- **Research question:** Should workspace lineage use a flat scope field in
  runtime and reserve PROV-Dictionary-style insertion/deletion lineage for
  export, or is a richer runtime representation justified (ontology Q1)?
- **Decision enabled:** Resolve ontology Q1 without weakening scope isolation,
  immutable provenance, or audit reconstruction.
- **Source evidence:** `SRC-05` §4 and §9 Q1; `SRC-01` §10 F7–F9; `SRC-03` §4
  data model; `SRC-08` §4 platform-subject/provenance fixes; `SRC-09`
  rounds 9 and 13.
- **Scope:** Workspace/scope identity, insertion/deletion lineage, export
  projection, immutable artifact versions, and cross-scope move/copy semantics.
- **Non-scope:** A production PROV store, arbitrary graph query service, or
  relaxing the single-scope invariant.
- **Required source mix/count:** At least 4 sources: ontology/PROV, data model,
  scope-security, and audit evidence; compare 2 representations over at least
  5 lineage operations.
- **Claim classes:** `ontology_fact`, `provenance_invariant`, `tradeoff`,
  `design_inference`, and `decision`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is Q1 lineage
  comparison, round-trip export, and scope invariants.
- **Adversarial/near-miss eval probes (≥2):**
  - Copying an artifact to another workspace must create a new operation/version
    and never rewrite the original `located_in` scope.
  - Deleting an inserted member from a derived view must not erase the immutable
    provenance needed to explain the earlier membership.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: compare both representations across at least 5 insertion,
    deletion, move, copy, and export operations; 0 orphan provenance links.
  - Binary: Q1 selects flat runtime, PROV-Dictionary runtime, or a split with
    explicit export semantics; INV2/scope isolation remains intact.
  - Binary: both probes pass and the audit can reconstruct the operation chain.
- **Stop/escalation condition:** Escalate if a lineage representation requires
  mutable historical artifacts, permits multiple runtime scopes, or cannot
  round-trip a move/copy without ambiguity.
- **Bundle path:** `research/tickets/stage-1/S1-016/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-016 workspace lineage flat scope versus PROV Dictionary" --bundle "research/tickets/stage-1/S1-016/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-017 — STIT/ATL responsibility analytics placement

- **Status:** `READY`
- **Priority:** `P2`
- **Wave:** `W4`
- **Owner:** `formal`
- **Dependencies:** `S1-004, S1-016`
- **Research question:** Can STIT/ATL annotations explain responsibility and
  available alternatives in audit analytics, and where must they remain
  offline rather than enter runtime authorization (ontology Q2)?
- **Decision enabled:** Resolve Q2 by placing responsibility analytics in an
  offline/export layer or documenting a tightly bounded runtime annotation.
- **Source evidence:** `SRC-05` §4 and §9 Q2; `SRC-01` §10 L5/L6; `SRC-06`
  §1–2 and §7; `SRC-03` §4 audit/provenance; `SRC-08` §2–4.
- **Scope:** Responsibility vocabulary, alternatives/choice traces, STIT/ATL
  mapping, audit explanation, and three bounded scenarios.
- **Non-scope:** Replacing policy authorization, making modal logic an
  enforcement oracle, or building a production model checker.
- **Required source mix/count:** At least 3 sources: ontology, formal logic,
  and audit/runtime semantics; at least 3 scenarios with one denial, one
  delegation, and one revoked-grant case.
- **Claim classes:** `formal_semantics`, `audit_explanation`, `design_inference`,
  `runtime_boundary`, and `limitation`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is Q2 scenario
  semantics, audit placement, and the non-enforcement boundary.
- **Adversarial/near-miss eval probes (≥2):**
  - An STIT/ATL annotation that recommends `allow` despite a gateway deny must
    remain an explanation only and cannot change the decision.
  - A responsibility graph that omits the delegator or revocation event must
    fail trace completeness.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: at least 3 scenarios with actor, choice, grant, scope, and
    audit trace; 100% of runtime authorization outcomes remain gateway-owned.
  - Binary: Q2 chooses offline analytics, export annotation, or a bounded
    runtime field with explicit semantics and no policy authority.
  - Binary: both probes pass and formal claims identify their model limits.
- **Stop/escalation condition:** Escalate if annotations can alter policy,
  responsibility is underdetermined by available audit data, or a required
  logic tool is unavailable without a bounded fallback.
- **Bundle path:** `research/tickets/stage-1/S1-017/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-017 STIT ATL responsibility analytics placement" --bundle "research/tickets/stage-1/S1-017/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-018 — Profile-C MLS + TEE attested-indexer PoC research

- **Status:** `READY`
- **Priority:** `P1`
- **Wave:** `W4`
- **Owner:** `privacy`
- **Dependencies:** `S1-007, S1-008, S1-009`
- **Research question:** What evidence is needed to decide whether profile C
  can combine MLS confidentiality with a TEE/attested indexer without leaking
  scope, keys, or unverifiable trust assumptions?
- **Decision enabled:** Resolve G-04 with a research-scoped PoC decision and a
  conditional adapter/rollout roadmap, not a production approval.
- **Source evidence:** `SRC-07` §3 G-04 and §5 step 4; `SRC-01` §11 G3/G3b;
  `SRC-02` EP-12; `SRC-03` §6 topologies B/C and §9; `SRC-08` §1/§5;
  `SRC-09` round-4 and round-13 journal.
- **Scope:** MLS group/key lifecycle, attestation evidence, encrypted index
  queries, scope isolation, revocation interaction, threat model, and a
  bounded prototype if it is needed as evidence.
- **Non-scope:** Production rollout, procurement, deployment-specific legal or
  high-risk classification, or an assertion that a TEE is trusted by default.
- **Required source mix/count:** At least 4 sources: MLS primary standards,
  TEE/attestation primary material, architecture/profile-C model, and a threat
  or privacy analysis; at least 3 threat cases and 2 attestation failure cases.
- **Claim classes:** `privacy_invariant`, `protocol_fact`, `PoC_measurement`,
  `threat_model`, `design_inference`, and `rollout_condition`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is profile-C
  threat model, attestation evidence, encrypted-indexer boundaries, and
  explicitly non-production prototype evidence.
- **Adversarial/near-miss eval probes (≥2):**
  - A failed or stale attestation must deny index access and must not reveal
    plaintext through an error path.
  - A revoked MLS member with a valid cached index token must not retrieve new
    scope content; the result must connect to S1-008's revocation trace.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: at least 3 threat cases, 2 attestation failures, key/member
    lifecycle traces, and a measured or explicitly unavailable leakage result.
  - Binary: PoC evidence, if used, is confined to research and includes a
    threat-model/attestation limitation; no production rollout is declared.
  - Binary: both probes pass and profile-C conditions are linked to QA3/revocation.
- **Stop/escalation condition:** Stop on plaintext leakage, unverifiable
  attestation, missing MLS key lifecycle evidence, or a request to roll out
  profile C; re-enter PARK-04 for rollout.
- **Bundle path:** `research/tickets/stage-1/S1-018/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-018 profile C MLS TEE attested indexer PoC research" --bundle "research/tickets/stage-1/S1-018/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-019 — P0 platform architecture decision synthesis and prototype evidence

- **Status:** `READY`
- **Priority:** `P0`
- **Wave:** `W5`
- **Owner:** `synthesis`
- **Dependencies:** `S1-004, S1-005, S1-006, S1-007, S1-008, S1-009, S1-010, S1-011, S1-012, S1-013, S1-014, S1-015, S1-016, S1-017, S1-018`
- **Research question:** Given the completed Stage 1 evidence, what P0
  architecture decisions and bounded prototype evidence are justified for
  EP-01–EP-05 and EP-08, and what remains explicitly non-production?
- **Decision enabled:** Produce a single research-scoped decision synthesis,
  including architecture boundaries, evidence-backed assumptions, and a
  prototype/evidence backlog without silently converting research into build
  authorization.
- **Source evidence:** `SRC-00` §Definition of Done and §Controlled deviation;
  `SRC-02` EP-01–EP-05 and EP-08; `SRC-03` §1–8; `SRC-06` §8–9; `SRC-07` §5
  step 2 and §6; `SRC-08` §5; `SRC-09` §Status artifacts.
- **Scope:** Cross-ticket synthesis, P0 architecture decisions, traceability,
  risk/assumption ledger, and a bounded prototype used only as evidence.
- **Non-scope:** Production implementation, deployment, rollout, new external
  integrations, or moving a Goal to `ACCEPTED`.
- **Required source mix/count:** All completed active-ticket evidence packs
  (S1-001..S1-018) plus the ten source aliases; all EP-01..EP-05 and EP-08
  decision rows must have at least one direct ticket and one independent audit
  reference.
- **Claim classes:** `synthesis`, `decision`, `assumption`, `prototype_measurement`,
  `residual_risk`, and `non_goal`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is the P0
  decision matrix, cross-ticket traceability, and prototype-as-evidence limit.
- **Adversarial/near-miss eval probes (≥2):**
  - A prototype result with no reproducible input, version, or artifact hash
    must not support a P0 decision.
  - A synthesis that labels an unmeasured planning number as an SLO or marks a
    research pass as Goal `ACCEPTED` must fail the boundary check.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: every EP-01..EP-05 and EP-08 decision row maps to at least one
    active ticket and one evidence/audit reference; all S1-001..S1-018 results
    are represented with status and limits.
  - Binary: platform plan contains Scope, Architecture, Workstreams,
    Milestones, Verification, Risks, and Open decisions, and labels any
    prototype as research-only.
  - Binary: both probes pass; no production artifact or Goal acceptance is
    claimed.
- **Stop/escalation condition:** Escalate if an upstream result is missing,
  contradictory, unaudited, or if synthesis requires a production build or
  deployment-specific legal/high-risk determination (PARK-01).
- **Bundle path:** `research/tickets/stage-1/S1-019/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-019 P0 platform architecture decision synthesis and prototype evidence" --bundle "research/tickets/stage-1/S1-019/bundle.json" --db ".agentos-research/platform-stage-1"
```

### S1-020 — Independent phase audit and closure decision

- **Status:** `READY`
- **Priority:** `P0`
- **Wave:** `W6`
- **Owner:** `audit`
- **Dependencies:** `S1-001, S1-002, S1-003, S1-004, S1-005, S1-006, S1-007, S1-008, S1-009, S1-010, S1-011, S1-012, S1-013, S1-014, S1-015, S1-016, S1-017, S1-018, S1-019`
- **Research question:** Does the complete active portfolio meet the common
  evidence/closure gate with a genuinely independent auditor, and which items
  must remain `PASS_WITH_LIMITS`, `BLOCKED`, or parked?
- **Decision enabled:** Make the Stage 1 research closure decision and publish
  the evidence-calibrated limits and next phase entry conditions.
- **Source evidence:** `SRC-00` §Definition of Done; `SRC-01` §1–3 and §15;
  `SRC-07` §3–6; `SRC-08` §1–6; `SRC-09` §Status artifacts and round-13
  correction log; all ticket-specific evidence packs S1-001..S1-019.
- **Scope:** Independent audit, coverage/traceability, chain/evidence/wiki
  freshness, probe results, status justification, and final research closure.
- **Non-scope:** Executing missing research, production certification, legal
  qualification, mass verification of 176 `u` sources, or release acceptance.
- **Required source mix/count:** All 19 prior active-ticket bundles/evidence
  packs plus all 10 source aliases; at least one auditor identity distinct from
  the subject producer and one coverage check per open-item family.
- **Claim classes:** `audit_finding`, `coverage`, `evaluation_result`,
  `limitation`, `closure_decision`, and `next_step`.
- **FLOW-11 requirement:** Produce all eleven artifacts
  (`research_plan`, `source_registry`, `feature_catalog`, `architecture_models`,
  `mental_model`, `ontology`, `mathematical_model`, `synthesis_and_gaps`,
  `independent_audit`, `platform_plan`, `progress`); emphasis is the
  independent closure record, common-gate booleans, reverse coverage, and
  explicit remaining limits.
- **Adversarial/near-miss eval probes (≥2):**
  - A stale evidence pack with `chain_fresh=false` or
    `latest_evaluation_valid=false` must prevent closure even when every ticket
    text says PASS.
  - An auditor identity equal to the subject producer, or a missing ticket
    probe, must fail the closure decision rather than be waived in prose.
- **Acceptance criteria (binary/quantitative):**
  - Quantitative: 20 active ticket IDs and 4 parked IDs are accounted for,
    every active dependency resolves, and every open-item row in the coverage
    matrix has a ticket mapping.
  - Binary: status is `PASS` or explicitly justified `PASS_WITH_LIMITS`, the
    evidence-pack/v3 exists, `chain_fresh=true`,
    `latest_evaluation_valid=true`, wiki check is OK, auditor is distinct, and
    all 19 prior tickets' probes pass.
  - Binary: closure explicitly states that research-plan PASS is not Goal
    `ACCEPTED` and does not reopen parked rollout/legal work.
- **Stop/escalation condition:** Stop at `BLOCKED` if any common-gate boolean,
  dependency, ticket probe, or auditor-distinctness check fails; escalate the
  missing evidence to the owning ticket instead of overriding it.
- **Bundle path:** `research/tickets/stage-1/S1-020/bundle.json`
- **PowerShell command:**

```powershell
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-020 independent phase audit and closure decision" --bundle "research/tickets/stage-1/S1-020/bundle.json" --db ".agentos-research/platform-stage-1"
```

## Parked items and re-entry triggers

Parked work is explicit scope control, not a hidden failure. These items have no
active bundle or command in Stage 1; they re-enter only when the named trigger
is satisfied and a new dependency/owner decision is recorded.

| ID | Status | Parked item | Why parked now | Re-entry trigger |
|---|---|---|---|---|
| `PARK-01` | `PARKED` | Deployment-specific legal/high-risk classification | The evidence states Art. 14 applicability is conditional; Stage 1 has no named deployment, jurisdiction, counsel, or risk classification. | A named deployment/jurisdiction, system role, intended use, and qualified legal/regulatory review are supplied; then create a scoped ticket with explicit authority. |
| `PARK-02` | `PARKED` | Mass verification of every 176 `u` source | Targeted promotion/verification is active in S1-001; the registry explicitly does not claim line-by-line verification of all 176 `u` entries. | A decision requires the full `u` tail, with budget, access, verifier method, and a finite acceptance corpus approved; otherwise retain targeted verification. |
| `PARK-03` | `PARKED` | Production SLO claim | 34 events/s, p95, queueing, storage, and ≤5-second revocation are planning targets until benchmark evidence exists. | S1-002/S1-008 produce reproducible measurements under a named production-like workload, with CI/ops ownership and an explicit SLO review. |
| `PARK-04` | `PARKED` | Production rollout of profile C | S1-018 may produce PoC evidence only; production rollout needs threat, privacy, attestation, operations, and deployment review. | S1-018 PoC passes its threat/attestation probes, QA3/revocation evidence is current, and a separately approved deployment/rollout decision exists. |

## Bidirectional coverage matrix

The first tables map every named open item to one or more active/parked tickets.
The reverse table maps every active ticket back to source aliases and evidence
anchors, proving that no active ticket is orphaned from the evidence set.

### Gaps G-01..G-10

| Open item | Evidence anchor | Ticket mapping |
|---|---|---|
| G-01 — no peer-reviewed agent-delegation UX study | `SRC-07` §3 G-01; `SRC-08` §1/§5 | S1-013, S1-014, S1-015 |
| G-02 — MCP/A2A lack delegation/knowledge semantics | `SRC-07` §3 G-02 | S1-009 |
| G-03 — no quantitative agent-hub load model | `SRC-07` §3 G-03; `SRC-06` §9 limitation 1 | S1-002, S1-006, S1-019 |
| G-04 — weak TEE/confidential multi-agent evidence | `SRC-07` §3 G-04; `SRC-01` §11 G3/G3b | S1-018 |
| G-05 — Beta/EigenTrust not validated against LLM Sybil/collusion | `SRC-07` §3 G-05; `SRC-06` §9 limitations 2/5 | S1-001, S1-012 |
| G-06 — argumentation/TMS rarely production-tested | `SRC-07` §3 G-06 | S1-011 |
| G-07 — tool-poisoning detection remains open | `SRC-07` §3 G-07; `SRC-01` §11 I | S1-010 |
| G-08 — no cross-component revocation standard at ≤5s | `SRC-07` §3 G-08; `SRC-06` §8 | S1-008 |
| G-09 — no agent-interface comprehension metrics | `SRC-07` §3 G-09; `SRC-04` §7 | S1-013, S1-014 |
| G-10 — no ready deterministic LLM-agent simulation harness | `SRC-07` §3 G-10; `SRC-06` §7 limitation 4 | S1-004 |

### Architecture, human factors, and ontology questions

| Open item | Evidence anchor | Ticket mapping |
|---|---|---|
| QA1 — modular monolith versus multiple containers | `SRC-03` §9 QA1 | S1-005 |
| QA2 — in-process scheduler versus durable execution | `SRC-03` §9 QA2 | S1-006 |
| QA3 — per-scope index versus shared index with retrieval RLS | `SRC-03` §9 QA3 | S1-007 |
| QM1 — dispute visualization card versus graph | `SRC-04` §8 QM1 | S1-014 |
| QM2 — role-based N_prompts/hour calibration | `SRC-04` §8 QM2 | S1-013 |
| QM3 — petname vocabulary for principals | `SRC-04` §8 QM3 | S1-015 |
| Ontology Q1 — flat scope versus PROV-Dictionary lineage | `SRC-05` §9 Q1 | S1-016 |
| Ontology Q2 — STIT/ATL responsibility annotations | `SRC-05` §9 Q2 | S1-017 |
| Ontology Q3 — evidence document/span/digest granularity | `SRC-05` §9 Q3 | S1-012 |

### Mathematical model limitations 1–5

| Limitation | Evidence anchor | Ticket mapping |
|---|---|---|
| 1 — all numbers are planning estimates; benchmark required | `SRC-06` §9 limitation 1 | S1-002, S1-019, PARK-03 |
| 2 — Beta trust is sensitive to decay/attack and is UX-only | `SRC-06` §9 limitation 2 | S1-012 |
| 3 — argumentation weights need incident-corpus calibration | `SRC-06` §9 limitation 3 | S1-011, S1-012 |
| 4 — Alloy/TLA+/simulation properties are design obligations until run | `SRC-06` §9 limitation 4 | S1-003, S1-004, S1-020 |
| 5 — evidence independence needs Sybil/collusion calibration | `SRC-06` §9 limitation 5 | S1-001, S1-012 |

### Audit limits, registry deviation/tail, and next steps

| Explicit limit or recommendation | Evidence anchor | Ticket mapping |
|---|---|---|
| No benchmark evidence | `SRC-08` §5; `SRC-07` §4 | S1-002, S1-006, S1-008, PARK-03 |
| No user study | `SRC-08` §1/§5; `SRC-07` G-01/G-09 | S1-013, S1-014, S1-015 |
| No deployment-specific legal qualification | `SRC-08` §1; `SRC-07` §1/§4 | PARK-01; S1-013 and S1-018 escalate to it when encountered |
| No runtime `rdflib`, `pySHACL`, or `llm_verifier` execution | `SRC-08` §5 | S1-003, S1-020 |
| Planning numbers (34 events/s, p95, 41,820 pairs, `L_auth≈0.68`, storage, ≤5s) | `SRC-06` §8–9; `SRC-08` §5 | S1-002, S1-008, S1-019, PARK-03 |
| Remaining quantitative assumptions (205 agents/225 principals, four PDP workers, ≤82 external calls/min, `F_max≤10`, `κ_run≤3`) | `SRC-06` §8–9 | S1-002, S1-004, S1-012, S1-019 |
| 176 `u` sources remain outside line-by-line verification | `SRC-01` §3/§15; `SRC-07` §4; `SRC-08` §1 | S1-001, PARK-02 |
| Source-registry controlled deviation (247 positions/246 valid, 118 curated core) | `SRC-00` §Controlled deviation; `SRC-01` §1; `SRC-08` §1 | S1-001, S1-020 |
| Source-registry Z/SV controlled tail and targeted spot checks | `SRC-01` §13–15 | S1-001, S1-009 |
| Recommended next step 1 — benchmark envelope | `SRC-07` §5 step 1 | S1-002 |
| Recommended next step 2 — P0 prototype/synthesis | `SRC-07` §5 step 2 | S1-019 |
| Recommended next step 3 — comprehension/N_prompts pilot | `SRC-07` §5 step 3 | S1-013 |
| Recommended next step 4 — profile-C MLS + TEE PoC | `SRC-07` §5 step 4 | S1-018 |
| Recommended next step 5 — promote cited `u` sources; do not mass-verify by implication | `SRC-07` §5 step 5 | S1-001, PARK-02 |

### Reverse ticket → source mapping

| Ticket | Evidence aliases and anchors |
|---|---|
| S1-001 | `SRC-00` deviation; `SRC-01` §1/§3/§13–15; `SRC-07` G-05/step 5; `SRC-08` §1/§5; `SRC-09` round 13 |
| S1-002 | `SRC-03` §3.1/§9; `SRC-06` §8–9; `SRC-07` G-03/step 1; `SRC-08` §5; `SRC-09` round 13 |
| S1-003 | `SRC-01` F4/F7–F9; `SRC-05` §3/§5/§7/§9; `SRC-08` §4–5; `SRC-09` rounds 11–13 |
| S1-004 | `SRC-01` L10/L11/L19; `SRC-06` §7/§9(4); `SRC-07` G-10; `SRC-08` §4; `SRC-09` rounds 9/13 |
| S1-005 | `SRC-02` EP-01–EP-05/EP-08; `SRC-03` §2/§6–§9; `SRC-07` step 2; `SRC-08` §5; `SRC-09` status |
| S1-006 | `SRC-02` EP-11; `SRC-03` §3.2/§5/§9 QA2; `SRC-06` §7; `SRC-07` G-03/G-10; `SRC-08` §5 |
| S1-007 | `SRC-02` EP-04/EP-07; `SRC-03` §4/§6/§9 QA3; `SRC-05` §1/§4/§9 Q1/Q3; `SRC-06` §1–2; `SRC-07` G-04/G-08 |
| S1-008 | `SRC-03` §3–4; `SRC-06` §2.3/§7/§8; `SRC-07` G-08; `SRC-08` §4–5; `SRC-09` round 13 |
| S1-009 | `SRC-01` A1/A4/A6/SV; `SRC-02` EP-03/EP-05/EP-06; `SRC-03` §5; `SRC-07` G-02; `SRC-09` MCP Tasks update |
| S1-010 | `SRC-01` M17/M18/I; `SRC-02` EP-06; `SRC-03` §3.4; `SRC-07` G-07; `SRC-08` §2/§4; `SRC-09` round 13 |
| S1-011 | `SRC-02` EP-07; `SRC-05` §3.2/§7/§9 Q3; `SRC-06` §5/§9(3); `SRC-07` G-06; `SRC-08` §4 |
| S1-012 | `SRC-01` §1/§3; `SRC-05` §7/§9 Q3; `SRC-06` §5–6/§9(2,3,5); `SRC-07` G-05/step 5; `SRC-08` §4; `SRC-09` rounds 9/13 |
| S1-013 | `SRC-01` K-domain; `SRC-02` EP-10; `SRC-04` §3/§7/§8 QM2; `SRC-07` G-01/G-09/step 3; `SRC-08` §1/§5 |
| S1-014 | `SRC-01` K6–K10; `SRC-02` EP-07/EP-10; `SRC-04` §3/§7/§8 QM1; `SRC-07` G-01/G-09; `SRC-08` §5 |
| S1-015 | `SRC-01` G16/K; `SRC-02` EP-01/EP-10; `SRC-04` §2/§3/§8 QM3; `SRC-07` G-01/G-09; `SRC-08` §2 |
| S1-016 | `SRC-01` F7–F9; `SRC-03` §4; `SRC-05` §4/§9 Q1; `SRC-08` §4; `SRC-09` rounds 9/13 |
| S1-017 | `SRC-01` L5/L6; `SRC-03` §4; `SRC-05` §4/§9 Q2; `SRC-06` §1–2/§7; `SRC-08` §2–4 |
| S1-018 | `SRC-01` G3/G3b; `SRC-02` EP-12; `SRC-03` §6; `SRC-07` G-04/step 4; `SRC-08` §1/§5; `SRC-09` rounds 4/13 |
| S1-019 | `SRC-00` DoD/deviation; `SRC-02` EP-01–EP-05/EP-08; `SRC-03` §1–8; `SRC-06` §8–9; `SRC-07` §5–6; `SRC-08` §5; `SRC-09` status |
| S1-020 | `SRC-00` DoD; `SRC-01` §1–3/§15; `SRC-07` §3–6; `SRC-08` §1–6; `SRC-09` status/journal; S1-001..S1-019 packs |

## Operator handoff and limits

To execute a ticket, first create its bounded bundle at the listed path through
the approved workflow, then run the exact command in that ticket from the repo
root. Do not infer that a missing bundle is a successful scaffold, and do not
copy external document text into a capability or policy channel. After the
command, inspect the returned evidence-pack/v3 path, freshness booleans, audit
identities, and wiki check before changing the ticket status.

The portfolio intentionally leaves four items parked: legal/high-risk
classification, mass verification of 176 `u` sources, production SLO claims,
and production rollout of profile C. These are re-entry conditions, not implied
claims of completion. The Stage 1 exit decision can be `PASS_WITH_LIMITS` while
those limits remain explicit.
