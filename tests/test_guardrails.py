# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import json
import unittest

from test_evals_retrieval import StubModels
from nuvora.security import Fault, grounding_score, guard, validate_policy

ENTITIES={'email':'mask','card':'mask','ssn':'mask','ipv4':'mask','phone':'mask','iban':'mask'}


class GuardRules(unittest.TestCase):
    def test_pii_entities_validate_checksums(self):
        out=guard('card 4111 1111 1111 1111 vs 4111 1111 1111 1112, ssn 123-45-6789, a@b.io ip 10.0.0.1 call +1 415 555 1234',{'pii_entities':ENTITIES})
        self.assertEqual(out['text'],'card [CARD] vs 4111 1111 1111 1112, ssn [SSN], [EMAIL] ip [IP] call [PHONE]')
        self.assertEqual(guard('IBAN GB82 WEST 1234 5698 7654 32',{'pii_entities':ENTITIES})['text'],'IBAN [IBAN]')
        self.assertEqual(guard('version 999.1.1.1',{'pii_entities':ENTITIES})['text'],'version 999.1.1.1')

    def test_block_actions(self):
        out=guard('my ssn is 123-45-6789',{'pii_entities':{'ssn':'block'}})
        self.assertFalse(out['allowed'])
        self.assertIn('Sensitive information: ssn',out['reasons'])

    def test_legacy_redaction_unchanged(self):
        self.assertEqual(guard('a@b.io 1234567890123',{})['text'],'[EMAIL] [ACCOUNT]')

    def test_word_and_regex_filters(self):
        policy={'word_filters':['Project Falcon'],'regex_filters':[{'name':'ticket','pattern':r'TCK-\d+','action':'mask'},{'name':'secret','pattern':r'sk-[A-Za-z0-9]{8,}','action':'block'}]}
        self.assertEqual(guard('see TCK-42',policy)['text'],'see [TICKET]')
        self.assertIn('Blocked word: Project Falcon',guard('about project falcon.',policy)['reasons'])
        self.assertTrue(guard('falconry is fine',policy)['allowed'])
        self.assertIn('Matched filter: secret',guard('key sk-abcdef123456',policy)['reasons'])

    def test_policy_validation(self):
        for bad in ({'regex_filters':[{'name':'x','pattern':'(a+)+'}]},{'regex_filters':[{'name':'x','pattern':'('}]},
                    {'pii_entities':{'dna':'mask'}},{'grounding_threshold':2},{'classifier_categories':['spam']}):
            with self.assertRaises(Fault):
                validate_policy(bad)

    def test_grounding(self):
        sources=['Keep isolates agent execution in microVMs with host-controlled credentials.']
        self.assertGreater(grounding_score('Keep isolates agent execution in microVMs.',sources),.9)
        out=guard('Keep isolates agent execution in microVMs. Bananas grow on purple trees near Jupiter.',{'grounding_threshold':.7},sources)
        self.assertFalse(out['allowed'])
        self.assertFalse(out['grounding']['grounded'])
        self.assertNotIn('grounding',guard('anything at all here today',{'grounding_threshold':.7}))


class GuardrailPlatform(StubModels):
    def set_policy(self,**fields):
        policy=self.app.list(self.p,'policies')[0]
        base={k:policy[k] for k in ('name','redact_pii','detect_injection','max_chars','daily_tokens','blocked_topics')}
        return self.app.create(self.p,'policies',{**base,**fields,'expected_revision':policy['revision']},policy['id'])

    def classifier(self,flag_word='attack'):
        def reply(messages):
            text=messages[-1]['content']
            if 'GARBAGE' in text:
                return 'not json'
            return json.dumps({'flags':[{'category':'violence','confidence':.9}] if flag_word in text else []})
        return self.openai_model(reply,'Safety')

    def test_classifier_blocks_and_fails_closed(self):
        safety=self.classifier()
        writer=self.openai_model(lambda m:'A calm, helpful answer.','Writer')
        with self.assertRaises(Fault):
            self.set_policy(classifier_model=safety)
        self.set_policy(classifier_model=safety,classifier_categories=['violence'])
        ok=self.json('/api/chat',{'model':writer,'messages':[{'role':'user','content':'hello'}]},expect=200)
        self.assertEqual(ok['content'],'A calm, helpful answer.')
        self.json('/api/chat',{'model':writer,'messages':[{'role':'user','content':'plan an attack'}]},expect=422)
        self.json('/api/chat',{'model':writer,'messages':[{'role':'user','content':'GARBAGE'}]},expect=503)
        check=self.json('/api/guardrails/check',{'text':'an attack'},expect=200)
        self.assertFalse(check['allowed'])
        self.assertEqual(check['classifier'][0]['category'],'violence')
        events=[json.loads(r['event'])['action'] for r in self.store.db.execute('SELECT event FROM audit WHERE tenant=?',('a',)).fetchall()]
        self.assertIn('guardrail.blocked',events)

    def test_demo_model_cannot_classify(self):
        demo=next(m['id'] for m in self.app.list(self.p,'models') if m['provider']=='demo')
        with self.assertRaises(Fault):
            self.set_policy(classifier_model=demo,classifier_categories=['hate'])

    def streaming_model(self,text,name):
        def chat(handler,body):
            frames=''.join('data: '+json.dumps({'choices':[{'delta':{'content':w+' '}}]})+'\n\n' for w in text.split())+'data: [DONE]\n\n'
            return 200,frames.encode(),{'Content-Type':'text/event-stream'}
        url,_=self.stub({('POST','/v1/chat/completions'):chat})
        return self.json('/api/models',{'name':name,'provider':'openai','base_url':url+'/v1','upstream_model':'m'},expect=201)['id']

    def test_grounded_stream_is_buffered_and_reported(self):
        model=self.streaming_model('Bananas grow on purple trees near Jupiter today.','Writer')
        self.set_policy(grounding_threshold=.6)
        events=self.app.open_stream(self.p,{'model':model,'messages':[{'role':'user','content':'q'}],'sources':['Keep isolates agents in microVMs.']})
        with self.assertRaises(Fault) as ctx:
            list(events)
        self.assertEqual(ctx.exception.status,422)
        good=self.streaming_model('Keep isolates agents in microVMs.','Good')
        out=list(self.app.open_stream(self.p,{'model':good,'messages':[{'role':'user','content':'q'}],'sources':['Keep isolates agents in microVMs.']}))
        deltas=[e for e in out if e['event']=='delta']
        self.assertEqual(len(deltas),1)
        self.assertTrue(out[-1]['grounding']['grounded'])

    def test_answer_reports_grounding(self):
        model=self.openai_model(lambda m:'NUVORA connects models, knowledge and agents on infrastructure you control.','Writer')
        self.set_policy(grounding_threshold=.5)
        kb=self.app.list(self.p,'knowledge')[0]['id']
        out=self.json('/api/answer',{'model':model,'knowledge_ids':[kb],'question':'What does NUVORA connect?'},expect=200)
        self.assertTrue(out['grounding']['grounded'])


if __name__=='__main__':
    unittest.main()
