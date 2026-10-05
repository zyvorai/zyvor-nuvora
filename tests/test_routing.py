# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import json
import time

from test_evals_retrieval import StubModels
from nuvora.security import Fault


class RoutingTests(StubModels):
    def model(self,reply,name,usage=None,stream=False,**prices):
        calls=[]
        def chat(handler,body):
            calls.append(body)
            text=reply(body['messages'])
            if body.get('stream'):
                frames=''.join('data: '+json.dumps({'choices':[{'delta':{'content':w+' '}}]})+'\n\n' for w in text.split())+'data: [DONE]\n\n'
                return 200,frames.encode(),{'Content-Type':'text/event-stream'}
            return 200,{'choices':[{'message':{'content':text}}],'usage':usage or {'prompt_tokens':10,'completion_tokens':5}}
        url,_=self.stub({('POST','/v1/chat/completions'):chat})
        mid=self.json('/api/models',{'name':name,'provider':'openai','base_url':url+'/v1','upstream_model':'m',**prices},expect=201)['id']
        return mid,calls

    def router(self,models,**extra):
        return self.json('/api/routers',{'name':'Cascade','models':models,**extra},expect=201)['id']

    def ask(self,router,text='What is Keep?',expect=200):
        return self.json('/api/chat',{'model':'router:'+router,'messages':[{'role':'user','content':text}]},expect=expect)

    def test_cheap_answer_is_accepted(self):
        cheap,cheap_calls=self.model(lambda m:'Keep runs code in microVMs.','Cheap')
        strong,strong_calls=self.model(lambda m:'Strong answer.','Strong')
        out=self.ask(self.router([cheap,strong]))
        self.assertEqual(out['model'],cheap)
        self.assertNotIn('escalations',out)
        self.assertEqual(len(strong_calls),0)
        self.assertEqual(out['routing'],'router Cascade: Cheap')

    def test_uncertain_answer_escalates_and_both_are_metered(self):
        cheap,_=self.model(lambda m:"I'm not sure about that.",'Cheap')
        strong,_=self.model(lambda m:'Keep runs code in microVMs.','Strong')
        before=self.app.usage(self.p)['requests']
        out=self.ask(self.router([cheap,strong]))
        self.assertEqual(out['model'],strong)
        self.assertEqual(out['escalations'],[{'model':cheap,'reason':'model expressed uncertainty'}])
        self.assertIn('after 1 escalation',out['routing'])
        self.assertEqual(self.app.usage(self.p)['requests'],before+2)

    def test_judge_score_escalates(self):
        cheap,_=self.model(lambda m:'Something vague.','Cheap')
        strong,_=self.model(lambda m:'A precise answer.','Strong')
        judge,_=self.model(lambda m:json.dumps({'score':.9 if 'precise' in m[-1]['content'] else .2,'reason':'r'}),'Judge')
        out=self.ask(self.router([cheap,strong],judge_model=judge,min_score=.6))
        self.assertEqual(out['model'],strong)
        self.assertEqual(out['escalations'][0]['reason'],'judge score 0.2')

    def test_streamed_router(self):
        cheap,_=self.model(lambda m:"I don't know.",'Cheap')
        strong,strong_calls=self.model(lambda m:'Keep runs code in microVMs.','Strong')
        rid=self.router([cheap,strong])
        events=list(self.app.open_stream(self.p,{'model':'router:'+rid,'messages':[{'role':'user','content':'q'}]}))
        self.assertTrue(strong_calls[-1]['stream'])
        self.assertEqual(''.join(e['text'] for e in events if e['event']=='delta').strip(),'Keep runs code in microVMs.')
        self.assertEqual(events[-1]['escalations'][0]['model'],cheap)

    def test_router_validation_and_references(self):
        cheap,_=self.model(lambda m:'x','Cheap')
        self.json('/api/routers',{'name':'One','models':[cheap]},expect=400)
        self.json('/api/routers',{'name':'Dup','models':[cheap,cheap]},expect=400)
        strong,_=self.model(lambda m:'y','Strong')
        self.router([cheap,strong])
        with self.assertRaises(Fault) as ctx:
            self.app.delete(self.p,'models',strong)
        self.assertEqual(ctx.exception.status,409)

    def test_provider_cached_tokens_are_priced_and_saved(self):
        usage={'prompt_tokens':100,'completion_tokens':10,'prompt_tokens_details':{'cached_tokens':80}}
        mid,_=self.model(lambda m:'ok','Priced',usage,input_price=10,output_price=20,cached_input_price=1)
        out=self.json('/api/chat',{'model':mid,'messages':[{'role':'user','content':'hi'}]},expect=200)
        self.assertAlmostEqual(out['cost'],(20*10+80*1+10*20)/1e6)
        self.assertAlmostEqual(out['saved'],80*9/1e6)
        self.assertEqual(out['usage']['cached_tokens'],80)
        summary=self.app.usage(self.p)
        self.assertEqual(summary['cached_tokens'],80)
        self.assertAlmostEqual(summary['saved'],80*9/1e6)

    def test_cache_ttl_policy(self):
        mid,calls=self.model(lambda m:'ok','Cached',input_price=5,output_price=5)
        policy=self.app.list(self.p,'policies')[0]
        base={k:policy[k] for k in ('name','redact_pii','detect_injection','max_chars','daily_tokens','blocked_topics')}
        with self.assertRaises(Fault):
            self.app.create(self.p,'policies',{**base,'cache_ttl':5,'expected_revision':policy['revision']},policy['id'])
        self.app.create(self.p,'policies',{**base,'cache_ttl':60,'expected_revision':policy['revision']},policy['id'])
        body={'model':mid,'temperature':0,'cache':True,'messages':[{'role':'user','content':'hi'}]}
        self.json('/api/chat',body,expect=200)
        second=self.json('/api/chat',body,expect=200)
        self.assertTrue(second['cached'])
        self.assertGreater(second['saved'],0)
        self.assertEqual(len(calls),1)
        expires=self.store.db.execute('SELECT expires FROM cache WHERE tenant=?',('a',)).fetchone()[0]
        self.assertAlmostEqual(expires-time.time(),60,delta=5)
