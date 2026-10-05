# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import base64
import importlib.util
import json
import unittest

from test_evals_retrieval import StubModels
from nuvora.platform import Platform
from nuvora.providers import aws_messages, ollama_messages, text_of

PNG=b'\x89PNG\r\n\x1a\n'+b'\x00'*32
IMAGE='data:image/png;base64,'+base64.b64encode(PNG).decode()


def parts(text,*images):
    return [{'type':'text','text':text}]+[{'type':'image_url','image_url':{'url':i}} for i in images]


class ProviderMappingTests(unittest.TestCase):
    def test_text_of_and_mappings(self):
        messages=[{'role':'system','content':'Be brief.'},{'role':'user','content':parts('What is this?',IMAGE)}]
        self.assertEqual(text_of(messages[1]['content']),'What is this?')
        ollama=ollama_messages(messages)
        self.assertEqual(ollama[1],{'role':'user','content':'What is this?','images':[base64.b64encode(PNG).decode()]})
        self.assertNotIn('images',ollama[0])
        system,history=aws_messages(messages)
        self.assertEqual(system,[{'text':'Be brief.'}])
        self.assertEqual(history[0]['content'][1],{'image':{'format':'png','source':{'bytes':PNG}}})

    def test_coerce(self):
        self.assertEqual(Platform.coerce('integer','1,200'),1200)
        self.assertEqual(Platform.coerce('number',3),3.0)
        self.assertIs(Platform.coerce('boolean','yes'),True)
        self.assertEqual(Platform.coerce('date','2026-10-05'),'2026-10-05')
        for kind,value in (('integer',1.5),('date','05/10/2026'),('date','2026-13-01'),('boolean','maybe'),('number',True)):
            with self.assertRaises(ValueError):
                Platform.coerce(kind,value)


class MultimodalTests(StubModels):
    def setUp(self):
        super().setUp()
        self.auth.add_user('a','boss',self.password,'approver')
        self.boss={'tenant':'a','username':'boss','role':'approver'}

    def model(self,reply,name='Vision',**extra):
        calls=[]
        def chat(handler,body):
            calls.append(body)
            return 200,{'choices':[{'message':{'content':reply(body['messages'])}}],'usage':{'prompt_tokens':10,'completion_tokens':5}}
        def transcribe(handler,body):
            calls.append({'multipart':body,'type':handler.headers['Content-Type']})
            return 200,{'text':'Refunds over 500 euros need finance approval.'}
        url,_=self.stub({('POST','/v1/chat/completions'):chat,('POST','/v1/audio/transcriptions'):transcribe})
        mid=self.json('/api/models',{'name':name,'provider':'openai','base_url':url+'/v1','upstream_model':'m',**extra},expect=201)['id']
        return mid,calls

    def kb(self,**extra):
        return self.json('/api/knowledge',{'name':'Docs',**extra},expect=201)['id']

    def upload(self,kb,name,data,expect=201):
        return self.json(f'/api/knowledge/{kb}/upload',{'name':name,'content_base64':base64.b64encode(data).decode()},expect=expect)

    def test_vision_parts_reach_the_provider_with_text_guarded(self):
        mid,calls=self.model(lambda m:'A receipt.',vision=True)
        out=self.json('/api/chat',{'model':mid,'messages':[{'role':'user','content':parts('Mail ops@example.com about this',IMAGE)}]},expect=200)
        self.assertEqual(out['content'],'A receipt.')
        sent=calls[0]['messages'][0]['content']
        self.assertEqual(sent[1]['image_url']['url'],IMAGE)
        self.assertNotIn('ops@example.com',sent[0]['text'])

    def test_image_limits_and_vision_requirement(self):
        blind,_=self.model(lambda m:'x',name='Blind')
        vision,_=self.model(lambda m:'x',vision=True)
        self.json('/api/chat',{'model':blind,'messages':[{'role':'user','content':parts('q',IMAGE)}]},expect=422)
        self.json('/api/chat',{'model':vision,'messages':[{'role':'user','content':parts('q',*[IMAGE]*5)}]},expect=400)
        self.json('/api/chat',{'model':vision,'messages':[{'role':'assistant','content':parts('q')}]},expect=400)
        self.json('/api/chat',{'model':vision,'messages':[{'role':'user','content':parts('q','https://example.com/a.png')}]},expect=400)

    def test_image_upload_uses_the_ocr_model(self):
        blind,_=self.model(lambda m:'x',name='Blind')
        self.json('/api/knowledge',{'name':'Bad','ocr_model':blind},expect=400)
        vision,calls=self.model(lambda m:'INVOICE 42\nTotal | 120.00',vision=True)
        doc=self.upload(self.kb(ocr_model=vision),'scan.png',PNG)
        self.assertEqual(doc['extraction'],'ocr')
        self.assertIn('INVOICE 42',self.app.get(self.p,'documents',doc['id'])['text'])
        self.assertEqual(calls[0]['messages'][0]['content'][1]['image_url']['url'],IMAGE)
        self.upload(self.kb(ocr_model=vision),'fake.png',b'not an image',expect=422)

    @unittest.skipIf(importlib.util.find_spec('pytesseract'),'local OCR installed')
    def test_image_upload_without_ocr_explains_the_extra(self):
        code,raw,_=self.request(f'/api/knowledge/{self.kb()}/upload',{'name':'scan.png','content_base64':base64.b64encode(PNG).decode()})
        self.assertEqual(code,503)
        self.assertIn('zyvor-nuvora[ocr]',json.loads(raw)['error'])

    def test_audio_upload_is_transcribed(self):
        self.upload(self.kb(),'call.mp3',b'ID3audio',expect=422)
        whisper,calls=self.model(lambda m:'x',name='Whisper',capability='transcription')
        chat,_=self.model(lambda m:'x',name='Chat')
        self.json('/api/knowledge',{'name':'Bad','transcription_model':chat},expect=400)
        doc=self.upload(self.kb(transcription_model=whisper),'call.mp3',b'ID3audio')
        self.assertEqual(doc['extraction'],'transcription')
        self.assertIn('finance approval',self.app.get(self.p,'documents',doc['id'])['text'])
        self.assertTrue(calls[0]['type'].startswith('multipart/form-data; boundary='))
        self.assertIn(b'filename="call.mp3"',calls[0]['multipart'])
        self.assertIn(b'ID3audio',calls[0]['multipart'])

    FIELDS={'invoice':{'type':'string','description':'Invoice number'},'total':{'type':'number'},'due':{'type':'date'}}

    def extractor(self,confidence):
        return self.model(lambda m:json.dumps({'fields':{'invoice':{'value':'INV-42','confidence':.95},'total':{'value':'1,200.50','confidence':confidence},
                                                        'due':{'value':'2026-11-01','confidence':.9}}}),name='Extractor')[0]

    def test_extraction_coerces_fields(self):
        mid=self.extractor(.9)
        job=self.json('/api/extract',{'text':'Invoice INV-42 total 1,200.50 due 2026-11-01','fields':self.FIELDS,'model':mid},expect=202)
        self.assertNotIn('text',job['input'])
        self.app.process_job(self.p,job['id'])
        done=self.app.get(self.p,'jobs',job['id'])
        self.assertEqual(done['status'],'completed')
        self.assertEqual(done['result']['fields']['total'],{'value':1200.5,'confidence':.9})
        self.assertEqual(done['result']['low_confidence'],[])
        self.json('/api/extract',{'text':'x','fields':{'Bad Name':{'type':'string'}}},expect=400)
        self.json('/api/extract',{'text':'x','fields':{'a':{'type':'money'}}},expect=400)

    def test_bare_values_are_kept_without_confidence(self):
        mid=self.model(lambda m:json.dumps({'fields':{'invoice':'INV-42','total':'1250.50','due':'2026-11-01'}}),name='Small')[0]
        job=self.app.new_job(self.p,'extract',None,{'text':'Invoice INV-42','fields':self.FIELDS,'model':mid,'review':False},None)
        self.app.process_job(self.p,job['id'])
        result=self.app.get(self.p,'jobs',job['id'])['result']
        self.assertEqual(result['fields']['total'],{'value':1250.5,'confidence':0.0})
        self.assertEqual(result['fields']['invoice']['value'],'INV-42')
        self.assertEqual(sorted(result['low_confidence']),['due','invoice','total'])
        self.assertFalse(result['malformed'])

    def test_low_confidence_goes_to_review(self):
        mid=self.extractor(.4)
        for decision,status in (('approved','completed'),('rejected','rejected')):
            job=self.app.new_job(self.p,'extract',None,{'text':'Invoice INV-42','fields':self.FIELDS,'model':mid,'review':True},None)
            self.app.process_job(self.p,job['id'])
            waiting=self.app.get(self.p,'jobs',job['id'])
            self.assertEqual(waiting['status'],'waiting_approval')
            self.assertEqual(waiting['result']['low_confidence'],['total'])
            approval=self.app.get(self.p,'approvals',waiting['checkpoint']['approval'])
            self.assertEqual(approval['action']['type'],'extraction_review')
            self.app.decide(self.boss,approval['id'],decision,approval['digest'])
            self.app.process_job(self.p,job['id'])
            final=self.app.get(self.p,'jobs',job['id'])
            self.assertEqual(final['status'],status)
            if status=='completed':
                self.assertTrue(final['result']['reviewed'])
                self.assertEqual(final['result']['reviewer'],'boss')

    def test_extraction_from_an_image(self):
        blind,_=self.model(lambda m:'{}',name='Blind')
        job=self.app.new_job(self.p,'extract',None,{'image':IMAGE,'fields':self.FIELDS,'model':blind},None)
        self.app.process_job(self.p,job['id'])
        failed=self.app.get(self.p,'jobs',job['id'])
        self.assertEqual(failed['status'],'failed')
        self.assertIn('vision',failed['error'])
        vision,calls=self.model(lambda m:json.dumps({'fields':{'invoice':{'value':'INV-7','confidence':.8}}}),vision=True)
        job=self.app.new_job(self.p,'extract',None,{'image':IMAGE,'fields':self.FIELDS,'model':vision},None)
        self.app.process_job(self.p,job['id'])
        done=self.app.get(self.p,'jobs',job['id'])
        self.assertEqual(done['result']['fields']['invoice']['value'],'INV-7')
        self.assertEqual(sorted(done['result']['low_confidence']),['due','total'])
        self.assertEqual(calls[0]['messages'][1]['content'][1]['image_url']['url'],IMAGE)
