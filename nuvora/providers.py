# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Operator-configured providers; no unrestricted URL tools."""
import json
import os
import time
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


def stream_lines(url, body, headers, allowlist):
    """POST and yield response lines as they arrive (SSE or NDJSON), capped at 8 MiB."""
    validate_url(url,allowlist)
    request=urllib.request.Request(url,json.dumps(body).encode(),{'Content-Type':'application/json',**headers},method='POST')
    total=0
    try:
        with urllib.request.build_opener(NoRedirect).open(request,timeout=45) as response:
            for raw in response:
                total+=len(raw)
                if total>8*1024*1024:
                    raise Fault('Provider response too large',502)
                line=raw.decode('utf-8','replace').strip()
                if line:
                    yield line
    except Fault:
        raise
    except (urllib.error.URLError,ValueError,TimeoutError) as exc:
        raise Fault('Provider request failed; check operator configuration',502) from exc


class Providers:
    def __init__(self, allowed_hosts=None):
        self.allowed_hosts=set(allowed_hosts if allowed_hosts is not None else os.getenv('NUVORA_PROVIDER_HOSTS','localhost,127.0.0.1').split(','))

    def validate(self,model):
        if model.get('provider')=='bedrock':
            model['provider']='aws'
        if model['provider'] not in ('demo','openai','ollama','aws'):
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
        if kind=='aws':
            if tools:
                raise Fault('AWS tool calling is not supported in this release; use an OpenAI-compatible agent model',422)
            client=self._aws_client(model)
            system=[{'text':m['content']} for m in messages if m['role']=='system']
            history=[{'role':m['role'],'content':[{'text':m['content']}]} for m in messages if m['role'] in ('user','assistant')]
            try:
                raw=client.converse(modelId=model['upstream_model'],messages=history,system=system,inferenceConfig={'maxTokens':max_tokens,'temperature':temperature})
            except Exception as exc:
                raise Fault('AWS model invocation failed',502) from exc
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

    def _auth(self,model):
        headers={}
        if model.get('key_env'):
            key=os.getenv(model['key_env'])
            if not key:
                raise Fault('Provider credential is not configured',503)
            headers['Authorization']='Bearer '+key
        return headers

    def stream(self,model,messages,max_tokens=1024,temperature=.2):
        """Yield {'delta': text} pieces, then {'usage': {...}, 'evidence_class': ...}."""
        self.validate(model)
        kind=model['provider']
        if kind=='aws':
            yield from self._aws_stream(model,messages,max_tokens,temperature)
            return
        if kind=='demo':
            result=self.chat(model,messages,None,max_tokens,temperature)
            words=result['content'].split(' ')
            pause=min(.03,1.2/max(1,len(words))) if kind=='demo' else 0
            for i,word in enumerate(words):
                yield {'delta':(' ' if i else '')+word}
                if pause:
                    time.sleep(pause)
            yield {'usage':result['usage'],'evidence_class':result['evidence_class']}
            return
        url=model['base_url'].rstrip('/')
        headers=self._auth(model)
        usage={}
        if kind=='ollama':
            body={'model':model['upstream_model'],'messages':messages,'stream':True,'options':{'num_predict':max_tokens,'temperature':temperature}}
            for line in stream_lines(url+'/api/chat',body,headers,self.allowed_hosts):
                try:
                    chunk=json.loads(line)
                except ValueError:
                    continue
                text=chunk.get('message',{}).get('content','')
                if text:
                    yield {'delta':text}
                if chunk.get('done'):
                    usage={'prompt_tokens':chunk.get('prompt_eval_count',0),'completion_tokens':chunk.get('eval_count',0)}
            yield {'usage':usage,'evidence_class':'provider'}
            return
        body={'model':model['upstream_model'],'messages':messages,'max_tokens':max_tokens,'temperature':temperature,'stream':True,'stream_options':{'include_usage':True}}
        for line in stream_lines(url+'/chat/completions',body,headers,self.allowed_hosts):
            if not line.startswith('data:'):
                continue
            data=line[5:].strip()
            if data=='[DONE]':
                break
            try:
                chunk=json.loads(data)
            except ValueError:
                continue
            if chunk.get('usage'):
                usage=chunk['usage']
            for choice in chunk.get('choices') or []:
                text=(choice.get('delta') or {}).get('content')
                if text:
                    yield {'delta':text}
        yield {'usage':usage,'evidence_class':'provider'}

    def _aws_client(self,model):
        try:
            import boto3
        except ImportError as exc:
            raise Fault('Install nuvora[aws] for the AWS provider',503) from exc
        return boto3.client('bedrock-runtime',region_name=model.get('region','us-east-1'))

    def _aws_stream(self,model,messages,max_tokens,temperature):
        client=self._aws_client(model)
        system=[{'text':m['content']} for m in messages if m['role']=='system']
        history=[{'role':m['role'],'content':[{'text':m['content']}]} for m in messages if m['role'] in ('user','assistant')]
        try:
            raw=client.converse_stream(modelId=model['upstream_model'],messages=history,system=system,inferenceConfig={'maxTokens':max_tokens,'temperature':temperature})
        except Exception as exc:
            raise Fault('AWS model invocation failed',502) from exc
        usage={}
        try:
            for event in raw['stream']:
                text=event.get('contentBlockDelta',{}).get('delta',{}).get('text')
                if text:
                    yield {'delta':text}
                if 'metadata' in event:
                    u=event['metadata'].get('usage',{})
                    usage={'prompt_tokens':u.get('inputTokens',0),'completion_tokens':u.get('outputTokens',0)}
                for key in ('internalServerException','modelStreamErrorException','throttlingException','validationException','serviceUnavailableException'):
                    if key in event:
                        raise Fault('AWS model stream failed',502)
        except Fault:
            raise
        except Exception as exc:
            raise Fault('AWS model stream failed',502) from exc
        yield {'usage':usage,'evidence_class':'provider'}

    def embed(self,model,texts):
        if model['provider'] not in ('openai','ollama'):
            raise Fault('Embedding models require an OpenAI-compatible or Ollama provider')
        self.validate(model)
        if model['provider']=='ollama':
            raw=post_json(model['base_url'].rstrip('/')+'/api/embed',{'model':model['upstream_model'],'input':texts},self._auth(model),self.allowed_hosts)
            vectors=raw.get('embeddings') or []
            if len(vectors)!=len(texts):
                raise Fault('Embedding provider returned the wrong number of vectors',502)
            return vectors
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
