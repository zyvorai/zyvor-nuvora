import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import socket
import time
from urllib.parse import urlsplit

ROLES = {'viewer':0, 'developer':1, 'approver':2, 'admin':3}
DEMO_PASSWORD = 'Admin@321'

class Fault(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def password_hash(password):
    salt = secrets.token_hex(16)
    return salt + ':' + hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 250_000).hex()


def password_matches(password, encoded):
    salt, digest = encoded.split(':')
    candidate = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 250_000).hex()
    return hmac.compare_digest(candidate,digest)


def validate_url(url, allowed_hosts):
    """No user-defined egress: operator exact-host allowlist, no redirects."""
    parsed = urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise Fault('Invalid provider URL')
    host = parsed.hostname.lower()
    if host not in allowed_hosts:
        raise Fault('Provider host is not on the operator allowlist',403)
    if host in ('169.254.169.254','metadata.google.internal'):
        raise Fault('Metadata endpoints are forbidden',403)
    if parsed.scheme == 'http' and host not in ('localhost','127.0.0.1','::1'):
        raise Fault('Remote providers require HTTPS')
    return parsed


class Auth:
    def __init__(self, store):
        self.store=store
        self.failures={}
        self.dummy=password_hash('unmatched-'+secrets.token_hex(16))

    def add_user(self, tenant, username, password, role, allow_demo_password=False):
        if role not in ROLES or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}', username) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}',tenant):
            raise Fault('Invalid tenant, username or role')
        demo=allow_demo_password and password==DEMO_PASSWORD
        if (len(password)<12 and not demo) or len(password)>256:
            raise Fault('Passwords must contain 12–256 characters')
        with self.store.lock:
            self.store.db.execute('INSERT INTO users VALUES (?,?,?,?)',(tenant,username,password_hash(password),role))

    def login(self, tenant, username, password):
        key=(tenant,username)
        with self.store.lock:
            attempts=[t for t in self.failures.get(key,[]) if t>time.time()-300]
            if len(attempts)>=10:
                raise Fault('Too many login attempts; try in five minutes',429)
            row=self.store.db.execute('SELECT * FROM users WHERE tenant=? AND username=?',key).fetchone()
            ok=password_matches(password,row['password'] if row else self.dummy)
            if not ok or not row:
                self.failures[key]=attempts+[time.time()]
                raise Fault('Wrong tenant, username or password',401)
            self.failures.pop(key,None)
            token=secrets.token_urlsafe(32)
            self.store.db.execute('INSERT INTO tokens VALUES (?,?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),tenant,username,row['role'],time.time()+8*3600))
        self.store.audit(tenant,username,'session.created',username)
        return token

    def issue(self, principal, role="viewer", lifetime=3600):
        if principal['role'] not in ('admin','developer') or role not in ('viewer','developer'):
            raise Fault('Service tokens may only view or propose',403)
        if not isinstance(lifetime,int) or not 60<=lifetime<=86400*30:
            raise Fault('Token lifetime must be 60 seconds to 30 days')
        token=secrets.token_urlsafe(32)
        with self.store.lock:
            self.store.db.execute('INSERT INTO tokens VALUES (?,?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),principal['tenant'],principal['username'],role,time.time()+lifetime))
        self.store.audit(principal['tenant'],principal['username'],'service_token.created',role,{'lifetime':lifetime})
        return {'token':token,'role':role,'expires':time.time()+lifetime}

    def principal(self, token):
        with self.store.lock:
            row=self.store.db.execute('SELECT * FROM tokens WHERE digest=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        if not row:
            raise Fault('Sign in required',401)
        return {k:row[k] for k in ('tenant','username','role')}

    def logout(self, token):
        with self.store.lock:
            self.store.db.execute('DELETE FROM tokens WHERE digest=?',(hashlib.sha256(token.encode()).hexdigest(),))


def require(p, *roles):
    if p['role'] not in roles:
        raise Fault('This role cannot perform that action',403)


def guard(text, policy):
    reasons=[]
    transformed=text
    for topic in policy.get('blocked_topics',[]):
        if topic.lower() in text.lower():
            reasons.append('Denied topic: '+topic)
    if policy.get('detect_injection',True) and re.search(r'ignore\s+(all\s+)?(previous|prior|system)\s+(instructions|prompts)|reveal\s+(the\s+)?system\s+prompt',text,re.I):
        reasons.append('Instruction override pattern detected')
    if policy.get('redact_pii',True):
        transformed=re.sub(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b','[EMAIL]',transformed)
        transformed=re.sub(r'\b(?:\d[ -]?){13,19}\b','[ACCOUNT]',transformed)
    if len(text)>policy.get('max_chars',100000):
        reasons.append('Content size exceeds policy')
    return {'allowed':not reasons,'text':transformed,'reasons':reasons,'pii_redacted':transformed!=text,'engine':'deterministic rules; not a classifier or formal proof'}
