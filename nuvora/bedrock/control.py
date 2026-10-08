# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""bedrock (control plane) operations: guardrails, inference profiles, invocation logging, model
customization jobs, evaluation jobs and tags.

Everything maps onto Nuvora resources (guardrails and their versions, routers, recipes/datasets/training
jobs, evaluations/jobs) and goes through `Platform`, so validation, roles and audit stay in one place.
A Bedrock member Nuvora cannot honour is a ValidationException naming it; nothing is silently dropped.

Resource ARNs are a Nuvora scheme, not AWS's:  arn:nuvora:bedrock:<region>:<tenant>:<kind>/<id>
(kinds: guardrail, inference-profile, model-customization-job, evaluation-job, custom-model). The region is
whatever the caller signed with, is not checked on the way in, and the tenant must be the caller's.
Wherever Bedrock takes an ARN or an identifier, both are accepted. Data locations that Bedrock expresses as
S3 URIs are Nuvora references instead: `nuvora://datasets/<id>`, `nuvora://evaluations/<id>` and
`nuvora://jobs` (output); real `s3://` locations are refused because Nuvora neither reads nor writes S3 here.
"""
import base64
import json
import os
import re
from datetime import datetime, timezone

from ..guardrails import GROUNDING_SCORE
from ..security import Fault, require
from . import errors
from .foundation import summary as model_summary
from .router import CONTROL, Response
from .runtime import _arn_tail

ARN_HEAD = 'arn:nuvora:bedrock:'
TAG_LIMIT = 50
PAGE_DEFAULT, PAGE_MAX = 100, 1000


# ---- small helpers ----------------------------------------------------------------------

def refuse(what, why):
    return errors.validation(f'{what} is not supported by Nuvora: {why}')


def check_members(obj, allowed, where, refused=None):
    """`obj` must be an object whose members are in `allowed`; members in `refused` say why they are not honoured."""
    if not isinstance(obj, dict):
        raise errors.validation(f'{where} must be an object')
    for key in obj:
        if refused and key in refused:
            raise refuse(f'{where}.{key}' if where else key, refused[key])
    extra = sorted(set(obj) - set(allowed))
    if extra:
        raise refuse(', '.join(f'{where}.{k}' if where else k for k in extra), 'unknown member')
    return obj


def need_list(value, where, maximum=1000):
    if not isinstance(value, list) or len(value) > maximum:
        raise errors.validation(f'{where} must be a list of at most {maximum} entries')
    return value


def need_str(value, where, low=1, high=1000, pattern=None):
    if not isinstance(value, str) or not low <= len(value) <= high:
        raise errors.validation(f'{where} must be a string of {low}-{high} characters')
    if pattern and not re.fullmatch(pattern, value):
        raise errors.validation(f'{where} does not match the pattern {pattern}')
    return value


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def parse_time(value, where):
    try:
        if re.fullmatch(r'[0-9]+(\.[0-9]+)?', value):
            return float(value)
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except ValueError:
        raise errors.validation(f'{where} is not a timestamp') from None


def admin(req):
    require(req.principal, 'admin')


def call(function, *args):
    """Run a Platform call, turning KeyError into ResourceNotFoundException and a revision race into ConflictException."""
    try:
        return function(*args)
    except KeyError:
        raise errors.not_found('Resource not found') from None
    except ValueError as exc:
        raise errors.BedrockError('ConflictException', str(exc)) from None


def arn_for(req, kind, ident):
    return f"{ARN_HEAD}{req.region or 'local'}:{req.principal['tenant']}:{kind}/{ident}"


def split_arn(req, value, label):
    """(kind, id) of one of this tenant's Nuvora Bedrock ARNs."""
    if not value.startswith(ARN_HEAD):
        raise errors.validation(f'{label} is not a Nuvora Bedrock ARN (arn:nuvora:bedrock:<region>:<tenant>:<kind>/<id>)')
    _region, _, rest = value[len(ARN_HEAD):].partition(':')
    tenant = req.principal['tenant']
    if not rest.startswith(tenant + ':'):
        raise errors.not_found(f'{label} names no resource of this tenant')
    kind, _, ident = rest[len(tenant) + 1:].partition('/')
    if not kind or not ident:
        raise errors.validation(f'{label} is not a valid ARN')
    return kind, ident


def ident_for(req, value, kind, label):
    """The id inside `value`, which is either a bare id or an ARN of the expected kind."""
    need_str(value, label, 1, 2048)
    if not value.startswith('arn:'):
        return value
    got, ident = split_arn(req, value, label)
    if got != kind:
        raise errors.validation(f'{label} must be a {kind} ARN, not {got}')
    return ident


def max_results(query):
    raw = query.get('maxResults')
    if raw is None:
        return PAGE_DEFAULT
    if not re.fullmatch(r'[0-9]{1,6}', raw) or not 1 <= int(raw) <= PAGE_MAX:
        raise errors.validation(f'maxResults must be an integer between 1 and {PAGE_MAX}')
    return int(raw)


def paginate(items, query, descending=False):
    """items: [(created, id, payload)]. Returns (payloads, nextToken|None). The token is the sort key of the last item
    returned, so pages stay stable while resources are added or removed."""
    size = max_results(query)
    ordered = sorted(items, key=lambda i: (i[0], i[1]), reverse=descending)
    token = query.get('nextToken')
    if token:
        try:
            created, ident = json.loads(base64.urlsafe_b64decode(token.encode() + b'=' * (-len(token) % 4)))
            cursor = (float(created), str(ident))
        except (ValueError, TypeError):
            raise errors.validation('nextToken is not valid') from None
        ordered = [i for i in ordered if ((i[0], i[1]) < cursor if descending else (i[0], i[1]) > cursor)]
    chunk = ordered[:size]
    more = None
    if len(ordered) > size and chunk:
        more = base64.urlsafe_b64encode(json.dumps([chunk[-1][0], chunk[-1][1]]).encode()).decode().rstrip('=')
    return [c[2] for c in chunk], more


def listing(key, payloads, more):
    return Response({key: payloads, **({'nextToken': more} if more else {})})


def check_query(req, allowed):
    extra = sorted(set(req.query) - set(allowed))
    if extra:
        raise errors.validation('Unsupported query parameter: ' + ', '.join(extra))


# ---- tags (bedrock layer metadata; guardrails only) ---------------------------------------

def validate_tags(tags, where='tags'):
    need_list(tags, where, TAG_LIMIT)
    out = {}
    for n, tag in enumerate(tags):
        check_members(tag, ('key', 'value'), f'{where}[{n}]')
        key = need_str(tag.get('key'), f'{where}[{n}].key', 1, 128)
        value = need_str(tag.get('value', ''), f'{where}[{n}].value', 0, 256)
        if key.lower().startswith('aws:'):
            raise errors.validation('Tag keys starting with aws: are reserved')
        out[key] = value
    return out


def tags_of(req, kind, ident):
    try:
        return req.app.store.get(req.principal['tenant'], 'bedrock_tags', f'{kind}:{ident}')['tags']
    except KeyError:
        return {}


def save_tags(req, kind, ident, tags):
    store, tenant = req.app.store, req.principal['tenant']
    if len(tags) > TAG_LIMIT:
        raise errors.BedrockError('ServiceQuotaExceededException', f'A resource has at most {TAG_LIMIT} tags')
    with store.transaction():
        if tags:
            store.put(tenant, 'bedrock_tags', {'tags': tags}, f'{kind}:{ident}')
        else:
            try:
                store.delete(tenant, 'bedrock_tags', f'{kind}:{ident}')
            except KeyError:
                pass


def taggable(req, value):
    need_str(value, 'resourceARN', 1, 2048)
    kind, ident = split_arn(req, value, 'resourceARN') if value.startswith('arn:') else (None, None)
    if kind is None:
        raise errors.validation('resourceARN must be a Nuvora Bedrock ARN')
    if kind != 'guardrail':
        raise refuse('Tags on ' + kind, 'only guardrails carry tags; other Nuvora resources have none')
    call(req.app.get, req.principal, 'guardrails', ident)
    return kind, ident


def tag_resource(req):
    admin(req)
    body = check_members(req.json(), ('resourceARN', 'tags'), '')
    kind, ident = taggable(req, body.get('resourceARN'))
    new = validate_tags(body.get('tags'))
    save_tags(req, kind, ident, {**tags_of(req, kind, ident), **new})
    req.app.store.audit(req.principal['tenant'], req.principal['username'], 'bedrock.tags.added', ident, {'keys': sorted(new)})
    return Response({})


def untag_resource(req):
    admin(req)
    body = check_members(req.json(), ('resourceARN', 'tagKeys'), '')
    kind, ident = taggable(req, body.get('resourceARN'))
    keys = [need_str(k, 'tagKeys', 1, 128) for k in need_list(body.get('tagKeys'), 'tagKeys', TAG_LIMIT)]
    current = tags_of(req, kind, ident)
    save_tags(req, kind, ident, {k: v for k, v in current.items() if k not in keys})
    req.app.store.audit(req.principal['tenant'], req.principal['username'], 'bedrock.tags.removed', ident, {'keys': sorted(keys)})
    return Response({})


def list_tags(req):
    body = check_members(req.json(), ('resourceARN',), '')
    kind, ident = taggable(req, body.get('resourceARN'))
    return Response({'tags': [{'key': k, 'value': v} for k, v in sorted(tags_of(req, kind, ident).items())]})


# ---- guardrails ---------------------------------------------------------------------------

CONTENT_TYPES = {'HATE': 'hate', 'VIOLENCE': 'violence', 'SEXUAL': 'sexual', 'MISCONDUCT': 'misconduct', 'PROMPT_ATTACK': 'prompt_attack'}
PII_TYPES = {'EMAIL': 'email', 'PHONE': 'phone', 'CREDIT_DEBIT_CARD_NUMBER': 'card', 'US_SOCIAL_SECURITY_NUMBER': 'ssn',
             'IP_ADDRESS': 'ipv4', 'INTERNATIONAL_BANK_ACCOUNT_NUMBER': 'iban'}
GUARDRAIL_NAME = r'[0-9a-zA-Z_ -]{1,50}'
GUARDRAIL_REFUSED = {
    'automatedReasoningPolicyConfig': 'Nuvora has no automated reasoning checks',
    'crossRegionConfig': 'a guardrail runs where it is stored; there are no cross-region guardrail profiles',
    'kmsKeyId': 'guardrails are stored with the tenant database; there is no per-resource KMS key',
}
GUARDRAIL_MEMBERS = ('name', 'description', 'topicPolicyConfig', 'contentPolicyConfig', 'wordPolicyConfig',
                     'sensitiveInformationPolicyConfig', 'contextualGroundingPolicyConfig', 'blockedInputMessaging', 'blockedOutputsMessaging')
DIRS = (('input', 'inputAction', 'inputEnabled'), ('output', 'outputAction', 'outputEnabled'))


def directions(item, where, legacy=None, allowed=('BLOCK',)):
    """{'input': action|None, 'output': action|None}: None when that direction is switched off. NONE (detect only) is refused."""
    out = {}
    for name, action_key, enabled_key in DIRS:
        enabled = item.get(enabled_key, True)
        if not isinstance(enabled, bool):
            raise errors.validation(f'{where}.{enabled_key} must be a boolean')
        action = item.get(action_key) or legacy or 'BLOCK'
        if enabled and action == 'NONE':
            raise refuse(f'{where}.{action_key} NONE (detect mode)', 'a guardrail either blocks or anonymizes; it cannot only report')
        if enabled and action not in allowed:
            raise errors.validation(f'{where}.{action_key} must be one of {", ".join(allowed)}')
        out[name] = action if enabled else None
    return out


def classifier_model(req):
    """The chat model that content filters use to classify: NUVORA_GUARDRAIL_CLASSIFIER_MODEL, else the tenant's oldest enabled real chat model."""
    chosen = os.getenv('NUVORA_GUARDRAIL_CLASSIFIER_MODEL')
    if chosen:
        return chosen
    models = sorted((m for m in req.app.list(req.principal, 'models') if m.get('enabled') and m.get('capability', 'chat') == 'chat' and m.get('provider') != 'demo'),
                    key=lambda m: (m['created'], m['id']))
    return models[0]['id'] if models else None


def guardrail_input(req, body):
    """Bedrock create/update members -> a Nuvora guardrail resource body."""
    check_members(body, GUARDRAIL_MEMBERS + ('tags', 'clientRequestToken'), '', GUARDRAIL_REFUSED)
    name = need_str(body.get('name'), 'name', 1, 50, GUARDRAIL_NAME)
    sections = {'input': {}, 'output': {}}
    meta = {'topics': {}, 'regexes': {}}

    topics = body.get('topicPolicyConfig')
    if topics is not None:
        check_members(topics, ('topicsConfig', 'tierConfig'), 'topicPolicyConfig', {'tierConfig': 'Nuvora has a single topic matcher, not Classic/Standard tiers'})
        for n, topic in enumerate(need_list(topics.get('topicsConfig'), 'topicPolicyConfig.topicsConfig', 30)):
            where = f'topicPolicyConfig.topicsConfig[{n}]'
            check_members(topic, ('name', 'definition', 'examples', 'type', 'inputAction', 'outputAction', 'inputEnabled', 'outputEnabled'), where)
            tname = need_str(topic.get('name'), where + '.name', 1, 100)
            need_str(topic.get('definition'), where + '.definition', 1, 1000)
            if topic.get('type') != 'DENY':
                raise errors.validation(where + '.type must be DENY')
            for action in directions(topic, where).items():
                if action[1]:
                    sections[action[0]].setdefault('blocked_topics', []).append(tname)
            # Matching is the topic name only, a case-insensitive substring; the definition and examples are kept for display.
            meta['topics'][tname] = {'definition': topic['definition'], 'examples': topic.get('examples') or []}

    content = body.get('contentPolicyConfig')
    if content is not None:
        check_members(content, ('filtersConfig', 'tierConfig'), 'contentPolicyConfig', {'tierConfig': 'Nuvora has a single content filter engine, not Classic/Standard tiers'})
        seen, model = set(), None
        for n, item in enumerate(need_list(content.get('filtersConfig'), 'contentPolicyConfig.filtersConfig', 10)):
            where = f'contentPolicyConfig.filtersConfig[{n}]'
            check_members(item, ('type', 'inputStrength', 'outputStrength', 'inputModalities', 'outputModalities', 'inputAction', 'outputAction', 'inputEnabled', 'outputEnabled'), where)
            kind = item.get('type')
            if kind == 'INSULTS':
                raise refuse(where + '.type INSULTS', 'Nuvora has no insults category (hate, violence, sexual, misconduct and prompt attack are mapped)')
            if kind not in CONTENT_TYPES:
                raise errors.validation(f'{where}.type must be one of ' + ', '.join(sorted(CONTENT_TYPES)))
            if kind in seen:
                raise errors.validation(f'{where}.type {kind} is listed twice')
            seen.add(kind)
            for key in ('inputModalities', 'outputModalities'):
                if item.get(key) not in (None, ['TEXT']):
                    raise refuse(f'{where}.{key}', 'only TEXT content is filtered')
            live = directions(item, where)
            for (side, _, _), strength_key in zip(DIRS, ('inputStrength', 'outputStrength')):
                strength = item.get(strength_key)
                if strength not in ('NONE', 'LOW', 'MEDIUM', 'HIGH'):
                    raise errors.validation(f'{where}.{strength_key} must be NONE, LOW, MEDIUM or HIGH')
                if kind == 'PROMPT_ATTACK' and side == 'output' and strength != 'NONE':
                    raise errors.validation(f'{where}.outputStrength must be NONE for PROMPT_ATTACK')
                if live[side] is None:
                    strength = 'NONE'
                sections[side].setdefault('strengths', {})[CONTENT_TYPES[kind]] = strength
                if strength != 'NONE' and kind != 'PROMPT_ATTACK':
                    model = model or classifier_model(req)
                    if model is None:
                        raise errors.validation(f'{where}: the {kind} filter needs a real chat model to classify with, and this tenant has none enabled '
                                                '(register one, or set NUVORA_GUARDRAIL_CLASSIFIER_MODEL)')
                    sections[side]['classifier_model'] = model

    words = body.get('wordPolicyConfig')
    if words is not None:
        check_members(words, ('wordsConfig', 'managedWordListsConfig'), 'wordPolicyConfig')
        if words.get('managedWordListsConfig'):
            raise refuse('wordPolicyConfig.managedWordListsConfig', 'Nuvora ships no managed word lists (PROFANITY); list the words in wordsConfig')
        for n, item in enumerate(need_list(words.get('wordsConfig', []), 'wordPolicyConfig.wordsConfig', 200)):
            where = f'wordPolicyConfig.wordsConfig[{n}]'
            check_members(item, ('text', 'inputAction', 'outputAction', 'inputEnabled', 'outputEnabled'), where)
            text = need_str(item.get('text'), where + '.text', 1, 100)
            for side, action in directions(item, where).items():
                if action and text not in sections[side].setdefault('word_filters', []):
                    sections[side]['word_filters'].append(text)

    sensitive = body.get('sensitiveInformationPolicyConfig')
    if sensitive is not None:
        check_members(sensitive, ('piiEntitiesConfig', 'regexesConfig'), 'sensitiveInformationPolicyConfig')
        for n, item in enumerate(need_list(sensitive.get('piiEntitiesConfig', []), 'sensitiveInformationPolicyConfig.piiEntitiesConfig', 100)):
            where = f'sensitiveInformationPolicyConfig.piiEntitiesConfig[{n}]'
            check_members(item, ('type', 'action', 'inputAction', 'outputAction', 'inputEnabled', 'outputEnabled'), where)
            kind = item.get('type')
            if kind not in PII_TYPES:
                raise refuse(f'{where}.type {kind}', 'Nuvora detects ' + ', '.join(PII_TYPES))
            for side, action in directions(item, where, item.get('action'), ('BLOCK', 'ANONYMIZE')).items():
                if action:
                    entities = sections[side].setdefault('pii_entities', {})
                    if PII_TYPES[kind] in entities:
                        raise errors.validation(f'{where}.type {kind} is listed twice')
                    entities[PII_TYPES[kind]] = 'mask' if action == 'ANONYMIZE' else 'block'
        for n, item in enumerate(need_list(sensitive.get('regexesConfig', []), 'sensitiveInformationPolicyConfig.regexesConfig', 20)):
            where = f'sensitiveInformationPolicyConfig.regexesConfig[{n}]'
            check_members(item, ('name', 'description', 'pattern', 'action', 'inputAction', 'outputAction', 'inputEnabled', 'outputEnabled'), where)
            rname = need_str(item.get('name'), where + '.name', 1, 100)
            pattern = need_str(item.get('pattern'), where + '.pattern', 1, 200)
            for side, action in directions(item, where, item.get('action'), ('BLOCK', 'ANONYMIZE')).items():
                if action:
                    sections[side].setdefault('regex_filters', []).append({'name': rname, 'pattern': pattern, 'action': 'mask' if action == 'ANONYMIZE' else 'block'})
            meta['regexes'][rname] = item.get('description', '')

    grounding = body.get('contextualGroundingPolicyConfig')
    if grounding is not None:
        check_members(grounding, ('filtersConfig',), 'contextualGroundingPolicyConfig')
        for n, item in enumerate(need_list(grounding.get('filtersConfig'), 'contextualGroundingPolicyConfig.filtersConfig', 2)):
            where = f'contextualGroundingPolicyConfig.filtersConfig[{n}]'
            check_members(item, ('type', 'threshold', 'action', 'enabled'), where)
            if item.get('type') == 'RELEVANCE':
                raise refuse(where + '.type RELEVANCE', 'Nuvora checks grounding in the supplied sources, not query relevance')
            if item.get('type') != 'GROUNDING':
                raise errors.validation(where + '.type must be GROUNDING or RELEVANCE')
            threshold = item.get('threshold')
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 0.99:
                raise errors.validation(where + '.threshold must be a number between 0 and 0.99')
            if item.get('action', 'BLOCK') == 'NONE':
                raise refuse(where + '.action NONE (detect mode)', 'a guardrail either blocks or anonymizes; it cannot only report')
            if item.get('enabled', True) is not False:
                sections['output']['grounding_threshold'] = threshold

    data = {'name': name, 'input': sections['input'], 'output': sections['output'],
            'blocked_input_message': need_str(body.get('blockedInputMessaging'), 'blockedInputMessaging', 1, 500),
            'blocked_output_message': need_str(body.get('blockedOutputsMessaging'), 'blockedOutputsMessaging', 1, 500)}
    if 'description' in body:
        data['description'] = need_str(body['description'], 'description', 0, 200)
    return data, meta


def guardrail_meta(req, ident):
    try:
        return req.app.store.get(req.principal['tenant'], 'bedrock_guardrails', ident)
    except KeyError:
        return {'topics': {}, 'regexes': {}}


def merge_sides(entries, key):
    """entries: {side: [(identity, payload)]} -> [(identity, payload, {side: True})] in first-seen order."""
    order, seen = [], {}
    for side in ('input', 'output'):
        for ident, payload in entries[side]:
            if ident not in seen:
                seen[ident] = [payload, set()]
                order.append(ident)
            seen[ident][1].add(side)
    return [(i, seen[i][0], seen[i][1]) for i in order]


def sided(sides, action_of):
    out = {'inputEnabled': 'input' in sides, 'outputEnabled': 'output' in sides}
    for side in ('input', 'output'):
        if side in sides:
            out[side + 'Action'] = action_of(side)
    return out


def guardrail_view(record, meta):
    """A stored Nuvora guardrail (draft or version snapshot) in the shape of GetGuardrail."""
    inp, out = record.get('input') or {}, record.get('output') or {}
    sections = {'input': inp, 'output': out}
    view = {'name': record['name'], 'blockedInputMessaging': record.get('blocked_input_message', 'Sorry, the model cannot answer this question.'),
            'blockedOutputsMessaging': record.get('blocked_output_message', 'Sorry, the model cannot answer this question.')}
    if record.get('description'):
        view['description'] = record['description']
    topics = merge_sides({s: [(t, t) for t in sections[s].get('blocked_topics', [])] for s in sections}, 'topic')
    if topics:
        view['topicPolicy'] = {'topics': [{'name': t, 'definition': meta['topics'].get(t, {}).get('definition', t), 'examples': meta['topics'].get(t, {}).get('examples', []),
                                           'type': 'DENY', **sided(sides, lambda s: 'BLOCK')} for t, _, sides in topics]}
    filters = []
    for kind, ours in CONTENT_TYPES.items():
        strengths = {s: sections[s].get('strengths', {}).get(ours) for s in sections}
        if all(v is None for v in strengths.values()):
            continue
        item = {'type': kind, 'inputStrength': strengths['input'] or 'NONE', 'outputStrength': strengths['output'] or 'NONE',
                'inputModalities': ['TEXT'], 'outputModalities': ['TEXT'],
                'inputAction': 'BLOCK', 'outputAction': 'BLOCK',
                'inputEnabled': strengths['input'] not in (None, 'NONE'), 'outputEnabled': strengths['output'] not in (None, 'NONE')}
        filters.append(item)
    if filters:
        view['contentPolicy'] = {'filters': filters}
    words = merge_sides({s: [(w, w) for w in sections[s].get('word_filters', [])] for s in sections}, 'word')
    if words:
        view['wordPolicy'] = {'words': [{'text': w, **sided(sides, lambda s: 'BLOCK')} for w, _, sides in words]}
    pii = merge_sides({s: [(k, v) for k, v in sections[s].get('pii_entities', {}).items()] for s in sections}, 'pii')
    reverse = {v: k for k, v in PII_TYPES.items()}
    regexes = merge_sides({s: [((f['name'], f['pattern'], f.get('action', 'block')), f) for f in sections[s].get('regex_filters', [])] for s in sections}, 'regex')
    if pii or regexes:
        policy = {}
        if pii:
            policy['piiEntities'] = []
            for kind, _, sides in pii:
                acts = {s: 'ANONYMIZE' if sections[s]['pii_entities'][kind] == 'mask' else 'BLOCK' for s in sides}
                policy['piiEntities'].append({'type': reverse[kind], 'action': acts.get('input') or acts['output'], **sided(sides, lambda s, a=acts: a[s])})
        if regexes:
            policy['regexes'] = []
            for (rname, pattern, action), _, sides in regexes:
                act = 'ANONYMIZE' if action == 'mask' else 'BLOCK'
                policy['regexes'].append({'name': rname, 'description': meta['regexes'].get(rname, ''), 'pattern': pattern, 'action': act, **sided(sides, lambda s, a=act: a)})
        view['sensitiveInformationPolicy'] = policy
    threshold = out.get('grounding_threshold')
    level = (out.get('strengths') or {}).get('grounding')
    if threshold is None and level in GROUNDING_SCORE:
        threshold = GROUNDING_SCORE[level]
    if threshold:
        view['contextualGroundingPolicy'] = {'filters': [{'type': 'GROUNDING', 'threshold': threshold, 'action': 'BLOCK', 'enabled': True}]}
    return view


def guardrail_summary_fields(req, ident, version, created, updated):
    return {'id': ident, 'arn': arn_for(req, 'guardrail', ident), 'status': 'READY', 'version': str(version), 'createdAt': iso(created), 'updatedAt': iso(updated)}


def guardrail_ident(req, value='guardrailIdentifier'):
    return ident_for(req, req.params[value], 'guardrail', value)


def all_guardrails(req):
    return req.app.list(req.principal, 'guardrails')


def name_in_use(req, name, except_id=None):
    return any(g['name'] == name and g['id'] != except_id for g in all_guardrails(req))


def create_guardrail(req):
    admin(req)
    body = req.json()
    data, meta = guardrail_input(req, body)
    token = body.get('clientRequestToken')
    store, tenant = req.app.store, req.principal['tenant']
    if token is not None:
        need_str(token, 'clientRequestToken', 33, 256)
        for known in store.list(tenant, 'bedrock_guardrails'):
            if known.get('token') == token:
                if known.get('name') != data['name']:
                    raise errors.BedrockError('ConflictException', 'clientRequestToken was already used for a different guardrail')
                again = call(req.app.get, req.principal, 'guardrails', known['id'])
                return Response({'guardrailId': again['id'], 'guardrailArn': arn_for(req, 'guardrail', again['id']), 'version': 'DRAFT', 'createdAt': iso(again['created'])}, 202)
    tags = validate_tags(body['tags']) if 'tags' in body else {}
    if name_in_use(req, data['name']):
        raise errors.BedrockError('ConflictException', f"A guardrail named {data['name']} already exists")
    try:
        record = req.app.create(req.principal, 'guardrails', data)
    except Fault as exc:
        raise errors.from_fault(exc) from None
    store.put(tenant, 'bedrock_guardrails', {**meta, 'name': data['name'], 'token': token}, record['id'])
    if tags:
        save_tags(req, 'guardrail', record['id'], tags)
    return Response({'guardrailId': record['id'], 'guardrailArn': arn_for(req, 'guardrail', record['id']), 'version': 'DRAFT', 'createdAt': iso(record['created'])}, 202)


def version_arg(value, label='guardrailVersion', numeric=False):
    if value is None:
        return None if numeric else 'DRAFT'
    if value == 'DRAFT' and not numeric:
        return value
    if not re.fullmatch(r'[1-9][0-9]{0,8}', value):
        raise errors.validation(f'{label} must be {"" if numeric else "DRAFT or "}a version number')
    return int(value)


def get_guardrail(req):
    check_query(req, ('guardrailVersion',))
    ident = guardrail_ident(req)
    number = version_arg(req.query.get('guardrailVersion'))
    draft = call(req.app.get, req.principal, 'guardrails', ident)
    meta = guardrail_meta(req, ident)
    if number == 'DRAFT':
        record, created, updated = draft, draft['created'], draft['updated']
    else:
        stored = call(req.app.guardrail_version, req.principal, ident, number)[1]
        version = req.app.store.get(req.principal['tenant'], 'guardrail_versions', f'{ident}:{number}')
        record, created, updated = stored, version['created'], version['created']
    view = guardrail_view(record, meta)
    return Response({**view, 'guardrailId': ident, 'guardrailArn': arn_for(req, 'guardrail', ident), 'version': str(number), 'status': 'READY',
                     'createdAt': iso(created), 'updatedAt': iso(updated)})


def list_guardrails(req):
    check_query(req, ('guardrailIdentifier', 'maxResults', 'nextToken'))
    items = []
    if req.query.get('guardrailIdentifier'):
        ident = ident_for(req, req.query['guardrailIdentifier'], 'guardrail', 'guardrailIdentifier')
        draft = call(req.app.get, req.principal, 'guardrails', ident)
        items.append((draft['created'], 'DRAFT', {**guardrail_summary_fields(req, ident, 'DRAFT', draft['created'], draft['updated']), 'name': draft['name'],
                                                  **({'description': draft['description']} if draft.get('description') else {})}))
        for number, record in call(lambda: [(v['version'], v) for v in req.app.guardrail_versions(req.principal, ident)['items']]):
            items.append((record['created'], '%09d' % number, {**guardrail_summary_fields(req, ident, number, record['created'], record['created']), 'name': record['name'],
                                                                  **({'description': record['description']} if record.get('description') else {})}))
    else:
        for g in all_guardrails(req):
            items.append((g['created'], g['id'], {**guardrail_summary_fields(req, g['id'], 'DRAFT', g['created'], g['updated']), 'name': g['name'],
                                                  **({'description': g['description']} if g.get('description') else {})}))
    payloads, more = paginate(items, req.query)
    return listing('guardrails', payloads, more)


def update_guardrail(req):
    admin(req)
    ident = guardrail_ident(req)
    current = call(req.app.get, req.principal, 'guardrails', ident)
    body = req.json()
    data, meta = guardrail_input(req, body)
    if 'tags' in body or 'clientRequestToken' in body:
        raise refuse('tags/clientRequestToken on UpdateGuardrail', 'UpdateGuardrail does not take them; use TagResource')
    if name_in_use(req, data['name'], ident):
        raise errors.BedrockError('ConflictException', f"A guardrail named {data['name']} already exists")
    try:
        record = call(req.app.create, req.principal, 'guardrails', {**data, 'expected_revision': current['revision']}, ident)
    except Fault as exc:
        raise errors.from_fault(exc) from None
    known = guardrail_meta(req, ident)
    req.app.store.put(req.principal['tenant'], 'bedrock_guardrails', {**meta, 'name': data['name'], 'token': known.get('token')}, ident)
    return Response({'guardrailId': ident, 'guardrailArn': arn_for(req, 'guardrail', ident), 'version': 'DRAFT', 'updatedAt': iso(record['updated'])}, 202)


def delete_guardrail(req):
    admin(req)
    check_query(req, ('guardrailVersion',))
    ident = guardrail_ident(req)
    number = version_arg(req.query.get('guardrailVersion'), numeric=True)
    store, tenant = req.app.store, req.principal['tenant']
    call(req.app.get, req.principal, 'guardrails', ident)
    if number is not None:
        try:
            store.delete(tenant, 'guardrail_versions', f'{ident}:{number}')
        except KeyError:
            raise errors.not_found(f'Guardrail {ident} has no version {number}') from None
        store.audit(tenant, req.principal['username'], 'guardrails.version_deleted', ident, {'version': number})
        return Response({}, 202)
    call(req.app.delete, req.principal, 'guardrails', ident)
    for kind, key in (('bedrock_guardrails', ident), ('bedrock_tags', 'guardrail:' + ident)):
        try:
            store.delete(tenant, kind, key)
        except KeyError:
            pass
    return Response({}, 202)


def create_guardrail_version(req):
    admin(req)
    ident = guardrail_ident(req)
    body = check_members(req.json(), ('description', 'clientRequestToken'), '')
    description = need_str(body.get('description', ''), 'description', 0, 200)
    token = body.get('clientRequestToken')
    if token is not None:
        need_str(token, 'clientRequestToken', 33, 256)
        for v in call(lambda: req.app.guardrail_versions(req.principal, ident)['items']):
            stored = req.app.store.get(req.principal['tenant'], 'guardrail_versions', f"{ident}:{v['version']}")
            if stored.get('token') == token:
                return Response({'guardrailId': ident, 'version': str(v['version'])}, 202)
    try:
        view = call(req.app.create_guardrail_version, req.principal, ident, description)
    except Fault as exc:
        raise errors.from_fault(exc) from None
    if token is not None:
        key = f"{ident}:{view['version']}"
        stored = req.app.store.get(req.principal['tenant'], 'guardrail_versions', key)
        req.app.store.put(req.principal['tenant'], 'guardrail_versions', {**{k: v for k, v in stored.items() if k not in ('id', 'revision', 'created', 'updated', 'tenant')}, 'token': token}, key)
    return Response({'guardrailId': ident, 'version': str(view['version'])}, 202)


# ---- inference profiles (read only, over routers) -------------------------------------------

def profile_view(req, router):
    out = {'inferenceProfileName': router['name'], 'inferenceProfileArn': arn_for(req, 'inference-profile', router['id']), 'inferenceProfileId': router['id'],
           'models': [{'modelArn': model_summary({'id': m}, req.region or 'local')['modelArn']} for m in router.get('models', [])],
           'status': 'ACTIVE', 'type': 'APPLICATION', 'createdAt': iso(router['created']), 'updatedAt': iso(router['updated'])}
    out['description'] = f"Nuvora router ({router.get('strategy', 'cascade')}) over {len(router.get('models', []))} models, cheapest first"
    return out


def list_inference_profiles(req):
    check_query(req, ('maxResults', 'nextToken', 'type'))   # `type` is the wire name of the typeEquals member
    kind = req.query.get('type')
    if kind not in (None, 'SYSTEM_DEFINED', 'APPLICATION'):
        raise errors.validation('type (typeEquals) must be SYSTEM_DEFINED or APPLICATION')
    routers = [] if kind == 'SYSTEM_DEFINED' else req.app.list(req.principal, 'routers')
    payloads, more = paginate([(r['created'], r['id'], profile_view(req, r)) for r in routers], req.query)
    return listing('inferenceProfileSummaries', payloads, more)


def get_inference_profile(req):
    value = need_str(req.params['inferenceProfileIdentifier'], 'inferenceProfileIdentifier', 1, 2048)
    ident = value[7:] if value.startswith('router:') else ident_for(req, value, 'inference-profile', 'inferenceProfileIdentifier')
    if ident.startswith('router:'):
        ident = ident[7:]
    try:
        router = req.app.get(req.principal, 'routers', ident)
    except KeyError:
        raise errors.not_found(f'Could not find the inference profile {value}: no such router') from None
    return Response(profile_view(req, router))


def unsupported_profile_write(operation, detail):
    def handler(req):
        raise errors.BedrockError('UnsupportedOperationException', f'{operation} is not supported by Nuvora: {detail}', 501)
    return handler


# ---- model invocation logging ----------------------------------------------------------------

LOGGING_FLAGS = ('textDataDeliveryEnabled', 'imageDataDeliveryEnabled', 'embeddingDataDeliveryEnabled', 'videoDataDeliveryEnabled', 'audioDataDeliveryEnabled')


def put_logging(req):
    admin(req)
    body = check_members(req.json(), ('loggingConfig',), '')
    config = check_members(body.get('loggingConfig'), ('cloudWatchConfig', 's3Config') + LOGGING_FLAGS, 'loggingConfig',
                           {'cloudWatchConfig': 'Nuvora does not deliver to CloudWatch Logs', 's3Config': 'Nuvora does not deliver to S3'})
    for flag in LOGGING_FLAGS:
        if config.get(flag, False) is not False:
            if not isinstance(config[flag], bool):
                raise errors.validation(f'loggingConfig.{flag} must be a boolean')
            raise refuse(f'loggingConfig.{flag}', 'Nuvora does not record prompt or response payloads outside the guardrail-checked pipeline; it records usage and audit events '
                         '(GET /api/usage, /api/audit) for every invocation, whatever this setting says')
    stored = {flag: False for flag in LOGGING_FLAGS}
    req.app.store.put(req.principal['tenant'], 'bedrock_logging', {'config': stored, 'by': req.principal['username']}, 'config')
    req.app.store.audit(req.principal['tenant'], req.principal['username'], 'bedrock.logging.configured', 'config', {'delivery': 'none'})
    return Response({})


def get_logging(req):
    try:
        return Response({'loggingConfig': req.app.store.get(req.principal['tenant'], 'bedrock_logging', 'config')['config']})
    except KeyError:
        return Response({})


def delete_logging(req):
    admin(req)
    try:
        req.app.store.delete(req.principal['tenant'], 'bedrock_logging', 'config')
    except KeyError:
        raise errors.not_found('Model invocation logging is not configured') from None
    req.app.store.audit(req.principal['tenant'], req.principal['username'], 'bedrock.logging.deleted', 'config')
    return Response({})


# ---- job plumbing (customization + evaluation) ------------------------------------------------

JOB_NAME = r'[a-zA-Z0-9](-*[a-zA-Z0-9+.-])*'


def job_status(job):
    status = (job or {}).get('status')
    if status == 'completed':
        return 'Completed'
    if status in ('failed', 'interrupted', 'rejected', None):
        return 'Failed'
    return 'InProgress'


def lookup_job(req, kind_store, kind_arn, value):
    """The bedrock-layer record for a job identifier: an id, an ARN or a unique job name."""
    value = need_str(value, 'jobIdentifier', 1, 2048)
    ident = ident_for(req, value, kind_arn, 'jobIdentifier') if value.startswith('arn:') else value
    store, tenant = req.app.store, req.principal['tenant']
    try:
        return store.get(tenant, kind_store, ident)
    except KeyError:
        pass
    named = [r for r in store.list(tenant, kind_store) if r.get('name') == value]
    if len(named) == 1:
        return named[0]
    raise errors.not_found(f'Could not find the job {value}')


def job_or_none(req, record):
    try:
        return req.app.store.get(req.principal['tenant'], 'jobs', record['id'])
    except KeyError:
        return None


def job_filters(req, records, status_of):
    q = req.query
    allowed = ('creationTimeAfter', 'creationTimeBefore', 'statusEquals', 'nameContains', 'maxResults', 'nextToken', 'sortBy', 'sortOrder', 'applicationTypeEquals')
    check_query(req, allowed)
    if q.get('statusEquals') and q['statusEquals'] not in ('InProgress', 'Completed', 'Failed', 'Stopping', 'Stopped', 'Deleting'):
        raise errors.validation('statusEquals is not a job status')
    if q.get('sortBy') not in (None, 'CreationTime'):
        raise errors.validation('sortBy must be CreationTime')
    if q.get('sortOrder') not in (None, 'Ascending', 'Descending'):
        raise errors.validation('sortOrder must be Ascending or Descending')
    if q.get('applicationTypeEquals') not in (None, 'ModelEvaluation', 'RagEvaluation'):
        raise errors.validation('applicationTypeEquals must be ModelEvaluation or RagEvaluation')
    after = parse_time(q['creationTimeAfter'], 'creationTimeAfter') if q.get('creationTimeAfter') else None
    before = parse_time(q['creationTimeBefore'], 'creationTimeBefore') if q.get('creationTimeBefore') else None
    out = []
    for r in records:
        if q.get('statusEquals') and status_of(r) != q['statusEquals']:
            continue
        if q.get('nameContains') and q['nameContains'] not in r['name']:
            continue
        if after is not None and r['created'] < after:
            continue
        if before is not None and r['created'] >= before:
            continue
        if q.get('applicationTypeEquals') == 'RagEvaluation':
            continue
        out.append(r)
    return out, q.get('sortOrder', 'Descending') == 'Descending'


def data_ref(value, where, kind):
    """`nuvora://<kind>/<id>` -> id. S3 is refused by name."""
    need_str(value, where, 1, 1024)
    if value.startswith('s3://'):
        raise refuse(f'{where} {value}', f'Nuvora does not read S3 here; reference a Nuvora resource as nuvora://{kind}/<id>')
    match = re.fullmatch(r'nuvora://' + kind + r'/([A-Za-z0-9_-]{1,64})', value)
    if not match:
        raise errors.validation(f'{where} must be nuvora://{kind}/<id>')
    return match.group(1)


def output_ref(value, where):
    need_str(value, where, 1, 1024)
    if not value.startswith('nuvora://'):
        raise refuse(f'{where} {value}', 'Nuvora does not write job output to S3; results stay in the Nuvora job record (GET /api/jobs/<job id>), so pass nuvora://jobs')
    return value


def model_ref(req, value, where):
    """A Nuvora model id or foundation-model ARN -> model id (routers are not models here)."""
    need_str(value, where, 1, 2048)
    kind, ident = _arn_tail(value)
    if kind not in (None, 'foundation-model') or ident.startswith('router:'):
        raise refuse(f'{where} {value}', 'only a registered Nuvora model (id or foundation-model ARN) is accepted, not a router or profile')
    call(req.app.get, req.principal, 'models', ident)
    return ident


def claim_name(req, store_kind, name):
    if any(r.get('name') == name for r in req.app.store.list(req.principal['tenant'], store_kind)):
        raise errors.BedrockError('ConflictException', f'A job named {name} already exists')


def by_token(req, store_kind, token):
    if token is None:
        return None
    need_str(token, 'clientRequestToken', 1, 256)
    for r in req.app.store.list(req.principal['tenant'], store_kind):
        if r.get('token') == token:
            return r
    return None


# ---- model customization jobs -------------------------------------------------------------------

CUSTOM_MEMBERS = ('jobName', 'customModelName', 'roleArn', 'clientRequestToken', 'baseModelIdentifier', 'customizationType', 'trainingDataConfig',
                  'outputDataConfig', 'hyperParameters', 'customizationConfig')
CUSTOM_REFUSED = {
    'customModelKmsKeyId': 'tuned models are registered in the tenant catalog; there is no per-model KMS key',
    'jobTags': 'jobs carry no tags in Nuvora',
    'customModelTags': 'models carry no tags in Nuvora',
    'validationDataConfig': 'the external trainer takes one dataset and reports its own metrics',
    'vpcConfig': 'training runs on the operator-configured trainer, not in a VPC Nuvora manages',
}
CUSTOM_TYPES = {'FINE_TUNING': 'lora', 'DISTILLATION': 'distillation'}
HYPER = {'epochCount': ('epochs', 1, 50), 'rank': ('rank', 1, 256)}


def custom_arn(req, ident):
    return arn_for(req, 'model-customization-job', ident)


def create_customization(req):
    admin(req)
    body = check_members(req.json(), CUSTOM_MEMBERS, '', CUSTOM_REFUSED)
    app, p = req.app, req.principal
    name = need_str(body.get('jobName'), 'jobName', 1, 63, JOB_NAME)
    model_name = need_str(body.get('customModelName'), 'customModelName', 1, 63, JOB_NAME)
    need_str(body.get('roleArn'), 'roleArn', 20, 2048)
    again = by_token(req, 'bedrock_custom_jobs', body.get('clientRequestToken'))
    if again:
        if again['name'] != name:
            raise errors.BedrockError('ConflictException', 'clientRequestToken was already used for a different job')
        return Response({'jobArn': custom_arn(req, again['id'])}, 201)
    kind = body.get('customizationType', 'FINE_TUNING')
    if kind not in CUSTOM_TYPES:
        raise refuse(f'customizationType {kind}', 'Nuvora fine-tunes (LoRA) and distils through its external trainer; continued pre-training, reinforcement fine-tuning and imports are not available')
    base = model_ref(req, body.get('baseModelIdentifier'), 'baseModelIdentifier')
    training = check_members(body.get('trainingDataConfig') or {}, ('s3Uri', 'invocationLogsConfig'), 'trainingDataConfig',
                             {'invocationLogsConfig': 'distil from a Nuvora dataset (nuvora://datasets/<id>), not invocation logs'})
    dataset = data_ref(training.get('s3Uri'), 'trainingDataConfig.s3Uri', 'datasets')
    output_ref(check_members(body.get('outputDataConfig'), ('s3Uri',), 'outputDataConfig').get('s3Uri'), 'outputDataConfig.s3Uri')
    recipe = {'name': model_name, 'model': base, 'method': CUSTOM_TYPES[kind], 'dataset_id': dataset}
    hyper = body.get('hyperParameters') or {}
    if not isinstance(hyper, dict):
        raise errors.validation('hyperParameters must be a map of strings')
    for key, value in hyper.items():
        if key not in HYPER:
            raise refuse(f'hyperParameters.{key}', 'Nuvora passes only epochCount and rank (LoRA rank) to the trainer')
        field, low, high = HYPER[key]
        if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,3}', value) or not low <= int(value) <= high:
            raise errors.validation(f'hyperParameters.{key} must be a whole number from {low} to {high}')
        recipe[field] = int(value)
    config = body.get('customizationConfig')
    if kind == 'DISTILLATION':
        teacher = check_members(config or {}, ('distillationConfig',), 'customizationConfig', {'rftConfig': 'reinforcement fine-tuning is not available'})
        teacher = check_members((teacher.get('distillationConfig') or {}).get('teacherModelConfig') or {}, ('teacherModelIdentifier', 'maxResponseLengthForInference'),
                                'customizationConfig.distillationConfig.teacherModelConfig',
                                {'maxResponseLengthForInference': 'Nuvora asks the teacher for up to 1024 tokens per answer'})
        recipe['teacher_model'] = model_ref(req, teacher.get('teacherModelIdentifier'), 'teacherModelIdentifier')
    elif config:
        raise refuse('customizationConfig', 'only distillation takes one')
    claim_name(req, 'bedrock_custom_jobs', name)
    if not app.integrations.configured('trainer'):
        raise errors.unavailable('No trainer is configured on this Nuvora server (NUVORA_TRAINER_URL); model customization is unavailable')
    try:
        created = app.create(p, 'recipes', recipe)
        try:
            job = app.new_job(p, 'training', created['id'], {})
        except Exception:
            app.delete(p, 'recipes', created['id'])
            raise
    except Fault as exc:
        raise errors.from_fault(exc) from None
    except KeyError:
        raise errors.not_found('Resource not found') from None
    app.store.put(p['tenant'], 'bedrock_custom_jobs', {'name': name, 'custom_model_name': model_name, 'recipe_id': created['id'], 'kind': kind, 'base_model': base,
                                                       'dataset_id': dataset, 'role_arn': body['roleArn'], 'hyper': hyper, 'token': body.get('clientRequestToken'),
                                                       'teacher_model': recipe.get('teacher_model'), 'output': body['outputDataConfig']['s3Uri']}, job['id'])
    return Response({'jobArn': custom_arn(req, job['id'])}, 201)


def custom_status(job):
    return job_status(job)


def custom_view(req, record, full):
    job = job_or_none(req, record)
    status = custom_status(job)
    try:
        recipe = req.app.store.get(req.principal['tenant'], 'recipes', record['recipe_id'])
    except KeyError:
        recipe = {}
    out = {'jobArn': custom_arn(req, record['id']), 'jobName': record['name'], 'status': status,
           'baseModelArn': model_summary({'id': record['base_model']}, req.region or 'local')['modelArn'],
           'creationTime': iso(record['created']), 'lastModifiedTime': iso((job or record)['updated']),
           'customModelName': record['custom_model_name'], 'customizationType': record['kind']}
    if status == 'Completed' and recipe.get('trained_model'):
        out['customModelArn'] = arn_for(req, 'custom-model', recipe['trained_model'])
    if job and job.get('finished'):
        out['endTime'] = iso(job['finished'])
    if not full:
        return out
    del out['customModelName']
    out.update(outputModelName=record['custom_model_name'], roleArn=record['role_arn'], hyperParameters=record['hyper'],
               trainingDataConfig={'s3Uri': f"nuvora://datasets/{record['dataset_id']}"}, validationDataConfig={'validators': []}, outputDataConfig={'s3Uri': record['output']})
    if 'customModelArn' in out:
        out['outputModelArn'] = out.pop('customModelArn')
    if record.get('token'):
        out['clientRequestToken'] = record['token']
    if record['kind'] == 'DISTILLATION':
        out['customizationConfig'] = {'distillationConfig': {'teacherModelConfig': {'teacherModelIdentifier': record['teacher_model']}}}
    if status == 'Failed':
        out['failureMessage'] = (job or {}).get('error') or 'The training job record no longer exists'
    return out


def get_customization(req):
    return Response(custom_view(req, lookup_job(req, 'bedrock_custom_jobs', 'model-customization-job', req.params['jobIdentifier']), True))


def list_customization(req):
    records = req.app.store.list(req.principal['tenant'], 'bedrock_custom_jobs')
    kept, descending = job_filters(req, records, lambda r: custom_status(job_or_none(req, r)))
    payloads, more = paginate([(r['created'], r['id'], custom_view(req, r, False)) for r in kept], req.query, descending)
    return listing('modelCustomizationJobSummaries', payloads, more)


def stop_job(req, store_kind, arn_kind, status_of, what):
    admin(req)
    record = lookup_job(req, store_kind, arn_kind, req.params['jobIdentifier'])
    status = status_of(job_or_none(req, record))
    if status != 'InProgress':
        raise errors.BedrockError('ConflictException', f'The {what} job is {status} and cannot be stopped')
    raise errors.BedrockError('UnsupportedOperationException', f'Stop is not supported by Nuvora: a queued or running job cannot be interrupted; it finishes or fails on its own', 501)


def stop_customization(req):
    return stop_job(req, 'bedrock_custom_jobs', 'model-customization-job', custom_status, 'model customization')


# ---- evaluation jobs ----------------------------------------------------------------------------

EVAL_MEMBERS = ('jobName', 'jobDescription', 'clientRequestToken', 'roleArn', 'applicationType', 'evaluationConfig', 'inferenceConfig', 'outputDataConfig')
EVAL_REFUSED = {'customerEncryptionKeyId': 'job records live in the tenant database; there is no per-job KMS key', 'jobTags': 'jobs carry no tags in Nuvora'}
METRICS = {'assertions': 'Nuvora.Assertions', 'judge': 'Nuvora.Judge', 'grounded': 'Nuvora.Grounded'}


def metrics_of(cases):
    used = {METRICS['assertions']}
    for case in cases:
        if case.get('judge'):
            used.add(METRICS['judge'])
        if case.get('grounded'):
            used.add(METRICS['grounded'])
    return sorted(used)


def eval_arn(req, ident):
    return arn_for(req, 'evaluation-job', ident)


def create_evaluation(req):
    admin(req)
    body = check_members(req.json(), EVAL_MEMBERS, '', EVAL_REFUSED)
    app, p = req.app, req.principal
    name = need_str(body.get('jobName'), 'jobName', 1, 63, JOB_NAME)
    need_str(body.get('roleArn'), 'roleArn', 20, 2048)
    description = need_str(body['jobDescription'], 'jobDescription', 1, 200) if 'jobDescription' in body else None
    again = by_token(req, 'bedrock_eval_jobs', body.get('clientRequestToken'))
    if again:
        if again['name'] != name:
            raise errors.BedrockError('ConflictException', 'clientRequestToken was already used for a different job')
        return Response({'jobArn': eval_arn(req, again['id'])}, 202)
    if body.get('applicationType', 'ModelEvaluation') != 'ModelEvaluation':
        raise refuse('applicationType ' + str(body['applicationType']), 'Nuvora has no RAG evaluation job; evaluate knowledge-grounded answers with grounded cases')
    output = output_ref(check_members(body.get('outputDataConfig'), ('s3Uri',), 'outputDataConfig').get('s3Uri'), 'outputDataConfig.s3Uri')
    config = check_members(body.get('evaluationConfig'), ('automated', 'human'), 'evaluationConfig', {'human': 'Nuvora has no human evaluation workflow'})
    auto = check_members(config.get('automated'), ('datasetMetricConfigs', 'evaluatorModelConfig', 'customMetricConfig'), 'evaluationConfig.automated',
                         {'customMetricConfig': 'metrics are Nuvora.Assertions, Nuvora.Judge and Nuvora.Grounded'})
    configs = need_list(auto.get('datasetMetricConfigs'), 'evaluationConfig.automated.datasetMetricConfigs', 5)
    if len(configs) != 1:
        raise refuse('evaluationConfig.automated.datasetMetricConfigs', 'exactly one dataset per job (a Nuvora evaluation is one set of cases)')
    where = 'evaluationConfig.automated.datasetMetricConfigs[0]'
    item = check_members(configs[0], ('taskType', 'dataset', 'metricNames'), where)
    if item.get('taskType') != 'Custom':
        raise refuse(f"{where}.taskType {item.get('taskType')}", 'Nuvora evaluations are user-supplied cases, which is the Custom task type; built-in task types and Builtin.* metrics do not exist')
    dataset = check_members(item.get('dataset'), ('name', 'datasetLocation'), where + '.dataset')
    need_str(dataset.get('name'), where + '.dataset.name', 1, 63)
    location = check_members(dataset.get('datasetLocation'), ('s3Uri',), where + '.dataset.datasetLocation')
    source_id = data_ref(location.get('s3Uri'), where + '.dataset.datasetLocation.s3Uri', 'evaluations')
    source = call(app.get, p, 'evaluations', source_id)
    wanted = [need_str(m, where + '.metricNames', 1, 100) for m in need_list(item.get('metricNames'), where + '.metricNames', 10)]
    expected = metrics_of(source['cases'])
    unknown = sorted(set(wanted) - set(METRICS.values()))
    if unknown:
        raise refuse(f'{where}.metricNames {", ".join(unknown)}', 'the metrics Nuvora has are ' + ', '.join(sorted(METRICS.values())))
    if sorted(set(wanted)) != expected:
        raise errors.validation(f'{where}.metricNames must list exactly the checks this dataset\'s cases run: {", ".join(expected)}')
    judge = None
    if auto.get('evaluatorModelConfig') is not None:
        models = need_list(check_members(auto['evaluatorModelConfig'], ('bedrockEvaluatorModels',), 'evaluationConfig.automated.evaluatorModelConfig').get('bedrockEvaluatorModels'),
                           'evaluatorModelConfig.bedrockEvaluatorModels', 1)
        if len(models) != 1:
            raise errors.validation('evaluatorModelConfig.bedrockEvaluatorModels takes exactly one model')
        judge = model_ref(req, check_members(models[0], ('modelIdentifier',), 'evaluatorModelConfig.bedrockEvaluatorModels[0]').get('modelIdentifier'), 'evaluator modelIdentifier')
        if len(expected) == 1:
            raise errors.validation('evaluatorModelConfig is only used by Nuvora.Judge and Nuvora.Grounded checks, and this dataset has none')
    inference = check_members(body.get('inferenceConfig'), ('models', 'ragConfigs'), 'inferenceConfig', {'ragConfigs': 'Nuvora has no RAG evaluation job'})
    models = need_list(inference.get('models'), 'inferenceConfig.models', 5)
    if len(models) != 1:
        raise refuse('inferenceConfig.models', 'exactly one model per job')
    pick = check_members(models[0], ('bedrockModel', 'precomputedInferenceSource'), 'inferenceConfig.models[0]',
                         {'precomputedInferenceSource': 'Nuvora generates the answers itself'})
    bedrock_model = check_members(pick.get('bedrockModel'), ('modelIdentifier', 'inferenceParams', 'performanceConfig'), 'inferenceConfig.models[0].bedrockModel',
                                  {'inferenceParams': 'evaluations run at temperature 0', 'performanceConfig': 'latency tiers do not exist'})
    model = model_ref(req, bedrock_model.get('modelIdentifier'), 'inferenceConfig.models[0].bedrockModel.modelIdentifier')
    claim_name(req, 'bedrock_eval_jobs', name)
    spec = {'name': (name + ' (Bedrock job)')[:120], 'model': model, 'cases': source['cases'], 'pass_threshold': source.get('pass_threshold', 1)}
    if source.get('knowledge_ids'):
        spec['knowledge_ids'] = source['knowledge_ids']
    if judge or source.get('judge_model'):
        spec['judge_model'] = judge or source['judge_model']
    try:
        evaluation = app.create(p, 'evaluations', spec)
        try:
            job = app.new_job(p, 'evaluation', evaluation['id'], {})
        except Exception:
            app.delete(p, 'evaluations', evaluation['id'])
            raise
    except Fault as exc:
        raise errors.from_fault(exc) from None
    except KeyError:
        raise errors.not_found('Resource not found') from None
    app.store.put(p['tenant'], 'bedrock_eval_jobs', {'name': name, 'description': description, 'evaluation_id': evaluation['id'], 'source_id': source_id, 'model': model, 'judge': judge,
                                                     'role_arn': body['roleArn'], 'token': body.get('clientRequestToken'), 'output': output, 'metrics': expected,
                                                     'dataset_name': dataset['name']}, job['id'])
    return Response({'jobArn': eval_arn(req, job['id'])}, 202)


def eval_status(job):
    return job_status(job)


def eval_view(req, record, full):
    job = job_or_none(req, record)
    status = eval_status(job)
    out = {'jobArn': eval_arn(req, record['id']), 'jobName': record['name'], 'status': status, 'creationTime': iso(record['created']),
           'jobType': 'Automated'}
    if not full:
        out.update(evaluationTaskTypes=['Custom'], modelIdentifiers=[record['model']], applicationType='ModelEvaluation')
        if record.get('judge'):
            out['evaluatorModelIdentifiers'] = [record['judge']]
        return out
    out.update(roleArn=record['role_arn'], applicationType='ModelEvaluation', lastModifiedTime=iso((job or record)['updated']),
               evaluationConfig={'automated': {'datasetMetricConfigs': [{'taskType': 'Custom', 'dataset': {'name': record['dataset_name'],
                                 'datasetLocation': {'s3Uri': f"nuvora://evaluations/{record['source_id']}"}}, 'metricNames': record['metrics']}],
                                 **({'evaluatorModelConfig': {'bedrockEvaluatorModels': [{'modelIdentifier': record['judge']}]}} if record.get('judge') else {})}},
               inferenceConfig={'models': [{'bedrockModel': {'modelIdentifier': record['model']}}]}, outputDataConfig={'s3Uri': record['output']})
    if record.get('description'):
        out['jobDescription'] = record['description']
    if status == 'Failed':
        out['failureMessages'] = [(job or {}).get('error') or 'The evaluation job record no longer exists']
    return out


def get_evaluation(req):
    return Response(eval_view(req, lookup_job(req, 'bedrock_eval_jobs', 'evaluation-job', req.params['jobIdentifier']), True))


def list_evaluation(req):
    records = req.app.store.list(req.principal['tenant'], 'bedrock_eval_jobs')
    kept, descending = job_filters(req, records, lambda r: eval_status(job_or_none(req, r)))
    payloads, more = paginate([(r['created'], r['id'], eval_view(req, r, False)) for r in kept], req.query, descending)
    return listing('jobSummaries', payloads, more)


def stop_evaluation(req):
    return stop_job(req, 'bedrock_eval_jobs', 'evaluation-job', eval_status, 'evaluation')


# ---- registration -------------------------------------------------------------------------------

HANDLERS = {
    'CreateGuardrail': create_guardrail, 'GetGuardrail': get_guardrail, 'ListGuardrails': list_guardrails, 'UpdateGuardrail': update_guardrail,
    'DeleteGuardrail': delete_guardrail, 'CreateGuardrailVersion': create_guardrail_version,
    'ListInferenceProfiles': list_inference_profiles, 'GetInferenceProfile': get_inference_profile,
    'CreateInferenceProfile': unsupported_profile_write('CreateInferenceProfile', 'a Nuvora inference profile is a router over 2-5 models, created in the console or with POST /api/routers; '
                                                         'an application profile that copies one model has no Nuvora equivalent'),
    'DeleteInferenceProfile': unsupported_profile_write('DeleteInferenceProfile', 'profiles are Nuvora routers; delete them with DELETE /api/routers/<id>'),
    'PutModelInvocationLoggingConfiguration': put_logging, 'GetModelInvocationLoggingConfiguration': get_logging,
    'DeleteModelInvocationLoggingConfiguration': delete_logging,
    'CreateModelCustomizationJob': create_customization, 'GetModelCustomizationJob': get_customization,
    'ListModelCustomizationJobs': list_customization, 'StopModelCustomizationJob': stop_customization,
    'CreateEvaluationJob': create_evaluation, 'GetEvaluationJob': get_evaluation, 'ListEvaluationJobs': list_evaluation, 'StopEvaluationJob': stop_evaluation,
    'TagResource': tag_resource, 'UntagResource': untag_resource, 'ListTagsForResource': list_tags,
}
# Operations of this service that router.py does not list yet (the table there predates the control plane).
EXTRA_ROUTES = [
    (CONTROL, 'POST', '/model-customization-jobs/{jobIdentifier}/stop', 'StopModelCustomizationJob'),
    (CONTROL, 'POST', '/evaluation-job/{jobIdentifier}/stop', 'StopEvaluationJob'),
    (CONTROL, 'POST', '/inference-profiles', 'CreateInferenceProfile'),
    (CONTROL, 'DELETE', '/inference-profiles/{inferenceProfileIdentifier}', 'DeleteInferenceProfile'),
]


def install(router):
    """Add the missing control-plane routes and attach the handlers."""
    known = {r.operation for r in router.routes}
    for route in EXTRA_ROUTES:
        if route[3] not in known:
            router.register(*route)
    for route in router.routes:
        if route.operation in HANDLERS:
            route.handler = HANDLERS[route.operation]
