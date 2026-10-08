# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""AWS-style access keys for SigV4 clients (boto3, the aws CLI).

SigV4 needs the secret itself to recompute the signature, so unlike service tokens (stored as
SHA-256 digests) these secrets must be recoverable. They are encrypted at rest under a key
derived from the operator's NUVORA_SECRET_KEY, with a stdlib-only construction:

  enc_key = HMAC-SHA256(NUVORA_SECRET_KEY, "nuvora/aws-credential/enc/v1")
  mac_key = HMAC-SHA256(NUVORA_SECRET_KEY, "nuvora/aws-credential/mac/v1")
  stream  = HMAC-SHA256(enc_key, nonce || counter_be32) blocks, concatenated
  stored  = "v1." b64(nonce) "." b64(secret XOR stream) "." b64(HMAC-SHA256(mac_key, "v1" || access_key_id || nonce || ciphertext))

Encrypt-then-MAC with a fresh 16-byte nonce per credential; the access key id is bound into the
tag so a row cannot be moved to another key id. Without NUVORA_SECRET_KEY no credential can be
issued or used. This is a deliberate small construction, not a replacement for a KMS: anyone who
holds both the database and NUVORA_SECRET_KEY can recover every secret."""
import base64
import hashlib
import hmac
import os
import re
import secrets
import time

from ..security import Fault, ROLES, require

ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
SECRET_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
MIN_KEY_CHARS = 32
PREFIX = 'NVRA'


def master_key():
    value = os.getenv('NUVORA_SECRET_KEY', '')
    return value.encode() if len(value) >= MIN_KEY_CHARS else None


def _derive(master, label):
    return hmac.new(master, b'nuvora/aws-credential/' + label + b'/v1', hashlib.sha256).digest()


def _stream(key, nonce, length):
    out, counter = b'', 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(4, 'big'), hashlib.sha256).digest()
        counter += 1
    return out[:length]


def _b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def _unb64(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def seal(master, access_key_id, secret):
    nonce = secrets.token_bytes(16)
    raw = secret.encode()
    cipher = bytes(a ^ b for a, b in zip(raw, _stream(_derive(master, b'enc'), nonce, len(raw))))
    tag = hmac.new(_derive(master, b'mac'), b'v1' + access_key_id.encode() + nonce + cipher, hashlib.sha256).digest()
    return '.'.join(['v1', _b64(nonce), _b64(cipher), _b64(tag)])


def unseal(master, access_key_id, stored):
    """The plaintext secret, or None when the row is malformed, tampered with or sealed under another key."""
    try:
        version, nonce, cipher, tag = stored.split('.')
        nonce, cipher, tag = _unb64(nonce), _unb64(cipher), _unb64(tag)
    except ValueError:
        return None
    if version != 'v1':
        return None
    want = hmac.new(_derive(master, b'mac'), b'v1' + access_key_id.encode() + nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(want, tag):
        return None
    try:
        return bytes(a ^ b for a, b in zip(cipher, _stream(_derive(master, b'enc'), nonce, len(cipher)))).decode()
    except UnicodeDecodeError:
        return None


class Credentials:
    def __init__(self, store, auth):
        self.store = store
        self.auth = auth

    def issue(self, principal, role='viewer', lifetime=30 * 86400, label='', username=None):
        require(principal, 'admin')
        master = master_key()
        if master is None:
            raise Fault(f'NUVORA_SECRET_KEY (at least {MIN_KEY_CHARS} characters) is not set; AWS-style credentials cannot be issued', 503)
        if role not in ('viewer', 'developer'):
            raise Fault('AWS credentials may only have the viewer or developer role', 400)
        if not isinstance(lifetime, int) or isinstance(lifetime, bool) or not 60 <= lifetime <= 365 * 86400:
            raise Fault('Credential lifetime must be 60 seconds to 365 days')
        if not isinstance(label, str) or len(label) > 80:
            raise Fault('Labels are at most 80 characters')
        owner = username if username is not None else principal['username']
        if not isinstance(owner, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}', owner):
            raise Fault('Invalid username')
        with self.store.lock:
            row = self.store.db.execute('SELECT role FROM users WHERE tenant=? AND username=?', (principal['tenant'], owner)).fetchone()
            if not row:
                raise Fault('User not found', 404)
            if ROLES[role] > ROLES[row['role']]:
                raise Fault('A credential cannot outrank its user', 403)
            access_key_id = PREFIX + ''.join(secrets.choice(ALPHABET) for _ in range(16))
            secret = ''.join(secrets.choice(SECRET_ALPHABET) for _ in range(40))
            now = time.time()
            self.store.db.execute('INSERT INTO aws_credentials (access_key_id,tenant,username,role,secret,expires,created,label) VALUES (?,?,?,?,?,?,?,?)',
                                  (access_key_id, principal['tenant'], owner, role, seal(master, access_key_id, secret), now + lifetime, now, label.strip()))
        self.store.audit(principal['tenant'], principal['username'], 'aws_credential.created', access_key_id,
                         {'role': role, 'username': owner, 'lifetime': lifetime})
        return {'access_key_id': access_key_id, 'secret_access_key': secret, 'username': owner, 'role': role,
                'label': label.strip(), 'created': now, 'expires': now + lifetime}

    def list(self, principal):
        require(principal, 'admin')
        with self.store.lock:
            rows = self.store.db.execute('SELECT access_key_id,username,role,label,created,expires FROM aws_credentials WHERE tenant=? AND expires>? ORDER BY created DESC',
                                         (principal['tenant'], time.time())).fetchall()
        return [dict(r) for r in rows]

    def revoke(self, principal, access_key_id):
        require(principal, 'admin')
        with self.store.lock:
            gone = self.store.db.execute('DELETE FROM aws_credentials WHERE tenant=? AND access_key_id=?', (principal['tenant'], access_key_id)).rowcount
        if not gone:
            raise KeyError('Credential not found')
        self.store.audit(principal['tenant'], principal['username'], 'aws_credential.revoked', access_key_id)

    def lookup(self, access_key_id):
        """(secret, principal) for a live credential, else None. The principal has the same
        shape as Auth.principal and never outranks the user's current role."""
        master = master_key()
        if master is None or not isinstance(access_key_id, str) or len(access_key_id) > 128:
            return None
        with self.store.lock:
            row = self.store.db.execute('SELECT * FROM aws_credentials WHERE access_key_id=? AND expires>?', (access_key_id, time.time())).fetchone()
            user = self.store.db.execute('SELECT role FROM users WHERE tenant=? AND username=?', (row['tenant'], row['username'])).fetchone() if row else None
        if not row or not user:
            return None
        secret = unseal(master, access_key_id, row['secret'])
        if secret is None:
            return None
        role = row['role'] if ROLES[row['role']] <= ROLES[user['role']] else user['role']
        return secret, {'tenant': row['tenant'], 'username': row['username'], 'role': role,
                        'groups': self.auth.groups(row['tenant'], row['username'])}

    def owner(self, access_key_id):
        """Tenant and username that own a key id, for audit of failed signatures."""
        with self.store.lock:
            row = self.store.db.execute('SELECT tenant,username FROM aws_credentials WHERE access_key_id=?', (str(access_key_id)[:128],)).fetchone()
        return (row['tenant'], row['username']) if row else None
