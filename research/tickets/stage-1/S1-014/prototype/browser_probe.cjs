// Real offline browser regression for S1-014. Output is a synthetic technical
// replay envelope (role synthetic_technical_replay); never human evidence.
// usage: node browser_probe.cjs <out.json> [seed] [executor] [mode]
const {chromium} = require(process.env.S1014_PLAYWRIGHT || 'playwright');
const http = require('node:http'), fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
(async () => {
  const allowed = {'/index.html': 'text/html', '/app.js': 'text/javascript', '/style.css': 'text/css', '/browser-contract.json': 'application/json'};
  const server = http.createServer((req, res) => {
    const name = req.url.split('?')[0];
    if (!(name in allowed)) { res.writeHead(404); res.end(); return; }
    res.setHeader('Content-Type', allowed[name]); res.end(fs.readFileSync(path.join(__dirname, name.slice(1))));
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const out = process.argv[2], seed = process.argv[3] || 'seed-0001', executor = process.argv[4] || 'EXEC-RUN-A', mode = process.argv[5] || 'keyboard_only';
  let browser;
  try {
    const opts = {headless: true};
    if (process.env.S1014_BROWSER) opts.executablePath = process.env.S1014_BROWSER;
    browser = await chromium.launch(opts);
    const page = await browser.newPage({acceptDownloads: true}), errors = [], requests = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('request', (r) => requests.push(r.url()));
    const url = 'http://127.0.0.1:' + server.address().port + '/index.html';
    await page.goto(url);
    await page.getByText(/Frozen contract 1\.0\.0 loaded/).waitFor();
    assert.equal(await page.locator('#banner').innerText(), 'OPERATOR DESIGN REVIEW — NOT A USER STUDY');
    await page.selectOption('#seed', seed); await page.selectOption('#executor', executor); await page.selectOption('#a11y', mode);
    // consent gate
    await page.locator('#start').focus(); await page.keyboard.press('Enter');
    assert.equal(await page.locator('#trial').isVisible(), false, 'start without consent must be blocked');
    await page.locator('#consent').focus(); await page.keyboard.press('Space');
    await page.locator('#start').focus(); await page.keyboard.press('Enter');
    await page.getByText(/PRACTICE/).waitFor();
    await page.locator('input[name=ans]:focus').first().waitFor();
    // practice: submit via keyboard
    await page.locator('#submit').focus(); await page.keyboard.press('Enter');
    const contract = JSON.parse(fs.readFileSync(path.join(__dirname, 'browser-contract.json'), 'utf8'));
    const assignment = contract.assignments.find((a) => a.seed === seed && a.executor === executor);
    const checks = ['banner', 'consent-gate', 'practice'];
    for (let i = 0; i < assignment.trials.length; i++) {
      const spec = assignment.trials[i];
      await page.getByText('Trial ' + (i + 1) + ' of ' + assignment.trials.length).waitFor();
      await page.locator('input[name=ans]:focus').first().waitFor(); // presentation complete
      const dispute = contract.disputes.find((d) => d.dispute_id === spec.dispute_id);
      // level-0 cues must be visible without any disclosure action, in both variants
      const text = await page.locator('#view').innerText();
      assert.ok(text.includes(dispute.challenge_claim.text), 'challenge visible level0 ' + spec.variant);
      for (const s of dispute.sources) { assert.ok(text.includes(s.source_id), 'source visible ' + s.source_id); assert.ok(text.includes(s.origin), 'origin visible ' + s.origin); }
      for (const g of dispute.independence_groups) assert.ok(text.includes(g.group_id), 'group visible ' + g.group_id);
      if (spec.variant === 'GRAPH') {
        assert.ok(await page.locator('section[aria-label="linear equivalent of the graph"] ol li').count() >= dispute.evidence.length + 2, 'linear equivalent');
        await page.locator('g.node').first().focus();
      }
      // keyboard-only disclosure: focus button, press Enter, panel must open
      const btn = page.getByRole('button', {name: 'Show provenance detail'});
      await btn.focus(); await page.keyboard.press('Enter');
      assert.equal(await page.locator('#disc-provenance_detail').isVisible(), true, 'disclosure keyboard-openable');
      assert.equal(await btn.getAttribute('aria-expanded'), 'true');
      if (i === 1) { await page.locator('#pause').focus(); await page.keyboard.press('Enter'); assert.equal(await page.locator('#submit').isDisabled(), true); await page.locator('#resume').focus(); await page.keyboard.press('Enter'); checks.push('pause-resume'); }
      // deterministic technical answers: pick the first radio, first source, "yes" challenge, overload medium
      const answerChoice = dispute.answer_choices[i % dispute.answer_choices.length];
      await page.locator('input[name=ans][value="' + answerChoice + '"]').focus(); await page.keyboard.press('Space');
      await page.locator('input[name=prov]').first().focus(); await page.keyboard.press('Space');
      await page.locator('input[name=chal][value=challenge_seen]').focus(); await page.keyboard.press('Space');
      await page.locator('input[name=ovl][value=medium]').focus(); await page.keyboard.press('Space');
      await page.locator('#submit').focus(); await page.keyboard.press('Enter');
    }
    await page.getByText(/Lifecycle complete/).waitFor();
    checks.push('8-trials-keyboard-only', 'level0-cues-both-variants', 'graph-linear-equivalent', 'disclosure-keyboard');
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#export').focus(); await page.keyboard.press('Enter');
    const download = await downloadPromise; await download.saveAs(out);
    const doc = JSON.parse(fs.readFileSync(out, 'utf8'));
    assert.equal(doc.trials.length, assignment.trials.length);
    assert.equal(doc.trials.filter((t) => t.pointer_used).length, 0, 'keyboard-only run must not record pointer use');
    assert.ok(doc.trials.every((t) => t.disclosure_actions >= 1));
    assert.ok(!JSON.stringify(doc).includes('correct'), 'export must carry no self-grading');
    await page.locator('#import').setInputFiles(out);
    await page.getByText(/Envelope schema\/bindings OK/).waitFor();
    const bad = structuredClone(doc); bad.contract_sha256 = '0'.repeat(64);
    await page.locator('#import').setInputFiles({name: 'bad.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(bad))});
    await page.getByText(/Import FAILED/).waitFor();
    checks.push('export', 'reimport-ok', 'forged-binding-rejected');
    // withdrawal path on a fresh session keeps missing trials in the denominator
    await page.goto(url); await page.getByText(/Frozen contract 1\.0\.0 loaded/).waitFor();
    await page.locator('#consent').check(); await page.locator('#start').click(); await page.getByText(/PRACTICE/).waitFor();
    await page.locator('#submit').click(); await page.getByText('Trial 1 of').waitFor(); await page.locator('#withdraw').click();
    await page.getByText(/Lifecycle withdrawn/).waitFor();
    const dl2 = page.waitForEvent('download'); await page.locator('#export').click(); const d2 = await dl2; await d2.saveAs(out + '.withdrawn.json');
    const doc2 = JSON.parse(fs.readFileSync(out + '.withdrawn.json', 'utf8'));
    assert.equal(doc2.trials.length, assignment.trials.length); assert.equal(doc2.session.lifecycle, 'withdrawn');
    checks.push('withdraw-keeps-denominator');
    const external = requests.filter((u) => !u.startsWith('http://127.0.0.1:'));
    assert.deepEqual(external, [], 'no external requests'); assert.deepEqual(errors, []);
    console.log(JSON.stringify({browser: browser.version(), checks, synthetic: true, seed, executor, mode}));
  } finally { if (browser) await browser.close(); await new Promise((r) => server.close(r)); }
})().catch((e) => { console.error(e.stack); process.exit(1); });
