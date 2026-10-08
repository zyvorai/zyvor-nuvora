# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Bedrock-shaped wire API front door (preview).

server.py calls `matches()` and then `handle()`; everything else lives here. Authentication is
either AWS Signature V4 against an access key issued through /api/aws-credentials, or
`Authorization: Bearer <Nuvora token>` (what boto3 sends for AWS_BEARER_TOKEN_BEDROCK)."""
import json
import time
import traceback
from urllib.parse import parse_qsl, urlsplit

from ..security import Fault
from . import errors, eventstream, sigv4
from .credentials import Credentials
from .errors import BedrockError, new_request_id
from .foundation import list_foundation_models
from .router import Request, Response, Stream, default_router
from .runtime import HANDLERS
from . import agent_runtime

BODY_LIMIT = 28 * 1024 * 1024
FAILURE_LIMIT = 20
FAILURE_WINDOW = 300
# Roots only Bedrock uses: matched even without credentials so the caller gets a Bedrock error.
EXCLUSIVE_ROOTS = ('/model', '/guardrail', '/foundation-models', '/inference-profiles', '/async-invoke', '/retrieveAndGenerate',
                   '/model-customization-jobs', '/evaluation-jobs', '/logging/modelinvocations', '/listTagsForResource',
                   '/tagResource', '/untagResource')
# Roots the web console could also serve: Bedrock only when the request carries credentials.
SHARED_ROOTS = ('/agents', '/knowledgebases', '/guardrails', '/flows')
NATIVE = ('/api/', '/v1/', '/mcp', '/healthz')

ROUTER = default_router()
for _route in ROUTER.routes:
    if _route.operation == 'ListFoundationModels':
        _route.handler = list_foundation_models
    elif _route.operation in HANDLERS:
        _route.handler = HANDLERS[_route.operation]

agent_runtime.register(ROUTER)


def _under(path, roots):
    return any(path == r or path.startswith(r + '/') for r in roots)


def matches(method, path, headers):
    """True when the request belongs to the Bedrock layer (path is the decoded URL path)."""
    if path.startswith(NATIVE):
        return False
    authorization = headers.get('Authorization', '')
    if authorization.startswith(sigv4.ALGORITHM):
        return True
    if _under(path, EXCLUSIVE_ROOTS):
        return True
    return authorization.startswith('Bearer ') and _under(path, SHARED_ROOTS)


def _client(handler):
    return str(handler.client_address[0])[:64] if handler.client_address else ''


def _failures(store, who):
    with store.lock:
        return store.db.execute('SELECT COUNT(*) FROM login_failures WHERE tenant=? AND username=? AND at>?',
                                ('_bedrock', who, time.time() - FAILURE_WINDOW)).fetchone()[0]


def _record_failure(store, who):
    now = time.time()
    with store.lock:
        store.db.execute('DELETE FROM login_failures WHERE tenant=? AND at<?', ('_bedrock', now - FAILURE_WINDOW))
        store.db.execute('INSERT INTO login_failures (tenant,username,at) VALUES (?,?,?)', ('_bedrock', who, now))


def _audit_failure(app, creds, access_key, code, info):
    """Audit under the key's tenant when the key id is known; unknown ids are only throttled
    (an audit chain is per tenant, and an attacker must not be able to fill one)."""
    owner = creds.owner(access_key) if access_key else None
    if owner:
        app.store.audit(owner[0], owner[1], 'bedrock.auth.failed', str(access_key)[:40], {'reason': code, **info})


def authenticate(handler, method, target, body):
    """Returns (principal, service|None, region|None). Raises BedrockError."""
    app = handler.server.platform
    creds = Credentials(app.store, app.auth)
    who = 'ip:' + _client(handler)
    if _failures(app.store, who) >= FAILURE_LIMIT:
        raise errors.throttled('Too many failed authentication attempts; try again in five minutes')
    authorization = handler.headers.get('Authorization', '')
    info = {'ip': _client(handler)}
    if authorization.startswith('Bearer '):
        try:
            return app.auth.principal(authorization[7:].strip()), None, None
        except Exception:  # Fault, or a malformed JWT from the OIDC verifier
            _record_failure(app.store, who)
            raise BedrockError('UnrecognizedClientException', 'The security token included in the request is invalid.')
    found = {}

    def secret_for(access_key):
        hit = creds.lookup(access_key)
        if hit:
            found['principal'] = hit[1]
            return hit[0]
        return None

    pairs = list(handler.headers.items())
    if any(n.lower() == 'x-amz-security-token' for n, _ in pairs):
        _record_failure(app.store, who)
        raise BedrockError('UnrecognizedClientException', 'Temporary session credentials are not issued by this server.')
    try:
        verified = sigv4.verify(method, target, pairs, body, secret_for)
    except sigv4.SigV4Error as exc:
        _record_failure(app.store, who)
        key = ''
        try:
            key = sigv4.parse_authorization(authorization)[0]
        except sigv4.SigV4Error:
            pass
        _audit_failure(app, creds, key, exc.code, info)
        raise BedrockError(exc.code, exc.message)
    return found['principal'], verified.service, verified.region


def _read_body(handler):
    if handler.headers.get('Transfer-Encoding'):
        raise errors.validation('Chunked request bodies are not accepted')
    try:
        size = int(handler.headers.get('Content-Length', '0') or 0)
    except ValueError:
        raise errors.validation('Invalid Content-Length')
    if size < 0 or size > BODY_LIMIT:
        raise BedrockError('ValidationException', 'Request body exceeds %d MiB' % (BODY_LIMIT // (1024 * 1024)), 413)
    return handler.rfile.read(size) if size else b''


def _send(handler, result, rid):
    headers = {'x-amzn-RequestId': rid, **result.headers}
    if isinstance(result, Stream):
        _stream(handler, result, headers)
        return
    body = result.body
    if body is None:
        raw = b''
    elif isinstance(body, bytes):
        raw = body
    else:
        raw = json.dumps(body, separators=(',', ':')).encode()
        headers.setdefault('Content-Type', 'application/json')
    headers.setdefault('Content-Type', 'application/octet-stream')
    handler.respond(result.status, raw, headers)


def _stream(handler, result, headers):
    handler.send_response(result.status)
    handler.send_header('Content-Type', eventstream.CONTENT_TYPE)
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.send_header('Connection', 'close')
    for k, v in headers.items():
        if k != 'Content-Type':
            handler.send_header(k, v)
    handler.end_headers()
    handler.close_connection = True
    frames = iter(result.frames)
    try:
        for frame in frames:
            handler.wfile.write(frame)
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        getattr(frames, 'close', lambda: None)()
    except BedrockError as exc:
        handler.wfile.write(eventstream.exception_event(errors.stream_exception(exc.error_type), exc.message))
    except Fault as exc:
        mapped = errors.from_fault(exc)
        handler.wfile.write(eventstream.exception_event(errors.stream_exception(mapped.error_type), mapped.message))
    except Exception:
        traceback.print_exc()
        handler.wfile.write(eventstream.exception_event('internalServerException', 'Internal server error'))


def handle(handler, method, router=None):
    router = router or ROUTER
    rid = new_request_id()
    try:
        target = handler.path
        parts = urlsplit(target)
        body = _read_body(handler)
        principal, service, region = authenticate(handler, method, target, body)
        # The credential-scope service does not pick the route: botocore signs bedrock-runtime,
        # bedrock-agent and bedrock-agent-runtime requests with the signing name `bedrock`.
        route, params = router.find(None, method, parts.path)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        if route.handler is None:
            raise BedrockError('UnsupportedOperationException', f'{route.operation} is recognised but not implemented by this Nuvora release', 501)
        request = Request(handler, method, parts.path, params, query, body, principal, route.service, region, rid, route)
        result = route.handler(request)
        _send(handler, result, rid)
    except BedrockError as exc:
        handler.respond(exc.status, exc.body(), exc.headers(rid))
    except Fault as exc:
        mapped = errors.from_fault(exc)
        handler.respond(mapped.status, mapped.body(), mapped.headers(rid))
    except KeyError:
        missing = errors.not_found('Resource not found')
        handler.respond(missing.status, missing.body(), missing.headers(rid))
    except (BrokenPipeError, ConnectionResetError):
        pass
    except Exception:
        traceback.print_exc()
        failure = errors.internal()
        handler.respond(failure.status, failure.body(), failure.headers(rid))
