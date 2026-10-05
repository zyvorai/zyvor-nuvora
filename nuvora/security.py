# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
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
        self.dummy=password_hash('unmatched-'+secrets.token_hex(16))
        self.oidc=None

    def add_user(self, tenant, username, password, role, allow_demo_password=False):
        if role not in ROLES or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}', username) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}',tenant):
            raise Fault('Invalid tenant, username or role')
        demo=allow_demo_password and password==DEMO_PASSWORD
        if (len(password)<12 and not demo) or len(password)>256:
            raise Fault('Passwords must contain 12–256 characters')
        with self.store.lock:
            self.store.db.execute('INSERT INTO users (tenant,username,password,role) VALUES (?,?,?,?)',(tenant,username,password_hash(password),role))

    def login(self, tenant, username, password):
        key=(tenant,username)
        now=time.time()
        with self.store.lock:
            attempts=self.store.db.execute('SELECT COUNT(*) FROM login_failures WHERE tenant=? AND username=? AND at>?',(str(tenant)[:64],str(username)[:64],now-300)).fetchone()[0]
            if attempts>=10:
                raise Fault('Too many login attempts; try in five minutes',429)
            row=self.store.db.execute('SELECT * FROM users WHERE tenant=? AND username=?',key).fetchone()
            ok=password_matches(password,row['password'] if row else self.dummy)
            if not ok or not row or row['identity']:
                self.store.db.execute('DELETE FROM login_failures WHERE at<?',(now-300,))
                self.store.db.execute('INSERT INTO login_failures (tenant,username,at) VALUES (?,?,?)',(str(tenant)[:64],str(username)[:64],now))
                raise Fault('Wrong tenant, username or password',401)
            self.store.db.execute('DELETE FROM login_failures WHERE tenant=? AND username=?',(tenant,username))
            token=self._insert(tenant,username,row['role'],8*3600,'session')
        self.store.audit(tenant,username,'session.created',username)
        return token

    def sso_login(self, tenant, username, role, subject):
        """Create or update a just-in-time SSO user, sync its role from the identity provider and open a session."""
        actor='oidc:'+username
        with self.store.transaction():
            row=self.store.db.execute('SELECT role,identity FROM users WHERE tenant=? AND username=?',(tenant,username)).fetchone()
            if row and row['identity']!=subject:
                raise Fault('A local account already uses this username; ask an administrator to rename it',409)
            if not row:
                # Unusable password: SSO users never sign in with one.
                self.store.db.execute('INSERT INTO users (tenant,username,password,role,identity) VALUES (?,?,?,?,?)',
                                      (tenant,username,password_hash(secrets.token_urlsafe(32)),role,subject))
            elif row['role']!=role:
                self.store.db.execute('UPDATE users SET role=? WHERE tenant=? AND username=?',(role,tenant,username))
                self.store.db.execute("UPDATE tokens SET role=? WHERE tenant=? AND username=? AND kind='session'",(role,tenant,username))
                if role not in ('admin','developer'):
                    self.store.db.execute("DELETE FROM tokens WHERE tenant=? AND username=? AND kind='service'",(tenant,username))
            token=self._insert(tenant,username,role,8*3600,'session')
        if not row:
            self.store.audit(tenant,actor,'user.provisioned',username,{'role':role,'source':'oidc'})
        elif row['role']!=role:
            self.store.audit(tenant,actor,'user.role_synced',username,{'from':row['role'],'to':role})
        self.store.audit(tenant,actor,'session.created',username,{'source':'oidc'})
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
            sso=self.store.db.execute('SELECT identity FROM users WHERE tenant=? AND username=?',(tenant,username)).fetchone()
            if sso and sso['identity']:
                raise Fault('This account is managed by your identity provider',409)
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
        if self.oidc and token.count('.')==2:
            tenant,username,role,_=self.oidc.identity(self.oidc.verify(token))
            return {'tenant':tenant,'username':username,'role':role,'source':'oidc'}
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


PII_ACTIONS = ('mask', 'block')
CLASSIFIER_CATEGORIES = ('hate', 'violence', 'sexual', 'self_harm', 'misconduct', 'prompt_attack')
GROUNDING_STOP = frozenset('the a an and or of to in on for with is are was were be been it this that as at by from not no but if then than so do does did can could will would should may might must have has had their there they them its into over under about'.split())


def _luhn(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _iban(value):
    raw = value.replace(' ', '').upper()
    if not 15 <= len(raw) <= 34:
        return False
    moved = raw[4:] + raw[:4]
    return int(''.join(str(int(c, 36)) for c in moved)) % 97 == 1


def _ipv4(value):
    try:
        ipaddress.IPv4Address(value)
        return True
    except ValueError:
        return False


PII = {
    'email': (r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b', None, '[EMAIL]'),
    'iban': (r'\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b', _iban, '[IBAN]'),
    'card': (r'\b\d(?:[ -]?\d){12,18}\b', lambda m: _luhn(re.sub(r'\D', '', m)), '[CARD]'),
    'ssn': (r'\b\d{3}-\d{2}-\d{4}\b', None, '[SSN]'),
    'ipv4': (r'\b(?:\d{1,3}\.){3}\d{1,3}\b', _ipv4, '[IP]'),
    'phone': (r'(?<![\w+])(?<!\d[ .-])(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)|\d{2,4})[ .-]\d{3,4}[ .-]\d{3,4}(?![\w-])(?![ .-]?\d)', None, '[PHONE]'),
}


def grounding_score(text, sources):
    """Mean share of each answer sentence's content words that appear in the sources (0–1)."""
    vocab = set(re.findall(r'[a-z0-9]+', ' '.join(sources).lower())) - GROUNDING_STOP
    scores = []
    for sentence in re.split(r'(?<=[.!?])\s+|\n+', text):
        words = [w for w in re.findall(r'[a-z0-9]+', sentence.lower()) if w not in GROUNDING_STOP and len(w) > 2]
        if len(words) >= 4:
            scores.append(sum(w in vocab for w in words) / len(words))
    return round(sum(scores) / len(scores), 3) if scores else 1.0


def validate_policy(data):
    words = data.get('word_filters', [])
    if not isinstance(words, list) or len(words) > 200 or any(not isinstance(w, str) or not 1 <= len(w) <= 100 for w in words):
        raise Fault('word_filters must be up to 200 strings of 1–100 characters')
    filters = data.get('regex_filters', [])
    if not isinstance(filters, list) or len(filters) > 20:
        raise Fault('regex_filters allows up to 20 entries')
    for f in filters:
        if not isinstance(f, dict) or set(f) - {'name', 'pattern', 'action'} or not isinstance(f.get('name'), str) or not isinstance(f.get('pattern'), str) \
                or not 1 <= len(f['pattern']) <= 200 or f.get('action', 'block') not in PII_ACTIONS:
            raise Fault('Each regex filter needs a name, a pattern of 1–200 characters and action mask or block')
        if re.search(r'\([^)]*[+*][^)]*\)[+*{]', f['pattern']):
            raise Fault('Nested quantifiers are not allowed in regex filters')
        try:
            re.compile(f['pattern'])
        except re.error as exc:
            raise Fault('Invalid regex filter: ' + f['name']) from exc
    entities = data.get('pii_entities')
    if entities is not None and (not isinstance(entities, dict) or set(entities) - set(PII) or any(v not in PII_ACTIONS for v in entities.values())):
        raise Fault('pii_entities maps ' + ', '.join(PII) + ' to mask or block')
    threshold = data.get('grounding_threshold')
    if threshold is not None and (not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1):
        raise Fault('grounding_threshold must be between 0 and 1')
    categories = data.get('classifier_categories', [])
    if not isinstance(categories, list) or set(categories) - set(CLASSIFIER_CATEGORIES):
        raise Fault('classifier_categories must be among ' + ', '.join(CLASSIFIER_CATEGORIES))
    ct = data.get('classifier_threshold', .5)
    if not isinstance(ct, (int, float)) or not 0 < ct <= 1:
        raise Fault('classifier_threshold must be above 0 and at most 1')


def guard(text, policy, sources=None):
    reasons = []
    transformed = text
    lower = text.lower()
    for topic in policy.get('blocked_topics', []):
        if topic.lower() in lower:
            reasons.append('Denied topic: ' + topic)
    for word in policy.get('word_filters', []):
        if re.search(r'(?<!\w)' + re.escape(word.lower()) + r'(?!\w)', lower):
            reasons.append('Blocked word: ' + word)
    if policy.get('detect_injection', True) and re.search(r'ignore\s+(all\s+)?(previous|prior|system)\s+(instructions|prompts)|reveal\s+(the\s+)?system\s+prompt', text, re.I):
        reasons.append('Instruction override pattern detected')
    for f in policy.get('regex_filters', []):
        if re.search(f['pattern'], transformed):
            if f.get('action', 'block') == 'block':
                reasons.append('Matched filter: ' + f['name'])
            else:
                transformed = re.sub(f['pattern'], '[' + f['name'].upper() + ']', transformed)
    entities = policy.get('pii_entities')
    found = []
    if entities is None:
        if policy.get('redact_pii', True):
            transformed = re.sub(PII['email'][0], '[EMAIL]', transformed)
            transformed = re.sub(r'\b(?:\d[ -]?){13,19}\b', '[ACCOUNT]', transformed)
    else:
        for name in [n for n in PII if n in entities]:
            action = entities[name]
            pattern, check, label = PII[name]
            hits = [m for m in re.findall(pattern, transformed) if check is None or check(m)]
            if not hits:
                continue
            found.append(name)
            if action == 'block':
                reasons.append('Sensitive information: ' + name)
            else:
                transformed = re.sub(pattern, lambda m: label if check is None or check(m.group(0)) else m.group(0), transformed)
    if len(text) > policy.get('max_chars', 100000):
        reasons.append('Content size exceeds policy')
    verdict = {'allowed': not reasons, 'text': transformed, 'reasons': reasons, 'pii_redacted': transformed != text, 'pii_found': found,
               'engine': 'deterministic rules; not a classifier or formal proof'}
    threshold = policy.get('grounding_threshold')
    if sources and threshold:
        score = grounding_score(text, sources)
        verdict['grounding'] = {'score': score, 'threshold': threshold, 'grounded': score >= threshold}
        if score < threshold:
            verdict['reasons'].append(f'Answer not grounded in sources (score {score})')
            verdict['allowed'] = False
    return verdict
