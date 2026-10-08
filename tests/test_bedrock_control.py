# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""bedrock control-plane operations (guardrails, inference profiles, invocation logging, model customization,
evaluation jobs, tags) through the real AWS SDK against a live server and the offline demo provider.
Skipped when boto3/botocore are not installed."""
import json
import os
import unittest
from unittest import mock

import test_evals_retrieval as ev
import test_training as tr

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
    HAVE = True
except ImportError:
    HAVE = False

FULL = {
    'name': 'support-bot', 'description': 'For the support bot',
    'topicPolicyConfig': {'topicsConfig': [{'name': 'crypto', 'definition': 'Anything about cryptocurrency', 'examples': ['buy bitcoin'], 'type': 'DENY'},
                                          {'name': 'weather', 'definition': 'Forecasts', 'type': 'DENY', 'outputEnabled': False}]},
    'contentPolicyConfig': {'filtersConfig': [{'type': 'PROMPT_ATTACK', 'inputStrength': 'HIGH', 'outputStrength': 'NONE'}]},
    'wordPolicyConfig': {'wordsConfig': [{'text': 'secretword'}, {'text': 'inbound', 'outputEnabled': False}]},
    'sensitiveInformationPolicyConfig': {
        'piiEntitiesConfig': [{'type': 'EMAIL', 'action': 'BLOCK'}, {'type': 'US_SOCIAL_SECURITY_NUMBER', 'action': 'ANONYMIZE', 'inputAction': 'BLOCK'}],
        'regexesConfig': [{'name': 'ticket', 'description': 'Ticket ids', 'pattern': 'TCK-[0-9]{4}', 'action': 'ANONYMIZE'}]},
    'contextualGroundingPolicyConfig': {'filtersConfig': [{'type': 'GROUNDING', 'threshold': 0.7}]},
    'blockedInputMessaging': 'No input.', 'blockedOutputsMessaging': 'No output.',
}


class Bearer:
    """Runs every call (and every page of a paginator) with the token in the environment."""

    def __init__(self, client, token):
        self.client, self.token = client, token

    def __getattr__(self, name):
        if name == 'get_paginator':
            return lambda op: Pages(self, self.client.get_paginator(op))

        def run(*args, **kwargs):
            with mock.patch.dict(os.environ, {'AWS_BEARER_TOKEN_BEDROCK': self.token}):
                return getattr(self.client, name)(*args, **kwargs)
        return run


class Pages:
    def __init__(self, owner, paginator):
        self.owner, self.paginator = owner, paginator

    def paginate(self, **kwargs):
        with mock.patch.dict(os.environ, {'AWS_BEARER_TOKEN_BEDROCK': self.owner.token}):
            return list(self.paginator.paginate(**kwargs))


class Base(ev.StubModels):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {'NUVORA_SECRET_KEY': 'k' * 40})
        self.env.start()
        super().setUp()
        self.cred = self.json('/api/aws-credentials', {'role': 'developer'}, expect=201)
        self.demo = next(m['id'] for m in self.app.list(self.p, 'models') if m['provider'] == 'demo')

    def tearDown(self):
        super().tearDown()
        self.env.stop()

    def bearer(self, token=None):
        """A bedrock client that sends the bearer token (botocore reads AWS_BEARER_TOKEN_BEDROCK when it signs)."""
        token = token or self.token
        try:
            with mock.patch.dict(os.environ, {'AWS_BEARER_TOKEN_BEDROCK': token}):
                client = boto3.client('bedrock', endpoint_url=self.url, region_name='us-east-1', config=Config(retries={'max_attempts': 1}))
        except Exception as exc:
            self.skipTest('this botocore does not support AWS_BEARER_TOKEN_BEDROCK: %s' % type(exc).__name__)
        return Bearer(client, token)

    def keyed(self):
        return boto3.client('bedrock', endpoint_url=self.url, region_name='us-west-2', aws_access_key_id=self.cred['access_key_id'],
                            aws_secret_access_key=self.cred['secret_access_key'], config=Config(retries={'max_attempts': 1}))

    def code(self, call, **kw):
        with self.assertRaises(ClientError) as ctx:
            call(**kw)
        e = ctx.exception.response
        return e['Error']['Code'], e['ResponseMetadata']['HTTPStatusCode'], e['Error'].get('Message', '')


@unittest.skipUnless(HAVE, 'boto3/botocore not installed')
class Guardrails(Base):
    def test_create_get_roundtrip_and_enforcement(self):
        client = self.bearer()
        made = client.create_guardrail(**FULL)
        gid = made['guardrailId']
        self.assertEqual(made['version'], 'DRAFT')
        self.assertEqual(made['guardrailArn'], f'arn:nuvora:bedrock:local:a:guardrail/{gid}')
        got = client.get_guardrail(guardrailIdentifier=made['guardrailArn'])
        self.assertEqual((got['name'], got['version'], got['status'], got['guardrailId']), ('support-bot', 'DRAFT', 'READY', gid))
        self.assertEqual((got['blockedInputMessaging'], got['blockedOutputsMessaging'], got['description']), ('No input.', 'No output.', 'For the support bot'))
        topics = {t['name']: t for t in got['topicPolicy']['topics']}
        self.assertEqual(topics['crypto']['definition'], 'Anything about cryptocurrency')
        self.assertEqual(topics['crypto']['examples'], ['buy bitcoin'])
        self.assertTrue(topics['crypto']['inputEnabled'] and topics['crypto']['outputEnabled'])
        self.assertTrue(topics['weather']['inputEnabled'] and not topics['weather']['outputEnabled'])
        attack = got['contentPolicy']['filters'][0]
        self.assertEqual((attack['type'], attack['inputStrength'], attack['outputStrength']), ('PROMPT_ATTACK', 'HIGH', 'NONE'))
        words = {w['text']: w for w in got['wordPolicy']['words']}
        self.assertEqual(sorted(words), ['inbound', 'secretword'])
        self.assertFalse(words['inbound']['outputEnabled'])
        pii = {e['type']: e for e in got['sensitiveInformationPolicy']['piiEntities']}
        self.assertEqual((pii['EMAIL']['inputAction'], pii['EMAIL']['outputAction']), ('BLOCK', 'BLOCK'))
        self.assertEqual((pii['US_SOCIAL_SECURITY_NUMBER']['inputAction'], pii['US_SOCIAL_SECURITY_NUMBER']['outputAction']), ('BLOCK', 'ANONYMIZE'))
        regex = got['sensitiveInformationPolicy']['regexes'][0]
        self.assertEqual((regex['name'], regex['description'], regex['action'], regex['pattern']), ('ticket', 'Ticket ids', 'ANONYMIZE', 'TCK-[0-9]{4}'))
        self.assertEqual(got['contextualGroundingPolicy']['filters'][0]['threshold'], 0.7)
        self.assertEqual(got['createdAt'].year >= 2024, True)
        # The stored resource is the N2 resource, and it enforces what was asked for.
        stored = self.app.get(self.p, 'guardrails', gid)
        self.assertEqual(stored['input']['blocked_topics'], ['crypto', 'weather'])
        self.assertEqual(stored['output']['blocked_topics'], ['crypto'])
        self.assertEqual(stored['input']['strengths'], {'prompt_attack': 'HIGH'})
        self.assertEqual(stored['output']['grounding_threshold'], 0.7)
        self.assertEqual(stored['input']['pii_entities'], {'email': 'block', 'ssn': 'block'})
        self.assertEqual(stored['output']['pii_entities'], {'email': 'block', 'ssn': 'mask'})
        version = client.create_guardrail_version(guardrailIdentifier=gid, description='v1')
        self.assertEqual(version['version'], '1')
        hit = self.json(f'/api/guardrails/{gid}/apply', {'source': 'INPUT', 'content': ['tell me about crypto'], 'version': 1}, expect=200)
        self.assertEqual(hit['action'], 'GUARDRAIL_INTERVENED')
        self.assertEqual(hit['outputs'], [{'text': 'No input.'}])

    def test_versions_update_list_and_delete(self):
        client = self.bearer()
        gid = client.create_guardrail(**FULL)['guardrailId']
        self.assertEqual(client.create_guardrail_version(guardrailIdentifier=gid)['version'], '1')
        changed = {**FULL, 'topicPolicyConfig': {'topicsConfig': [{'name': 'politics', 'definition': 'Elections', 'type': 'DENY'}]}, 'blockedInputMessaging': 'Changed.'}
        updated = client.update_guardrail(guardrailIdentifier=gid, **{k: v for k, v in changed.items()})
        self.assertEqual((updated['guardrailId'], updated['version']), (gid, 'DRAFT'))
        self.assertEqual(client.create_guardrail_version(guardrailIdentifier=gid)['version'], '2')
        draft = client.get_guardrail(guardrailIdentifier=gid)
        self.assertEqual([t['name'] for t in draft['topicPolicy']['topics']], ['politics'])
        one = client.get_guardrail(guardrailIdentifier=gid, guardrailVersion='1')
        self.assertEqual((one['version'], one['blockedInputMessaging']), ('1', 'No input.'))
        self.assertEqual([t['name'] for t in one['topicPolicy']['topics']], ['crypto', 'weather'])
        everything = client.list_guardrails(guardrailIdentifier=gid)['guardrails']
        self.assertEqual(sorted(g['version'] for g in everything), ['1', '2', 'DRAFT'])
        self.assertEqual(self.code(client.get_guardrail, guardrailIdentifier=gid, guardrailVersion='9')[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.code(client.get_guardrail, guardrailIdentifier=gid, guardrailVersion='zero')[:2], ('ValidationException', 400))
        client.delete_guardrail(guardrailIdentifier=gid, guardrailVersion='1')
        self.assertEqual(self.code(client.get_guardrail, guardrailIdentifier=gid, guardrailVersion='1')[:2], ('ResourceNotFoundException', 404))
        client.get_guardrail(guardrailIdentifier=gid, guardrailVersion='2')
        client.delete_guardrail(guardrailIdentifier=gid)
        self.assertEqual(self.code(client.get_guardrail, guardrailIdentifier=gid)[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.app.store.list('a', 'guardrail_versions'), [])
        self.assertEqual(self.code(client.delete_guardrail, guardrailIdentifier=gid)[:2], ('ResourceNotFoundException', 404))

    def test_list_pagination_and_paginator(self):
        client = self.bearer()
        ids = [client.create_guardrail(**{**FULL, 'name': f'g{n}'})['guardrailId'] for n in range(5)]
        first = client.list_guardrails(maxResults=2)
        self.assertEqual(len(first['guardrails']), 2)
        self.assertIn('nextToken', first)
        seen = [g['id'] for g in first['guardrails']]
        token = first['nextToken']
        while token:
            page = client.list_guardrails(maxResults=2, nextToken=token)
            seen += [g['id'] for g in page['guardrails']]
            token = page.get('nextToken')
        self.assertEqual(seen, ids)
        self.assertEqual(sorted(g['id'] for g in (p for page in client.get_paginator('list_guardrails').paginate(PaginationConfig={'PageSize': 3}) for p in page['guardrails'])), sorted(ids))
        self.assertEqual(self.code(client.list_guardrails, nextToken='garbage')[:2], ('ValidationException', 400))
        self.assertNotIn('nextToken', client.list_guardrails(maxResults=5))

    def test_refusals_name_the_member(self):
        client = self.bearer()
        cases = [
            ({'contentPolicyConfig': {'filtersConfig': [{'type': 'INSULTS', 'inputStrength': 'LOW', 'outputStrength': 'LOW'}]}}, 'INSULTS'),
            ({'contentPolicyConfig': {'filtersConfig': [{'type': 'PROMPT_ATTACK', 'inputStrength': 'LOW', 'outputStrength': 'LOW'}]}}, 'outputStrength must be NONE'),
            ({'contentPolicyConfig': {'filtersConfig': [{'type': 'HATE', 'inputStrength': 'LOW', 'outputStrength': 'LOW'}]}}, 'real chat model'),
            ({'contentPolicyConfig': {'filtersConfig': [{'type': 'PROMPT_ATTACK', 'inputStrength': 'LOW', 'outputStrength': 'NONE'}], 'tierConfig': {'tierName': 'STANDARD'}}}, 'tierConfig'),
            ({'wordPolicyConfig': {'managedWordListsConfig': [{'type': 'PROFANITY'}]}}, 'managedWordListsConfig'),
            ({'wordPolicyConfig': {'wordsConfig': [{'text': 'x', 'inputAction': 'NONE'}]}}, 'detect mode'),
            ({'sensitiveInformationPolicyConfig': {'piiEntitiesConfig': [{'type': 'NAME', 'action': 'BLOCK'}]}}, 'NAME'),
            ({'contextualGroundingPolicyConfig': {'filtersConfig': [{'type': 'RELEVANCE', 'threshold': 0.5}]}}, 'RELEVANCE'),
            ({'kmsKeyId': 'arn:aws:kms:us-east-1:1:key/abc'}, 'kmsKeyId'),
            ({'crossRegionConfig': {'guardrailProfileIdentifier': 'us.guardrail.v1:0'}}, 'crossRegionConfig'),
            ({'topicPolicyConfig': {'topicsConfig': [{'name': 'x', 'definition': 'd', 'type': 'DENY', 'inputAction': 'NONE'}]}}, 'detect mode'),
            ({'sensitiveInformationPolicyConfig': {'regexesConfig': [{'name': 'bad', 'pattern': '(a+)+b', 'action': 'BLOCK'}]}}, 'Nested quantifiers'),
        ]
        for extra, needle in cases:
            code, status, message = self.code(client.create_guardrail, name='refused', blockedInputMessaging='x', blockedOutputsMessaging='y', **extra)
            self.assertEqual((code, status), ('ValidationException', 400), extra)
            self.assertIn(needle, message, extra)
        self.assertEqual(self.app.list(self.p, 'guardrails'), [])

    def test_content_filters_use_a_real_chat_model(self):
        classifier = self.openai_model(lambda m: '{"categories": []}', 'Classifier')
        client = self.bearer()
        body = {**FULL, 'contentPolicyConfig': {'filtersConfig': [{'type': 'HATE', 'inputStrength': 'HIGH', 'outputStrength': 'LOW'},
                                                                  {'type': 'PROMPT_ATTACK', 'inputStrength': 'MEDIUM', 'outputStrength': 'NONE'}]}}
        gid = client.create_guardrail(**body)['guardrailId']
        stored = self.app.get(self.p, 'guardrails', gid)
        self.assertEqual(stored['input']['classifier_model'], classifier)
        self.assertEqual(stored['input']['strengths'], {'hate': 'HIGH', 'prompt_attack': 'MEDIUM'})
        self.assertEqual(stored['output']['strengths'], {'hate': 'LOW', 'prompt_attack': 'NONE'})
        filters = {f['type']: f for f in client.get_guardrail(guardrailIdentifier=gid)['contentPolicy']['filters']}
        self.assertEqual((filters['HATE']['inputStrength'], filters['HATE']['outputStrength']), ('HIGH', 'LOW'))
        self.assertEqual(filters['PROMPT_ATTACK']['outputEnabled'], False)

    def test_conflicts_idempotency_and_native_edits(self):
        client = self.bearer()
        token = 'a' * 40
        first = client.create_guardrail(**FULL, clientRequestToken=token)
        again = client.create_guardrail(**FULL, clientRequestToken=token)
        self.assertEqual(first['guardrailId'], again['guardrailId'])
        self.assertEqual(len(self.app.list(self.p, 'guardrails')), 1)
        self.assertEqual(self.code(client.create_guardrail, **FULL)[:2], ('ConflictException', 409))
        self.assertEqual(self.code(client.create_guardrail, **{**FULL, 'name': 'other'}, clientRequestToken=token)[:2], ('ConflictException', 409))
        self.assertEqual(self.code(client.create_guardrail, **{**FULL, 'name': 'bad/name'})[:2], ('ValidationException', 400))
        v = client.create_guardrail_version(guardrailIdentifier=first['guardrailId'], clientRequestToken='b' * 40)
        self.assertEqual(client.create_guardrail_version(guardrailIdentifier=first['guardrailId'], clientRequestToken='b' * 40)['version'], v['version'])
        # An edit through the native API shows up in GetGuardrail (the view is derived, not cached).
        g = self.app.get(self.p, 'guardrails', first['guardrailId'])
        self.json('/api/guardrails/' + g['id'], {'name': 'support-bot', 'input': {'blocked_topics': ['sports']}, 'expected_revision': g['revision']}, expect=201)
        names = [t['name'] for t in client.get_guardrail(guardrailIdentifier=g['id'])['topicPolicy']['topics']]
        self.assertEqual(names, ['sports'])

    def test_roles_and_tenant_isolation(self):
        gid = self.bearer().create_guardrail(**FULL)['guardrailId']
        keyed = self.keyed()   # SigV4 keys are capped at the developer role
        self.assertEqual(keyed.get_guardrail(guardrailIdentifier=gid)['name'], 'support-bot')
        self.assertEqual(len(keyed.list_guardrails()['guardrails']), 1)
        for call, kw in ((keyed.create_guardrail, FULL), (keyed.update_guardrail, {**FULL, 'guardrailIdentifier': gid}), (keyed.delete_guardrail, {'guardrailIdentifier': gid}),
                         (keyed.create_guardrail_version, {'guardrailIdentifier': gid}), (keyed.tag_resource, {'resourceARN': f'arn:nuvora:bedrock:us-west-2:a:guardrail/{gid}', 'tags': [{'key': 'k', 'value': 'v'}]})):
            self.assertEqual(self.code(call, **kw)[:2], ('AccessDeniedException', 403))
        viewer = self.bearer(self.viewer)
        self.assertEqual(viewer.get_guardrail(guardrailIdentifier=gid)['name'], 'support-bot')
        self.assertEqual(self.code(viewer.delete_guardrail, guardrailIdentifier=gid)[:2], ('AccessDeniedException', 403))
        self.assertEqual(self.code(self.bearer().get_guardrail, guardrailIdentifier=f'arn:nuvora:bedrock:us-east-1:other:guardrail/{gid}')[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.code(self.bearer().get_guardrail, guardrailIdentifier=f'arn:nuvora:bedrock:local:a:inference-profile/{gid}')[:2], ('ValidationException', 400))
        self.assertEqual(self.code(self.bearer().get_guardrail, guardrailIdentifier='arn:aws:bedrock:us-east-1:a:guardrail/x')[:2], ('ValidationException', 400))
        actions = [json.loads(r['event'])['action'] for r in self.store.db.execute('SELECT event FROM audit WHERE tenant=?', ('a',)).fetchall()]
        self.assertIn('guardrails.saved', actions)

    def test_tags(self):
        client = self.bearer()
        gid = client.create_guardrail(**FULL, tags=[{'key': 'team', 'value': 'support'}])['guardrailId']
        arn = f'arn:nuvora:bedrock:local:a:guardrail/{gid}'
        self.assertEqual(client.list_tags_for_resource(resourceARN=arn)['tags'], [{'key': 'team', 'value': 'support'}])
        client.tag_resource(resourceARN=arn, tags=[{'key': 'env', 'value': 'prod'}, {'key': 'team', 'value': 'ops'}])
        self.assertEqual(client.list_tags_for_resource(resourceARN=arn)['tags'], [{'key': 'env', 'value': 'prod'}, {'key': 'team', 'value': 'ops'}])
        client.untag_resource(resourceARN=arn, tagKeys=['team', 'absent'])
        self.assertEqual(client.list_tags_for_resource(resourceARN=arn)['tags'], [{'key': 'env', 'value': 'prod'}])
        self.assertEqual(self.code(client.tag_resource, resourceARN=arn, tags=[{'key': 'aws:x', 'value': 'v'}])[:2], ('ValidationException', 400))
        self.assertEqual(self.code(client.tag_resource, resourceARN=f'arn:nuvora:bedrock:local:a:guardrail/nope', tags=[{'key': 'a', 'value': 'b'}])[:2], ('ResourceNotFoundException', 404))
        code, _, message = self.code(client.list_tags_for_resource, resourceARN='arn:nuvora:bedrock:local:a:evaluation-job/x')
        self.assertEqual(code, 'ValidationException')
        self.assertIn('only guardrails carry tags', message)
        client.delete_guardrail(guardrailIdentifier=gid)
        self.assertEqual(self.app.store.list('a', 'bedrock_tags'), [])


@unittest.skipUnless(HAVE, 'boto3/botocore not installed')
class ProfilesAndLogging(Base):
    def test_inference_profiles_over_routers(self):
        client = self.bearer()
        self.assertEqual(client.list_inference_profiles()['inferenceProfileSummaries'], [])
        second = self.json('/api/models', {'name': 'Second', 'provider': 'demo', 'upstream_model': 'demo'}, expect=201)['id']
        router = self.json('/api/routers', {'name': 'Tiered', 'models': [self.demo, second]}, expect=201)['id']
        listed = client.list_inference_profiles(typeEquals='APPLICATION')['inferenceProfileSummaries']
        self.assertEqual([p['inferenceProfileId'] for p in listed], [router])
        profile = listed[0]
        self.assertEqual((profile['inferenceProfileName'], profile['type'], profile['status']), ('Tiered', 'APPLICATION', 'ACTIVE'))
        self.assertEqual([m['modelArn'] for m in profile['models']], [f'arn:nuvora:bedrock:local::foundation-model/{m}' for m in (self.demo, second)])
        self.assertEqual(client.list_inference_profiles(typeEquals='SYSTEM_DEFINED')['inferenceProfileSummaries'], [])
        for ident in (router, profile['inferenceProfileArn'], 'router:' + router):
            self.assertEqual(client.get_inference_profile(inferenceProfileIdentifier=ident)['inferenceProfileId'], router)
        self.assertEqual(self.code(client.get_inference_profile, inferenceProfileIdentifier='missing')[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.code(client.list_inference_profiles, nextToken='x')[0], 'ValidationException')
        # The ARN is usable as a modelId on the runtime.
        runtime = boto3.client('bedrock-runtime', endpoint_url=self.url, region_name='us-east-1', aws_access_key_id=self.cred['access_key_id'], aws_secret_access_key=self.cred['secret_access_key'])
        out = runtime.converse(modelId=profile['inferenceProfileArn'], messages=[{'role': 'user', 'content': [{'text': 'via profile'}]}])
        self.assertIn('via profile', out['output']['message']['content'][0]['text'])
        code, status, message = self.code(client.create_inference_profile, inferenceProfileName='n', modelSource={'copyFrom': profile['models'][0]['modelArn']})
        self.assertEqual((code, status), ('UnsupportedOperationException', 501))
        self.assertIn('CreateInferenceProfile', message)
        self.assertEqual(self.code(client.delete_inference_profile, inferenceProfileIdentifier=router)[:2], ('UnsupportedOperationException', 501))
        self.assertEqual(len(self.app.list(self.p, 'routers')), 1)

    def test_invocation_logging_stores_only_what_it_can_honour(self):
        client = self.bearer()
        self.assertEqual(client.get_model_invocation_logging_configuration().get('loggingConfig'), None)
        self.assertEqual(self.code(client.delete_model_invocation_logging_configuration)[:2], ('ResourceNotFoundException', 404))
        for config, needle in (({'s3Config': {'bucketName': 'bucket'}}, 's3Config'),
                               ({'cloudWatchConfig': {'logGroupName': 'g', 'roleArn': 'arn:aws:iam::1:role/r' + 'x' * 5}}, 'cloudWatchConfig'),
                               ({'textDataDeliveryEnabled': True}, 'textDataDeliveryEnabled'),
                               ({'embeddingDataDeliveryEnabled': True}, 'embeddingDataDeliveryEnabled')):
            code, status, message = self.code(client.put_model_invocation_logging_configuration, loggingConfig=config)
            self.assertEqual((code, status), ('ValidationException', 400), config)
            self.assertIn(needle, message)
        self.assertEqual(client.get_model_invocation_logging_configuration().get('loggingConfig'), None)
        client.put_model_invocation_logging_configuration(loggingConfig={'textDataDeliveryEnabled': False})
        got = client.get_model_invocation_logging_configuration()['loggingConfig']
        self.assertEqual((got['textDataDeliveryEnabled'], 's3Config' in got, 'cloudWatchConfig' in got), (False, False, False))
        keyed = self.keyed()
        self.assertEqual(keyed.get_model_invocation_logging_configuration()['loggingConfig']['textDataDeliveryEnabled'], False)
        self.assertEqual(self.code(keyed.put_model_invocation_logging_configuration, loggingConfig={})[:2], ('AccessDeniedException', 403))
        client.delete_model_invocation_logging_configuration()
        self.assertEqual(client.get_model_invocation_logging_configuration().get('loggingConfig'), None)


@unittest.skipUnless(HAVE, 'boto3/botocore not installed')
class Customization(Base):
    def setUp(self):
        super().setUp()
        self.remote = {'status': 'running'}
        self.submitted = []

        def submit(handler, body):
            self.submitted.append(body)
            return 200, {'id': 't1', 'status': 'queued'}
        self.trainer, _ = self.stub({('POST', '/v1/training/jobs'): submit, ('GET', '/v1/training/jobs/t1'): lambda h, b: (200, self.remote)})
        self.trainer_env = mock.patch.dict(os.environ, {'NUVORA_TRAINER_URL': self.trainer})
        self.trainer_env.start()
        self.addCleanup(self.trainer_env.stop)
        self.base = self.openai_model(lambda m: 'base answer', 'Base')
        self.dataset = self.json('/api/datasets', {'name': 'Support', 'content': tr.chat_lines(10)}, expect=201)['id']

    def job(self, **extra):
        return {'jobName': 'tune-1', 'customModelName': 'support-ft', 'roleArn': 'arn:aws:iam::123456789012:role/tuner', 'baseModelIdentifier': self.base,
                'trainingDataConfig': {'s3Uri': f'nuvora://datasets/{self.dataset}'}, 'outputDataConfig': {'s3Uri': 'nuvora://jobs'},
                'hyperParameters': {'epochCount': '2', 'rank': '8'}, **extra}

    def test_fine_tuning_lifecycle(self):
        client = self.bearer()
        created = client.create_model_customization_job(**self.job())
        job_id = created['jobArn'].rsplit('/', 1)[1]
        self.assertEqual(created['jobArn'], f'arn:nuvora:bedrock:local:a:model-customization-job/{job_id}')
        got = client.get_model_customization_job(jobIdentifier=created['jobArn'])
        self.assertEqual((got['jobName'], got['status'], got['outputModelName'], got['customizationType']), ('tune-1', 'InProgress', 'support-ft', 'FINE_TUNING'))
        self.assertEqual(got['hyperParameters'], {'epochCount': '2', 'rank': '8'})
        self.assertEqual(got['baseModelArn'], f'arn:nuvora:bedrock:local::foundation-model/{self.base}')
        self.assertEqual(client.get_model_customization_job(jobIdentifier='tune-1')['jobArn'], created['jobArn'])
        recipe = next(r for r in self.app.list(self.p, 'recipes') if r['name'] == 'support-ft')
        self.assertEqual((recipe['method'], recipe['epochs'], recipe['rank'], recipe['dataset_id']), ('lora', 2, 8, self.dataset))
        self.app.process_job(self.p, job_id)
        self.assertEqual(self.submitted[0]['hyperparameters'], {'rank': 8, 'epochs': 2})
        self.assertEqual(client.get_model_customization_job(jobIdentifier=job_id)['status'], 'InProgress')
        self.remote = {'status': 'succeeded', 'result': {'model': 'm-ft', 'base_url': self.trainer + '/v1'}}
        self.app.poll_training()
        self.app.process_job(self.p, job_id)
        done = client.get_model_customization_job(jobIdentifier=job_id)
        self.assertEqual(done['status'], 'Completed')
        tuned = self.app.get(self.p, 'recipes', recipe['id'])['trained_model']
        self.assertEqual(done['outputModelArn'], f'arn:nuvora:bedrock:local:a:custom-model/{tuned}')
        self.assertIn('endTime', done)
        listed = client.list_model_customization_jobs()['modelCustomizationJobSummaries']
        self.assertEqual([(j['jobName'], j['status']) for j in listed], [('tune-1', 'Completed')])
        self.assertEqual(listed[0]['customModelArn'], done['outputModelArn'])
        self.assertEqual(client.list_model_customization_jobs(statusEquals='Failed')['modelCustomizationJobSummaries'], [])
        self.assertEqual(len(client.list_model_customization_jobs(nameContains='tune')['modelCustomizationJobSummaries']), 1)
        self.assertEqual(self.code(client.stop_model_customization_job, jobIdentifier=job_id)[:2], ('ConflictException', 409))

    def test_failure_and_stop(self):
        client = self.bearer()
        job_id = client.create_model_customization_job(**self.job())['jobArn'].rsplit('/', 1)[1]
        code, status, message = self.code(client.stop_model_customization_job, jobIdentifier=job_id)
        self.assertEqual((code, status), ('UnsupportedOperationException', 501))
        self.app.process_job(self.p, job_id)
        self.remote = {'status': 'failed', 'error': 'out of memory'}
        self.app.poll_training()
        failed = client.get_model_customization_job(jobIdentifier=job_id)
        self.assertEqual(failed['status'], 'Failed')
        self.assertIn('out of memory', failed['failureMessage'])

    def test_distillation(self):
        teacher = self.openai_model(lambda m: 'Teacher says: ' + m[-1]['content'], 'Teacher')
        prompts = self.json('/api/datasets', {'name': 'Prompts', 'content': tr.prompt_lines(10)}, expect=201)['id']
        client = self.bearer()
        made = client.create_model_customization_job(**self.job(jobName='distill-1', customizationType='DISTILLATION', hyperParameters={},
                                                                trainingDataConfig={'s3Uri': f'nuvora://datasets/{prompts}'},
                                                                customizationConfig={'distillationConfig': {'teacherModelConfig': {'teacherModelIdentifier': teacher}}}))
        got = client.get_model_customization_job(jobIdentifier=made['jobArn'])
        self.assertEqual(got['customizationConfig']['distillationConfig']['teacherModelConfig']['teacherModelIdentifier'], teacher)
        self.assertEqual(next(r for r in self.app.list(self.p, 'recipes') if r['name'] == 'support-ft')['method'], 'distillation')

    def test_refusals_idempotency_and_roles(self):
        client = self.bearer()
        self.recipes_before = len(self.app.list(self.p, 'recipes'))
        cases = [
            ({'customizationType': 'CONTINUED_PRE_TRAINING'}, 'CONTINUED_PRE_TRAINING'),
            ({'customizationType': 'REINFORCEMENT_FINE_TUNING'}, 'REINFORCEMENT_FINE_TUNING'),
            ({'trainingDataConfig': {'s3Uri': 's3://bucket/train.jsonl'}}, 'nuvora://datasets'),
            ({'outputDataConfig': {'s3Uri': 's3://bucket/out'}}, 'nuvora://jobs'),
            ({'hyperParameters': {'learningRate': '0.1'}}, 'hyperParameters.learningRate'),
            ({'hyperParameters': {'epochCount': '999'}}, 'epochCount'),
            ({'validationDataConfig': {'validators': [{'s3Uri': 'nuvora://datasets/x'}]}}, 'validationDataConfig'),
            ({'vpcConfig': {'subnetIds': ['s'], 'securityGroupIds': ['g']}}, 'vpcConfig'),
            ({'customModelKmsKeyId': 'arn:aws:kms:us-east-1:1:key/k'}, 'customModelKmsKeyId'),
            ({'jobTags': [{'key': 'a', 'value': 'b'}]}, 'jobTags'),
            ({'baseModelIdentifier': 'router:x'}, 'baseModelIdentifier'),
            ({'trainingDataConfig': {'s3Uri': 'nuvora://datasets/nope'}}, None),
            ({'customizationConfig': {'distillationConfig': {'teacherModelConfig': {'teacherModelIdentifier': 'x'}}}}, 'customizationConfig'),
        ]
        for extra, needle in cases:
            code, status, message = self.code(client.create_model_customization_job, **self.job(**extra))
            self.assertIn(code, ('ValidationException', 'ResourceNotFoundException'), extra)
            if needle:
                self.assertIn(needle, message, extra)
        self.assertEqual(len(self.app.list(self.p, 'recipes')), self.recipes_before)
        token = 'c' * 40
        a = client.create_model_customization_job(**self.job(clientRequestToken=token))
        self.assertEqual(client.create_model_customization_job(**self.job(clientRequestToken=token))['jobArn'], a['jobArn'])
        self.assertEqual(self.code(client.create_model_customization_job, **self.job(customModelName='other'))[:2], ('ConflictException', 409))
        self.assertEqual(self.code(self.keyed().create_model_customization_job, **self.job(jobName='dev-job'))[:2], ('AccessDeniedException', 403))
        self.assertEqual(len(self.keyed().list_model_customization_jobs()['modelCustomizationJobSummaries']), 1)
        with mock.patch.dict(os.environ, {'NUVORA_TRAINER_URL': ''}):
            self.assertEqual(self.code(client.create_model_customization_job, **self.job(jobName='no-trainer'))[:2], ('ServiceUnavailableException', 503))
        self.assertEqual(self.code(client.get_model_customization_job, jobIdentifier='missing')[:2], ('ResourceNotFoundException', 404))

    def test_pagination(self):
        client = self.bearer()
        for n in range(3):
            client.create_model_customization_job(**self.job(jobName=f'tune-{n}', customModelName=f'm{n}'))
        names = [j['jobName'] for page in client.get_paginator('list_model_customization_jobs').paginate(PaginationConfig={'PageSize': 2}, sortOrder='Ascending')
                 for j in page['modelCustomizationJobSummaries']]
        self.assertEqual(names, ['tune-0', 'tune-1', 'tune-2'])
        newest = client.list_model_customization_jobs(maxResults=1)
        self.assertEqual(newest['modelCustomizationJobSummaries'][0]['jobName'], 'tune-2')
        self.assertIn('nextToken', newest)


@unittest.skipUnless(HAVE, 'boto3/botocore not installed')
class Evaluation(Base):
    def setUp(self):
        super().setUp()
        self.judge = self.openai_model(lambda m: 'Verdict: {"score": 0.9, "reason": "ok"}')
        self.suite = self.json('/api/evaluations', {'name': 'Suite', 'model': self.demo, 'cases': [{'input': 'Keep isolates agents', 'contains': ['Keep isolates agents']},
                                                                                                     {'input': 'second', 'excludes': ['zzz']}]}, expect=201)['id']
        self.judged = self.json('/api/evaluations', {'name': 'Judged', 'model': self.demo, 'judge_model': self.judge,
                                                     'cases': [{'input': 'Who approves?', 'judge': {'criteria': 'Says someone approves'}}]}, expect=201)['id']

    def job(self, suite=None, metrics=('Nuvora.Assertions',), **extra):
        return {'jobName': 'eval-1', 'roleArn': 'arn:aws:iam::123456789012:role/eval',
                'evaluationConfig': {'automated': {'datasetMetricConfigs': [{'taskType': 'Custom', 'dataset': {'name': 'cases', 'datasetLocation': {'s3Uri': f'nuvora://evaluations/{suite or self.suite}'}},
                                                                             'metricNames': list(metrics)}]}},
                'inferenceConfig': {'models': [{'bedrockModel': {'modelIdentifier': self.demo}}]}, 'outputDataConfig': {'s3Uri': 'nuvora://jobs'}, **extra}

    def test_job_runs_the_evaluation(self):
        client = self.bearer()
        made = client.create_evaluation_job(**self.job(jobDescription='nightly'))
        job_id = made['jobArn'].rsplit('/', 1)[1]
        self.assertEqual(made['jobArn'], f'arn:nuvora:bedrock:local:a:evaluation-job/{job_id}')
        got = client.get_evaluation_job(jobIdentifier=made['jobArn'])
        self.assertEqual((got['jobName'], got['status'], got['jobType'], got['jobDescription']), ('eval-1', 'InProgress', 'Automated', 'nightly'))
        self.assertEqual(got['inferenceConfig']['models'][0]['bedrockModel']['modelIdentifier'], self.demo)
        self.assertEqual(got['evaluationConfig']['automated']['datasetMetricConfigs'][0]['metricNames'], ['Nuvora.Assertions'])
        self.assertEqual(client.list_evaluation_jobs()['jobSummaries'][0]['evaluationTaskTypes'], ['Custom'])
        self.assertEqual(self.code(client.stop_evaluation_job, jobIdentifier=job_id)[:2], ('UnsupportedOperationException', 501))
        self.app.process_job(self.p, job_id)
        done = client.get_evaluation_job(jobIdentifier='eval-1')
        self.assertEqual(done['status'], 'Completed')
        result = self.app.get(self.p, 'jobs', job_id)['result']
        self.assertEqual(result['score'], 1.0)
        self.assertEqual(self.code(client.stop_evaluation_job, jobIdentifier=job_id)[:2], ('ConflictException', 409))
        summary = client.list_evaluation_jobs(statusEquals='Completed', nameContains='eval')['jobSummaries']
        self.assertEqual([(s['jobName'], s['modelIdentifiers']) for s in summary], [('eval-1', [self.demo])])
        self.assertEqual(client.list_evaluation_jobs(statusEquals='Failed')['jobSummaries'], [])

    def test_judge_metrics_and_evaluator_model(self):
        client = self.bearer()
        made = client.create_evaluation_job(**self.job(self.judged, ('Nuvora.Assertions', 'Nuvora.Judge')))
        job_id = made['jobArn'].rsplit('/', 1)[1]
        evaluation = [e for e in self.app.list(self.p, 'evaluations') if e['name'].endswith('(Bedrock job)')][0]
        self.assertEqual(evaluation['judge_model'], self.judge)
        self.app.process_job(self.p, job_id)
        self.assertEqual(client.get_evaluation_job(jobIdentifier=job_id)['status'], 'Completed')
        other = self.openai_model(lambda m: 'Verdict: {"score": 0.1, "reason": "no"}', 'Strict judge')
        config = self.job(self.judged, ('Nuvora.Assertions', 'Nuvora.Judge'), jobName='eval-2')
        config['evaluationConfig']['automated']['evaluatorModelConfig'] = {'bedrockEvaluatorModels': [{'modelIdentifier': other}]}
        job2 = client.create_evaluation_job(**config)['jobArn'].rsplit('/', 1)[1]
        self.app.process_job(self.p, job2)
        self.assertEqual(self.app.get(self.p, 'jobs', job2)['result']['cases'][0]['judge']['score'], 0.1)

    def test_refusals_and_roles(self):
        client = self.bearer()

        def refused(needle, **kw):
            code, status, message = self.code(client.create_evaluation_job, **kw)
            self.assertEqual((code, status), ('ValidationException', 400), kw)
            self.assertIn(needle, message)
        base = self.job()
        refused('Builtin.Accuracy', **{**base, 'evaluationConfig': {'automated': {'datasetMetricConfigs': [{**base['evaluationConfig']['automated']['datasetMetricConfigs'][0], 'metricNames': ['Builtin.Accuracy']}]}}})
        refused('Nuvora.Assertions', **self.job(self.suite, ('Nuvora.Assertions', 'Nuvora.Judge')))
        refused('exactly the checks', **self.job(self.judged, ('Nuvora.Assertions',)))
        refused('taskType Summarization', **{**base, 'evaluationConfig': {'automated': {'datasetMetricConfigs': [{**base['evaluationConfig']['automated']['datasetMetricConfigs'][0], 'taskType': 'Summarization'}]}}})
        refused('human', **{**base, 'evaluationConfig': {'human': {'datasetMetricConfigs': [{'taskType': 'Custom', 'dataset': {'name': 'd'}, 'metricNames': ['m']}]}}})
        refused('s3://', **{**base, 'evaluationConfig': {'automated': {'datasetMetricConfigs': [{'taskType': 'Custom', 'dataset': {'name': 'd', 'datasetLocation': {'s3Uri': 's3://b/k'}}, 'metricNames': ['Nuvora.Assertions']}]}}})
        refused('nuvora://jobs', **{**base, 'outputDataConfig': {'s3Uri': 's3://b/out'}})
        refused('inferenceParams', **{**base, 'inferenceConfig': {'models': [{'bedrockModel': {'modelIdentifier': self.demo, 'inferenceParams': '{}'}}]}})
        refused('exactly one model', **{**base, 'inferenceConfig': {'models': [{'bedrockModel': {'modelIdentifier': self.demo}}, {'bedrockModel': {'modelIdentifier': self.demo}}]}})
        refused('precomputedInferenceSource', **{**base, 'inferenceConfig': {'models': [{'precomputedInferenceSource': {'inferenceSourceIdentifier': 'x'}}]}})
        refused('applicationType', **{**base, 'applicationType': 'RagEvaluation'})
        refused('jobTags', **{**base, 'jobTags': [{'key': 'a', 'value': 'b'}]})
        config = self.job()
        config['evaluationConfig']['automated']['evaluatorModelConfig'] = {'bedrockEvaluatorModels': [{'modelIdentifier': self.judge}]}
        refused('only used by', **config)
        self.assertEqual(self.code(client.create_evaluation_job, **self.job(jobName='x', evaluationConfig={'automated': {'datasetMetricConfigs': [
            {'taskType': 'Custom', 'dataset': {'name': 'd', 'datasetLocation': {'s3Uri': 'nuvora://evaluations/nope'}}, 'metricNames': ['Nuvora.Assertions']}]}}))[:2], ('ResourceNotFoundException', 404))
        self.assertEqual(self.code(self.keyed().create_evaluation_job, **self.job())[:2], ('AccessDeniedException', 403))
        self.assertEqual(self.app.store.list('a', 'bedrock_eval_jobs'), [])
        made = client.create_evaluation_job(**self.job(clientRequestToken='d' * 40))
        self.assertEqual(client.create_evaluation_job(**self.job(clientRequestToken='d' * 40))['jobArn'], made['jobArn'])
        self.assertEqual(self.code(client.create_evaluation_job, **self.job())[:2], ('ConflictException', 409))
        self.assertEqual(len(self.keyed().list_evaluation_jobs()['jobSummaries']), 1)


if __name__ == '__main__':
    unittest.main()
