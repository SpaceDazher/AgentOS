// S1-014 static mock UI. Renders CARD and GRAPH from ONE frozen contract.
// No innerHTML for data, no external scripts/fonts/telemetry, no oracle, no self-grading.
'use strict';
(function () {
  const $ = (id) => document.getElementById(id);
  const el = (tag, attrs, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === 'class') n.className = v; else if (k === 'text') n.textContent = v; else n.setAttribute(k, v);
    }
    for (const k of kids) n.append(k);
    return n;
  };
  const svgEl = (tag, attrs, text) => {
    const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const TIMEOUT_MS = 180000;
  const S = { contract: null, assignment: null, trials: [], events: [], seq: 0, idx: -1, practice: true,
    paused: false, pausedAt: 0, pausedTotal: 0, t0: 0, timer: null, current: null, lifecycle: 'incomplete',
    disclosureActions: 0, keyboardSteps: 0, pointerUsed: false, session: null, lastT: 0 };
  const now = () => { S.lastT = Math.max(S.lastT, Math.round(performance.now() - S.t0 - S.pausedTotal)); return S.lastT; };
  const opaque = (prefix) => {
    const b = new Uint8Array(8); crypto.getRandomValues(b);
    return prefix + '-' + Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  };
  const log = (type, extra) => {
    S.seq += 1;
    const e = Object.assign({ seq: S.seq, t_ms: now(), type }, extra || {});
    S.events.push(e);
    return e;
  };
  const sha256 = async (text) => {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return Array.from(new Uint8Array(buf), (x) => x.toString(16).padStart(2, '0')).join('');
  };
  const canonical = (v) => {
    if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']';
    if (v && typeof v === 'object') return '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}';
    if (typeof v === 'number' && !Number.isFinite(v)) throw new Error('non-finite');
    return JSON.stringify(v);
  };

  // ---------------------------------------------------------------- renderers
  function disclosure(name, label, body, dispute, variant) {
    const box = el('div', { class: 'disclosure' });
    const panel = el('div', { id: 'disc-' + name, hidden: '' });
    const btn = el('button', { type: 'button', 'aria-expanded': 'false', 'aria-controls': 'disc-' + name, text: label });
    btn.addEventListener('click', () => {
      const open = panel.hasAttribute('hidden');
      if (open) { panel.removeAttribute('hidden'); S.disclosureActions += 1; log('disclosure_opened', { dispute_id: dispute, variant, detail: name }); }
      else panel.setAttribute('hidden', '');
      btn.setAttribute('aria-expanded', String(open));
    });
    panel.append(body);
    box.append(btn, panel);
    return box;
  }
  function sourceTable(sources) {
    const t = el('table', {}, el('caption', { text: 'Provenance' }));
    t.append(el('tr', {}, ...['source', 'publisher', 'origin', 'retrieval boundary', 'state'].map((h) => el('th', { text: h }))));
    for (const s of sources) t.append(el('tr', { class: s.provenance_state === 'withheld' ? 'withheld' : '' },
      ...[s.source_id, s.publisher, s.origin, s.retrieval_boundary, s.provenance_state].map((v) => el('td', { text: v }))));
    return t;
  }
  function evidenceList(items) {
    const ol = el('ol');
    for (const e of items) ol.append(el('li', { class: e.evidence_state === 'withheld' ? 'withheld' : '' },
      el('span', { class: 'badge', text: e.evidence_id }), el('span', { class: 'badge', text: e.source_id }),
      el('span', { class: 'badge', text: e.independence_group }), el('span', { class: 'badge', text: e.evidence_state }),
      document.createTextNode(' ' + e.summary)));
    return ol;
  }
  function relationList(rels, groups) {
    const wrap = el('div');
    const ol = el('ol');
    for (const r of rels) ol.append(el('li', { text: r.from_evidence + ' ' + r.relation + ' ' + r.to_claim }));
    const gl = el('ul');
    for (const g of groups) gl.append(el('li', { text: g.group_id + ' — ' + g.label + ' (' + g.independence_basis + ')' }));
    wrap.append(el('p', { text: 'Relations' }), ol, el('p', { text: 'Independence groups' }), gl);
    return wrap;
  }
  function renderCard(view) {
    const l0 = view.level0, did = view.dispute_id;
    const card = el('article', { class: 'card', 'aria-label': 'evidence card' });
    card.append(el('p', { class: 'claim' }, el('span', { class: 'badge', text: 'focal ' + l0.focal_claim.claim_id }),
      el('span', { class: 'badge', text: 'status ' + l0.status }), el('span', { class: 'badge', text: 'gate ' + l0.knowledge_gate_state }),
      document.createTextNode(' ' + l0.focal_claim.text)));
    const ch = l0.challenge_indicator;
    card.append(el('p', { class: 'challenge' }, el('span', { class: 'badge', text: 'CHALLENGE ' + ch.claim.claim_id }),
      el('span', { class: 'badge', text: 'status ' + ch.claim.status }), el('span', { class: 'badge', text: ch.challenging_count + ' challenging' }),
      document.createTextNode(' ' + ch.claim.text)));
    card.append(el('p', { class: 'cue', text: 'Sources: ' + l0.source_cue.map((s) => s.source_id + ' (' + s.publisher + (s.publisher === s.origin ? '' : ' ← origin ' + s.origin) + ', ' + s.provenance_state + ')').join('; ') }));
    card.append(el('p', { class: 'cue', text: 'Independence groups: ' + l0.independence_cue.map((g) => g.group_id + ' ' + g.label + ' ×' + g.size).join('; ') }));
    if (l0.withheld_fields.length) card.append(el('p', { class: 'cue withheld', text: 'Withheld: ' + l0.withheld_fields.join(', ') }));
    card.append(disclosure('provenance_detail', 'Show provenance detail', sourceTable(view.disclosures.provenance_detail.content), did, 'CARD'));
    card.append(disclosure('evidence_detail', 'Show evidence detail', evidenceList(view.disclosures.evidence_detail.content), did, 'CARD'));
    card.append(disclosure('relations_detail', 'Show relations and groups', relationList(view.disclosures.relations_detail.content, view.disclosures.relations_detail.independence_groups), did, 'CARD'));
    return card;
  }
  function renderGraph(view) {
    const l0 = view.level0, did = view.dispute_id;
    const wrap = el('div', { class: 'graph' });
    const claims = l0.nodes.filter((n) => n.kind === 'claim'), evid = l0.nodes.filter((n) => n.kind === 'evidence');
    const W = 760, rowH = 60, H = 140 + Math.ceil(evid.length / 3) * rowH;
    const svg = svgEl('svg', { width: W, height: H, role: 'img', 'aria-labelledby': 'graph-title' });
    svg.append(svgEl('title', { id: 'graph-title' }, 'Argumentation graph; linear equivalent follows'));
    const pos = {};
    claims.forEach((c, i) => { pos[c.id] = { x: 60 + i * 380, y: 20 }; });
    evid.forEach((e, i) => { pos[e.id] = { x: 20 + (i % 3) * 250, y: 120 + Math.floor(i / 3) * rowH }; });
    for (const e of l0.edges) {
      const a = pos[e.from], b = pos[e.to];
      svg.append(svgEl('path', { class: 'edge ' + e.relation, d: 'M' + (a.x + 110) + ',' + a.y + ' L' + (b.x + 150) + ',' + (b.y + 50) }));
    }
    for (const n of l0.nodes) {
      const p = pos[n.id], g = svgEl('g', { class: 'node ' + (n.role || 'evidence'), tabindex: '0', role: 'group' });
      const lines = n.kind === 'claim' ? [n.id + ' [' + n.role + '] status ' + n.status, n.label]
        : [n.id + ' src ' + n.source_id + ' grp ' + n.independence_group, 'pub ' + n.publisher + ' ← origin ' + n.origin, n.label + ' [' + n.evidence_state + ']'];
      g.append(svgEl('title', {}, lines.join(' | ')));
      g.append(svgEl('rect', { x: p.x, y: p.y, width: n.kind === 'claim' ? 300 : 230, height: 50, rx: 4 }));
      lines.forEach((t, i) => g.append(svgEl('text', { x: p.x + 4, y: p.y + 13 + i * 13 }, t.slice(0, n.kind === 'claim' ? 48 : 36))));
      g.addEventListener('focus', () => log('node_focus', { dispute_id: did, variant: 'GRAPH', detail: n.id }));
      svg.append(g);
    }
    wrap.append(svg);
    const lin = el('section', { 'aria-label': 'linear equivalent of the graph' }, el('p', { text: 'Linear equivalent (keyboard / screen reader):' }));
    const ol = el('ol');
    for (const line of l0.linear_equivalent) ol.append(el('li', { text: line }));
    lin.append(ol);
    lin.append(el('p', { class: 'cue', text: 'Independence groups: ' + l0.groups.map((g) => g.group_id + ' ' + g.label).join('; ') + ' · gate ' + l0.knowledge_gate_state }));
    if (l0.withheld_fields.length) lin.append(el('p', { class: 'cue withheld', text: 'Withheld: ' + l0.withheld_fields.join(', ') }));
    wrap.append(lin);
    wrap.append(disclosure('provenance_detail', 'Show provenance detail', sourceTable(view.disclosures.provenance_detail.content), did, 'GRAPH'));
    wrap.append(disclosure('evidence_detail', 'Show evidence detail', evidenceList(view.disclosures.evidence_detail.content), did, 'GRAPH'));
    wrap.append(disclosure('relations_detail', 'Show relations and groups', relationList(view.disclosures.relations_detail.content, view.disclosures.relations_detail.independence_groups), did, 'GRAPH'));
    return wrap;
  }

  // ---------------------------------------------------------------- flow
  function fillSetup() {
    const seeds = [...new Set(S.contract.assignments.map((a) => a.seed))], execs = [...new Set(S.contract.assignments.map((a) => a.executor))];
    for (const s of seeds) $('seed').append(el('option', { value: s, text: s }));
    for (const x of execs) $('executor').append(el('option', { value: x, text: x }));
  }
  function currentTrialSpec() {
    if (S.practice) return { position: -1, dispute_id: S.contract.disputes[0].dispute_id, variant: 'CARD' };
    return S.assignment.trials[S.idx];
  }
  function present() {
    const spec = currentTrialSpec(), view = S.contract.views[spec.dispute_id][spec.variant], dispute = S.contract.disputes.find((d) => d.dispute_id === spec.dispute_id);
    S.disclosureActions = 0; S.keyboardSteps = 0; S.pointerUsed = false;
    $('progress').textContent = (S.practice ? 'PRACTICE (not recorded as a trial) · ' : 'Trial ' + (S.idx + 1) + ' of ' + S.assignment.trials.length + ' · ') + 'variant ' + spec.variant + ' · stratum ' + dispute.complexity_stratum;
    $('wording').textContent = dispute.task_wording;
    const v = $('view'); v.replaceChildren(spec.variant === 'CARD' ? renderCard(view) : renderGraph(view));
    const ans = $('answers'); ans.replaceChildren();
    for (const c of dispute.answer_choices) ans.append(el('label', {}, el('input', { type: 'radio', name: 'ans', value: c }), document.createTextNode(' ' + c)));
    const prov = $('prov'); prov.replaceChildren();
    for (const s of dispute.sources) prov.append(el('label', {}, el('input', { type: 'checkbox', name: 'prov', value: s.source_id }), document.createTextNode(' ' + s.source_id)));
    for (const r of document.querySelectorAll('input[name=chal],input[name=ovl]')) r.checked = false;
    S.current = { position: spec.position, dispute_id: spec.dispute_id, variant: spec.variant, presented_t_ms: null };
    requestAnimationFrame(() => requestAnimationFrame(() => {
      S.current.presented_t_ms = now();
      if (!S.practice) log('task_presented', { dispute_id: spec.dispute_id, variant: spec.variant });
      $('answers').querySelector('input').focus();
      clearTimeout(S.timer); S.timer = setTimeout(() => finish('timeout'), TIMEOUT_MS);
    }));
  }
  function finish(outcome) {
    clearTimeout(S.timer);
    const c = S.current, t = now();
    const ans = document.querySelector('input[name=ans]:checked'), chal = document.querySelector('input[name=chal]:checked'), ovl = document.querySelector('input[name=ovl]:checked');
    const trial = { position: c.position, dispute_id: c.dispute_id, variant: c.variant, presented_t_ms: c.presented_t_ms,
      submitted_t_ms: outcome === 'submitted' || outcome === 'timeout' ? t : null, outcome,
      answer: ans ? ans.value : '__MISSING__', provenance_recall: [...document.querySelectorAll('input[name=prov]:checked')].map((x) => x.value).sort(),
      challenge_choice: chal ? chal.value : '__MISSING__', overload: ovl ? ovl.value : 'not_reported',
      disclosure_actions: S.disclosureActions, keyboard_steps: S.keyboardSteps, pointer_used: S.pointerUsed };
    if (S.practice) { S.practice = false; log('practice_end'); S.idx = 0; present(); return; }
    if (ans) log('answer_selected', { dispute_id: c.dispute_id, variant: c.variant, detail: ans.value });
    if (trial.provenance_recall.length) log('provenance_marked', { dispute_id: c.dispute_id, variant: c.variant, detail: trial.provenance_recall.join('+') });
    if (chal) log('challenge_marked', { dispute_id: c.dispute_id, variant: c.variant, detail: chal.value });
    if (ovl) log('overload_reported', { dispute_id: c.dispute_id, variant: c.variant, detail: ovl.value });
    log(outcome === 'timeout' ? 'task_timeout' : 'task_submitted', { dispute_id: c.dispute_id, variant: c.variant });
    S.trials.push(trial);
    S.idx += 1;
    if (S.idx < S.assignment.trials.length) present(); else complete('complete');
  }
  function complete(lifecycle) {
    clearTimeout(S.timer);
    S.lifecycle = lifecycle;
    // Trials never presented stay in the denominator as explicit missing rows.
    if (S.assignment) for (let i = Math.max(S.idx, 0); i < S.assignment.trials.length; i++) {
      const spec = S.assignment.trials[i];
      if (S.trials.some((t) => t.position === spec.position)) continue;
      S.trials.push({ position: spec.position, dispute_id: spec.dispute_id, variant: spec.variant, presented_t_ms: S.current && S.current.position === spec.position ? S.current.presented_t_ms : null,
        submitted_t_ms: null, outcome: lifecycle === 'withdrawn' ? 'withdrawn' : 'missing', answer: '__MISSING__', provenance_recall: [], challenge_choice: '__MISSING__',
        overload: 'not_reported', disclosure_actions: 0, keyboard_steps: 0, pointer_used: false });
    }
    log(lifecycle === 'withdrawn' ? 'withdraw' : 'session_complete');
    $('trial').hidden = true; $('done').hidden = false;
    $('summary').textContent = 'Lifecycle ' + lifecycle + ' · trials recorded ' + S.trials.length + ' · events ' + S.events.length + ' · no correctness shown here (oracle is not available to this UI).';
    $('export').focus();
  }
  async function buildEnvelope() {
    const body = { envelope_schema: 'agentos.s1-014.browser-envelope/v1', contract_schema: S.contract.contract_schema, contract_version: S.contract.contract_version,
      contract_sha256: S.contract.contract_sha256, banner: S.contract.banner,
      session: Object.assign({}, S.session, { lifecycle: S.lifecycle }), trials: S.trials.slice().sort((a, b) => a.position - b.position), events: S.events };
    body.payload_sha256 = await sha256(canonical(body));
    return body;
  }
  async function checkEnvelope(doc) {
    const problems = [];
    if (!doc || typeof doc !== 'object') return ['not an object'];
    if (doc.envelope_schema !== 'agentos.s1-014.browser-envelope/v1') problems.push('envelope schema');
    if (doc.contract_sha256 !== S.contract.contract_sha256) problems.push('contract binding');
    const copy = Object.assign({}, doc); delete copy.payload_sha256;
    if ((await sha256(canonical(copy))) !== doc.payload_sha256) problems.push('payload digest');
    const a = S.contract.assignments.find((x) => x.assignment_sha256 === (doc.session || {}).assignment_sha256);
    if (!a) problems.push('assignment binding');
    return problems;
  }

  document.addEventListener('keydown', (e) => { if (['Tab', 'Enter', ' ', 'ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight'].includes(e.key)) S.keyboardSteps += 1; });
  document.addEventListener('pointerdown', () => { S.pointerUsed = true; });

  fetch('browser-contract.json').then((r) => r.json()).then((c) => {
    S.contract = c;
    $('banner').textContent = c.banner;
    $('contract-state').textContent = 'Frozen contract ' + c.contract_version + ' loaded · sha256 ' + c.contract_sha256.slice(0, 16) + '… · ' + c.disputes.length + ' disputes';
    fillSetup();
  }).catch(() => { $('contract-state').textContent = 'Contract load FAILED'; });

  $('start').addEventListener('click', () => {
    if (!$('consent').checked) { $('contract-state').textContent = 'Consent required before start'; return; }
    S.t0 = performance.now(); S.pausedTotal = 0; S.lastT = 0;
    S.assignment = S.contract.assignments.find((a) => a.seed === $('seed').value && a.executor === $('executor').value);
    S.session = { session_id: opaque('SES'), participant_id: opaque('OPQ'), role: $('role').value, seed: S.assignment.seed, executor: S.assignment.executor,
      assignment_sha256: S.assignment.assignment_sha256, consent: { given: true, form_version: 'S1-014-review-v1', t_ms: 0 }, accessibility_mode: $('a11y').value, lifecycle: 'incomplete' };
    log('consent_given'); log('practice_start');
    $('setup').hidden = true; $('trial').hidden = false; S.practice = true; present();
  });
  $('submit').addEventListener('click', () => { if (!S.paused) finish('submitted'); });
  $('pause').addEventListener('click', () => { if (S.paused) return; S.paused = true; S.pausedAt = performance.now(); clearTimeout(S.timer); log('pause'); $('submit').disabled = true; $('resume').disabled = false; $('pause').disabled = true; });
  $('resume').addEventListener('click', () => { if (!S.paused) return; S.pausedTotal += performance.now() - S.pausedAt; S.paused = false; log('resume'); $('submit').disabled = false; $('resume').disabled = true; $('pause').disabled = false; });
  $('withdraw').addEventListener('click', () => { complete('withdrawn'); $('withdraw').disabled = true; });
  $('export').addEventListener('click', async () => {
    const doc = await buildEnvelope();
    const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' });
    const a = el('a', { href: URL.createObjectURL(blob), download: 's1-014-envelope.json' });
    document.body.append(a); a.click(); a.remove();
  });
  $('import').addEventListener('change', async (e) => {
    const f = e.target.files[0]; if (!f) return;
    try { const problems = await checkEnvelope(JSON.parse(await f.text())); $('import-result').textContent = problems.length ? 'Import FAILED: ' + problems.join(', ') : 'Envelope schema/bindings OK (not a score)'; }
    catch (err) { $('import-result').textContent = 'Import FAILED: parse error'; }
  });
})();
