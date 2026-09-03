# S1-012 — Evidence granularity, independence, and Beta/Sybil calibration

Research ticket bundle (Stage 1, W2, P0, owner `knowledge`, dependencies
S1-001 + S1-003 + S1-011, all done). Research question: what evidence unit
(document, span, or digest) and provenance/independence rule gives a
defensible promotion gate, and how should Beta/reputation parameters be
calibrated against Sybil and collusion cases (ontology Q3, G-05)?

## Files

| File | Purpose |
|---|---|
| `bundle.json` | The bounded research bundle: config, 12 verified sources, 18 claims (all six ticket claim classes), 11 FLOW-11 artifacts, audit block (pass_with_limits), probes block. |
| `granularity_beta_probe.py` | Deterministic stdlib adversarial probe: P1 mirror collapse + document/span/digest granularity invariance, P2 three Sybil/collusion scenarios (colluding cluster with no pretrusted anchor can only produce a flagged recommendation), P3 Beta sensitivity table (a0=b0=1, decay {0, 0.02, 0.05}, P[θ>0.9] ≥ 0.95) labeled as model assumptions. Writes `probe-results.json` (25/25 checks). |
| `acceptance_probe.py` | Machine-checks the ticket acceptance criteria against the bundle: ≥5 verified sources across 5 classes, granularity comparison, ≥3 scenarios, assumption labeling, Beta/EigenTrust outside enforcement, per-unit provenance completeness, audit/double-count confirmation, probe wiring, platform sections. Writes `acceptance-results.json` (18/18 checks). |
| `probe-results.json` | Output of `granularity_beta_probe.py` (25/25 pass). |
| `acceptance-results.json` | Output of `acceptance_probe.py` (18/18 pass). |

## Decision (resolves ontology Q3 and G-05)

- **Granularity (Q3):** span-level `EvidenceUnit` — a named span inside a
  canonical resource pinned by canonical source + publisher + independence
  group + resolver version + metadata freeze, with optional content-digest
  pinning; document units are coarse spans and digest units are the frozen
  pinning mechanism. Dedup/correlation caps apply at the canonical-source
  level, so finer granularity never multiplies independence
  (probe-verified: document == span == digest → 1 independent unit per source).
- **Correlation caps:** one independent unit per (canonical_source_id,
  independence_group) pair is the hard enforcement floor; mirrors and
  co-authored spans collapse, never double count; content-Sybil mirrors
  (identical publisher + digest) are absorbed; per-group weight caps are
  recommendation-side parameters.
- **Beta/EigenTrust (G-05):** strictly recommendation-only — a flagged,
  `enforcement=false` advisory. Enforcement allow/reject comes only from the
  deterministic provenance gate (S1-003 promoted preconditions + S1-001
  independence arithmetic). A colluding cluster with high positive ratings
  and no pretrusted anchor never raises an enforcement allow (probe P2).
- **Calibration:** `a0=b0=1`, decay values, cap weights, and the planning
  threshold `P[θ>0.9] ≥ 0.95` are model assumptions, reported for
  sensitivity; calibration requires an incident corpus (ticket stop
  condition). Probe finding: at λ=0.05 the 0.95 threshold is unapproachable
  from clean ratings alone (steady-state effective count ~19.5, max P ≈
  0.885), so decay and threshold must be calibrated together.

## Run

```powershell
# probes (stdlib only)
python research/tickets/stage-1/S1-012/granularity_beta_probe.py
python research/tickets/stage-1/S1-012/acceptance_probe.py

# harness evaluation (from repo root)
$env:PYTHONPATH = "src"
python -m agentos.cli research-plan --topic "S1-012 evidence granularity independence and Beta reputation Sybil collusion calibration" --bundle "research/tickets/stage-1/S1-012/bundle.json" --db ".agentos-research/platform-stage-1"
```

## Notes and limits

- Seven repo-local sources are hash-bound by host-recomputed SHA-256 in
  `verifier_provenance.path` / `file_sha256` (S1-001 bundle + promotion
  probes, S1-003 shapes-v3.ttl, S1-011 bundle + lifecycle probe, AGENTS.md,
  `docs/RESEARCH_STAGE_1_TICKETS.md`). Literature identity (EigenTrust WWW
  2003, Beta Reputation System Bled 2002, uncertain-probabilities logic 2001,
  Sybil Attack IPTPS 2002, attack survey CSUR 2009) was verified by honest
  offline bibliographic review — no new live page review and no full-text
  archiving; the AISeL URL for the Beta reputation system is presumed and
  must be refreshed before production citation.
- Because the working tree had concurrent uncommitted edits to
  `docs/RESEARCH_STAGE_1_TICKETS.md`, the STAGE1-TICKETS hash binding in this
  bundle was refreshed to the bytes present at validation time
  (`9d28b1d7…`); re-run the probe pair and CLI if that file changes again.
- Audit verdict is `pass_with_limits`: process-separated (not external)
  auditor; assumption-level numeric calibration; reputation is
  recommendation-only; the models are deterministic research models, not a
  production knowledge-gate runtime or reputation service. Nothing here sets
  a Goal to ACCEPTED, and nothing was committed.