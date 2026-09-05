# S1-015 accessibility plan

- Every principal-display envelope carries `accessibility_text` with the
  canonical principal ID, type, scope and tenant in plain text.
- The prototype mirrors it into an `aria-live` screen-reader node; visual and
  accessibility trees always agree on the canonical identity (I8).
- Ambiguous petnames expose every matching canonical identity as labeled radio
  options with no preselection; selection and approval are keyboard-operable
  with a `:focus-visible` indicator.
- Color/iconography is never the sole disambiguation cue; text cues
  (canonical ID, type, scope) are always present.
- Copy-canonical-ID is a keyboard-reachable button whose accessible name
  resolves to the canonical ID; it reveals no private data.
- Hiding or truncating the canonical ID in the approval view or the
  screen-reader tree is an identity-gate FAIL (probe I), verified through the
  real browser (keyboard tab stop + SR text assertions) and the evaluator
  (`accessibility_identity_omission_count` must be 0).
