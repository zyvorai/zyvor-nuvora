// End-to-end console smoke against a running server (local or deployed).
//   NUVORA_TEST_URL       default http://127.0.0.1:8789 (self-signed HTTPS is accepted)
//   NUVORA_TEST_USER      default admin
//   NUVORA_TEST_PASSWORD  default Nuvora-Test-Password-123
//   NUVORA_SCREENSHOT_DIR default docs/screenshots
const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
const assert=require('node:assert/strict');

const url=(process.env.NUVORA_TEST_URL||'http://127.0.0.1:8789').replace(/\/$/,'');
const user=process.env.NUVORA_TEST_USER||'admin';
const password=process.env.NUVORA_TEST_PASSWORD||'Nuvora-Test-Password-123';
const shots=path.resolve(process.env.NUVORA_SCREENSHOT_DIR||path.join(process.cwd(),'docs','screenshots'));

const pages=['overview','playground','models','knowledge','agents','actions','workflows','prompts','recipes','jobs','evaluations','batches','approvals','policies','usage','audit','users'];

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
  assert((await page.locator('.answer').innerText()).includes('OFFLINE DEMO'));checks++;
  assert(await page.locator('.citation').count()>0);checks++;
  await shot('02-playground');

  await go('knowledge');
  await page.getByLabel('Document title').fill('Browser test guide');
  await page.getByLabel('Document text').fill('Browser integration verifies quokka retrieval and document ingestion.');
  await page.getByRole('button',{name:'Index document',exact:true}).click();
  await page.getByRole('status').waitFor();checks++;
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
  await page.getByRole('button',{name:'Start workflow'}).click();
  await page.getByRole('status').waitFor();checks++;
  await shot('05-workflows');

  await go('evaluations');
  await page.getByRole('button',{name:'Evaluate',exact:true}).first().click();
  await page.getByRole('heading',{name:'Every step, in view.'}).waitFor();checks++;
  await page.waitForTimeout(1500);
  await page.getByRole('button',{name:'Inspect'}).first().click();
  await page.getByRole('heading',{name:'Run evidence'}).waitFor();checks++;
  await shot('06-runs');

  await go('approvals');await shot('07-approvals');
  await go('policies');
  await page.getByRole('button',{name:'Check policy'}).click();
  await page.getByText(/\[EMAIL\]/).waitFor();checks++;
  await shot('08-guardrails');

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

  await page.getByRole('button',{name:'Log out'}).click();
  await page.getByRole('heading',{name:'Sign in.'}).waitFor();checks++;

  assert.deepEqual(failures,[]);
  console.log(JSON.stringify({url,checks,errors:failures,viewports:[1440,390],screenshots:fs.readdirSync(shots).sort()},null,2));
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
