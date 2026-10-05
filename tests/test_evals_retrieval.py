# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import json
import re
from pathlib import Path

from harness import LiveServer
from nuvora.platform import Platform
from nuvora.providers import Providers
from nuvora.retrieval import chunks, search

FIXTURE=json.loads((Path(__file__).parent/'fixtures'/'retrieval.json').read_text())


def candidates():
    out=[]
    for name,text in FIXTURE['documents'].items():
        out.extend({**c,'document':name} for c in chunks(text,1000,150))
    return out


def recall_at(k,rank):
    hits=sum(any(r['document']==q['relevant'] for r in rank(q['q'])[:k]) for q in FIXTURE['queries'])
    return hits/len(FIXTURE['queries'])


class StubModels(LiveServer):
    def make_platform(self):
        return Platform(self.store,self.auth,Providers({'127.0.0.1'}))

    def openai_model(self,reply,name='Judge'):
        """reply(messages) -> assistant text."""
        def chat(handler,body):
            self.seen.append(body)
            return 200,{'choices':[{'message':{'content':reply(body['messages'])}}],'usage':{'prompt_tokens':10,'completion_tokens':5}}
        self.seen=getattr(self,'seen',[])
        url,_=self.stub({('POST','/v1/chat/completions'):chat})
        return self.json('/api/models',{'name':name,'provider':'openai','base_url':url+'/v1','upstream_model':'m'},expect=201)['id']

    def evaluate(self,evaluation):
        job=self.app.new_job(self.p,'evaluation',evaluation,{},None)
        self.app.process_job(self.p,job['id'])
        return self.app.get(self.p,'jobs',job['id'])


class EvaluationJudgeTests(StubModels):
    def demo(self):
        return next(m['id'] for m in self.app.list(self.p,'models') if m['provider']=='demo')

    def test_judge_scores_and_reasons(self):
        judge=self.openai_model(lambda m:'Verdict: {"score": 0.9, "reason": "Names the approver rule."}')
        ev=self.json('/api/evaluations',{'name':'Judged','model':self.demo(),'judge_model':judge,
                     'cases':[{'input':'Who approves?','judge':{'criteria':'Says a different person approves','min_score':0.8}}]},expect=201)['id']
        result=self.evaluate(ev)['result']
        case=result['cases'][0]
        self.assertTrue(case['passed'])
        self.assertEqual(case['judge']['score'],0.9)
        self.assertEqual(case['judge']['reason'],'Names the approver rule.')
        self.assertIn('LLM judge',result['grading'])
        prompt=self.seen[-1]['messages']
        self.assertEqual(prompt[0]['role'],'system')
        self.assertIn('CRITERIA:\nSays a different person approves',prompt[1]['content'])
        self.assertIn('ANSWER:',prompt[1]['content'])

    def test_low_or_malformed_verdicts_fail(self):
        replies=iter(['{"score": 0.4, "reason": "Vague"}','I think it is fine','{"score": 7}'])
        judge=self.openai_model(lambda m:next(replies))
        ev=self.json('/api/evaluations',{'name':'Strict','model':self.demo(),'judge_model':judge,'pass_threshold':0.5,
                     'cases':[{'input':'a','judge':{'criteria':'x'}},{'input':'b','judge':{'criteria':'x'}},{'input':'c','judge':{'criteria':'x'}}]},expect=201)['id']
        cases=self.evaluate(ev)['result']['cases']
        self.assertEqual([c['passed'] for c in cases],[False,False,False])
        self.assertTrue(cases[1]['judge']['malformed'])
        self.assertTrue(cases[2]['judge']['malformed'])

    def test_grounded_case_uses_retrieved_passages(self):
        kb=self.json('/api/knowledge',{'name':'Facts'},expect=201)['id']
        self.json(f'/api/knowledge/{kb}/ingest',{'name':'outage','text':FIXTURE['documents']['frankfurt-outage']},expect=201)
        judge=self.openai_model(lambda m:'{"score": 1, "reason": "Supported by incident 2291."}' if 'PASSAGES:' in m[1]['content'] else '{"score":0,"reason":"no passages"}')
        ev=self.json('/api/evaluations',{'name':'Grounded','model':self.demo(),'judge_model':judge,'knowledge_ids':[kb],
                     'cases':[{'input':'Which customers did the Frankfurt power fault hit?','grounded':True,'contains':['Frankfurt']}]},expect=201)['id']
        case=self.evaluate(ev)['result']['cases'][0]
        self.assertTrue(case['passed'],case)
        self.assertEqual(case['grounded']['passages'],1)
        self.assertIn('Incident 2291',case['answer'])

    def test_offline_demo_judge_is_labelled_synthetic(self):
        ev=self.json('/api/evaluations',{'name':'Demo','model':self.demo(),'cases':[{'input':'Keep isolates agents','judge':{'criteria':'mentions Keep isolates agents'}}]},expect=201)['id']
        case=self.evaluate(ev)['result']['cases'][0]
        self.assertEqual(case['judge']['judge'],'synthetic')

    def test_validation(self):
        bad=[{'input':'x','judge':{'criteria':''}},{'input':'x','judge':{'criteria':'ok','min_score':2}},{'input':'x','grounded':True}]
        for case in bad:
            self.json('/api/evaluations',{'name':'Bad','model':self.demo(),'cases':[case]},expect=400)


class RetrievalQualityTests(StubModels):
    def test_recall_on_fixture(self):
        pool=candidates()
        bm25=recall_at(3,lambda q:search(q,pool,3,fuse=False))
        hybrid=recall_at(3,lambda q:search(q,pool,3))
        self.assertGreaterEqual(bm25,0.75)
        self.assertGreaterEqual(hybrid,0.75)

    def test_rerank_reorders_with_model_scores(self):
        relevant={q['q']:FIXTURE['documents'][q['relevant']][:60] for q in FIXTURE['queries']}

        def oracle(messages):
            text=messages[1]['content']
            query=re.search(r'QUERY: (.*)',text).group(1)
            items=re.findall(r'\[(\d+)\] (.*)',text)
            return json.dumps([{'i':int(i),'score':10 if body.startswith(relevant[query]) else 1} for i,body in items])
        reranker=self.openai_model(oracle,'Reranker')
        kb=self.json('/api/knowledge',{'name':'Fixture','rerank_model':reranker},expect=201)
        self.assertIn('LLM rerank',kb['retrieval'])
        for name,text in FIXTURE['documents'].items():
            self.json(f'/api/knowledge/{kb["id"]}/ingest',{'name':name,'text':text},expect=201)
        hits=0
        for q in FIXTURE['queries']:
            top=self.json('/api/retrieve',{'knowledge_ids':[kb['id']],'query':q['q'],'top_k':1},expect=200)['citations']
            hits+=bool(top) and top[0]['document']==q['relevant']
            if top:
                self.assertIn('rerank_score',top[0])
        self.assertEqual(hits/len(FIXTURE['queries']),1.0)

    def test_rerank_failure_keeps_fused_order(self):
        reranker=self.openai_model(lambda m:'no idea','Broken')
        kb=self.json('/api/knowledge',{'name':'Fixture','rerank_model':reranker},expect=201)['id']
        self.json(f'/api/knowledge/{kb}/ingest',{'name':'budget','text':FIXTURE['documents']['budget']},expect=201)
        top=self.json('/api/retrieve',{'knowledge_ids':[kb],'query':'daily token budget'},expect=200)['citations']
        self.assertEqual(top[0]['document'],'budget')
        self.assertNotIn('rerank_score',top[0])

    def test_ollama_embeddings(self):
        def embed(handler,body):
            return 200,{'embeddings':[[float(len(t)),1.0] for t in body['input']]}
        url,calls=self.stub({('POST','/api/embed'):embed})
        model=self.json('/api/models',{'name':'Embed','provider':'ollama','base_url':url,'upstream_model':'nomic-embed-text','capability':'embedding'},expect=201)['id']
        kb=self.json('/api/knowledge',{'name':'Semantic','embedding_model':model},expect=201)['id']
        self.json(f'/api/knowledge/{kb}/ingest',{'name':'pii','text':FIXTURE['documents']['pii']},expect=201)
        self.assertEqual(calls[0]['body']['model'],'nomic-embed-text')
        self.assertEqual(len(self.json('/api/retrieve',{'knowledge_ids':[kb],'query':'email redaction'},expect=200)['citations']),1)
