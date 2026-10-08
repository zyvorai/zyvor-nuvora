# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""The real AWS SDK against the live server. Skipped unless boto3/botocore are installed
(`pip install boto3`); the stdlib-only server never imports them."""
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
class RealSdk(LiveServer):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {'NUVORA_SECRET_KEY': 'k' * 40})
        self.env.start()
        super().setUp()
        self.cred = self.json('/api/aws-credentials', {'role': 'developer'}, expect=201)

    def tearDown(self):
        super().tearDown()
        self.env.stop()

    def client(self, service, secret=None, region='us-west-2'):
        return boto3.client(service, endpoint_url=self.url, region_name=region, aws_access_key_id=self.cred['access_key_id'],
                            aws_secret_access_key=secret or self.cred['secret_access_key'],
                            config=Config(retries={'max_attempts': 1}, user_agent_extra='nuvora-test'))

    def test_list_foundation_models_with_boto3(self):
        out = self.client('bedrock').list_foundation_models()
        self.assertEqual(out['ResponseMetadata']['HTTPStatusCode'], 200)
        names = {m['modelName'] for m in out['modelSummaries']}
        self.assertIn('Offline demo', names)
        image = self.client('bedrock').list_foundation_models(byOutputModality='IMAGE')['modelSummaries']
        self.assertEqual([m['modelName'] for m in image], ['Offline demo images'])

    def test_signature_survives_colon_model_ids_and_every_service(self):
        # A model id with ':' is percent-encoded on the wire and double-encoded in the canonical request.
        # Reaching the 404 (not an InvalidSignature) means the signature verified and the model id decoded.
        with self.assertRaises(ClientError) as ctx:
            self.client('bedrock-runtime').converse(modelId='anthropic.claude-3-5-sonnet-20240620-v1:0', messages=[{'role': 'user', 'content': [{'text': 'hi'}]}])
        self.assertEqual(ctx.exception.response['Error']['Code'], 'ResourceNotFoundException')
        self.assertEqual(ctx.exception.response['ResponseMetadata']['HTTPStatusCode'], 404)
        with self.assertRaises(ClientError) as ctx:
            self.client('bedrock-agent-runtime').retrieve(knowledgeBaseId='ABCDEFGHIJ', retrievalQuery={'text': 'q'})
        self.assertEqual(ctx.exception.response['Error']['Code'], 'UnsupportedOperationException')
        with self.assertRaises(ClientError) as ctx:
            self.client('bedrock-agent').list_agents()
        self.assertEqual(ctx.exception.response['Error']['Code'], 'UnsupportedOperationException')

    def test_wrong_secret_is_rejected_with_the_aws_error_code(self):
        with self.assertRaises(ClientError) as ctx:
            self.client('bedrock', secret='z' * 40).list_foundation_models()
        self.assertEqual((ctx.exception.response['Error']['Code'], ctx.exception.response['ResponseMetadata']['HTTPStatusCode']), ('InvalidSignatureException', 403))

    def test_any_region_is_accepted(self):
        for region in ('us-east-1', 'eu-central-1', 'ap-southeast-2'):
            self.assertEqual(self.client('bedrock', region=region).list_foundation_models()['ResponseMetadata']['HTTPStatusCode'], 200)

    def test_bearer_token_environment_variable(self):
        with mock.patch.dict(os.environ, {'AWS_BEARER_TOKEN_BEDROCK': self.dev}):
            try:
                client = boto3.client('bedrock', endpoint_url=self.url, region_name='us-east-1')
                out = client.list_foundation_models()
            except Exception as exc:  # SDKs older than bearer-token support sign with the credential chain instead
                self.skipTest('this botocore does not support AWS_BEARER_TOKEN_BEDROCK: %s' % type(exc).__name__)
        self.assertEqual(out['ResponseMetadata']['HTTPStatusCode'], 200)


if __name__ == '__main__':
    unittest.main()
