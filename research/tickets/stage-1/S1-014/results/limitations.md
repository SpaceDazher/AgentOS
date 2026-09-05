# S1-014 limitations

1. **No human participants.** human_study_n=0. Every number in `results/metrics.json` comes from synthetic technical replay or (later) one operator; comparative_human_effectiveness=NOT_MEASURED and no CARD/GRAPH winner exists.
2. **Single operator as owner and reviewer.** Phase B is a design-contract approval, not an experiment; the operator's answers are never converted into participant scores.
3. **Inherited S1-011/S1-012/S1-013 limits** are carried verbatim in `dependency-gate.json` (`inherited_limits`), including S1-013's cancelled mass pilot, absent independent raters and deleted raw observations.
4. **Same-host replay.** Run A/Run B are process-separated (distinct PID, executor, nonce, output root) but not an external audit.
5. **External HCI sources** (Ghoniem et al. 2004; Shneiderman 1996) are stored as Crossref bibliographic/availability records, not full text; no numeric result from them is used.
6. **Prototype cosmetics.** Long node labels are truncated in the SVG; the information is complete in the node tooltip and the linear equivalent. Not a production UI.
7. **Browser evidence** comes from Playwright Chromium 129 headless on Linux in this environment; the operator's Windows/Edge run is expected to reproduce it but was not executed here.
8. **Environment note.** Ticket tests were run with Python 3.11 (`py -3.12` unavailable in the preparation sandbox); full-suite results are recorded in the agent report with exact exit codes.
