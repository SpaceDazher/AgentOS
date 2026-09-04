# S1-012 corrective log (defects found, regressions added, lessons)

Rule: every defect gets a regression and a short lesson. Oracle and
thresholds are never weakened to close a round.

1. Beta continued-fraction sign error (self-found via binomial
   reference test): `beta_cf` subtracted `lbeta` where Numerical
   Recipes adds it; tails were wrong by orders of magnitude.
   Regression: `test_runner_matches_binomial_on_integers` (25 random
   integer cases, 1e-9) plus frozen reference values in
   calibration-plan.json. Lesson: never trust a remembered formula;
   verify numerics against an independent closed form before freezing.
2. False symmetry claim (self-found): asserted
   P[t>0.9|Beta(6,3)] == 1-P[t>0.9|Beta(3,6)], which is mathematically
   wrong (mirror is at 1-x, not x). Replaced with the correct
   prior-washout metamorphic test. Lesson: state metamorphic
   properties with the exact event; prove the identity before encoding.
3. Manifest seed typo (self-found via Cartesian enforcement):
   corpus-manifest listed seeds that matched no executed cell.
   Regression: `check_series` frozen-Cartesian test plus the official
   runs themselves. Lesson: the manifest must be generated from, or
   checked against, executed evidence — never hand-typed twice.
4. Missing evaluator variant passthrough in tests (self-found):
   `evaluate_in_memory` defaulted variant to document, masking span
   rows as drift. Lesson: default arguments in test helpers are
   silent oracle changes; pass context explicitly.
5. Bundle trusted saved flags (independent review F1): rebuilt
   publication as recompute-from-raw plus crosscheck plus
   verdict/counter consistency. Regressions: Repro A/B integration
   tests, consistency unit test, adjudication branch tests. Lesson:
   saved PASS flags are never authority (task section 10).
6. Raw run cells never committed (independent review F2): staging
   import was verified against staging instead of `git ls-files`, so
   96 files silently missed the commit; ENVIRONMENT.md repeated the
   false claim. Fixed by byte-verified robocopy import plus ls-files
   count check; ENVIRONMENT.md corrected. Lesson: verify tracked
   state with `git ls-files`, never with the source of the copy.
7. Copy-Item directory copies are unreliable (self-found, twice):
   PowerShell `Copy-Item -Recurse ...\*` silently produced empty
   trees. Lesson: use robocopy with output checks for evidence trees.
8. Candidate lacked a tracked-artifact registry (independent review
   F3): added `tracked_artifacts` plus a disk-match regression test.
   Lesson: a candidate record must bind everything a re-verifier
   needs, checkable from `git archive HEAD`.
