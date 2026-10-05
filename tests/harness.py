# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""A live Nuvora server on an ephemeral port, plus small stub upstreams, for HTTP tests."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from nuvora.platform import Platform
from nuvora.security import Auth
from nuvora.server import Server
from nuvora.store import Store
from dbutil import make_store


class LiveServer(unittest.TestCase):
    password='Long-password-123'

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=make_store(str(Path(self.tmp.name)/'test.db'))
        self.auth=Auth(self.store)
        self.auth.add_user('a','owner',self.password,'admin')
        self.auth.add_user('a','dev',self.password,'developer')
        self.auth.add_user('a','viewer',self.password,'viewer')
        self.app=self.make_platform()
        self.p={'tenant':'a','username':'owner','role':'admin'}
        self.app.seed(self.p)
        self.token=self.auth.login('a','owner',self.password)
        self.dev=self.auth.login('a','dev',self.password)
        self.viewer=self.auth.login('a','viewer',self.password)
        self.server=Server(('127.0.0.1',0),self.app)
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.stubs=[]

    def make_platform(self):
        return Platform(self.store,self.auth)

    def tearDown(self):
        for stub in self.stubs:
            stub.shutdown();stub.server_close()
        self.server.shutdown();self.server.server_close();self.store.db.close();self.tmp.cleanup()

    def request(self,path,body=None,token=None,method=None,headers=None):
        h={'Authorization':'Bearer '+(token or self.token),'Content-Type':'application/json',**(headers or {})}
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=h,method=method)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status,r.read(),r.headers
        except urllib.error.HTTPError as r:
            with r:
                return r.code,r.read(),r.headers

    def json(self,path,body=None,token=None,method=None,expect=None):
        code,raw,_=self.request(path,body,token,method)
        if expect is not None:
            self.assertEqual(code,expect,raw[:400])
        return json.loads(raw) if raw else {}

    def stub(self,routes):
        """Serve routes {('GET'|'POST', path): fn(handler, body) -> (status, obj|bytes, headers)} on loopback."""
        calls=[]

        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):
                pass

            def handle_one(self,method):
                size=int(self.headers.get('Content-Length','0') or 0)
                raw=self.rfile.read(size) if size else b''
                body=json.loads(raw) if raw[:1] in (b'{',b'[') else raw
                path=self.path.split('?')[0]
                calls.append({'method':method,'path':self.path,'body':body,'headers':dict(self.headers)})
                fn=routes.get((method,path))
                if not fn:
                    self.send_response(404);self.end_headers();return
                status,payload,headers=(list(fn(self,body))+[{}])[:3]
                data=payload if isinstance(payload,bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('Content-Type',(headers or {}).get('Content-Type','application/json'))
                self.send_header('Content-Length',str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self.handle_one('GET')

            def do_POST(self):
                self.handle_one('POST')

            def do_DELETE(self):
                self.handle_one('DELETE')

        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.stubs.append(server)
        return 'http://127.0.0.1:'+str(server.server_port),calls
