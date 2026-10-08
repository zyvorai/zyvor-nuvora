# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""bedrock-agent control plane (knowledge bases, data sources, ingestion jobs, agents, aliases, action groups,
associations, tags) through the real AWS SDK (botocore) against a live server and the offline demo provider.
Every response is also checked against the service model's required members, which is what the SDK's parser
and typed clients (Terraform, CDK) rely on. Skipped when boto3/botocore are not installed."""
import json
import os
import unittest
from unittest import mock

from test_bedrock_runtime import Base
from nuvora.bedrock import control_agent

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError, ParamValidationError
    HAVE = True
except ImportError:
    HAVE = False

TOKEN = 'a' * 33
OTHER_TOKEN = 'b' * 33
INSTRUCTION = 'You are a helpful assistant that answers questions about refunds and shipping.'


def missing(shape, value, path=''):
    """Required members the service model demands but the response lacks."""
    out = []
    if shape.type_name == 'structure' and isinstance(value, dict):
        for name in shape.required_members:
            if name not in value:
                out.append(path + '.' + name)
        for name, member in shape.members.items():
            if name in value:
                out += missing(member, value[name], path + '.' + name)
    elif shape.type_name == 'list' and isinstance(value, list):
        for i, item in enumerate(value):
            out += missing(shape.member, item, f'{path}[{i}]')
    return out


@unittest.skipUnless(HAVE, 'boto3/botocore not installed')
class AgentControl(Base):
    def setUp(self):
        super().setUp()
        self.app.connector_hosts = {'127.0.0.1'}
        self.problems = []
        self.base_kbs = len(self.app.list(self.p, 'knowledge'))

    def tearDown(self):
        super().tearDown()
        self.assertEqual(self.problems, [], 'responses lack members the bedrock-agent model requires')

    def agent_client(self, cred=None, region='us-west-2', bearer=None):
        # AWS access keys carry the viewer or developer role only; admin operations (connectors, actions, deletes) need a bearer token
        cred = cred or self.cred
        client = boto3.client('bedrock-agent', endpoint_url=self.url, region_name=region, aws_access_key_id=cred['access_key_id'],
                              aws_secret_access_key=cred['secret_access_key'], config=Config(retries={'max_attempts': 1}))

        def check(http_response, parsed, model, **kw):
            if http_response.status_code < 300 and model.output_shape is not None:
                self.problems += [model.name + p for p in missing(model.output_shape, parsed)]
        client.meta.events.register('after-call.bedrock-agent.*', check)
        if bearer:
            client.meta.events.register('before-send.bedrock-agent.*', lambda request, **kw: request.headers.__setitem__('Authorization', 'Bearer ' + bearer))
        return client

    @property
    def ba(self):
        if not hasattr(self, '_ba'):
            self._ba = self.agent_client(bearer=self.token)
        return self._ba

    def err(self, call, **kw):
        with self.assertRaises(ClientError) as ctx:
            call(**kw)
        e = ctx.exception.response
        return e['Error']['Code'], e['ResponseMetadata']['HTTPStatusCode'], e['Error'].get('Message', '')

    def embed_arn(self):
        return f'arn:nuvora:bedrock:local::foundation-model/{self.embed_model}'

    def kb(self, name='Support', **kw):
        return self.ba.create_knowledge_base(name=name, roleArn='arn:aws:iam::123456789012:role/kb', knowledgeBaseConfiguration={
            'type': 'VECTOR', 'vectorKnowledgeBaseConfiguration': {'embeddingModelArn': self.embed_arn()}}, **kw)['knowledgeBase']

    def web_source(self, url, name='site'):
        return {'type': 'WEB', 'webConfiguration': {'sourceConfiguration': {'urlConfiguration': {'seedUrls': [{'url': url}]}}}}

    def agent(self, name='helper', **kw):
        return self.ba.create_agent(agentName=name, foundationModel=self.demo, instruction=INSTRUCTION, **kw)['agent']

    def spec(self, url):
        return json.dumps({'openapi': '3.0.0', 'info': {'title': 'Orders', 'version': '1'}, 'servers': [{'url': url}],
                           'paths': {'/order': {'get': {'operationId': 'getOrder', 'summary': 'Get an order', 'parameters': [
                               {'name': 'id', 'in': 'query', 'required': True, 'schema': {'type': 'string'}}]}}}})

    # ---- knowledge bases -------------------------------------------------------------------

    def test_knowledge_base_lifecycle_ids_arns_and_status(self):
        kb = self.kb(description='Docs')
        self.assertEqual(kb['status'], 'ACTIVE')
        self.assertEqual(kb['knowledgeBaseArn'], f"arn:nuvora:bedrock:local:a:knowledge-base/{kb['knowledgeBaseId']}")
        self.assertEqual(kb['knowledgeBaseConfiguration']['vectorKnowledgeBaseConfiguration']['embeddingModelArn'], self.embed_arn())
        self.assertEqual(kb['storageConfiguration'], {'type': 'NUVORA_BUILTIN'})
        native = self.json(f"/api/knowledge/{kb['knowledgeBaseId']}", expect=200)
        self.assertEqual((native['name'], native['embedding_model']), ('Support', self.embed_model))
        by_arn = self.ba.get_knowledge_base(knowledgeBaseId=kb['knowledgeBaseArn'])['knowledgeBase']
        self.assertEqual(by_arn['knowledgeBaseId'], kb['knowledgeBaseId'])
        self.assertEqual(by_arn['description'], 'Docs')
        self.assertEqual(by_arn['roleArn'], 'arn:aws:iam::123456789012:role/kb')
        updated = self.ba.update_knowledge_base(knowledgeBaseId=kb['knowledgeBaseId'], name='Support2', roleArn='arn:aws:iam::123456789012:role/other',
                                                knowledgeBaseConfiguration=kb['knowledgeBaseConfiguration'], description='Newer')['knowledgeBase']
        self.assertEqual((updated['name'], updated['description'], updated['roleArn']), ('Support2', 'Newer', 'arn:aws:iam::123456789012:role/other'))
        self.assertEqual(self.json(f"/api/knowledge/{kb['knowledgeBaseId']}")['name'], 'Support2')
        out = self.ba.delete_knowledge_base(knowledgeBaseId=kb['knowledgeBaseId'])
        self.assertEqual(out['status'], 'DELETING')
        self.assertEqual(self.err(self.ba.get_knowledge_base, knowledgeBaseId=kb['knowledgeBaseId'])[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.err(self.ba.delete_knowledge_base, knowledgeBaseId=kb['knowledgeBaseId'])[:2], ('ResourceNotFoundException', 404))

    def test_knowledge_base_list_pagination(self):
        ids = {self.kb(name=f'kb{i}')['knowledgeBaseId'] for i in range(3)}
        first = self.ba.list_knowledge_bases(maxResults=2)
        self.assertEqual(len(first['knowledgeBaseSummaries']), 2)
        seen, page = list(first['knowledgeBaseSummaries']), first
        while 'nextToken' in page:
            page = self.ba.list_knowledge_bases(maxResults=2, nextToken=page['nextToken'])
            self.assertLessEqual(len(page['knowledgeBaseSummaries']), 2)
            seen += page['knowledgeBaseSummaries']
        self.assertEqual(len(seen), self.base_kbs + 3)
        self.assertEqual(len({s['knowledgeBaseId'] for s in seen}), self.base_kbs + 3)
        self.assertTrue(ids <= {s['knowledgeBaseId'] for s in seen})
        self.assertEqual(self.err(self.ba.list_knowledge_bases, nextToken='garbage')[:2], ('ValidationException', 400))

    def test_knowledge_base_refusals_name_the_member(self):
        vector = {'type': 'VECTOR', 'vectorKnowledgeBaseConfiguration': {'embeddingModelArn': self.embed_arn()}}
        base = {'name': 'x', 'roleArn': 'arn:aws:iam::123456789012:role/kb'}

        def refused(fragment, **kw):
            code, status, message = self.err(self.ba.create_knowledge_base, **{**base, 'knowledgeBaseConfiguration': vector, **kw})
            self.assertEqual((code, status), ('ValidationException', 400), message)
            self.assertIn(fragment, message)
        refused('storageConfiguration.type OPENSEARCH_SERVERLESS', storageConfiguration={'type': 'OPENSEARCH_SERVERLESS', 'opensearchServerlessConfiguration': {
            'collectionArn': 'arn:aws:aoss:us-east-1:123456789012:collection/abc', 'vectorIndexName': 'i', 'fieldMapping': {'vectorField': 'v', 'textField': 't', 'metadataField': 'm'}}})
        refused('knowledgeBaseConfiguration.type KENDRA', knowledgeBaseConfiguration={'type': 'KENDRA', 'kendraKnowledgeBaseConfiguration': {'kendraIndexArn': 'arn:aws:kendra:us-east-1:123456789012:index/' + 'a' * 36}})
        refused('embeddingModelConfiguration', knowledgeBaseConfiguration={'type': 'VECTOR', 'vectorKnowledgeBaseConfiguration': {
            'embeddingModelArn': self.embed_arn(), 'embeddingModelConfiguration': {'bedrockEmbeddingModelConfiguration': {'dimensions': 256}}}})
        refused('no model nope', knowledgeBaseConfiguration={'type': 'VECTOR', 'vectorKnowledgeBaseConfiguration': {'embeddingModelArn': 'nope-model-identifier'}})
        refused('capability chat', knowledgeBaseConfiguration={'type': 'VECTOR', 'vectorKnowledgeBaseConfiguration': {'embeddingModelArn': self.demo}})
        with self.assertRaises(ParamValidationError):
            self.ba.create_knowledge_base(name='x')
        accepted = self.ba.create_knowledge_base(**base, knowledgeBaseConfiguration=vector, storageConfiguration={'type': 'NUVORA_BUILTIN'})
        self.assertEqual(accepted['knowledgeBase']['status'], 'ACTIVE')
        code, status, message = self.err(self.ba.update_knowledge_base, knowledgeBaseId=accepted['knowledgeBase']['knowledgeBaseId'], **base,
                                          knowledgeBaseConfiguration={'type': 'VECTOR', 'vectorKnowledgeBaseConfiguration': {'embeddingModelArn': self.demo}})
        self.assertEqual((code, status), ('ValidationException', 400))
        self.assertEqual(self.err(self.ba.create_knowledge_base, **{**base, 'name': 'bad name!'}, knowledgeBaseConfiguration=vector)[0], 'ValidationException')

    def test_names_are_unique_and_client_tokens_replay(self):
        first = self.kb(name='same', clientToken=TOKEN)
        again = self.kb(name='same', clientToken=TOKEN)
        self.assertEqual(first['knowledgeBaseId'], again['knowledgeBaseId'])
        self.assertEqual(len(self.ba.list_knowledge_bases()['knowledgeBaseSummaries']), self.base_kbs + 1)
        self.assertEqual(self.err(self.ba.create_knowledge_base, name='different', clientToken=TOKEN, roleArn='arn:aws:iam::123456789012:role/kb',
                                   knowledgeBaseConfiguration=first['knowledgeBaseConfiguration'])[:2], ('ConflictException', 409))
        self.assertEqual(self.err(self.kb, name='same')[:2], ('ConflictException', 409))
        with self.assertRaises(ParamValidationError):
            self.ba.create_knowledge_base(name='short', clientToken='short', roleArn='arn:aws:iam::123456789012:role/kb', knowledgeBaseConfiguration=first['knowledgeBaseConfiguration'])
        code, raw, headers = self.request('/knowledgebases', {'name': 'short', 'clientToken': 'short', 'roleArn': 'r', 'knowledgeBaseConfiguration': first['knowledgeBaseConfiguration']}, method='PUT')
        self.assertEqual((code, headers['x-amzn-ErrorType']), (400, 'ValidationException'))

    def test_roles_viewer_reads_developer_writes_admin_deletes(self):
        kb = self.kb()
        viewer = self.agent_client(self.json('/api/aws-credentials', {'role': 'viewer', 'username': 'viewer'}, expect=201))
        dev = self.agent_client(self.json('/api/aws-credentials', {'role': 'developer', 'username': 'dev'}, expect=201))
        self.assertEqual(viewer.get_knowledge_base(knowledgeBaseId=kb['knowledgeBaseId'])['knowledgeBase']['name'], 'Support')
        self.assertEqual(self.err(viewer.create_knowledge_base, name='v', roleArn='arn:aws:iam::123456789012:role/kb',
                                   knowledgeBaseConfiguration=kb['knowledgeBaseConfiguration'])[:2], ('AccessDeniedException', 403))
        made = dev.create_knowledge_base(name='d', roleArn='arn:aws:iam::123456789012:role/kb', knowledgeBaseConfiguration=kb['knowledgeBaseConfiguration'])['knowledgeBase']
        self.assertEqual(self.err(dev.delete_knowledge_base, knowledgeBaseId=made['knowledgeBaseId'])[:2], ('AccessDeniedException', 403))
        self.ba.delete_knowledge_base(knowledgeBaseId=made['knowledgeBaseId'])

    # ---- data sources and ingestion jobs ---------------------------------------------------

    def site(self):
        pages = {'/': '<title>Home</title><a href="/a">A</a> Welcome to refunds', '/a': '<p>Refund policy: thirty days</p>'}
        routes = {('GET', '/robots.txt'): lambda h, b: (404, b'', {})}
        for path, html in pages.items():
            routes[('GET', path)] = (lambda html: lambda h, b: (200, html.encode(), {'Content-Type': 'text/html; charset=utf-8'}))(html)
        return self.stub(routes)

    def test_data_source_to_ingestion_job_round_trip(self):
        url, calls = self.site()
        kb = self.kb()
        kb_id = kb['knowledgeBaseId']
        ds = self.ba.create_data_source(knowledgeBaseId=kb_id, name='site', description='Help site', dataSourceConfiguration={
            'type': 'WEB', 'webConfiguration': {'sourceConfiguration': {'urlConfiguration': {'seedUrls': [{'url': url + '/'}]}},
                                                'crawlerConfiguration': {'crawlerLimits': {'maxPages': 10}, 'scope': 'HOST_ONLY'}}})['dataSource']
        self.assertEqual((ds['status'], ds['dataDeletionPolicy'], ds['description']), ('AVAILABLE', 'RETAIN', 'Help site'))
        connector = self.json(f"/api/connectors/{ds['dataSourceId']}", expect=200)
        self.assertEqual((connector['type'], connector['url'], connector['max_pages'], connector['knowledge_id']), ('web', url + '/', 10, kb_id))
        self.assertEqual(self.ba.get_data_source(knowledgeBaseId=kb_id, dataSourceId=ds['dataSourceId'])['dataSource']['dataSourceConfiguration']['type'], 'WEB')
        self.assertEqual([s['name'] for s in self.ba.list_data_sources(knowledgeBaseId=kb_id)['dataSourceSummaries']], ['site'])
        job = self.ba.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds['dataSourceId'], description='first sync')['ingestionJob']
        self.assertEqual(job['status'], 'STARTING')
        self.assertEqual(job['statistics']['numberOfDocumentsScanned'], 0)
        self.assertEqual(self.ba.get_knowledge_base(knowledgeBaseId=kb_id)['knowledgeBase']['status'], 'UPDATING')
        self.app.process_job(self.p, job['ingestionJobId'])
        done = self.ba.get_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds['dataSourceId'], ingestionJobId=job['ingestionJobId'])['ingestionJob']
        self.assertEqual(done['status'], 'COMPLETE', done)
        self.assertEqual((done['statistics']['numberOfDocumentsScanned'], done['statistics']['numberOfNewDocumentsIndexed'], done['statistics']['numberOfDocumentsFailed']), (2, 2, 0))
        self.assertEqual(done['description'], 'first sync')
        self.assertEqual(self.ba.get_knowledge_base(knowledgeBaseId=kb_id)['knowledgeBase']['status'], 'ACTIVE')
        self.assertEqual(len(self.json(f'/api/knowledge/{kb_id}/documents')['items']), 2)
        listed = self.ba.list_ingestion_jobs(knowledgeBaseId=kb_id, dataSourceId=ds['dataSourceId'])['ingestionJobSummaries']
        self.assertEqual([j['ingestionJobId'] for j in listed], [job['ingestionJobId']])
        self.assertEqual(listed[0]['statistics']['numberOfNewDocumentsIndexed'], 2)
        again = self.ba.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds['dataSourceId'])['ingestionJob']
        self.app.process_job(self.p, again['ingestionJobId'])
        second = self.ba.get_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds['dataSourceId'], ingestionJobId=again['ingestionJobId'])['ingestionJob']
        self.assertEqual((second['statistics']['numberOfDocumentsSkipped'], second['statistics']['numberOfNewDocumentsIndexed']), (2, 0))
        done_only = self.ba.list_ingestion_jobs(knowledgeBaseId=kb_id, dataSourceId=ds['dataSourceId'], filters=[{'attribute': 'STATUS', 'operator': 'EQ', 'values': ['COMPLETE']}], maxResults=1)
        self.assertEqual(len(done_only['ingestionJobSummaries']), 1)
        self.assertIn('nextToken', done_only)
        self.assertEqual(self.ba.list_ingestion_jobs(knowledgeBaseId=kb_id, dataSourceId=ds['dataSourceId'], filters=[{'attribute': 'STATUS', 'operator': 'EQ', 'values': ['FAILED']}])['ingestionJobSummaries'], [])
        sources = self.ba.update_data_source(knowledgeBaseId=kb_id, dataSourceId=ds['dataSourceId'], name='site2', dataSourceConfiguration=self.web_source(url + '/a'))['dataSource']
        self.assertEqual(sources['name'], 'site2')
        self.assertEqual(self.json(f"/api/connectors/{ds['dataSourceId']}")['url'], url + '/a')
        self.assertEqual(self.err(self.ba.delete_knowledge_base, knowledgeBaseId=kb_id)[:2], ('ConflictException', 409))
        self.assertEqual(self.ba.delete_data_source(knowledgeBaseId=kb_id, dataSourceId=ds['dataSourceId'])['status'], 'DELETING')
        self.assertEqual(self.err(self.ba.get_data_source, knowledgeBaseId=kb_id, dataSourceId=ds['dataSourceId'])[:2], ('ResourceNotFoundException', 404))

    def test_ingestion_client_token_conflict_and_scoping(self):
        url, _ = self.site()
        kb = self.kb()['knowledgeBaseId']
        other = self.kb('other')['knowledgeBaseId']
        ds = self.ba.create_data_source(knowledgeBaseId=kb, name='s', dataSourceConfiguration=self.web_source(url + '/'))['dataSource']['dataSourceId']
        first = self.ba.start_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds, clientToken=TOKEN)['ingestionJob']
        replay = self.ba.start_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds, clientToken=TOKEN)['ingestionJob']
        self.assertEqual(first['ingestionJobId'], replay['ingestionJobId'])
        self.assertEqual(self.err(self.ba.start_ingestion_job, knowledgeBaseId=kb, dataSourceId=ds, clientToken=OTHER_TOKEN)[:2], ('ConflictException', 409))
        self.assertEqual(self.err(self.ba.start_ingestion_job, knowledgeBaseId=kb, dataSourceId=ds, clientToken=TOKEN, description='changed')[:2], ('ConflictException', 409))
        self.app.process_job(self.p, first['ingestionJobId'])
        self.assertEqual(self.err(self.ba.get_data_source, knowledgeBaseId=other, dataSourceId=ds)[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.err(self.ba.get_ingestion_job, knowledgeBaseId=kb, dataSourceId=ds, ingestionJobId='nope')[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.err(self.ba.list_ingestion_jobs, knowledgeBaseId=kb, dataSourceId=ds, sortBy={'attribute': 'STATUS', 'order': 'ASCENDING'})[0], 'ValidationException')

    def test_data_source_failed_job_reports_statistics_and_reasons(self):
        kb = self.kb()['knowledgeBaseId']
        url, _ = self.stub({('GET', '/robots.txt'): lambda h, b: (404, b'', {}), ('GET', '/'): lambda h, b: (500, b'', {})})
        ds = self.ba.create_data_source(knowledgeBaseId=kb, name='s', dataSourceConfiguration=self.web_source(url + '/'))['dataSource']['dataSourceId']
        job = self.ba.start_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds)['ingestionJob']
        self.app.process_job(self.p, job['ingestionJobId'])
        got = self.ba.get_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds, ingestionJobId=job['ingestionJobId'])['ingestionJob']
        self.assertIn(got['status'], ('FAILED', 'COMPLETE'))
        self.assertIsInstance(got['failureReasons'], list)

    def test_data_source_types_and_fields_refused_by_name(self):
        kb = self.kb()['knowledgeBaseId']

        def refused(fragment, **kw):
            code, status, message = self.err(self.ba.create_data_source, knowledgeBaseId=kb, name='x', **kw)
            self.assertEqual((code, status), ('ValidationException', 400), message)
            self.assertIn(fragment, message)
        refused('type SALESFORCE', dataSourceConfiguration={'type': 'SALESFORCE', 'salesforceConfiguration': {'sourceConfiguration': {
            'hostUrl': 'https://x.my.salesforce.com', 'authType': 'OAUTH2_CLIENT_CREDENTIALS', 'credentialsSecretArn': 'arn:aws:secretsmanager:us-east-1:123456789012:secret:s'}}})
        refused('type SHAREPOINT', dataSourceConfiguration={'type': 'SHAREPOINT'})
        refused('type CUSTOM', dataSourceConfiguration={'type': 'CUSTOM'})
        refused('seedUrls must hold exactly one', dataSourceConfiguration=self.web_source('http://127.0.0.1:1/') | {'webConfiguration': {'sourceConfiguration': {'urlConfiguration': {'seedUrls': [{'url': 'http://127.0.0.1:1/a'}, {'url': 'http://127.0.0.1:1/b'}]}}}})
        refused('inclusionFilters', dataSourceConfiguration={'type': 'WEB', 'webConfiguration': {'sourceConfiguration': {'urlConfiguration': {'seedUrls': [{'url': 'http://127.0.0.1:1/'}]}},
                                                                                                    'crawlerConfiguration': {'inclusionFilters': ['.*docs.*']}}})
        refused('scope SUBDOMAINS', dataSourceConfiguration={'type': 'WEB', 'webConfiguration': {'sourceConfiguration': {'urlConfiguration': {'seedUrls': [{'url': 'http://127.0.0.1:1/'}]}},
                                                                                                 'crawlerConfiguration': {'scope': 'SUBDOMAINS'}}})
        refused('vectorIngestionConfiguration', dataSourceConfiguration=self.web_source('http://127.0.0.1:1/'), vectorIngestionConfiguration={'chunkingConfiguration': {'chunkingStrategy': 'NONE'}})
        refused('dataDeletionPolicy DELETE', dataSourceConfiguration=self.web_source('http://127.0.0.1:1/'), dataDeletionPolicy='DELETE')
        refused('serverSideEncryptionConfiguration', dataSourceConfiguration=self.web_source('http://127.0.0.1:1/'), serverSideEncryptionConfiguration={'kmsKeyArn': 'arn:aws:kms:us-east-1:123456789012:key/' + 'a' * 36})
        refused('NUVORA_SECRET_', dataSourceConfiguration={'type': 'CONFLUENCE', 'confluenceConfiguration': {'sourceConfiguration': {
            'hostUrl': 'https://wiki.example.com', 'hostType': 'SAAS', 'authType': 'BASIC', 'credentialsSecretArn': 'arn:aws:secretsmanager:us-east-1:123456789012:secret:plain'}}})
        refused('bucketArn', dataSourceConfiguration={'type': 'S3', 's3Configuration': {'bucketArn': 'not-an-arn'}})
        self.assertEqual(self.err(self.ba.create_data_source, knowledgeBaseId=kb, name='h', dataSourceConfiguration=self.web_source('http://elsewhere.example/'))[:2], ('AccessDeniedException', 403))

    def test_s3_and_confluence_data_sources_map_to_connectors(self):
        kb = self.kb()['knowledgeBaseId']
        s3 = self.ba.create_data_source(knowledgeBaseId=kb, name='bucket', dataSourceConfiguration={'type': 'S3', 's3Configuration': {
            'bucketArn': 'arn:aws:s3:::support-docs', 'inclusionPrefixes': ['faq/']}})['dataSource']
        connector = self.json(f"/api/connectors/{s3['dataSourceId']}")
        self.assertEqual((connector['type'], connector['bucket'], connector['prefix']), ('s3', 'support-docs', 'faq/'))
        wiki = self.ba.create_data_source(knowledgeBaseId=kb, name='wiki', dataSourceConfiguration={'type': 'CONFLUENCE', 'confluenceConfiguration': {
            'sourceConfiguration': {'hostUrl': 'https://127.0.0.1', 'hostType': 'SAAS', 'authType': 'BASIC',
                                    'credentialsSecretArn': 'arn:aws:secretsmanager:us-east-1:123456789012:secret:NUVORA_SECRET_WIKI'},
            'crawlerConfiguration': {'filterConfiguration': {'type': 'PATTERN', 'patternObjectFilter': {'filters': [{'objectType': 'Space', 'inclusionFilters': ['DOCS']}]}}}}})['dataSource']
        connector = self.json(f"/api/connectors/{wiki['dataSourceId']}")
        self.assertEqual((connector['type'], connector['space'], connector['key_env']), ('confluence', 'DOCS', 'NUVORA_SECRET_WIKI'))
        self.assertEqual(len(self.ba.list_data_sources(knowledgeBaseId=kb)['dataSourceSummaries']), 2)
        dup = self.err(self.ba.create_data_source, knowledgeBaseId=kb, name='bucket', dataSourceConfiguration={'type': 'S3', 's3Configuration': {'bucketArn': 'arn:aws:s3:::other'}})
        self.assertEqual(dup[:2], ('ConflictException', 409))

    # ---- agents ----------------------------------------------------------------------------

    def test_agent_lifecycle_prepare_and_maps_to_nuvora_agent(self):
        agent = self.agent(description='Helps', idleSessionTTLInSeconds=900, agentResourceRoleArn='arn:aws:iam::123456789012:role/agent')
        agent_id = agent['agentId']
        self.assertEqual((agent['agentVersion'], agent['agentStatus'], agent['idleSessionTTLInSeconds']), ('DRAFT', 'NOT_PREPARED', 900))
        self.assertEqual(agent['agentArn'], f'arn:nuvora:bedrock:local:a:agent/{agent_id}')
        native = self.json(f'/api/agents/{agent_id}', expect=200)
        self.assertEqual((native['name'], native['model'], native['system_prompt']), ('helper', self.demo, INSTRUCTION))
        prepared = self.ba.prepare_agent(agentId=agent_id)
        self.assertEqual((prepared['agentStatus'], prepared['agentVersion']), ('PREPARED', 'DRAFT'))
        got = self.ba.get_agent(agentId=agent['agentArn'])['agent']
        self.assertEqual((got['agentStatus'], got['foundationModel'], got['instruction']), ('PREPARED', self.demo, INSTRUCTION))
        self.assertIn('preparedAt', got)
        updated = self.ba.update_agent(agentId=agent_id, agentName='helper2', foundationModel=self.demo, agentResourceRoleArn='arn:aws:iam::123456789012:role/agent',
                                       instruction='You answer questions about refunds only. Be precise and brief.',
                                       memoryConfiguration={'enabledMemoryTypes': ['SESSION_SUMMARY']})['agent']
        self.assertEqual((updated['agentName'], updated['agentStatus']), ('helper2', 'NOT_PREPARED'))
        native = self.json(f'/api/agents/{agent_id}')
        self.assertEqual((native['name'], native['summarize_memory'], native['system_prompt'][:20]), ('helper2', True, 'You answer questions'))
        revisions = self.json(f'/api/agents/{agent_id}/versions')['items']
        self.assertGreaterEqual(len(revisions), 2)
        listed = self.ba.list_agents()['agentSummaries']
        self.assertIn(('helper2', 'DRAFT'), [(a['agentName'], a['latestAgentVersion']) for a in listed])
        self.assertEqual(self.ba.delete_agent(agentId=agent_id)['agentStatus'], 'DELETING')
        self.assertEqual(self.err(self.ba.get_agent, agentId=agent_id)[:2], ('ResourceNotFoundException', 404))
        self.json(f'/api/agents/{agent_id}', expect=404)

    def test_agent_refusals_and_validation(self):
        def refused(fragment, **kw):
            code, status, message = self.err(self.ba.create_agent, **{'agentName': 'x', 'foundationModel': self.demo, 'instruction': INSTRUCTION, **kw})
            self.assertEqual((code, status), ('ValidationException', 400), message)
            self.assertIn(fragment, message)
        refused('promptOverrideConfiguration', promptOverrideConfiguration={'promptConfigurations': [{'promptType': 'PRE_PROCESSING', 'promptState': 'DISABLED'}]})
        refused('customerEncryptionKeyArn', customerEncryptionKeyArn='arn:aws:kms:us-east-1:123456789012:key/abc')
        refused('orchestrationType CUSTOM_ORCHESTRATION', orchestrationType='CUSTOM_ORCHESTRATION')
        refused('agentCollaboration SUPERVISOR', agentCollaboration='SUPERVISOR')
        refused('storageDays', memoryConfiguration={'enabledMemoryTypes': ['SESSION_SUMMARY'], 'storageDays': 10})
        refused('no model anthropic.claude-3', foundationModel='anthropic.claude-3-sonnet-20240229-v1:0')
        refused('guardrail nope', guardrailConfiguration={'guardrailIdentifier': 'nope', 'guardrailVersion': 'DRAFT'})
        refused('foundationModel', foundationModel=self.embed_model)
        with self.assertRaises(ParamValidationError):
            self.ba.create_agent(agentName='short', foundationModel=self.demo, instruction='too short')
        self.assertEqual(self.err(self.ba.create_agent, agentName='bad name', foundationModel=self.demo)[0], 'ValidationException')
        first = self.agent('dup', clientToken=TOKEN)
        self.assertEqual(self.agent('dup', clientToken=TOKEN)['agentId'], first['agentId'])
        self.assertEqual(self.err(self.ba.create_agent, agentName='dup', foundationModel=self.demo)[:2], ('ConflictException', 409))
        record = self.agent('guarded', guardrailConfiguration={'guardrailIdentifier': self.json('/api/guardrails', {'name': 'g', 'input': {}, 'output': {}}, expect=201)['id'], 'guardrailVersion': 'DRAFT'})
        self.assertEqual(record['guardrailConfiguration']['guardrailVersion'], 'DRAFT')

    def test_alias_creates_versions_and_resolves(self):
        agent_id = self.agent()['agentId']
        self.ba.prepare_agent(agentId=agent_id)
        alias = self.ba.create_agent_alias(agentId=agent_id, agentAliasName='live', description='prod')['agentAlias']
        self.assertEqual(alias['routingConfiguration'], [{'agentVersion': '1'}])
        self.assertEqual((alias['agentAliasStatus'], len(alias['agentAliasId']), alias['aliasInvocationState']), ('PREPARED', 10, 'ACCEPT_INVOCATIONS'))
        self.assertEqual(alias['agentAliasArn'], f"arn:nuvora:bedrock:local:a:agent-alias/{agent_id}/{alias['agentAliasId']}")
        self.assertEqual(len(alias['agentAliasHistoryEvents']), 1)
        row = self.app.store.get('a', 'agent_aliases', alias['agentAliasId'])
        self.assertEqual((row['agent_id'], row['routing']), (agent_id, [{'agentVersion': '1'}]))
        same = self.ba.create_agent_alias(agentId=agent_id, agentAliasName='live2')['agentAlias']
        self.assertEqual(same['routingConfiguration'], [{'agentVersion': '1'}])
        self.ba.update_agent(agentId=agent_id, agentName='helper', foundationModel=self.demo, agentResourceRoleArn='r', instruction='A new instruction that is long enough to pass the minimum check.')
        newer = self.ba.create_agent_alias(agentId=agent_id, agentAliasName='next')['agentAlias']
        self.assertEqual(newer['routingConfiguration'], [{'agentVersion': '2'}])
        versions = self.ba.list_agent_versions(agentId=agent_id)['agentVersionSummaries']
        self.assertEqual(sorted(v['agentVersion'] for v in versions), ['1', '2', 'DRAFT'])
        v1 = self.ba.get_agent_version(agentId=agent_id, agentVersion='1')['agentVersion']
        self.assertEqual((v1['version'], v1['instruction'], v1['agentStatus']), ('1', INSTRUCTION, 'PREPARED'))
        self.assertEqual(self.ba.get_agent_version(agentId=agent_id, agentVersion='2')['agentVersion']['instruction'][:5], 'A new')
        self.assertEqual(self.ba.get_agent_version(agentId=agent_id, agentVersion='DRAFT')['agentVersion']['version'], 'DRAFT')
        moved = self.ba.update_agent_alias(agentId=agent_id, agentAliasId=alias['agentAliasId'], agentAliasName='live', routingConfiguration=[{'agentVersion': '2'}])['agentAlias']
        self.assertEqual(moved['routingConfiguration'], [{'agentVersion': '2'}])
        self.assertEqual(len(moved['agentAliasHistoryEvents']), 2)
        self.assertIn('endDate', moved['agentAliasHistoryEvents'][0])
        self.assertEqual(self.err(self.ba.update_agent_alias, agentId=agent_id, agentAliasId=alias['agentAliasId'], agentAliasName='live', routingConfiguration=[{'agentVersion': '9'}])[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.err(self.ba.update_agent_alias, agentId=agent_id, agentAliasId=alias['agentAliasId'], agentAliasName='live', routingConfiguration=[{'agentVersion': 'DRAFT'}])[0], 'ValidationException')
        self.assertEqual(self.err(self.ba.update_agent_alias, agentId=agent_id, agentAliasId=alias['agentAliasId'], agentAliasName='live',
                                   routingConfiguration=[{'agentVersion': '1', 'provisionedThroughput': 'x'}])[0], 'ValidationException')
        self.assertEqual(self.err(self.ba.create_agent_alias, agentId=agent_id, agentAliasName='live')[:2], ('ConflictException', 409))
        listed = self.ba.list_agent_aliases(agentId=agent_id, maxResults=2)
        self.assertEqual(len(listed['agentAliasSummaries']), 2)
        self.assertIn('nextToken', listed)
        self.assertEqual(self.ba.get_agent_alias(agentId=agent_id, agentAliasId=alias['agentAliasArn'])['agentAlias']['agentAliasName'], 'live')
        req = self.fake_request()
        resolved = control_agent.resolve_alias(req, agent_id, alias['agentAliasId'])
        self.assertEqual((resolved['agentVersion'], resolved['agent']['system_prompt'][:5], resolved['agent']['model']), ('2', 'A new', self.demo))
        first = control_agent.resolve_alias(req, agent_id, same['agentAliasId'])
        self.assertEqual((first['agentVersion'], first['agent']['system_prompt']), ('1', INSTRUCTION))
        draft = control_agent.resolve_alias(req, f'arn:nuvora:bedrock:local:a:agent/{agent_id}', 'TSTALIASID')
        self.assertEqual((draft['agentVersion'], draft['agentAliasId']), ('DRAFT', 'TSTALIASID'))
        self.ba.update_agent_alias(agentId=agent_id, agentAliasId=alias['agentAliasId'], agentAliasName='live', aliasInvocationState='REJECT_INVOCATIONS')
        from nuvora.bedrock.errors import BedrockError
        with self.assertRaises(BedrockError):
            control_agent.resolve_alias(self.fake_request(), agent_id, alias['agentAliasId'])
        with self.assertRaises(BedrockError):
            control_agent.resolve_alias(self.fake_request(), agent_id, 'NOSUCHALIAS')
        self.assertEqual(self.err(self.ba.delete_agent, agentId=agent_id)[:2], ('ConflictException', 409))
        self.assertEqual(self.ba.delete_agent_alias(agentId=agent_id, agentAliasId=same['agentAliasId'])['agentAliasStatus'], 'DELETING')
        self.assertEqual(self.err(self.ba.get_agent_alias, agentId=agent_id, agentAliasId=same['agentAliasId'])[:2], ('ResourceNotFoundException', 404))

    def fake_request(self):
        class Req:
            pass
        req = Req()
        req.app, req.principal, req.region = self.app, self.p, 'us-west-2'
        return req

    def test_action_groups_import_openapi_and_become_agent_tools(self):
        url, _ = self.stub({})
        agent_id = self.agent()['agentId']
        group = self.ba.create_agent_action_group(agentId=agent_id, agentVersion='DRAFT', actionGroupName='orders', description='Orders API',
                                                  apiSchema={'payload': self.spec(url)})['agentActionGroup']
        self.assertEqual((group['actionGroupState'], group['agentVersion']), ('ENABLED', 'DRAFT'))
        actions = self.json('/api/actions')['items']
        self.assertEqual([a['name'] for a in actions], ['Get an order'])
        native = self.json(f'/api/agents/{agent_id}')
        self.assertEqual(native['tools'], ['action_' + actions[0]['id']])
        self.assertEqual(self.ba.get_agent(agentId=agent_id)['agent']['agentStatus'], 'NOT_PREPARED')
        got = self.ba.get_agent_action_group(agentId=agent_id, agentVersion='DRAFT', actionGroupId=group['actionGroupId'])['agentActionGroup']
        self.assertEqual(json.loads(got['apiSchema']['payload'])['info']['title'], 'Orders')
        off = self.ba.update_agent_action_group(agentId=agent_id, agentVersion='DRAFT', actionGroupId=group['actionGroupId'], actionGroupName='orders', actionGroupState='DISABLED')['agentActionGroup']
        self.assertEqual(off['actionGroupState'], 'DISABLED')
        self.assertEqual(self.json(f'/api/agents/{agent_id}')['tools'], [])
        self.assertEqual([g['actionGroupName'] for g in self.ba.list_agent_action_groups(agentId=agent_id, agentVersion='DRAFT')['actionGroupSummaries']], ['orders'])
        self.assertEqual(self.err(self.ba.create_agent_action_group, agentId=agent_id, agentVersion='DRAFT', actionGroupName='orders', apiSchema={'payload': self.spec(url)})[:2], ('ConflictException', 409))
        self.assertEqual(len(self.json('/api/actions')['items']), 1)
        self.ba.delete_agent_action_group(agentId=agent_id, agentVersion='DRAFT', actionGroupId=group['actionGroupId'])
        self.assertEqual(self.json('/api/actions')['items'], [])
        self.assertEqual(self.err(self.ba.get_agent_action_group, agentId=agent_id, agentVersion='DRAFT', actionGroupId=group['actionGroupId'])[:2], ('ResourceNotFoundException', 404))

    # ---- InvokeAgent runs the version the alias pins ----------------------------------------------

    def runtime_client(self):
        return boto3.client('bedrock-agent-runtime', endpoint_url=self.url, region_name='us-east-1', aws_access_key_id=self.cred['access_key_id'],
                            aws_secret_access_key=self.cred['secret_access_key'], config=Config(retries={'max_attempts': 1}))

    def invoke(self, agent_id, alias, **kw):
        out = self.runtime_client().invoke_agent(agentId=agent_id, agentAliasId=alias, sessionId='sess-1', inputText='hello', **kw)
        text, traces = '', []
        for event in out['completion']:
            if 'chunk' in event:
                text += event['chunk']['bytes'].decode()
            elif 'trace' in event:
                traces.append(event['trace'])
        return text, traces

    def scripted(self):
        """A chat provider that reports what the agent job handed it: system prompt, tool names, model."""
        seen = []

        def chat(model, messages, tools, maximum, temp):
            names = sorted(t['function']['name'] for t in tools or [])
            seen.append({'model': model, 'system': messages[0]['content'], 'tools': names})
            return {'content': f"system={messages[0]['content'][:20]}|tools={','.join(names)}", 'tool_calls': [], 'usage': {}, 'evidence_class': 'scripted'}
        original = self.app.providers.chat
        self.app.providers.chat = chat
        self.addCleanup(setattr, self.app.providers, 'chat', original)
        return seen

    def test_invoke_agent_runs_the_version_the_alias_pins(self):
        url, _ = self.stub({})
        kb = self.kb()
        agent_id = self.agent()['agentId']
        self.ba.create_agent_action_group(agentId=agent_id, agentVersion='DRAFT', actionGroupName='orders', apiSchema={'payload': self.spec(url)})
        self.ba.associate_agent_knowledge_base(agentId=agent_id, agentVersion='DRAFT', knowledgeBaseId=kb['knowledgeBaseId'], description='docs')
        self.ba.prepare_agent(agentId=agent_id)
        alias = self.ba.create_agent_alias(agentId=agent_id, agentAliasName='live')['agentAlias']
        self.assertEqual(alias['routingConfiguration'], [{'agentVersion': '1'}])
        pinned_tools = sorted(self.json(f'/api/agents/{agent_id}')['tools'])
        self.assertEqual(len(pinned_tools), 2)
        # edit the DRAFT after the version was pinned: new instruction, no tools, no knowledge base
        group = self.ba.list_agent_action_groups(agentId=agent_id, agentVersion='DRAFT')['actionGroupSummaries'][0]
        self.ba.update_agent_action_group(agentId=agent_id, agentVersion='DRAFT', actionGroupId=group['actionGroupId'], actionGroupName='orders', actionGroupState='DISABLED')
        self.ba.disassociate_agent_knowledge_base(agentId=agent_id, agentVersion='DRAFT', knowledgeBaseId=kb['knowledgeBaseId'])
        self.ba.update_agent(agentId=agent_id, agentName='helper', foundationModel=self.demo, agentResourceRoleArn='r',
                             instruction='A different DRAFT instruction that is long enough to be accepted.')
        self.assertEqual(self.json(f'/api/agents/{agent_id}')['tools'], [])
        seen = self.scripted()
        old, traces = self.invoke(agent_id, alias['agentAliasId'], enableTrace=True)
        new, _ = self.invoke(agent_id, 'TSTALIASID')
        self.assertEqual(seen[0]['system'], INSTRUCTION)
        self.assertEqual(seen[0]['tools'], pinned_tools)
        self.assertEqual((seen[1]['system'][:20], seen[1]['tools']), ('A different DRAFT in', []))
        self.assertNotEqual(old, new)
        self.assertEqual(traces[0]['agentVersion'], '1')
        self.assertEqual(traces[0]['agentAliasId'], alias['agentAliasId'])
        jobs = sorted((j for j in self.app.list(self.p, 'jobs') if j['type'] == 'agent'), key=lambda j: j['created'])
        self.assertEqual((jobs[0]['spec']['knowledge_ids'], jobs[1]['spec']['knowledge_ids']), ([kb['knowledgeBaseId']], []))
        # moving the alias to a newer version changes what it runs
        self.ba.prepare_agent(agentId=agent_id)
        newer = self.ba.create_agent_alias(agentId=agent_id, agentAliasName='next')['agentAlias']
        self.assertEqual(newer['routingConfiguration'], [{'agentVersion': '2'}])
        self.ba.update_agent_alias(agentId=agent_id, agentAliasId=alias['agentAliasId'], agentAliasName='live', routingConfiguration=[{'agentVersion': '2'}])
        self.invoke(agent_id, alias['agentAliasId'])
        self.assertEqual((seen[2]['system'][:20], seen[2]['tools']), ('A different DRAFT in', []))

    def test_native_agent_run_is_unchanged(self):
        agent = self.json('/api/agents', {'name': 'native', 'model': self.demo, 'tools': [], 'knowledge_ids': [], 'max_steps': 3}, expect=201)
        job = self.app.new_job(self.p, 'agent', agent['id'], {'message': 'hi'})
        self.assertEqual((job['spec']['id'], job['spec']['max_steps']), (agent['id'], 3))
        with self.assertRaises(Exception):
            self.app.new_job(self.p, 'agent', agent['id'], {'message': 'hi'}, pinned_spec={'id': 'other'})

    def test_invoke_agent_alias_errors(self):
        agent_id = self.agent()['agentId']
        runtime = self.runtime_client()

        def call(alias):
            return self.err(runtime.invoke_agent, agentId=agent_id, agentAliasId=alias, sessionId='sess-1', inputText='hi')
        self.assertEqual(call('NOSUCHALIAS')[:2], ('ResourceNotFoundException', 404))
        self.ba.prepare_agent(agentId=agent_id)
        alias = self.ba.create_agent_alias(agentId=agent_id, agentAliasName='live')['agentAlias']
        # the history of the pinned revision is gone: a clear conflict, not an internal error
        revision = self.app.store.get('a', 'agent_versions', agent_id + ':1')['agent_revision']
        self.app.store.delete('a', 'versions', f'{agent_id}:{revision}')
        code, status, message = call(alias['agentAliasId'])
        self.assertEqual((code, status), ('ConflictException', 409))
        self.assertIn('version 1', message)
        self.ba.update_agent_alias(agentId=agent_id, agentAliasId=alias['agentAliasId'], agentAliasName='live', aliasInvocationState='REJECT_INVOCATIONS')
        self.assertEqual(call(alias['agentAliasId'])[0], 'ValidationException')

    def test_invoke_agent_alias_keeps_its_action_and_refuses_one_that_is_gone(self):
        url, _ = self.stub({})
        agent_id = self.agent()['agentId']
        group = self.ba.create_agent_action_group(agentId=agent_id, agentVersion='DRAFT', actionGroupName='orders', apiSchema={'payload': self.spec(url)})['agentActionGroup']
        self.ba.prepare_agent(agentId=agent_id)
        alias = self.ba.create_agent_alias(agentId=agent_id, agentAliasName='live')['agentAlias']
        tool = self.json(f'/api/agents/{agent_id}')['tools']
        self.ba.delete_agent_action_group(agentId=agent_id, agentVersion='DRAFT', actionGroupId=group['actionGroupId'])
        self.assertEqual(self.json(f'/api/agents/{agent_id}')['tools'], [])
        seen = self.scripted()
        # the pinned version still owns the action, so the alias keeps offering it while the DRAFT does not
        self.invoke(agent_id, alias['agentAliasId'])
        self.invoke(agent_id, 'TSTALIASID')
        self.assertEqual((seen[0]['tools'], seen[1]['tools']), (tool, []))
        # an action removed behind the version's back is a clear conflict rather than a failed run
        self.app.delete(self.p, 'actions', tool[0][7:])
        code, status, message = self.err(self.runtime_client().invoke_agent, agentId=agent_id, agentAliasId=alias['agentAliasId'], sessionId='sess-1', inputText='hi')
        self.assertEqual((code, status), ('ConflictException', 409))
        self.assertIn('action that no longer exists', message)

    def test_action_group_refusals_name_the_member(self):
        url, _ = self.stub({})
        agent_id = self.agent()['agentId']

        def refused(fragment, **kw):
            code, status, message = self.err(self.ba.create_agent_action_group, agentId=agent_id, agentVersion='DRAFT', actionGroupName='g', **kw)
            self.assertEqual((code, status), ('ValidationException', 400), message)
            self.assertIn(fragment, message)
        refused('actionGroupExecutor.lambda', actionGroupExecutor={'lambda': 'arn:aws:lambda:us-east-1:123456789012:function:f'}, apiSchema={'payload': self.spec(url)})
        refused('RETURN_CONTROL', actionGroupExecutor={'customControl': 'RETURN_CONTROL'}, apiSchema={'payload': self.spec(url)})
        refused('functionSchema', functionSchema={'functions': [{'name': 'f', 'parameters': {}}]})
        refused('parentActionGroupSignature', parentActionGroupSignature='AMAZON.UserInput')
        refused('apiSchema.s3', apiSchema={'s3': {'s3BucketName': 'bucket', 's3ObjectKey': 'k.json'}})
        refused('YAML is not parsed', apiSchema={'payload': 'openapi: 3.0.0\ninfo: {}'})
        refused('servers[0].url', apiSchema={'payload': json.dumps({'openapi': '3.0.0', 'paths': {}})})
        refused('Path parameters are not supported', apiSchema={'payload': json.dumps({'openapi': '3.0.0', 'servers': [{'url': url}], 'paths': {'/o/{id}': {'get': {'operationId': 'o'}}}})})
        self.assertEqual(self.json('/api/actions')['items'], [])
        ok = self.ba.create_agent_action_group(agentId=agent_id, agentVersion='DRAFT', actionGroupName='g', apiSchema={'payload': self.spec(url)})['agentActionGroup']
        self.ba.create_agent_alias(agentId=agent_id, agentAliasName='live')
        code, raw, headers = self.request(f"/agents/{agent_id}/agentversions/1/actiongroups/{ok['actionGroupId']}", {'actionGroupName': 'g'}, method='PUT')
        self.assertEqual((code, headers['x-amzn-ErrorType']), (400, 'ValidationException'))
        self.assertIn('immutable', json.loads(raw)['message'])
        pinned = self.ba.get_agent_action_group(agentId=agent_id, agentVersion='1', actionGroupId=ok['actionGroupId'])['agentActionGroup']
        self.assertEqual(pinned['agentVersion'], '1')
        self.assertEqual(self.request(f"/agents/{agent_id}/agentversions/1/actiongroups/{ok['actionGroupId']}", method='DELETE')[0], 400)
        dev = self.agent_client(self.json('/api/aws-credentials', {'role': 'developer', 'username': 'dev'}, expect=201))
        self.assertEqual(self.err(dev.create_agent_action_group, agentId=agent_id, agentVersion='DRAFT', actionGroupName='h', apiSchema={'payload': self.spec(url)})[:2], ('AccessDeniedException', 403))

    def test_knowledge_base_association_and_full_agent_round_trip(self):
        url, _ = self.stub({})
        kb = self.kb()
        agent_id = self.agent()['agentId']
        link = self.ba.associate_agent_knowledge_base(agentId=agent_id, agentVersion='DRAFT', knowledgeBaseId=kb['knowledgeBaseArn'], description='refund docs')['agentKnowledgeBase']
        self.assertEqual((link['knowledgeBaseId'], link['knowledgeBaseState'], link['agentVersion']), (kb['knowledgeBaseId'], 'ENABLED', 'DRAFT'))
        native = self.json(f'/api/agents/{agent_id}')
        self.assertEqual((native['knowledge_ids'], 'knowledge_search' in native['tools']), ([kb['knowledgeBaseId']], True))
        self.assertEqual(self.err(self.ba.associate_agent_knowledge_base, agentId=agent_id, agentVersion='DRAFT', knowledgeBaseId=kb['knowledgeBaseId'], description='again')[:2], ('ConflictException', 409))
        self.assertEqual(self.err(self.ba.associate_agent_knowledge_base, agentId=agent_id, agentVersion='DRAFT', knowledgeBaseId='nope', description='x')[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.err(self.ba.delete_knowledge_base, knowledgeBaseId=kb['knowledgeBaseId'])[:2], ('ConflictException', 409))
        group = self.ba.create_agent_action_group(agentId=agent_id, agentVersion='DRAFT', actionGroupName='orders', apiSchema={'payload': self.spec(url)})['agentActionGroup']
        self.ba.prepare_agent(agentId=agent_id)
        alias = self.ba.create_agent_alias(agentId=agent_id, agentAliasName='prod')['agentAlias']
        self.assertEqual(alias['routingConfiguration'], [{'agentVersion': '1'}])
        listed = self.ba.list_agent_knowledge_bases(agentId=agent_id, agentVersion='1')['agentKnowledgeBaseSummaries']
        self.assertEqual([k['knowledgeBaseId'] for k in listed], [kb['knowledgeBaseId']])
        self.assertEqual(self.ba.get_agent_knowledge_base(agentId=agent_id, agentVersion='1', knowledgeBaseId=kb['knowledgeBaseId'])['agentKnowledgeBase']['agentVersion'], '1')
        off = self.ba.update_agent_knowledge_base(agentId=agent_id, agentVersion='DRAFT', knowledgeBaseId=kb['knowledgeBaseId'], knowledgeBaseState='DISABLED')['agentKnowledgeBase']
        self.assertEqual(off['knowledgeBaseState'], 'DISABLED')
        native = self.json(f'/api/agents/{agent_id}')
        self.assertEqual((native['knowledge_ids'], 'knowledge_search' in native['tools']), ([], False))
        resolved = control_agent.resolve_alias(self.fake_request(), agent_id, alias['agentAliasId'])
        self.assertEqual([k['knowledgeBaseId'] for k in resolved['knowledgeBases']], [kb['knowledgeBaseId']])
        self.assertEqual([g['actionGroupId'] for g in resolved['actionGroups']], [group['actionGroupId']])
        self.assertEqual(resolved['agent']['knowledge_ids'], [kb['knowledgeBaseId']])
        self.assertEqual(self.request(f"/agents/{agent_id}/agentversions/1/knowledgebases/{kb['knowledgeBaseId']}", method='DELETE')[0], 400)
        self.ba.disassociate_agent_knowledge_base(agentId=agent_id, agentVersion='DRAFT', knowledgeBaseId=kb['knowledgeBaseId'])
        self.assertEqual(self.err(self.ba.get_agent_knowledge_base, agentId=agent_id, agentVersion='DRAFT', knowledgeBaseId=kb['knowledgeBaseId'])[:2], ('ResourceNotFoundException', 404))
        self.ba.delete_agent(agentId=agent_id, skipResourceInUseCheck=True)
        self.assertEqual(self.app.store.list('a', 'agent_aliases'), [])
        self.assertEqual(self.app.store.list('a', 'agent_action_groups'), [])
        self.assertEqual(self.json('/api/actions')['items'], [])
        self.ba.delete_knowledge_base(knowledgeBaseId=kb['knowledgeBaseId'])

    def test_client_token_replays_data_sources_and_action_groups(self):
        url, _ = self.stub({})
        kb = self.kb()['knowledgeBaseId']
        config = self.web_source(url + '/')
        one = self.ba.create_data_source(knowledgeBaseId=kb, name='s', clientToken=TOKEN, dataSourceConfiguration=config)['dataSource']
        two = self.ba.create_data_source(knowledgeBaseId=kb, name='s', clientToken=TOKEN, dataSourceConfiguration=config)['dataSource']
        self.assertEqual(one['dataSourceId'], two['dataSourceId'])
        self.assertEqual(self.err(self.ba.create_data_source, knowledgeBaseId=kb, name='t', clientToken=TOKEN, dataSourceConfiguration=config)[:2], ('ConflictException', 409))
        agent_id = self.agent()['agentId']
        args = dict(agentId=agent_id, agentVersion='DRAFT', actionGroupName='orders', clientToken=TOKEN, apiSchema={'payload': self.spec(url)})
        group = self.ba.create_agent_action_group(**args)['agentActionGroup']
        self.assertEqual(self.ba.create_agent_action_group(**args)['agentActionGroup']['actionGroupId'], group['actionGroupId'])
        self.assertEqual(len(self.json('/api/actions')['items']), 1)
        alias = self.ba.create_agent_alias(agentId=agent_id, agentAliasName='a', clientToken=TOKEN)['agentAlias']
        self.assertEqual(self.ba.create_agent_alias(agentId=agent_id, agentAliasName='a', clientToken=TOKEN)['agentAlias']['agentAliasId'], alias['agentAliasId'])

    # ---- tags, routing, errors -------------------------------------------------------------

    def test_tags_on_knowledge_bases_agents_and_aliases(self):
        kb = self.kb(tags={'team': 'search'})
        self.assertEqual(self.ba.list_tags_for_resource(resourceArn=kb['knowledgeBaseArn'])['tags'], {'team': 'search'})
        self.ba.tag_resource(resourceArn=kb['knowledgeBaseArn'], tags={'env': 'dev', 'team': 'ml'})
        self.assertEqual(self.ba.list_tags_for_resource(resourceArn=kb['knowledgeBaseArn'])['tags'], {'team': 'ml', 'env': 'dev'})
        self.ba.untag_resource(resourceArn=kb['knowledgeBaseArn'], tagKeys=['team', 'env'])
        self.assertEqual(self.ba.list_tags_for_resource(resourceArn=kb['knowledgeBaseArn'])['tags'], {})
        agent = self.agent(tags={'a': '1'})
        self.ba.tag_resource(resourceArn=agent['agentArn'], tags={'b': '2'})
        self.assertEqual(self.ba.list_tags_for_resource(resourceArn=agent['agentArn'])['tags'], {'a': '1', 'b': '2'})
        self.ba.prepare_agent(agentId=agent['agentId'])
        alias = self.ba.create_agent_alias(agentId=agent['agentId'], agentAliasName='v', tags={'c': '3'})['agentAlias']
        self.assertEqual(self.ba.list_tags_for_resource(resourceArn=alias['agentAliasArn'])['tags'], {'c': '3'})
        self.ba.tag_resource(resourceArn=alias['agentAliasArn'], tags={'d': '4'})
        self.assertEqual(self.ba.list_tags_for_resource(resourceArn=alias['agentAliasArn'])['tags'], {'c': '3', 'd': '4'})
        self.assertEqual(self.err(self.ba.list_tags_for_resource, resourceArn='arn:nuvora:bedrock:us-west-2:other:agent/' + agent['agentId'])[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.err(self.ba.list_tags_for_resource, resourceArn='arn:aws:bedrock:us-east-1:123456789012:agent/ABCDEFGHIJ')[0], 'ValidationException')
        self.assertEqual(self.err(self.ba.list_tags_for_resource, resourceArn='arn:nuvora:bedrock:local:a:agent/nope')[:2], ('ResourceNotFoundException', 404))

    def test_unimplemented_and_malformed_versions(self):
        agent_id = self.agent()['agentId']
        self.assertEqual(self.err(self.ba.delete_agent_version, agentId=agent_id, agentVersion='1')[:2], ('UnsupportedOperationException', 501))
        self.assertEqual(self.err(self.ba.get_agent_version, agentId=agent_id, agentVersion='abc')[0], 'ValidationException')
        self.assertEqual(self.err(self.ba.get_agent_version, agentId=agent_id, agentVersion='7')[:2], ('ResourceNotFoundException', 404))

    def test_bearer_token_environment_variable(self):
        kb = self.kb()
        with mock.patch.dict(os.environ, {'AWS_BEARER_TOKEN_BEDROCK': self.dev}):
            try:
                client = boto3.client('bedrock-agent', endpoint_url=self.url, region_name='us-east-1', config=Config(retries={'max_attempts': 1}))
                out = client.get_knowledge_base(knowledgeBaseId=kb['knowledgeBaseId'])
            except Exception as exc:
                self.skipTest('this botocore does not support AWS_BEARER_TOKEN_BEDROCK: %s' % type(exc).__name__)
        self.assertEqual(out['knowledgeBase']['name'], 'Support')

    def test_arn_parsing(self):
        req = self.fake_request()
        self.assertEqual(control_agent.ref(req, 'agent', 'arn:nuvora:bedrock:eu-west-1:a:agent/abc123', 'x'), 'abc123')
        self.assertEqual(control_agent.ref(req, 'agent', 'abc123', 'x'), 'abc123')
        self.assertEqual(control_agent.ref(req, 'agent-alias', 'arn:nuvora:bedrock:local:a:agent-alias/AGENT/ALIAS', 'x'), 'ALIAS')
        for bad in ('arn:aws:bedrock:us-east-1:123456789012:agent/x', 'arn:nuvora:bedrock:local:a:knowledge-base/x', 'arn:nuvora:bedrock:local:a:agent'):
            with self.assertRaises(Exception):
                control_agent.ref(req, 'agent', bad, 'x')


if __name__ == '__main__':
    unittest.main()
