// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
// End-to-end console smoke against a running server (local or deployed).
//   NUVORA_TEST_URL       default http://127.0.0.1:8789 (self-signed HTTPS is accepted)
//   NUVORA_TEST_USER      default admin
//   NUVORA_TEST_PASSWORD  default Nuvora-Test-Password-123
//   NUVORA_SCREENSHOT_DIR default docs/screenshots
//   NUVORA_EXPECT_SSO     set to 1 when the server has NUVORA_OIDC_* configured
const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
const assert=require('node:assert/strict');

const url=(process.env.NUVORA_TEST_URL||'http://127.0.0.1:8789').replace(/\/$/,'');
const user=process.env.NUVORA_TEST_USER||'admin';
const password=process.env.NUVORA_TEST_PASSWORD||'Nuvora-Test-Password-123';
const shots=path.resolve(process.env.NUVORA_SCREENSHOT_DIR||path.join(process.cwd(),'docs','screenshots'));

const pages=['overview','playground','models','routers','knowledge','connectors','agents','actions','mcp_servers','workflows','prompts','recipes','jobs','evaluations','batches','approvals','policies','usage','audit','users','keys','settings'];

(async()=>{
  fs.mkdirSync(shots,{recursive:true});
  const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  const context=await browser.newContext({viewport:{width:1440,height:1000},ignoreHTTPSErrors:true});
  const page=await context.newPage();
  const failures=[];
  let checks=0;
  page.on('pageerror',e=>failures.push(e.message));
  page.on('console',m=>{if(m.type()==='error'&&/Content Security Policy/.test(m.text()))failures.push(m.text())});
  const shot=async name=>{await page.waitForTimeout(800);await page.screenshot({path:path.join(shots,name+'.png'),fullPage:true})};
  const go=async name=>{await page.goto(url+'/#'+name);await page.locator('footer').waitFor()};

  await page.goto(url);
  await page.getByRole('heading',{name:'Sign in.'}).waitFor();checks++;
  if(process.env.NUVORA_EXPECT_SSO==='1'){
    const sso=page.getByRole('link',{name:/^Sign in with /});
    await sso.waitFor();
    assert.equal(await sso.getAttribute('href'),'/api/auth/oidc/login');checks++;
  }
  await shot('00-login');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  assert.equal(await page.getByRole('alert').innerText(),'Wrong username or password.');checks++;
  await page.getByLabel('Username',{exact:true}).fill(user);
  await page.getByLabel('Password',{exact:true}).fill('definitely-wrong-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByText('Wrong username or password.').waitFor();checks++;
  await page.getByLabel('Password',{exact:true}).fill(password);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByRole('heading',{name:'Your intelligence stack'}).waitFor();checks++;
  await shot('01-overview');

  await page.getByRole('button',{name:'Workspace',exact:true}).click();
  await page.getByRole('region',{name:'Workspace'}).getByRole('button',{name:/^Playground/}).click();
  await page.getByRole('heading',{name:'Ask your model'}).waitFor();checks++;

  await page.getByLabel('Grounding').selectOption({label:'Zyvor field guide'});
  await page.getByRole('button',{name:'Generate answer'}).click();
  await page.getByRole('heading',{name:'Response',exact:true}).waitFor();
  await page.getByRole('button',{name:'Generate answer'}).waitFor({timeout:30000});
  assert((await page.locator('.answer').innerText()).includes('OFFLINE DEMO'));checks++;
  assert(await page.locator('.citation').count()>0);checks++;
  await page.getByLabel('Your question').fill('And who approves production changes?');
  await page.getByRole('button',{name:'Generate answer'}).click();
  await page.locator('.bubble.user').nth(1).waitFor();
  await page.getByRole('button',{name:'Generate answer'}).waitFor({timeout:30000});
  assert.equal(await page.locator('.answer').count(),2);checks++;
  await shot('02-playground');

  await page.getByRole('tab',{name:'Images'}).click();
  await page.getByLabel('Prompt',{exact:true}).fill('A lighthouse on a calm sea at dawn');
  await page.getByRole('button',{name:'Generate',exact:true}).click();
  await page.locator('.image-grid img').first().waitFor({timeout:30000});
  assert(await page.locator('.image-grid img').first().evaluate(img=>img.complete&&img.naturalWidth>0));checks++;
  await shot('19-images');
  await page.getByRole('tab',{name:'Chat'}).click();

  await page.keyboard.press('Control+k');
  await page.getByRole('combobox',{name:'Command'}).fill('setings');
  await page.waitForTimeout(200);
  await page.screenshot({path:path.join(shots,'14-command-palette.png')});
  await page.keyboard.press('Enter');
  await page.waitForFunction(()=>location.hash==='#settings');checks++;

  await go('knowledge');
  await page.getByLabel('Upload documents').setInputFiles({name:'smoke-upload.html',mimeType:'text/html',
    buffer:Buffer.from('<html><head><style>.x{}</style></head><body><h1>Smoke upload</h1><p>The pangolin runbook covers uploaded HTML ingestion.</p><script>alert(1)</script></body></html>')});
  await page.locator('.upload-list li.done').waitFor({timeout:20000});checks++;
  await page.getByRole('button',{name:'Delete smoke-upload.html'}).waitFor();checks++;
  await page.getByLabel('Search your knowledge').fill('pangolin');
  await page.getByRole('button',{name:'Retrieve evidence'}).click();
  await page.locator('.citation, .evidence, .result').filter({hasText:'pangolin'}).first().waitFor().catch(()=>page.getByText(/pangolin/).first().waitFor());checks++;
  await page.getByRole('button',{name:'Delete smoke-upload.html'}).click();
  await page.getByRole('button',{name:'Delete',exact:true}).click();
  await page.getByRole('button',{name:'Delete smoke-upload.html'}).waitFor({state:'detached'});checks++;
  await page.getByRole('button',{name:'Paste text'}).click();
  await page.getByLabel('Document title').fill('Browser test guide');
  await page.getByLabel('Document text').fill('Browser integration verifies quokka retrieval and document ingestion.');
  await page.getByRole('button',{name:'Index document',exact:true}).click();
  await page.getByText('Document indexed').first().waitFor();checks++;
  await page.getByLabel('Search your knowledge').fill('quokka');
  await page.getByRole('button',{name:'Retrieve evidence'}).click();
  await page.getByText('Browser test guide',{exact:true}).first().waitFor();checks++;
  await shot('03-knowledge');

  await go('agents');
  await page.getByRole('button',{name:'Open agent'}).first().click();
  await page.getByLabel('Task').fill('Explain Keep');
  await page.getByRole('button',{name:'Run agent',exact:true}).click();
  await page.getByRole('status').waitFor();checks++;
  await shot('04-agents');

  await go('workflows');
  await page.getByRole('button',{name:'Research → review → answer',exact:true}).click();
  const drawer=page.getByRole('dialog',{name:'Research → review → answer'});
  await drawer.locator('svg.dag').waitFor();checks++;
  await drawer.getByRole('button',{name:'Start workflow'}).click();
  await drawer.getByRole('status').waitFor();checks++;
  await shot('05-workflows');
  await drawer.getByRole('tab',{name:'History'}).click();
  await drawer.getByText('Current revision').waitFor();checks++;
  await drawer.getByRole('button',{name:'Edit',exact:true}).click();
  await page.getByRole('tab',{name:'Visual builder'}).waitFor();
  await page.waitForTimeout(400);
  await page.screenshot({path:path.join(shots,'15-workflow-builder.png')});checks++;
  await page.getByRole('button',{name:'Close dialog'}).click();
  await page.keyboard.press('Escape');

  await go('evaluations');
  await page.getByRole('button',{name:'Grounding smoke suite',exact:true}).click();
  await page.getByRole('dialog',{name:'Grounding smoke suite'}).getByRole('button',{name:'Edit',exact:true}).click();
  await page.getByRole('tab',{name:'Case editor'}).waitFor();
  await page.getByLabel('Grade with an LLM judge').first().check();
  await page.getByLabel('Judge criteria').fill('Mentions microVMs and isolation');
  await page.waitForTimeout(300);
  await page.screenshot({path:path.join(shots,'18-eval-case-editor.png')});
  await page.getByRole('button',{name:'Save new revision'}).click();
  await page.getByRole('dialog',{name:'Grounding smoke suite'}).waitFor({state:'detached'}).catch(()=>{});
  await page.keyboard.press('Escape');checks++;
  await go('evaluations');
  await page.getByRole('button',{name:'Evaluate',exact:true}).first().click();
  await page.getByRole('heading',{name:'Every step, in view.'}).waitFor();checks++;
  await page.waitForTimeout(1500);
  await page.getByRole('button',{name:'Inspect'}).first().click();
  await page.getByRole('heading',{name:'Run evidence'}).waitFor();checks++;
  await page.getByRole('table',{name:'Per-case results'}).waitFor();checks++;
  await shot('06-runs');

  await go('approvals');await shot('07-approvals');
  await go('policies');
  await page.getByRole('button',{name:'Check policy'}).click();
  await page.getByText(/\[EMAIL\]/).waitFor();checks++;
  await shot('08-guardrails');

  await go('keys');
  await page.getByLabel('Label').fill('Browser smoke key');
  await page.getByRole('button',{name:'Create key'}).click();
  await page.getByText('Copy this key now. It is shown only once.').waitFor();checks++;
  await page.getByRole('button',{name:'Revoke Browser smoke key'}).click();
  await page.getByRole('button',{name:'Revoke',exact:true}).click();
  await page.getByText('No active API keys').or(page.getByText('Browser smoke key').locator('xpath=ancestor::tr').filter({hasNot:page.locator('code')})).first().waitFor().catch(()=>{});
  await page.getByRole('button',{name:'I saved it'}).click();
  await shot('16-api-keys');
  await go('settings');
  await page.getByText('Provider allow-list',{exact:true}).waitFor();checks++;
  await page.getByText('Netra',{exact:true}).waitFor();checks++;
  await shot('17-settings');

  for(const name of pages){await go(name);checks++}
  await go('audit');await page.getByText('Chain verified').waitFor();checks++;await shot('09-evidence');
  await go('usage');await shot('10-usage');

  await go('overview');
  await page.getByRole('button',{name:'Switch to dark mode'}).click();
  assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');checks++;
  await page.reload();await page.getByRole('heading',{name:'Your intelligence stack'}).waitFor();
  assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');checks++;
  await shot('11-overview-dark');
  await go('playground');await shot('12-playground-dark');

  await page.setViewportSize({width:390,height:844});
  for(const name of pages){
    await go(name);
    const d=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:window.innerWidth}));
    assert(d.scroll<=d.width,`${name}: horizontal overflow ${JSON.stringify(d)}`);checks++;
  }
  await go('overview');await shot('13-mobile-dark');
  await page.getByRole('button',{name:'Switch to light mode'}).click();

  await page.getByRole('button',{name:/^Account/}).click();
  await page.getByRole('menuitem',{name:'Log out'}).click();
  await page.getByRole('heading',{name:'Sign in.'}).waitFor();checks++;

  assert.deepEqual(failures,[]);
  console.log(JSON.stringify({url,checks,errors:failures,viewports:[1440,390],screenshots:fs.readdirSync(shots).sort()},null,2));
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
