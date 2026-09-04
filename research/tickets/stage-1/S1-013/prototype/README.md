# S1-013 mock prototype

Static single-file mock UI (`index.html`, no external URLs, no
telemetry, no backend). Serve locally for interactive use:

```powershell
py -3.12 -m http.server 8130 --bind 127.0.0.1 --directory research/tickets/stage-1/S1-013/prototype
# open http://localhost:8130/index.html
```

The MOCK banner is always visible; role/consent/scenarios/approvals/
stop-all/fatigue/export/import flows work offline. Event vocabulary
is identical to `schemas/events.schema.json` (enforced by
`tests/test_s1_013_ui.py`, which fails on any divergence).

`browser-contract.json` is mechanically derived by `synthetic/build_synthetic.py`
from the protocol, scenarios and schemas. Its equality to the canonical inputs
is tested. The exporter writes a single `*.export.json` envelope accepted by
`runner.py --src <export-directory> --out <temporary-import-directory>`.

The real browser test is mandatory: configure Node, the `playwright` package
(for example via NODE_PATH to an existing bundled runtime), and installed Edge
or set S1013_BROWSER to a Chromium executable. Run
`py -3.12 -m unittest tests.test_s1_013_ui -v`. Missing tooling is a failure,
not a fake pass or optional skip. The test exercises the browser and imports its
actual download through Python, including consent, responses, fatigue, 36
approvals, pause/resume, stop success/failure and invalid import.

Free-text answers are retained but never self-graded. The synthetic scorer has
no human-rater authority; human data is rejected. Mock timing uses
performance.now(); C5 starts at task presentation and awaits both mock agents.
Want to stop withdraws the session and stops collection. No telemetry or real
permissions are involved. Human-duration blocks and human adjudication remain
unimplemented until operator approval, not silently simulated as human evidence.
