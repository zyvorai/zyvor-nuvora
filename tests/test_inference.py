# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Embeddings, tools, structured output, top_p and stop (N1). No network: demo provider, loopback stubs and a mocked boto3."""
import base64
import json
import struct
import sys
import types
import unittest
from unittest import mock

from harness import LiveServer
from nuvora.platform import Platform
from nuvora.providers import Providers, aws_messages, converse_to_openai, demo_embedding
from nuvora.security import Fault

TOOL={'type':'function','function':{'name':'get_weather','description':'Weather','parameters':{'type':'object','properties':{'city':{'type':'string'},'days':{'type':'integer'}},'required':['city','days']}}}
SCHEMA={'type':'object','properties':{'name':{'type':'string'},'age':{'type':'integer'},'tags':{'type':'array','items':{'type':'string'}}}}
MSG=[{'role':'user','content':'weather in Paris'}]


def frames(raw):
    out=[]
    for block in raw.decode().strip().split('\n\n'):
        data=block.strip()[6:]
        out.append(data if data=='[DONE]' else json.loads(data))
    return out


class InferenceTests(LiveServer):
    def make_platform(self):
        return Platform(self.store,self.auth,Providers({'127.0.0.1','localhost'}))

    def embedding_model(self,provider='demo',**extra):
        return self.json('/api/models',{'name':'Embed '+provider,'provider':provider,'upstream_model':'e','capability':'embedding','input_price':2,**extra},expect=201)

    def chat(self,body,expect=200,path='/v1/chat/completions'):
        return self.json(path,{'model':'auto','messages':MSG,**body},expect=expect)

    # embeddings
    def test_embeddings_openai_shape_usage_and_audit(self):
        model=self.embedding_model()
        out=self.json('/v1/embeddings',{'model':model['id'],'input':['alpha beta','gamma']},expect=200)
        self.assertEqual(out['object'],'list')
        self.assertEqual([d['index'] for d in out['data']],[0,1])
        self.assertEqual(len(out['data'][0]['embedding']),64)
        self.assertEqual(out['data'][0]['embedding'],demo_embedding('alpha beta'))
        self.assertEqual(out['nuvora']['evidence_class'],'synthetic')
        self.assertEqual(out['usage']['prompt_tokens'],out['usage']['total_tokens'])
        self.assertTrue(out['nuvora']['usage_estimated'])
        self.assertGreater(out['nuvora']['cost'],0)
        self.assertEqual(self.json('/v1/embeddings',{'model':model['id'],'input':'alpha beta'})['data'][0]['embedding'],out['data'][0]['embedding'])
        self.assertEqual(self.app.usage(self.p)['requests'],2)
        with self.store.lock:
            events=[json.loads(r['event']) for r in self.store.db.execute('SELECT event FROM audit WHERE tenant=?',('a',)).fetchall()]
        done=[e for e in events if e['action']=='embedding.completed']
        self.assertEqual(len(done),2)
        self.assertEqual(done[0]['detail']['inputs'],2)
        self.assertEqual(done[0]['detail']['evidence_class'],'synthetic')

    def test_embeddings_base64(self):
        model=self.embedding_model()
        out=self.json('/v1/embeddings',{'model':model['id'],'input':'x','encoding_format':'base64'},expect=200)
        values=struct.unpack('<64f',base64.b64decode(out['data'][0]['embedding']))
        self.assertAlmostEqual(values[0],demo_embedding('x')[0],places=5)

    def test_embeddings_validation_and_roles(self):
        model=self.embedding_model()
        for bad in ({'input':''},{'input':[]},{'input':[1,2]},{'input':['x']*129},{'input':'x','encoding_format':'int8'},{'input':'x'*20001},{'input':None}):
            self.json('/v1/embeddings',{'model':model['id'],**bad},expect=400)
        self.json('/v1/embeddings',{'model':model['id'],'input':'x','dimensions':8},expect=422)
        self.json('/v1/embeddings',{'input':'x'},expect=400)
        self.json('/v1/embeddings',{'model':'missing','input':'x'},expect=404)
        self.json('/v1/embeddings',{'model':model['id'],'input':'x'},token=self.viewer,expect=403)
        self.json('/v1/embeddings',{'model':model['id'],'input':'x'},token=self.dev,expect=200)
        chat_id=next(m['id'] for m in self.app.list(self.p,'models') if m.get('capability','chat')=='chat')
        self.json('/v1/embeddings',{'model':chat_id,'input':'x'},expect=409)

    def test_embeddings_guardrail_and_budget(self):
        model=self.embedding_model()
        out=self.json('/v1/embeddings',{'model':model['id'],'input':'mail alex@example.com now'},expect=200)
        self.assertNotEqual(out['data'][0]['embedding'],demo_embedding('mail alex@example.com now'))
        self.assertEqual(out['data'][0]['embedding'],demo_embedding('mail [EMAIL] now'))
        policy=self.app.list(self.p,'policies')[0]
        self.app.create(self.p,'policies',{**policy,'daily_tokens':10,'expected_revision':policy['revision']},policy['id'])
        self.json('/v1/embeddings',{'model':model['id'],'input':'word '*100},expect=429)

    def test_embeddings_openai_and_ollama_providers(self):
        seen=[]
        def openai(handler,body):
            seen.append(body)
            return 200,{'data':[{'index':1,'embedding':[0.0,1.0]},{'index':0,'embedding':[1.0,0.0]}]}
        def ollama(handler,body):
            seen.append(body)
            return 200,{'embeddings':[[0.5,0.5],[0.25,0.75]]}
        url,_=self.stub({('POST','/v1/embeddings'):openai,('POST','/api/embed'):ollama})
        a=self.embedding_model('openai',base_url=url+'/v1')
        b=self.embedding_model('ollama',base_url=url)
        out=self.json('/v1/embeddings',{'model':a['id'],'input':['a','b']},expect=200)
        self.assertEqual([d['embedding'] for d in out['data']],[[1.0,0.0],[0.0,1.0]])
        self.assertEqual(out['nuvora']['evidence_class'],'provider')
        self.assertEqual(self.json('/v1/embeddings',{'model':b['id'],'input':['a','b']})['data'][1]['embedding'],[0.25,0.75])

    # tools
    def test_demo_tool_call_envelope(self):
        out=self.chat({'tools':[TOOL],'tool_choice':{'type':'function','function':{'name':'get_weather'}}})
        choice=out['choices'][0]
        self.assertEqual(choice['finish_reason'],'tool_calls')
        self.assertIsNone(choice['message']['content'])
        call=choice['message']['tool_calls'][0]
        self.assertEqual(call['function']['name'],'get_weather')
        self.assertEqual(json.loads(call['function']['arguments']),{'city':'city','days':1})

    def test_tool_choice_none_and_native_endpoint(self):
        out=self.chat({'tools':[TOOL],'tool_choice':'none'})
        self.assertEqual(out['choices'][0]['finish_reason'],'stop')
        self.assertIn('OFFLINE DEMO',out['choices'][0]['message']['content'])
        native=self.chat({'tools':[TOOL]},path='/api/chat')
        self.assertEqual(native['tool_calls'][0]['function']['name'],'get_weather')

    def test_tool_result_turn_round_trip(self):
        history=MSG+[{'role':'assistant','content':None,'tool_calls':[{'id':'c1','type':'function','function':{'name':'get_weather','arguments':'{"city":"Paris"}'}}]},
                     {'role':'tool','tool_call_id':'c1','content':'sunny'}]
        out=self.json('/v1/chat/completions',{'model':'auto','messages':history,'tools':[TOOL]},expect=200)
        self.assertEqual(out['choices'][0]['finish_reason'],'stop')

    def test_tool_validation(self):
        bad=[{'tools':[]},{'tools':'x'},{'tools':[{'type':'function'}]},{'tools':[{'type':'function','function':{'name':'bad name'}}]},
             {'tools':[TOOL,TOOL]},{'tools':[{'type':'function','function':{'name':'f','strict':True}}]},{'tools':[{'type':'function','function':{'name':'f','parameters':[]}}]},
             {'tool_choice':'auto'},{'tools':[TOOL],'tool_choice':'sometimes'},{'tools':[TOOL],'tool_choice':{'type':'function','function':{'name':'other'}}}]
        for body in bad:
            self.chat(body,expect=400)
        self.json('/v1/chat/completions',{'model':'auto','messages':[{'role':'tool','content':'x'}]},expect=400)
        self.json('/v1/chat/completions',{'model':'auto','messages':[{'role':'user','content':'x','tool_calls':[]}]},expect=400)

    def test_tool_call_arguments_in_history_pass_input_guardrail(self):
        history=MSG+[{'role':'assistant','content':'','tool_calls':[{'id':'c1','type':'function','function':{'name':'f','arguments':'{"to":"alex@example.com"}'}}]}]
        seen=[]
        original=self.app.providers.chat
        self.app.providers.chat=lambda model,messages,*a,**k:seen.append(messages) or original(model,messages,*a,**k)
        self.json('/v1/chat/completions',{'model':'auto','messages':history},expect=200)
        self.assertEqual(seen[0][1]['tool_calls'][0]['function']['arguments'],'{"to":"[EMAIL]"}')

    def test_streamed_tool_calls_demo(self):
        code,raw,_=self.request('/v1/chat/completions',{'model':'auto','stream':True,'messages':MSG,'tools':[TOOL]})
        self.assertEqual(code,200)
        out=frames(raw)
        calls=[c['choices'][0]['delta']['tool_calls'] for c in out[:-1] if c['choices'][0]['delta'].get('tool_calls')]
        self.assertEqual(calls[0][0]['index'],0)
        self.assertEqual(calls[0][0]['function']['name'],'get_weather')
        self.assertEqual(out[-2]['choices'][0]['finish_reason'],'tool_calls')

    def test_native_stream_emits_tool_calls_event(self):
        code,raw,_=self.request('/api/chat/stream',{'model':'auto','messages':MSG,'tools':[TOOL]})
        names=[b.split('\n')[0] for b in raw.decode().strip().split('\n\n')]
        self.assertIn('event: tool_calls',names)
        self.assertEqual(names[-1],'event: done')

    def test_openai_upstream_tools_and_options(self):
        calls=[{'id':'call_1','type':'function','function':{'name':'get_weather','arguments':'{"city":"Paris"}'}}]
        def chat(handler,body):
            self.upstream=body
            return 200,{'choices':[{'message':{'content':None,'tool_calls':calls}}],'usage':{'prompt_tokens':5,'completion_tokens':3}}
        url,_=self.stub({('POST','/v1/chat/completions'):chat})
        model=self.json('/api/models',{'name':'S','provider':'openai','base_url':url+'/v1','upstream_model':'m'},expect=201)['id']
        out=self.json('/v1/chat/completions',{'model':model,'messages':MSG,'tools':[TOOL],'tool_choice':'required','top_p':.5,'stop':'END',
                                              'response_format':{'type':'json_schema','json_schema':{'name':'x','schema':SCHEMA}}},expect=200)
        self.assertEqual(out['choices'][0]['message']['tool_calls'],calls)
        self.assertEqual(out['choices'][0]['finish_reason'],'tool_calls')
        body=self.upstream
        self.assertEqual((body['tool_choice'],body['top_p'],body['stop'],body['tools'][0]['function']['name']),('required',.5,['END'],'get_weather'))
        self.assertEqual(body['response_format']['json_schema']['schema'],SCHEMA)

    def test_openai_upstream_streams_tool_call_fragments(self):
        def chat(handler,body):
            pieces=[{'choices':[{'delta':{'tool_calls':[{'index':0,'id':'c9','function':{'name':'get_weather','arguments':''}}]}}]},
                    {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':'{"city":'}}]}}]},
                    {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':'"Rome"}'}}]}}]},
                    {'choices':[],'usage':{'prompt_tokens':4,'completion_tokens':6}}]
            return 200,''.join('data: '+json.dumps(x)+'\n\n' for x in pieces).encode()+b'data: [DONE]\n\n',{'Content-Type':'text/event-stream'}
        url,_=self.stub({('POST','/v1/chat/completions'):chat})
        model=self.json('/api/models',{'name':'S','provider':'openai','base_url':url+'/v1','upstream_model':'m'},expect=201)['id']
        _,raw,_=self.request('/v1/chat/completions',{'model':model,'stream':True,'messages':MSG,'tools':[TOOL]})
        out=frames(raw)
        call=next(c['choices'][0]['delta']['tool_calls'][0] for c in out[:-1] if c['choices'][0]['delta'].get('tool_calls'))
        self.assertEqual((call['id'],call['function']['name'],json.loads(call['function']['arguments'])),('c9','get_weather',{'city':'Rome'}))

    def test_ollama_native_tools_format_and_options(self):
        def chat(handler,body):
            self.upstream=body
            return 200,{'message':{'content':'','tool_calls':[{'function':{'name':'get_weather','arguments':{'city':'Oslo'}}}]},'prompt_eval_count':3,'eval_count':2}
        url,_=self.stub({('POST','/api/chat'):chat})
        model=self.json('/api/models',{'name':'O','provider':'ollama','base_url':url,'upstream_model':'m'},expect=201)['id']
        history=MSG+[{'role':'assistant','content':'','tool_calls':[{'id':'c1','type':'function','function':{'name':'get_weather','arguments':'{"city":"X"}'}}]},{'role':'tool','tool_call_id':'c1','content':'rain'}]
        out=self.json('/v1/chat/completions',{'model':model,'messages':history,'tools':[TOOL],'top_p':.9,'stop':['a','b'],'response_format':{'type':'json_schema','json_schema':{'name':'x','schema':SCHEMA}}},expect=200)
        call=out['choices'][0]['message']['tool_calls'][0]
        self.assertEqual(json.loads(call['function']['arguments']),{'city':'Oslo'})
        self.assertTrue(call['id'])
        body=self.upstream
        self.assertEqual(body['format'],SCHEMA)
        self.assertEqual((body['options']['top_p'],body['options']['stop']),(.9,['a','b']))
        self.assertEqual(body['messages'][1]['tool_calls'][0]['function']['arguments'],{'city':'X'})
        self.assertEqual(body['messages'][2]['tool_name'],'get_weather')
        self.chat({'model':model,'response_format':{'type':'json_object'}})
        self.assertEqual(self.upstream['format'],'json')

    def test_unsupported_parameters_are_refused_not_ignored(self):
        url,_=self.stub({})
        ollama=self.json('/api/models',{'name':'O','provider':'ollama','base_url':url,'upstream_model':'m'},expect=201)['id']
        out=self.json('/v1/chat/completions',{'model':ollama,'messages':MSG,'tools':[TOOL],'tool_choice':'required'},expect=422)
        self.assertIn('tool_choice',out['error'])
        self.json('/v1/chat/completions',{'model':'router:missing','messages':MSG},expect=404)
        aws=self.json('/api/models',{'name':'A','provider':'aws','upstream_model':'x'},expect=201)['id']
        out=self.json('/v1/chat/completions',{'model':aws,'messages':MSG,'response_format':{'type':'json_object'}},expect=422)
        self.assertIn('response_format',out['error'])
        out=self.json('/api/chat/stream',{'model':aws,'messages':MSG,'response_format':{'type':'json_object'}},expect=422)

    def test_router_refuses_when_any_tier_cannot(self):
        url,_=self.stub({})
        ollama=self.json('/api/models',{'name':'O','provider':'ollama','base_url':url,'upstream_model':'m'},expect=201)['id']
        demo=next(m['id'] for m in self.app.list(self.p,'models') if m['provider']=='demo' and m.get('capability','chat')=='chat')
        router=self.json('/api/routers',{'name':'R','models':[demo,ollama]},expect=201)
        self.json('/v1/chat/completions',{'model':'router:'+router['id'],'messages':MSG,'tools':[TOOL],'tool_choice':'required'},expect=422)

    # structured output, top_p, stop
    def test_demo_json_object_and_schema(self):
        out=self.chat({'response_format':{'type':'json_object'}})
        self.assertEqual(list(json.loads(out['choices'][0]['message']['content'])),['response'])
        out=self.chat({'response_format':{'type':'json_schema','json_schema':{'name':'person','schema':SCHEMA}}})
        self.assertEqual(json.loads(out['choices'][0]['message']['content']),{'name':'name','age':1,'tags':['tags']})
        self.assertIn('OFFLINE DEMO',self.chat({'response_format':{'type':'text'}})['choices'][0]['message']['content'])

    def test_response_format_validation(self):
        for bad in ('json',{'type':'xml'},{'type':'json_schema'},{'type':'json_schema','json_schema':{'name':'bad name','schema':{}}},{'type':'json_schema','json_schema':{'name':'x','schema':[]}}):
            self.chat({'response_format':bad},expect=400)

    def test_stop_and_top_p(self):
        out=self.chat({'stop':'DEMO','top_p':.3})
        self.assertEqual(out['choices'][0]['message']['content'],'[OFFLINE ')
        for bad in ({'top_p':0},{'top_p':1.5},{'top_p':'x'},{'top_p':True},{'stop':[]},{'stop':['']},{'stop':['a']*5},{'stop':[1]}):
            self.chat(bad,expect=400)

    def test_top_p_and_stop_change_the_cache_key(self):
        a=self.app._begin(self.p,{'model':'auto','messages':MSG,'top_p':.5})
        b=self.app._begin(self.p,{'model':'auto','messages':MSG,'top_p':.6})
        try:
            self.assertNotEqual(a['fingerprint'],b['fingerprint'])
        finally:
            self.app._release(a);self.app._release(b)

    def test_viewer_cannot_use_new_options(self):
        self.json('/v1/chat/completions',{'model':'auto','messages':MSG,'tools':[TOOL]},token=self.viewer,expect=403)


def fake_boto(client):
    return mock.patch.dict(sys.modules,{'boto3':types.SimpleNamespace(client=lambda *a,**k:client)})


class AwsConverseToolTests(unittest.TestCase):
    model={'provider':'aws','upstream_model':'anthropic.x','region':'eu-west-1'}

    def test_messages_to_converse(self):
        messages=[{'role':'system','content':'S'},{'role':'user','content':'q'},
                  {'role':'assistant','content':'','tool_calls':[{'id':'t1','type':'function','function':{'name':'f','arguments':'{"a":1}'}},{'id':'t2','type':'function','function':{'name':'g','arguments':'bad'}}]},
                  {'role':'tool','tool_call_id':'t1','content':'one'},{'role':'tool','tool_call_id':'t2','content':'two'},{'role':'user','content':'go on'}]
        system,history=aws_messages(messages)
        self.assertEqual(system,[{'text':'S'}])
        self.assertEqual(history[1]['content'],[{'toolUse':{'toolUseId':'t1','name':'f','input':{'a':1}}},{'toolUse':{'toolUseId':'t2','name':'g','input':{}}}])
        self.assertEqual([b['toolResult']['toolUseId'] for b in history[2]['content']],['t1','t2'])
        self.assertEqual(history[2]['role'],'user')
        self.assertEqual(history[3],{'role':'user','content':[{'text':'go on'}]})

    def test_converse_to_openai(self):
        text,calls=converse_to_openai({'content':[{'text':'Checking. '},{'toolUse':{'toolUseId':'u1','name':'f','input':{'x':[1]}}}]})
        self.assertEqual(text,'Checking. ')
        self.assertEqual(calls,[{'id':'u1','type':'function','function':{'name':'f','arguments':'{"x": [1]}'}}])

    def test_chat_sends_tool_config_and_inference_options(self):
        client=mock.Mock()
        client.converse.return_value={'output':{'message':{'role':'assistant','content':[{'toolUse':{'toolUseId':'u1','name':'get_weather','input':{'city':'Paris'}}}]}},'usage':{'inputTokens':7,'outputTokens':5},'stopReason':'tool_use'}
        with fake_boto(client):
            out=Providers().chat(self.model,MSG,[TOOL],200,.1,{'tool_choice':{'type':'function','function':{'name':'get_weather'}},'top_p':.8,'stop':['X']})
        kwargs=client.converse.call_args.kwargs
        self.assertEqual(kwargs['toolConfig']['tools'][0]['toolSpec']['name'],'get_weather')
        self.assertEqual(kwargs['toolConfig']['tools'][0]['toolSpec']['inputSchema']['json'],TOOL['function']['parameters'])
        self.assertEqual(kwargs['toolConfig']['toolChoice'],{'tool':{'name':'get_weather'}})
        self.assertEqual(kwargs['inferenceConfig'],{'maxTokens':200,'temperature':.1,'topP':.8,'stopSequences':['X']})
        self.assertEqual(out['tool_calls'][0]['function']['arguments'],'{"city": "Paris"}')
        self.assertEqual(out['usage'],{'prompt_tokens':7,'completion_tokens':5})
        client.converse.return_value['output']['message']['content']=[{'text':'hi'}]
        with fake_boto(client):
            Providers().chat(self.model,MSG,[TOOL],200,.1,{'tool_choice':'required'})
        self.assertEqual(client.converse.call_args.kwargs['toolConfig']['toolChoice'],{'any':{}})

    def test_no_tool_config_without_tools(self):
        client=mock.Mock()
        client.converse.return_value={'output':{'message':{'content':[{'text':'hi'}]}},'usage':{}}
        with fake_boto(client):
            Providers().chat(self.model,MSG)
        self.assertNotIn('toolConfig',client.converse.call_args.kwargs)

    def test_stream_assembles_tool_use(self):
        events=[{'contentBlockDelta':{'contentBlockIndex':0,'delta':{'text':'ok '}}},
                {'contentBlockStart':{'contentBlockIndex':1,'start':{'toolUse':{'toolUseId':'u2','name':'get_weather'}}}},
                {'contentBlockDelta':{'contentBlockIndex':1,'delta':{'toolUse':{'input':'{"city":'}}}},
                {'contentBlockDelta':{'contentBlockIndex':1,'delta':{'toolUse':{'input':'"Rome"}'}}}},
                {'metadata':{'usage':{'inputTokens':2,'outputTokens':3}}}]
        client=mock.Mock()
        client.converse_stream.return_value={'stream':iter(events)}
        with fake_boto(client):
            out=list(Providers().stream(self.model,MSG,100,.2,[TOOL],{}))
        calls=next(o['tool_calls'] for o in out if 'tool_calls' in o)
        self.assertEqual(calls,[{'id':'u2','type':'function','function':{'name':'get_weather','arguments':'{"city":"Rome"}'}}])
        self.assertEqual(out[-1]['usage'],{'prompt_tokens':2,'completion_tokens':3})
        self.assertIn('toolConfig',client.converse_stream.call_args.kwargs)

    def test_aws_refuses_response_format_and_none_choice_drops_tools(self):
        with self.assertRaises(Fault) as cm:
            Providers().chat(self.model,MSG,None,10,.1,{'response_format':{'type':'json_object'}})
        self.assertEqual(cm.exception.status,422)
        self.assertIn('response_format',str(cm.exception))
        client=mock.Mock()
        client.converse.return_value={'output':{'message':{'content':[{'text':'hi'}]}},'usage':{}}
        with fake_boto(client):
            Providers().chat(self.model,MSG,[TOOL],10,.1,{'tool_choice':'none'})
        self.assertNotIn('toolConfig',client.converse.call_args.kwargs)


if __name__=='__main__':
    unittest.main()
