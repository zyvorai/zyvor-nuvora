# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""bedrock-agent-runtime (Retrieve, RetrieveAndGenerate, InvokeAgent) through the real AWS SDK
against a live server and the offline demo provider. Skipped when boto3/botocore are not installed."""
import os
import unittest
from unittest import mock

from harness import LiveServer

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
    HAVE = True
except ImportError:
    HAVE = False


@unittest.skipUnless(HAVE, 'boto3/botocore not installed')
class AgentRuntime(LiveServer):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {'NUVORA_SECRET_KEY': 'k' * 40})
        self.env.start()
        super().setUp()
        self.auth.add_user('a', 'dev2', self.password, 'developer')
        self.json('/api/users/dev', {'groups': ['finance']}, expect=200)
        self.kb = self.json('/api/knowledge', {'name': 'Policies'}, expect=201)['id']
        self.demo = next(m['id'] for m in self.app.list(self.p, 'models') if m['name'] == 'Offline demo')
        for n in range(7):
            self.json(f'/api/knowledge/{self.kb}/ingest', {'name': f'refund-{n}', 'text': f'refund policy number {n} covers returns within thirty days', 'metadata': {'team': 'support' if n % 2 else 'sales', 'tier': n}}, expect=201)
        self.json(f'/api/knowledge/{self.kb}/ingest', {'name': 'payroll', 'text': 'refund of salary advances is handled by finance', 'groups': ['finance']}, expect=201)
        self.dev_cred = self.credential('dev')
        self.dev2_cred = self.credential('dev2')
        self.view_cred = self.credential('viewer', 'viewer')
        self.agent = next(a for a in self.app.list(self.p, 'agents'))

    def tearDown(self):
        super().tearDown()
        self.env.stop()

    def credential(self, user, role='developer'):
        return self.json('/api/aws-credentials', {'role': role, 'username': user}, expect=201)

    def client(self, cred=None):
        cred = cred or self.dev_cred
        return boto3.client('bedrock-agent-runtime', endpoint_url=self.url, region_name='us-east-1', aws_access_key_id=cred['access_key_id'],
                            aws_secret_access_key=cred['secret_access_key'], config=Config(retries={'max_attempts': 1}))

    def code(self, call, **kw):
        with self.assertRaises(ClientError) as ctx:
            call(**kw)
        e = ctx.exception.response
        return e['Error']['Code'], e['ResponseMetadata']['HTTPStatusCode'], e['Error'].get('Message', '')

    def cfg(self, **vector):
        return {'vectorSearchConfiguration': vector}

    # ---- Retrieve -----------------------------------------------------------------------

    def test_retrieve_pages_with_next_token(self):
        client = self.client()
        seen, token = [], None
        for _ in range(10):
            out = client.retrieve(knowledgeBaseId=self.kb, retrievalQuery={'text': 'refund policy'}, retrievalConfiguration=self.cfg(numberOfResults=3),
                                  **({'nextToken': token} if token else {}))
            self.assertLessEqual(len(out['retrievalResults']), 3)
            seen += out['retrievalResults']
            token = out.get('nextToken')
            if not token:
                break
        self.assertGreaterEqual(len(seen), 7)
        ids = [r['metadata']['x-amz-bedrock-kb-chunk-id'] for r in seen]
        self.assertEqual(len(ids), len(set(ids)))
        first = seen[0]
        self.assertEqual(first['content']['type'], 'TEXT')
        self.assertIn('refund', first['content']['text'])
        self.assertEqual(first['location']['type'], 'CUSTOM')
        self.assertIsInstance(first['score'], float)
        # a token belongs to its query
        page = client.retrieve(knowledgeBaseId=self.kb, retrievalQuery={'text': 'refund policy'}, retrievalConfiguration=self.cfg(numberOfResults=2))
        code, status, message = self.code(client.retrieve, knowledgeBaseId=self.kb, retrievalQuery={'text': 'something else'}, nextToken=page['nextToken'])
        self.assertEqual((code, status), ('ValidationException', 400))
        self.assertEqual(self.code(client.retrieve, knowledgeBaseId=self.kb, retrievalQuery={'text': 'x'}, nextToken='!!')[0], 'ValidationException')

    def test_retrieve_filters(self):
        client = self.client()

        def teams(**vector):
            out = client.retrieve(knowledgeBaseId=self.kb, retrievalQuery={'text': 'refund policy'}, retrievalConfiguration=self.cfg(numberOfResults=20, **vector))
            return [r['metadata'] for r in out['retrievalResults']]
        only = teams(filter={'equals': {'key': 'team', 'value': 'support'}})
        self.assertEqual(len(only), 3)
        self.assertTrue(all(m['team'] == 'support' for m in only))
        both = teams(filter={'andAll': [{'equals': {'key': 'team', 'value': 'sales'}}, {'in': {'key': 'tier', 'value': [0, 2]}}]})
        self.assertEqual(sorted(m['tier'] for m in both), [0, 2])
        # unmappable operators are refused by name
        for op, spec in (('orAll', {'orAll': [{'equals': {'key': 'team', 'value': 'a'}}, {'equals': {'key': 'team', 'value': 'b'}}]}),
                         ('notEquals', {'notEquals': {'key': 'team', 'value': 'a'}}), ('greaterThan', {'greaterThan': {'key': 'tier', 'value': 1}}),
                         ('startsWith', {'startsWith': {'key': 'team', 'value': 's'}}), ('stringContains', {'stringContains': {'key': 'team', 'value': 's'}})):
            code, status, message = self.code(client.retrieve, knowledgeBaseId=self.kb, retrievalQuery={'text': 'refund'}, retrievalConfiguration=self.cfg(filter=spec))
            self.assertEqual((code, status), ('ValidationException', 400))
            self.assertIn(op, message)
        code, _, message = self.code(client.retrieve, knowledgeBaseId=self.kb, retrievalQuery={'text': 'refund'}, retrievalConfiguration=self.cfg(
            filter={'andAll': [{'equals': {'key': 'team', 'value': 'a'}}, {'in': {'key': 'team', 'value': ['b']}}]}))
        self.assertEqual(code, 'ValidationException')
        self.assertIn('team', message)

    def test_retrieve_refuses_unsupported_members_and_unknown_base(self):
        client = self.client()
        for kw, name in (({'guardrailConfiguration': {'guardrailId': 'g', 'guardrailVersion': '1'}}, 'guardrailConfiguration'),
                         ({'retrievalConfiguration': self.cfg(rerankingConfiguration={'type': 'BEDROCK_RERANKING_MODEL'})}, 'rerankingConfiguration'),
                         ({'retrievalConfiguration': self.cfg(numberOfResults=50)}, 'numberOfResults'),
                         ({'retrievalConfiguration': self.cfg(overrideSearchType='SEMANTIC')}, 'overrideSearchType')):
            code, status, message = self.code(client.retrieve, knowledgeBaseId=self.kb, retrievalQuery={'text': 'refund'}, **kw)
            self.assertEqual((code, status), ('ValidationException', 400), kw)
            self.assertIn(name, message)
        code, status, _ = self.code(client.retrieve, knowledgeBaseId='NOSUCHKB123', retrievalQuery={'text': 'refund'})
        self.assertEqual((code, status), ('ResourceNotFoundException', 404))

    def test_roles_and_group_access(self):
        code, status, _ = self.code(self.client(self.view_cred).retrieve, knowledgeBaseId=self.kb, retrievalQuery={'text': 'refund'})
        self.assertEqual((code, status), ('AccessDeniedException', 403))
        for cred, expect in ((self.dev_cred, True), (self.dev2_cred, False)):
            out = self.client(cred).retrieve(knowledgeBaseId=self.kb, retrievalQuery={'text': 'salary advances finance'})
            self.assertEqual(any('salary advances' in r['content']['text'] for r in out['retrievalResults']), expect)
        # the same filtering applies to generated answers and their citations
        for cred, expect in ((self.dev_cred, True), (self.dev2_cred, False)):
            out = self.client(cred).retrieve_and_generate(input={'text': 'salary advances finance'}, retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE', 'knowledgeBaseConfiguration': {'knowledgeBaseId': self.kb, 'modelArn': self.demo}})
            seen = [ref['content']['text'] for c in out['citations'] for ref in c['retrievedReferences']]
            self.assertEqual(any('salary advances' in t for t in seen), expect)

    # ---- RetrieveAndGenerate ------------------------------------------------------------

    def rag(self, client=None, **overrides):
        config = {'type': 'KNOWLEDGE_BASE', 'knowledgeBaseConfiguration': {'knowledgeBaseId': self.kb, 'modelArn': self.demo, **overrides}}
        return (client or self.client()).retrieve_and_generate(input={'text': 'what is the refund policy'}, retrieveAndGenerateConfiguration=config)

    def test_retrieve_and_generate_with_citations_and_session(self):
        out = self.rag(retrievalConfiguration=self.cfg(numberOfResults=2, filter={'equals': {'key': 'team', 'value': 'support'}}))
        self.assertTrue(out['output']['text'])
        self.assertTrue(out['sessionId'])
        (citation,) = out['citations']
        text = citation['generatedResponsePart']['textResponsePart']
        self.assertEqual(text['text'], out['output']['text'])
        self.assertEqual(text['span'], {'start': 0, 'end': len(text['text']) - 1})
        refs = citation['retrievedReferences']
        self.assertEqual(len(refs), 2)
        self.assertTrue(all(r['metadata']['team'] == 'support' for r in refs))
        # the session id is opaque and echoed
        again = self.client().retrieve_and_generate(sessionId='my-session-1', input={'text': 'refund'}, retrieveAndGenerateConfiguration={
            'type': 'KNOWLEDGE_BASE', 'knowledgeBaseConfiguration': {'knowledgeBaseId': self.kb, 'modelArn': self.demo}})
        self.assertEqual(again['sessionId'], 'my-session-1')

    def test_retrieve_and_generate_without_evidence(self):
        out = self.client().retrieve_and_generate(input={'text': 'zzzqqq'}, retrieveAndGenerateConfiguration={
            'type': 'KNOWLEDGE_BASE', 'knowledgeBaseConfiguration': {'knowledgeBaseId': self.kb, 'modelArn': self.demo}})
        self.assertEqual(out['output']['text'], 'No relevant evidence found.')
        self.assertEqual(out['citations'], [])

    def test_retrieve_and_generate_refusals(self):
        client = self.client()
        code, status, message = self.code(client.retrieve_and_generate, input={'text': 'q'}, retrieveAndGenerateConfiguration={
            'type': 'EXTERNAL_SOURCES', 'externalSourcesConfiguration': {'modelArn': self.demo, 'sources': [{'sourceType': 'S3', 's3Location': {'uri': 's3://b/k'}}]}})
        self.assertEqual((code, status), ('ValidationException', 400))
        self.assertIn('EXTERNAL_SOURCES', message)
        for member, name in (({'orchestrationConfiguration': {'queryTransformationConfiguration': {'type': 'QUERY_DECOMPOSITION'}}}, 'orchestrationConfiguration'),
                             ({'generationConfiguration': {'inferenceConfig': {'textInferenceConfig': {'temperature': 0.1}}}}, 'inferenceConfig')):
            code, _, message = self.code(self.rag, **member)
            self.assertEqual(code, 'ValidationException')
            self.assertIn(name, message)
        code, _, message = self.code(client.retrieve_and_generate, input={'text': 'q'}, sessionConfiguration={'kmsKeyArn': 'arn:aws:kms:us-east-1:1:key/x'},
                                     retrieveAndGenerateConfiguration={'type': 'KNOWLEDGE_BASE', 'knowledgeBaseConfiguration': {'knowledgeBaseId': self.kb, 'modelArn': self.demo}})
        self.assertIn('sessionConfiguration', message)
        self.assertEqual(self.code(self.rag, modelArn='no-such-model')[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.code(self.rag, knowledgeBaseId='NOSUCHKB123')[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.code(lambda: self.rag(self.client(self.view_cred)))[0], 'AccessDeniedException')

    def test_retrieve_and_generate_with_guardrail_and_model_arn(self):
        blocked = self.json('/api/guardrails', {'name': 'g', 'output': {'blocked_topics': ['refund']}, 'blocked_output_message': 'Sorry, blocked.'}, expect=201)
        out = self.rag(modelArn='arn:aws:bedrock:us-east-1::foundation-model/' + self.demo, generationConfiguration={
            'guardrailConfiguration': {'guardrailId': blocked['id'], 'guardrailVersion': 'DRAFT'}})
        self.assertEqual(out['guardrailAction'], 'INTERVENED')
        self.assertEqual(out['output']['text'], 'Sorry, blocked.')

    # ---- InvokeAgent --------------------------------------------------------------------

    def invoke(self, client=None, **kw):
        out = (client or self.client()).invoke_agent(agentId=self.agent['id'], agentAliasId=kw.pop('agentAliasId', 'TSTALIASID'), sessionId=kw.pop('sessionId', 'session-1'),
                                                     inputText=kw.pop('inputText', 'Keep'), **kw)
        chunks, traces = [], []
        for event in out['completion']:
            if 'chunk' in event:
                chunks.append(event['chunk']['bytes'].decode())
            elif 'trace' in event:
                traces.append(event['trace'])
        return out, ''.join(chunks), traces

    def test_invoke_agent_streams_completion(self):
        out, text, traces = self.invoke()
        self.assertTrue(text)
        self.assertEqual(out['sessionId'], 'session-1')
        self.assertTrue(out['contentType'].startswith('text/plain'))
        self.assertEqual(traces, [])
        job = max((j for j in self.app.list(self.p, 'jobs') if j['type'] == 'agent'), key=lambda j: j['created'])
        self.assertEqual(job['result']['answer'], text)
        self.assertEqual(job['input']['session'], 'session-1')

    def test_invoke_agent_trace_and_any_alias(self):
        out, text, traces = self.invoke(agentAliasId='PRODALIAS1', enableTrace=True)
        self.assertTrue(text)
        self.assertTrue(traces)
        kinds = [list(t['trace']['orchestrationTrace'])[0] for t in traces]
        self.assertIn('modelInvocationInput', kinds)
        self.assertIn('invocationInput', kinds)
        last = traces[-1]['trace']['orchestrationTrace']['observation']
        self.assertEqual((last['type'], last['finalResponse']['text']), ('FINISH', text))
        self.assertEqual(traces[0]['agentId'], self.agent['id'])
        self.assertEqual(traces[0]['agentAliasId'], 'PRODALIAS1')
        kb = next(t for t in traces if t['trace']['orchestrationTrace'].get('observation', {}).get('type') == 'KNOWLEDGE_BASE')
        self.assertTrue(kb['trace']['orchestrationTrace']['observation']['knowledgeBaseLookupOutput']['retrievedReferences'])

    def test_invoke_agent_refusals_and_errors(self):
        client = self.client()
        for kw, name in (({'memoryId': 'm1'}, 'memoryId'), ({'sessionState': {'sessionAttributes': {'a': 'b'}}}, 'sessionState'),
                         ({'streamingConfigurations': {'streamFinalResponse': True}}, 'streamingConfigurations'),
                         ({'bedrockModelConfigurations': {'performanceConfig': {'latency': 'optimized'}}}, 'bedrockModelConfigurations')):
            code, status, message = self.code(self.invoke, **kw)
            self.assertEqual((code, status), ('ValidationException', 400), kw)
            self.assertIn(name, message)
        self.assertEqual(self.code(client.invoke_agent, agentId='NOSUCHAGENT', agentAliasId='TSTALIASID', sessionId='s1', inputText='x')[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.code(client.invoke_agent, agentId=self.agent['id'], agentAliasId='TSTALIASID', sessionId='s1', inputText=' ')[0], 'ValidationException')
        self.assertEqual(self.code(lambda: self.invoke(self.client(self.view_cred)))[:2], ('AccessDeniedException', 403))

    def test_invoke_agent_timeout(self):
        with mock.patch.dict(os.environ, {'NUVORA_BEDROCK_AGENT_WAIT_SECONDS': '1'}), mock.patch.object(self.app, 'process_job', side_effect=lambda *a: __import__('time').sleep(3)):
            code, status, message = self.code(self.invoke)
        self.assertEqual((code, status), ('ModelTimeoutException', 408))
        self.assertIn('/api/jobs/', message)

    def test_invoke_agent_blocked_on_approval_is_an_honest_error(self):
        writer = self.app.create(self.p, 'agents', {'name': 'Writer', 'model': self.demo, 'tools': ['memory_write'], 'knowledge_ids': [], 'max_steps': 5})
        original = self.app.providers.chat

        def scripted(model, messages, tools, maximum, temp):
            if not any(m['role'] == 'tool' for m in messages):
                return {'content': '', 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'memory_write', 'arguments': '{"text":"remember"}'}}], 'usage': {}, 'evidence_class': 'scripted'}
            return {'content': 'Saved', 'tool_calls': [], 'usage': {}, 'evidence_class': 'scripted'}
        self.app.providers.chat = scripted
        try:
            code, status, message = self.code(self.client().invoke_agent, agentId=writer['id'], agentAliasId='TSTALIASID', sessionId='s-approval', inputText='remember this')
        finally:
            self.app.providers.chat = original
        self.assertEqual((code, status), ('ConflictException', 409))
        self.assertIn('waiting for approval', message)
        job = next(j for j in self.app.list(self.p, 'jobs') if j['target'] == writer['id'])
        self.assertEqual(job['status'], 'waiting_approval')
        self.assertEqual(self.app.list(self.p, 'memory'), [])

    def test_agent_memory_operations_are_refused(self):
        client = self.client()
        code, status, message = self.code(client.get_agent_memory, agentId=self.agent['id'], agentAliasId='TSTALIASID', memoryId='m1', memoryType='SESSION_SUMMARY')
        self.assertEqual((code, status), ('UnsupportedOperationException', 501))
        self.assertIn('GetAgentMemory', message)
        self.assertEqual(self.code(client.delete_agent_memory, agentId=self.agent['id'], agentAliasId='TSTALIASID')[0], 'UnsupportedOperationException')


if __name__ == '__main__':
    unittest.main()
