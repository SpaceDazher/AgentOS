# S1-013 privacy plan (v1, operator-approved before recruitment)

1. **Data minimization:** session records carry pseudonymous ids
   (`P-XXXXXX`), coded answers and event timings only. No names,
   contacts, files, credentials, audio/video or verbatim free text
   beyond coded responses.
2. **Separation:** contacts, signed consent originals and the
   reidentification key live under operator control, never in Git,
   wiki, packs or generated vaults. Publication carries aggregates
   and approved de-identified observations only.
3. **Pseudonymity ≠ anonymity:** small role strata and free-text
   explanations are manually reviewed for reidentification risk
   before any release; risky cells are suppressed or coarsened.
4. **Restricted raw data:** any auditor-accessible raw set ships with
   a manifest, hashes and a named access procedure; public clones
   must not claim reproducibility of conclusions that need
   operator-held data.
5. **Retention/deletion:** [operator sets windows]; withdrawal
   requests honored, recorded as dropout with reason.
6. **Leak/discomfort/withdrawal = stop:** any incident halts the
   pilot pending operator review (escalation PARK-01 for
   high-risk/legal qualification).
7. **Human privacy outranks "everything in Git":** when in doubt,
   withhold and log the withholding.
