# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import json

from test_evals_retrieval import StubModels
from nuvora import telemetry
from nuvora.mcp_client import tool_name
from nuvora.security import Fault


class AgentToolTests(StubModels):
    def setUp(self):
        super().setUp()
        self.auth.add_user('a','boss',self.password,'approver')
        self.boss={'tenant':'a','username':'boss','role':'approver'}

    def tool_model(self,tool,args,answer='Done.'):
        """First turn calls `tool`, the next turn answers."""
        def chat(handler,body):
            if any(m['role']=='tool' for m in body['messages']) or not body.get('tools'):
                return 200,{'choices':[{'message':{'content':answer}}],'usage':{'prompt_tokens':5,'completion_tokens':3}}
            call={'id':'c1','type':'function','function':{'name':tool,'arguments':json.dumps(args)}}
            return 200,{'choices':[{'message':{'content':'','tool_calls':[call]}}],'usage':{'prompt_tokens':5,'completion_tokens':3}}
        url,_=self.stub({('POST','/v1/chat/completions'):chat})
        return self.json('/api/models',{'name':'Agent model','provider':'openai','base_url':url+'/v1','upstream_model':'m'},expect=201)['id']

    def mcp_server(self):
        calls=[]
        tools=[{'name':'lookup','description':'Look up an order','inputSchema':{'type':'object','properties':{'order':{'type':'string'}},'required':['order']}},
               {'name':'create_ticket','description':'Open a ticket','inputSchema':{'type':'object','properties':{'title':{'type':'string'}}}}]

        def rpc(handler,body):
            calls.append({'body':body,'session':handler.headers.get('Mcp-Session-Id')})
            if 'id' not in body:
                return 202,b'',{}
            if body['method']=='initialize':
                return 200,{'jsonrpc':'2.0','id':body['id'],'result':{'protocolVersion':'2025-06-18','capabilities':{'tools':{}}}},{'Mcp-Session-Id':'s-1'}
            if body['method']=='tools/list':
                return 200,{'jsonrpc':'2.0','id':body['id'],'result':{'tools':tools}},{}
            if body['method']=='tools/call':
                frame='data: '+json.dumps({'jsonrpc':'2.0','id':body['id'],'result':{'content':[{'type':'text','text':'called '+body['params']['name']+' '+json.dumps(body['params']['arguments'])}]}})+'\n\n'
                return 200,frame.encode(),{'Content-Type':'text/event-stream'}
            return 200,{'jsonrpc':'2.0','id':body['id'],'error':{'code':-32601,'message':'nope'}},{}
        url,_=self.stub({('POST','/mcp'):rpc})
        return url+'/mcp',calls

    def run_agent(self,agent,message='go'):
        job=self.app.new_job(self.p,'agent',agent,{'message':message})
        self.app.process_job(self.p,job['id'])
        return self.app.get(self.p,'jobs',job['id'])

    def test_openapi_import(self):
        url,_=self.stub({})
        spec={'openapi':'3.0.3','servers':[{'url':url}],'components':{'schemas':{'Ticket':{'type':'object','properties':{'title':{'type':'string'},'priority':{'type':'integer','minimum':1,'maximum':5}},'required':['title']}}},
              'paths':{'/status':{'get':{'operationId':'getStatus','summary':'Service status','parameters':[{'name':'region','in':'query','required':True,'schema':{'type':'string','enum':['eu','us']}}]}},
                       '/tickets':{'post':{'operationId':'createTicket','requestBody':{'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Ticket'}}}}}},
                       '/items/{id}':{'get':{'operationId':'getItem'}},
                       '/auth':{'get':{'operationId':'whoami','parameters':[{'name':'X-Key','in':'header','schema':{'type':'string'}}]}},
                       '/nested':{'post':{'operationId':'nested','requestBody':{'content':{'application/json':{'schema':{'type':'object','properties':{'a':{'type':'object'}}}}}}}}}}
        out=self.json('/api/actions/import-openapi',{'spec':spec},expect=201)
        self.assertEqual([c['operation'] for c in out['created']],['getStatus','createTicket'])
        self.assertEqual([c['requires_approval'] for c in out['created']],[False,True])
        reasons={s['operation']:s['reason'] for s in out['skipped']}
        self.assertEqual(set(reasons),{'getItem','whoami','nested'})
        self.assertIn('Path parameters',reasons['getItem'])
        ticket=self.app.get(self.p,'actions',out['created'][1]['id'])
        self.assertEqual(ticket['input_schema']['properties']['priority'],{'type':'integer','minimum':1,'maximum':5})
        self.json('/api/actions/import-openapi',{'spec':spec},token=self.dev,expect=403)
        self.json('/api/actions/import-openapi',{'spec':{'swagger':'2.0'}},expect=400)

    def test_readonly_mcp_tool_runs_directly(self):
        url,calls=self.mcp_server()
        server=self.json('/api/mcp_servers',{'name':'Orders','url':url,'readonly':True,'tools':['lookup']},expect=201)
        self.assertEqual(server['available'],['create_ticket','lookup'])
        self.json('/api/mcp_servers',{'name':'Bad','url':url,'tools':['missing']},expect=400)
        name=tool_name(server['id'],'lookup')
        self.assertIn(name,self.json('/api/tools')['tools'])
        model=self.tool_model(name,{'order':'A-1'})
        agent=self.app.create(self.p,'agents',{'name':'Orders agent','model':model,'tools':[name]})
        done=self.run_agent(agent['id'])
        self.assertEqual(done['status'],'completed',done.get('error'))
        tool_step=next(t for t in done['trace'] if t['type']=='tool')
        self.assertEqual(tool_step['result']['content'],'called lookup {"order": "A-1"}')
        self.assertLessEqual(tool_step['start'],tool_step['end'])
        self.assertTrue(any(c['session']=='s-1' for c in calls if c['body'].get('method')=='tools/call'))

    def test_writing_mcp_tool_needs_approval(self):
        url,calls=self.mcp_server()
        server=self.json('/api/mcp_servers',{'name':'Tickets','url':url,'tools':['create_ticket']},expect=201)
        name=tool_name(server['id'],'create_ticket')
        model=self.tool_model(name,{'title':'Disk full'})
        agent=self.app.create(self.p,'agents',{'name':'Ticket agent','model':model,'tools':[name]})
        waiting=self.run_agent(agent['id'])
        self.assertEqual(waiting['status'],'waiting_approval')
        self.assertFalse(any(c['body'].get('method')=='tools/call' for c in calls))
        approval=self.app.get(self.p,'approvals',waiting['checkpoint']['approval'])
        self.assertEqual(approval['action']['type'],'mcp_call')
        self.app.decide(self.boss,approval['id'],'approved',approval['digest'])
        self.app.process_job(self.p,waiting['id'])
        done=self.app.get(self.p,'jobs',waiting['id'])
        self.assertEqual(done['status'],'completed',done.get('error'))
        self.assertTrue(any(c['body'].get('method')=='tools/call' for c in calls))

    def test_memory_search_scopes_to_owner_and_agent(self):
        model=self.tool_model('memory_search',{'query':'favourite region'})
        agent=self.app.create(self.p,'agents',{'name':'Rememberer','model':model,'tools':['memory_search']})
        put=lambda owner,agent_id,text:self.store.put('a','memory',{'name':'m','session':'s','owner':owner,'agent':agent_id,'text':text})
        put('owner',agent['id'],'The favourite region is eu-central.')
        put('owner','other-agent','The favourite region is us-east.')
        put('dev',agent['id'],'The favourite region is ap-south.')
        hits=self.app.memory_search(self.p,agent,'favourite region')
        self.assertEqual([h['text'] for h in hits],['The favourite region is eu-central.'])

    def test_session_summary_goes_to_approval(self):
        model=self.tool_model('none',{},answer='Order A-1 ships Friday.')
        agent=self.app.create(self.p,'agents',{'name':'Summariser','model':model,'tools':[],'summarize_memory':True})
        waiting=self.run_agent(agent['id'])
        self.assertEqual(waiting['status'],'waiting_approval')
        approval=self.app.get(self.p,'approvals',waiting['checkpoint']['approval'])
        self.assertTrue(approval['action']['summary'])
        self.app.decide(self.boss,approval['id'],'approved',approval['digest'])
        self.app.process_job(self.p,waiting['id'])
        done=self.app.get(self.p,'jobs',waiting['id'])
        self.assertEqual(done['result']['memory'],'summary saved')
        self.assertEqual(done['result']['answer'],'Order A-1 ships Friday.')
        self.assertTrue(any(m.get('agent')==agent['id'] for m in self.app.list(self.p,'memory')))
        second=self.run_agent(agent['id'])
        approval=self.app.get(self.p,'approvals',second['checkpoint']['approval'])
        self.app.decide(self.boss,approval['id'],'rejected',approval['digest'])
        self.app.process_job(self.p,second['id'])
        rejected=self.app.get(self.p,'jobs',second['id'])
        self.assertEqual((rejected['status'],rejected['result']['memory']),('completed','summary rejected'))

    def test_otlp_export(self):
        received=[]
        url,_=self.stub({('POST','/v1/traces'):lambda h,b:(received.append(b) or 200,{},{})})
        model=self.tool_model('memory_search',{'query':'x'})
        agent=self.app.create(self.p,'agents',{'name':'Traced','model':model,'tools':['memory_search']})
        done=self.run_agent(agent['id'])
        self.assertTrue(done['started']<=done['finished'])
        telemetry.export(done,'a',url+'/v1/traces',wait=True)
        spans=received[0]['resourceSpans'][0]['scopeSpans'][0]['spans']
        self.assertEqual(spans[0]['name'],'agent run')
        self.assertEqual({s['parentSpanId'] for s in spans[1:]},{spans[0]['spanId']})
        self.assertIn('tool memory_search',[s['name'] for s in spans])
        self.assertNotIn('Done.',json.dumps(received))

    def test_mcp_server_admin_only(self):
        url,_=self.mcp_server()
        with self.assertRaises(Fault):
            self.app.create({'tenant':'a','username':'dev','role':'developer'},'mcp_servers',{'name':'X','url':url,'tools':[]})
