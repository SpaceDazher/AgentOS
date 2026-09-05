# S1-016 sensitivity plan (frozen before measurement)

Dimensions (higher is better, all measured): utility (reconstruction rate +
query efficiency), state/storage/constraint/latency/implementation parsimony.

- Base weights equal (1.0 each); decision = argmax; ties are explicit TIE.
- Perturbations: each dimension x0.5 and x1.5 (12 vectors).
- Leave-one-dimension-out: each dimension x0.0 (6 vectors).
- Deterministic grid: {0.5, 1.0, 1.5}^6 = 729 vectors.
- Total 1 + 12 + 6 + 729 = 748 vectors (>= 200 required).
- Winner distribution, flip list (vs base) and flip examples recorded.
- Mapping to the decision rule: B wins only on unique argmax with a real
  utility gap over A; C wins only on unique argmax with proven B-utility at
  lower complexity; otherwise A on no-necessary-benefit, or INCONCLUSIVE.
- Any winner flip caps the verdict at INCONCLUSIVE, even with admissible
  operator answers. Safety gates are never weighted.
