"""Dependency-free SDK. Cookie login or operator-issued scoped service token."""
import hashlib
import http.cookiejar
import json
import urllib.request
import urllib.error

class NuvoraClient:
    def __init__(self,base_url,token=None):
        from urllib.parse import urlsplit
        parsed=urlsplit(base_url)
        if parsed.scheme!='https' and parsed.hostname not in ('localhost','127.0.0.1','::1'):
            raise ValueError('Remote SDK connections require HTTPS')
        self.base=base_url.rstrip('/')
        self.token=token
        self.csrf=''
        self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self,path,body=None,method=None):
        if not path.startswith('/') or '://' in path:
            raise ValueError('API paths must be relative to the configured host')
        headers={'Content-Type':'application/json'}
        if self.token:headers['Authorization']='Bearer '+self.token
        if self.csrf:headers['X-CSRF-Token']=self.csrf
        req=urllib.request.Request(self.base+path,json.dumps(body).encode() if body is not None else None,headers,method=method or ('POST' if body is not None else 'GET'))
        try:
            with self.opener.open(req,timeout=60) as response:return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(json.loads(exc.read()).get('error','API request failed')) from exc

    def login(self,username,password,tenant='default'):
        result=self.request('/api/login',{'tenant':tenant,'username':username,'password':password})
        self.csrf=result['csrf']
        return result['principal']

    def chat(self,question,model='auto'):
        return self.request('/api/chat',{'model':model,'messages':[{'role':'user','content':question}]})

    def answer(self,question,knowledge_ids,model='auto'):
        return self.request('/api/answer',{'model':model,'question':question,'knowledge_ids':knowledge_ids})

    def run_agent(self,id,message):
        return self.request('/api/agents/'+id+'/run',{'message':message})

    def run_workflow(self,id,text):
        return self.request('/api/workflows/'+id+'/run',{'text':text})

    def job(self,id):return self.request('/api/jobs/'+id)
    def close(self):return self.request('/api/logout',{})
