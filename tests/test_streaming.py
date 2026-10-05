# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from harness import LiveServer
from nuvora.platform import Platform
from nuvora.providers import Providers

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sdk'/'python'))
from nuvora_client import NuvoraClient  # noqa: E402


def frames(raw):
    out=[]
    for block in raw.decode().strip().split('\n\n'):
        line=block.strip()
        assert line.startswith('data: '),line
        data=line[6:]
        out.append(data if data=='[DONE]' else json.loads(data))
    return out


class OpenAIStreamTests(LiveServer):
    def make_platform(self):
        return Platform(self.store,self.auth,Providers({'127.0.0.1','localhost'}))

    def openai_upstream(self,pieces):
        def chat(handler,body):
            self.upstream_body=body
            out=''.join('data: '+json.dumps({'choices':[{'delta':{'content':p}}]})+'\n\n' for p in pieces)
            out+='data: '+json.dumps({'choices':[],'usage':{'prompt_tokens':5,'completion_tokens':7}})+'\n\ndata: [DONE]\n\n'
            return 200,out.encode(),{'Content-Type':'text/event-stream'}
        url,_=self.stub({('POST','/v1/chat/completions'):chat})
        return self.json('/api/models',{'name':'Stub','provider':'openai','base_url':url+'/v1','upstream_model':'m'},expect=201)['id']

    def test_v1_streams_upstream_chunks(self):
        model=self.openai_upstream(['Hello ','there. ','Second ','sentence.'])
        code,raw,headers=self.request('/v1/chat/completions',{'model':model,'stream':True,'messages':[{'role':'user','content':'hi'}]})
        self.assertEqual(code,200)
        self.assertIn('text/event-stream',headers['Content-Type'])
        out=frames(raw)
        self.assertEqual(out[-1],'[DONE]')
        chunks=out[:-1]
        self.assertTrue(all(c['object']=='chat.completion.chunk' for c in chunks))
        self.assertEqual(chunks[0]['choices'][0]['delta']['role'],'assistant')
        text=''.join(c['choices'][0]['delta'].get('content','') for c in chunks)
        self.assertEqual(text,'Hello there. Second sentence.')
        self.assertGreater(len([c for c in chunks if c['choices'][0]['delta'].get('content')]),1)
        self.assertEqual(chunks[-1]['choices'][0]['finish_reason'],'stop')
        self.assertEqual(chunks[-1]['usage']['completion_tokens'],7)
        self.assertTrue(self.upstream_body['stream'])

    def test_v1_stream_redacts_like_buffered(self):
        model=self.openai_upstream(['Write to alex@example.com today. ','Thanks.'])
        _,raw,_=self.request('/v1/chat/completions',{'model':model,'stream':True,'messages':[{'role':'user','content':'hi'}]})
        text=''.join(c['choices'][0]['delta'].get('content','') for c in frames(raw)[:-1])
        self.assertNotIn('alex@example.com',text)
        self.assertIn('[EMAIL]',text)

    def test_v1_stream_errors_before_start_are_http_errors(self):
        code,raw,_=self.request('/v1/chat/completions',{'model':'missing','stream':True,'messages':[{'role':'user','content':'hi'}]})
        self.assertEqual(code,404)

    def test_ollama_stream(self):
        def chat(handler,body):
            lines=[{'message':{'content':'Local '}},{'message':{'content':'answer.'}},{'done':True,'prompt_eval_count':3,'eval_count':2}]
            return 200,('\n'.join(json.dumps(x) for x in lines)+'\n').encode(),{'Content-Type':'application/x-ndjson'}
        url,_=self.stub({('POST','/api/chat'):chat})
        model=self.json('/api/models',{'name':'Local','provider':'ollama','base_url':url,'upstream_model':'llama'},expect=201)['id']
        out=frames(self.request('/v1/chat/completions',{'model':model,'stream':True,'messages':[{'role':'user','content':'hi'}]})[1])
        self.assertEqual(''.join(c['choices'][0]['delta'].get('content','') for c in out[:-1]),'Local answer.')
        self.assertEqual(out[-2]['usage']['completion_tokens'],2)

    def test_sdk_chat_stream(self):
        client=NuvoraClient(self.url,self.token)
        text=''.join(client.chat_stream('Hello there. How are you?'))
        self.assertIn('OFFLINE DEMO',text)


class BedrockStreamTests(unittest.TestCase):
    def test_converse_stream_mapping(self):
        events=[{'messageStart':{'role':'assistant'}},{'contentBlockDelta':{'delta':{'text':'Hi '}}},{'contentBlockDelta':{'delta':{'text':'there.'}}},
                {'messageStop':{'stopReason':'end_turn'}},{'metadata':{'usage':{'inputTokens':9,'outputTokens':4}}}]
        client=mock.Mock()
        client.converse_stream.return_value={'stream':iter(events)}
        fake=types.SimpleNamespace(client=lambda *a,**k:client)
        with mock.patch.dict(sys.modules,{'boto3':fake}):
            out=list(Providers().stream({'provider':'bedrock','upstream_model':'anthropic.x','region':'eu-central-1'},[{'role':'system','content':'Be brief'},{'role':'user','content':'hi'}]))
        self.assertEqual([o['delta'] for o in out if 'delta' in o],['Hi ','there.'])
        self.assertEqual(out[-1]['usage'],{'prompt_tokens':9,'completion_tokens':4})
        kwargs=client.converse_stream.call_args.kwargs
        self.assertEqual(kwargs['system'],[{'text':'Be brief'}])

    def test_converse_stream_error_event(self):
        client=mock.Mock()
        client.converse_stream.return_value={'stream':iter([{'contentBlockDelta':{'delta':{'text':'a'}}},{'throttlingException':{'message':'slow down'}}])}
        with mock.patch.dict(sys.modules,{'boto3':types.SimpleNamespace(client=lambda *a,**k:client)}):
            from nuvora.security import Fault
            with self.assertRaises(Fault) as ctx:
                list(Providers().stream({'provider':'bedrock','upstream_model':'x'},[{'role':'user','content':'hi'}]))
        self.assertEqual(ctx.exception.status,502)


if __name__=='__main__':
    unittest.main()
