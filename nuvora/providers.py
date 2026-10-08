# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Operator-configured providers; no unrestricted URL tools."""
import base64
import hashlib
import json
import math
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from .security import Fault, validate_url

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Fault('Provider redirects are disabled',502)


def provider_timeout():
    """Seconds to wait for a provider response: NUVORA_PROVIDER_TIMEOUT, 5–900, default 45."""
    try:
        return min(900,max(5,int(os.getenv('NUVORA_PROVIDER_TIMEOUT','45'))))
    except ValueError:
        return 45


def post_json(url, body, headers, allowlist, timeout=None, limit=8*1024*1024):
    validate_url(url,allowlist)
    request=urllib.request.Request(url,json.dumps(body).encode(),{'Content-Type':'application/json',**headers},method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(request,timeout=timeout or provider_timeout()) as response:
            raw=response.read(limit+1)
            if len(raw)>limit:
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
        with urllib.request.build_opener(NoRedirect).open(request,timeout=provider_timeout()) as response:
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


DATA_IMAGE=re.compile(r'data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\s]+)$')


def text_of(content):
    """The text of a message content (a string, or OpenAI-style content parts)."""
    if isinstance(content,str):
        return content
    return '\n'.join(part.get('text','') for part in content or [] if isinstance(part,dict) and part.get('type')=='text')


def images_of(content):
    """[(mime, base64)] for the data-URL image parts of a message content."""
    if isinstance(content,str):
        return []
    out=[]
    for part in content or []:
        if isinstance(part,dict) and part.get('type')=='image_url':
            match=DATA_IMAGE.match((part.get('image_url') or {}).get('url',''))
            if match:
                out.append((match[1],match[2]))
    return out


def parse_arguments(raw):
    """The JSON object in a tool call's arguments string; {} when it is not one."""
    try:
        value=json.loads(raw) if isinstance(raw,str) and raw.strip() else raw
    except ValueError:
        return {}
    return value if isinstance(value,dict) else {}


def tool_names(messages):
    """{tool_call_id: function name} for the assistant tool calls in a conversation."""
    return {c.get('id'):(c.get('function') or {}).get('name','') for m in messages for c in m.get('tool_calls') or [] if isinstance(c,dict)}


def ollama_messages(messages):
    out=[]
    names=tool_names(messages)
    for m in messages:
        images=images_of(m.get('content'))
        item={'role':m['role'],'content':text_of(m.get('content')),**({'images':[b for _,b in images]} if images else {})}
        if m.get('tool_calls'):
            item['tool_calls']=[{'function':{'name':(c.get('function') or {}).get('name',''),'arguments':parse_arguments((c.get('function') or {}).get('arguments'))}} for c in m['tool_calls']]
        if m['role']=='tool' and names.get(m.get('tool_call_id')):
            item['tool_name']=names[m['tool_call_id']]
        out.append(item)
    return out


def aws_messages(messages):
    system=[{'text':text_of(m['content'])} for m in messages if m['role']=='system']
    history=[]
    for m in messages:
        if m['role']=='tool':
            block={'toolResult':{'toolUseId':str(m.get('tool_call_id','')),'content':[{'text':text_of(m['content']) or ' '}]}}
            if history and history[-1]['role']=='user' and all('toolResult' in b for b in history[-1]['content']):
                history[-1]['content'].append(block)
            else:
                history.append({'role':'user','content':[block]})
            continue
        if m['role'] not in ('user','assistant'):
            continue
        calls=m.get('tool_calls') or []
        text=text_of(m['content'])
        blocks=([{'text':text}] if text or not calls else [])+[{'image':{'format':mime.split('/')[1],'source':{'bytes':base64.b64decode(b)}}} for mime,b in images_of(m['content'])]
        blocks+=[{'toolUse':{'toolUseId':c.get('id',''),'name':(c.get('function') or {}).get('name',''),'input':parse_arguments((c.get('function') or {}).get('arguments'))}} for c in calls]
        history.append({'role':m['role'],'content':blocks})
    return system,history


def aws_tool_config(tools,choice):
    """Converse toolConfig for OpenAI-style tools and tool_choice."""
    config={'tools':[{'toolSpec':{'name':t['function']['name'],**({'description':t['function']['description']} if t['function'].get('description') else {}),
                                  'inputSchema':{'json':t['function'].get('parameters') or {'type':'object','properties':{}}}}} for t in tools]}
    if choice=='required':
        config['toolChoice']={'any':{}}
    elif isinstance(choice,dict):
        config['toolChoice']={'tool':{'name':choice['function']['name']}}
    return config


def converse_to_openai(message):
    """(text, tool_calls) from a Converse output message: toolUse blocks become OpenAI tool calls."""
    text=''.join(b.get('text','') for b in message.get('content') or [])
    calls=[{'id':b['toolUse']['toolUseId'],'type':'function','function':{'name':b['toolUse']['name'],'arguments':json.dumps(b['toolUse'].get('input') or {})}}
           for b in message.get('content') or [] if 'toolUse' in b]
    return text,calls


SUPPORTED={'demo':{'tools','tool_choice','top_p','stop','response_format'},
           'openai':{'tools','tool_choice','top_p','stop','response_format'},
           'ollama':{'tools','top_p','stop','response_format'},
           'aws':{'tools','tool_choice','top_p','stop'}}


def check_support(model,tools,opts):
    """Refuse (422, naming the parameter) what the model's provider cannot do; never ignore it."""
    kind=model.get('provider')
    allowed=SUPPORTED.get(kind,set())
    opts=opts or {}
    wanted=(['tools'] if tools else [])+[k for k in ('tool_choice','top_p','stop','response_format') if opts.get(k) is not None]
    for key in wanted:
        if key=='tool_choice' and opts[key] in ('auto','none'):
            continue
        if key not in allowed:
            raise Fault(f"Model {model.get('name',model.get('id',''))} ({kind} provider) does not support {key}",422)


def demo_value(schema,hint='demo'):
    """A deterministic value that satisfies a (simple) JSON schema, for the offline demo provider."""
    if not isinstance(schema,dict):
        return hint
    if schema.get('enum'):
        return schema['enum'][0]
    kind=schema.get('type')
    if isinstance(kind,list):
        kind=next((k for k in kind if k!='null'),'string')
    if kind=='object' or (kind is None and 'properties' in schema):
        return {k:demo_value(v,k) for k,v in (schema.get('properties') or {}).items()}
    if kind=='array':
        return [demo_value(schema.get('items') or {},hint)]
    if kind=='integer':
        return 1
    if kind=='number':
        return 1.5
    if kind=='boolean':
        return True
    if kind=='null':
        return None
    return hint


def demo_embedding(text,dim=64):
    """A deterministic unit vector from hashed words; similar texts share dimensions. Not semantic."""
    out=[0.0]*dim
    for word in re.findall(r'\w+',text.lower()) or [text]:
        digest=hashlib.sha256(word.encode()).digest()
        out[int.from_bytes(digest[:2],'big')%dim]+=1 if digest[2]%2 else -1
    norm=math.sqrt(sum(v*v for v in out)) or 1
    return [round(v/norm,8) for v in out]


def stop_at(text,stop):
    cut=min([i for i in (text.find(s) for s in stop or []) if i>=0],default=len(text))
    return text[:cut]


class ToolCallAssembler:
    """Joins streamed tool-call fragments (by index) into complete OpenAI tool calls."""
    def __init__(self):
        self.calls={}

    def add(self,index,call_id=None,name=None,arguments=None):
        call=self.calls.setdefault(index,{'id':'','name':'','arguments':''})
        call['id']=call_id or call['id']
        call['name']=name or call['name']
        call['arguments']+=arguments or ''

    def result(self):
        return [{'id':c['id'] or 'call_'+secrets.token_hex(8),'type':'function','function':{'name':c['name'],'arguments':c['arguments'] or '{}'}} for _,c in sorted(self.calls.items())]


def multipart(fields,files):
    """(body, content_type) for multipart/form-data; files are (field, filename, mime, bytes)."""
    boundary='nuvora'+secrets.token_hex(12)
    parts=[]
    for key,value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    for key,filename,mime,data in files:
        safe=re.sub(r'[^\w.-]','_',filename)[:120] or 'upload'
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{safe}"\r\nContent-Type: {mime}\r\n\r\n'.encode()+data+b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    return b''.join(parts),'multipart/form-data; boundary='+boundary


def demo_png(prompt,index=0,width=256,height=256):
    """A deterministic two-tone PNG so the demo provider can exercise the image path offline."""
    import hashlib,struct,zlib
    seed=hashlib.sha256(f'{index}:{prompt}'.encode()).digest()
    top,bottom=seed[:3],seed[3:6]
    rows=b''.join(b'\x00'+(top if y<height//2 else bottom)*width for y in range(height))
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows,9))+chunk(b'IEND',b'')


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

    def chat(self,model,messages,tools=None,max_tokens=1024,temperature=.2,opts=None):
        """opts: top_p, stop (list), tool_choice, response_format; anything the provider cannot honour is a 422."""
        self.validate(model)
        opts=opts or {}
        check_support(model,tools,opts)
        kind=model['provider']
        choice=opts.get('tool_choice')
        if choice=='none':
            tools=None
        if kind=='demo':
            last=messages[-1]
            text=text_of(last.get('content',''))+(' [image attached]' if images_of(last.get('content')) else '')
            if tools and not any(m.get('role')=='tool' for m in messages):
                pick=next((t for t in tools if isinstance(choice,dict) and t['function']['name']==choice['function']['name']),tools[0])
                name=pick['function']['name']
                params=pick['function'].get('parameters') or {}
                args={'query':text} if name=='knowledge_search' else {k:text if k=='query' else demo_value((params.get('properties') or {}).get(k),k) for k in params.get('required') or []}
                return {'content':'','tool_calls':[{'id':'demo-call','type':'function','function':{'name':name,'arguments':json.dumps(args)}}],'usage':{'prompt_tokens':len(text)//4+1,'completion_tokens':10},'evidence_class':'synthetic'}
            fmt=opts.get('response_format')
            if fmt and fmt['type']=='json_object':
                content=json.dumps({'response':text[:200]})
            elif fmt:
                content=json.dumps(demo_value(fmt['json_schema'].get('schema')))
            else:
                content='[OFFLINE DEMO — no model inference] '+text[:1800]
            if opts.get('stop'):
                content=stop_at(content,opts['stop'])
            return {'content':content,'tool_calls':[],'usage':{'prompt_tokens':sum(len(str(m)) for m in messages)//4+1,'completion_tokens':len(text)//4+12},'evidence_class':'synthetic'}
        if kind=='aws':
            client=self._aws_client(model)
            try:
                raw=client.converse(**self._aws_args(model,messages,tools,max_tokens,temperature,opts))
            except Exception as exc:
                raise Fault('AWS model invocation failed',502) from exc
            usage=raw.get('usage',{})
            text,calls=converse_to_openai(raw['output']['message'])
            return {'content':text,'tool_calls':calls,'usage':{'prompt_tokens':usage.get('inputTokens',0),'completion_tokens':usage.get('outputTokens',0)},'evidence_class':'provider'}
        url=model['base_url'].rstrip('/')
        headers={}
        if model.get('key_env'):
            key=os.getenv(model['key_env'])
            if not key:
                raise Fault('Provider credential is not configured',503)
            headers['Authorization']='Bearer '+key
        if kind=='ollama':
            raw=post_json(url+'/api/chat',self._ollama_body(model,messages,tools,max_tokens,temperature,opts,False),headers,self.allowed_hosts)
            message=raw['message']
            calls=[{'id':'call_'+secrets.token_hex(8),'type':'function','function':{'name':c['function']['name'],'arguments':json.dumps(c['function'].get('arguments') or {})}} for c in message.get('tool_calls') or []]
            return {'content':message.get('content') or '','tool_calls':calls,'usage':{'prompt_tokens':raw.get('prompt_eval_count',0),'completion_tokens':raw.get('eval_count',0)},'evidence_class':'provider'}
        raw=post_json(url+'/chat/completions',self._openai_body(model,messages,tools,max_tokens,temperature,opts,False),headers,self.allowed_hosts)
        msg=raw['choices'][0]['message']
        return {'content':msg.get('content') or '', 'tool_calls':msg.get('tool_calls') or [],'usage':raw.get('usage',{}),'evidence_class':'provider'}

    @staticmethod
    def _openai_body(model,messages,tools,max_tokens,temperature,opts,stream):
        body={'model':model['upstream_model'],'messages':messages,'max_tokens':max_tokens,'temperature':temperature,'stream':stream}
        if stream:
            body['stream_options']={'include_usage':True}
        if tools:
            body['tools']=tools
        for key in ('tool_choice','top_p','stop','response_format'):
            if opts.get(key) is not None and (key!='tool_choice' or tools):
                body[key]=opts[key]
        return body

    @staticmethod
    def _ollama_body(model,messages,tools,max_tokens,temperature,opts,stream):
        options={'num_predict':max_tokens,'temperature':temperature,**({'top_p':opts['top_p']} if opts.get('top_p') is not None else {}),**({'stop':opts['stop']} if opts.get('stop') else {})}
        body={'model':model['upstream_model'],'messages':ollama_messages(messages),'stream':stream,'options':options}
        if tools:
            body['tools']=tools
        fmt=opts.get('response_format')
        if fmt:
            body['format']='json' if fmt['type']=='json_object' else fmt['json_schema']['schema']
        return body

    @staticmethod
    def _aws_args(model,messages,tools,max_tokens,temperature,opts):
        system,history=aws_messages(messages)
        config={'maxTokens':max_tokens,'temperature':temperature,**({'topP':opts['top_p']} if opts.get('top_p') is not None else {}),**({'stopSequences':opts['stop']} if opts.get('stop') else {})}
        args={'modelId':model['upstream_model'],'messages':history,'system':system,'inferenceConfig':config}
        if tools:
            args['toolConfig']=aws_tool_config(tools,opts.get('tool_choice'))
        return args

    def _auth(self,model):
        headers={}
        if model.get('key_env'):
            key=os.getenv(model['key_env'])
            if not key:
                raise Fault('Provider credential is not configured',503)
            headers['Authorization']='Bearer '+key
        return headers

    def stream(self,model,messages,max_tokens=1024,temperature=.2,tools=None,opts=None):
        """Yield {'delta': text} pieces, then one {'tool_calls': [...]} if the model called tools,
        then {'usage': {...}, 'evidence_class': ...}."""
        self.validate(model)
        opts=opts or {}
        check_support(model,tools,opts)
        kind=model['provider']
        if opts.get('tool_choice')=='none':
            tools=None
        if kind=='aws':
            yield from self._aws_stream(model,messages,max_tokens,temperature,tools,opts)
            return
        if kind=='demo':
            result=self.chat(model,messages,tools,max_tokens,temperature,opts)
            words=result['content'].split(' ')
            pause=min(.03,1.2/max(1,len(words)))
            for i,word in enumerate(words):
                yield {'delta':(' ' if i else '')+word}
                if pause:
                    time.sleep(pause)
            if result['tool_calls']:
                yield {'tool_calls':result['tool_calls']}
            yield {'usage':result['usage'],'evidence_class':result['evidence_class']}
            return
        url=model['base_url'].rstrip('/')
        headers=self._auth(model)
        usage={}
        assembler=ToolCallAssembler()
        if kind=='ollama':
            body=self._ollama_body(model,messages,tools,max_tokens,temperature,opts,True)
            for line in stream_lines(url+'/api/chat',body,headers,self.allowed_hosts):
                try:
                    chunk=json.loads(line)
                except ValueError:
                    continue
                text=chunk.get('message',{}).get('content','')
                if text:
                    yield {'delta':text}
                for call in chunk.get('message',{}).get('tool_calls') or []:
                    assembler.add(len(assembler.calls),None,call['function']['name'],json.dumps(call['function'].get('arguments') or {}))
                if chunk.get('done'):
                    usage={'prompt_tokens':chunk.get('prompt_eval_count',0),'completion_tokens':chunk.get('eval_count',0)}
            if assembler.calls:
                yield {'tool_calls':assembler.result()}
            yield {'usage':usage,'evidence_class':'provider'}
            return
        body=self._openai_body(model,messages,tools,max_tokens,temperature,opts,True)
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
                delta=choice.get('delta') or {}
                text=delta.get('content')
                if text:
                    yield {'delta':text}
                for call in delta.get('tool_calls') or []:
                    function=call.get('function') or {}
                    assembler.add(call.get('index',0),call.get('id'),function.get('name'),function.get('arguments'))
        if assembler.calls:
            yield {'tool_calls':assembler.result()}
        yield {'usage':usage,'evidence_class':'provider'}

    def _aws_client(self,model):
        try:
            import boto3
        except ImportError as exc:
            raise Fault('Install nuvora[aws] for the AWS provider',503) from exc
        return boto3.client('bedrock-runtime',region_name=model.get('region','us-east-1'))

    def _aws_stream(self,model,messages,max_tokens,temperature,tools=None,opts=None):
        client=self._aws_client(model)
        try:
            raw=client.converse_stream(**self._aws_args(model,messages,tools,max_tokens,temperature,opts or {}))
        except Exception as exc:
            raise Fault('AWS model invocation failed',502) from exc
        usage={}
        assembler=ToolCallAssembler()
        try:
            for event in raw['stream']:
                text=event.get('contentBlockDelta',{}).get('delta',{}).get('text')
                if text:
                    yield {'delta':text}
                started=event.get('contentBlockStart',{}).get('start',{}).get('toolUse')
                if started:
                    assembler.add(event['contentBlockStart'].get('contentBlockIndex',0),started.get('toolUseId'),started.get('name'))
                piece=event.get('contentBlockDelta',{}).get('delta',{}).get('toolUse')
                if piece:
                    assembler.add(event['contentBlockDelta'].get('contentBlockIndex',0),arguments=piece.get('input'))
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
        if assembler.calls:
            yield {'tool_calls':assembler.result()}
        yield {'usage':usage,'evidence_class':'provider'}

    def image(self,model,prompt,n,size):
        """[(bytes, mime)] from an OpenAI-compatible /images/generations endpoint, or a synthetic demo PNG."""
        self.validate(model)
        if model['provider']=='demo':
            return [(demo_png(prompt,i),'image/png') for i in range(n)]
        if model['provider']!='openai':
            raise Fault('Image generation uses the OpenAI-compatible provider',422)
        raw=post_json(model['base_url'].rstrip('/')+'/images/generations',{'model':model['upstream_model'],'prompt':prompt,'n':n,'size':size,'response_format':'b64_json'},
                      self._auth(model),self.allowed_hosts,180,48*1024*1024)
        out=[]
        for item in (raw.get('data') if isinstance(raw,dict) else None) or []:
            try:
                data=base64.b64decode(item['b64_json'],validate=True)
            except (KeyError,TypeError,ValueError) as exc:
                raise Fault('Image provider must return b64_json images',502) from exc
            mime='image/png' if data.startswith(b'\x89PNG') else 'image/jpeg' if data.startswith(b'\xff\xd8') else 'image/webp' if data[8:12]==b'WEBP' else None
            if not mime:
                raise Fault('Image provider returned an unsupported image format',502)
            out.append((data,mime))
        if not out:
            raise Fault('Image provider returned no images',502)
        return out[:n]

    def transcribe(self,model,filename,data,mime):
        """Speech to text through an OpenAI-compatible /audio/transcriptions endpoint."""
        self.validate(model)
        if model['provider']!='openai':
            raise Fault('Transcription models use the OpenAI-compatible provider (for example a Whisper server)',422)
        url=model['base_url'].rstrip('/')+'/audio/transcriptions'
        validate_url(url,self.allowed_hosts)
        body,ctype=multipart({'model':model['upstream_model'],'response_format':'json'},[('file',filename,mime,data)])
        request=urllib.request.Request(url,body,{'Content-Type':ctype,**self._auth(model)},method='POST')
        try:
            with urllib.request.build_opener(NoRedirect).open(request,timeout=300) as response:
                raw=json.loads(response.read(8*1024*1024))
        except Fault:
            raise
        except (urllib.error.URLError,ValueError,TimeoutError) as exc:
            raise Fault('Transcription request failed; check operator configuration',502) from exc
        if not isinstance(raw,dict) or not isinstance(raw.get('text'),str):
            raise Fault('Transcription provider returned no text',502)
        return raw['text']

    def embed(self,model,texts):
        if model['provider'] not in ('demo','openai','ollama'):
            raise Fault('Embedding models require an OpenAI-compatible or Ollama provider')
        self.validate(model)
        if model['provider']=='demo':
            return [demo_embedding(t) for t in texts]
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
