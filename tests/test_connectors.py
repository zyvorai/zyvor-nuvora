# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import io
import json
import os
import unittest
from unittest import mock

from harness import LiveServer
from nuvora.platform import validate_filter
from nuvora.security import Fault


class FakeS3:
    def __init__(self, objects):
        self.objects = objects
        self.reads = []

    def get_paginator(self, name):
        objects = self.objects

        class Pages:
            def paginate(self, Bucket, Prefix):
                return [{'Contents': [{'Key': k, 'ETag': '"'+v[0]+'"', 'Size': len(v[1])} for k, v in objects.items() if k.startswith(Prefix)]}]
        return Pages()

    def get_object(self, Bucket, Key):
        self.reads.append(Key)
        return {'Body': io.BytesIO(self.objects[Key][1])}


class ConnectorTests(LiveServer):
    def setUp(self):
        super().setUp()
        self.app.connector_hosts = {'127.0.0.1'}
        self.kb = self.json('/api/knowledge', {'name': 'Synced'}, expect=201)['id']

    def sync(self, cid):
        job = self.json(f'/api/connectors/{cid}/sync', {}, expect=202)
        self.app.process_job(self.p, job['id'])
        done = self.app.get(self.p, 'jobs', job['id'])
        self.assertEqual(done['status'], 'completed', done.get('error'))
        return done['result']

    def docs(self):
        return {d['name']: d for d in self.app.documents(self.p, self.kb)}

    def test_web_crawl_respects_robots_and_syncs_incrementally(self):
        pages = {'/': '<title>Home</title><a href="/a">A</a> <a href="/private/x">P</a> <a href="/logo.png">L</a> <a href="https://other.example/">O</a> Welcome',
                 '/a': '<p>Refund policy version one</p>'}

        def page(path):
            return lambda h, b: (200, pages[path].encode(), {'Content-Type': 'text/html; charset=utf-8'}) if path in pages else (404, b'', {})
        url, calls = self.stub({('GET', '/robots.txt'): lambda h, b: (200, b'User-agent: *\nDisallow: /private\n', {'Content-Type': 'text/plain'}),
                                ('GET', '/'): page('/'), ('GET', '/a'): page('/a'), ('GET', '/private/x'): page('/private/x')})
        cid = self.json('/api/connectors', {'name': 'Site', 'type': 'web', 'knowledge_id': self.kb, 'url': url+'/', 'depth': 1, 'metadata': {'team': 'ops'}}, expect=201)['id']
        first = self.sync(cid)
        self.assertEqual((first['added'], first['seen']), (2, 2))
        self.assertIn({'item': url+'/private/x', 'reason': 'disallowed by robots.txt'}, first['skipped'])
        self.assertFalse(any(c['path'] in ('/private/x', '/logo.png') for c in calls))
        docs = self.docs()
        self.assertEqual(docs[url+'/']['metadata'], {'team': 'ops', 'connector': 'Site', 'title': 'Home'})
        self.assertEqual(self.sync(cid)['unchanged'], 2)
        pages['/a'] = '<p>Refund policy version two</p>'
        self.assertEqual(self.sync(cid)['updated'], 1)
        self.assertIn('version two', self.app.get(self.p, 'documents', self.docs()[url+'/a']['id'])['text'])
        pages['/'] = 'Welcome, no links'
        result = self.sync(cid)
        self.assertEqual(result['removed'], 1)
        self.assertEqual(list(self.docs()), [url+'/'])
        connector = self.json(f'/api/connectors/{cid}', expect=200)
        self.assertEqual(connector['last_result']['removed'], 1)

    def test_connector_validation(self):
        self.json('/api/connectors', {'name': 'x', 'type': 'web', 'knowledge_id': self.kb, 'url': 'https://evil.example/'}, expect=403)
        self.json('/api/connectors', {'name': 'x', 'type': 'web', 'knowledge_id': self.kb, 'url': 'http://127.0.0.1/', 'depth': 9}, expect=400)
        self.json('/api/connectors', {'name': 'x', 'type': 'ftp', 'knowledge_id': self.kb}, expect=400)
        self.json('/api/connectors', {'name': 'x', 'type': 's3', 'knowledge_id': self.kb, 'bucket': 'docs'}, token=self.dev, expect=403)
        self.json('/api/connectors', {'name': 'x', 'type': 'confluence', 'knowledge_id': self.kb, 'url': 'http://127.0.0.1/', 'space': 'OPS', 'key_env': 'TOKEN'}, expect=400)
        cid = self.json('/api/connectors', {'name': 'x', 'type': 's3', 'knowledge_id': self.kb, 'bucket': 'docs'}, expect=201)['id']
        self.json(f'/api/knowledge/{self.kb}', method='DELETE', expect=409)
        self.json(f'/api/connectors/{cid}/sync', {}, token=self.dev, expect=403)
        self.app.connector_hosts = set()
        self.json('/api/connectors', {'name': 'x', 'type': 'web', 'knowledge_id': self.kb, 'url': 'http://127.0.0.1/'}, expect=403)

    def test_confluence_pages_sync_by_version(self):
        seen = []

        def content(handler, body):
            seen.append(handler.headers['Authorization'])
            return 200, {'results': [{'id': '1', 'title': 'Runbook', 'version': {'number': 3}, 'body': {'storage': {'value': '<p>Restart the <b>queue</b></p>'}}, '_links': {'webui': '/x/1'}},
                                     {'id': '2', 'title': 'Broken'}], '_links': {}}
        url, _ = self.stub({('GET', '/wiki/rest/api/content'): content})
        with mock.patch.dict(os.environ, {'NUVORA_SECRET_CONF': 'tok'}):
            cid = self.json('/api/connectors', {'name': 'Wiki', 'type': 'confluence', 'knowledge_id': self.kb, 'url': url+'/wiki', 'space': 'OPS', 'key_env': 'NUVORA_SECRET_CONF'}, expect=201)['id']
            first = self.sync(cid)
            self.assertEqual(first['added'], 1)
            self.assertEqual(first['skipped'][0]['reason'], 'page without body or version')
            self.assertEqual(seen[0], 'Bearer tok')
            self.assertEqual(self.docs()['Runbook']['version'], '3')
            self.assertEqual(self.sync(cid)['unchanged'], 1)

    def test_s3_prefix_skips_unchanged_etags(self):
        s3 = FakeS3({'kb/a.md': ('e1', b'# Alpha policy'), 'kb/b.txt': ('e2', b'Beta notes'), 'kb/c.png': ('e3', b'x'), 'other/d.txt': ('e4', b'no')})
        self.app.s3_factory = lambda spec: s3
        cid = self.json('/api/connectors', {'name': 'Bucket', 'type': 's3', 'knowledge_id': self.kb, 'bucket': 'docs', 'prefix': 'kb/'}, expect=201)['id']
        first = self.sync(cid)
        self.assertEqual(first['added'], 2)
        self.assertEqual(first['skipped'][0]['item'], 'kb/c.png')
        s3.reads.clear()
        s3.objects['kb/b.txt'] = ('e5', b'Beta notes revised')
        second = self.sync(cid)
        self.assertEqual((second['unchanged'], second['updated']), (1, 1))
        self.assertEqual(s3.reads, ['kb/b.txt'])

    def test_scheduler_queues_due_connectors_once(self):
        s3 = FakeS3({'a.txt': ('e1', b'alpha')})
        self.app.s3_factory = lambda spec: s3
        cid = self.json('/api/connectors', {'name': 'Bucket', 'type': 's3', 'knowledge_id': self.kb, 'bucket': 'docs', 'interval_minutes': 15}, expect=201)['id']
        self.app.schedule_connectors()
        self.app.schedule_connectors()
        jobs = [j for j in self.app.list(self.p, 'jobs') if j['type'] == 'sync']
        self.assertEqual(len(jobs), 1)
        self.app.process_job(jobs[0]['principal'], jobs[0]['id'])
        self.app.schedule_connectors()
        self.assertEqual(len([j for j in self.app.list(self.p, 'jobs') if j['type'] == 'sync']), 1)
        self.assertEqual(self.app.get(self.p, 'connectors', cid)['last_result']['added'], 1)


class AccessTests(LiveServer):
    def setUp(self):
        super().setUp()
        self.kb = self.json('/api/knowledge', {'name': 'Mixed'}, expect=201)['id']

    def ingest(self, name, text, token=None, expect=201, **extra):
        return self.json(f'/api/knowledge/{self.kb}/ingest', {'name': name, 'text': text, **extra}, token=token, expect=expect)

    def search(self, query, token=None, **extra):
        return [c['document'] for c in self.json('/api/retrieve', {'knowledge_ids': [self.kb], 'query': query, **extra}, token=token, expect=200)['citations']]

    def test_metadata_filters(self):
        self.ingest('ops', 'refund escalation rules', metadata={'team': 'ops', 'year': 2026})
        self.ingest('sales', 'refund discount rules', metadata={'team': 'sales', 'year': 2025})
        self.assertEqual(self.search('refund rules', filter={'team': 'ops'}), ['ops'])
        self.assertEqual(sorted(self.search('refund rules', filter={'year': {'in': [2025, 2026]}})), ['ops', 'sales'])
        self.assertEqual(self.search('refund rules', filter={'team': 'legal'}), [])
        self.json('/api/retrieve', {'knowledge_ids': [self.kb], 'query': 'q', 'filter': {'team': {'gt': 1}}}, expect=400)
        self.ingest('bad', 'x', metadata={'Bad Key': 1}, expect=400)
        with self.assertRaises(Fault):
            validate_filter({'a': [1]})

    def test_group_acls(self):
        self.json('/api/users/dev', {'groups': ['finance']}, expect=200)
        self.assertEqual(next(u for u in self.json('/api/users', expect=200)['users'] if u['username'] == 'dev')['groups'], ['finance'])
        self.assertEqual(self.json('/api/users/dev', {'groups': 'finance'}, expect=400).get('error')[:6], 'groups')
        doc = self.ingest('payroll', 'salary bands for finance', groups=['finance'])
        self.ingest('handbook', 'salary review process for everyone')
        self.assertEqual(sorted(self.search('salary', token=self.dev)), ['handbook', 'payroll'])
        self.assertEqual(self.search('salary', token=self.viewer), ['handbook'])
        self.json('/api/documents/'+doc['id'], token=self.viewer, expect=404)
        self.assertNotIn('payroll', [d['name'] for d in self.json('/api/documents', token=self.viewer, expect=200)['items']])
        self.assertNotIn('payroll', [d['name'] for d in self.json(f'/api/knowledge/{self.kb}/documents', token=self.viewer, expect=200)['items']])
        self.ingest('secret', 'x', token=self.dev, groups=['legal'], expect=403)
        self.ingest('payroll', 'overwrite', token=self.viewer, expect=403)


if __name__ == '__main__':
    unittest.main()
