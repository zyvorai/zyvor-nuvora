# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Bedrock front door end to end: a hand-signed SigV4 client against a live server."""
import hashlib
import hmac
import http.client
import json
import os
import time
import unittest
from unittest import mock

from harness import LiveServer
from nuvora import bedrock
from nuvora.bedrock import eventstream as es
from nuvora.bedrock.router import Response, Stream

KEY = 'k' * 40


def _h(key, msg):
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def signed_headers(ak, secret, method, target, host, body=b'', service='bedrock', region='us-east-1', when=None, extra=None):
    """An independent SigV4 signer (not the server's code path) for a path that needs no re-encoding."""
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(when or time.time()))
    headers = {'host': host, 'x-amz-date': stamp, **(extra or {})}
    path, _, query = target.partition('?')
    from urllib.parse import quote
    canon_path = quote(path, safe='/~')
    names = sorted(headers)
    canonical = '\n'.join([method, canon_path, query, ''.join(f'{n}:{headers[n]}\n' for n in names), ';'.join(names), hashlib.sha256(body).hexdigest()])
    scope = f'{stamp[:8]}/{region}/{service}/aws4_request'
    sts = '\n'.join(['AWS4-HMAC-SHA256', stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    k = _h(('AWS4' + secret).encode(), stamp[:8])
    for part in (region, service, 'aws4_request'):
        k = _h(k, part)
    sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    out = {**headers, 'Authorization': f'AWS4-HMAC-SHA256 Credential={ak}/{scope}, SignedHeaders={";".join(names)}, Signature={sig}'}
    return out


class BedrockHTTP(LiveServer):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {'NUVORA_SECRET_KEY': KEY})
        self.env.start()
        super().setUp()
        self.host = self.url.split('//')[1]
        self.cred = self.json('/api/aws-credentials', {'role': 'developer', 'label': 'test'}, expect=201)

    def tearDown(self):
        super().tearDown()
        self.env.stop()

    def call(self, method, target, body=b'', ak=None, secret=None, headers=None, **kw):
        ak = ak or self.cred['access_key_id']
        secret = secret or self.cred['secret_access_key']
        sent = headers if headers is not None else signed_headers(ak, secret, method, target, self.host, body, **kw)
        conn = http.client.HTTPConnection(self.host)
        conn.request(method, target, body or None, sent)
        r = conn.getresponse()
        data = r.read()
        out = (r.status, data, dict((k.lower(), v) for k, v in r.getheaders()))
        conn.close()
        return out

    def error(self, response, status, kind):
        code, raw, headers = response
        self.assertEqual((code, headers.get('x-amzn-errortype')), (status, kind), raw)
        self.assertIn('message', json.loads(raw))
        self.assertIn('x-amzn-requestid', headers)
        return json.loads(raw)['message']

    # credentials ----------------------------------------------------------------------------
    def test_credential_lifecycle_and_storage(self):
        self.assertTrue(self.cred['access_key_id'].startswith('NVRA'))
        self.assertEqual(len(self.cred['secret_access_key']), 40)
        listing = self.json('/api/aws-credentials', expect=200)['credentials']
        self.assertEqual([c['access_key_id'] for c in listing], [self.cred['access_key_id']])
        self.assertNotIn('secret', json.dumps(listing).lower())
        row = self.store.db.execute('SELECT secret FROM aws_credentials').fetchone()
        self.assertNotIn(self.cred['secret_access_key'], row['secret'])
        self.json('/api/aws-credentials/' + self.cred['access_key_id'], method='DELETE', expect=200)
        self.error(self.call('GET', '/foundation-models'), 403, 'UnrecognizedClientException')
        self.json('/api/aws-credentials/NVRAGONE', method='DELETE', expect=404)

    def test_issuing_needs_admin_a_key_and_a_valid_role(self):
        self.json('/api/aws-credentials', {}, token=self.dev, expect=403)
        self.json('/api/aws-credentials', {'role': 'admin'}, expect=400)
        self.json('/api/aws-credentials', {'username': 'nobody'}, expect=404)
        self.json('/api/aws-credentials', {'username': 'viewer', 'role': 'developer'}, expect=403)
        issued = self.json('/api/aws-credentials', {'username': 'viewer', 'role': 'viewer'}, expect=201)
        self.assertEqual(issued['username'], 'viewer')
        with mock.patch.dict(os.environ, {'NUVORA_SECRET_KEY': ''}):
            self.assertIn('NUVORA_SECRET_KEY', self.json('/api/aws-credentials', {}, expect=503)['error'])
        with mock.patch.dict(os.environ, {'NUVORA_SECRET_KEY': 'short'}):
            self.json('/api/aws-credentials', {}, expect=503)

    def test_without_the_key_no_signature_verifies(self):
        with mock.patch.dict(os.environ, {'NUVORA_SECRET_KEY': 'y' * 40}):
            self.error(self.call('GET', '/foundation-models'), 403, 'UnrecognizedClientException')
        self.assertEqual(self.call('GET', '/foundation-models')[0], 200)

    def test_removed_user_and_expired_credentials_stop_working(self):
        user = self.json('/api/aws-credentials', {'username': 'viewer', 'role': 'viewer'}, expect=201)
        self.assertEqual(self.call('GET', '/foundation-models', ak=user['access_key_id'], secret=user['secret_access_key'])[0], 200)
        self.json('/api/users/viewer', method='DELETE', expect=200)
        self.error(self.call('GET', '/foundation-models', ak=user['access_key_id'], secret=user['secret_access_key']), 403, 'UnrecognizedClientException')
        self.store.db.execute('UPDATE aws_credentials SET expires=? WHERE access_key_id=?', (time.time() - 1, self.cred['access_key_id']))
        self.error(self.call('GET', '/foundation-models'), 403, 'UnrecognizedClientException')

    def test_role_is_capped_by_the_users_current_role(self):
        self.auth.set_role(self.p, 'dev', 'viewer')
        user = self.json('/api/aws-credentials', {'username': 'dev', 'role': 'developer'}, expect=403)
        self.assertIn('outrank', user['error'])

    # signed requests ------------------------------------------------------------------------
    def test_list_foundation_models_signed(self):
        code, raw, headers = self.call('GET', '/foundation-models')
        self.assertEqual(code, 200, raw)
        self.assertTrue(headers['content-type'].startswith('application/json'))
        self.assertIn('x-amzn-requestid', headers)
        models = json.loads(raw)['modelSummaries']
        names = {m['modelName'] for m in models}
        self.assertIn('Offline demo', names)
        demo = next(m for m in models if m['modelName'] == 'Offline demo')
        self.assertEqual((demo['inputModalities'], demo['outputModalities'], demo['responseStreamingSupported']), (['TEXT'], ['TEXT'], True))
        self.assertEqual(demo['modelLifecycle'], {'status': 'ACTIVE'})
        image = next(m for m in models if m['modelName'] == 'Offline demo images')
        self.assertEqual(image['outputModalities'], ['IMAGE'])
        listed = self.json('/v1/models', expect=200)['data']
        self.assertEqual({m['modelId'] for m in models}, {m['id'] for m in listed if m['owned_by'] != 'nuvora-router'})

    def test_filters_and_unknown_parameters(self):
        code, raw, _ = self.call('GET', '/foundation-models?byOutputModality=IMAGE')
        self.assertEqual([m['modelName'] for m in json.loads(raw)['modelSummaries']], ['Offline demo images'])
        self.assertEqual(json.loads(self.call('GET', '/foundation-models?byProvider=nobody')[1])['modelSummaries'], [])
        self.assertEqual(json.loads(self.call('GET', '/foundation-models?byCustomizationType=FINE_TUNING')[1])['modelSummaries'], [])
        self.assertIn('bogus', self.error(self.call('GET', '/foundation-models?bogus=1'), 400, 'ValidationException'))
        self.error(self.call('GET', '/foundation-models?byOutputModality=VIDEO'), 400, 'ValidationException')

    def test_each_bedrock_service_scope_and_any_region(self):
        for service in ('bedrock', 'bedrock-runtime', 'bedrock-agent', 'bedrock-agent-runtime'):
            code, raw, _ = self.call('GET', '/foundation-models', service=service, region='ap-south-1')
            self.assertEqual(code, 200, (service, raw))  # routes come from the path, not the scope
        self.error(self.call('GET', '/foundation-models', service='s3'), 403, 'InvalidSignatureException')

    def test_rejections(self):
        target = '/foundation-models'
        good = signed_headers(self.cred['access_key_id'], self.cred['secret_access_key'], 'GET', target, self.host)
        self.error(self.call('GET', target, secret='x' * 40), 403, 'InvalidSignatureException')
        self.error(self.call('GET', target, ak='NVRAUNKNOWN0000000', secret='x' * 40), 403, 'UnrecognizedClientException')
        self.error(self.call('GET', '/foundation-models?byProvider=a', headers=good), 403, 'InvalidSignatureException')  # query changed after signing
        self.assertIn('expired', self.error(self.call('GET', target, when=time.time() - 600), 403, 'InvalidSignatureException'))
        self.assertIn('expired', self.error(self.call('GET', target, when=time.time() + 600), 403, 'InvalidSignatureException'))
        tampered = dict(good, **{'x-amz-date': time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(time.time() - 1))})
        self.error(self.call('GET', target, headers=tampered), 403, 'InvalidSignatureException')
        self.error(self.call('GET', target, headers={'host': self.host}), 403, 'MissingAuthenticationTokenException')

    def test_body_tampering_and_payload_hash_modes(self):
        body = json.dumps({'messages': []}).encode()
        sent = signed_headers(self.cred['access_key_id'], self.cred['secret_access_key'], 'POST', '/guardrail/g1/version/1/apply', self.host, body, service='bedrock-runtime')
        self.error(self.call('POST', '/guardrail/g1/version/1/apply', b'{"messages":[1]}', headers=sent), 403, 'InvalidSignatureException')
        # authenticated: the handler runs and rejects the body (no `source`)
        message = self.error(self.call('POST', '/guardrail/g1/version/1/apply', body, service='bedrock-runtime'), 400, 'ValidationException')
        self.assertIn('unsupported field messages', message)
        digest = hashlib.sha256(body).hexdigest()
        extra = {'x-amz-content-sha256': digest}
        sent = signed_headers(self.cred['access_key_id'], self.cred['secret_access_key'], 'POST', '/guardrail/g1/version/1/apply', self.host, body, service='bedrock-runtime', extra=extra)
        self.error(self.call('POST', '/guardrail/g1/version/1/apply', b'{"messages":[2]}', headers=sent), 403, 'InvalidSignatureException')
        self.error(self.call('POST', '/guardrail/g1/version/1/apply', body, headers=sent), 400, 'ValidationException')

    def test_unknown_and_recognised_operations(self):
        self.assertIn('POST /guardrail/x/nope', self.error(self.call('POST', '/guardrail/x/nope'), 404, 'UnknownOperationException'))
        self.error(self.call('DELETE', '/foundation-models'), 404, 'UnknownOperationException')
        self.error(self.call('GET', '/inference-profiles/abc'), 501, 'UnsupportedOperationException')
        message = self.error(self.call('POST', '/async-invoke', b'{}', service='bedrock-runtime'), 501, 'UnsupportedOperationException')
        self.assertIn('StartAsyncInvoke', message)
        message = self.error(self.call('POST', '/knowledgebases/kb1/retrieve', b'{}', service='bedrock-agent-runtime'), 501, 'UnsupportedOperationException')
        self.assertIn('Retrieve', message)

    def test_no_credentials_on_bedrock_roots_answers_in_bedrock_shape(self):
        conn = http.client.HTTPConnection(self.host)
        conn.request('GET', '/foundation-models')
        r = conn.getresponse()
        r.read()
        self.assertEqual((r.status, r.getheader('x-amzn-ErrorType')), (403, 'MissingAuthenticationTokenException'))
        conn.close()

    # bearer ---------------------------------------------------------------------------------
    def test_bearer_token_on_bedrock_paths(self):
        for token in (self.viewer, self.dev):
            code, raw, _ = self.call('GET', '/foundation-models', headers={'Authorization': 'Bearer ' + token, 'Host': self.host})
            self.assertEqual(code, 200, raw)
        self.error(self.call('GET', '/foundation-models', headers={'Authorization': 'Bearer nope', 'Host': self.host}), 403, 'UnrecognizedClientException')
        # shared roots (/agents) are Bedrock only when credentials are sent
        self.error(self.call('POST', '/agents', b'{}', headers={'Authorization': 'Bearer ' + self.token, 'Host': self.host}), 501, 'UnsupportedOperationException')
        self.assertEqual(self.json('/api/session', expect=200)['principal']['username'], 'owner')

    def test_console_routes_are_untouched(self):
        for path in ('/agents', '/guardrails', '/healthz'):
            conn = http.client.HTTPConnection(self.host)
            conn.request('GET', path)
            r = conn.getresponse()
            r.read()
            self.assertNotIn('x-amzn-errortype', [k.lower() for k, _ in r.getheaders()], path)
            conn.close()
        self.assertEqual(self.call('GET', '/api/session', headers={'Authorization': 'Bearer ' + self.token, 'Host': self.host})[0], 200)

    # throttling and audit ------------------------------------------------------------------
    def test_failed_signatures_are_audited_without_secrets_then_throttled(self):
        for _ in range(3):
            self.call('GET', '/foundation-models', secret='w' * 40)
        events = self.store.events('a')
        failed = [e for e in events if e['action'] == 'bedrock.auth.failed']
        self.assertEqual(len(failed), 3)
        self.assertEqual(failed[0]['target'], self.cred['access_key_id'])
        self.assertEqual(failed[0]['detail']['reason'], 'InvalidSignatureException')
        blob = json.dumps(events)
        self.assertNotIn('w' * 40, blob)
        self.assertNotIn(self.cred['secret_access_key'], blob)
        for _ in range(20):
            self.call('GET', '/foundation-models', ak='NVRAUNKNOWN0000000', secret='x' * 40)
        self.error(self.call('GET', '/foundation-models'), 429, 'ThrottlingException')
        self.assertEqual(self.json('/api/session', expect=200)['principal']['username'], 'owner')  # native API unaffected

    # streaming framing through the server -------------------------------------------------
    def test_event_stream_response(self):
        def handler(req):
            def frames():
                yield es.json_event('messageStart', {'role': 'assistant'})
                yield es.chunk_event(b'one')
                raise bedrock.errors.BedrockError('ModelStreamErrorException', 'boom')
            return Stream(frames())
        bedrock.ROUTER.register('bedrock-runtime', 'POST', '/model/{modelId}/test-stream', 'TestStream', handler)
        self.addCleanup(bedrock.ROUTER.unregister, 'TestStream')
        code, raw, headers = self.call('POST', '/model/m1/test-stream', b'{}', service='bedrock-runtime')
        self.assertEqual((code, headers['content-type']), (200, 'application/vnd.amazon.eventstream'))
        frames = es.decode(raw)
        self.assertEqual([h[':event-type'] if ':event-type' in h else h[':exception-type'] for h, _ in frames], ['messageStart', 'chunk', 'modelStreamErrorException'])

    def test_handler_receives_decoded_params_and_principal(self):
        seen = {}

        def handler(req):
            seen.update(params=req.params, principal=req.principal, region=req.region, body=req.json(), query=req.query)
            return Response({'ok': True})
        bedrock.ROUTER.register('bedrock-runtime', 'POST', '/model/{modelId}/test-echo', 'TestEcho', handler)
        self.addCleanup(bedrock.ROUTER.unregister, 'TestEcho')
        code, raw, _ = self.call('POST', '/model/anthropic.claude-v2%3A1/test-echo?x=1', b'{"a":1}', service='bedrock-runtime', region='eu-central-1')
        self.assertEqual(code, 200, raw)
        self.assertEqual(seen['params'], {'modelId': 'anthropic.claude-v2:1'})
        self.assertEqual((seen['principal']['username'], seen['principal']['role'], seen['principal']['tenant']), ('owner', 'developer', 'a'))
        self.assertEqual((seen['region'], seen['query'], seen['body']), ('eu-central-1', {'x': '1'}, {'a': 1}))
        self.error(self.call('POST', '/model/m/test-echo', b'not json', service='bedrock-runtime'), 400, 'ValidationException')


if __name__ == '__main__':
    unittest.main()
