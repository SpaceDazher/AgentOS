# S1-013 — corrective R1 verification

Date: 2026-09-04. Preparation: **PREPARATION_READY**.
Human phase: **BLOCKED_HUMAN_PILOT**. The full research ticket is not closed.

## Reviewed findings

1. Publication now verifies the exact frozen file set, freshly checks dependency records, executes the importer/scorer and two-process replay, and compares saved evidence to fresh results. Fabricated gate, comparison and C4 metrics were independently rejected. Failed publication removes stale ready outputs; read-only derivation does not delete them.
2. Dependency identities, revisions, verdicts, chains and pack bytes bind to authoritative tracked Git records on matching origin refs. Fabricated overrides fail. Live DB recheck remains Phase B work.
3. Duplicate sessions/participants/measures are rejected; missing presented responses stay in denominators. An untrusted `adjudicated` flag cannot award credit. The exact-answer oracle is for synthetic fixtures only; browser free text remains ungraded, not an automatic human assessment.
4. C5 starts at task presentation and awaits both mock agents. The slow synthetic failure remains in the distribution (62000 ms), not just in a failure counter.
5. A real Edge browser exported the envelope consumed by Python. Consent, free responses, fatigue, pause/resume, 36 approvals, withdrawal, stop success/failure and invalid re-import were exercised. The browser has no self-confirmation/self-grading button.
6. The importer enforces schema types, versions, protocol digest, identity, consent, chronology and event lifecycle, with recursive privacy checks on all documents. Additional mutations cover duplicate session ID under another participant and substituted displayed actor.
7. Approval exposure uses active block intervals, excludes pauses/comprehension and explicitly infeasible blocks, and retains participant-level fatigue/rates. Uncertainty is a participant range, not a calibrated human confidence claim.

## Observed verification

Worktree: `.codex-work/s1-013-task`, branch `codex/s1-013-comprehension-pilot`.
Python 3.12.6; actual browser Edge 152.0.4191.53; Node and existing bundled Playwright.
Set `PYTHONPATH=src`; set `NODE_PATH` to the existing bundled Node dependencies when running browser tests.

- RED: four original boundary/grading/timing regressions failed before fixes; two additional duplicate-session/displayed-actor tests also failed before correction.
- `py -3.12 -m unittest tests.test_s1_013_regressions tests.test_s1_013_boundary_r1 tests.test_s1_013_ui tests.test_s1_013_publication_r1 -q`: **55 tests, OK**, including actual browser-to-Python flow.
- `py -3.12 -m unittest discover -s tests -q`: **865 tests, OK (1 skipped)**, 98.399 seconds, on clean evidence commit `0fb5343`.
- `py -3.12 -m evals.gen_fixtures --check`: **78 checked, zero violations**.
- `py -3.12 research/tickets/stage-1/S1-013/prepare_evidence.py --freeze-inputs`: explicit post-review freeze and fresh evidence generation succeeded. Normal replay omits `--freeze-inputs` and refuses changed input hashes.
- Synthetic results: 11 sessions = 7 eligible + 3 rejected + 1 quarantined; probes A–H green; distinct-process replication agrees.
- Root adversarial publication probes: fake saved gate, fake saved comparison, and forged 20/20 C4 result all rejected by real derivation with fresh recomputation.
- Candidate registry: all 80 entries at `0fb5343` matched bytes extracted from `git archive HEAD`. This report is added by the final documentation commit and included in its regenerated registry.
- `git diff --check`: clean.

TDD/implementation commits: `27b0d59`, `60163cf`, `5bbba0d`, `f2ae54c` (additional RED), `7601090` (GREEN), `66bb71d` (publication), `0fb5343` (evidence).

## Limits and non-claims

- No people recruited, human data imported, canonical DB updated, main merged, or GitHub push performed. S1-013 still requires operator-approved consent/privacy, 15–20 real participants, full-duration facilitation and independent human grading/adjudication.
- The UI is accelerated synthetic preparation, not implementation of an approved 75-minute human study. Real collection is rejected by the current importer.
- Same-host process replay is reproducibility, not an external audit or independent implementation. SRC04 is now a locally snapshotted design input, not a new empirical source.
- Baseline full-suite isolation (excluding S1-013) once exposed `test_concurrent_exact_repeats_create_one_goal` uniqueness failure; its isolated rerun passed. The final full suite passed. Core code was not changed to hide this intermittent issue.
- No type checker/linter dependencies were installed. Coverage instrumentation of only the 20 focused in-process boundary/publication tests produced contract 70.3%, runner 55.8%, evaluator 48.0%, publisher 13.0%; this excludes subprocess/browser execution and is **not** total suite coverage. An 80% aggregate coverage claim is not made.
- Readiness is bounded to these preparation criteria; no human-comprehension, stamina, production or universal privacy/security result follows from synthetic tests.
