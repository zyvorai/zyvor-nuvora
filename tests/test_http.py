# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from nuvora.store import Store
from dbutil import make_store
from nuvora.security import Auth
from nuvora.platform import Platform
from nuvora.server import Server

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.store=make_store(str(Path(cls.tmp.name)/'test.db'))
        cls.auth=Auth(cls.store)
        cls.auth.add_user('a','owner','Long-password-123','admin')
        cls.auth.add_user('b','other','Long-password-123','admin')
        cls.app=Platform(cls.store,cls.auth)
        cls.app.seed({'tenant':'a','username':'owner','role':'admin'})
        cls.token=cls.auth.login('a','owner','Long-password-123')
        cls.other=cls.auth.login('b','other','Long-password-123')
        cls.server=Server(('127.0.0.1',0),cls.app)
        cls.url='http://127.0.0.1:'+str(cls.server.server_port)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.store.db.close();cls.tmp.cleanup()

    def request(self,path,body=None,headers=None,method=None):
        h={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'}
        if headers:h.update(headers)
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=h,method=method)
        try:
            with urllib.request.urlopen(req) as r:return r.status,r.read(),r.headers
        except urllib.error.HTTPError as r:return r.code,r.read(),r.headers

    def test_health(self):
        code,body,_=self.request('/healthz',headers={'Authorization':''})
        self.assertEqual(code,200)

    def test_unauthenticated(self):
        self.assertEqual(self.request('/api/models',headers={'Authorization':''})[0],401)

    def test_session_cookie_csrf(self):
        code,raw,headers=self.request('/api/login',{'tenant':'a','username':'owner','password':'Long-password-123'},headers={'Authorization':''})
        self.assertEqual(code,200)
        self.assertIn('HttpOnly',headers['Set-Cookie'])
        cookie=headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('/api/logout',{},headers={'Authorization':'','Cookie':cookie})[0],403)
        self.assertEqual(self.request('/api/logout',{},headers={'Authorization':'','Cookie':cookie,'X-CSRF-Token':json.loads(raw)['csrf']})[0],200)

    def test_cross_origin_denied(self):
        self.assertEqual(self.request('/api/chat',{},headers={'Origin':'https://evil.example'})[0],403)

    def test_api_not_spa_fallback(self):
        code,raw,headers=self.request('/api/nonexistent')
        self.assertEqual(code,404)
        self.assertIn('application/json',headers['Content-Type'])

    def test_openai_envelope(self):
        code,raw,_=self.request('/v1/chat/completions',{'model':'auto','messages':[{'role':'user','content':'hello'}]})
        self.assertEqual(code,200)
        value=json.loads(raw)
        self.assertEqual(value['object'],'chat.completion')
        self.assertIn('OFFLINE DEMO',value['choices'][0]['message']['content'])

    def test_streaming_sse(self):
        code,raw,headers=self.request('/v1/chat/completions',{'model':'auto','messages':[{'role':'user','content':'hello'}],'stream':True})
        self.assertEqual(code,200)
        self.assertIn('text/event-stream',headers['Content-Type'])
        self.assertIn(b'data: [DONE]',raw)

    def test_http_tenant_boundary(self):
        model=self.app.list({'tenant':'a','username':'owner','role':'admin'},'models')[0]
        code,_,_=self.request('/api/models/'+model['id'],headers={'Authorization':'Bearer '+self.other})
        self.assertEqual(code,404)

    def test_mcp_tools(self):
        code,raw,_=self.request('/mcp',{'jsonrpc':'2.0','id':1,'method':'tools/list'})
        self.assertEqual(code,200)
        self.assertEqual(len(json.loads(raw)['result']['tools']),2)

    def test_unknown_mcp_tool(self):
        _,raw,_=self.request('/mcp',{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'shell'}})
        self.assertIn('error',json.loads(raw))

    def test_static_traversal(self):
        self.assertEqual(self.request('/%2e%2e/pyproject.toml')[0],404)

    def test_security_headers(self):
        _,_,headers=self.request('/healthz')
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        self.assertEqual(headers['X-Content-Type-Options'],'nosniff')

if __name__=='__main__':unittest.main()
