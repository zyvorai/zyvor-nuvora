# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import base64
from harness import LiveServer


class IngestionJobTests(LiveServer):
    def setUp(self):
        super().setUp()
        self.kb = self.json('/api/knowledge', {'name': 'Jobs'}, expect=201)['id']

    def run_job(self, body, expect_status='COMPLETE'):
        job = self.json(f'/api/knowledge/{self.kb}/ingestion-jobs', body, expect=202)
        self.assertEqual(job['status'], 'STARTING')
        self.assertEqual(job['statistics']['documents_scanned'], 0)
        self.app.process_job(self.p, job['id'])
        done = self.json(f'/api/knowledge/{self.kb}/ingestion-jobs/{job["id"]}', expect=200)
        self.assertEqual(done['status'], expect_status, done)
        return done

    def test_documents_job_counts_new_modified_unchanged_and_failures(self):
        first = self.run_job({'documents': [{'name': 'a', 'text': 'alpha refunds'}, {'name': 'b', 'text': 'beta shipping'}]})
        self.assertEqual(first['statistics'], {'documents_scanned': 2, 'documents_new': 2, 'documents_modified': 0, 'documents_unchanged': 0, 'documents_deleted': 0, 'documents_failed': 0})
        self.assertTrue(first['started'] and first['finished'])
        again = self.run_job({'documents': [
            {'name': 'a', 'text': 'alpha refunds'}, {'name': 'b', 'text': 'beta shipping changed'},
            {'name': 'c', 'content_base64': base64.b64encode(b'gamma upload').decode(), 'content_type': 'text/plain'},
            {'name': 'd', 'content_base64': 'AAAA', 'content_type': 'application/x-nothing'}]})
        s = again['statistics']
        self.assertEqual((s['documents_scanned'], s['documents_unchanged'], s['documents_modified'], s['documents_new'], s['documents_failed']), (4, 1, 1, 1, 1))
        self.assertEqual(len(again['failure_reasons']), 1)
        self.assertTrue(again['failure_reasons'][0].startswith('d:'))
        self.assertEqual(len(self.json(f'/api/knowledge/{self.kb}/documents')['items']), 3)

    def test_text_source_all_failed_marks_job_failed(self):
        done = self.run_job({'source': 'text', 'name': 'x', 'text': 'x' * 10}, 'COMPLETE')
        self.assertEqual(done['statistics']['documents_new'], 1)
        bad = self.run_job({'documents': [{'name': 'z', 'content_base64': 'AAAA', 'content_type': 'application/x-nothing'}]}, 'FAILED')
        self.assertEqual(bad['statistics']['documents_failed'], 1)
        self.assertIn('Every document failed', bad['failure_reasons'])

    def test_validation_and_roles(self):
        path = f'/api/knowledge/{self.kb}/ingestion-jobs'
        self.json(path, {'documents': []}, expect=400)
        self.json(path, {'documents': [{'name': 'a'}]}, expect=400)
        self.json(path, {'source': 'ftp'}, expect=400)
        self.json(path, {'source': 'connector', 'connector_id': 'nope'}, expect=404)
        self.json('/api/knowledge/missing/ingestion-jobs', {'text': 'x'}, expect=404)
        self.json(f'{path}/nope', expect=404)

    def test_one_running_job_and_idempotency_and_status(self):
        self.assertEqual(self.json(f'/api/knowledge/{self.kb}')['status'], 'ACTIVE')
        path = f'/api/knowledge/{self.kb}/ingestion-jobs'
        job = self.json(path, {'text': 'hello world', 'name': 'h', 'clientToken': 't1'}, expect=202)
        same = self.json(path, {'text': 'hello world', 'name': 'h', 'clientToken': 't1'}, expect=202)
        self.assertEqual(job['id'], same['id'])
        self.json(path, {'text': 'other', 'name': 'o'}, expect=409)
        self.assertEqual(self.json(f'/api/knowledge/{self.kb}')['status'], 'UPDATING')
        self.assertEqual(self.json('/api/knowledge')['items'][0]['status'], 'UPDATING')
        self.app.process_job(self.p, job['id'])
        self.assertEqual(self.json(f'/api/knowledge/{self.kb}')['status'], 'ACTIVE')
        self.run_job({'documents': [{'name': 'z', 'content_base64': 'AAAA', 'content_type': 'application/x-nothing'}]}, 'FAILED')
        self.assertEqual(self.json(f'/api/knowledge/{self.kb}')['status'], 'FAILED')
        self.run_job({'text': 'fine again', 'name': 'ok'})
        self.assertEqual(self.json(f'/api/knowledge/{self.kb}')['status'], 'ACTIVE')

    def test_job_pagination(self):
        ids = []
        for n in range(3):
            ids.append(self.run_job({'text': f'doc {n} text', 'name': f'd{n}'})['id'])
        seen, token = [], None
        while True:
            url = f'/api/knowledge/{self.kb}/ingestion-jobs?maxResults=2' + (f'&nextToken={token}' if token else '')
            page = self.json(url, expect=200)
            seen += [j['id'] for j in page['items']]
            token = page.get('nextToken')
            if not token:
                break
        self.assertEqual(seen, ids[::-1])
        self.json(f'/api/knowledge/{self.kb}/ingestion-jobs?maxResults=0', expect=400)
        self.json(f'/api/knowledge/{self.kb}/ingestion-jobs?nextToken=garbage', expect=400)

    def test_list_pagination_documents_knowledge_and_retrieve(self):
        for n in range(4):
            self.json('/api/knowledge', {'name': f'K{n}'}, expect=201)
        everything = self.json('/api/knowledge')['items']
        self.assertGreaterEqual(len(everything), 5)
        got, token = [], None
        while True:
            page = self.json('/api/knowledge?maxResults=2' + (f'&nextToken={token}' if token else ''))
            got += [k['id'] for k in page['items']]
            token = page.get('nextToken')
            if not token:
                break
        self.assertEqual(got, [k['id'] for k in everything])
        self.run_job({'documents': [{'name': f'n{i}', 'text': f'refund policy number {i} applies'} for i in range(5)]})
        page = self.json(f'/api/knowledge/{self.kb}/documents?maxResults=3')
        self.assertEqual(len(page['items']), 3)
        rest = self.json(f'/api/knowledge/{self.kb}/documents?maxResults=3&nextToken={page["nextToken"]}')
        self.assertEqual(len(rest['items']), 2)
        self.assertNotIn('nextToken', rest)
        self.assertFalse({d['id'] for d in page['items']} & {d['id'] for d in rest['items']})
        body = {'knowledge_ids': [self.kb], 'query': 'refund policy', 'top_k': 5}
        full = self.json('/api/retrieve', body, expect=200)
        self.assertEqual(len(full['citations']), 5)
        self.assertNotIn('nextToken', full)
        p1 = self.json('/api/retrieve', {**body, 'maxResults': 2}, expect=200)
        p2 = self.json('/api/retrieve', {**body, 'maxResults': 2, 'nextToken': p1['nextToken']}, expect=200)
        p3 = self.json('/api/retrieve', {**body, 'maxResults': 2, 'nextToken': p2['nextToken']}, expect=200)
        joined = p1['citations'] + p2['citations'] + p3['citations']
        self.assertEqual([c['document_id'] for c in joined], [c['document_id'] for c in full['citations']])
        self.assertNotIn('nextToken', p3)
        self.json('/api/retrieve', {**body, 'query': 'different', 'maxResults': 2, 'nextToken': p1['nextToken']}, expect=400)
