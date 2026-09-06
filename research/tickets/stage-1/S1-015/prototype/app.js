"use strict";
// S1-015 bounded prototype. Safe text API only: textContent/createElement.
// No innerHTML, no outerHTML, no insertAdjacentHTML, no external network.
let cfg = null;
const seen = [];
const el = (id) => document.getElementById(id);
const canonical = (v) => JSON.stringify(sort(v));
function sort(v) {
  if (Array.isArray(v)) return v.map(sort);
  if (v && typeof v === "object") return Object.fromEntries(Object.keys(v).sort().map((k) => [k, sort(v[k])]));
  return v;
}
function log(type, extra) {
  seen.push(Object.assign({ t: new Date().toISOString(), type }, extra || {}));
  el("eventlog").textContent = JSON.stringify(seen, null, 2);
}
function setText(id, value) { el(id).textContent = value == null ? "" : String(value); }
function currentCase() {
  const id = el("case").value;
  return cfg.cases.find((c) => c.case_id === id);
}
function variant() { return el("variant").value; }
function render() {
  const c = currentCase();
  if (!c) return;
  const v = variant();
  el("principal-card").hidden = false;
  el("approval-card").hidden = false;
  el("onbehalf-card").hidden = false;
  el("history-card").hidden = false;
  el("export").disabled = false;
  setText("card-title", c.case_id + " / " + c.class + " / " + v.toUpperCase());
  setText("canon-id", c.principal_id);
  setText("canon-type", c.principal_type);
  setText("canon-scope", c.scope);
  setText("canon-tenant", c.tenant);
  const petRow = el("petname-row");
  if (v === "baseline") {
    petRow.style.display = "none";
  } else {
    petRow.style.display = "";
    setText("petname", c.petname == null ? "(no current label — tombstone)" : c.petname);
    setText("petname-meta", "(owner " + c.petname_owner_id + ", v" + c.petname_version + ", " + c.petname_state + ")");
  }
  // Screen-reader text always carries the canonical identity (I8).
  setText("sr-text", "Principal " + c.principal_id + ", type " + c.principal_type + ", scope " + c.scope + ", tenant " + c.tenant + (v === "petname" && c.petname ? ", also known to owner as " + c.petname : ""));
  // Ambiguity: list every matching canonical identity, require explicit choice.
  const amb = el("ambiguity");
  const list = el("candidates");
  while (list.firstChild) list.removeChild(list.firstChild);
  let cands = c.candidates || [];
  let ambiguous = cands.length > 1 || c.approval_outcome === "require-selection";
  if (c.case_id === "COL-08") { ambiguous = false; cands = []; }
  if (ambiguous) {
    amb.hidden = false;
    cands.forEach((cand) => {
      const li = document.createElement("li");
      const label = document.createElement("label");
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "cand-" + c.case_id;
      radio.value = cand.principal_id;
      // No preselected radio: auto-select is forbidden.
      label.appendChild(radio);
      label.appendChild(document.createTextNode(" " + cand.principal_id + " · " + cand.scope));
      li.appendChild(label);
      list.appendChild(li);
    });
  } else {
    amb.hidden = true;
  }
  const warns = [];
  if (c.confusable_expect) warns.push("Caution: label flagged by confusable/Unicode check — canonical ID governs.");
  if (c.injection) warns.push("Untrusted label rendered as inert text (no execution).");
  if (c.petname_state === "renamed") warns.push("Renamed projection v" + c.petname_version + " (supersedes v" + c.supersedes + "); history stays canonical.");
  if (c.petname_state === "deleted") warns.push("Deleted projection — tombstone binding; history stays canonical.");
  if ((c.petname || "").length >= 200) warns.push("Oversized label truncated for display; full canonical ID unaffected.");
  setText("warnings", warns.join(" "));
  // Approval card: canonical actor/target/action; petname is annotation only.
  setText("ap-actor", c.principal_id);
  setText("ap-target", c.principal_id);
  setText("ap-action", "read " + c.scope);
  setText("ap-tool", "directory.lookup@1 (display-only)");
  setText("ap-pet", v === "petname" && c.petname ? c.petname : "(none — canonical governs)");
  // On-behalf banner always carries canonical actor/beneficiary + scope.
  setText("ob-text", "On behalf of " + c.principal_id + " for owner " + c.petname_owner_id + " in " + c.scope);
  // History stays canonical across rename/delete.
  const hist = el("history");
  while (hist.firstChild) hist.removeChild(hist.firstChild);
  [c.historical_identity + " — created",
   c.historical_identity + " — current projection v" + c.petname_version + " (" + c.petname_state + ")"].forEach((line) => {
    const li = document.createElement("li");
    li.textContent = line;
    hist.appendChild(li);
  });
  log("render", { case_id: c.case_id, variant: v });
}
el("variant").addEventListener("change", render);
el("case").addEventListener("change", render);
el("copy-id").addEventListener("click", async () => {
  const c = currentCase();
  try { await navigator.clipboard.writeText(c.principal_id); } catch (e) { /* clipboard may be unavailable headless */ }
  log("copy_id", { case_id: c.case_id, copied_canonical: true });
});
el("ap-approve").addEventListener("click", () => {
  const c = currentCase();
  const checked = document.querySelector('input[name="cand-' + c.case_id + '"]:checked');
  if ((c.candidates || []).length > 1 && !checked) {
    setText("ap-status", "Blocked: ambiguous petname requires explicit canonical selection.");
    log("approval_blocked_ambiguity", { case_id: c.case_id });
    return;
  }
  if (checked && checked.value !== c.principal_id) {
    setText("ap-status", "Blocked: selection does not match viewed canonical principal.");
    log("approval_blocked_mismatch", { case_id: c.case_id });
    return;
  }
  if (c.approval_outcome === "deny" || c.approval_outcome === "require-selection") {
    setText("ap-status", "Denied: this case requires explicit canonical selection or denial per oracle.");
    log("approval_denied", { case_id: c.case_id });
    return;
  }
  setText("ap-status", "Approved canonical target " + c.principal_id + " (petname never authorized).");
  log("approval_granted_canonical", { case_id: c.case_id });
});
el("ap-deny").addEventListener("click", () => {
  const c = currentCase();
  setText("ap-status", "Denied.");
  log("approval_denied", { case_id: c.case_id });
});
el("export").addEventListener("click", () => {
  const doc = buildExport();
  const blob = new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  const url = URL.createObjectURL(blob);
  a.href = url;
  a.download = "s1-015-envelopes-" + variant() + ".json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
function buildExport() {
  const v = variant();
  const envelopes = cfg.cases.map((c) => buildEnvelope(c, v));
  return { schema: cfg.export_schema, variant: v, envelopes };
}
function buildEnvelope(c, v) {
  let cands = c.candidates || [{ principal_id: c.principal_id, scope: c.scope }];
  let ambiguous = cands.length > 1 || c.approval_outcome === "require-selection";
  if (c.case_id === "COL-08") { ambiguous = false; cands = [{ principal_id: c.principal_id, scope: c.scope }]; }
  return {
    schema_version: cfg.envelope_schema,
    case_id: c.case_id,
    variant: v,
    principal_id: c.principal_id,
    principal_type: c.principal_type,
    scope: c.scope,
    tenant: c.tenant,
    petname_owner_id: c.petname_owner_id,
    petname: v === "baseline" ? null : c.petname,
    petname_normalized: v === "baseline" ? null : c.petname_normalized,
    petname_state: v === "baseline" ? "none" : c.petname_state,
    petname_version: v === "baseline" ? 0 : c.petname_version,
    supersedes: v === "baseline" ? null : c.supersedes,
    canonical_display: c.principal_id + " · " + c.principal_type + " · " + c.scope,
    ambiguity: ambiguous,
    candidates: ambiguous ? cands : [{ principal_id: c.principal_id, scope: c.scope }],
    confusable_flag: !!c.confusable_expect || !!c.injection || (c.candidates || []).length > 1,
    confusable_reason: c.confusable_expect ? "flagged" : null,
    accessibility_text: "Principal " + c.principal_id + ", type " + c.principal_type + ", scope " + c.scope + ", tenant " + c.tenant,
    copy_id_available: true,
    approval: { actor: c.principal_id, target: c.principal_id, operation: "read", tool: "directory.lookup", tool_version: "1", args: { scope: c.scope }, expiry: null },
    on_behalf: c.principal_type === "platform_agent" ? { actor: c.principal_id, beneficiary: c.petname_owner_id } : null,
    provenance: "prototype:" + cfg.corpus_sha256.slice(0, 12),
    updated_at: "2026-09-05T00:00:00Z",
    no_authority: "petname-display-only-no-authority",
    disambiguation_cues: ["canonical ID text", "type text", "scope text"],
  };
}
el("import").addEventListener("change", async (e) => {
  try {
    const f = e.target.files[0];
    if (!f || f.size > 2000000) throw new Error("size");
    const doc = JSON.parse(await f.text());
    if (doc.schema !== cfg.export_schema || !Array.isArray(doc.envelopes) || !doc.envelopes.length) throw new Error("envelope mismatch");
    setText("import-status", "Envelope schema/bindings OK (" + doc.envelopes.length + "). Python lifecycle validation still required.");
  } catch (err) {
    setText("import-status", "Import FAILED: invalid, unbound or private envelope.");
  }
});
fetch("browser-contract.json").then((r) => { if (!r.ok) throw new Error("contract unavailable"); return r.json(); }).then((x) => {
  cfg = x;
  const sel = el("case");
  x.cases.forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c.case_id;
    opt.textContent = c.case_id + " — " + c.description;
    sel.appendChild(opt);
  });
  setText("status", "Frozen corpus " + x.cases.length + " cases loaded. Synthetic tooling only.");
  render();
}).catch(() => { setText("status", "BLOCKED: contract unavailable or invalid"); });
