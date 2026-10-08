# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Verify AWS Signature Version 4 (header based) for non-S3 services.

Follows "Signature Version 4 signing process" in the AWS IAM user guide: canonical request,
string to sign, derived signing key, constant-time comparison. Query-string (presigned)
authentication and chunked streaming payloads are not supported and are refused by name."""
import calendar
import hashlib
import hmac
import re
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote, unquote

ALGORITHM = 'AWS4-HMAC-SHA256'
SERVICES = frozenset({'bedrock', 'bedrock-runtime', 'bedrock-agent', 'bedrock-agent-runtime'})
MAX_SKEW = 300
UNSIGNED = 'UNSIGNED-PAYLOAD'
EMPTY_SHA256 = hashlib.sha256(b'').hexdigest()


class SigV4Error(Exception):
    """`code` is the Bedrock/AWS error type to answer with."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class Verified:
    def __init__(self, access_key, region, service, date, signed_headers, payload_hash):
        self.access_key, self.region, self.service = access_key, region, service
        self.date, self.signed_headers, self.payload_hash = date, signed_headers, payload_hash


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def _hmac(key, message):
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def signing_key(secret, date, region, service):
    k = _hmac(('AWS4' + secret).encode(), date)
    for part in (region, service, 'aws4_request'):
        k = _hmac(k, part)
    return k


def _normalize_path(path):
    """Collapse empty segments and resolve `.`/`..`; keeps a trailing slash."""
    if not path:
        return '/'
    out = []
    for segment in path.split('/'):
        if segment in ('', '.'):
            continue
        if segment == '..':
            if out:
                out.pop()
            continue
        out.append(segment)
    result = '/' + '/'.join(out)
    return result + '/' if path.endswith('/') and result != '/' else result


def canonical_uri(raw_path):
    """Non-S3 services URI-encode the already-encoded path a second time."""
    return quote(_normalize_path(raw_path or '/'), safe='/~')


def canonical_query(raw_query):
    pairs = []
    for piece in (raw_query or '').split('&'):
        if not piece:
            continue
        name, _, value = piece.partition('=')
        pairs.append((quote(unquote(name.replace('+', ' ')), safe='-_.~'), quote(unquote(value.replace('+', ' ')), safe='-_.~')))
    return '&'.join(f'{n}={v}' for n, v in sorted(pairs))


def canonical_headers(headers, signed):
    """`headers` is a list of (name, value) pairs; repeated names are joined with commas."""
    merged = {}
    for name, value in headers:
        merged.setdefault(name.lower(), []).append(re.sub(r' +', ' ', value.strip()))
    lines = []
    for name in signed:
        if name not in merged:
            raise SigV4Error('InvalidSignatureException', f"Signed header '{name}' is missing from the request")
        lines.append(f"{name}:{','.join(merged[name])}\n")
    return ''.join(lines)


def canonical_request(method, raw_path, raw_query, headers, signed, payload_hash):
    return '\n'.join([method.upper(), canonical_uri(raw_path), canonical_query(raw_query),
                      canonical_headers(headers, signed), ';'.join(signed), payload_hash])


def string_to_sign(amz_date, scope, canonical):
    return '\n'.join([ALGORITHM, amz_date, scope, sha256_hex(canonical.encode())])


def sign(secret, method, target, headers, signed, payload_hash, amz_date, region, service):
    """The signature a client computes (used by the verifier and by tests)."""
    path, _, query = target.partition('?')
    scope = f'{amz_date[:8]}/{region}/{service}/aws4_request'
    sts = string_to_sign(amz_date, scope, canonical_request(method, path, query, headers, signed, payload_hash))
    return hmac.new(signing_key(secret, amz_date[:8], region, service), sts.encode(), hashlib.sha256).hexdigest()


def parse_authorization(value):
    if not value.startswith(ALGORITHM + ' '):
        raise SigV4Error('IncompleteSignatureException', 'Unsupported authorization algorithm; use AWS4-HMAC-SHA256')
    fields = {}
    for piece in value[len(ALGORITHM):].split(','):
        key, _, val = piece.strip().partition('=')
        fields[key] = val.strip()
    missing = [k for k in ('Credential', 'SignedHeaders', 'Signature') if not fields.get(k)]
    if missing:
        raise SigV4Error('IncompleteSignatureException', 'Authorization header requires ' + ', '.join(missing))
    parts = fields['Credential'].split('/')
    if len(parts) < 5 or parts[-1] != 'aws4_request':
        raise SigV4Error('IncompleteSignatureException', 'Credential must be <key>/<date>/<region>/<service>/aws4_request')
    access_key, date, region, service = '/'.join(parts[:-4]), parts[-4], parts[-3], parts[-2]
    if not re.fullmatch(r'\d{8}', date):
        raise SigV4Error('IncompleteSignatureException', 'Credential date must be YYYYMMDD')
    if not re.fullmatch(r'[0-9a-f]{64}', fields['Signature']):
        raise SigV4Error('IncompleteSignatureException', 'Signature must be 64 hexadecimal characters')
    signed = fields['SignedHeaders'].split(';')
    if any(not s or s != s.lower() for s in signed):
        raise SigV4Error('IncompleteSignatureException', 'SignedHeaders must be lowercase and semicolon separated')
    return access_key, date, region, service, signed, fields['Signature']


def request_time(headers):
    """Epoch seconds and the X-Amz-Date form of the request time (x-amz-date, else Date)."""
    lookup = {}
    for name, value in headers:
        lookup.setdefault(name.lower(), value.strip())
    stamp = lookup.get('x-amz-date')
    if stamp:
        if not re.fullmatch(r'\d{8}T\d{6}Z', stamp):
            raise SigV4Error('IncompleteSignatureException', 'X-Amz-Date must be YYYYMMDDTHHMMSSZ')
        return calendar.timegm(time.strptime(stamp, '%Y%m%dT%H%M%SZ')), stamp
    if lookup.get('date'):
        try:
            moment = parsedate_to_datetime(lookup['date'])
            epoch = int(moment.timestamp())
        except (TypeError, ValueError) as exc:
            raise SigV4Error('IncompleteSignatureException', 'Date header is not a valid HTTP date') from exc
        return epoch, time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(epoch))
    raise SigV4Error('IncompleteSignatureException', 'Request needs an X-Amz-Date or Date header')


def verify(method, target, headers, body, secret_for, now=None, services=SERVICES):
    """Verify a signed request. `target` is the raw request target (path and query as sent),
    `headers` a list of (name, value) pairs, `secret_for(access_key)` the secret or None.

    Returns Verified or raises SigV4Error. Unknown keys run the full computation against a
    dummy secret so timing does not reveal which access key ids exist."""
    lower = {n.lower(): v for n, v in headers}
    authorization = lower.get('authorization', '')
    if not authorization:
        raise SigV4Error('MissingAuthenticationTokenException', 'Missing Authentication Token')
    path, _, query = target.partition('?')
    if 'x-amz-signature=' in query.lower() or 'x-amz-algorithm=' in query.lower():
        raise SigV4Error('IncompleteSignatureException', 'Query-string (presigned) authentication is not supported')
    access_key, date, region, service, signed, signature = parse_authorization(authorization)
    if services is not None and service not in services:
        raise SigV4Error('InvalidSignatureException', f"Credential scope service '{service}' is not served here")
    if not region or not re.fullmatch(r'[A-Za-z0-9-]{1,32}', region):
        raise SigV4Error('InvalidSignatureException', 'Credential scope region is invalid')
    if 'host' not in signed:
        raise SigV4Error('InvalidSignatureException', "'host' must be a signed header")
    if 'x-amz-date' in lower and 'x-amz-date' not in signed:
        raise SigV4Error('InvalidSignatureException', "'x-amz-date' must be a signed header")
    if 'x-amz-content-sha256' in lower and 'x-amz-content-sha256' not in signed:
        raise SigV4Error('InvalidSignatureException', "'x-amz-content-sha256' must be a signed header")
    if 'x-amz-date' not in signed and 'date' not in signed:
        raise SigV4Error('InvalidSignatureException', "'x-amz-date' or 'date' must be a signed header")
    if signed != sorted(signed) or len(set(signed)) != len(signed):
        raise SigV4Error('InvalidSignatureException', 'SignedHeaders must be sorted and unique')
    when, amz_date = request_time(headers)
    if abs((time.time() if now is None else now) - when) > MAX_SKEW:
        raise SigV4Error('InvalidSignatureException', 'Signature expired: request time is more than 5 minutes from server time')
    if amz_date[:8] != date:
        raise SigV4Error('InvalidSignatureException', 'Credential date does not match the request date')
    declared = lower.get('x-amz-content-sha256')
    if declared and declared.startswith('STREAMING-'):
        raise SigV4Error('InvalidSignatureException', 'Chunked (streaming) payload signing is not supported')
    if declared == UNSIGNED:
        payload_hash = UNSIGNED
    else:
        payload_hash = sha256_hex(body)
        if declared and not hmac.compare_digest(declared.lower(), payload_hash):
            raise SigV4Error('InvalidSignatureException', 'x-amz-content-sha256 does not match the request body')
    secret = secret_for(access_key)
    expected = sign(secret or 'x' * 40, method, target, headers, signed, payload_hash, amz_date, region, service)
    # Always compare, so a missing key and a wrong signature take the same path.
    if not hmac.compare_digest(expected, signature) or secret is None:
        if secret is None:
            raise SigV4Error('UnrecognizedClientException', 'The security token included in the request is invalid.')
        raise SigV4Error('InvalidSignatureException', 'The request signature we calculated does not match the signature you provided.')
    return Verified(access_key, region, service, date, signed, payload_hash)
