# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import base64
import io
import unittest
import zipfile

from harness import LiveServer
from nuvora import ingest
from nuvora.security import Fault


def docx(paragraphs):
    ns='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    body=''.join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs)
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        z.writestr('[Content_Types].xml','<Types/>')
        z.writestr('word/document.xml',f'<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def pdf(text):
    """A minimal single-page PDF with one line of Helvetica text."""
    stream=f'BT /F1 18 Tf 72 720 Td ({text}) Tj ET'.encode()
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
             b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
             b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream',
             b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out=bytearray(b'%PDF-1.4\n');offsets=[]
    for i,obj in enumerate(objects,1):
        offsets.append(len(out));out+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    xref=len(out)
    out+=f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()+b''.join(f'{o:010d} 00000 n \n'.encode() for o in offsets)
    out+=f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return bytes(out)


def has_pypdf():
    try:
        import pypdf  # noqa: F401
        return True
    except ImportError:
        return False


class ExtractTests(unittest.TestCase):
    def test_plain_markdown_csv_json(self):
        self.assertEqual(ingest.extract('a.md','', '# Title\r\n\r\n\r\n\r\nBody'.encode())[0],'# Title\n\nBody')
        self.assertEqual(ingest.extract('t.csv','',b'a,b\n1, 2\n')[0],'a | b\n1 | 2')
        self.assertIn('"k": 1',ingest.extract('d.json','',b'{"k":1}')[0])
        self.assertEqual(ingest.extract('notes','text/plain','\ufeffhello'.encode('utf-8'))[0],'hello')

    def test_html_strips_scripts_and_styles(self):
        text,kind=ingest.extract('p.html','',b'<html><style>.x{}</style><script>alert(1)</script><h1>Keep</h1><p>Isolates &amp; audits</p></html>')
        self.assertEqual(kind,'text/html')
        self.assertNotIn('alert',text);self.assertNotIn('.x',text)
        self.assertIn('Keep',text);self.assertIn('Isolates & audits',text)

    def test_docx(self):
        text,kind=ingest.extract('brief.docx','',docx(['Quarterly review','Approved by Priya']))
        self.assertTrue(kind.endswith('wordprocessingml.document'))
        self.assertEqual(text,'Quarterly review\nApproved by Priya')
        with self.assertRaises(Fault) as bad:
            ingest.extract('broken.docx','',b'not a zip')
        self.assertEqual(bad.exception.status,422)

    @unittest.skipUnless(has_pypdf(),'pypdf not installed')
    def test_pdf(self):
        text,kind=ingest.extract('incident.pdf','',pdf('Frankfurt outage summary'))
        self.assertEqual(kind,'application/pdf')
        self.assertIn('Frankfurt outage summary',text)

    def test_rejections(self):
        for name,data,status in (('x.exe',b'MZ',415),('empty.txt',b'',400),('blank.txt',b'   \n',422)):
            with self.assertRaises(Fault) as ctx:
                ingest.extract(name,'',data)
            self.assertEqual(ctx.exception.status,status,name)
        with self.assertRaises(Fault) as big:
            ingest.extract('big.txt','',b'a'*(ingest.MAX_UPLOAD+1))
        self.assertEqual(big.exception.status,413)


class UploadAPITests(LiveServer):
    def kb(self):
        return self.json('/api/knowledge',{'name':'Uploads'},expect=201)['id']

    def upload(self,kb,name,data,token=None,content_type=''):
        return self.request(f'/api/knowledge/{kb}/upload',{'name':name,'content_base64':base64.b64encode(data).decode(),'content_type':content_type},token)

    def test_upload_retrieve_delete(self):
        kb=self.kb()
        code,raw,_=self.upload(kb,'brief.docx',docx(['Quokka migration runs on Tuesday']),self.dev)
        self.assertEqual(code,201,raw)
        import json
        doc=json.loads(raw)
        self.assertEqual(doc['source'],'upload')
        self.assertTrue(doc['content_type'].endswith('wordprocessingml.document'))
        self.assertGreater(doc['bytes'],0)
        listed=self.json(f'/api/knowledge/{kb}/documents',expect=200)['items']
        self.assertEqual([(d['name'],d['chunks']) for d in listed],[('brief.docx',1)])
        self.assertNotIn('text',listed[0])
        hits=self.json('/api/retrieve',{'knowledge_ids':[kb],'query':'quokka migration'},expect=200)['citations']
        self.assertEqual(hits[0]['document_id'],doc['id'])
        self.assertEqual(self.request(f'/api/documents/{doc["id"]}',token=self.viewer,method='DELETE')[0],403)
        self.json(f'/api/documents/{doc["id"]}',token=self.dev,method='DELETE',expect=200)
        self.assertEqual(self.json('/api/retrieve',{'knowledge_ids':[kb],'query':'quokka migration'},expect=200)['citations'],[])
        actions=[e['action'] for e in self.store.events('a')]
        self.assertIn('document.deleted',actions)

    def test_upload_limits_and_errors(self):
        kb=self.kb()
        self.assertEqual(self.upload(kb,'x.exe',b'MZ')[0],415)
        self.assertEqual(self.request(f'/api/knowledge/{kb}/upload',{'name':'a.txt','content_base64':'@@@'})[0],400)
        self.assertEqual(self.upload(kb,'a.txt',b'hello',self.viewer)[0],403)
        import http.client
        for path,size,status in (('/api/chat',1024*1024+1,413),(f'/api/knowledge/{kb}/upload',1024*1024+1,'not 413'),(f'/api/knowledge/{kb}/upload',28*1024*1024+1,413)):
            conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
            conn.putrequest('POST',path)
            for k,v in (('Authorization','Bearer '+self.token),('Content-Type','application/json'),('Content-Length',str(size))):
                conn.putheader(k,v)
            conn.endheaders()
            if status==413:
                self.assertEqual(conn.getresponse().status,413,path)
            else:
                conn.send(b'{"name":"a.txt","content_base64":"aGk="}'+b' '*(size-40))
                self.assertEqual(conn.getresponse().status,201,path)
            conn.close()

    def test_deleting_a_knowledge_base_removes_its_documents(self):
        kb=self.kb()
        self.upload(kb,'one.txt',b'first document')
        other=self.kb()
        self.upload(other,'two.txt',b'second document')
        self.json(f'/api/knowledge/{kb}',method='DELETE',expect=200)
        names=[d['name'] for d in self.json('/api/documents',expect=200)['items']]
        self.assertNotIn('one.txt',names)
        self.assertIn('two.txt',names)


if __name__=='__main__':
    unittest.main()
