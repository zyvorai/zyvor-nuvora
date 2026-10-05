# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import json
import time

from harness import LiveServer
from nuvora.security import Fault


class IntegrationTest(LiveServer):
    def setUp(self):
        super().setUp()
        self.devp = {'tenant': 'a', 'username': 'dev', 'role': 'developer'}
        self.model = next(m for m in self.app.list(self.p, 'models') if m['capability'] == 'chat')['id']
        self.env = {}
        self.app.integrations.env = self.env

    def configure(self, system, routes, token='secret-token'):
        url, calls = self.stub(routes)
        self.env['NUVORA_'+system.upper()+'_URL'] = url
        self.env['NUVORA_SECRET_'+system.upper()+'_TOKEN'] = token
        return calls

    def scripted(self, name, arguments):
        def provider(model, messages, tools, maximum, temp):
            done = any(m['role'] == 'tool' for m in messages)
            return {'content': 'done' if done else '', 'usage': {}, 'evidence_class': 'scripted test',
                    'tool_calls': [] if done else [{'id': 'c1', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}
        self.app.providers.chat = provider

    def test_tools_appear_only_when_configured(self):
        self.assertNotIn('netra_status', self.json('/api/tools')['tools'])
        with self.assertRaises(Fault):
            self.app.create(self.devp, 'agents', {'name': 'x', 'model': self.model, 'tools': ['netra_status']})
        self.configure('netra', {})
        tools = self.json('/api/tools')['tools']
        self.assertIn('netra_incidents', tools)
        self.assertNotIn('run_code', tools)
        systems = {s['id']: s for s in self.json('/api/integrations')['systems']}
        self.assertTrue(systems['netra']['configured'] and systems['netra']['credential_set'])
        self.assertFalse(systems['keep']['configured'])
        self.json('/api/integrations', token=self.dev, expect=403)

    def test_netra_tool_is_read_only_and_screened(self):
        calls = self.configure('netra', {('GET', '/api/v1/incidents'): lambda h, b: (200, {'incidents': [{'id': 'i1', 'owner': 'noc@example.com', 'severity': 'high'}]})})
        agent = self.app.create(self.devp, 'agents', {'name': 'NOC', 'model': self.model, 'tools': ['netra_incidents']})
        self.scripted('netra_incidents', {'status': 'open'})
        job = self.app.new_job(self.devp, 'agent', agent['id'], {'message': 'open incidents?'})
        self.app.process_job(self.devp, job['id'])
        job = self.app.get(self.devp, 'jobs', job['id'])
        self.assertEqual(job['status'], 'completed')
        result = next(t for t in job['trace'] if t['type'] == 'tool')['result']
        self.assertEqual(result['incidents'][0]['owner'], '[EMAIL]')
        self.assertEqual(calls[0]['method'], 'GET')
        self.assertIn('status=open', calls[0]['path'])
        self.assertIn('limit=20', calls[0]['path'])
        self.assertEqual(calls[0]['headers']['Authorization'], 'Bearer secret-token')
        self.scripted('netra_incidents', {'status': 'everything'})
        job = self.app.new_job(self.devp, 'agent', agent['id'], {'message': 'bad args'})
        self.app.process_job(self.devp, job['id'])
        self.assertEqual(self.app.get(self.devp, 'jobs', job['id'])['status'], 'failed')

    def keep_routes(self, process_status=200):
        return {('POST', '/v1/sandboxes'): lambda h, b: (201, {'id': 'sbx-1'}),
                ('POST', '/v1/sandboxes/sbx-1/fs/write'): lambda h, b: (200, {}),
                ('POST', '/v1/sandboxes/sbx-1/process'): lambda h, b: (process_status, {'exit_code': 0, 'stdout': '42\n', 'stderr': ''}),
                ('DELETE', '/v1/sandboxes/sbx-1'): lambda h, b: (200, {})}

    def test_run_code_needs_a_different_approver(self):
        calls = self.configure('keep', self.keep_routes())
        agent = self.app.create(self.devp, 'agents', {'name': 'Coder', 'model': self.model, 'tools': ['run_code']})
        self.scripted('run_code', {'language': 'python', 'code': 'print(6*7)'})
        job = self.app.new_job(self.devp, 'agent', agent['id'], {'message': 'compute'})
        self.app.process_job(self.devp, job['id'])
        self.assertEqual(self.app.get(self.devp, 'jobs', job['id'])['status'], 'waiting_approval')
        self.assertEqual(calls, [])
        approval = self.app.list(self.p, 'approvals')[0]
        self.assertEqual(approval['action']['preview'], 'print(6*7)')
        with self.assertRaises(Fault):
            self.app.decide(self.devp, approval['id'], 'approved', approval['digest'])
        self.app.decide(self.p, approval['id'], 'approved', approval['digest'])
        self.app.process_job(self.devp, job['id'])
        job = self.app.get(self.devp, 'jobs', job['id'])
        self.assertEqual(job['status'], 'completed')
        self.assertEqual([(c['method'], c['path']) for c in calls], [('POST', '/v1/sandboxes'), ('POST', '/v1/sandboxes/sbx-1/fs/write'),
                                                                     ('POST', '/v1/sandboxes/sbx-1/process'), ('DELETE', '/v1/sandboxes/sbx-1')])
        self.assertEqual(calls[0]['body']['network'], 'none')
        self.assertEqual(calls[1]['body'], {'path': '/work/main.py', 'content': 'print(6*7)'})
        approved = next(t for t in job['trace'] if t['type'] == 'approved_action')
        self.assertEqual(approved['result']['stdout'], '42\n')

    def test_sandbox_is_deleted_when_the_process_fails(self):
        calls = self.configure('keep', self.keep_routes(process_status=500))
        with self.assertRaises(Fault):
            self.app.integrations.run_code('bash', 'echo hi', self.app.policy(self.p))
        self.assertEqual(calls[-1]['method'], 'DELETE')

    def handoff_workflow(self, status_box):
        calls = self.configure('zyntra', {
            ('POST', '/api/v1/proposals'): lambda h, b: (201, {'id': 'prop-7', 'status': 'pending'}),
            ('GET', '/api/v1/proposals/prop-7'): lambda h, b: (200, {'id': 'prop-7', **status_box}),
        })
        wf = self.app.create(self.devp, 'workflows', {'name': 'Change', 'steps': [
            {'id': 'draft', 'type': 'template', 'template': 'Restart {{input}}'},
            {'id': 'decide', 'type': 'handoff', 'action': 'restart_service', 'scenario': 'maintenance', 'inputs': {'summary': '{{draft}}', 'priority': 2}, 'depends_on': ['draft']},
            {'id': 'report', 'type': 'template', 'template': 'Zyntra said {{decide}}', 'depends_on': ['decide']}]})
        job = self.app.new_job(self.devp, 'workflow', wf['id'], {'text': 'billing-api'})
        self.app.process_job(self.devp, job['id'])
        return calls, job['id']

    def test_handoff_waits_for_zyntra_decision(self):
        box = {'status': 'pending'}
        calls, jid = self.handoff_workflow(box)
        job = self.app.get(self.devp, 'jobs', jid)
        self.assertEqual(job['status'], 'waiting_external')
        self.assertEqual(calls[0]['body'], {'action': 'restart_service', 'scenario': 'maintenance', 'inputs': {'summary': 'Restart billing-api', 'priority': 2}})
        self.app.poll_external()
        self.assertEqual(self.app.get(self.devp, 'jobs', jid)['status'], 'waiting_external')
        box.update(status='approved', result={'ticket': 'CHG-1'}, decided_by='ops-lead')
        self.app.poll_external()
        self.assertEqual(self.app.get(self.devp, 'jobs', jid)['status'], 'queued')
        self.app.process_job(self.devp, jid)
        job = self.app.get(self.devp, 'jobs', jid)
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['result']['decide']['result'], {'ticket': 'CHG-1'})
        self.assertIn('CHG-1', job['result']['report'])
        self.assertIn('handoff.approved', [e['action'] for e in self.app.store.events('a')])

    def test_handoff_rejection_and_timeout(self):
        box = {'status': 'rejected'}
        _, jid = self.handoff_workflow(box)
        self.app.poll_external()
        job = self.app.get(self.devp, 'jobs', jid)
        self.assertEqual((job['status'], job['error']), ('rejected', 'Zyntra proposal rejected'))
        box['status'] = 'pending'
        _, jid = self.handoff_workflow(box)
        job = self.app.get(self.devp, 'jobs', jid)
        job['checkpoint']['external']['deadline'] = time.time()-1
        self.app.store.put('a', 'jobs', job, jid)
        self.app.poll_external()
        self.assertEqual(self.app.get(self.devp, 'jobs', jid)['status'], 'failed')

    def test_handoff_needs_zyntra(self):
        with self.assertRaises(Fault) as ctx:
            self.app.create(self.devp, 'workflows', {'name': 'x', 'steps': [{'id': 'h', 'type': 'handoff', 'action': 'a'}]})
        self.assertEqual(ctx.exception.status, 409)

    def test_model_discovery_and_presets(self):
        url, calls = self.stub({('GET', '/v1/models'): lambda h, b: (200, {'data': [{'id': 'llama-3.1-70b', 'owned_by': 'gryvia'}, {'id': 'bge-m3'}]}),
                                ('GET', '/api/tags'): lambda h, b: (200, {'models': [{'name': 'qwen2.5:7b'}, {'name': 'nomic-embed-text'}]})})
        found = self.json('/api/models/discover', {'provider': 'openai', 'base_url': url+'/v1'}, expect=200)['models']
        self.assertEqual([(m['id'], m['capability']) for m in found], [('llama-3.1-70b', 'chat'), ('bge-m3', 'embedding')])
        found = self.json('/api/models/discover', {'provider': 'ollama', 'base_url': url}, expect=200)['models']
        self.assertEqual([m['capability'] for m in found], ['chat', 'embedding'])
        self.json('/api/models/discover', {'provider': 'openai', 'base_url': 'https://not-allowed.example/v1'}, expect=403)
        self.json('/api/models/discover', {'provider': 'openai', 'base_url': url+'/v1', 'key_env': 'HOME'}, expect=400)
        self.json('/api/models/discover', {'provider': 'openai', 'base_url': url+'/v1'}, token=self.dev, expect=403)
        presets = {p['id'] for p in self.json('/api/models/presets')['presets']}
        self.assertTrue({'fabric', 'gryvia'} <= presets)

    def test_connection_check(self):
        self.configure('netra', {('GET', '/api/v1/status'): lambda h, b: (200, {'ok': True})})
        self.assertTrue(self.json('/api/integrations/netra/test', {}, expect=200)['ok'])
        self.json('/api/integrations/zyntra/test', {}, expect=503)
        self.json('/api/integrations/nope/test', {}, expect=404)
