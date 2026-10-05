"""Operator-configured providers; no unrestricted URL tools."""
import json
import os
import urllib.error
import urllib.request
from .security import Fault, validate_url

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Fault('Provider redirects are disabled',502)


def post_json(url, body, headers, allowlist):
    validate_url(url,allowlist)
    request=urllib.request.Request(url,json.dumps(body).encode(),{'Content-Type':'application/json',**headers},method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(request,timeout=45) as response:
            raw=response.read(8*1024*1024+1)
            if len(raw)>8*1024*1024:
                raise Fault('Provider response too large',502)
            return json.loads(raw)
    except Fault:
        raise
    except (urllib.error.URLError,ValueError,TimeoutError) as exc:
        # Provider response bodies and auth headers must never enter API errors.
        raise Fault('Provider request failed; check operator configuration',502) from exc


class Providers:
    def __init__(self, allowed_hosts=None):
        self.allowed_hosts=set(allowed_hosts if allowed_hosts is not None else os.getenv('NUVORA_PROVIDER_HOSTS','localhost,127.0.0.1').split(','))

    def validate(self,model):
        if model['provider'] not in ('demo','openai','ollama','bedrock'):
            raise Fault('Unknown provider')
        if model['provider'] in ('openai','ollama'):
            validate_url(model.get('base_url',''),self.allowed_hosts)
        if model.get('key_env') and not model['key_env'].startswith('NUVORA_SECRET_'):
            raise Fault('Secrets must use a NUVORA_SECRET_ environment reference')

    def chat(self,model,messages,tools=None,max_tokens=1024,temperature=.2):
        self.validate(model)
        kind=model['provider']
        if kind=='demo':
            last=messages[-1]
            text=last.get('content','')
            if tools and not any(m.get('role')=='tool' for m in messages):
                name=tools[0]['function']['name']
                args={'query':text} if name=='knowledge_search' else {}
                return {'content':'','tool_calls':[{'id':'demo-call','type':'function','function':{'name':name,'arguments':json.dumps(args)}}],'usage':{'prompt_tokens':len(text)//4+1,'completion_tokens':10},'evidence_class':'synthetic'}
            return {'content':'[OFFLINE DEMO — no model inference] '+text[:1800],'tool_calls':[],'usage':{'prompt_tokens':sum(len(str(m)) for m in messages)//4+1,'completion_tokens':len(text)//4+12},'evidence_class':'synthetic'}
        if kind=='bedrock':
            try:
                import boto3
            except ImportError as exc:
                raise Fault('Install nuvora[aws] for the Bedrock provider',503) from exc
            if tools:
                raise Fault('Bedrock tool calling is not supported in this release; use an OpenAI-compatible agent model',422)
            client=boto3.client('bedrock-runtime',region_name=model.get('region','us-east-1'))
            system=[{'text':m['content']} for m in messages if m['role']=='system']
            history=[{'role':m['role'],'content':[{'text':m['content']}]} for m in messages if m['role'] in ('user','assistant')]
            try:
                raw=client.converse(modelId=model['upstream_model'],messages=history,system=system,inferenceConfig={'maxTokens':max_tokens,'temperature':temperature})
            except Exception as exc:
                raise Fault('Bedrock invocation failed',502) from exc
            usage=raw.get('usage',{})
            return {'content':''.join(c.get('text','') for c in raw['output']['message']['content']),'tool_calls':[],'usage':{'prompt_tokens':usage.get('inputTokens',0),'completion_tokens':usage.get('outputTokens',0)},'evidence_class':'provider'}
        url=model['base_url'].rstrip('/')
        headers={}
        if model.get('key_env'):
            key=os.getenv(model['key_env'])
            if not key:
                raise Fault('Provider credential is not configured',503)
            headers['Authorization']='Bearer '+key
        if kind=='ollama':
            if tools:
                raise Fault('Use Ollama’s OpenAI-compatible /v1 endpoint for agent tool calling',422)
            raw=post_json(url+'/api/chat',{'model':model['upstream_model'],'messages':messages,'stream':False,'options':{'num_predict':max_tokens,'temperature':temperature}},headers,self.allowed_hosts)
            return {'content':raw['message']['content'],'tool_calls':[],'usage':{'prompt_tokens':raw.get('prompt_eval_count',0),'completion_tokens':raw.get('eval_count',0)},'evidence_class':'provider'}
        body={'model':model['upstream_model'],'messages':messages,'max_tokens':max_tokens,'temperature':temperature,'stream':False}
        if tools:
            body['tools']=tools
        raw=post_json(url+'/chat/completions',body,headers,self.allowed_hosts)
        msg=raw['choices'][0]['message']
        return {'content':msg.get('content') or '', 'tool_calls':msg.get('tool_calls') or [],'usage':raw.get('usage',{}),'evidence_class':'provider'}

    def embed(self,model,texts):
        if model['provider']!='openai':
            raise Fault('Embedding models require an OpenAI-compatible provider')
        self.validate(model)
        headers={}
        if model.get('key_env'):
            key=os.getenv(model['key_env'])
            if not key:
                raise Fault('Embedding credential is not configured',503)
            headers['Authorization']='Bearer '+key
        raw=post_json(model['base_url'].rstrip('/')+'/embeddings',{'model':model['upstream_model'],'input':texts},headers,self.allowed_hosts)
        rows=sorted(raw['data'],key=lambda x:x['index'])
        if len(rows)!=len(texts):
            raise Fault('Embedding provider returned the wrong number of vectors',502)
        return [row['embedding'] for row in rows]
