# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Prepare a throwaway local Nuvora for run-compat.sh (stdlib only): sign in as admin, make sure an
embedding model exists, issue a developer AWS access key, and print shell exports."""
import json
import os
import shlex
import sys
import urllib.request

base, password = sys.argv[1], os.environ['NUVORA_ADMIN_PASSWORD']


def call(method, path, body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base + path, method=method, data=None if body is None else json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}, r.headers


_, headers = call('POST', '/api/login', {'tenant': 'default', 'username': 'admin', 'password': password})
token = next(c.split('=', 1)[1].split(';')[0] for c in headers.get_all('Set-Cookie') if c.startswith('nuvora_session='))
models = call('GET', '/api/models', token=token)[0]
models = models['items'] if isinstance(models, dict) else models
if not any(m.get('capability') == 'embedding' for m in models):
    call('POST', '/api/models', {'name': 'Offline demo embeddings', 'provider': 'demo', 'upstream_model': 'demo-embed', 'capability': 'embedding'}, token)
cred = call('POST', '/api/aws-credentials', {'role': 'developer', 'label': 'compat suite'}, token)[0]
for key, value in (('NUVORA_ENDPOINT', base), ('AWS_ACCESS_KEY_ID', cred['access_key_id']), ('AWS_SECRET_ACCESS_KEY', cred['secret_access_key']),
                   ('AWS_BEARER_TOKEN_BEDROCK', token), ('AWS_DEFAULT_REGION', 'us-east-1')):
    print('export %s=%s' % (key, shlex.quote(value)))
