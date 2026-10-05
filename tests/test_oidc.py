# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import base64
import hashlib
import http.client
import json
import time
import unittest
from urllib.parse import parse_qs, unquote, urlsplit

from harness import LiveServer
from nuvora import oidc
from nuvora.security import Fault

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
except ImportError:  # pragma: no cover - the sso extra is installed in CI
    rsa = None


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def num(n, size=None):
    return b64(n.to_bytes(size or (n.bit_length()+7)//8, 'big'))


class FakeIdP:
    """Signs tokens like Keycloak would; serves discovery, token and JWKS endpoints."""

    def __init__(self):
        self.rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.ec = ec.generate_private_key(ec.SECP256R1())
        self.claims = {}
        self.extra_keys = []

    def jwks(self):
        r = self.rsa.public_key().public_numbers()
        e = self.ec.public_key().public_numbers()
        return {'keys': [{'kty': 'RSA', 'kid': 'rsa1', 'n': num(r.n), 'e': num(r.e)},
                         {'kty': 'EC', 'kid': 'ec1', 'crv': 'P-256', 'x': num(e.x, 32), 'y': num(e.y, 32)}]+self.extra_keys}

    def sign(self, claims, alg='RS256', kid='rsa1'):
        head = b64(json.dumps({'alg': alg, 'kid': kid, 'typ': 'JWT'}).encode())
        body = b64(json.dumps(claims).encode())
        data = (head+'.'+body).encode()
        if alg == 'RS256':
            sig = self.rsa.sign(data, padding.PKCS1v15(), hashes.SHA256())
        elif alg == 'PS256':
            sig = self.rsa.sign(data, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
        elif alg == 'ES256':
            r, s = decode_dss_signature(self.ec.sign(data, ec.ECDSA(hashes.SHA256())))
            sig = r.to_bytes(32, 'big')+s.to_bytes(32, 'big')
        else:
            sig = b'unsigned'
        return head+'.'+body+'.'+b64(sig)


@unittest.skipIf(rsa is None, 'cryptography (sso extra) is not installed')
class OIDCTest(LiveServer):
    def setUp(self):
        super().setUp()
        self.idp = FakeIdP()
        box = {}
        self.issuer, self.calls = self.stub({
            ('GET', '/.well-known/openid-configuration'): lambda h, b: (200, {
                'issuer': box['url'], 'authorization_endpoint': box['url']+'/authorize',
                'token_endpoint': box['url']+'/token', 'jwks_uri': box['url']+'/jwks'}),
            ('GET', '/jwks'): lambda h, b: (200, self.idp.jwks()),
            ('POST', '/token'): self.token_endpoint,
        })
        box['url'] = self.issuer
        self.config = oidc.Config(self.issuer, 'nuvora', 'client-secret', roles_claim='realm_access.roles',
                                  role_map='nuvora-admins=admin,nuvora-devs=developer', default_role='viewer', default_tenant='a')
        self.auth.oidc = oidc.OIDC(self.config)
        self.groups = ['nuvora-devs']
        self.username = 'alice@example.com'
        self.token_overrides = {}

    def token_endpoint(self, handler, body):
        form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
        self.posted = form
        claims = {'iss': self.issuer, 'aud': 'nuvora', 'sub': 'u-'+self.username, 'exp': time.time()+300, 'iat': time.time(),
                  'nonce': self.nonce, 'preferred_username': self.username, 'realm_access': {'roles': self.groups}, **self.token_overrides}
        return 200, {'access_token': 'opaque', 'token_type': 'Bearer', 'id_token': self.idp.sign(claims)}

    def get(self, path, cookie=''):
        host = urlsplit(self.url).netloc
        conn = http.client.HTTPConnection(host, timeout=10)
        conn.request('GET', path, headers={'Cookie': cookie} if cookie else {})
        r = conn.getresponse()
        body = r.read()
        headers = r.getheaders()
        conn.close()
        return r.status, dict(headers), [v for k, v in headers if k.lower() == 'set-cookie'], body

    def sign_in(self, tamper=None):
        status, headers, cookies, _ = self.get('/api/auth/oidc/login')
        self.assertEqual(status, 302)
        location = headers['Location']
        query = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
        self.query, self.nonce = query, query['nonce']
        state_cookie = cookies[0].split(';')[0]
        state = query['state']
        if tamper == 'state':
            state = 'forged'
        if tamper == 'cookie':
            state_cookie = state_cookie[:-3]+'AAA'
        if tamper == 'nonce':
            self.nonce = 'other'
        return self.get('/api/auth/oidc/callback?code=abc&state='+state, state_cookie)

    def session_cookie(self, cookies):
        return next(c.split(';')[0] for c in cookies if c.startswith('nuvora_session=') and 'Max-Age=0' not in c)

    def test_providers_and_login_redirect(self):
        self.assertEqual(self.json('/api/auth/providers')['oidc']['login'], '/api/auth/oidc/login')
        status, headers, cookies, _ = self.get('/api/auth/oidc/login')
        self.assertEqual(status, 302)
        q = parse_qs(urlsplit(headers['Location']).query)
        self.assertTrue(headers['Location'].startswith(self.issuer+'/authorize?'))
        self.assertEqual(q['code_challenge_method'], ['S256'])
        self.assertEqual(q['redirect_uri'], [self.url+'/api/auth/oidc/callback'])
        self.assertIn('openid', q['scope'][0])
        self.assertIn('SameSite=Lax', cookies[0])
        self.assertIn('HttpOnly', cookies[0])

    def test_code_flow_provisions_user_with_pkce(self):
        status, headers, cookies, _ = self.sign_in()
        self.assertEqual((status, headers['Location']), (302, '/'))
        verifier = self.posted['code_verifier']
        self.assertEqual(b64(hashlib.sha256(verifier.encode()).digest()), self.query['code_challenge'])
        self.assertEqual(self.posted['client_secret'], 'client-secret')
        session = self.session_cookie(cookies)
        _, _, _, body = self.get('/api/session', session)
        principal = json.loads(body)['principal']
        self.assertEqual(principal, {'tenant': 'a', 'username': 'alice_example.com', 'role': 'developer'})
        users = {u['username']: u for u in self.json('/api/users')['users']}
        self.assertEqual(users['alice_example.com']['source'], 'sso')
        actions = [(e['actor'], e['action']) for e in self.json('/api/audit')['events']]
        self.assertIn(('oidc:alice_example.com', 'user.provisioned'), actions)
        self.assertIn(('oidc:alice_example.com', 'session.created'), actions)
        with self.assertRaises(Fault) as ctx:
            self.auth.login('a', 'alice_example.com', 'whatever-password')
        self.assertEqual(ctx.exception.status, 401)

    def test_role_syncs_on_every_login(self):
        self.sign_in()
        self.groups = ['nuvora-devs', 'nuvora-admins']
        _, _, cookies, _ = self.sign_in()
        _, _, _, body = self.get('/api/session', self.session_cookie(cookies))
        self.assertEqual(json.loads(body)['principal']['role'], 'admin')
        self.groups = []
        _, _, cookies, _ = self.sign_in()
        _, _, _, body = self.get('/api/session', self.session_cookie(cookies))
        self.assertEqual(json.loads(body)['principal']['role'], 'viewer')
        synced = [e for e in self.json('/api/audit')['events'] if e['action'] == 'user.role_synced']
        self.assertEqual([e['detail']['to'] for e in synced], ['admin', 'viewer'])

    def test_local_account_cannot_be_taken_over(self):
        self.username = 'owner'
        status, headers, cookies, _ = self.sign_in()
        self.assertEqual(status, 302)
        self.assertIn('sso_error=', headers['Location'])
        self.assertIn('local account', unquote(headers['Location']))
        self.assertFalse(any(c.startswith('nuvora_session=') for c in cookies))

    def test_tampering_and_bad_tokens_are_refused(self):
        for tamper, needle in (('state', 'does not match'), ('cookie', 'tampered'), ('nonce', 'nonce')):
            _, headers, _, _ = self.sign_in(tamper)
            self.assertIn(needle, unquote(headers['Location']), tamper)
        for override, needle in (({'aud': 'someone-else'}, 'audience'), ({'exp': time.time()-3600}, 'expired'), ({'iss': 'https://evil.example'}, 'issuer')):
            self.token_overrides = override
            _, headers, _, _ = self.sign_in()
            self.assertIn(needle, unquote(headers['Location']), override)
        _, headers, _, _ = self.get('/api/auth/oidc/callback?error=access_denied')
        self.assertIn('access_denied', unquote(headers['Location']))

    def test_no_role_means_no_access(self):
        self.auth.oidc.config.default_role = ''
        self.groups = ['unrelated']
        _, headers, _, _ = self.sign_in()
        self.assertIn('grant no Nuvora role', unquote(headers['Location']))

    def test_sso_users_cannot_change_password(self):
        _, _, cookies, _ = self.sign_in()
        token = self.session_cookie(cookies).split('=', 1)[1]
        self.json('/api/password', {'current': 'x', 'new': 'Another-long-password'}, token, expect=409)

    def claims(self, **extra):
        return {'iss': self.issuer, 'aud': 'nuvora', 'sub': 'svc-1', 'exp': time.time()+300, 'preferred_username': 'ci-bot',
                'realm_access': {'roles': ['nuvora-devs']}, **extra}

    def test_bearer_jwts_are_signature_verified(self):
        for alg, kid in (('RS256', 'rsa1'), ('PS256', 'rsa1'), ('ES256', 'ec1')):
            principal = self.json('/api/session', token=self.idp.sign(self.claims(), alg, kid), expect=200)['principal']
            self.assertEqual((principal['username'], principal['role']), ('ci-bot', 'developer'), alg)
        good = self.idp.sign(self.claims())
        head, body, sig = good.split('.')
        forged = head+'.'+b64(json.dumps(self.claims(realm_access={'roles': ['nuvora-admins']})).encode())+'.'+sig
        self.json('/api/session', token=forged, expect=401)
        self.json('/api/session', token=self.idp.sign(self.claims(), 'none'), expect=401)
        self.json('/api/session', token=self.idp.sign(self.claims(), 'HS256'), expect=401)
        self.json('/api/session', token=self.idp.sign(self.claims(aud='other')), expect=401)
        self.json('/api/session', token=self.idp.sign(self.claims(), 'RS256', 'missing'), expect=401)

    def test_rotated_key_triggers_one_jwks_refresh(self):
        self.json('/api/session', token=self.idp.sign(self.claims()), expect=200)
        fetches = lambda: sum(1 for c in self.calls if c['path'] == '/jwks')
        before = fetches()
        self.idp.rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = self.idp.sign(self.claims(), 'RS256', 'rsa2')
        r = self.idp.rsa.public_key().public_numbers()
        self.idp.extra_keys = [{'kty': 'RSA', 'kid': 'rsa2', 'n': num(r.n), 'e': num(r.e)}]
        self.json('/api/session', token=token, expect=200)
        self.assertEqual(fetches(), before+1)


class OIDCConfigTest(unittest.TestCase):
    def test_env_and_mapping(self):
        self.assertIsNone(oidc.Config.from_env({}))
        with self.assertRaises(ValueError):
            oidc.Config.from_env({'NUVORA_OIDC_ISSUER': 'https://idp.example/realms/x'})
        c = oidc.Config.from_env({'NUVORA_OIDC_ISSUER': 'https://idp.example/realms/x/', 'NUVORA_OIDC_CLIENT_ID': 'n',
                                  'NUVORA_OIDC_ROLE_MAP': 'ops=approver, bad=root', 'NUVORA_OIDC_TENANT_CLAIM': 'org', 'NUVORA_OIDC_SCOPES': 'email'})
        self.assertEqual((c.issuer, c.role_map, c.scopes), ('https://idp.example/realms/x', {'ops': 'approver'}, 'openid email'))
        provider = oidc.OIDC(c)
        self.assertEqual(provider.identity({'sub': 's', 'email': 'a@b', 'org': 'acme', 'roles': ['ops']}), ('acme', 'a_b', 'approver', c.issuer+'|s'))
        with self.assertRaises(Fault):
            provider.identity({'sub': 's', 'org': 'bad tenant!'})
        with self.assertRaises(Fault):
            provider._fetch('http://idp.example/x')
