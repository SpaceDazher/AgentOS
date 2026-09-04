# S1-013 mock prototype

Static single-file mock UI (`index.html`, no external URLs, no
telemetry, no backend). Serve locally for interactive use:

```powershell
py -3.12 -m http.server 8130 --directory research/tickets/stage-1/S1-013/prototype
# open http://localhost:8130/index.html
```

The MOCK banner is always visible; role/consent/scenarios/approvals/
stop-all/fatigue/export/import flows work offline. Event vocabulary
is identical to `schemas/events.schema.json` (enforced by
`tests/test_s1_013_ui.py`, which fails on any divergence).

Manual browser checklist (record results, do not automate against
production): happy flow through all scenarios and prompts, privacy
boundary text, stop pending→confirmed states, export→import
round-trip. Playwright checks are optional and skipped when the
driver is absent.
