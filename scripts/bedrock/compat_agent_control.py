#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""The `bedrock-agent` control plane (knowledge bases, data sources, ingestion jobs, agents, aliases, action
groups, associations, tags) against a running Nuvora, through boto3. Data sources, action groups and deletes
are admin operations, so most calls use the bearer token (AWS_BEARER_TOKEN_BEDROCK). The web data source needs
the server to allow the crawl host (NUVORA_CONNECTOR_HOSTS=127.0.0.1 for the local run); otherwise it is skipped."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from botocore.exceptions import ClientError

from _common import Skip, check, eq, expect_error, main_wrapper

SVC = 'bedrock-agent'
INSTRUCTION = 'You are a helpful assistant that answers questions about refunds and shipping.'
ROLE = 'arn:aws:iam::123456789012:role/compat'

PAGE = b'<html><head><title>Compat</title></head><body><h1>Refunds</h1><p>Refunds are paid within thirty days of a return request.</p></body></html>'


class Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == '/robots.txt':
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)


def body(env, report):
    ba = env.client(SVC, admin=True)
    keyed = env.client(SVC)
    suffix = str(int(time.time()))[-6:]
    fx = {}

    server = ThreadingHTTPServer(('127.0.0.1', 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    report.later(lambda: (server.shutdown(), server.server_close()))
    site = 'http://127.0.0.1:%d/' % server.server_port

    def discover():
        models = env.client('bedrock').list_foundation_models()['modelSummaries']
        chat = [m['modelId'] for m in models if 'TEXT' in m['outputModalities'] and 'EMBEDDING' not in m['outputModalities']]
        embed = [m['modelId'] for m in models if 'EMBEDDING' in m['outputModalities']]
        check(chat, 'no chat model enabled')
        fx['chat'], fx['embed'] = chat[0], embed[0] if embed else None
        return 'chat=%s embed=%s' % (fx['chat'], fx['embed'])

    report.run('bedrock', 'ListFoundationModels (fixture)', discover)
    if 'chat' not in fx:
        return

    # ---- knowledge bases ----
    def create_kb():
        if not fx['embed']:
            raise Skip('no embedding model registered')
        made = keyed.create_knowledge_base(name='compat-kb-' + suffix, roleArn=ROLE, description='compat', knowledgeBaseConfiguration={
            'type': 'VECTOR', 'vectorKnowledgeBaseConfiguration': {'embeddingModelArn': 'arn:nuvora:bedrock:local::foundation-model/' + fx['embed']}})['knowledgeBase']
        fx['kb'], fx['kb_arn'] = made['knowledgeBaseId'], made['knowledgeBaseArn']
        kb_id = made['knowledgeBaseId']
        report.later(lambda: ba.delete_knowledge_base(knowledgeBaseId=kb_id))
        eq(made['status'], 'ACTIVE', 'status')
        eq(made['storageConfiguration'], {'type': 'NUVORA_BUILTIN'}, 'storage')
        return made['knowledgeBaseArn'] + ' (created with an access key, developer role)'

    report.run(SVC, 'CreateKnowledgeBase', create_kb)

    if 'kb' in fx:
        report.run(SVC, 'GetKnowledgeBase (by ARN)', lambda: eq(ba.get_knowledge_base(knowledgeBaseId=fx['kb_arn'])['knowledgeBase']['knowledgeBaseId'], fx['kb'], 'id') or '')
        report.run(SVC, 'ListKnowledgeBases', lambda: check(fx['kb'] in [k['knowledgeBaseId'] for k in ba.list_knowledge_bases()['knowledgeBaseSummaries']], 'not listed') or '')

        def update_kb():
            kb = ba.get_knowledge_base(knowledgeBaseId=fx['kb'])['knowledgeBase']
            out = ba.update_knowledge_base(knowledgeBaseId=fx['kb'], name='compat-kb2-' + suffix, roleArn=ROLE, knowledgeBaseConfiguration=kb['knowledgeBaseConfiguration'], description='newer')['knowledgeBase']
            eq((out['name'], out['description']), ('compat-kb2-' + suffix, 'newer'), 'name/description')
            return ''

        report.run(SVC, 'UpdateKnowledgeBase', update_kb)
        report.run(SVC, 'CreateKnowledgeBase (unsupported store -> 400)', lambda: expect_error(
            ba.create_knowledge_base, 'ValidationException', 400, name='compat-bad-' + suffix, roleArn=ROLE,
            knowledgeBaseConfiguration={'type': 'VECTOR', 'vectorKnowledgeBaseConfiguration': {'embeddingModelArn': 'arn:nuvora:bedrock:local::foundation-model/' + fx['embed']}},
            storageConfiguration={'type': 'OPENSEARCH_SERVERLESS', 'opensearchServerlessConfiguration': {
                'collectionArn': 'arn:aws:aoss:us-east-1:1:collection/x', 'vectorIndexName': 'i', 'fieldMapping': {'vectorField': 'v', 'textField': 't', 'metadataField': 'm'}}}) and 'external vector stores refused')

        # ---- data source + ingestion job ----
        def data_source():
            try:
                ds = ba.create_data_source(knowledgeBaseId=fx['kb'], name='site-' + suffix, description='compat site', dataSourceConfiguration={
                    'type': 'WEB', 'webConfiguration': {'sourceConfiguration': {'urlConfiguration': {'seedUrls': [{'url': site}]}},
                                                        'crawlerConfiguration': {'crawlerLimits': {'maxPages': 5}, 'scope': 'HOST_ONLY'}}})['dataSource']
            except ClientError as e:
                if 'connector' in e.response['Error'].get('Message', '').lower():
                    raise Skip('server does not allow the crawl host: ' + e.response['Error']['Message'][:100])
                raise
            fx['ds'] = ds['dataSourceId']
            eq(ds['status'], 'AVAILABLE', 'status')
            return fx['ds']

        report.run(SVC, 'CreateDataSource (WEB)', data_source)
        if 'ds' in fx:
            report.run(SVC, 'GetDataSource / ListDataSources', lambda: check(
                ba.get_data_source(knowledgeBaseId=fx['kb'], dataSourceId=fx['ds'])['dataSource']['dataSourceConfiguration']['type'] == 'WEB'
                and fx['ds'] in [d['dataSourceId'] for d in ba.list_data_sources(knowledgeBaseId=fx['kb'])['dataSourceSummaries']], 'mismatch') or '')

            def ingestion():
                job = ba.start_ingestion_job(knowledgeBaseId=fx['kb'], dataSourceId=fx['ds'], description='compat sync')['ingestionJob']
                eq(job['status'], 'STARTING', 'initial status')
                status, done = 'STARTING', job
                for _ in range(60):
                    done = ba.get_ingestion_job(knowledgeBaseId=fx['kb'], dataSourceId=fx['ds'], ingestionJobId=job['ingestionJobId'])['ingestionJob']
                    status = done['status']
                    if status in ('COMPLETE', 'FAILED'):
                        break
                    time.sleep(.5)
                eq(status, 'COMPLETE', 'final status (%s)' % json.dumps(done.get('failureReasons', [])))
                check(done['statistics']['numberOfNewDocumentsIndexed'] >= 1, done['statistics'])
                listed = ba.list_ingestion_jobs(knowledgeBaseId=fx['kb'], dataSourceId=fx['ds'])['ingestionJobSummaries']
                check(job['ingestionJobId'] in [j['ingestionJobId'] for j in listed], 'job not listed')
                return '%d documents indexed' % done['statistics']['numberOfNewDocumentsIndexed']

            report.run(SVC, 'StartIngestionJob / GetIngestionJob / ListIngestionJobs', ingestion)
            report.run(SVC, 'UpdateDataSource', lambda: eq(ba.update_data_source(
                knowledgeBaseId=fx['kb'], dataSourceId=fx['ds'], name='site2-' + suffix, dataSourceConfiguration={
                    'type': 'WEB', 'webConfiguration': {'sourceConfiguration': {'urlConfiguration': {'seedUrls': [{'url': site}]}}}})['dataSource']['name'], 'site2-' + suffix, 'name') or '')
            report.run(SVC, 'DeleteKnowledgeBase (in use -> 409)', lambda: expect_error(ba.delete_knowledge_base, 'ConflictException', 409, knowledgeBaseId=fx['kb']) and 'data source still attached')
            report.run(SVC, 'DeleteDataSource', lambda: eq(ba.delete_data_source(knowledgeBaseId=fx['kb'], dataSourceId=fx['ds'])['status'], 'DELETING', 'status') or '')
        else:
            report.rows.append((SVC, 'GetDataSource / ListDataSources / Ingestion jobs / UpdateDataSource / DeleteDataSource', 'SKIP', 'no data source (see CreateDataSource)'))

        report.run(SVC, 'CreateDataSource (S3 -> connector)', lambda: s3_source(ba, fx, suffix))

    # ---- agents ----
    def create_agent():
        agent = keyed.create_agent(agentName='compat-agent-' + suffix, foundationModel=fx['chat'], instruction=INSTRUCTION, agentResourceRoleArn=ROLE, idleSessionTTLInSeconds=900)['agent']
        fx['agent'], fx['agent_arn'] = agent['agentId'], agent['agentArn']
        agent_id = agent['agentId']
        report.later(lambda: ba.delete_agent(agentId=agent_id, skipResourceInUseCheck=True))
        eq((agent['agentVersion'], agent['agentStatus']), ('DRAFT', 'NOT_PREPARED'), 'version/status')
        return agent['agentArn']

    report.run(SVC, 'CreateAgent', create_agent)
    if 'agent' not in fx:
        return
    agent_id = fx['agent']

    report.run(SVC, 'PrepareAgent', lambda: eq(ba.prepare_agent(agentId=agent_id)['agentStatus'], 'PREPARED', 'status') or '')
    report.run(SVC, 'GetAgent (by ARN) / ListAgents', lambda: check(
        ba.get_agent(agentId=fx['agent_arn'])['agent']['agentStatus'] == 'PREPARED' and agent_id in [a['agentId'] for a in ba.list_agents()['agentSummaries']], 'mismatch') or '')

    def update_agent():
        out = ba.update_agent(agentId=agent_id, agentName='compat-agent2-' + suffix, foundationModel=fx['chat'], agentResourceRoleArn=ROLE,
                              instruction='You answer questions about refunds only. Be precise and brief.')['agent']
        eq((out['agentName'], out['agentStatus']), ('compat-agent2-' + suffix, 'NOT_PREPARED'), 'name/status')
        return 'edit sets the agent back to NOT_PREPARED'

    report.run(SVC, 'UpdateAgent', update_agent)

    # knowledge base association
    if 'kb' in fx:
        def associate():
            link = ba.associate_agent_knowledge_base(agentId=agent_id, agentVersion='DRAFT', knowledgeBaseId=fx['kb'], description='refund docs')['agentKnowledgeBase']
            eq(link['knowledgeBaseState'], 'ENABLED', 'state')
            listed = ba.list_agent_knowledge_bases(agentId=agent_id, agentVersion='DRAFT')['agentKnowledgeBaseSummaries']
            eq([k['knowledgeBaseId'] for k in listed], [fx['kb']], 'listed')
            off = ba.update_agent_knowledge_base(agentId=agent_id, agentVersion='DRAFT', knowledgeBaseId=fx['kb'], knowledgeBaseState='DISABLED')['agentKnowledgeBase']
            eq(off['knowledgeBaseState'], 'DISABLED', 'state after update')
            return ''

        report.run(SVC, 'AssociateAgentKnowledgeBase / List / Update', associate)

    # action group from an OpenAPI schema (admin; the action host must be allowed by the server)
    def action_group():
        spec = json.dumps({'openapi': '3.0.0', 'info': {'title': 'Orders', 'version': '1'}, 'servers': [{'url': site.rstrip('/')}],
                           'paths': {'/order': {'get': {'operationId': 'getOrder', 'summary': 'Get an order', 'parameters': [
                               {'name': 'id', 'in': 'query', 'required': True, 'schema': {'type': 'string'}}]}}}})
        try:
            group = ba.create_agent_action_group(agentId=agent_id, agentVersion='DRAFT', actionGroupName='orders', description='Orders API', apiSchema={'payload': spec})['agentActionGroup']
        except ClientError as e:
            if e.response['Error']['Code'] in ('ValidationException', 'AccessDeniedException') and 'host' in e.response['Error'].get('Message', '').lower():
                raise Skip('server does not allow the action host: ' + e.response['Error']['Message'][:100])
            raise
        eq(group['actionGroupState'], 'ENABLED', 'state')
        got = ba.get_agent_action_group(agentId=agent_id, agentVersion='DRAFT', actionGroupId=group['actionGroupId'])['agentActionGroup']
        eq(json.loads(got['apiSchema']['payload'])['info']['title'], 'Orders', 'schema round trip')
        off = ba.update_agent_action_group(agentId=agent_id, agentVersion='DRAFT', actionGroupId=group['actionGroupId'], actionGroupName='orders', actionGroupState='DISABLED')['agentActionGroup']
        eq(off['actionGroupState'], 'DISABLED', 'state after update')
        eq([g['actionGroupName'] for g in ba.list_agent_action_groups(agentId=agent_id, agentVersion='DRAFT')['actionGroupSummaries']], ['orders'], 'listed')
        ba.delete_agent_action_group(agentId=agent_id, agentVersion='DRAFT', actionGroupId=group['actionGroupId'])
        expect_error(ba.get_agent_action_group, 'ResourceNotFoundException', 404, agentId=agent_id, agentVersion='DRAFT', actionGroupId=group['actionGroupId'])
        return 'OpenAPI imported as an action, then removed'

    report.run(SVC, 'Create/Get/Update/List/DeleteAgentActionGroup', action_group)

    # versions and aliases
    def alias():
        ba.prepare_agent(agentId=agent_id)
        made = ba.create_agent_alias(agentId=agent_id, agentAliasName='live-' + suffix, description='prod')['agentAlias']
        fx['alias'] = made['agentAliasId']
        eq(made['routingConfiguration'], [{'agentVersion': '1'}], 'routing')
        eq((made['agentAliasStatus'], len(made['agentAliasId'])), ('PREPARED', 10), 'status/id length')
        versions = sorted(v['agentVersion'] for v in ba.list_agent_versions(agentId=agent_id)['agentVersionSummaries'])
        eq(versions, ['1', 'DRAFT'], 'versions')
        eq(ba.get_agent_version(agentId=agent_id, agentVersion='1')['agentVersion']['version'], '1', 'GetAgentVersion')
        check(fx['alias'] in [a['agentAliasId'] for a in ba.list_agent_aliases(agentId=agent_id)['agentAliasSummaries']], 'alias not listed')
        eq(ba.get_agent_alias(agentId=agent_id, agentAliasId=made['agentAliasArn'])['agentAlias']['agentAliasName'], 'live-' + suffix, 'by ARN')
        moved = ba.update_agent_alias(agentId=agent_id, agentAliasId=fx['alias'], agentAliasName='live-' + suffix, routingConfiguration=[{'agentVersion': '1'}], description='still prod')['agentAlias']
        eq(moved['description'], 'still prod', 'description')
        return 'alias %s -> version 1' % fx['alias']

    report.run(SVC, 'PrepareAgent / Create, Get, List, UpdateAgentAlias / ListAgentVersions / GetAgentVersion', alias)
    def invoke_by_alias():
        if 'alias' not in fx:
            raise Skip('no alias created')
        rt = env.client('bedrock-agent-runtime')
        ba.update_agent(agentId=agent_id, agentName='compat-agent2-' + suffix, foundationModel=fx['chat'], agentResourceRoleArn=ROLE,
                        instruction='You answer in one word only, whatever you are asked. Never write more than one word.')

        def versions_seen(alias):
            out = rt.invoke_agent(agentId=agent_id, agentAliasId=alias, sessionId='compat-alias', inputText='Say hello', enableTrace=True)
            return {e['trace']['agentVersion'] for e in out['completion'] if 'trace' in e}
        eq(versions_seen(fx['alias']), {'1'}, 'alias runs its pinned version')
        eq(versions_seen('TSTALIASID'), {'DRAFT'}, 'TSTALIASID runs the DRAFT')
        expect_error(rt.invoke_agent, 'ResourceNotFoundException', 404, agentId=agent_id, agentAliasId='NOSUCHALIAS', sessionId='compat-alias', inputText='x')
        return 'alias -> version 1, TSTALIASID -> DRAFT, unknown alias 404'

    report.run('bedrock-agent-runtime', 'InvokeAgent honours the alias (pinned version vs DRAFT)', invoke_by_alias)
    report.run(SVC, 'DeleteAgentVersion (refused)', lambda: expect_error(ba.delete_agent_version, 'UnsupportedOperationException', 501, agentId=agent_id, agentVersion='1') and 'recorded route, 501')

    def tags():
        ba.tag_resource(resourceArn=fx['agent_arn'], tags={'team': 'compat'})
        eq(ba.list_tags_for_resource(resourceArn=fx['agent_arn'])['tags'], {'team': 'compat'}, 'tags')
        ba.untag_resource(resourceArn=fx['agent_arn'], tagKeys=['team'])
        eq(ba.list_tags_for_resource(resourceArn=fx['agent_arn'])['tags'], {}, 'tags after untag')
        return ''

    report.run(SVC, 'TagResource / ListTagsForResource / UntagResource', tags)

    def delete_alias_then_agent():
        if 'alias' not in fx:
            raise Skip('no alias created')
        expect_error(ba.delete_agent, 'ConflictException', 409, agentId=agent_id)
        eq(ba.delete_agent_alias(agentId=agent_id, agentAliasId=fx['alias'])['agentAliasStatus'], 'DELETING', 'alias status')
        eq(ba.delete_agent(agentId=agent_id)['agentStatus'], 'DELETING', 'agent status')
        expect_error(ba.get_agent, 'ResourceNotFoundException', 404, agentId=agent_id)
        return 'agent with an alias is 409 until the alias is gone'

    report.run(SVC, 'DeleteAgentAlias / DeleteAgent', delete_alias_then_agent)

    if 'kb' in fx:
        report.run(SVC, 'DeleteKnowledgeBase', lambda: eq(ba.delete_knowledge_base(knowledgeBaseId=fx['kb'])['status'], 'DELETING', 'status') or '')


def s3_source(ba, fx, suffix):
    try:
        ds = ba.create_data_source(knowledgeBaseId=fx['kb'], name='s3-' + suffix, dataSourceConfiguration={
            'type': 'S3', 's3Configuration': {'bucketArn': 'arn:aws:s3:::compat-bucket', 'inclusionPrefixes': ['docs/']}})['dataSource']
    except ClientError as e:
        raise Skip('S3 connector refused: %s' % e.response['Error'].get('Message', '')[:120])
    ba.delete_data_source(knowledgeBaseId=fx['kb'], dataSourceId=ds['dataSourceId'])
    return 'S3 connector created and removed (no S3 call is made)'


if __name__ == '__main__':
    main_wrapper('bedrock-agent control plane compatibility', body)
