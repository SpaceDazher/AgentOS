# S1-013 analysis plan (1.1.0-draft; R1, no human data)

## Units and clustering

Primary n is people (target N=16), not clicks. Repeated events of
one participant are dependent: all rate/latency/fatigue analyses are
participant-clustered (per-participant aggregates first) with paired
AB/BA comparisons where applicable. Role strata (8+8) are reported
with uncertainty; small samples are never called representative.

## Measures C1–C5

Per measure: raw counts, percentage, Wilson 95% interval, and
disposition target_met / not_met / inconclusive against the frozen
targets. Denominators per protocol (timeouts/failures/missing stay
in). Dual-rater adjudication per rubric; disagreements preserved in
answers.json. No imputation.

The implemented preparation evaluator uses a closed synthetic answer oracle
plus fixture coding agreement; producer `adjudicated` flags have no authority.
Browser free text has no independent grading and stays missing/ungraded. This
is deliberately not an automatic human-comprehension evaluator. The proposed
blinded human adjudication workflow remains a separate approval prerequisite.

## Approval load

Per role and block: prompts shown, eligible decisions,
approve/deny/abstain counts, oracle accuracy, median/p90 latency,
active minutes, errors, fatigue reports. N_prompts/hour = actual
prompts / active hours (paired across blocks per participant). Raw
exposure duration reported alongside; short-block rescaling is not
stamina evidence. Subjective fatigue vs behavioural errors analyzed
separately. Order/learning effects and missingness reported with
small-sample power caveats. Implemented dry-run rates use block start/end and
pause/resume events, exclude comprehension/rest, and mark incomplete blocks.
Infeasible scenarios are classified by the frozen scenario manifest, not a
prompt-count heuristic. Dry-run output provides per-participant values and their
range; it does not claim a calibrated human confidence interval or paired effect.

## Uncertainty and outcomes

Primary outcomes per §4 disposition rule; exploratory outcomes
clearly labeled. If final N falls outside 15–20, closure stops and a
plan change is requested. Post-freeze analysis fixes become new
analysis revisions with honest post-hoc disclosure; old sessions are
never re-issued as new.

## Replication

A separate process/executor reruns the frozen analysis over the same
approved data; hashes, counts, scores and verdict must match. This
replicates analysis, not the human pilot.
