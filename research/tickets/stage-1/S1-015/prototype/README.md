# S1-015 prototype (bounded, static, MOCK)

Two task-equivalent display variants over one frozen corpus:

- BASELINE: canonical principal ID + type + scope, no petname.
- PETNAME: petname as an additional annotation; canonical ID/type/scope stay
  visible, in the screen-reader text and behind the copy-ID control.

Safety properties (enforced by unit tests + browser probe):

- petname renders only through `textContent`/`createElement` (no `innerHTML`).
- No external scripts/fonts/telemetry/network; no secrets.
- CSP `default-src 'self'; script-src 'self'; style-src 'self'`.
- Ambiguous petnames list every matching canonical identity as radio options
  with no preselection; approval without explicit canonical selection is
  blocked; name-only approval is denied.
- Rename/delete shows version/lifecycle; history lists canonical IDs only.
- Keyboard-only flow with `:focus-visible`; color/icon never the sole cue.
- The UI never changes policy/status/authority; it only displays and exports
  versioned envelopes (`agentos.s1-015.export/v1`) for the Python importer.

Run the real-browser probe (Edge headless via Playwright):

```powershell
py -3.12 research/tickets/stage-1/S1-015/prototype/browser_probe.py --out D:/Temp-opencode/s1-015-envelopes.json
```
