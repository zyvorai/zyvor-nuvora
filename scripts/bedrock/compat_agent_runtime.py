#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""bedrock-agent-runtime (Retrieve, RetrieveAndGenerate, InvokeAgent) against a running Nuvora, through boto3.
Fixtures (a knowledge base with documents, an agent) are made with the native API and the bearer token, and
removed in finally. Without a bearer token the script looks for existing ones and skips what it cannot find."""
from _common import Skip, check, eq, expect_error, main_wrapper

SVC = 'bedrock-agent-runtime'


def body(env, report):
    rt = env.client(SVC)
    bd = env.client('bedrock')
    fx = {}

    def fixtures():
        models = bd.list_foundation_models()['modelSummaries']
        chat = [m['modelId'] for m in models if 'TEXT' in m['outputModalities'] and 'EMBEDDING' not in m['outputModalities']]
        check(chat, 'no chat model enabled')
        fx['model'] = chat[0]
        kb = env.native('POST', '/api/knowledge', {'name': 'compat-runtime-kb'}, expect=201)
        fx['kb'] = kb['id']
        report.later(lambda: env.native('DELETE', '/api/knowledge/' + kb['id']))
        for n in range(5):
            env.native('POST', '/api/knowledge/%s/ingest' % kb['id'], {
                'name': 'refund-%d' % n, 'text': 'refund policy number %d covers returns within thirty days' % n,
                'metadata': {'team': 'support' if n % 2 else 'sales'}}, expect=201)
        agent = env.native('POST', '/api/agents', {'name': 'compat-runtime-agent', 'model': fx['model'], 'tools': ['knowledge_search'],
                                                   'knowledge_ids': [kb['id']], 'max_steps': 5}, expect=201)
        fx['agent'] = agent['id']
        report.later(lambda: env.native('DELETE', '/api/agents/' + agent['id']))
        return 'knowledge base %s, agent %s' % (kb['id'], agent['id'])

    report.run('native', 'fixtures (knowledge base, agent)', fixtures)
    if 'kb' not in fx:
        return

    def retrieve():
        out = rt.retrieve(knowledgeBaseId=fx['kb'], retrievalQuery={'text': 'refund policy'})
        results = out['retrievalResults']
        check(results and 'refund policy' in results[0]['content']['text'], results[:1])
        check(0 <= results[0]['score'] <= 1.0, results[0]['score'])
        return '%d results, top score %.2f' % (len(results), results[0]['score'])

    report.run(SVC, 'Retrieve', retrieve)

    def retrieve_filter():
        out = rt.retrieve(knowledgeBaseId=fx['kb'], retrievalQuery={'text': 'refund'}, retrievalConfiguration={'vectorSearchConfiguration': {
            'numberOfResults': 10, 'filter': {'equals': {'key': 'team', 'value': 'support'}}}})
        rows = out['retrievalResults']
        check(rows and all(r['metadata'].get('team') == 'support' for r in rows), rows)
        return '%d support documents' % len(rows)

    report.run(SVC, 'Retrieve (metadata filter)', retrieve_filter)

    def retrieve_page():
        first = rt.retrieve(knowledgeBaseId=fx['kb'], retrievalQuery={'text': 'refund'}, retrievalConfiguration={'vectorSearchConfiguration': {'numberOfResults': 2}})
        check(len(first['retrievalResults']) == 2 and first.get('nextToken'), 'expected a full first page and a nextToken')
        second = rt.retrieve(knowledgeBaseId=fx['kb'], retrievalQuery={'text': 'refund'}, nextToken=first['nextToken'], retrievalConfiguration={'vectorSearchConfiguration': {'numberOfResults': 2}})
        ids = lambda page: [r['content']['text'] for r in page['retrievalResults']]
        check(not set(ids(first)) & set(ids(second)), 'pages overlap')
        return 'two pages of 2, disjoint'

    report.run(SVC, 'Retrieve (nextToken paging)', retrieve_page)
    report.run(SVC, 'Retrieve (unknown KB -> 404)', lambda: expect_error(rt.retrieve, 'ResourceNotFoundException', 404, knowledgeBaseId='NOSUCHKB123', retrievalQuery={'text': 'q'}) and '')

    def rag():
        out = rt.retrieve_and_generate(input={'text': 'What is the refund policy?'}, retrieveAndGenerateConfiguration={
            'type': 'KNOWLEDGE_BASE', 'knowledgeBaseConfiguration': {'knowledgeBaseId': fx['kb'], 'modelArn': fx['model']}})
        check(out['output']['text'] and out['sessionId'], out)
        refs = [r for c in out['citations'] for r in c['retrievedReferences']]
        check(refs, 'no citations')
        return '%d retrieved references cited' % len(refs)

    report.run(SVC, 'RetrieveAndGenerate (KNOWLEDGE_BASE)', rag)
    report.run(SVC, 'RetrieveAndGenerate (EXTERNAL_SOURCES refused)', lambda: expect_error(
        rt.retrieve_and_generate, 'ValidationException', 400, input={'text': 'q'}, retrieveAndGenerateConfiguration={
            'type': 'EXTERNAL_SOURCES', 'externalSourcesConfiguration': {'modelArn': fx['model'], 'sources': [{'sourceType': 'S3', 's3Location': {'uri': 's3://b/k'}}]}}) and 'refused')

    def invoke(**kw):
        out = rt.invoke_agent(agentId=fx['agent'], agentAliasId='TSTALIASID', sessionId='compat-session', inputText='What do you know about refunds?', **kw)
        text, traces = '', []
        for event in out['completion']:
            if 'chunk' in event:
                text += event['chunk']['bytes'].decode()
            elif 'trace' in event:
                traces.append(event['trace'])
        return out, text, traces

    def invoke_agent():
        out, text, traces = invoke()
        check(text.strip(), 'empty completion')
        eq(out['sessionId'], 'compat-session', 'sessionId')
        return '%d characters streamed' % len(text)

    report.run(SVC, 'InvokeAgent', invoke_agent)

    def invoke_trace():
        _, text, traces = invoke(enableTrace=True)
        check(traces, 'no trace events')
        final = traces[-1]['trace']['orchestrationTrace']['observation']
        eq(final['type'], 'FINISH', 'last observation')
        return '%d trace events' % len(traces)

    report.run(SVC, 'InvokeAgent (enableTrace)', invoke_trace)
    report.run(SVC, 'InvokeAgent (memoryId refused)', lambda: expect_error(
        lambda: invoke(memoryId='m1'), 'ValidationException', 400) and 'refused')
    report.run(SVC, 'InvokeAgent (unknown agent -> 404)', lambda: expect_error(
        rt.invoke_agent, 'ResourceNotFoundException', 404, agentId='NOSUCHAGENT', agentAliasId='TSTALIASID', sessionId='s1', inputText='x') and '')
    report.run(SVC, 'GetAgentMemory (refused)', lambda: expect_error(
        rt.get_agent_memory, 'UnsupportedOperationException', 501, agentId=fx['agent'], agentAliasId='TSTALIASID', memoryId='m1', memoryType='SESSION_SUMMARY') and 'recorded route, 501')


if __name__ == '__main__':
    main_wrapper('bedrock-agent-runtime compatibility', body)
