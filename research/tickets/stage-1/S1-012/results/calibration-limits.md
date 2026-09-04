# S1-012 calibration limits

1. The planning threshold `P[theta > 0.9] >= 0.95` is a HYPOTHESIS. It
   is reported per admitted trial set, never enforced, and never
   converted into a truth probability.
2. All numeric results are corpus/model-level: 60 synthetic cases, 40
   dev plus 20 lineage-isolated (non-blinded) holdout. No empirically
   validated production threshold is claimed.
3. Independent weight counts allowed groups (cap 2), never raw units,
   digests, URLs or accounts. Excess copies add zero weight.
4. Unresolved independence abstains; abstention is allowed per oracle
   but never counted as correct and never given weight.
5. Beta reference values are exact binomial closed forms; the runner
   uses continued fractions; agreement is enforced to 1e-9 on integer
   parameters. Non-integer (decayed) parameters are checked for
   finiteness, range and flag consistency only.
6. EigenTrust is fixed to row-stochastic normalization, declared
   anchor, damping 0.85 and L1 convergence 1e-9/1000 iterations.
   Anchorless or non-converged runs abstain; cluster self-trust is
   never substituted for an anchor.
7. Reputation outputs (Beta tails, EigenTrust vectors, raw scores)
   rank review queues at most. Enforcement, capability, approval,
   budget, PROMOTED and ACCEPTED are never created from scores
   (structural firewall: enforcement_allow is always false).
8. Joint sensitivity (135 prior/decay/threshold/cap combos through
   the real core) shows zero flips; the document~span tie is a
   standing limitation, not a hidden choice.
