# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Shared plumbing for the Bedrock compatibility scripts: argument handling, boto3 clients, the
native Nuvora API, a PASS/FAIL/SKIP table and cleanup. Scripts may import boto3; the server never does."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover
    sys.exit('boto3 is required: pip install "boto3>=1.35"')


class Skip(Exception):
    """Raised by a check that cannot run in this setup; the reason is shown in the table."""


def parse(description):
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument('--endpoint', default=os.getenv('NUVORA_ENDPOINT', ''), help='Nuvora base URL (default: $NUVORA_ENDPOINT)')
    ap.add_argument('--region', default=os.getenv('AWS_DEFAULT_REGION') or os.getenv('AWS_REGION') or 'us-east-1')
    args = ap.parse_args()
    if not args.endpoint:
        ap.error('set --endpoint or NUVORA_ENDPOINT')
    host = (urlsplit(args.endpoint).hostname or '').lower()
    if host.endswith('amazonaws.com') or host.endswith('amazonaws.com.cn') or host.endswith('.aws'):
        ap.error('refusing to run against an AWS endpoint (%s): these scripts are for a Nuvora server' % host)
    args.endpoint = args.endpoint.rstrip('/')
    return args


class Env:
    """Credentials and clients for one run. Access keys sign with SigV4 (role: developer at most);
    the bearer token (AWS_BEARER_TOKEN_BEDROCK, an admin session or service token) is what admin-only
    operations need, and doubles as the native API token."""

    def __init__(self, args):
        self.endpoint, self.region = args.endpoint, args.region
        self.key = os.getenv('AWS_ACCESS_KEY_ID', '')
        self.secret = os.getenv('AWS_SECRET_ACCESS_KEY', '')
        # botocore reads AWS_BEARER_TOKEN_BEDROCK itself and then prefers it over SigV4 (and fails with
        # NoAuthTokenError if it disappears again), so take it out of the environment for good: access-key
        # clients sign with SigV4, and bearer clients get the Authorization header set explicitly.
        self.bearer = os.environ.pop('AWS_BEARER_TOKEN_BEDROCK', '')
        if not (self.key and self.secret) and not self.bearer:
            sys.exit('set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY or AWS_BEARER_TOKEN_BEDROCK')

    def client(self, service, admin=False):
        """admin=True sends the bearer token; otherwise SigV4 with the access key (bearer if no key)."""
        use_bearer = bool(self.bearer) and (admin or not self.key)
        if admin and not self.bearer:
            raise Skip('needs AWS_BEARER_TOKEN_BEDROCK (admin writes cannot use an access key)')
        client = boto3.client(service, endpoint_url=self.endpoint, region_name=self.region,
                              aws_access_key_id=self.key or 'AKIAXXXXXXXXXXXXXXXX', aws_secret_access_key=self.secret or 'x' * 40,
                              config=Config(retries={'max_attempts': 1}, read_timeout=90, user_agent_extra='nuvora-compat'))
        if use_bearer:
            token = self.bearer
            client.meta.events.register('before-send.%s.*' % service, lambda request, **kw: request.headers.__setitem__('Authorization', 'Bearer ' + token))
        return client

    def sigv4_client(self, service, secret=None):
        """A client that signs with SigV4, optionally with a deliberately wrong secret."""
        return boto3.client(service, endpoint_url=self.endpoint, region_name=self.region, aws_access_key_id=self.key,
                            aws_secret_access_key=secret or self.secret, config=Config(retries={'max_attempts': 1}))

    def native(self, method, path, body=None, expect=None):
        if not self.bearer:
            raise Skip('needs AWS_BEARER_TOKEN_BEDROCK for the native API')
        req = urllib.request.Request(self.endpoint + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={'Authorization': 'Bearer ' + self.bearer, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                code, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            with e:
                code, raw = e.code, e.read()
        if expect is not None and code != expect:
            raise AssertionError('native %s %s answered %s: %s' % (method, path, code, raw[:200]))
        return json.loads(raw) if raw[:1] in (b'{', b'[') else {}


def error_of(call, *args, **kw):
    """(code, http status, message) of the ClientError `call` raises; AssertionError when it succeeds."""
    try:
        call(*args, **kw)
    except ClientError as e:
        r = e.response
        return r['Error'].get('Code', ''), r['ResponseMetadata']['HTTPStatusCode'], r['Error'].get('Message', '')
    raise AssertionError('expected an error but the call succeeded')


def expect_error(call, code, status, *args, **kw):
    got = error_of(call, *args, **kw)
    if got[:2] != (code, status):
        raise AssertionError('expected %s/%s, got %s/%s: %s' % (code, status, got[0], got[1], got[2][:160]))
    return got[2]


def check(cond, message='assertion failed'):
    if not cond:
        raise AssertionError(message)


def eq(got, want, label=''):
    if got != want:
        raise AssertionError('%s: expected %r, got %r' % (label or 'value', want, got))


class Report:
    def __init__(self, title):
        self.title, self.rows, self.cleanups = title, [], []

    def later(self, fn):
        """Register a cleanup; they run in reverse order, each failure is reported but never stops the rest."""
        self.cleanups.append(fn)

    def run(self, service, op, fn, expected_refusal=False):
        try:
            detail = fn()
            self.rows.append((service, op, 'PASS', detail if isinstance(detail, str) else ''))
        except Skip as e:
            self.rows.append((service, op, 'SKIP', str(e)))
        except AssertionError as e:
            self.rows.append((service, op, 'FAIL', str(e)))
        except Exception as e:  # any SDK or transport failure is a FAIL with its type
            self.rows.append((service, op, 'FAIL', '%s: %s' % (type(e).__name__, e)))

    def cleanup(self):
        for fn in reversed(self.cleanups):
            try:
                fn()
            except ClientError as e:
                if e.response['Error'].get('Code') != 'ResourceNotFoundException':  # already removed by the check itself
                    self.rows.append(('cleanup', 'delete fixture', 'FAIL', '%s: %s' % (type(e).__name__, e)))
            except Exception as e:
                self.rows.append(('cleanup', 'delete fixture', 'FAIL', '%s: %s' % (type(e).__name__, e)))
        self.cleanups = []

    def finish(self):
        width = [max(len(r[i]) for r in self.rows + [('service', 'operation', 'result', '')]) for i in range(3)]
        print('\n%s' % self.title)
        print('%-*s  %-*s  %-*s  %s' % (width[0], 'service', width[1], 'operation', width[2], 'result', 'detail'))
        for service, op, status, detail in self.rows:
            print('%-*s  %-*s  %-*s  %s' % (width[0], service, width[1], op, width[2], status, detail[:200]))
        counts = {s: sum(1 for r in self.rows if r[2] == s) for s in ('PASS', 'FAIL', 'SKIP')}
        print('PASS %(PASS)d  FAIL %(FAIL)d  SKIP %(SKIP)d' % counts)
        return 1 if counts['FAIL'] else 0


def main_wrapper(title, body):
    args = parse(title)
    env = Env(args)
    report = Report(title)
    try:
        body(env, report)
    finally:
        report.cleanup()
    code = report.finish()
    # machine-readable rows for run-compat.sh
    path = os.getenv('NUVORA_COMPAT_JSON')
    if path:
        with open(path, 'a') as f:
            for row in report.rows:
                f.write(json.dumps(row) + '\n')
    sys.exit(code)
