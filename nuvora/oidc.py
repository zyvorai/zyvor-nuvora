# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""OpenID Connect single sign-on: authorization code + PKCE for the console, JWKS bearer verification for APIs.

The ID token is received directly from the token endpoint over a verified TLS channel, so its
claims (iss, aud, exp, nonce) are validated without a signature check (OIDC Core 3.1.3.7).
Bearer JWTs arrive from clients and are always signature-verified against the issuer JWKS,
which needs the optional `cryptography` package (pip install 'zyvor-nuvora[sso]')."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .security import ROLES, Fault

ALGORITHMS = ('RS256','RS384','RS512','PS256','PS384','PS512','ES256','ES384')
NAME = re.compile(r'[^a-zA-Z0-9_.-]')
LOOPBACK = ('localhost','127.0.0.1','::1')
STATE_COOKIE = 'nuvora_oidc'
STATE_TTL = 600
JWKS_TTL = 600
SKEW = 60


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def unb64url(text):
    return base64.urlsafe_b64decode(text+'='*(-len(text)%4))


def claim(claims, path):
    """Read a dotted claim such as realm_access.roles."""
    value = claims
    for part in (path or '').split('.'):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def parse_role_map(text):
    mapping = {}
    for pair in (text or '').split(','):
        group, _, role = pair.strip().partition('=')
        if group and role.strip() in ROLES:
            mapping[group.strip()] = role.strip()
    return mapping


class Config:
    def __init__(self, issuer, client_id, client_secret='', redirect_url='', scopes='openid profile email',
                 roles_claim='roles', role_map='', default_role='viewer', tenant_claim='', identity_claim='preferred_username',
                 audience='', default_tenant='default', cookie_secret=''):
        self.issuer = issuer.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_url = redirect_url
        self.scopes = scopes if 'openid' in scopes.split() else 'openid '+scopes
        self.roles_claim = roles_claim
        self.role_map = parse_role_map(role_map)
        self.default_role = default_role if default_role in ROLES else ''
        self.tenant_claim = tenant_claim
        self.identity_claim = identity_claim
        self.audience = audience or client_id
        self.default_tenant = default_tenant
        key = cookie_secret or client_secret
        # Without a shared secret each replica signs with its own key, so a login must finish on the replica that started it.
        self.cookie_key = hashlib.sha256(b'nuvora-oidc-state:'+key.encode()).digest() if key else secrets.token_bytes(32)

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        issuer = env.get('NUVORA_OIDC_ISSUER', '').strip()
        if not issuer:
            return None
        client_id = env.get('NUVORA_OIDC_CLIENT_ID', '').strip()
        if not client_id:
            raise ValueError('NUVORA_OIDC_CLIENT_ID is required when NUVORA_OIDC_ISSUER is set')
        return cls(issuer, client_id, env.get('NUVORA_OIDC_CLIENT_SECRET', ''), env.get('NUVORA_OIDC_REDIRECT_URL', ''),
                   env.get('NUVORA_OIDC_SCOPES', 'openid profile email'), env.get('NUVORA_OIDC_ROLES_CLAIM', 'roles'),
                   env.get('NUVORA_OIDC_ROLE_MAP', ''), env.get('NUVORA_OIDC_DEFAULT_ROLE', 'viewer'),
                   env.get('NUVORA_OIDC_TENANT_CLAIM', ''), env.get('NUVORA_OIDC_IDENTITY_CLAIM', 'preferred_username'),
                   env.get('NUVORA_OIDC_AUDIENCE', ''), env.get('NUVORA_OIDC_DEFAULT_TENANT', 'default'),
                   env.get('NUVORA_OIDC_COOKIE_SECRET', ''))


class OIDC:
    def __init__(self, config, opener=None):
        self.config = config
        self.lock = threading.Lock()
        self._discovery = None
        self._jwks = (0.0, {})
        self.context = ssl.create_default_context()
        self.opener = opener

    # -- transport -------------------------------------------------------
    def _check_url(self, url):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme == 'https' or (parts.scheme == 'http' and parts.hostname in LOOPBACK):
            return url
        raise Fault('Identity provider endpoints must use HTTPS', 502)

    def _fetch(self, url, data=None, headers=None):
        req = urllib.request.Request(self._check_url(url), data=data, headers={'Accept':'application/json', **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=10, context=self.context if url.startswith('https') else None) as r:
                return json.loads(r.read(1024*1024))
        except urllib.error.HTTPError as exc:
            detail = ''
            try:
                detail = json.loads(exc.read(4096)).get('error', '')
            except (ValueError, AttributeError):
                pass
            raise Fault('Identity provider rejected the request'+(': '+detail if detail else ''), 502) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise Fault('Identity provider is unreachable', 502) from exc

    def discovery(self):
        with self.lock:
            if self._discovery:
                return self._discovery
        doc = self._fetch(self.config.issuer+'/.well-known/openid-configuration')
        if doc.get('issuer', '').rstrip('/') != self.config.issuer:
            raise Fault('Identity provider issuer mismatch', 502)
        for key in ('authorization_endpoint', 'token_endpoint'):
            self._check_url(doc.get(key, ''))
        with self.lock:
            self._discovery = doc
        return doc

    # -- signed, short-lived login state ---------------------------------
    def _seal(self, payload):
        body = b64url(json.dumps(payload, separators=(',', ':')).encode())
        return body+'.'+b64url(hmac.new(self.config.cookie_key, body.encode(), hashlib.sha256).digest())

    def _open(self, sealed):
        body, _, mac = (sealed or '').partition('.')
        expected = b64url(hmac.new(self.config.cookie_key, body.encode(), hashlib.sha256).digest())
        if not body or not hmac.compare_digest(mac, expected):
            raise Fault('Sign-in state is missing or was tampered with; start again', 400)
        payload = json.loads(unb64url(body))
        if payload.get('exp', 0) < time.time():
            raise Fault('Sign-in took too long; start again', 400)
        return payload

    def redirect_url(self, base):
        return self.config.redirect_url or base.rstrip('/')+'/api/auth/oidc/callback'

    def login(self, base):
        """Return (authorization URL, sealed state cookie value)."""
        doc = self.discovery()
        state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        query = {'response_type':'code', 'client_id':self.config.client_id, 'redirect_uri':self.redirect_url(base),
                 'scope':self.config.scopes, 'state':state, 'nonce':nonce,
                 'code_challenge':b64url(hashlib.sha256(verifier.encode()).digest()), 'code_challenge_method':'S256'}
        sealed = self._seal({'state':state, 'nonce':nonce, 'verifier':verifier, 'exp':time.time()+STATE_TTL})
        sep = '&' if '?' in doc['authorization_endpoint'] else '?'
        return doc['authorization_endpoint']+sep+urllib.parse.urlencode(query), sealed

    def callback(self, base, params, sealed):
        """Exchange the code and return validated ID token claims."""
        if params.get('error'):
            raise Fault('Identity provider returned '+params['error'][:80], 401)
        saved = self._open(sealed)
        if not params.get('code') or not hmac.compare_digest(params.get('state', ''), saved['state']):
            raise Fault('Sign-in state does not match; start again', 400)
        doc = self.discovery()
        form = {'grant_type':'authorization_code', 'code':params['code'], 'redirect_uri':self.redirect_url(base),
                'client_id':self.config.client_id, 'code_verifier':saved['verifier']}
        if self.config.client_secret:
            form['client_secret'] = self.config.client_secret
        tokens = self._fetch(doc['token_endpoint'], urllib.parse.urlencode(form).encode(),
                             {'Content-Type':'application/x-www-form-urlencoded'})
        if not isinstance(tokens.get('id_token'), str):
            raise Fault('Identity provider returned no ID token', 502)
        claims = self._claims(tokens['id_token'])
        self._check(claims, self.config.client_id)
        if not hmac.compare_digest(str(claims.get('nonce', '')), saved['nonce']):
            raise Fault('ID token nonce does not match', 401)
        return claims

    # -- token validation ------------------------------------------------
    @staticmethod
    def _split(token):
        try:
            head, body, sig = token.split('.')
            return json.loads(unb64url(head)), json.loads(unb64url(body)), unb64url(sig), (head+'.'+body).encode()
        except (ValueError, TypeError) as exc:
            raise Fault('Malformed token', 401) from exc

    def _claims(self, token):
        return self._split(token)[1]

    def _check(self, claims, audience):
        now = time.time()
        if str(claims.get('iss', '')).rstrip('/') != self.config.issuer:
            raise Fault('Token issuer is not trusted', 401)
        aud = claims.get('aud')
        if audience not in (aud if isinstance(aud, list) else [aud]):
            raise Fault('Token audience does not match', 401)
        if not isinstance(claims.get('exp'), (int, float)) or claims['exp'] < now-SKEW:
            raise Fault('Token has expired', 401)
        if isinstance(claims.get('nbf'), (int, float)) and claims['nbf'] > now+SKEW:
            raise Fault('Token is not valid yet', 401)

    def _keys(self, refresh=False):
        with self.lock:
            fetched, keys = self._jwks
        if keys and not refresh and time.time()-fetched < JWKS_TTL:
            return keys
        uri = self.discovery().get('jwks_uri')
        if not uri:
            raise Fault('Identity provider publishes no JWKS', 502)
        keys = {k.get('kid', ''):k for k in self._fetch(uri).get('keys', []) if isinstance(k, dict)}
        with self.lock:
            self._jwks = (time.time(), keys)
        return keys

    def verify(self, token):
        """Verify a bearer JWT signature and claims; return its claims."""
        head, claims, sig, signed = self._split(token)
        alg = head.get('alg')
        if alg not in ALGORITHMS:
            raise Fault('Token algorithm is not allowed', 401)
        keys = self._keys()
        jwk = keys.get(head.get('kid', ''))
        if jwk is None:
            jwk = self._keys(refresh=True).get(head.get('kid', ''))
        if jwk is None:
            raise Fault('Token signing key is unknown', 401)
        verify_signature(alg, jwk, signed, sig)
        self._check(claims, self.config.audience)
        return claims

    # -- identity mapping ------------------------------------------------
    def identity(self, claims):
        """Map claims to (tenant, username, role, subject)."""
        raw = claims.get(self.config.identity_claim) or claims.get('preferred_username') or claims.get('email') or claims.get('sub')
        if not isinstance(raw, str) or not raw.strip():
            raise Fault('Token carries no usable identity claim', 401)
        username = NAME.sub('_', raw.strip())[:64]
        tenant = self.config.default_tenant
        if self.config.tenant_claim:
            value = claim(claims, self.config.tenant_claim)
            if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}', value):
                raise Fault('Token carries no valid tenant claim', 403)
            tenant = value
        groups = claim(claims, self.config.roles_claim)
        groups = [groups] if isinstance(groups, str) else groups if isinstance(groups, list) else []
        mapped = [self.config.role_map.get(g, g if not self.config.role_map and g in ROLES else None) for g in groups if isinstance(g, str)]
        mapped = [r for r in mapped if r]
        role = max(mapped, key=ROLES.get) if mapped else self.config.default_role
        if not role:
            raise Fault('Your identity provider groups grant no Nuvora role', 403)
        return tenant, username, role, self.config.issuer+'|'+str(claims.get('sub', raw))


def verify_signature(alg, jwk, signed, sig):
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    except ImportError as exc:
        raise Fault("Bearer JWT verification needs the sso extra: pip install 'zyvor-nuvora[sso]'", 503) from exc
    digest = {'256':hashes.SHA256, '384':hashes.SHA384, '512':hashes.SHA512}[alg[2:]]()
    as_int = lambda v: int.from_bytes(unb64url(v), 'big')
    try:
        if alg[:2] in ('RS', 'PS'):
            if jwk.get('kty') != 'RSA':
                raise Fault('Token key type does not match its algorithm', 401)
            key = rsa.RSAPublicNumbers(as_int(jwk['e']), as_int(jwk['n'])).public_key()
            pad = padding.PKCS1v15() if alg[:2] == 'RS' else padding.PSS(mgf=padding.MGF1(digest), salt_length=digest.digest_size)
            key.verify(sig, signed, pad, digest)
        else:
            curve = {'ES256':(ec.SECP256R1(), 32), 'ES384':(ec.SECP384R1(), 48)}[alg]
            if jwk.get('kty') != 'EC' or len(sig) != 2*curve[1]:
                raise Fault('Token key type does not match its algorithm', 401)
            key = ec.EllipticCurvePublicNumbers(as_int(jwk['x']), as_int(jwk['y']), curve[0]).public_key()
            der = encode_dss_signature(int.from_bytes(sig[:curve[1]], 'big'), int.from_bytes(sig[curve[1]:], 'big'))
            key.verify(der, signed, ec.ECDSA(digest))
    except InvalidSignature as exc:
        raise Fault('Token signature is invalid', 401) from exc
    except (KeyError, ValueError) as exc:
        raise Fault('Token signing key is malformed', 401) from exc
