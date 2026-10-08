# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""bedrock-agent control plane: knowledge bases, data sources, ingestion jobs, agents, agent aliases,
action groups, agent/knowledge-base associations and tags.

Nothing here owns state the console cannot see. A knowledge base is a Nuvora `knowledge` resource, a data
source is a `connectors` resource, an ingestion job is an N3 `ingestion` job, an agent is an `agents`
resource (its DRAFT), an action group is a set of `actions` imported from an inline OpenAPI document.
What Bedrock has and Nuvora does not (descriptions, role ARNs, tags, numbered agent versions, aliases)
lives in small side records:

    bedrock_agent_meta     per KB / data source / agent: description, roleArn, tags, status flags
    agent_versions         numbered agent versions (pin a revision of the generic /api/agents/{id}/versions history)
    agent_aliases          alias id -> agent version
    agent_action_groups    action groups per agent version
    agent_knowledge_bases  KB associations per agent version

A field Nuvora cannot honour is a ValidationException naming it; nothing is silently dropped. A field
Nuvora can only record (roleArn, idleSessionTTLInSeconds, ...) is stored, echoed and documented as unused.

ARNs: `arn:nuvora:bedrock:<region>:<tenant>:<kind>/<id>` with kind `knowledge-base`, `agent`,
`agent-alias` (resource `agent-alias/<agentId>/<aliasId>`). Every path parameter takes an id or an ARN.
Model references use the existing `arn:nuvora:bedrock:<region>::foundation-model/<model id>`.

B3 (InvokeAgent) resolves an alias with `resolve_alias(req, agent_id, alias_id)`."""
import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit

from .. import pagination
from ..security import Fault, require
from ..store import canonical
from . import errors
from .router import AGENT, Response

PARTITION = 'arn:nuvora:bedrock'
DRAFT = 'DRAFT'
TEST_ALIAS = 'TSTALIASID'
META, VERSIONS, ALIASES, GROUPS, ASSOCIATIONS = 'bedrock_agent_meta', 'agent_versions', 'agent_aliases', 'agent_action_groups', 'agent_knowledge_bases'
NAME = re.compile(r'([0-9a-zA-Z][_-]?){1,100}')
TOKEN = re.compile(r'[a-zA-Z0-9](-*[a-zA-Z0-9]){0,256}')
SECRET = re.compile(r'NUVORA_SECRET_[A-Z0-9_]{1,100}')
ID_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
DEFAULT_IDLE_TTL = 600
MAX_VERSIONS = 200
MAX_TAGS = 50
BUILTIN_STORE = 'NUVORA_BUILTIN'

# Routes Bedrock defines that the shared table in router.py does not list yet. `install` adds those
# that are missing, so this module needs no edit to the table.
ROUTES = [
    ('POST', '/agents/{agentId}', 'PrepareAgent'),
    ('GET', '/agents/{agentId}/agentversions/{agentVersion}', 'GetAgentVersion'),
    ('DELETE', '/agents/{agentId}/agentversions/{agentVersion}', 'DeleteAgentVersion'),
    ('GET', '/agents/{agentId}/agentaliases/{agentAliasId}', 'GetAgentAlias'),
    ('PUT', '/agents/{agentId}/agentaliases/{agentAliasId}', 'UpdateAgentAlias'),
    ('DELETE', '/agents/{agentId}/agentaliases/{agentAliasId}', 'DeleteAgentAlias'),
    ('PUT', '/agents/{agentId}/agentversions/{agentVersion}/actiongroups', 'CreateAgentActionGroup'),
    ('POST', '/agents/{agentId}/agentversions/{agentVersion}/actiongroups', 'ListAgentActionGroups'),
    ('GET', '/agents/{agentId}/agentversions/{agentVersion}/actiongroups/{actionGroupId}', 'GetAgentActionGroup'),
    ('PUT', '/agents/{agentId}/agentversions/{agentVersion}/actiongroups/{actionGroupId}', 'UpdateAgentActionGroup'),
    ('DELETE', '/agents/{agentId}/agentversions/{agentVersion}/actiongroups/{actionGroupId}', 'DeleteAgentActionGroup'),
    ('PUT', '/agents/{agentId}/agentversions/{agentVersion}/knowledgebases', 'AssociateAgentKnowledgeBase'),
    ('POST', '/agents/{agentId}/agentversions/{agentVersion}/knowledgebases', 'ListAgentKnowledgeBases'),
    ('GET', '/agents/{agentId}/agentversions/{agentVersion}/knowledgebases/{knowledgeBaseId}', 'GetAgentKnowledgeBase'),
    ('PUT', '/agents/{agentId}/agentversions/{agentVersion}/knowledgebases/{knowledgeBaseId}', 'UpdateAgentKnowledgeBase'),
    ('DELETE', '/agents/{agentId}/agentversions/{agentVersion}/knowledgebases/{knowledgeBaseId}', 'DisassociateAgentKnowledgeBase'),
    ('PUT', '/knowledgebases/{knowledgeBaseId}', 'UpdateKnowledgeBase'),
    ('POST', '/knowledgebases/{knowledgeBaseId}/datasources', 'ListDataSources'),
    ('GET', '/knowledgebases/{knowledgeBaseId}/datasources/{dataSourceId}', 'GetDataSource'),
    ('PUT', '/knowledgebases/{knowledgeBaseId}/datasources/{dataSourceId}', 'UpdateDataSource'),
    ('DELETE', '/knowledgebases/{knowledgeBaseId}/datasources/{dataSourceId}', 'DeleteDataSource'),
    ('GET', '/tags/{resourceArn}', 'ListTagsForResource'),
    ('POST', '/tags/{resourceArn}', 'TagResource'),
    ('DELETE', '/tags/{resourceArn}', 'UntagResource'),
]


# ---- small helpers ----------------------------------------------------------------------

def iso(ts):
    """Timestamp as the ISO-8601 string Bedrock returns (botocore parses it into a datetime)."""
    return datetime.fromtimestamp(ts or 0, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def new_id():
    return ''.join(secrets.choice(ID_ALPHABET) for _ in range(10))


def region_of(req):
    return req.region or 'local'


def arn(req, kind, ident):
    return f"{PARTITION}:{region_of(req)}:{req.principal['tenant']}:{kind}/{ident}"


def parse_arn(req, value, kinds):
    """(kind, resource) of one of our ARNs; a foreign partition or tenant is rejected."""
    parts = value.split(':', 5)
    if len(parts) != 6 or parts[:3] != ['arn', 'nuvora', 'bedrock'] or '/' not in parts[5]:
        raise errors.validation(f'{value} is not a Nuvora Bedrock ARN (arn:nuvora:bedrock:<region>:<tenant>:<kind>/<id>)')
    kind, _, rest = parts[5].partition('/')
    if kind not in kinds:
        raise errors.validation(f'{value} is not a {" or ".join(kinds)} ARN')
    if parts[4] != req.principal['tenant']:
        raise errors.not_found(f'No such resource: {value}')
    return kind, rest


def ref(req, kind, value, label):
    """The id behind an id-or-ARN path parameter or member."""
    if not isinstance(value, str) or not value:
        raise errors.validation(f'{label} is required')
    if value.startswith('arn:'):
        found, rest = parse_arn(req, value, (kind,))
        return rest.split('/')[-1] if found == 'agent-alias' else rest
    return value


def check_fields(body, allowed, refused=(), where=''):
    """Reject members Nuvora cannot honour (named, with the reason) and members the API does not define."""
    refusals = dict(refused)
    for name in body:
        if name in refusals:
            if body[name] not in (None, {}, []):
                raise errors.validation(f'{where}{name} is not supported by Nuvora: {refusals[name]}')
        elif name not in allowed:
            raise errors.validation(f'Unsupported member: {where}{name}')


def text(body, key, low=1, high=200, required=False, pattern=None, where=''):
    value = body.get(key)
    if value is None:
        if required:
            raise errors.validation(f'{where}{key} is required')
        return None
    if not isinstance(value, str) or not low <= len(value) <= high:
        raise errors.validation(f'{where}{key} must be a string of {low}-{high} characters')
    if pattern is not None and not pattern.fullmatch(value):
        raise errors.validation(f'{where}{key} has an invalid format')
    return value


def mapping(body, key, required=False):
    value = body.get(key)
    if value is None:
        if required:
            raise errors.validation(f'{key} is required')
        return {}
    if not isinstance(value, dict):
        raise errors.validation(f'{key} must be an object')
    return value


def page_items(body, items):
    """maxResults (1-1000, served in pages of at most 100) and nextToken over items carrying `id` and `created`."""
    size = body.get('maxResults')
    if size is not None and (not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= 1000):
        raise errors.validation('maxResults must be an integer from 1 to 1000')
    token = body.get('nextToken')
    if token is not None and (not isinstance(token, str) or not token):
        raise errors.validation('nextToken must be a non-empty string')
    return pagination.page(items, min(size or pagination.MAX_RESULTS, pagination.MAX_RESULTS), token)


def with_token(out, key, items, token):
    out[key] = items
    if token:
        out['nextToken'] = token
    return out


def meta_get(app, tenant, ident):
    try:
        return app.store.get(tenant, META, ident)
    except KeyError:
        return {}


def meta_put(app, tenant, ident, **changes):
    current = meta_get(app, tenant, ident)
    data = {k: v for k, v in current.items() if k not in ('id', 'revision', 'created', 'updated')}
    data.update(changes)
    return app.store.put(tenant, META, data, ident)


def audit(req, action, target, **detail):
    p = req.principal
    req.app.store.audit(p['tenant'], p['username'], 'bedrock_agent.' + action, target, detail)


def writer(req):
    require(req.principal, 'developer', 'admin')


def lookup(req, kind, ident, label):
    try:
        return req.app.get(req.principal, kind, ident)
    except KeyError:
        raise errors.not_found(f'{label} {ident} does not exist') from None


def unique(items, name, label, exclude=None):
    if any(i['name'] == name and i['id'] != exclude for i in items):
        raise errors.BedrockError('ConflictException', f'{label} named {name} already exists')


def tag_map(value):
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_TAGS:
        raise errors.validation(f'tags must be an object of at most {MAX_TAGS} entries')
    for k, v in value.items():
        if not isinstance(k, str) or not 1 <= len(k) <= 128 or not isinstance(v, str) or len(v) > 256:
            raise errors.validation('Tag keys are 1-128 characters and values at most 256')
    return dict(value)


def save(req, kind, data, ident=None, existing=None):
    """app.create with optimistic locking on update; a lost race is a ConflictException."""
    if existing is not None:
        data = {**data, 'expected_revision': existing['revision']}
    try:
        return req.app.create(req.principal, kind, data, ident)
    except ValueError:
        raise errors.BedrockError('ConflictException', 'The resource was changed by another request; retry') from None


def idempotent(req, op, scope, body, make, fetch):
    """Replay a create that carries a clientToken. `make()` returns (payload, resource id); `fetch(id)` the payload again."""
    token = body.get('clientToken')
    if token is None:
        return make()[0]
    if not isinstance(token, str) or not 33 <= len(token) <= 256 or not TOKEN.fullmatch(token):
        raise errors.validation('clientToken must be 33-256 alphanumeric characters or hyphens')
    app, tenant = req.app, req.principal['tenant']
    key = f'bedrock-agent:{op}:{scope}:{token}'
    fingerprint = hashlib.sha256(canonical({k: v for k, v in body.items() if k != 'clientToken'}).encode()).hexdigest()
    with app.store.transaction():
        row = app.store.db.execute('SELECT * FROM idempotency WHERE tenant=? AND key=?', (tenant, key)).fetchone()
        if row:
            if row['fingerprint'] != fingerprint:
                raise errors.BedrockError('ConflictException', 'clientToken was already used for a different request')
            try:
                return fetch(json.loads(row['value'])['id'])
            except KeyError:
                app.store.db.execute('DELETE FROM idempotency WHERE tenant=? AND key=?', (tenant, key))
        payload, ident = make()
        app.store.db.execute('INSERT INTO idempotency (tenant,key,fingerprint,value) VALUES (?,?,?,?)', (tenant, key, fingerprint, canonical({'id': ident})))
    return payload


def model_ref(req, value, label, capability='chat'):
    """The Nuvora model id behind a model id or foundation-model ARN."""
    if not isinstance(value, str) or not value:
        raise errors.validation(f'{label} is required')
    ident = value
    if value.startswith('arn:'):
        parts = value.split(':', 5)
        if len(parts) != 6 or parts[:3] != ['arn', 'nuvora', 'bedrock'] or not parts[5].startswith('foundation-model/'):
            raise errors.validation(f'{label} must be a Nuvora model id or an arn:nuvora:bedrock:<region>::foundation-model/<id> ARN')
        ident = parts[5][len('foundation-model/'):]
    try:
        model = req.app.get(req.principal, 'models', ident)
    except KeyError:
        raise errors.validation(f'{label}: no model {ident} is registered for this tenant (register it in Nuvora; Bedrock model ids are not aliases)') from None
    if model.get('capability', 'chat') != capability:
        raise errors.validation(f'{label}: model {ident} has capability {model.get("capability", "chat")}, this member needs {capability}')
    if not model.get('enabled', True):
        raise errors.validation(f'{label}: model {ident} is disabled')
    return ident


def model_arn(req, ident):
    return f'{PARTITION}:{region_of(req)}::foundation-model/{ident}'


# ---- knowledge bases --------------------------------------------------------------------

VECTOR_REFUSED = {'embeddingModelConfiguration': 'Nuvora uses the embedding model as registered; per-request dimensions and data types are not available',
                  'supplementalDataStorageConfiguration': 'multimodal supplemental storage is not available'}


def kb_status(req, kb):
    return req.app.knowledge_view([kb], req.principal['tenant'])[0]['status']


def kb_view(req, kb):
    meta = meta_get(req.app, req.principal['tenant'], kb['id'])
    vector = {'embeddingModelArn': model_arn(req, kb['embedding_model'])} if kb.get('embedding_model') else {}
    status = kb_status(req, kb)
    out = {'knowledgeBaseId': kb['id'], 'name': kb['name'], 'knowledgeBaseArn': arn(req, 'knowledge-base', kb['id']),
           'roleArn': meta.get('roleArn', ''), 'knowledgeBaseConfiguration': {'type': 'VECTOR', 'vectorKnowledgeBaseConfiguration': vector},
           'storageConfiguration': {'type': BUILTIN_STORE}, 'status': status, 'createdAt': iso(kb['created']), 'updatedAt': iso(max(kb['updated'], meta.get('updated', 0)))}
    if meta.get('description'):
        out['description'] = meta['description']
    if status == 'FAILED':
        out['failureReasons'] = ['The latest ingestion job failed; see GetIngestionJob']
    return out


def kb_config(req, body):
    """(embedding model id, storage ok) from the request's configuration members."""
    cfg = mapping(body, 'knowledgeBaseConfiguration', True)
    kind = cfg.get('type')
    if kind != 'VECTOR':
        raise errors.validation(f'knowledgeBaseConfiguration.type {kind} is not supported by Nuvora: only VECTOR knowledge bases exist')
    check_fields(cfg, {'type', 'vectorKnowledgeBaseConfiguration'}, {'kendraKnowledgeBaseConfiguration': 'Kendra is not available',
                                                                       'sqlKnowledgeBaseConfiguration': 'structured (SQL) retrieval is not available',
                                                                       'managedKnowledgeBaseConfiguration': 'managed knowledge bases are not available'}, 'knowledgeBaseConfiguration.')
    vector = mapping(cfg, 'vectorKnowledgeBaseConfiguration', True)
    check_fields(vector, {'embeddingModelArn'}, VECTOR_REFUSED, 'knowledgeBaseConfiguration.vectorKnowledgeBaseConfiguration.')
    model = model_ref(req, vector.get('embeddingModelArn'), 'embeddingModelArn', 'embedding')
    storage = mapping(body, 'storageConfiguration')
    if storage:
        kind = storage.get('type')
        if kind != BUILTIN_STORE:
            raise errors.validation(f'storageConfiguration.type {kind} is not supported by Nuvora: vectors live in the built-in Nuvora store; omit storageConfiguration or use type {BUILTIN_STORE}')
        extra = sorted(set(storage) - {'type'})
        if extra:
            raise errors.validation('storageConfiguration.' + extra[0] + ' is not supported by Nuvora: the built-in store takes no settings')
    return model


def kb_common(body):
    name = text(body, 'name', 1, 100, True, NAME)
    description = text(body, 'description', 1, 200)
    role = text(body, 'roleArn', 0, 2048, True)
    return name, description, role


def create_knowledge_base(req):
    writer(req)
    body = req.json()
    check_fields(body, {'clientToken', 'name', 'description', 'roleArn', 'knowledgeBaseConfiguration', 'storageConfiguration', 'tags'})
    name, description, role = kb_common(body)
    tags = tag_map(body.get('tags'))
    model = kb_config(req, body)
    app, tenant = req.app, req.principal['tenant']

    def make():
        unique(app.list(req.principal, 'knowledge'), name, 'A knowledge base')
        kb = app.create(req.principal, 'knowledge', {'name': name, 'embedding_model': model})
        meta_put(app, tenant, kb['id'], kind='knowledge-base', description=description, roleArn=role, tags=tags)
        audit(req, 'knowledge_base.created', kb['id'])
        return {'knowledgeBase': kb_view(req, kb)}, kb['id']
    return Response(idempotent(req, 'CreateKnowledgeBase', '', body, make, lambda i: {'knowledgeBase': kb_view(req, app.get(req.principal, 'knowledge', i))}), 202)


def get_knowledge_base(req):
    kb = lookup(req, 'knowledge', ref(req, 'knowledge-base', req.params['knowledgeBaseId'], 'knowledgeBaseId'), 'Knowledge base')
    return Response({'knowledgeBase': kb_view(req, kb)})


def list_knowledge_bases(req):
    body = req.json()
    check_fields(body, {'maxResults', 'nextToken'})
    items = req.app.knowledge_view(req.app.list(req.principal, 'knowledge'), req.principal['tenant'])
    chosen, token = page_items(body, items)
    out = []
    for kb in chosen:
        meta = meta_get(req.app, req.principal['tenant'], kb['id'])
        row = {'knowledgeBaseId': kb['id'], 'name': kb['name'], 'status': kb['status'], 'updatedAt': iso(max(kb['updated'], meta.get('updated', 0)))}
        if meta.get('description'):
            row['description'] = meta['description']
        out.append(row)
    return Response(with_token({}, 'knowledgeBaseSummaries', out, token))


def update_knowledge_base(req):
    writer(req)
    kb = lookup(req, 'knowledge', ref(req, 'knowledge-base', req.params['knowledgeBaseId'], 'knowledgeBaseId'), 'Knowledge base')
    body = req.json()
    check_fields(body, {'name', 'description', 'roleArn', 'knowledgeBaseConfiguration', 'storageConfiguration'})
    name, description, role = kb_common(body)
    model = kb_config(req, body)
    if model != kb.get('embedding_model'):
        raise errors.validation('knowledgeBaseConfiguration.vectorKnowledgeBaseConfiguration.embeddingModelArn cannot be changed: existing documents are embedded with the current model')
    unique(req.app.list(req.principal, 'knowledge'), name, 'A knowledge base', kb['id'])
    keep = {k: kb[k] for k in ('embedding_model', 'rerank_model', 'ocr_model', 'transcription_model') if kb.get(k)}
    kb = save(req, 'knowledge', {**keep, 'name': name}, kb['id'], kb)
    meta_put(req.app, req.principal['tenant'], kb['id'], description=description, roleArn=role)
    audit(req, 'knowledge_base.updated', kb['id'])
    return Response({'knowledgeBase': kb_view(req, kb)}, 202)


def delete_knowledge_base(req):
    kb = lookup(req, 'knowledge', ref(req, 'knowledge-base', req.params['knowledgeBaseId'], 'knowledgeBaseId'), 'Knowledge base')
    app, tenant = req.app, req.principal['tenant']
    users = sorted({r['agent_id'] for r in app.store.list(tenant, ASSOCIATIONS) if r['knowledge_base_id'] == kb['id']})
    if users:
        raise errors.BedrockError('ConflictException', 'The knowledge base is associated with agent(s) ' + ', '.join(users) + '; disassociate it first')
    app.delete(req.principal, 'knowledge', kb['id'])
    try:
        app.store.delete(tenant, META, kb['id'])
    except KeyError:
        pass
    audit(req, 'knowledge_base.deleted', kb['id'])
    return Response({'knowledgeBaseId': kb['id'], 'status': 'DELETING'}, 202)


# ---- data sources (connectors) ----------------------------------------------------------

DS_ALLOWED = {'clientToken', 'name', 'description', 'dataSourceConfiguration', 'dataDeletionPolicy'}
DS_REFUSED = {'serverSideEncryptionConfiguration': 'Nuvora does not encrypt per resource',
              'vectorIngestionConfiguration': 'chunking, parsing and enrichment are fixed (the knowledge base chunker and its models)'}
DS_TYPES = ('WEB', 'S3', 'CONFLUENCE')
S3_ARN = re.compile(r'arn:aws(?:-cn|-us-gov)?:s3:::([a-z0-9][a-z0-9.-]{1,61}[a-z0-9])')


def connector_fields(cfg):
    """(connector fields, config to echo) for a dataSourceConfiguration; refuses what Nuvora cannot crawl."""
    kind = cfg.get('type')
    if kind not in DS_TYPES:
        raise errors.validation(f'dataSourceConfiguration.type {kind} is not supported by Nuvora: only {", ".join(DS_TYPES)} data sources exist (Salesforce, SharePoint, custom and managed connectors are not available)')
    members = {'WEB': 'webConfiguration', 'S3': 's3Configuration', 'CONFLUENCE': 'confluenceConfiguration'}
    others = {'managedKnowledgeBaseConnectorConfiguration', 'salesforceConfiguration', 'sharePointConfiguration', 'webConfiguration', 's3Configuration', 'confluenceConfiguration'} - {members[kind]}
    for name in sorted(others):
        if cfg.get(name):
            raise errors.validation(f'dataSourceConfiguration.{name} does not match type {kind}')
    check_fields(cfg, {'type', members[kind]}, {n: 'not available' for n in others}, 'dataSourceConfiguration.')
    section = mapping(cfg, members[kind], True)
    where = f'dataSourceConfiguration.{members[kind]}.'
    if kind == 'WEB':
        check_fields(section, {'sourceConfiguration', 'crawlerConfiguration'}, (), where)
        seeds = ((mapping(mapping(section, 'sourceConfiguration', True), 'urlConfiguration', True)).get('seedUrls')) or []
        if not isinstance(seeds, list) or len(seeds) != 1 or not isinstance(seeds[0], dict) or not isinstance(seeds[0].get('url'), str):
            raise errors.validation(where + 'sourceConfiguration.urlConfiguration.seedUrls must hold exactly one seed URL: Nuvora crawls one site per data source')
        crawler = mapping(section, 'crawlerConfiguration')
        check_fields(crawler, {'crawlerLimits', 'scope'}, {'inclusionFilters': 'URL pattern filters are not available (robots.txt and the host allowlist apply)',
                                                            'exclusionFilters': 'URL pattern filters are not available (robots.txt and the host allowlist apply)',
                                                            'userAgent': 'the crawler identifies itself as NuvoraConnector', 'userAgentHeader': 'the crawler identifies itself as NuvoraConnector'}, where + 'crawlerConfiguration.')
        if crawler.get('scope') not in (None, 'HOST_ONLY'):
            raise errors.validation(where + f'crawlerConfiguration.scope {crawler["scope"]} is not supported by Nuvora: the crawl stays on the seed host (HOST_ONLY)')
        limits = mapping(crawler, 'crawlerLimits')
        check_fields(limits, {'maxPages'}, {'rateLimit': 'Nuvora honours the site robots.txt crawl-delay instead'}, where + 'crawlerConfiguration.crawlerLimits.')
        fields = {'type': 'web', 'url': seeds[0]['url']}
        if limits.get('maxPages') is not None:
            if not isinstance(limits['maxPages'], int) or isinstance(limits['maxPages'], bool):
                raise errors.validation(where + 'crawlerConfiguration.crawlerLimits.maxPages must be an integer')
            fields['max_pages'] = limits['maxPages']
    elif kind == 'S3':
        check_fields(section, {'bucketArn', 'inclusionPrefixes'}, {'bucketOwnerAccountId': 'Nuvora reads the bucket with the host credentials, not a cross-account owner'}, where)
        match = S3_ARN.fullmatch(text(section, 'bucketArn', 1, 2048, True, where=where) or '')
        if not match:
            raise errors.validation(where + 'bucketArn must be arn:aws:s3:::<bucket>')
        prefixes = section.get('inclusionPrefixes') or []
        if not isinstance(prefixes, list) or len(prefixes) > 1 or any(not isinstance(x, str) for x in prefixes):
            raise errors.validation(where + 'inclusionPrefixes may hold at most one prefix: Nuvora reads one prefix per data source')
        fields = {'type': 's3', 'bucket': match.group(1), 'prefix': prefixes[0] if prefixes else ''}
    else:
        check_fields(section, {'sourceConfiguration', 'crawlerConfiguration'}, (), where)
        source = mapping(section, 'sourceConfiguration', True)
        check_fields(source, {'hostUrl', 'hostType', 'authType', 'credentialsSecretArn'}, (), where + 'sourceConfiguration.')
        secret = text(source, 'credentialsSecretArn', 1, 2048, True, where=where + 'sourceConfiguration.')
        name = secret.partition(':secret:')[2] if secret.startswith('arn:') else secret
        if not SECRET.fullmatch(name):
            raise errors.validation(where + 'sourceConfiguration.credentialsSecretArn must end in a NUVORA_SECRET_* environment variable name (arn:aws:secretsmanager:<region>:<account>:secret:NUVORA_SECRET_NAME); Nuvora does not read AWS Secrets Manager')
        if source.get('authType') not in ('BASIC', 'OAUTH2_CLIENT_CREDENTIALS') or source.get('hostType') not in (None, 'SAAS'):
            raise errors.validation(where + 'sourceConfiguration.authType must be BASIC or OAUTH2_CLIENT_CREDENTIALS and hostType SAAS')
        space = None
        crawl = mapping(mapping(section, 'crawlerConfiguration'), 'filterConfiguration')
        for entry in (mapping(crawl, 'patternObjectFilter').get('filters') or []):
            if isinstance(entry, dict) and entry.get('objectType') == 'Space' and len(entry.get('inclusionFilters') or []) == 1 and not entry.get('exclusionFilters'):
                space = entry['inclusionFilters'][0]
        if not space:
            raise errors.validation(where + 'crawlerConfiguration.filterConfiguration.patternObjectFilter.filters needs one {objectType: "Space", inclusionFilters: ["<space key>"]} entry: Nuvora syncs one space per data source')
        fields = {'type': 'confluence', 'url': text(source, 'hostUrl', 1, 2048, True, where=where + 'sourceConfiguration.'), 'space': space, 'key_env': name}
    return fields, cfg


def deletion_policy(body):
    policy = body.get('dataDeletionPolicy')
    if policy not in (None, 'RETAIN'):
        raise errors.validation('dataDeletionPolicy ' + str(policy) + ' is not supported by Nuvora: deleting a data source keeps the documents it ingested (RETAIN)')
    return 'RETAIN'


def connector_of(req, kb_id, ds_id):
    kb = lookup(req, 'knowledge', ref(req, 'knowledge-base', kb_id, 'knowledgeBaseId'), 'Knowledge base')
    try:
        connector = req.app.get(req.principal, 'connectors', ds_id)
    except KeyError:
        connector = None
    if connector is None or connector['knowledge_id'] != kb['id']:
        raise errors.not_found(f'Data source {ds_id} does not exist in knowledge base {kb["id"]}')
    return kb, connector


def ds_view(req, kb_id, connector):
    meta = meta_get(req.app, req.principal['tenant'], connector['id'])
    out = {'knowledgeBaseId': kb_id, 'dataSourceId': connector['id'], 'name': connector['name'], 'status': 'AVAILABLE',
           'dataSourceConfiguration': meta.get('dataSourceConfiguration') or {'type': connector['type'].upper()},
           'dataDeletionPolicy': meta.get('dataDeletionPolicy', 'RETAIN'), 'createdAt': iso(connector['created']),
           'updatedAt': iso(max(connector['updated'], meta.get('updated', 0)))}
    if meta.get('description'):
        out['description'] = meta['description']
    return out


def create_data_source(req):
    writer(req)
    kb = lookup(req, 'knowledge', ref(req, 'knowledge-base', req.params['knowledgeBaseId'], 'knowledgeBaseId'), 'Knowledge base')
    body = req.json()
    check_fields(body, DS_ALLOWED, DS_REFUSED)
    name = text(body, 'name', 1, 100, True, NAME)
    description = text(body, 'description', 1, 200)
    fields, echo = connector_fields(mapping(body, 'dataSourceConfiguration', True))
    policy = deletion_policy(body)
    app, tenant = req.app, req.principal['tenant']

    def make():
        unique([c for c in app.list(req.principal, 'connectors') if c['knowledge_id'] == kb['id']], name, 'A data source')
        connector = app.create(req.principal, 'connectors', {**fields, 'name': name, 'knowledge_id': kb['id']})
        meta_put(app, tenant, connector['id'], kind='data-source', description=description, dataSourceConfiguration=echo, dataDeletionPolicy=policy)
        audit(req, 'data_source.created', connector['id'], knowledge_base=kb['id'])
        return {'dataSource': ds_view(req, kb['id'], connector)}, connector['id']
    return Response(idempotent(req, 'CreateDataSource', kb['id'], body, make, lambda i: {'dataSource': ds_view(req, kb['id'], app.get(req.principal, 'connectors', i))}))


def get_data_source(req):
    kb, connector = connector_of(req, req.params['knowledgeBaseId'], req.params['dataSourceId'])
    return Response({'dataSource': ds_view(req, kb['id'], connector)})


def list_data_sources(req):
    kb = lookup(req, 'knowledge', ref(req, 'knowledge-base', req.params['knowledgeBaseId'], 'knowledgeBaseId'), 'Knowledge base')
    body = req.json()
    check_fields(body, {'maxResults', 'nextToken'})
    chosen, token = page_items(body, [c for c in req.app.list(req.principal, 'connectors') if c['knowledge_id'] == kb['id']])
    out = []
    for c in chosen:
        meta = meta_get(req.app, req.principal['tenant'], c['id'])
        row = {'knowledgeBaseId': kb['id'], 'dataSourceId': c['id'], 'name': c['name'], 'status': 'AVAILABLE', 'updatedAt': iso(max(c['updated'], meta.get('updated', 0)))}
        if meta.get('description'):
            row['description'] = meta['description']
        out.append(row)
    return Response(with_token({}, 'dataSourceSummaries', out, token))


def update_data_source(req):
    writer(req)
    kb, connector = connector_of(req, req.params['knowledgeBaseId'], req.params['dataSourceId'])
    body = req.json()
    check_fields(body, DS_ALLOWED - {'clientToken'}, DS_REFUSED)
    name = text(body, 'name', 1, 100, True, NAME)
    description = text(body, 'description', 1, 200)
    fields, echo = connector_fields(mapping(body, 'dataSourceConfiguration', True))
    if fields['type'] != connector['type']:
        raise errors.validation('dataSourceConfiguration.type cannot be changed')
    policy = deletion_policy(body)
    unique([c for c in req.app.list(req.principal, 'connectors') if c['knowledge_id'] == kb['id']], name, 'A data source', connector['id'])
    keep = {k: connector[k] for k in ('metadata', 'groups', 'interval_minutes', 'depth', 'username', 'region') if connector.get(k) is not None}
    updated = save(req, 'connectors', {**keep, **fields, 'name': name, 'knowledge_id': kb['id']}, connector['id'], connector)
    meta_put(req.app, req.principal['tenant'], connector['id'], description=description, dataSourceConfiguration=echo, dataDeletionPolicy=policy)
    audit(req, 'data_source.updated', connector['id'])
    return Response({'dataSource': ds_view(req, kb['id'], updated)})


def delete_data_source(req):
    kb, connector = connector_of(req, req.params['knowledgeBaseId'], req.params['dataSourceId'])
    req.app.delete(req.principal, 'connectors', connector['id'])
    try:
        req.app.store.delete(req.principal['tenant'], META, connector['id'])
    except KeyError:
        pass
    audit(req, 'data_source.deleted', connector['id'])
    return Response({'knowledgeBaseId': kb['id'], 'dataSourceId': connector['id'], 'status': 'DELETING'}, 202)


# ---- ingestion jobs ---------------------------------------------------------------------

JOB_FILTERS = ('STATUS',)


def statistics(stats):
    return {'numberOfDocumentsScanned': stats['documents_scanned'], 'numberOfMetadataDocumentsScanned': 0,
            'numberOfNewDocumentsIndexed': stats['documents_new'], 'numberOfModifiedDocumentsIndexed': stats['documents_modified'],
            'numberOfMetadataDocumentsModified': 0, 'numberOfDocumentsDeleted': stats['documents_deleted'],
            'numberOfDocumentsFailed': stats['documents_failed'], 'numberOfDocumentsSkipped': stats['documents_unchanged']}


def job_view(kb_id, ds_id, view, summary=False):
    out = {'knowledgeBaseId': kb_id, 'dataSourceId': ds_id, 'ingestionJobId': view['id'], 'status': view['status'],
           'statistics': statistics(view['statistics']), 'startedAt': iso(view.get('started') or view['created']), 'updatedAt': iso(view['updated'])}
    if view.get('description'):
        out['description'] = view['description']
    if not summary:
        out['failureReasons'] = [str(r)[:2048] for r in view.get('failure_reasons', [])]
    return out


def job_for(req, kb_id, ds_id, job_id):
    """The ingestion job `job_id` when it ran for this data source, else 404."""
    try:
        view = req.app.ingestion_job(req.principal, kb_id, job_id)
        job = req.app.get(req.principal, 'jobs', job_id)
    except KeyError:
        raise errors.not_found(f'Ingestion job {job_id} does not exist') from None
    if job['input'].get('connector_id') != ds_id:
        raise errors.not_found(f'Ingestion job {job_id} does not belong to data source {ds_id}')
    return view


def start_ingestion_job(req):
    writer(req)
    kb, connector = connector_of(req, req.params['knowledgeBaseId'], req.params['dataSourceId'])
    body = req.json()
    check_fields(body, {'clientToken', 'description'})
    description = text(body, 'description', 1, 200)
    token = body.get('clientToken')
    if token is not None and (not isinstance(token, str) or not 33 <= len(token) <= 256 or not TOKEN.fullmatch(token)):
        raise errors.validation('clientToken must be 33-256 alphanumeric characters or hyphens')
    spec = {'source': 'connector', 'connector_id': connector['id'], **({'description': description} if description else {})}
    key = 'bedrock-agent:ingest:' + hashlib.sha256(token.encode()).hexdigest()[:40] if token else None
    job = req.app.new_job(req.principal, 'ingestion', kb['id'], spec, key)
    return Response({'ingestionJob': job_view(kb['id'], connector['id'], req.app.ingestion_view(job))}, 202)


def get_ingestion_job(req):
    kb, connector = connector_of(req, req.params['knowledgeBaseId'], req.params['dataSourceId'])
    return Response({'ingestionJob': job_view(kb['id'], connector['id'], job_for(req, kb['id'], connector['id'], req.params['ingestionJobId']))})


def list_ingestion_jobs(req):
    kb, connector = connector_of(req, req.params['knowledgeBaseId'], req.params['dataSourceId'])
    body = req.json()
    check_fields(body, {'filters', 'sortBy', 'maxResults', 'nextToken'})
    sort = mapping(body, 'sortBy')
    if sort and (sort.get('attribute') != 'STARTED_AT' or sort.get('order') != 'DESCENDING'):
        raise errors.validation('sortBy is not supported by Nuvora beyond {attribute: STARTED_AT, order: DESCENDING}, the order jobs are always returned in')
    wanted = None
    for f in body.get('filters') or []:
        if not isinstance(f, dict) or f.get('attribute') != 'STATUS' or f.get('operator') != 'EQ' or not isinstance(f.get('values'), list):
            raise errors.validation('filters supports only {attribute: STATUS, operator: EQ, values: [...]}')
        wanted = set(f['values']) if wanted is None else wanted & set(f['values'])
    jobs = [j for j in req.app.list(req.principal, 'jobs') if j['type'] == 'ingestion' and j['target'] == kb['id'] and j['input'].get('connector_id') == connector['id']]
    views = [req.app.ingestion_view(j) for j in jobs]
    views = [v for v in views if wanted is None or v['status'] in wanted]
    chosen, token = page_items(body, views)
    return Response(with_token({}, 'ingestionJobSummaries', [job_view(kb['id'], connector['id'], v, True) for v in chosen], token))


# ---- agents -----------------------------------------------------------------------------

AGENT_ALLOWED = {'agentName', 'clientToken', 'instruction', 'foundationModel', 'description', 'orchestrationType', 'idleSessionTTLInSeconds', 'agentResourceRoleArn',
                 'tags', 'guardrailConfiguration', 'memoryConfiguration', 'agentCollaboration'}
AGENT_REFUSED = {'customOrchestration': 'only the default orchestration exists', 'customerEncryptionKeyArn': 'Nuvora does not encrypt per resource',
                 'promptOverrideConfiguration': 'prompt templates and the orchestration Lambda are not configurable'}
AGENT_FIELDS = ('model', 'knowledge_ids', 'tools', 'max_steps', 'system_prompt', 'summarize_memory')


def agent_settings(req, body, creating):
    """Validated Bedrock members -> (Nuvora agent fields, recorded meta)."""
    check_fields(body, AGENT_ALLOWED, AGENT_REFUSED)
    name = text(body, 'agentName', 1, 100, True, NAME)
    instruction = text(body, 'instruction', 40, 4000)
    description = text(body, 'description', 1, 200)
    if body.get('orchestrationType') not in (None, 'DEFAULT'):
        raise errors.validation(f'orchestrationType {body["orchestrationType"]} is not supported by Nuvora: only DEFAULT exists')
    if body.get('agentCollaboration') not in (None, 'DISABLED'):
        raise errors.validation(f'agentCollaboration {body["agentCollaboration"]} is not supported by Nuvora: multi-agent collaboration is not available (use workflows)')
    ttl = body.get('idleSessionTTLInSeconds')
    if ttl is not None and (not isinstance(ttl, int) or isinstance(ttl, bool) or not 60 <= ttl <= 5400):
        raise errors.validation('idleSessionTTLInSeconds must be an integer from 60 to 5400')
    role = text(body, 'agentResourceRoleArn', 0, 2048)
    raw_model = body.get('foundationModel')
    if raw_model is None and creating:
        raise errors.validation('foundationModel is required to create an agent')
    fields = {'name': name}
    if raw_model is not None:
        fields['model'] = model_ref(req, raw_model, 'foundationModel')
    if instruction is not None:
        fields['system_prompt'] = instruction
    memory = mapping(body, 'memoryConfiguration')
    check_fields(memory, {'enabledMemoryTypes'}, {'storageDays': 'memory retention is governed by the tenant policy', 'sessionSummaryConfiguration': 'summary prompts are fixed'}, 'memoryConfiguration.')
    types = memory.get('enabledMemoryTypes') or []
    if not isinstance(types, list) or set(types) - {'SESSION_SUMMARY'}:
        raise errors.validation('memoryConfiguration.enabledMemoryTypes supports only SESSION_SUMMARY')
    if 'memoryConfiguration' in body:
        fields['summarize_memory'] = bool(types)
    guard = None
    if body.get('guardrailConfiguration'):
        guard = mapping(body, 'guardrailConfiguration')
        check_fields(guard, {'guardrailIdentifier', 'guardrailVersion'}, (), 'guardrailConfiguration.')
        gid = ref(req, 'guardrail', guard.get('guardrailIdentifier'), 'guardrailConfiguration.guardrailIdentifier')
        version = str(guard.get('guardrailVersion') or DRAFT)
        try:
            req.app.guardrail(req.principal, {'id': gid, 'version': version})
        except KeyError:
            raise errors.validation(f'guardrailConfiguration: guardrail {gid} version {version} does not exist') from None
        guard = {'guardrailIdentifier': gid, 'guardrailVersion': version}
    present = {'description': description, 'agentResourceRoleArn': role, 'idleSessionTTLInSeconds': ttl, 'foundationModel': raw_model, 'guardrailConfiguration': guard}
    recorded = {k: v for k, v in present.items() if k in body}
    return fields, recorded


def agent_state(meta, agent):
    return 'NOT_PREPARED' if meta.get('dirty') or not meta.get('prepared_at') or meta.get('prepared_revision') != agent['revision'] else 'PREPARED'


def agent_body(req, source, meta, version, status, created, updated, agent_id):
    """The members GetAgent / GetAgentVersion share. `source` is the agent record at that version."""
    out = {'agentId': agent_id, 'agentName': source['name'], 'agentArn': arn(req, 'agent', agent_id), 'agentStatus': status,
           'foundationModel': meta.get('foundationModel') or source.get('model', ''), 'idleSessionTTLInSeconds': meta.get('idleSessionTTLInSeconds') or DEFAULT_IDLE_TTL,
           'agentResourceRoleArn': meta.get('agentResourceRoleArn') or '', 'createdAt': iso(created), 'updatedAt': iso(updated)}
    if source.get('system_prompt'):
        out['instruction'] = source['system_prompt']
    if meta.get('description'):
        out['description'] = meta['description']
    if meta.get('guardrailConfiguration'):
        out['guardrailConfiguration'] = meta['guardrailConfiguration']
    if source.get('summarize_memory'):
        out['memoryConfiguration'] = {'enabledMemoryTypes': ['SESSION_SUMMARY']}
    return out


def agent_view(req, agent):
    meta = meta_get(req.app, req.principal['tenant'], agent['id'])
    out = agent_body(req, agent, meta, DRAFT, agent_state(meta, agent), agent['created'], max(agent['updated'], meta.get('updated', 0)), agent['id'])
    out.update(agentVersion=DRAFT, orchestrationType='DEFAULT', agentCollaboration='DISABLED')
    if meta.get('prepared_at'):
        out['preparedAt'] = iso(meta['prepared_at'])
    return out


def agent_of(req, value=None):
    return lookup(req, 'agents', ref(req, 'agent', value or req.params['agentId'], 'agentId'), 'Agent')


def touch(req, agent_id):
    """Mark the DRAFT changed (NOT_PREPARED) and bump the stamp that decides whether a new version is needed."""
    meta = meta_get(req.app, req.principal['tenant'], agent_id)
    meta_put(req.app, req.principal['tenant'], agent_id, dirty=True, stamp=meta.get('stamp', 0) + 1)


def create_agent(req):
    writer(req)
    body = req.json()
    fields, recorded = agent_settings(req, body, True)
    tags = tag_map(body.get('tags'))
    app, tenant = req.app, req.principal['tenant']

    def make():
        unique(app.list(req.principal, 'agents'), fields['name'], 'An agent')
        agent = app.create(req.principal, 'agents', {**fields, 'knowledge_ids': [], 'tools': []})
        meta_put(app, tenant, agent['id'], kind='agent', tags=tags, dirty=True, stamp=1, **recorded)
        audit(req, 'agent.created', agent['id'])
        return {'agent': agent_view(req, agent)}, agent['id']
    return Response(idempotent(req, 'CreateAgent', '', body, make, lambda i: {'agent': agent_view(req, app.get(req.principal, 'agents', i))}), 202)


def get_agent(req):
    return Response({'agent': agent_view(req, agent_of(req))})


def latest_version(req, agent_id):
    rows = versions_of(req, agent_id)
    return rows[-1]['version'] if rows else DRAFT


def list_agents(req):
    body = req.json()
    check_fields(body, {'maxResults', 'nextToken'})
    chosen, token = page_items(body, req.app.list(req.principal, 'agents'))
    out = []
    for a in chosen:
        meta = meta_get(req.app, req.principal['tenant'], a['id'])
        row = {'agentId': a['id'], 'agentName': a['name'], 'agentStatus': agent_state(meta, a), 'updatedAt': iso(max(a['updated'], meta.get('updated', 0))),
               'latestAgentVersion': latest_version(req, a['id'])}
        if meta.get('description'):
            row['description'] = meta['description']
        if meta.get('guardrailConfiguration'):
            row['guardrailConfiguration'] = meta['guardrailConfiguration']
        out.append(row)
    return Response(with_token({}, 'agentSummaries', out, token))


def update_agent(req):
    writer(req)
    agent = agent_of(req)
    body = req.json()
    if body.get('foundationModel') is None:
        raise errors.validation('foundationModel is required')
    fields, recorded = agent_settings(req, {**body}, False)
    unique(req.app.list(req.principal, 'agents'), fields['name'], 'An agent', agent['id'])
    base = {k: agent[k] for k in AGENT_FIELDS if k in agent}
    updated = save(req, 'agents', {**base, **fields}, agent['id'], agent)
    meta = meta_get(req.app, req.principal['tenant'], agent['id'])
    meta_put(req.app, req.principal['tenant'], agent['id'], stamp=meta.get('stamp', 0) + 1, dirty=True, **recorded)
    audit(req, 'agent.updated', agent['id'])
    return Response({'agent': agent_view(req, updated)}, 202)


def prepare_agent(req):
    writer(req)
    agent = agent_of(req)
    if not agent.get('system_prompt') or len(agent['system_prompt']) < 40:
        raise errors.validation('An agent needs an instruction of at least 40 characters before it can be prepared')
    now = time.time()
    meta_put(req.app, req.principal['tenant'], agent['id'], dirty=False, prepared_at=now, prepared_revision=agent['revision'])
    audit(req, 'agent.prepared', agent['id'])
    return Response({'agentId': agent['id'], 'agentStatus': 'PREPARED', 'agentVersion': DRAFT, 'preparedAt': iso(now)}, 202)


def delete_agent(req):
    agent = agent_of(req)
    body = {k: v for k, v in req.query.items()}
    skip = str(body.get('skipResourceInUseCheck', 'false')).lower() == 'true'
    app, tenant = req.app, req.principal['tenant']
    aliases = [a for a in app.store.list(tenant, ALIASES) if a['agent_id'] == agent['id']]
    if aliases and not skip:
        raise errors.BedrockError('ConflictException', 'The agent has aliases (' + ', '.join(a['id'] for a in aliases) + '); delete them or pass skipResourceInUseCheck')
    rows = [(k, r) for k in (GROUPS, ASSOCIATIONS, VERSIONS) for r in app.store.list(tenant, k) if r['agent_id'] == agent['id']]
    action_ids = {a for kind, r in rows if kind == GROUPS for a in r['action_ids']}
    with app.store.transaction():
        app.delete(req.principal, 'agents', agent['id'])
        for kind, r in rows:
            app.store.delete(tenant, kind, r['id'])
        for a in aliases:
            app.store.delete(tenant, ALIASES, a['id'])
        try:
            app.store.delete(tenant, META, agent['id'])
        except KeyError:
            pass
        for action_id in action_ids:
            drop_action(req, action_id)
    audit(req, 'agent.deleted', agent['id'])
    return Response({'agentId': agent['id'], 'agentStatus': 'DELETING'}, 202)


# ---- agent versions ---------------------------------------------------------------------

def versions_of(req, agent_id):
    rows = [v for v in req.app.store.list(req.principal['tenant'], VERSIONS) if v['agent_id'] == agent_id]
    return sorted(rows, key=lambda v: v['number'])


def version_row(req, agent_id, version):
    try:
        return req.app.store.get(req.principal['tenant'], VERSIONS, f'{agent_id}:{version}')
    except KeyError:
        raise errors.not_found(f'Agent {agent_id} has no version {version}') from None


def agent_at(req, agent, version):
    """The Nuvora agent record at DRAFT or a numbered version (from the generic resource history)."""
    if version == DRAFT:
        return agent
    row = version_row(req, agent['id'], version)
    try:
        snapshot = req.app.store.get(req.principal['tenant'], 'versions', f"{agent['id']}:{row['agent_revision']}")['snapshot']
    except KeyError:
        raise errors.internal(f'The history for agent {agent["id"]} revision {row["agent_revision"]} is missing') from None
    return {**snapshot, 'id': agent['id']}


def version_name(value):
    if value == DRAFT or (isinstance(value, str) and value.isdigit() and 1 <= len(value) <= 5):
        return value
    raise errors.validation(f'agentVersion {value} must be DRAFT or a version number')


def draft_only(version):
    if version != DRAFT:
        raise errors.validation(f'Version {version} is immutable: only the DRAFT version of an agent can be modified')


def snapshot_version(req, agent, description=None):
    """Pin the current DRAFT as the next numbered version, or reuse the latest when nothing changed since."""
    app, tenant = req.app, req.principal['tenant']
    meta = meta_get(app, tenant, agent['id'])
    stamp = [agent['revision'], meta.get('stamp', 0)]
    with app.store.transaction():
        rows = versions_of(req, agent['id'])
        if rows and rows[-1]['stamp'] == stamp:
            return rows[-1]
        if len(rows) >= MAX_VERSIONS:
            raise errors.BedrockError('ServiceQuotaExceededException', f'An agent keeps at most {MAX_VERSIONS} versions')
        number = (rows[-1]['number'] if rows else 0) + 1
        recorded = {k: meta.get(k) for k in ('description', 'agentResourceRoleArn', 'idleSessionTTLInSeconds', 'foundationModel', 'guardrailConfiguration') if meta.get(k) is not None}
        row = app.store.put(tenant, VERSIONS, {'agent_id': agent['id'], 'version': str(number), 'number': number, 'agent_revision': agent['revision'], 'stamp': stamp,
                                                'description': description, 'meta': recorded}, f"{agent['id']}:{number}")
        for kind in (GROUPS, ASSOCIATIONS):
            for r in app.store.list(tenant, kind):
                if r['agent_id'] == agent['id'] and r['version'] == DRAFT:
                    app.store.put(tenant, kind, {**{k: v for k, v in r.items() if k not in ('id', 'revision', 'created', 'updated')}, 'version': str(number)},
                                  f"{agent['id']}:{number}:{r['group_id'] if kind == GROUPS else r['knowledge_base_id']}")
        audit(req, 'agent.version_created', agent['id'], version=str(number))
    return row


def version_summary(req, agent, row):
    meta = {**meta_get(req.app, req.principal['tenant'], agent['id']), **row['meta']} if row else meta_get(req.app, req.principal['tenant'], agent['id'])
    source = agent_at(req, agent, row['version'] if row else DRAFT)
    out = {'agentName': source['name'], 'agentStatus': 'PREPARED' if row else agent_state(meta, agent), 'agentVersion': row['version'] if row else DRAFT,
           'createdAt': iso(row['created'] if row else agent['created']), 'updatedAt': iso(row['updated'] if row else agent['updated'])}
    if meta.get('description'):
        out['description'] = meta['description']
    if meta.get('guardrailConfiguration'):
        out['guardrailConfiguration'] = meta['guardrailConfiguration']
    return out


def list_agent_versions(req):
    agent = agent_of(req)
    body = req.json()
    check_fields(body, {'maxResults', 'nextToken'})
    items = [{'id': r['version'], 'created': r['created'], 'row': r} for r in versions_of(req, agent['id'])]
    items.append({'id': DRAFT, 'created': agent['created'], 'row': None})
    chosen, token = page_items(body, items)
    return Response(with_token({}, 'agentVersionSummaries', [version_summary(req, agent, i['row']) for i in chosen], token))


def get_agent_version(req):
    agent = agent_of(req)
    version = version_name(req.params['agentVersion'])
    if version == DRAFT:
        out = agent_view(req, agent)
        out['version'] = out.pop('agentVersion')
        for k in ('orchestrationType', 'agentCollaboration', 'preparedAt'):
            out.pop(k, None)
        return Response({'agentVersion': out})
    row = version_row(req, agent['id'], version)
    source = agent_at(req, agent, version)
    meta = {**meta_get(req.app, req.principal['tenant'], agent['id']), **row['meta']}
    out = agent_body(req, source, meta, version, 'PREPARED', row['created'], row['updated'], agent['id'])
    out['version'] = version
    return Response({'agentVersion': out})


# ---- agent aliases ----------------------------------------------------------------------

def routing(req, agent, value):
    """Normalised routingConfiguration: one numbered version of this agent."""
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise errors.validation('routingConfiguration must hold exactly one entry: Nuvora routes an alias to one agent version')
    check_fields(value[0], {'agentVersion'}, {'provisionedThroughput': 'provisioned throughput does not exist in Nuvora'}, 'routingConfiguration[0].')
    version = version_name(value[0].get('agentVersion'))
    if version == DRAFT:
        raise errors.validation('routingConfiguration[0].agentVersion must be a numbered version; DRAFT is reachable through the test alias ' + TEST_ALIAS)
    version_row(req, agent['id'], version)
    return [{'agentVersion': version}]


def alias_view(req, alias, summary=False):
    out = {'agentAliasId': alias['id'], 'agentAliasName': alias['name'], 'routingConfiguration': alias['routing'], 'agentAliasStatus': 'PREPARED',
           'createdAt': iso(alias['created']), 'updatedAt': iso(alias['updated'])}
    if alias.get('description'):
        out['description'] = alias['description']
    if not summary:
        out.update(agentId=alias['agent_id'], agentAliasArn=arn(req, 'agent-alias', f"{alias['agent_id']}/{alias['id']}"), aliasInvocationState=alias['invocation_state'],
                   agentAliasHistoryEvents=[{k: (iso(v) if k.endswith('Date') else v) for k, v in e.items()} for e in alias['history']])
    return out


def alias_of(req, agent, value=None):
    ident = ref(req, 'agent-alias', value or req.params['agentAliasId'], 'agentAliasId')
    try:
        alias = req.app.store.get(req.principal['tenant'], ALIASES, ident)
    except KeyError:
        alias = None
    if alias is None or alias['agent_id'] != agent['id']:
        raise errors.not_found(f'Agent alias {ident} does not exist for agent {agent["id"]}')
    return alias


def new_alias_id(req):
    while True:
        ident = new_id()
        try:
            req.app.store.get(req.principal['tenant'], ALIASES, ident)
        except KeyError:
            return ident


def create_agent_alias(req):
    writer(req)
    agent = agent_of(req)
    body = req.json()
    check_fields(body, {'agentAliasName', 'clientToken', 'description', 'routingConfiguration', 'tags'})
    name = text(body, 'agentAliasName', 1, 100, True, NAME)
    description = text(body, 'description', 1, 200)
    tags = tag_map(body.get('tags'))
    app, tenant = req.app, req.principal['tenant']

    def make():
        unique([dict(a, name=a['name']) for a in app.store.list(tenant, ALIASES) if a['agent_id'] == agent['id']], name, 'An alias')
        if body.get('routingConfiguration') is None:
            route = [{'agentVersion': snapshot_version(req, agent)['version']}]
        else:
            route = routing(req, agent, body['routingConfiguration'])
        ident = new_alias_id(req)
        alias = app.store.put(tenant, ALIASES, {'agent_id': agent['id'], 'name': name, 'description': description, 'routing': route, 'invocation_state': 'ACCEPT_INVOCATIONS',
                                                'tags': tags, 'history': [{'routingConfiguration': route, 'startDate': time.time()}]}, ident)
        audit(req, 'agent_alias.created', ident, agent=agent['id'])
        return {'agentAlias': alias_view(req, alias)}, ident
    return Response(idempotent(req, 'CreateAgentAlias', agent['id'], body, make, lambda i: {'agentAlias': alias_view(req, alias_of(req, agent, i))}), 202)


def get_agent_alias(req):
    agent = agent_of(req)
    return Response({'agentAlias': alias_view(req, alias_of(req, agent))})


def list_agent_aliases(req):
    agent = agent_of(req)
    body = req.json()
    check_fields(body, {'maxResults', 'nextToken'})
    chosen, token = page_items(body, [a for a in req.app.store.list(req.principal['tenant'], ALIASES) if a['agent_id'] == agent['id']])
    return Response(with_token({}, 'agentAliasSummaries', [alias_view(req, a, True) for a in chosen], token))


def update_agent_alias(req):
    writer(req)
    agent = agent_of(req)
    alias = alias_of(req, agent)
    body = req.json()
    check_fields(body, {'agentAliasName', 'description', 'routingConfiguration', 'aliasInvocationState'})
    name = text(body, 'agentAliasName', 1, 100, True, NAME)
    description = text(body, 'description', 1, 200)
    state = body.get('aliasInvocationState', alias['invocation_state'])
    if state not in ('ACCEPT_INVOCATIONS', 'REJECT_INVOCATIONS'):
        raise errors.validation('aliasInvocationState must be ACCEPT_INVOCATIONS or REJECT_INVOCATIONS')
    unique([a for a in req.app.store.list(req.principal['tenant'], ALIASES) if a['agent_id'] == agent['id']], name, 'An alias', alias['id'])
    route, history = alias['routing'], alias['history']
    if body.get('routingConfiguration') is not None:
        route = routing(req, agent, body['routingConfiguration'])
        if route != alias['routing']:
            now = time.time()
            history = [{**e, 'endDate': now} if e is history[-1] else e for e in history] + [{'routingConfiguration': route, 'startDate': now}]
    data = {k: v for k, v in alias.items() if k not in ('id', 'revision', 'created', 'updated')}
    data.update(name=name, description=description, routing=route, history=history, invocation_state=state)
    alias = req.app.store.put(req.principal['tenant'], ALIASES, data, alias['id'])
    audit(req, 'agent_alias.updated', alias['id'])
    return Response({'agentAlias': alias_view(req, alias)}, 202)


def delete_agent_alias(req):
    writer(req)
    agent = agent_of(req)
    alias = alias_of(req, agent)
    req.app.store.delete(req.principal['tenant'], ALIASES, alias['id'])
    audit(req, 'agent_alias.deleted', alias['id'])
    return Response({'agentId': agent['id'], 'agentAliasId': alias['id'], 'agentAliasStatus': 'DELETING'}, 202)


def resolve_alias(req, agent_id, alias_id):
    """What InvokeAgent (B3) runs for `agentId` + `agentAliasId` (each an id or an ARN).

    Returns a dict:
      agentId, agentAliasId, agentAliasName, agentVersion ('DRAFT' for the reserved test alias TSTALIASID, else the pinned number),
      agent               the Nuvora `agents` record at that version (model, system_prompt, tools, knowledge_ids, max_steps,
                          summarize_memory), as run by Platform.new_job('agent', ...)
      instruction, foundationModel, idleSessionTTLInSeconds
      guardrail           {'id', 'version'} for Platform.guardrail / the job's `guardrail` input, or None
      actionGroups        [{actionGroupId, actionGroupName, actionGroupState, actionIds}] of that version
      knowledgeBases      [{knowledgeBaseId, knowledgeBaseState, description}] of that version
    Raises ResourceNotFoundException for an unknown agent or alias, ConflictException when the alias routes to a version that no longer exists, and ValidationException when the alias has
    aliasInvocationState REJECT_INVOCATIONS."""
    agent = agent_of(req, agent_id)
    if ref(req, 'agent-alias', alias_id, 'agentAliasId') == TEST_ALIAS:
        alias, version, name = None, DRAFT, 'TestAlias'
    else:
        alias = alias_of(req, agent, alias_id)
        if alias['invocation_state'] != 'ACCEPT_INVOCATIONS':
            raise errors.validation(f'Agent alias {alias["id"]} does not accept invocations')
        version, name = alias['routing'][0]['agentVersion'], alias['name']
    try:
        source = agent_at(req, agent, version)
        meta = meta_get(req.app, req.principal['tenant'], agent['id'])
        if version != DRAFT:
            meta = {**meta, **version_row(req, agent['id'], version)['meta']}
    except errors.BedrockError as exc:
        if alias is None or exc.status not in (404, 500):
            raise
        raise errors.BedrockError('ConflictException', f'Agent alias {alias["id"]} routes to version {version}, which no longer exists; point the alias at a prepared version with UpdateAgentAlias', 409) from None
    guard = meta.get('guardrailConfiguration')
    return {'agentId': agent['id'], 'agentAliasId': alias['id'] if alias else TEST_ALIAS, 'agentAliasName': name, 'agentVersion': version, 'agent': source,
            'instruction': source.get('system_prompt', ''), 'foundationModel': meta.get('foundationModel') or source.get('model', ''),
            'idleSessionTTLInSeconds': meta.get('idleSessionTTLInSeconds') or DEFAULT_IDLE_TTL,
            'guardrail': {'id': guard['guardrailIdentifier'], 'version': guard['guardrailVersion']} if guard else None,
            'actionGroups': [{'actionGroupId': g['group_id'], 'actionGroupName': g['name'], 'actionGroupState': g['state'], 'actionIds': list(g['action_ids'])} for g in group_rows(req, agent['id'], version)],
            'knowledgeBases': [{'knowledgeBaseId': r['knowledge_base_id'], 'knowledgeBaseState': r['state'], 'description': r['description']} for r in association_rows(req, agent['id'], version)]}


# ---- action groups ----------------------------------------------------------------------

GROUP_REFUSED = {'parentActionGroupSignature': 'built-in tool signatures (user input, code interpreter, computer use) are not available as action groups',
                 'parentActionGroupSignatureParams': 'built-in tool signatures are not available',
                 'functionSchema': 'function schemas have no HTTP endpoint to call; provide apiSchema.payload (OpenAPI 3 JSON)'}


def group_rows(req, agent_id, version):
    return sorted((r for r in req.app.store.list(req.principal['tenant'], GROUPS) if r['agent_id'] == agent_id and r['version'] == version), key=lambda r: r['created'])


def group_of(req, agent, version):
    ident = req.params['actionGroupId']
    try:
        return req.app.store.get(req.principal['tenant'], GROUPS, f"{agent['id']}:{version}:{ident}")
    except KeyError:
        raise errors.not_found(f'Action group {ident} does not exist in agent {agent["id"]} version {version}') from None


def group_view(req, row, detail=True):
    out = {'actionGroupId': row['group_id'], 'actionGroupName': row['name'], 'actionGroupState': row['state'], 'updatedAt': iso(row['updated'])}
    if row.get('description'):
        out['description'] = row['description']
    if detail:
        out.update(agentId=row['agent_id'], agentVersion=row['version'], createdAt=iso(row['created']), apiSchema={'payload': row['payload']})
    return out


def api_schema(body, required):
    schema = mapping(body, 'apiSchema', required)
    if not schema:
        return None
    check_fields(schema, {'payload'}, {'s3': 'Nuvora has no S3 fetch for schemas; send the document inline as apiSchema.payload'}, 'apiSchema.')
    payload = schema.get('payload')
    if not isinstance(payload, str) or not payload.strip():
        raise errors.validation('apiSchema.payload is required: an inline OpenAPI 3 document')
    if len(payload) > 150000:
        raise errors.validation('apiSchema.payload is larger than 150000 characters')
    try:
        spec = json.loads(payload)
    except ValueError:
        raise errors.validation('apiSchema.payload must be OpenAPI 3 as JSON; YAML is not parsed by Nuvora') from None
    if not isinstance(spec, dict):
        raise errors.validation('apiSchema.payload must be an OpenAPI 3 JSON object')
    return payload, spec


def import_actions(req, spec):
    """Actions for every operation of an OpenAPI document, atomically: any operation Nuvora cannot call refuses the whole schema."""
    servers = spec.get('servers') if isinstance(spec.get('servers'), list) else []
    base = servers[0].get('url') if servers and isinstance(servers[0], dict) else None
    if not isinstance(base, str) or not base.startswith(('http://', 'https://')):
        raise errors.validation('apiSchema.payload needs servers[0].url: Nuvora calls the HTTP endpoint directly (there is no Lambda executor)')
    result = req.app.import_openapi(req.principal, {'spec': spec})
    if result['skipped'] or not result['created']:
        for item in result['created']:
            drop_action(req, item['id'])
        why = '; '.join(f"{s['operation']}: {s['reason']}" for s in result['skipped']) or 'the document defines no GET or POST operations'
        raise errors.validation('apiSchema.payload cannot be imported as Nuvora actions: ' + why)
    return [item['id'] for item in result['created']]


def drop_action(req, action_id):
    """Delete an action no action group row of this tenant still references."""
    tenant = req.principal['tenant']
    if any(action_id in r['action_ids'] for r in req.app.store.list(tenant, GROUPS)):
        return
    try:
        req.app.delete(req.principal, 'actions', action_id)
    except (KeyError, Fault):
        pass


def sync_agent(req, agent_id):
    """Recompute the DRAFT agent's tools and knowledge_ids from its action groups and associations, leaving everything else alone."""
    app, tenant = req.app, req.principal['tenant']
    agent = app.get(req.principal, 'agents', agent_id)
    groups = group_rows(req, agent_id, DRAFT)
    kbs = association_rows(req, agent_id, DRAFT)
    owned_tools = {f'action_{a}' for r in app.store.list(tenant, GROUPS) if r['agent_id'] == agent_id for a in r['action_ids']}
    enabled = [f'action_{a}' for g in groups if g['state'] == 'ENABLED' for a in g['action_ids']]
    owned_kbs = {r['knowledge_base_id'] for r in app.store.list(tenant, ASSOCIATIONS) if r['agent_id'] == agent_id}
    active = [r['knowledge_base_id'] for r in kbs if r['state'] == 'ENABLED']
    meta = meta_get(app, tenant, agent_id)
    tools = [t for t in agent.get('tools', []) if t not in owned_tools]
    added_search = bool(meta.get('search_added'))
    if active and 'knowledge_search' not in tools:
        tools.append('knowledge_search')
        added_search = True
    elif not active and added_search:
        tools = [t for t in tools if t != 'knowledge_search']
        added_search = False
    tools += [t for t in enabled if t not in tools]
    knowledge = list(dict.fromkeys([k for k in agent.get('knowledge_ids', []) if k not in owned_kbs] + active))
    if tools != agent.get('tools', []) or knowledge != agent.get('knowledge_ids', []):
        save(req, 'agents', {**{k: agent[k] for k in AGENT_FIELDS if k in agent}, 'name': agent['name'], 'tools': tools, 'knowledge_ids': knowledge}, agent_id, agent)
    meta_put(app, tenant, agent_id, search_added=added_search)
    touch(req, agent_id)


def group_executor(body):
    executor = mapping(body, 'actionGroupExecutor')
    check_fields(executor, set(), {'lambda': 'there is no Lambda executor; Nuvora calls the HTTP endpoint named in apiSchema.payload servers[0].url',
                                   'customControl': 'RETURN_CONTROL is not available'}, 'actionGroupExecutor.')


def create_action_group(req):
    writer(req)
    agent = agent_of(req)
    draft_only(version_name(req.params['agentVersion']))
    body = req.json()
    check_fields(body, {'actionGroupName', 'clientToken', 'description', 'actionGroupExecutor', 'apiSchema', 'actionGroupState'}, GROUP_REFUSED)
    name = text(body, 'actionGroupName', 1, 100, True, NAME)
    description = text(body, 'description', 1, 200)
    state = body.get('actionGroupState', 'ENABLED')
    if state not in ('ENABLED', 'DISABLED'):
        raise errors.validation('actionGroupState must be ENABLED or DISABLED')
    group_executor(body)
    schema = api_schema(body, True)
    app, tenant = req.app, req.principal['tenant']

    def make():
        unique([{'id': r['group_id'], 'name': r['name']} for r in group_rows(req, agent['id'], DRAFT)], name, 'An action group')
        payload, spec = schema
        action_ids = import_actions(req, spec)
        ident = new_id()
        row = app.store.put(tenant, GROUPS, {'agent_id': agent['id'], 'version': DRAFT, 'group_id': ident, 'name': name, 'description': description, 'state': state,
                                             'action_ids': action_ids, 'payload': payload}, f"{agent['id']}:{DRAFT}:{ident}")
        sync_agent(req, agent['id'])
        audit(req, 'action_group.created', ident, agent=agent['id'], actions=action_ids)
        return {'agentActionGroup': group_view(req, row)}, ident

    def fetch(ident):
        return {'agentActionGroup': group_view(req, app.store.get(tenant, GROUPS, f"{agent['id']}:{DRAFT}:{ident}"))}
    return Response(idempotent(req, 'CreateAgentActionGroup', agent['id'], body, make, fetch))


def get_action_group(req):
    agent = agent_of(req)
    return Response({'agentActionGroup': group_view(req, group_of(req, agent, version_name(req.params['agentVersion'])))})


def list_action_groups(req):
    agent = agent_of(req)
    version = version_name(req.params['agentVersion'])
    if version != DRAFT:
        version_row(req, agent['id'], version)
    body = req.json()
    check_fields(body, {'maxResults', 'nextToken'})
    chosen, token = page_items(body, [dict(r, id=r['group_id']) for r in group_rows(req, agent['id'], version)])
    return Response(with_token({}, 'actionGroupSummaries', [group_view(req, r, False) for r in chosen], token))


def update_action_group(req):
    writer(req)
    agent = agent_of(req)
    version = version_name(req.params['agentVersion'])
    draft_only(version)
    row = group_of(req, agent, version)
    body = req.json()
    check_fields(body, {'actionGroupName', 'description', 'actionGroupExecutor', 'apiSchema', 'actionGroupState'}, GROUP_REFUSED)
    name = text(body, 'actionGroupName', 1, 100, True, NAME)
    unique([{'id': r['group_id'], 'name': r['name']} for r in group_rows(req, agent['id'], DRAFT)], name, 'An action group', row['group_id'])
    state = body.get('actionGroupState', row['state'])
    if state not in ('ENABLED', 'DISABLED'):
        raise errors.validation('actionGroupState must be ENABLED or DISABLED')
    group_executor(body)
    schema = api_schema(body, False)
    data = {k: v for k, v in row.items() if k not in ('id', 'revision', 'created', 'updated')}
    data.update(name=name, state=state, description=text(body, 'description', 1, 200) if 'description' in body else row.get('description'))
    old_actions = []
    if schema:
        old_actions = row['action_ids']
        data.update(payload=schema[0], action_ids=import_actions(req, schema[1]))
    saved = req.app.store.put(req.principal['tenant'], GROUPS, data, f"{agent['id']}:{DRAFT}:{row['group_id']}")
    for action_id in old_actions:
        drop_action(req, action_id)
    sync_agent(req, agent['id'])
    audit(req, 'action_group.updated', row['group_id'], agent=agent['id'])
    return Response({'agentActionGroup': group_view(req, saved)})


def delete_action_group(req):
    writer(req)
    agent = agent_of(req)
    version = version_name(req.params['agentVersion'])
    draft_only(version)
    row = group_of(req, agent, version)
    req.app.store.delete(req.principal['tenant'], GROUPS, row['id'])
    for action_id in row['action_ids']:
        drop_action(req, action_id)
    sync_agent(req, agent['id'])
    audit(req, 'action_group.deleted', row['group_id'], agent=agent['id'])
    return Response(None, 204)


# ---- agent knowledge base associations --------------------------------------------------

def association_rows(req, agent_id, version):
    return sorted((r for r in req.app.store.list(req.principal['tenant'], ASSOCIATIONS) if r['agent_id'] == agent_id and r['version'] == version), key=lambda r: r['created'])


def association_view(row, summary=False):
    out = {'knowledgeBaseId': row['knowledge_base_id'], 'description': row['description'], 'knowledgeBaseState': row['state'], 'updatedAt': iso(row['updated'])}
    if not summary:
        out.update(agentId=row['agent_id'], agentVersion=row['version'], createdAt=iso(row['created']))
    return out


def association_of(req, agent, version):
    kb_id = ref(req, 'knowledge-base', req.params['knowledgeBaseId'], 'knowledgeBaseId')
    try:
        return req.app.store.get(req.principal['tenant'], ASSOCIATIONS, f"{agent['id']}:{version}:{kb_id}")
    except KeyError:
        raise errors.not_found(f'Knowledge base {kb_id} is not associated with agent {agent["id"]} version {version}') from None


def associate_knowledge_base(req):
    writer(req)
    agent = agent_of(req)
    draft_only(version_name(req.params['agentVersion']))
    body = req.json()
    check_fields(body, {'knowledgeBaseId', 'description', 'knowledgeBaseState'})
    kb = lookup(req, 'knowledge', ref(req, 'knowledge-base', body.get('knowledgeBaseId'), 'knowledgeBaseId'), 'Knowledge base')
    description = text(body, 'description', 1, 200, True)
    state = body.get('knowledgeBaseState', 'ENABLED')
    if state not in ('ENABLED', 'DISABLED'):
        raise errors.validation('knowledgeBaseState must be ENABLED or DISABLED')
    ident = f"{agent['id']}:{DRAFT}:{kb['id']}"
    try:
        req.app.store.get(req.principal['tenant'], ASSOCIATIONS, ident)
    except KeyError:
        pass
    else:
        raise errors.BedrockError('ConflictException', f'Knowledge base {kb["id"]} is already associated with this agent')
    row = req.app.store.put(req.principal['tenant'], ASSOCIATIONS, {'agent_id': agent['id'], 'version': DRAFT, 'knowledge_base_id': kb['id'], 'description': description, 'state': state}, ident)
    sync_agent(req, agent['id'])
    audit(req, 'agent_knowledge_base.associated', kb['id'], agent=agent['id'])
    return Response({'agentKnowledgeBase': association_view(row)})


def get_agent_knowledge_base(req):
    agent = agent_of(req)
    return Response({'agentKnowledgeBase': association_view(association_of(req, agent, version_name(req.params['agentVersion'])))})


def list_agent_knowledge_bases(req):
    agent = agent_of(req)
    version = version_name(req.params['agentVersion'])
    if version != DRAFT:
        version_row(req, agent['id'], version)
    body = req.json()
    check_fields(body, {'maxResults', 'nextToken'})
    chosen, token = page_items(body, [dict(r, id=r['knowledge_base_id']) for r in association_rows(req, agent['id'], version)])
    return Response(with_token({}, 'agentKnowledgeBaseSummaries', [association_view(r, True) for r in chosen], token))


def update_agent_knowledge_base(req):
    writer(req)
    agent = agent_of(req)
    version = version_name(req.params['agentVersion'])
    draft_only(version)
    row = association_of(req, agent, version)
    body = req.json()
    check_fields(body, {'description', 'knowledgeBaseState'})
    state = body.get('knowledgeBaseState', row['state'])
    if state not in ('ENABLED', 'DISABLED'):
        raise errors.validation('knowledgeBaseState must be ENABLED or DISABLED')
    data = {k: v for k, v in row.items() if k not in ('id', 'revision', 'created', 'updated')}
    data.update(state=state, description=text(body, 'description', 1, 200) or row['description'])
    saved = req.app.store.put(req.principal['tenant'], ASSOCIATIONS, data, row['id'])
    sync_agent(req, agent['id'])
    audit(req, 'agent_knowledge_base.updated', row['knowledge_base_id'], agent=agent['id'])
    return Response({'agentKnowledgeBase': association_view(saved)})


def disassociate_knowledge_base(req):
    writer(req)
    agent = agent_of(req)
    version = version_name(req.params['agentVersion'])
    draft_only(version)
    row = association_of(req, agent, version)
    req.app.store.delete(req.principal['tenant'], ASSOCIATIONS, row['id'])
    sync_agent(req, agent['id'])
    audit(req, 'agent_knowledge_base.disassociated', row['knowledge_base_id'], agent=agent['id'])
    return Response(None, 204)


# ---- tags -------------------------------------------------------------------------------

def tagged(req):
    """(kind, record getter/setter) for the ARN in the path: a knowledge base, an agent or an agent alias."""
    value = req.params['resourceArn']
    kind, rest = parse_arn(req, value, ('knowledge-base', 'agent', 'agent-alias'))
    tenant = req.principal['tenant']
    if kind == 'agent-alias':
        agent_id, _, alias_id = rest.partition('/')
        try:
            alias = req.app.store.get(tenant, ALIASES, alias_id)
        except KeyError:
            alias = None
        if alias is None or alias['agent_id'] != agent_id:
            raise errors.not_found(f'No such resource: {value}')
        return (lambda: dict(alias.get('tags') or {})), (lambda tags: req.app.store.put(tenant, ALIASES, {**{k: v for k, v in alias.items() if k not in ('id', 'revision', 'created', 'updated')}, 'tags': tags}, alias_id))
    lookup(req, 'knowledge' if kind == 'knowledge-base' else 'agents', rest, 'Resource')
    return (lambda: dict(meta_get(req.app, tenant, rest).get('tags') or {})), (lambda tags: meta_put(req.app, tenant, rest, tags=tags))


def list_tags_for_resource(req):
    getter, _ = tagged(req)
    return Response({'tags': getter()})


def tag_resource(req):
    writer(req)
    getter, setter = tagged(req)
    body = req.json()
    check_fields(body, {'tags'})
    new = tag_map(body.get('tags'))
    if not new:
        raise errors.validation('tags is required')
    merged = {**getter(), **new}
    if len(merged) > MAX_TAGS:
        raise errors.BedrockError('ServiceQuotaExceededException', f'A resource has at most {MAX_TAGS} tags')
    setter(merged)
    return Response({})


def untag_resource(req):
    writer(req)
    getter, setter = tagged(req)
    keys = [v for k, v in parse_qsl(urlsplit(req.handler.path).query, keep_blank_values=True) if k == 'tagKeys']
    if not keys:
        raise errors.validation('tagKeys is required')
    setter({k: v for k, v in getter().items() if k not in keys})
    return Response({})


HANDLERS = {
    'CreateKnowledgeBase': create_knowledge_base, 'GetKnowledgeBase': get_knowledge_base, 'ListKnowledgeBases': list_knowledge_bases,
    'UpdateKnowledgeBase': update_knowledge_base, 'DeleteKnowledgeBase': delete_knowledge_base,
    'CreateDataSource': create_data_source, 'GetDataSource': get_data_source, 'ListDataSources': list_data_sources,
    'UpdateDataSource': update_data_source, 'DeleteDataSource': delete_data_source,
    'StartIngestionJob': start_ingestion_job, 'GetIngestionJob': get_ingestion_job, 'ListIngestionJobs': list_ingestion_jobs,
    'CreateAgent': create_agent, 'GetAgent': get_agent, 'ListAgents': list_agents, 'UpdateAgent': update_agent, 'DeleteAgent': delete_agent,
    'PrepareAgent': prepare_agent, 'ListAgentVersions': list_agent_versions, 'GetAgentVersion': get_agent_version,
    'CreateAgentAlias': create_agent_alias, 'GetAgentAlias': get_agent_alias, 'ListAgentAliases': list_agent_aliases,
    'UpdateAgentAlias': update_agent_alias, 'DeleteAgentAlias': delete_agent_alias,
    'CreateAgentActionGroup': create_action_group, 'GetAgentActionGroup': get_action_group, 'ListAgentActionGroups': list_action_groups,
    'UpdateAgentActionGroup': update_action_group, 'DeleteAgentActionGroup': delete_action_group,
    'AssociateAgentKnowledgeBase': associate_knowledge_base, 'GetAgentKnowledgeBase': get_agent_knowledge_base,
    'ListAgentKnowledgeBases': list_agent_knowledge_bases, 'UpdateAgentKnowledgeBase': update_agent_knowledge_base,
    'DisassociateAgentKnowledgeBase': disassociate_knowledge_base,
    'ListTagsForResource': list_tags_for_resource, 'TagResource': tag_resource, 'UntagResource': untag_resource,
}


def install(router):
    """Add the routes the shared table lacks, then attach this module's handlers (no handler for DeleteAgentVersion: it answers 501)."""
    known = {(r.service, r.operation) for r in router.routes}
    for method, template, operation in ROUTES:
        if (AGENT, operation) not in known:
            router.register(AGENT, method, template, operation)
    for route in router.routes:
        if route.operation in HANDLERS and route.service == AGENT:
            route.handler = HANDLERS[route.operation]
