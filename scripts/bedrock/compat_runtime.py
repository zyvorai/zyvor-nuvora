#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""bedrock-runtime and model listing against a running Nuvora, through boto3.
  NUVORA_ENDPOINT=http://127.0.0.1:8789 AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... python compat_runtime.py"""
import json

from _common import Skip, check, eq, error_of, expect_error, main_wrapper

RT = 'bedrock-runtime'
USER = [{'role': 'user', 'content': [{'text': 'compat suite hello'}]}]


def body(env, report):
    rt = env.client(RT)
    bd = env.client('bedrock')
    found = {}

    def pick_models():
        models = bd.list_foundation_models()['modelSummaries']
        text = [m['modelId'] for m in models if 'TEXT' in m['outputModalities'] and 'EMBEDDING' not in m['outputModalities']]
        embed = [m['modelId'] for m in models if 'EMBEDDING' in m['outputModalities']]
        check(text, 'no enabled chat model; start Nuvora with --demo or add one')
        found['chat'], found['embed'] = text[0], embed[0] if embed else None
        return '%d models; chat=%s' % (len(models), found['chat'])

    report.run('bedrock', 'ListFoundationModels', pick_models)
    if 'chat' not in found:
        return
    chat = found['chat']

    report.run('bedrock', 'GetFoundationModel', lambda: eq(bd.get_foundation_model(modelIdentifier=chat)['modelDetails']['modelId'], chat, 'modelId') or '')
    report.run('bedrock', 'GetFoundationModel (unknown)', lambda: expect_error(bd.get_foundation_model, 'ResourceNotFoundException', 404, modelIdentifier='nope.nothing-v1:0') and '')

    def converse():
        out = rt.converse(modelId=chat, messages=USER, system=[{'text': 'be brief'}], inferenceConfig={'maxTokens': 100, 'temperature': 0.2})
        check('compat suite hello' in out['output']['message']['content'][0]['text'], 'demo model should echo the prompt')
        u = out['usage']
        eq(u['totalTokens'], u['inputTokens'] + u['outputTokens'], 'totalTokens')
        return 'stopReason=%s' % out['stopReason']

    report.run(RT, 'Converse', converse)

    def converse_tools():
        out = rt.converse(modelId=chat, messages=USER, toolConfig={'tools': [{'toolSpec': {
            'name': 'lookup', 'description': 'Look something up', 'inputSchema': {'json': {'type': 'object', 'properties': {'q': {'type': 'string'}}}}}}]})
        check(out['stopReason'] in ('end_turn', 'tool_use'), out['stopReason'])
        return 'stopReason=' + out['stopReason']

    report.run(RT, 'Converse (toolConfig)', converse_tools)

    def stream():
        events = [e for e in rt.converse_stream(modelId=chat, messages=USER)['stream']]
        kinds = [next(iter(e)) for e in events]
        check('messageStart' in kinds and 'messageStop' in kinds and kinds[-1] == 'metadata', kinds)
        text = ''.join(e['contentBlockDelta']['delta'].get('text', '') for e in events if 'contentBlockDelta' in e)
        check('compat suite hello' in text, 'streamed text missing the prompt')
        return '%d events' % len(events)

    report.run(RT, 'ConverseStream', stream)

    def invoke_native():
        out = rt.invoke_model(modelId=chat, body=json.dumps({'messages': [{'role': 'user', 'content': 'native shape'}]}))
        data = json.loads(out['body'].read())
        check('native shape' in json.dumps(data), data)
        return 'input tokens header ' + str(out['ResponseMetadata']['HTTPHeaders'].get('x-amzn-bedrock-input-token-count'))

    report.run(RT, 'InvokeModel (Nuvora/OpenAI chat body)', invoke_native)

    def invoke_anthropic():
        out = rt.invoke_model(modelId=chat, body=json.dumps({'anthropic_version': 'bedrock-2023-05-31', 'max_tokens': 100, 'messages': [{'role': 'user', 'content': 'anthropic shape'}]}))
        data = json.loads(out['body'].read())
        check(data.get('type') == 'message' and 'anthropic shape' in json.dumps(data['content']), data)
        return 'stop_reason=%s' % data.get('stop_reason')

    report.run(RT, 'InvokeModel (Anthropic messages body)', invoke_anthropic)

    def invoke_stream():
        out = rt.invoke_model_with_response_stream(modelId=chat, body=json.dumps({'messages': [{'role': 'user', 'content': 'stream shape'}]}))
        chunks = [e['chunk']['bytes'] for e in out['body'] if 'chunk' in e]
        check(chunks, 'no chunk events')
        return '%d chunks' % len(chunks)

    report.run(RT, 'InvokeModelWithResponseStream', invoke_stream)

    def embed():
        if not found['embed']:
            raise Skip('no embedding model registered')
        out = rt.invoke_model(modelId=found['embed'], body=json.dumps({'inputText': 'embed me'}))
        data = json.loads(out['body'].read())
        vec = data.get('embedding') or (data.get('data') or [{}])[0].get('embedding')
        check(vec and all(isinstance(x, float) for x in vec[:4]), data)
        return '%d dimensions' % len(vec)

    report.run(RT, 'InvokeModel (embeddings)', embed)

    def count():
        out = rt.count_tokens(modelId=chat, input={'converse': {'messages': USER}})
        check(out['inputTokens'] > 0, out)
        return 'estimate: %d tokens (characters / 4)' % out['inputTokens']

    report.run(RT, 'CountTokens (estimate)', count)

    # Guardrail enforcement: a throwaway guardrail made through the bedrock control plane.
    gid = {}

    def make_guardrail():
        # guardrail writes are admin operations in Nuvora, so they need the bearer token (an access key is at most developer)
        admin = env.client('bedrock', admin=True)
        made = admin.create_guardrail(name='compat-rt-%s' % env.key[-6:].lower(), description='compat suite', blockedInputMessaging='blocked in', blockedOutputsMessaging='blocked out',
                                   topicPolicyConfig={'topicsConfig': [{'name': 'crypto', 'definition': 'Anything about cryptocurrency', 'examples': ['buy bitcoin'], 'type': 'DENY'}]},
                                   wordPolicyConfig={'wordsConfig': [{'text': 'compatsecretword'}]})
        gid['id'] = made['guardrailId']
        report.later(lambda: admin.delete_guardrail(guardrailIdentifier=gid['id']))
        return made['guardrailId']

    report.run('bedrock', 'CreateGuardrail (fixture)', make_guardrail)

    def apply_in():
        if 'id' not in gid:
            raise Skip('fixture guardrail missing')
        hit = rt.apply_guardrail(guardrailIdentifier=gid['id'], guardrailVersion='DRAFT', source='INPUT', content=[{'text': {'text': 'tell me about compatsecretword'}}])
        eq(hit['action'], 'GUARDRAIL_INTERVENED', 'action')
        eq(hit['outputs'], [{'text': 'blocked in'}], 'outputs')
        ok = rt.apply_guardrail(guardrailIdentifier=gid['id'], guardrailVersion='DRAFT', source='INPUT', content=[{'text': {'text': 'what is the weather'}}])
        eq(ok['action'], 'NONE', 'action on clean text')
        return 'blocked and passed as expected'

    report.run(RT, 'ApplyGuardrail', apply_in)

    def converse_guardrail():
        if 'id' not in gid:
            raise Skip('fixture guardrail missing')
        out = rt.converse(modelId=chat, messages=[{'role': 'user', 'content': [{'text': 'compatsecretword please'}]}],
                          guardrailConfig={'guardrailIdentifier': gid['id'], 'guardrailVersion': 'DRAFT'})
        eq(out['stopReason'], 'guardrail_intervened', 'stopReason')
        return 'blocked: ' + out['output']['message']['content'][0]['text']

    report.run(RT, 'Converse (guardrailConfig)', converse_guardrail)

    # Errors the SDK must see with AWS's codes and statuses.
    report.run(RT, 'Converse (unknown model -> 404)', lambda: expect_error(rt.converse, 'ResourceNotFoundException', 404, modelId='no.such-model-v1:0', messages=USER) and '')
    report.run(RT, 'Converse (maxTokens too large -> 400)', lambda: expect_error(rt.converse, 'ValidationException', 400, modelId=chat, messages=USER, inferenceConfig={'maxTokens': 999999}) and '')
    report.run(RT, 'Converse (refused member -> 400)', lambda: expect_error(rt.converse, 'ValidationException', 400, modelId=chat, messages=USER, additionalModelRequestFields={'x': 1}) and 'refused by name, not ignored')
    report.run(RT, 'StartAsyncInvoke (refused)', lambda: expect_error(
        rt.start_async_invoke, 'UnsupportedOperationException', 501, modelId=chat, modelInput={}, outputDataConfig={'s3OutputDataConfig': {'s3Uri': 's3://b/k'}}) and 'recorded route, 501')

    def wrong_secret():
        if not env.key:
            raise Skip('bearer-only run')
        bad = env.sigv4_client(RT, secret='z' * 40)
        got = error_of(bad.converse, modelId=chat, messages=USER)
        eq(got[:2], ('InvalidSignatureException', 403), 'wrong secret')
        return ''

    report.run(RT, 'SigV4 (wrong secret -> 403)', wrong_secret)

    def bearer_converse():
        if not env.bearer:
            raise Skip('no AWS_BEARER_TOKEN_BEDROCK')
        out = env.client(RT, admin=True).converse(modelId=chat, messages=USER)
        eq(out['stopReason'], 'end_turn', 'stopReason')
        return ''

    report.run(RT, 'Converse (bearer token)', bearer_converse)


if __name__ == '__main__':
    main_wrapper('bedrock-runtime compatibility', body)
