#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""The `bedrock` control plane (guardrails, inference profiles, invocation logging, model customization,
evaluation jobs, tags) against a running Nuvora, through boto3. Writes are admin operations in Nuvora, so
they use the bearer token (AWS_BEARER_TOKEN_BEDROCK); reads also run with the access key."""
import time

from botocore.exceptions import ClientError

from _common import Skip, check, eq, error_of, expect_error, main_wrapper


def body(env, report):
    admin = env.client('bedrock', admin=True)
    viewer = env.client('bedrock')
    suffix = str(int(time.time()))[-6:]
    gid = {}

    def full(name):
        return dict(name=name, description='compat suite', blockedInputMessaging='No input.', blockedOutputsMessaging='No output.',
                    topicPolicyConfig={'topicsConfig': [{'name': 'crypto', 'definition': 'Anything about cryptocurrency', 'examples': ['buy bitcoin'], 'type': 'DENY'}]},
                    contentPolicyConfig={'filtersConfig': [{'type': 'PROMPT_ATTACK', 'inputStrength': 'HIGH', 'outputStrength': 'NONE'}]},
                    wordPolicyConfig={'wordsConfig': [{'text': 'compatsecretword'}]},
                    sensitiveInformationPolicyConfig={'piiEntitiesConfig': [{'type': 'EMAIL', 'action': 'BLOCK'}],
                                                      'regexesConfig': [{'name': 'ticket', 'description': 'ids', 'pattern': 'TCK-[0-9]{4}', 'action': 'ANONYMIZE'}]})

    def create():
        made = admin.create_guardrail(**full('compat-ctl-' + suffix))
        gid['id'], gid['arn'] = made['guardrailId'], made['guardrailArn']
        report.later(lambda: admin.delete_guardrail(guardrailIdentifier=gid['id']))
        eq(made['version'], 'DRAFT', 'version')
        return made['guardrailArn']

    report.run('bedrock', 'CreateGuardrail', create)
    if 'id' not in gid:
        return

    def get():
        got = admin.get_guardrail(guardrailIdentifier=gid['arn'])
        eq((got['status'], got['version']), ('READY', 'DRAFT'), 'status/version')
        eq(got['topicPolicy']['topics'][0]['name'], 'crypto', 'topic')
        eq(got['wordPolicy']['words'], [{'text': 'compatsecretword', 'inputAction': 'BLOCK', 'outputAction': 'BLOCK', 'inputEnabled': True, 'outputEnabled': True}], 'words')
        return 'round trips by ARN'

    report.run('bedrock', 'GetGuardrail', get)

    def update():
        spec = full('compat-ctl-' + suffix)
        spec['blockedInputMessaging'] = 'Changed.'
        admin.update_guardrail(guardrailIdentifier=gid['id'], **spec)
        eq(admin.get_guardrail(guardrailIdentifier=gid['id'])['blockedInputMessaging'], 'Changed.', 'blockedInputMessaging')
        return ''

    report.run('bedrock', 'UpdateGuardrail', update)

    def version():
        eq(admin.create_guardrail_version(guardrailIdentifier=gid['id'], description='v1')['version'], '1', 'version')
        spec = full('compat-ctl-' + suffix)
        spec['blockedInputMessaging'] = 'Changed again.'
        admin.update_guardrail(guardrailIdentifier=gid['id'], **spec)
        eq(admin.get_guardrail(guardrailIdentifier=gid['id'], guardrailVersion='1')['blockedInputMessaging'], 'Changed.', 'version 1 is immutable')
        return 'version 1 unchanged after a DRAFT edit'

    report.run('bedrock', 'CreateGuardrailVersion', version)

    def listing():
        all_versions = admin.list_guardrails(guardrailIdentifier=gid['id'])['guardrails']
        eq(sorted(g['version'] for g in all_versions), ['1', 'DRAFT'], 'versions')
        names = {g['name'] for page in admin.get_paginator('list_guardrails').paginate(maxResults=1) for g in page['guardrails']}
        check('compat-ctl-' + suffix in names, 'paginator did not reach the guardrail')
        return 'paginated with maxResults=1'

    report.run('bedrock', 'ListGuardrails', listing)
    report.run('bedrock', 'GetGuardrail (access key, read only)', lambda: eq(viewer.get_guardrail(guardrailIdentifier=gid['id'])['guardrailId'], gid['id'], 'id') or '')
    report.run('bedrock', 'CreateGuardrail (access key -> 403)', lambda: expect_error(
        viewer.create_guardrail, 'AccessDeniedException', 403, **full('compat-denied-' + suffix)) and 'writes need an admin bearer token')
    report.run('bedrock', 'CreateGuardrail (unsupported member -> 400)', lambda: expect_error(
        admin.create_guardrail, 'ValidationException', 400, **dict(full('compat-bad-' + suffix), kmsKeyId='arn:aws:kms:us-east-1:1:key/x')) and 'kmsKeyId refused by name')

    def tags():
        admin.tag_resource(resourceARN=gid['arn'], tags=[{'key': 'team', 'value': 'compat'}])
        eq(admin.list_tags_for_resource(resourceARN=gid['arn'])['tags'], [{'key': 'team', 'value': 'compat'}], 'tags')
        admin.untag_resource(resourceARN=gid['arn'], tagKeys=['team'])
        eq(admin.list_tags_for_resource(resourceARN=gid['arn'])['tags'], [], 'tags after untag')
        return 'guardrail ARNs only'

    report.run('bedrock', 'TagResource / ListTagsForResource / UntagResource', tags)

    def delete_version():
        admin.delete_guardrail(guardrailIdentifier=gid['id'], guardrailVersion='1')
        expect_error(admin.get_guardrail, 'ResourceNotFoundException', 404, guardrailIdentifier=gid['id'], guardrailVersion='1')
        return ''

    report.run('bedrock', 'DeleteGuardrail (one version)', delete_version)

    def delete_whole():
        made = admin.create_guardrail(**full('compat-del-' + suffix))
        admin.delete_guardrail(guardrailIdentifier=made['guardrailId'])
        expect_error(admin.get_guardrail, 'ResourceNotFoundException', 404, guardrailIdentifier=made['guardrailId'])
        return ''

    report.run('bedrock', 'DeleteGuardrail', delete_whole)

    # Inference profiles are read-only views of routers.
    router = {}

    def profiles():
        models = viewer.list_foundation_models()['modelSummaries']
        chat = [m['modelId'] for m in models if 'TEXT' in m['outputModalities'] and 'EMBEDDING' not in m['outputModalities']]
        check(chat, 'no chat model enabled')
        second = env.native('POST', '/api/models', {'name': 'compat-second-' + suffix, 'provider': 'demo', 'upstream_model': 'demo'}, expect=201)['id']
        report.later(lambda: env.native('DELETE', '/api/models/' + second))
        made = env.native('POST', '/api/routers', {'name': 'compat-router-' + suffix, 'models': [chat[0], second]}, expect=201)
        router['id'] = made['id']
        report.later(lambda: env.native('DELETE', '/api/routers/' + made['id']))
        listed = viewer.list_inference_profiles(typeEquals='APPLICATION')['inferenceProfileSummaries']
        mine = [p for p in listed if p['inferenceProfileId'] == made['id']]
        check(mine, 'router not listed as a profile')
        eq((mine[0]['type'], mine[0]['status']), ('APPLICATION', 'ACTIVE'), 'type/status')
        router['arn'] = mine[0]['inferenceProfileArn']
        eq(viewer.get_inference_profile(inferenceProfileIdentifier=router['arn'])['inferenceProfileId'], made['id'], 'id by ARN')
        return 'router %s listed as an APPLICATION profile' % made['id']

    report.run('bedrock', 'ListInferenceProfiles / GetInferenceProfile', profiles)
    report.run('bedrock', 'ListInferenceProfiles (SYSTEM_DEFINED is empty)', lambda: eq(viewer.list_inference_profiles(typeEquals='SYSTEM_DEFINED')['inferenceProfileSummaries'], [], 'system profiles') or '')
    report.run('bedrock', 'CreateInferenceProfile (refused)', lambda: expect_error(
        admin.create_inference_profile, 'UnsupportedOperationException', 501, inferenceProfileName='n', modelSource={'copyFrom': router.get('arn', 'arn:nuvora:bedrock:local::foundation-model/x')}) and 'recorded route, 501')

    def logging_cfg():
        eq(admin.get_model_invocation_logging_configuration().get('loggingConfig'), None, 'initial config')
        expect_error(admin.put_model_invocation_logging_configuration, 'ValidationException', 400, loggingConfig={'s3Config': {'bucketName': 'bucket'}})
        admin.put_model_invocation_logging_configuration(loggingConfig={'textDataDeliveryEnabled': False})
        report.later(lambda: admin.delete_model_invocation_logging_configuration())
        eq(admin.get_model_invocation_logging_configuration()['loggingConfig']['textDataDeliveryEnabled'], False, 'stored config')
        admin.delete_model_invocation_logging_configuration()
        return 'S3/CloudWatch delivery refused, delivers-nothing config stored'

    report.run('bedrock', 'Put/Get/DeleteModelInvocationLoggingConfiguration', logging_cfg)

    # Model customization needs the external trainer (NUVORA_TRAINER_URL); without it the job is created and then fails.
    def customization():
        models = viewer.list_foundation_models()['modelSummaries']
        base = next(m['modelId'] for m in models if 'TEXT' in m['outputModalities'] and 'EMBEDDING' not in m['outputModalities'])
        lines = '\n'.join('{"messages":[{"role":"user","content":"q%d"},{"role":"assistant","content":"a%d"}]}' % (i, i) for i in range(10))
        ds = env.native('POST', '/api/datasets', {'name': 'compat-ds-' + suffix, 'content': lines}, expect=201)['id']
        report.later(lambda: env.native('DELETE', '/api/datasets/' + ds))
        try:
            made = admin.create_model_customization_job(jobName='compat-tune-' + suffix, customModelName='compat-ft-' + suffix, roleArn='arn:aws:iam::123456789012:role/tuner',
                                                        baseModelIdentifier=base, trainingDataConfig={'s3Uri': 'nuvora://datasets/' + ds}, outputDataConfig={'s3Uri': 'nuvora://jobs'},
                                                        hyperParameters={'epochCount': '1', 'rank': '8'})
        except ClientError as e:
            if e.response['Error']['Code'] == 'ServiceUnavailableException':
                raise Skip('no trainer configured on this server (NUVORA_TRAINER_URL); Nuvora answers 503 ServiceUnavailableException')
            raise
        job_id = made['jobArn'].rsplit('/', 1)[1]
        status = None
        for _ in range(40):
            status = admin.get_model_customization_job(jobIdentifier=job_id)['status']
            if status != 'InProgress':
                break
            time.sleep(.5)
        listed = admin.list_model_customization_jobs(nameContains='compat-tune-' + suffix)['modelCustomizationJobSummaries']
        check(listed, 'job missing from list')
        return 'created; final status %s ' % status

    report.run('bedrock', 'CreateModelCustomizationJob / Get / List', customization)

    # Evaluation jobs run a Nuvora evaluation on the worker thread.
    def evaluation():
        models = viewer.list_foundation_models()['modelSummaries']
        model = next(m['modelId'] for m in models if 'TEXT' in m['outputModalities'] and 'EMBEDDING' not in m['outputModalities'])
        suite = env.native('POST', '/api/evaluations', {'name': 'compat-eval-' + suffix, 'model': model, 'cases': [{'input': 'compat prompt', 'contains': ['compat prompt']}]}, expect=201)['id']
        report.later(lambda: env.native('DELETE', '/api/evaluations/' + suite))
        made = admin.create_evaluation_job(jobName='compat-eval-' + suffix, roleArn='arn:aws:iam::123456789012:role/eval', outputDataConfig={'s3Uri': 'nuvora://jobs'},
                                           inferenceConfig={'models': [{'bedrockModel': {'modelIdentifier': model}}]},
                                           evaluationConfig={'automated': {'datasetMetricConfigs': [{'taskType': 'Custom', 'dataset': {'name': 'cases', 'datasetLocation': {'s3Uri': 'nuvora://evaluations/' + suite}},
                                                                                                    'metricNames': ['Nuvora.Assertions']}]}})
        status = 'InProgress'
        for _ in range(60):
            status = admin.get_evaluation_job(jobIdentifier=made['jobArn'])['status']
            if status != 'InProgress':
                break
            time.sleep(.5)
        eq(status, 'Completed', 'final status')
        check(any(j['jobName'] == 'compat-eval-' + suffix for j in admin.list_evaluation_jobs(statusEquals='Completed')['jobSummaries']), 'not in list')
        return 'Completed on the worker thread'

    report.run('bedrock', 'CreateEvaluationJob / Get / List', evaluation)
    report.run('bedrock', 'CreateEvaluationJob (Builtin metric refused)', lambda: expect_error(
        admin.create_evaluation_job, 'ValidationException', 400, jobName='compat-bad-' + suffix, roleArn='arn:aws:iam::123456789012:role/eval', outputDataConfig={'s3Uri': 'nuvora://jobs'},
        inferenceConfig={'models': [{'bedrockModel': {'modelIdentifier': 'x'}}]},
        evaluationConfig={'automated': {'datasetMetricConfigs': [{'taskType': 'Summarization', 'dataset': {'name': 'd'}, 'metricNames': ['Builtin.Accuracy']}]}}) and 'refused by name')


if __name__ == '__main__':
    main_wrapper('bedrock control plane compatibility', body)
