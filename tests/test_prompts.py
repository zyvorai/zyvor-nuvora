# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import json
from collections import Counter

from harness import LiveServer
from nuvora.security import Fault


class PromptVariantTests(LiveServer):
    def prompt(self,variants,template='Answer {{question}} briefly.'):
        return self.app.create(self.p,'prompts',{'name':'Answerer','template':template,'variants':variants})

    def test_validation(self):
        for bad in ([{'name':'control','template':'{{question}}','weight':10}],
                    [{'name':'b','template':'no variable','weight':10}],
                    [{'name':'b','template':'{{question}}','weight':60},{'name':'c','template':'{{question}}!','weight':50}],
                    [{'name':'B!','template':'{{question}}','weight':10}],
                    [{'name':'b','template':'{{question}}','weight':1.5}]):
            with self.assertRaises(Fault):
                self.prompt(bad)

    def test_sticky_weighted_split(self):
        prompt=self.prompt([{'name':'b','template':'Explain {{question}} in detail.','weight':50}])
        first=self.app.render_prompt(self.p,prompt['id'],{'question':'Keep'},subject='user-1')
        for _ in range(5):
            self.assertEqual(self.app.render_prompt(self.p,prompt['id'],{'question':'Keep'},subject='user-1')['variant'],first['variant'])
        counts=Counter(self.app.render_prompt(self.p,prompt['id'],{'question':'x'},subject=f's{i}')['variant'] for i in range(400))
        self.assertGreater(counts['b'],140)
        self.assertGreater(counts['control'],140)
        forced=self.app.render_prompt(self.p,prompt['id'],{'question':'Keep'},variant='b')
        self.assertEqual(forced,{'text':'Explain Keep in detail.','revision':1,'variant':'b'})
        with self.assertRaises(Fault):
            self.app.render_prompt(self.p,prompt['id'],{'question':'Keep'},variant='z')

    def test_zero_weight_variant_gets_no_traffic(self):
        prompt=self.prompt([{'name':'b','template':'B {{question}}','weight':0}])
        self.assertEqual({self.app.render_prompt(self.p,prompt['id'],{'question':'x'},subject=f's{i}')['variant'] for i in range(50)},{'control'})

    def test_experiment_scores_each_variant(self):
        demo=next(m['id'] for m in self.app.list(self.p,'models') if m['provider']=='demo')
        suite=self.app.create(self.p,'evaluations',{'name':'Marker','model':demo,'cases':[{'input':'Keep','contains':['VARIANT-B'],'excludes':[]}],'pass_threshold':1})
        prompt=self.prompt([{'name':'b','template':'VARIANT-B {{question}}','weight':20},{'name':'c','template':'Other {{question}}','weight':20}])
        status,raw,_=self.request('/api/prompts/'+prompt['id']+'/experiment',{'evaluation':suite['id']})
        self.assertEqual(status,202,raw)
        job=json.loads(raw)
        self.app.process_job(self.p,job['id'])
        done=self.app.get(self.p,'jobs',job['id'])
        self.assertEqual(done['status'],'completed',done.get('error'))
        scores={a['variant']:a['score'] for a in done['result']['arms']}
        self.assertEqual(scores,{'control':0,'b':1,'c':0})
        self.assertEqual(done['result']['winner'],'b')
        self.assertEqual(done['result']['arms'][0]['weight'],60)

    def test_experiment_needs_variants_and_a_variable(self):
        demo=next(m['id'] for m in self.app.list(self.p,'models') if m['provider']=='demo')
        suite=self.app.create(self.p,'evaluations',{'name':'S','model':demo,'cases':[{'input':'x','contains':[],'excludes':[]}]})
        plain=self.prompt([])
        with self.assertRaises(Fault):
            self.app.new_job(self.p,'experiment',plain['id'],{'evaluation':suite['id']})
        two=self.prompt([{'name':'b','template':'{{a}} {{b}}!','weight':10}],template='{{a}} {{b}}')
        with self.assertRaises(Fault):
            self.app.new_job(self.p,'experiment',two['id'],{'evaluation':suite['id']})
        job=self.app.new_job(self.p,'experiment',two['id'],{'evaluation':suite['id'],'variable':'a','variables':{'b':'fixed'}})
        self.assertEqual(job['spec']['variable'],'a')
