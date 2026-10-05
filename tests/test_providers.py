# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from nuvora.providers import Providers,post_json
from nuvora.security import Fault

class Stub(BaseHTTPRequestHandler):
    captured=[]
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.captured.append((self.path,body))
        if self.path=='/redirect':
            self.send_response(302);self.send_header('Location','http://169.254.169.254');self.end_headers();return
        if self.path.endswith('embeddings'):
            value={'data':[{'index':i,'embedding':[float(i+1),0.5]} for i in range(len(body['input']))]}
        elif self.path.endswith('/api/chat'):
            value={'message':{'content':'Ollama response'},'prompt_eval_count':4,'eval_count':3}
        else:
            value={'choices':[{'message':{'content':'Provider response'}}],'usage':{'prompt_tokens':4,'completion_tokens':3}}
        raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Stub)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.server.server_port)
        cls.providers=Providers({'127.0.0.1'})
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
    def model(self,kind='openai'):
        return {'provider':kind,'base_url':self.url+('/v1' if kind=='openai' else ''),'upstream_model':'stub'}
    def test_openai_real_http_mapping(self):
        r=self.providers.chat(self.model(),[{'role':'user','content':'hello'}])
        self.assertEqual(r['content'],'Provider response')
        self.assertEqual(r['evidence_class'],'provider')
        self.assertFalse(Stub.captured[-1][1]['stream'])
    def test_ollama_mapping(self):
        r=self.providers.chat(self.model('ollama'),[{'role':'user','content':'hello'}])
        self.assertEqual(r['content'],'Ollama response')
        self.assertEqual(r['usage']['completion_tokens'],3)
    def test_embeddings_mapping(self):
        r=self.providers.embed(self.model(),['a','b'])
        self.assertEqual(r,[[1.0,.5],[2.0,.5]])
    def test_redirect_denied(self):
        with self.assertRaises(Fault):post_json(self.url+'/redirect',{}, {},{'127.0.0.1'})
    def test_missing_secret(self):
        with self.assertRaises(Fault):self.providers.chat({**self.model(),'key_env':'NUVORA_SECRET_MISSING'},[{'role':'user','content':'hello'}])
    def test_ollama_tools_explicitly_refused(self):
        with self.assertRaises(Fault):self.providers.chat(self.model('ollama'),[{'role':'user','content':'hello'}],[{'type':'function'}])

if __name__=='__main__':unittest.main()
