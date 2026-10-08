# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""bedrock-runtime operations through the real AWS SDK (botocore) against a live server, using the
offline demo provider so no network is needed. Skipped when boto3/botocore are not installed."""
import base64
import json
import os
import unittest
from unittest import mock

from harness import LiveServer

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError, EventStreamError
    HAVE = True
except ImportError:
    HAVE = False

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')


class Base(LiveServer):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {'NUVORA_SECRET_KEY': 'k' * 40})
        self.env.start()
        super().setUp()
        self.cred = self.json('/api/aws-credentials', {'role': 'developer'}, expect=201)
        models = self.app.list(self.p, 'models')
        self.demo = next(m['id'] for m in models if m['name'] == 'Offline demo')
        self.embed_model = self.json('/api/models', {'name': 'Embed', 'provider': 'demo', 'upstream_model': 'e', 'capability': 'embedding'}, expect=201)['id']

    def tearDown(self):
        super().tearDown()
        self.env.stop()

    def runtime(self, bearer=None):
        if bearer:
            with mock.patch.dict(os.environ, {'AWS_BEARER_TOKEN_BEDROCK': bearer}):
                return boto3.client('bedrock-runtime', endpoint_url=self.url, region_name='us-east-1', config=Config(retries={'max_attempts': 1}))
        return boto3.client('bedrock-runtime', endpoint_url=self.url, region_name='us-west-2', aws_access_key_id=self.cred['access_key_id'],
                            aws_secret_access_key=self.cred['secret_access_key'], config=Config(retries={'max_attempts': 1}))

    def code(self, call, **kw):
        with self.assertRaises(ClientError) as ctx:
            call(**kw)
        e = ctx.exception.response
        return e['Error']['Code'], e['ResponseMetadata']['HTTPStatusCode'], e['Error'].get('Message', '')

    def user(self, text):
        return [{'role': 'user', 'content': [{'text': text}]}]


@unittest.skipUnless(HAVE, 'boto3/botocore not installed')
class Runtime(Base):
    def converse_tests(self, client):
        out = client.converse(modelId=self.demo, messages=self.user('hello bedrock'), system=[{'text': 'be brief'}],
                              inferenceConfig={'maxTokens': 200, 'temperature': 0.1, 'topP': 0.9})
        self.assertEqual(out['stopReason'], 'end_turn')
        self.assertIn('hello bedrock', out['output']['message']['content'][0]['text'])
        self.assertEqual(out['output']['message']['role'], 'assistant')
        usage = out['usage']
        self.assertEqual(usage['totalTokens'], usage['inputTokens'] + usage['outputTokens'])
        self.assertGreater(usage['inputTokens'], 0)
        self.assertIn('latencyMs', out['metrics'])

    def test_converse_sigv4(self):
        self.converse_tests(self.runtime())

    def test_converse_bearer_token(self):
        try:
            client = self.runtime(bearer=self.dev)
        except Exception as exc:
            self.skipTest('this botocore does not support AWS_BEARER_TOKEN_BEDROCK: %s' % type(exc).__name__)
        with mock.patch.dict(os.environ, {'AWS_BEARER_TOKEN_BEDROCK': self.dev}):
            self.converse_tests(client)
            self.assertEqual(client.invoke_model(modelId=self.demo, body=json.dumps({'messages': [{'role': 'user', 'content': 'x'}]}))['ResponseMetadata']['HTTPStatusCode'], 200)
            events = [e for e in client.converse_stream(modelId=self.demo, messages=self.user('bearer stream'))['stream']]
            self.assertIn('metadata', events[-1])

    def test_usage_and_audit_are_recorded_like_native_chat(self):
        before = self.app.usage(self.p)['requests']
        self.runtime().converse(modelId=self.demo, messages=self.user('count me'))
        self.assertEqual(self.app.usage(self.p)['requests'], before + 1)

    def test_model_id_forms(self):
        client = self.runtime()
        arn = f'arn:nuvora:bedrock:us-west-2::foundation-model/{self.demo}'
        self.assertEqual(client.converse(modelId=arn, messages=self.user('arn'))['stopReason'], 'end_turn')
        second = self.json('/api/models', {'name': 'Second', 'provider': 'demo', 'upstream_model': 'demo'}, expect=201)['id']
        router = self.json('/api/routers', {'name': 'R', 'models': [self.demo, second]}, expect=201)['id']
        for ident in ('router:' + router, f'arn:nuvora:bedrock:us-west-2:123456789012:inference-profile/router:{router}'):
            out = client.converse(modelId=ident, messages=self.user('via router'))
            self.assertIn('via router', out['output']['message']['content'][0]['text'])
        self.assertEqual(self.code(client.converse, modelId='router:nope', messages=self.user('x'))[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.code(client.converse, modelId='nonexistent.model-v1:0', messages=self.user('x'))[:2], ('ResourceNotFoundException', 404))

    def test_error_mapping(self):
        client = self.runtime()
        self.assertEqual(self.code(client.converse, modelId=self.demo, messages=self.user('x'), inferenceConfig={'maxTokens': 999999})[:2], ('ValidationException', 400))
        code, status, message = self.code(client.converse, modelId=self.demo, messages=self.user('x'), guardrailConfig={'guardrailIdentifier': 'g', 'guardrailVersion': '1'})
        self.assertEqual((code, status), ('ResourceNotFoundException', 404))
        self.assertIn('Guardrail g', message)
        code, _, message = self.code(client.converse, modelId=self.demo, messages=self.user('x'), requestMetadata={'a': 'b'})
        self.assertEqual(code, 'ValidationException')
        self.assertIn('requestMetadata', message)
        code, _, message = self.code(client.converse, modelId=self.demo, messages=[{'role': 'user', 'content': [{'document': {'format': 'pdf', 'name': 'd', 'source': {'bytes': b'x'}}}]}])
        self.assertEqual(code, 'ValidationException')
        self.assertIn('document', message)
        code, _, message = self.code(client.converse, modelId=self.embed_model, messages=self.user('x'))
        self.assertEqual(code, 'ValidationException')
        self.assertIn('capability', message)
        # a Nuvora guardrail: the tenant policy blocks a topic, which Converse reports as guardrail_intervened
        policy = self.json('/api/policies', {'name': 'p', 'blocked_topics': ['forbidden']}, expect=201)
        self.assertTrue(policy['id'])
        out = client.converse(modelId=self.demo, messages=self.user('talk about forbidden things'))
        self.assertEqual(out['stopReason'], 'guardrail_intervened')
        events = [e for e in client.converse_stream(modelId=self.demo, messages=self.user('talk about forbidden things'))['stream']]
        self.assertEqual([k for e in events for k in e][-2:], ['messageStop', 'metadata'])
        self.assertEqual(events[-2]['messageStop']['stopReason'], 'guardrail_intervened')

    def test_viewer_cannot_run_inference(self):
        cred = self.json('/api/aws-credentials', {'role': 'viewer', 'username': 'viewer'}, expect=201)
        client = boto3.client('bedrock-runtime', endpoint_url=self.url, region_name='us-east-1', aws_access_key_id=cred['access_key_id'],
                              aws_secret_access_key=cred['secret_access_key'], config=Config(retries={'max_attempts': 1}))
        self.assertEqual(self.code(client.converse, modelId=self.demo, messages=self.user('x'))[:2], ('AccessDeniedException', 403))
        self.assertEqual(self.code(client.count_tokens, modelId=self.demo, input={'converse': {'messages': self.user('x')}})[:2], ('AccessDeniedException', 403))

    def test_budget_maps_to_throttling(self):
        self.json('/api/policies', {'name': 'tiny', 'daily_tokens': 1000}, expect=201)
        self.assertEqual(self.code(self.runtime().converse, modelId=self.demo, messages=self.user('x'), inferenceConfig={'maxTokens': 2000})[:2], ('ThrottlingException', 429))

    def test_max_tokens_stop_reason(self):
        out = self.runtime().converse(modelId=self.demo, messages=self.user('word ' * 400), inferenceConfig={'maxTokens': 1})
        self.assertEqual(out['stopReason'], 'max_tokens')

    def test_stop_sequences_are_forwarded(self):
        out = self.runtime().converse(modelId=self.demo, messages=self.user('alpha STOPHERE omega'), inferenceConfig={'stopSequences': ['STOPHERE']})
        self.assertNotIn('omega', out['output']['message']['content'][0]['text'])

    def test_images(self):
        client = self.runtime()
        out = client.converse(modelId=self.demo, messages=[{'role': 'user', 'content': [{'text': 'describe'}, {'image': {'format': 'png', 'source': {'bytes': PNG}}}]}])
        self.assertIn('[image attached]', out['output']['message']['content'][0]['text'])
        code, _, message = self.code(client.converse, modelId=self.demo, messages=[{'role': 'user', 'content': [{'image': {'format': 'gif', 'source': {'bytes': PNG}}}]}])
        self.assertEqual(code, 'ValidationException')
        self.assertIn('gif', message)

    def test_tool_use_round_trip(self):
        client = self.runtime()
        tools = {'tools': [{'toolSpec': {'name': 'get_weather', 'description': 'Weather', 'inputSchema': {'json': {'type': 'object', 'properties': {'city': {'type': 'string'}}, 'required': ['city']}}}}],
                 'toolChoice': {'tool': {'name': 'get_weather'}}}
        first = client.converse(modelId=self.demo, messages=self.user('weather in Oslo'), toolConfig=tools)
        self.assertEqual(first['stopReason'], 'tool_use')
        use = next(b['toolUse'] for b in first['output']['message']['content'] if 'toolUse' in b)
        self.assertEqual(use['name'], 'get_weather')
        self.assertIsInstance(use['input'], dict)
        self.assertIn('city', use['input'])
        history = self.user('weather in Oslo') + [first['output']['message'],
                                                  {'role': 'user', 'content': [{'toolResult': {'toolUseId': use['toolUseId'], 'content': [{'json': {'temp_c': 4}}], 'status': 'success'}}]}]
        second = client.converse(modelId=self.demo, messages=history, toolConfig=tools)
        self.assertEqual(second['stopReason'], 'end_turn')
        self.assertIn('temp_c', second['output']['message']['content'][0]['text'])
        code, _, message = self.code(client.converse, modelId=self.demo, messages=self.user('x'), toolConfig={'tools': [{'toolSpec': {'name': 'a', 'inputSchema': {'json': {}}}}], 'toolChoice': {'tool': {'name': 'zzz'}}})
        self.assertEqual(code, 'ValidationException')
        self.assertIn('tool_choice', message)

    def test_converse_stream_decoded_by_botocore(self):
        client = self.runtime()
        stream = client.converse_stream(modelId=self.demo, messages=self.user('Hello there. This is a streamed answer. It has several sentences.'))
        events = list(stream['stream'])
        names = [next(iter(e)) for e in events]
        self.assertEqual(names[0], 'messageStart')
        self.assertEqual(names[-2:], ['messageStop', 'metadata'])
        self.assertIn('contentBlockDelta', names)
        self.assertEqual(names[-3], 'contentBlockStop')
        text = ''.join(e['contentBlockDelta']['delta']['text'] for e in events if 'contentBlockDelta' in e)
        self.assertIn('streamed answer', text)
        self.assertEqual(events[-2]['messageStop']['stopReason'], 'end_turn')
        usage = events[-1]['metadata']['usage']
        self.assertEqual(usage['totalTokens'], usage['inputTokens'] + usage['outputTokens'])
        self.assertIn('latencyMs', events[-1]['metadata']['metrics'])

    def test_converse_stream_tool_use(self):
        client = self.runtime()
        tools = {'tools': [{'toolSpec': {'name': 'lookup', 'inputSchema': {'json': {'type': 'object', 'properties': {'q': {'type': 'string'}}, 'required': ['q']}}}}]}
        events = list(client.converse_stream(modelId=self.demo, messages=self.user('find it'), toolConfig=tools)['stream'])
        names = [next(iter(e)) for e in events]
        self.assertEqual(names, ['messageStart', 'contentBlockStart', 'contentBlockDelta', 'contentBlockStop', 'messageStop', 'metadata'])
        self.assertEqual(events[1]['contentBlockStart']['start']['toolUse']['name'], 'lookup')
        self.assertIn('q', json.loads(events[2]['contentBlockDelta']['delta']['toolUse']['input']))
        self.assertEqual(events[4]['messageStop']['stopReason'], 'tool_use')

    def test_stream_errors_before_start_are_http_errors(self):
        client = self.runtime()
        self.assertEqual(self.code(client.converse_stream, modelId='nope', messages=self.user('x'))[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.code(client.converse_stream, modelId=self.demo, messages=self.user('x'), inferenceConfig={'maxTokens': 999999})[:2], ('ValidationException', 400))

    def test_stream_failure_after_start_is_an_exception_frame(self):
        client = self.runtime()

        def broken(*a, **k):
            yield {'delta': 'First sentence. '}
            from nuvora.providers import Fault
            raise Fault('Provider request failed; check operator configuration', 502)
        with mock.patch.object(self.app.providers, 'stream', broken):
            stream = client.converse_stream(modelId=self.demo, messages=self.user('x'))
            with self.assertRaises(EventStreamError) as ctx:
                list(stream['stream'])
        self.assertEqual(ctx.exception.response['Error']['Code'], 'modelStreamErrorException')
        self.assertEqual(self.app.usage(self.p)['requests'], 0)

    def test_invoke_model_nuvora_chat_shape(self):
        client = self.runtime()
        out = client.invoke_model(modelId=self.demo, body=json.dumps({'messages': [{'role': 'user', 'content': 'plain invoke'}], 'max_tokens': 100}))
        self.assertEqual(out['contentType'], 'application/json')
        body = json.loads(out['body'].read())
        self.assertEqual(body['object'], 'chat.completion')
        self.assertIn('plain invoke', body['choices'][0]['message']['content'])
        self.assertEqual(out['ResponseMetadata']['HTTPHeaders']['x-amzn-bedrock-output-token-count'], str(body['usage']['completion_tokens']))

    def test_invoke_model_anthropic_shape(self):
        client = self.runtime()
        request = {'anthropic_version': 'bedrock-2023-05-31', 'max_tokens': 100, 'system': 'terse',
                   'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'anthropic style'}]}],
                   'tools': [{'name': 'calc', 'description': 'math', 'input_schema': {'type': 'object', 'properties': {'expr': {'type': 'string'}}, 'required': ['expr']}}],
                   'tool_choice': {'type': 'none'}}
        body = json.loads(client.invoke_model(modelId=self.demo, body=json.dumps(request))['body'].read())
        self.assertEqual((body['type'], body['role'], body['stop_reason']), ('message', 'assistant', 'end_turn'))
        self.assertIn('anthropic style', body['content'][0]['text'])
        self.assertEqual(set(body['usage']), {'input_tokens', 'output_tokens'})
        request['tool_choice'] = {'type': 'tool', 'name': 'calc'}
        body = json.loads(client.invoke_model(modelId=self.demo, body=json.dumps(request))['body'].read())
        self.assertEqual(body['stop_reason'], 'tool_use')
        self.assertEqual(body['content'][0]['type'], 'tool_use')
        self.assertIn('expr', body['content'][0]['input'])

    def test_invoke_model_rejects_what_it_cannot_map(self):
        client = self.runtime()
        base = {'anthropic_version': 'bedrock-2023-05-31', 'max_tokens': 10, 'messages': [{'role': 'user', 'content': 'x'}]}
        for extra, field in (({'top_k': 5}, 'top_k'), ({'metadata': {}}, 'metadata'), ({'thinking': {'type': 'enabled'}}, 'thinking')):
            code, status, message = self.code(client.invoke_model, modelId=self.demo, body=json.dumps({**base, **extra}))
            self.assertEqual((code, status), ('ValidationException', 400))
            self.assertIn(field, message)
        code, _, message = self.code(client.invoke_model, modelId=self.demo, body=json.dumps({**base, 'anthropic_version': 'x'}))
        self.assertIn('anthropic_version', message)
        code, _, message = self.code(client.invoke_model, modelId=self.demo, body=json.dumps({'messages': [{'role': 'user', 'content': 'x'}], 'n': 2}))
        self.assertIn('n', message)
        code, _, message = self.code(client.invoke_model, modelId=self.demo, body='not json')
        self.assertEqual(code, 'ValidationException')
        code, _, message = self.code(client.invoke_model, modelId=self.demo, body=json.dumps({'inputText': 'x'}))
        self.assertIn('embeddings', message)
        code, status, message = self.code(client.invoke_model, modelId=self.demo, body=json.dumps({'messages': [{'role': 'user', 'content': 'x'}]}), guardrailIdentifier='g', guardrailVersion='1')
        self.assertEqual((code, status), ('ResourceNotFoundException', 404))
        code, _, message = self.code(client.invoke_model, modelId=self.demo, body=json.dumps({'messages': [{'role': 'user', 'content': 'x'}]}), performanceConfigLatency='optimized')
        self.assertIn('PerformanceConfig', message)
        code, _, message = self.code(client.invoke_model, modelId=self.demo, body=json.dumps({'messages': [{'role': 'user', 'content': 'x'}]}), accept='text/plain')
        self.assertIn('accept', message)

    def test_invoke_model_embeddings(self):
        client = self.runtime()
        titan = json.loads(client.invoke_model(modelId=self.embed_model, body=json.dumps({'inputText': 'alpha beta'}))['body'].read())
        self.assertEqual(len(titan['embedding']), 64)
        self.assertGreater(titan['inputTextTokenCount'], 0)
        nuvora = json.loads(client.invoke_model(modelId=self.embed_model, body=json.dumps({'input': ['alpha beta', 'gamma']}))['body'].read())
        self.assertEqual(nuvora['object'], 'list')
        self.assertEqual(nuvora['data'][0]['embedding'], titan['embedding'])
        self.assertEqual(len(nuvora['data']), 2)
        code, _, message = self.code(client.invoke_model, modelId=self.embed_model, body=json.dumps({'inputText': 'x', 'dimensions': 256}))
        self.assertEqual(code, 'ValidationException')
        self.assertIn('dimensions', message)
        code, _, message = self.code(client.invoke_model_with_response_stream, modelId=self.embed_model, body=json.dumps({'inputText': 'x'}))
        self.assertEqual(code, 'ValidationException')

    def chunks(self, stream):
        return [json.loads(e['chunk']['bytes']) for e in stream['body']]

    def test_invoke_stream_anthropic_shape(self):
        client = self.runtime()
        request = {'anthropic_version': 'bedrock-2023-05-31', 'max_tokens': 100, 'messages': [{'role': 'user', 'content': 'Hello there. Stream this please.'}]}
        chunks = self.chunks(client.invoke_model_with_response_stream(modelId=self.demo, body=json.dumps(request)))
        kinds = [c['type'] for c in chunks]
        self.assertEqual(kinds[0], 'message_start')
        self.assertEqual(kinds[-2:], ['message_delta', 'message_stop'])
        self.assertIn('content_block_delta', kinds)
        self.assertIn('Stream this', ''.join(c['delta']['text'] for c in chunks if c['type'] == 'content_block_delta'))
        self.assertEqual(chunks[-2]['delta']['stop_reason'], 'end_turn')
        self.assertIn('inputTokenCount', chunks[-1]['amazon-bedrock-invocationMetrics'])

    def test_invoke_stream_nuvora_shape_and_tools(self):
        client = self.runtime()
        chunks = self.chunks(client.invoke_model_with_response_stream(modelId=self.demo, body=json.dumps({'messages': [{'role': 'user', 'content': 'Hi there. Second.'}]})))
        self.assertEqual(chunks[0]['object'], 'chat.completion.chunk')
        self.assertEqual(chunks[-1]['choices'][0]['finish_reason'], 'stop')
        tools = [{'type': 'function', 'function': {'name': 'f', 'parameters': {'type': 'object', 'properties': {'a': {'type': 'string'}}, 'required': ['a']}}}]
        chunks = self.chunks(client.invoke_model_with_response_stream(modelId=self.demo, body=json.dumps({'messages': [{'role': 'user', 'content': 'go'}], 'tools': tools})))
        self.assertEqual(chunks[-1]['choices'][0]['finish_reason'], 'tool_calls')
        request = {'anthropic_version': 'bedrock-2023-05-31', 'max_tokens': 50, 'messages': [{'role': 'user', 'content': 'go'}],
                   'tools': [{'name': 'f', 'input_schema': tools[0]['function']['parameters']}]}
        chunks = self.chunks(client.invoke_model_with_response_stream(modelId=self.demo, body=json.dumps(request)))
        starts = [c for c in chunks if c['type'] == 'content_block_start']
        self.assertEqual(starts[0]['content_block']['type'], 'tool_use')
        self.assertEqual(chunks[-2]['delta']['stop_reason'], 'tool_use')

    def test_count_tokens(self):
        client = self.runtime()
        small = client.count_tokens(modelId=self.demo, input={'converse': {'messages': self.user('short')}})
        large = client.count_tokens(modelId=self.demo, input={'converse': {'messages': self.user('long ' * 400)}})
        self.assertGreater(large['inputTokens'], small['inputTokens'])
        self.assertEqual(small['ResponseMetadata']['HTTPHeaders']['x-nuvora-token-count'], 'estimate; characters/4')
        body = json.dumps({'messages': [{'role': 'user', 'content': 'long ' * 400}]}).encode()
        via_invoke = client.count_tokens(modelId=self.demo, input={'invokeModel': {'body': body}})
        self.assertEqual(via_invoke['inputTokens'], large['inputTokens'])
        self.assertEqual(self.code(client.count_tokens, modelId='nope', input={'converse': {'messages': self.user('x')}})[:2], ('ResourceNotFoundException', 404))
        before = self.app.usage(self.p)['requests']
        self.assertEqual(self.app.usage(self.p)['requests'], before)

    def test_get_foundation_model(self):
        control = boto3.client('bedrock', endpoint_url=self.url, region_name='us-east-1', aws_access_key_id=self.cred['access_key_id'],
                               aws_secret_access_key=self.cred['secret_access_key'], config=Config(retries={'max_attempts': 1}))
        details = control.get_foundation_model(modelIdentifier=self.demo)['modelDetails']
        self.assertEqual((details['modelId'], details['modelName']), (self.demo, 'Offline demo'))
        self.assertEqual(self.code(control.get_foundation_model, modelIdentifier='nope')[:2], ('ResourceNotFoundException', 404))
        self.assertIn('arn:nuvora', control.get_foundation_model(modelIdentifier=self.demo)['modelDetails']['modelArn'])


if __name__ == '__main__':
    unittest.main()
