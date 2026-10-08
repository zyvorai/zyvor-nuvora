# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""SigV4 verification against the AWS signature test-suite vectors (secret AKIDEXAMPLE /
wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY, 20150830T123600Z, us-east-1, service "service")."""
import calendar
import hashlib
import hmac
import time
import unittest

from nuvora.bedrock import sigv4
from nuvora.bedrock.credentials import seal, unseal

AK = 'AKIDEXAMPLE'
SECRET = 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY'
STAMP = '20150830T123600Z'
NOW = calendar.timegm(time.strptime(STAMP, '%Y%m%dT%H%M%SZ'))
HEADERS = [('Host', 'example.amazonaws.com'), ('X-Amz-Date', STAMP)]
EMPTY = hashlib.sha256(b'').hexdigest()

# name -> (method, target, expected signature) from the AWS test suite
VECTORS = {
    'get-vanilla': ('GET', '/', '5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31'),
    'get-vanilla-query-order-key-case': ('GET', '/?Param2=value2&Param1=value1', 'b97d918cfa904a5beff61c982a1b6f458b799221646efd99d3219ec94cdf2500'),
    'get-vanilla-query': ('GET', '/?Param1=value1', 'a67d582fa61cc504c4bae71f336f98b97f1ea3c7a6bfe1b6e45aec72011b9aeb'),
    'post-vanilla': ('POST', '/', '5da7c1a2acd57cee7505fc6676e4e544621c30862966e37dddb68e92efbe5d6b'),
}


def authorization(signature, signed='host;x-amz-date', service='service', region='us-east-1', key=AK):
    return f'AWS4-HMAC-SHA256 Credential={key}/20150830/{region}/{service}/aws4_request, SignedHeaders={signed}, Signature={signature}'


def secret_for(key):
    return SECRET if key == AK else None


def check(method, target, signature, headers=HEADERS, body=b'', **kw):
    return sigv4.verify(method, target, headers + [('Authorization', authorization(signature))], body, secret_for, now=NOW, services=None, **kw)


class Vectors(unittest.TestCase):
    def test_aws_published_vectors_verify(self):
        for name, (method, target, signature) in VECTORS.items():
            with self.subTest(name):
                got = check(method, target, signature)
                self.assertEqual((got.access_key, got.region, got.service), (AK, 'us-east-1', 'service'))

    def test_canonical_request_and_string_to_sign_for_get_vanilla(self):
        canonical = sigv4.canonical_request('GET', '/', '', HEADERS, ['host', 'x-amz-date'], EMPTY)
        self.assertEqual(canonical, 'GET\n/\n\nhost:example.amazonaws.com\nx-amz-date:20150830T123600Z\n\nhost;x-amz-date\n' + EMPTY)
        self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), 'bb579772317eb040ac9ed261061d46c1f17a8133879d6129b6e1c25292927e63')
        self.assertEqual(sigv4.string_to_sign(STAMP, '20150830/us-east-1/service/aws4_request', canonical),
                         'AWS4-HMAC-SHA256\n20150830T123600Z\n20150830/us-east-1/service/aws4_request\nbb579772317eb040ac9ed261061d46c1f17a8133879d6129b6e1c25292927e63')

    def test_signing_key_vector(self):
        # Derived-key example from the AWS documentation (secret ...EXAMPLEKEY, 20150830, us-east-1, iam).
        key = sigv4.signing_key(SECRET, '20150830', 'us-east-1', 'iam')
        self.assertEqual(key.hex(), 'c4afb1cc5771d871763a393e44b703571b55cc28424d1a5e86da6ed3c154a4b9')

    def test_canonicalisation_rules(self):
        self.assertEqual(sigv4.canonical_uri('/a/./b//c/../d'), '/a/b/d')
        self.assertEqual(sigv4.canonical_uri('/model/anthropic.claude-v2%3A1/converse'), '/model/anthropic.claude-v2%253A1/converse')
        self.assertEqual(sigv4.canonical_query('b=2&a=1&a=0&c=&d=x%20y+z'), 'a=0&a=1&b=2&c=&d=x%20y%20z')
        headers = [('Host', 'h'), ('My-Header', '  a   b  '), ('my-header', 'c')]
        self.assertEqual(sigv4.canonical_headers(headers, ['host', 'my-header']), 'host:h\nmy-header:a b,c\n')

    def test_tampering_is_rejected(self):
        method, target, signature = VECTORS['post-vanilla']
        cases = {
            'body': dict(body=b'x'),
            'header value': dict(headers=[('Host', 'evil.amazonaws.com'), ('X-Amz-Date', STAMP)]),
            'path': dict(target='/other'),
            'method': dict(method='GET'),
            'query': dict(target='/?a=1'),
        }
        for name, change in cases.items():
            with self.subTest(name):
                args = dict(method=method, target=target, signature=signature)
                args.update(change)
                with self.assertRaises(sigv4.SigV4Error) as ctx:
                    check(args.pop('method'), args.pop('target'), args.pop('signature'), **args)
                self.assertEqual(ctx.exception.code, 'InvalidSignatureException')

    def test_wrong_secret_unknown_key_and_flipped_signature(self):
        method, target, signature = VECTORS['get-vanilla']
        with self.assertRaises(sigv4.SigV4Error) as ctx:
            sigv4.verify(method, target, HEADERS + [('Authorization', authorization(signature))], b'', lambda k: 'other-secret', now=NOW, services=None)
        self.assertEqual(ctx.exception.code, 'InvalidSignatureException')
        with self.assertRaises(sigv4.SigV4Error) as ctx:
            sigv4.verify(method, target, HEADERS + [('Authorization', authorization(signature, key='NOPE'))], b'', secret_for, now=NOW, services=None)
        self.assertEqual(ctx.exception.code, 'UnrecognizedClientException')
        flipped = signature[:-1] + ('0' if signature[-1] != '0' else '1')
        with self.assertRaises(sigv4.SigV4Error):
            check(method, target, flipped)

    def test_clock_skew_window(self):
        method, target, signature = VECTORS['get-vanilla']
        headers = HEADERS + [('Authorization', authorization(signature))]
        for offset, ok in ((299, True), (-299, True), (301, False), (-301, False), (86400, False)):
            with self.subTest(offset):
                call = lambda: sigv4.verify(method, target, headers, b'', secret_for, now=NOW + offset, services=None)
                if ok:
                    call()
                else:
                    with self.assertRaises(sigv4.SigV4Error) as ctx:
                        call()
                    self.assertIn('expired', ctx.exception.message)

    def test_scope_and_signed_header_checks(self):
        method, target, signature = VECTORS['get-vanilla']
        with self.assertRaises(sigv4.SigV4Error) as ctx:
            sigv4.verify(method, target, HEADERS + [('Authorization', authorization(signature, service='s3'))], b'', secret_for, now=NOW)
        self.assertIn("service 's3'", ctx.exception.message)
        for service in sigv4.SERVICES:  # any region is accepted and recorded
            got = sigv4.verify(method, target, HEADERS + [('Authorization', authorization(sigv4.sign(SECRET, method, target, HEADERS, ['host', 'x-amz-date'], EMPTY, STAMP, 'eu-west-9', service), service=service, region='eu-west-9'))], b'', secret_for, now=NOW)
            self.assertEqual((got.service, got.region), (service, 'eu-west-9'))
        for signed, text in (('x-amz-date', "'host'"), ('host', "'x-amz-date'"), ('x-amz-date;host', 'sorted')):
            with self.assertRaises(sigv4.SigV4Error) as ctx:
                sigv4.verify(method, target, HEADERS + [('Authorization', authorization(signature, signed=signed))], b'', secret_for, now=NOW, services=None)
            self.assertIn(text, ctx.exception.message)
        with self.assertRaises(sigv4.SigV4Error):  # extra header declared signed but absent
            sigv4.verify(method, target, HEADERS + [('Authorization', authorization(signature, signed='host;x-amz-date;x-extra'))], b'', secret_for, now=NOW, services=None)

    def test_payload_hash_modes(self):
        body = b'{"a":1}'
        base = [('Host', 'example.amazonaws.com'), ('X-Amz-Date', STAMP)]

        def go(extra, payload_hash, send_body):
            headers = base + extra
            signed = sorted(h[0].lower() for h in headers)
            sig = sigv4.sign(SECRET, 'POST', '/', headers, signed, payload_hash, STAMP, 'us-east-1', 'service')
            return sigv4.verify('POST', '/', headers + [('Authorization', authorization(sig, signed=';'.join(signed)))], send_body, secret_for, now=NOW, services=None)

        digest = hashlib.sha256(body).hexdigest()
        self.assertEqual(go([('X-Amz-Content-Sha256', digest)], digest, body).payload_hash, digest)
        self.assertEqual(go([('X-Amz-Content-Sha256', 'UNSIGNED-PAYLOAD')], 'UNSIGNED-PAYLOAD', b'anything').payload_hash, 'UNSIGNED-PAYLOAD')
        with self.assertRaises(sigv4.SigV4Error) as ctx:  # declared hash does not match the body that arrived
            go([('X-Amz-Content-Sha256', digest)], digest, b'tampered')
        self.assertIn('does not match the request body', ctx.exception.message)
        with self.assertRaises(sigv4.SigV4Error):
            go([('X-Amz-Content-Sha256', 'STREAMING-AWS4-HMAC-SHA256-PAYLOAD')], 'STREAMING-AWS4-HMAC-SHA256-PAYLOAD', body)

    def test_date_header_fallback_and_malformed_authorization(self):
        headers = [('Host', 'example.amazonaws.com'), ('Date', 'Sun, 30 Aug 2015 12:36:00 GMT')]
        sig = sigv4.sign(SECRET, 'GET', '/', headers, ['date', 'host'], EMPTY, STAMP, 'us-east-1', 'service')
        sigv4.verify('GET', '/', headers + [('Authorization', authorization(sig, signed='date;host'))], b'', secret_for, now=NOW, services=None)
        for bad in ('AWS4-HMAC-SHA256', 'AWS4-HMAC-SHA256 Credential=a/b, SignedHeaders=host, Signature=zz', 'Basic abc'):
            with self.assertRaises(sigv4.SigV4Error):
                sigv4.verify('GET', '/', HEADERS + [('Authorization', bad)], b'', secret_for, now=NOW, services=None)
        with self.assertRaises(sigv4.SigV4Error) as ctx:
            sigv4.verify('GET', '/', HEADERS, b'', secret_for, now=NOW)
        self.assertEqual(ctx.exception.code, 'MissingAuthenticationTokenException')
        with self.assertRaises(sigv4.SigV4Error) as ctx:  # presigned form is refused by name
            sigv4.verify('GET', '/?X-Amz-Signature=ab', HEADERS + [('Authorization', 'x')], b'', secret_for, now=NOW)
        self.assertIn('presigned', ctx.exception.message)


class SealedSecrets(unittest.TestCase):
    master = b'k' * 40

    def test_round_trip_tamper_and_binding(self):
        stored = seal(self.master, 'NVRAABC', 'super-secret-value')
        self.assertNotIn('super-secret-value', stored)
        self.assertEqual(unseal(self.master, 'NVRAABC', stored), 'super-secret-value')
        self.assertNotEqual(stored, seal(self.master, 'NVRAABC', 'super-secret-value'))  # fresh nonce
        self.assertIsNone(unseal(b'z' * 40, 'NVRAABC', stored))
        self.assertIsNone(unseal(self.master, 'NVRAOTHER', stored))
        version, nonce, cipher, tag = stored.split('.')
        self.assertIsNone(unseal(self.master, 'NVRAABC', '.'.join([version, nonce, cipher[:-2] + 'AA', tag])))
        self.assertIsNone(unseal(self.master, 'NVRAABC', 'garbage'))


if __name__ == '__main__':
    unittest.main()
