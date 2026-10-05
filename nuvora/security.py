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
            token=self._insert(tenant,username,row['role'],8*3600,'session')
        self.store.audit(tenant,username,'session.created',username)
        return token

    def _insert(self, tenant, username, role, lifetime, kind, label=''):
        token=secrets.token_urlsafe(32)
        now=time.time()
        self.store.db.execute('INSERT INTO tokens (digest,tenant,username,role,expires,id,kind,label,created) VALUES (?,?,?,?,?,?,?,?,?)',
                              (hashlib.sha256(token.encode()).hexdigest(),tenant,username,role,now+lifetime,secrets.token_hex(8),kind,label,now))
        return token

    def issue(self, principal, role="viewer", lifetime=3600, label=''):
        if principal['role'] not in ('admin','developer') or role not in ('viewer','developer'):
            raise Fault('Service tokens may only view or propose',403)
        if not isinstance(lifetime,int) or not 60<=lifetime<=86400*30:
            raise Fault('Token lifetime must be 60 seconds to 30 days')
        if not isinstance(label,str) or len(label)>80:
            raise Fault('Token labels are at most 80 characters')
        with self.store.lock:
            token=self._insert(principal['tenant'],principal['username'],role,lifetime,'service',label.strip())
            row=self.store.db.execute('SELECT id FROM tokens WHERE digest=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        self.store.audit(principal['tenant'],principal['username'],'service_token.created',role,{'lifetime':lifetime,'id':row['id']})
        return {'token':token,'id':row['id'],'role':role,'label':label.strip(),'expires':time.time()+lifetime}

    def list_tokens(self, principal):
        query='SELECT id,username,role,label,created,expires FROM tokens WHERE tenant=? AND kind=\'service\' AND expires>?'
        args=[principal['tenant'],time.time()]
        if principal['role']!='admin':
            query+=' AND username=?'
            args.append(principal['username'])
        with self.store.lock:
            rows=self.store.db.execute(query+' ORDER BY created DESC',args).fetchall()
        return [dict(r) for r in rows]

    def revoke_token(self, principal, id):
        with self.store.lock:
            row=self.store.db.execute("SELECT username FROM tokens WHERE tenant=? AND kind='service' AND id=?",(principal['tenant'],id)).fetchone()
            if not row:
                raise KeyError('Token not found')
            if principal['role']!='admin' and row['username']!=principal['username']:
                raise Fault('Only the owner or an administrator can revoke this token',403)
            self.store.db.execute("DELETE FROM tokens WHERE tenant=? AND kind='service' AND id=?",(principal['tenant'],id))
        self.store.audit(principal['tenant'],principal['username'],'service_token.revoked',id)

    def change_password(self, principal, current, new, keep_token):
        tenant,username=principal['tenant'],principal['username']
        if not isinstance(new,str) or not 12<=len(new)<=256:
            raise Fault('Passwords must contain 12–256 characters')
        with self.store.lock:
            row=self.store.db.execute('SELECT password FROM users WHERE tenant=? AND username=?',(tenant,username)).fetchone()
            if not row or not password_matches(current if isinstance(current,str) else '',row['password']):
                raise Fault('Current password is incorrect',403)
            if new==current:
                raise Fault('Choose a password different from the current one')
            self.store.db.execute('UPDATE users SET password=? WHERE tenant=? AND username=?',(password_hash(new),tenant,username))
            keep=hashlib.sha256(keep_token.encode()).hexdigest()
            self.store.db.execute("DELETE FROM tokens WHERE tenant=? AND username=? AND kind='session' AND digest!=?",(tenant,username,keep))
        self.store.audit(tenant,username,'user.password_changed',username)

    def _admins(self, tenant):
        return self.store.db.execute("SELECT COUNT(*) FROM users WHERE tenant=? AND role='admin'",(tenant,)).fetchone()[0]

    def set_role(self, principal, username, role):
        require(principal,'admin')
        if role not in ROLES:
            raise Fault('Invalid role')
        if username==principal['username']:
            raise Fault('You cannot change your own role',409)
        with self.store.lock:
            row=self.store.db.execute('SELECT role FROM users WHERE tenant=? AND username=?',(principal['tenant'],username)).fetchone()
            if not row:
                raise KeyError('User not found')
            if row['role']=='admin' and role!='admin' and self._admins(principal['tenant'])<=1:
                raise Fault('A workspace needs at least one administrator',409)
            self.store.db.execute('UPDATE users SET role=? WHERE tenant=? AND username=?',(role,principal['tenant'],username))
            self.store.db.execute("UPDATE tokens SET role=? WHERE tenant=? AND username=? AND kind='session'",(role,principal['tenant'],username))
            revoked=0
            if role not in ('admin','developer'):
                revoked=self.store.db.execute("DELETE FROM tokens WHERE tenant=? AND username=? AND kind='service'",(principal['tenant'],username)).rowcount
        self.store.audit(principal['tenant'],principal['username'],'user.role_changed',username,{'from':row['role'],'to':role,'service_tokens_revoked':revoked})

    def remove_user(self, principal, username):
        require(principal,'admin')
        if username==principal['username']:
            raise Fault('You cannot remove yourself',409)
        with self.store.lock:
            row=self.store.db.execute('SELECT role FROM users WHERE tenant=? AND username=?',(principal['tenant'],username)).fetchone()
            if not row:
                raise KeyError('User not found')
            if row['role']=='admin' and self._admins(principal['tenant'])<=1:
                raise Fault('A workspace needs at least one administrator',409)
            self.store.db.execute('DELETE FROM users WHERE tenant=? AND username=?',(principal['tenant'],username))
            self.store.db.execute('DELETE FROM tokens WHERE tenant=? AND username=?',(principal['tenant'],username))
        self.store.audit(principal['tenant'],principal['username'],'user.removed',username)

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
