// Actual offline browser regression. Output is a synthetic session, never human evidence.
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
let playwright;
try { playwright=require('playwright'); }
catch (firstError) {
 const Module=require('node:module');
 const bundled=path.join(process.env.USERPROFILE||process.env.HOME||'', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
 process.env.NODE_PATH=[process.env.NODE_PATH,bundled].filter(Boolean).join(path.delimiter);
 Module._initPaths();
 try { playwright=require(path.join(bundled,'playwright')); }
 catch (_) { throw firstError; }
}
const {chromium}=playwright;
(async()=>{
 const role=process.argv[3]||'owner';assert.ok(['owner','reviewer'].includes(role),'role must be owner or reviewer');
 const allowed={'/index.html':'text/html','/app.js':'text/javascript','/style.css':'text/css','/browser-contract.json':'application/json'};
 const server=http.createServer((req,res)=>{const name=req.url.split('?')[0];if(!(name in allowed)){res.writeHead(404);res.end();return;}res.setHeader('Content-Type',allowed[name]);res.end(fs.readFileSync(path.join(__dirname,name.slice(1))));});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 let browser;
 try{
  const executable=process.env.S1013_BROWSER||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  browser=await chromium.launch({headless:true,executablePath:executable});
  const page=await browser.newPage({acceptDownloads:true}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const url='http://127.0.0.1:'+server.address().port+'/index.html';
  await page.goto(url);await page.getByText(/Frozen 1\.1\.0-draft loaded/).waitFor();await page.locator('#role').selectOption(role);
  await page.locator('#start').click();assert.equal(await page.locator('#scenario-card').isVisible(),false,'no consent must block start');
  await page.locator('#consent').check();await page.locator('#start').click();
  for(let i=0;i<4;i++){
   await page.locator('#answer').fill(['scoped revocable grant','only connected principals','untrusted until gated','no'][i]);
   await page.locator('#explanation').fill(['principal+scope+expiry','access basis stated','provenance+gate status','explicit connection required, default deny'][i]);
   if(i===0)await page.getByRole('button',{name:'Tired',exact:true}).click();
   await page.locator('#save-answer').click();
  }
  await page.locator('#stop-request').click();await page.getByText('Stop pending acknowledgement from mock agents',{exact:true}).waitFor();
  await page.getByText('Stop confirmed by all mock agents',{exact:true}).waitFor();
  assert.equal(await page.locator('#agent-states').innerText(),'A-1: stopped\nA-2: stopped');
  await page.locator('#continue').click();await page.locator('#pause').click();
  assert.equal(await page.getByRole('button',{name:'approve',exact:true}).isDisabled(),true);
  await page.locator('#resume').click();
  for(let i=0;i<36;i++)await page.getByRole('button',{name:'deny',exact:true}).click();
  await page.getByText(/Synthetic session complete/).waitFor();
  const downloadPromise=page.waitForEvent('download');await page.locator('#export').click();
  const download=await downloadPromise;await download.saveAs(process.argv[2]);
  const doc=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
  assert.equal(doc.session.role,role);assert.equal(doc.answers.responses.length,4);assert.equal(doc.answers.responses[3].primary.value,'no');
  assert.equal(doc.events.events.find(e=>e.type==='fatigue_report').fatigue,'tired');
  assert.equal(doc.events.events.filter(e=>e.type==='decision').length,36);
  assert.equal(doc.events.events.filter(e=>e.type==='stop_confirmed').length,1);
  await page.locator('#import').setInputFiles(process.argv[2]);await page.getByText(/Envelope schema\/bindings OK/).waitFor();
  const bad=structuredClone(doc);bad.session.protocol_version='forged';
  await page.locator('#import').setInputFiles({name:'bad.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(bad))});
  await page.getByText(/Import FAILED/).waitFor();
  // Fresh session, genuine simulated acknowledgement failure (no self-confirm button).
  await page.goto(url);await page.getByText(/Frozen 1\.1\.0-draft loaded/).waitFor();await page.locator('#consent').check();await page.locator('#start').click();
  for(let i=0;i<4;i++)await page.locator('#save-answer').click();
  await page.locator('#stuck').check();await page.locator('#stop-request').click();await page.getByText(/Stop failed: mock agent still pending/).waitFor();
  await page.locator('#withdraw').click();assert.equal(await page.locator('#withdraw').isDisabled(),true);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({browser:browser.version(),role,checks:['consent','free-responses','fatigue-value','stop-ack','stop-failure','pause-resume','36-approvals','export-import','invalid-import','withdraw'],synthetic:true}));
 }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e.stack);process.exit(1);});
