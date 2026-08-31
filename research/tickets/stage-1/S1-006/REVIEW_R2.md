# S1-006 — REVIEW_R2 corrective closure

Verdict: findings closed; ticket remains `PASS_WITH_LIMITS` because the
comparison is model-based and same-host, not because evidence is missing.

## Findings and observed fixes

1. **Raw evidence and scored comparison could diverge.**
   The evaluator now loads only manifest-named, SHA-verified raw files,
   independently derives all safety counters and latency/throughput/queue
   metrics, and rejects any comparison projection that differs. A forged raw
   `duplicate_effect_count=99` cannot be hidden by a clean summary.

2. **S1 did not prove commit/outbox/replay semantics.**
   S1 now records an atomic transition/outbox commit, a coordinator crash
   before delivery, and replay of that same decision after recovery. Event
   identity and ordering are evaluator-checked.

3. **The workload was effectively one serial DAG with no queue pressure.**
   Every repeated 12-task DAG instance now starts from a fresh dependency
   state and is validated independently. Arrivals are open-loop. The high
   load is an explicit 20,000/s saturation probe and produces waiting time
   and queue depth greater than one.

4. **Provenance was incomplete.**
   Only explicit generated outputs (`results/` and `bundle.json`) are
   excluded from dirty detection. Five exact evidence scripts are mandatory;
   both executed disk-byte and commit-blob SHA-256 sets are verified, as are
   commit, tree, executor identity and environment hash.

5. **Probes and replay assertions were self-confirming.**
   Probe A calls the unsafe delivery path and produces a real second effect
   and receipt in raw ledgers. Probe C records blind retries without
   reconciliation. S3 verifies a registered checkpoint and new-run
   provenance; S4 verifies an actual stale-fence rejection and deduplicated
   redelivery. The probe file itself is digest-bound to both evaluator runs.

6. **Dependency proof was partial.**
   The gate now verifies content-addressed file SHA, payload self-hash,
   `chain_fresh`, `latest_evaluation_valid`, current/latest chain,
   goal/campaign/evaluation/result/revision, and canonical DB ownership.

7. **Scores and sensitivity reporting contained hardcoded authority.**
   Behavioral scores derive from verified scenario evidence. Qualitative
   scores live in explicit contract cells with claim type, evidence refs and
   rationale. The reported count is exactly 22 perturbations + 200 random
   compositions = 222; ties are indeterminate and no longer resolved by
   insertion order.

8. **S2 fault coverage depended on chance.**
   Every S2 seed now injects at least one unknown outcome deterministically;
   an empty S2 fault set or a reconciliation-set mismatch fails closed.

## Final evidence

- Experiment SHA: `30cdd80d8b47168522248fac5516cc7f773a018a`,
  `dirty=false`.
- 90 main + 90 isolated rerun records; different executor identities.
- Seven safety counters are zero in every accepted run.
- Rerun score and metric deltas: all 0.
- Sensitivity: 222 runs, zero flips, zero ties.
- S1-006 regressions: 68/68.
- Clean-tree full repository suite: 467 tests, 466 passed + 1 skipped,
  exit 0.
- Canonical research revision 5:
  `reval_3R5R2WNN81E4ZMWW01M1CKXMRE`, chain
  `f5e45f4f59f2f5fd08e57a27afc9c7c6e8ea502b1b034da613c757e8d24bfe53`.
- Tracked pack:
  `results/evidence/evidence-pack-615e39d622acef5bc2b331c9c7d3fadadafe4b7825275799eb0518775d0fd4df.json`;
  payload SHA
  `80058f8345015a550eb18bbcd19a31b9fa771b411603ed3904f7815ccdf4d3ce`;
  `chain_fresh=true`, `latest_evaluation_valid=true`.

Remaining limits are unchanged and explicit: no vendor engine, production
SLO, multi-host partition qualification, or external human audit.
