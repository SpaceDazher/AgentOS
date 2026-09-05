# S1-014 facilitator guide (operator self-walkthrough)

1. Serve `prototype/` locally (`node prototype/browser_probe.cjs` runs the
   automated keyboard-only regression; for a manual look open `index.html`
   through any static server on 127.0.0.1).
2. Confirm the banner **OPERATOR DESIGN REVIEW — NOT A USER STUDY** and the
   frozen contract hash shown under it match `frozen-manifest.json`.
3. Choose role `operator_design_reviewer`, a seed/executor, and a mode.
   Tick consent, start; complete the practice task.
4. For each of the 8 trials inspect level 0 first (claim, status, challenge,
   sources with origin, independence groups), then open disclosures as needed.
   Answer, mark the sources you relied on, whether you saw the challenge, and
   your effort level. Use pause/resume if interrupted.
5. Export the envelope **outside the repository** and run
   `python importer.py <dir> <out>` then `python evaluator.py <out> <out2>`.
   Delete the raw export afterwards.
6. Answer the 12 questions from `TASK_FOR_AGENT.md` §9.1 as `1A 2A … 12A`.
   The agent writes `operator-decision.json`, runs
   `python publisher.py verify-decision` and `python publisher.py publish`.
7. Record any deviation by appending to `results/decision.md`; never edit history.
