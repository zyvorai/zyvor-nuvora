// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
// @vitest-environment jsdom
import {afterEach,describe,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import App from './App';
const fixtures:Record<string,any>={models:[{id:'demo',name:'Offline demo',provider:'demo',capability:'chat',enabled:true,input_price:0,output_price:0}],knowledge:[{id:'guide',name:'Field guide',retrieval:'BM25 + hashed lexical vectors'}],agents:[{id:'agent',name:'Investigator',model:'demo',tools:['knowledge_search'],max_steps:5}]};
const sse=(events:[string,any][])=>events.map(([e,d])=>`event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join('');
function setup(role='admin',authenticated=true){
 const fetch=vi.fn(async(path:string)=>{
  if(path==='/api/session')return {ok:authenticated,status:authenticated?200:401,json:async()=>authenticated?{principal:{tenant:'test',username:'alice',role},csrf:'test-csrf'}:{error:'Sign in required'}};
  if(path==='/api/overview')return {ok:true,json:async()=>({counts:{models:1,knowledge:1,jobs:0},usage:{tokens:0,cost:0},audit:{valid:true},recent_jobs:[]})};
  if(path==='/api/login')return {ok:true,json:async()=>({principal:{tenant:'test',username:'alice',role},csrf:'test-csrf'})};
  if(path==='/api/chat/stream')return new Response(sse([['start',{model:'demo',name:'Offline demo',routing:'explicit',cached:false}],['delta',{text:'[OFFLINE DEMO] '}],['delta',{text:'evidence answer'}],['done',{model:'demo',cached:false,cost:0,routing:'explicit',latency_ms:3,usage:{prompt_tokens:4,completion_tokens:3},evidence_class:'synthetic'}]]),{status:200,headers:{'Content-Type':'text/event-stream'}});
  if(path==='/api/chat')return {ok:true,json:async()=>({content:'[OFFLINE DEMO] evidence answer',evidence_class:'synthetic',cost:0,cached:false,routing:'explicit'})};
  if(path==='/api/retrieve')return {ok:true,json:async()=>({citations:[{text:'Keep evidence',document:'Guide',digest:'abc123',index:0,source:'test',lexical_score:1,score:.03}]})};
  if(path==='/api/agents/agent/versions')return {ok:true,json:async()=>({items:[{id:'agent:2',actor:'alice',created:2,snapshot:{...fixtures.agents[0],revision:2,max_steps:7}},{id:'agent:1',actor:'alice',created:1,snapshot:{...fixtures.agents[0],revision:1}}]})};
  if(path==='/api/tokens')return {ok:true,json:async()=>({tokens:[{id:'tok1',label:'CI pipeline',role:'viewer',username:'alice',created:1,expires:4102444800}]})};
  if(path==='/api/logout')return {ok:true,json:async()=>({ok:true})};
  if(path==='/api/agents/agent/run')return {ok:true,json:async()=>({id:'run1'})};
  return {ok:true,json:async()=>({items:fixtures[path.split('/').pop()||'']||[]})};
 });vi.stubGlobal('fetch',fetch);return fetch;
}
afterEach(()=>{cleanup();vi.unstubAllGlobals();location.hash='';localStorage.clear()});
describe('console workflows',()=>{
 it('signs in to the authenticated workspace',async()=>{
  const fetch=setup('admin',false);render(<App/>);await screen.findByRole('heading',{name:'Sign in.'});
  fireEvent.change(screen.getByLabelText('Username'),{target:{value:'admin'}});
  fireEvent.change(screen.getByLabelText('Password'),{target:{value:'LongPassword123'}});
  fireEvent.click(screen.getByRole('button',{name:'Sign in'}));await screen.findByRole('heading',{name:'Your intelligence stack'});
  const login=fetch.mock.calls.find(([p])=>p==='/api/login') as any;expect(JSON.parse(login[1].body)).toEqual({tenant:'default',username:'admin',password:'LongPassword123'});
 });
 it('rejects an empty sign-in before calling the server',async()=>{
  const fetch=setup('admin',false);render(<App/>);await screen.findByRole('heading',{name:'Sign in.'});
  fireEvent.click(screen.getByRole('button',{name:'Sign in'}));expect((await screen.findByRole('alert')).textContent).toBe('Wrong username or password.');
  expect(fetch.mock.calls.some(([p])=>p==='/api/login')).toBe(false);
 });
 it('lets a member choose another workspace',async()=>{
  const fetch=setup('admin',false);render(<App/>);await screen.findByRole('heading',{name:'Sign in.'});
  fireEvent.click(screen.getByRole('button',{name:/Workspace: default/}));fireEvent.change(screen.getByLabelText('Workspace'),{target:{value:'acme'}});
  fireEvent.change(screen.getByLabelText('Username'),{target:{value:'alice'}});fireEvent.change(screen.getByLabelText('Password'),{target:{value:'LongPassword123'}});
  fireEvent.click(screen.getByRole('button',{name:'Sign in'}));await screen.findByRole('heading',{name:'Your intelligence stack'});
  const login=fetch.mock.calls.find(([p])=>p==='/api/login') as any;expect(JSON.parse(login[1].body).tenant).toBe('acme');
 });
 it('navigates from the grouped mega menu',async()=>{
  setup();render(<App/>);await screen.findByRole('heading',{name:'Your intelligence stack'});
  fireEvent.click(screen.getByRole('button',{name:'Workspace'}));fireEvent.click(screen.getByRole('button',{name:/^Playground/}));
  await screen.findByRole('heading',{name:'Ask your model'});expect(location.hash).toBe('#playground');
 });
 it('labels synthetic output and shows retrieved citations',async()=>{
  location.hash='playground';const fetch=setup();render(<App/>);await screen.findByRole('heading',{name:'Ask your model'});
  await waitFor(()=>expect(screen.getByLabelText('Grounding').querySelectorAll('option').length).toBe(2));
  fireEvent.change(screen.getByLabelText('Grounding'),{target:{value:'guide'}});
  fireEvent.click(screen.getByRole('button',{name:'Generate answer'}));await screen.findByText('[OFFLINE DEMO] evidence answer');
  expect(screen.getAllByText('Keep evidence').length).toBeGreaterThan(0);expect(document.querySelector('.citation')?.textContent).toContain('Keep evidence');expect(fetch.mock.calls.some(([p])=>p==='/api/retrieve')).toBe(true);
 });
 it('disables generation for viewers',async()=>{
  location.hash='playground';setup('viewer');render(<App/>);await screen.findByRole('heading',{name:'Ask your model'});
  expect((screen.getByRole('button',{name:'Generate answer'}) as HTMLButtonElement).disabled).toBe(true);
 });
 it('queues an agent run from the console',async()=>{
  location.hash='agents';setup();render(<App/>);await screen.findByRole('button',{name:'Open agent'});fireEvent.click(screen.getByRole('button',{name:'Open agent'}));
  fireEvent.click(screen.getByRole('button',{name:'Run agent'}));await screen.findByRole('status');expect(screen.getByRole('status').textContent).toContain('run1');
 });
 it('retains opt-in dark mode',async()=>{
  setup();render(<App/>);await screen.findByRole('heading',{name:'Your intelligence stack'});fireEvent.click(screen.getByRole('button',{name:'Switch to dark mode'}));expect(document.documentElement.dataset.theme).toBe('dark');
 });
 it('restricts user administration for viewers',async()=>{
  location.hash='users';setup('viewer');render(<App/>);await screen.findByText('Administrator access required');expect(screen.queryByRole('button',{name:'Create member'})).toBeNull();
 });
 it('opens the command palette and navigates by fuzzy match',async()=>{
  setup();render(<App/>);await screen.findByRole('heading',{name:'Your intelligence stack'});
  fireEvent.keyDown(window,{key:'k',metaKey:true});
  const box=await screen.findByRole('combobox',{name:'Command'});
  fireEvent.change(box,{target:{value:'evidnc'}});
  expect(screen.getAllByRole('option')[0].textContent).toContain('Evidence');
  fireEvent.keyDown(box,{key:'Enter'});
  await waitFor(()=>expect(location.hash).toBe('#audit'));
  expect(screen.queryByRole('dialog',{name:'Command palette'})).toBeNull();
 });
 it('shows keyboard shortcuts and jumps with g-prefixed keys',async()=>{
  setup();render(<App/>);await screen.findByRole('heading',{name:'Your intelligence stack'});
  fireEvent.keyDown(window,{key:'?'});await screen.findByRole('dialog',{name:'Keyboard shortcuts'});
  fireEvent.keyDown(window,{key:'Escape'});
  await waitFor(()=>expect(screen.queryByRole('dialog',{name:'Keyboard shortcuts'})).toBeNull());
  fireEvent.keyDown(window,{key:'g'});fireEvent.keyDown(window,{key:'p'});
  await waitFor(()=>expect(location.hash).toBe('#playground'));
 });
 it('deep-links a resource drawer with history and a revision diff',async()=>{
  location.hash='agents/agent';setup();render(<App/>);
  const drawer=await screen.findByRole('dialog',{name:'Investigator'});
  expect(drawer.textContent).toContain('knowledge_search');
  fireEvent.click(screen.getByRole('tab',{name:'History'}));await screen.findByText('Current revision');
  fireEvent.click(screen.getByRole('tab',{name:'Diff'}));
  await waitFor(()=>expect(document.querySelector('.diff .add')?.textContent).toContain('"max_steps": 7'));
  fireEvent.click(screen.getByRole('button',{name:'Close panel'}));
  await waitFor(()=>expect(screen.queryByRole('dialog',{name:'Investigator'})).toBeNull());expect(location.hash).toBe('#agents');
 });
 it('lists API keys and signs out from the profile menu',async()=>{
  location.hash='keys';const fetch=setup();render(<App/>);await screen.findByText('CI pipeline');
  fireEvent.click(screen.getByRole('button',{name:/^Account/}));fireEvent.click(screen.getByRole('menuitem',{name:'Log out'}));
  await screen.findByRole('heading',{name:'Sign in.'});expect(fetch.mock.calls.some(([p])=>p==='/api/logout')).toBe(true);
 });
});
