# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Bedrock guardrails on the runtime surface: ApplyGuardrail, and the guardrail reference that Converse,
ConverseStream and InvokeModel carry (`guardrailConfig`, `X-Amzn-Bedrock-Guardrail*` headers).

The engine is the Nuvora guardrail resource (nuvora/guardrails.py, Platform.apply_guardrail and the
`guardrail: {id, version}` request reference). This module only translates: it names a Nuvora finding
as the closest Bedrock assessment entry and says so when there is none. Mapping, by Nuvora finding:

    DENIED_TOPIC            topicPolicy.topics[]            type DENY
    BLOCKED_WORD            wordPolicy.customWords[]
    PII_BLOCKED/ANONYMIZED  sensitiveInformationPolicy.piiEntities[]   (entity name mapped to Bedrock's type)
    REGEX_BLOCKED/ANONYMIZED sensitiveInformationPolicy.regexes[]
    CONTENT_FILTER          contentPolicy.filters[]         hate, violence, sexual, misconduct only
    PROMPT_ATTACK           contentPolicy.filters[]         type PROMPT_ATTACK
    GROUNDING               contextualGroundingPolicy.filters[]   type GROUNDING (score recomputed)
    self_harm filter, MAX_CHARS, other   no Bedrock entry: named in actionReason and in the `nuvora` extension

Every assessment also carries `nuvora.findings`, the unmapped Nuvora findings with their codes."""
import math
import re
import time

from .. import guardrails
from ..security import PII, Fault, grounding_score, require
from . import errors
from .router import Response

PII_TYPES = {'email': 'EMAIL', 'card': 'CREDIT_DEBIT_CARD_NUMBER', 'ssn': 'US_SOCIAL_SECURITY_NUMBER', 'ipv4': 'IP_ADDRESS', 'phone': 'PHONE',
             'iban': 'INTERNATIONAL_BANK_ACCOUNT_NUMBER'}
FILTER_TYPES = {'hate': 'HATE', 'violence': 'VIOLENCE', 'sexual': 'SEXUAL', 'misconduct': 'MISCONDUCT', 'prompt_attack': 'PROMPT_ATTACK'}
STRENGTH_OF_THRESHOLD = ((.8, 'LOW'), (.5, 'MEDIUM'), (0, 'HIGH'))
CONFIDENCE_OF_THRESHOLD = ((.8, 'HIGH'), (.5, 'MEDIUM'), (0, 'LOW'))
TRACE_VALUES = ('enabled', 'disabled', 'enabled_full')
UNITS_LABEL = 'computed; 1 unit = 1000 characters per configured policy, rounded up; Nuvora does not bill guardrail units'
MATCH_CAP = 50


def _bucket(table, threshold):
    return next(name for floor, name in table if threshold >= floor)


def parse_identifier(value):
    """A Nuvora guardrail id, or an ARN whose resource is `guardrail/<id>`."""
    if not isinstance(value, str) or not value:
        raise errors.validation('guardrailIdentifier is required')
    if value.startswith('arn:'):
        parts = value.split(':', 5)
        kind, _, ident = (parts[5] if len(parts) == 6 else '').partition('/')
        if kind != 'guardrail' or not ident:
            raise errors.validation('guardrailIdentifier is not a guardrail ARN')
        return ident
    return value


def parse_version(value):
    if not isinstance(value, str) or not value:
        raise errors.validation('guardrailVersion is required (DRAFT or a version number)')
    try:
        return guardrails.parse_version(value)
    except Fault as exc:
        raise errors.validation(str(exc))


def _resolve(req, ident, version):
    """(version, stored guardrail) or ResourceNotFoundException."""
    try:
        return req.app.guardrail_version(req.principal, ident, version)
    except KeyError:
        raise errors.not_found(f'Guardrail {ident} version {version} was not found for this tenant')


# ---- assessments ------------------------------------------------------------------------

def _hits(pattern, check, texts):
    seen = []
    for text in texts:
        for m in re.finditer(pattern, text):
            value = m.group(0)
            if (check is None or check(value)) and value not in seen:
                seen.append(value)
    return seen[:MATCH_CAP]


def _units(section, chars):
    n = max(1, math.ceil(chars / 1000)) if chars else 0
    content = any(v != 'NONE' for v in (section.get('strengths') or {}).values() if v) or section.get('classifier_categories') or section.get('detect_injection')
    grounded = (section.get('strengths') or {}).get('grounding') not in (None, 'NONE') or section.get('grounding_threshold')
    return {'topicPolicyUnits': n if section.get('blocked_topics') else 0, 'contentPolicyUnits': n if content else 0,
            'wordPolicyUnits': n if section.get('word_filters') else 0, 'sensitiveInformationPolicyUnits': n if section.get('pii_entities') else 0,
            'sensitiveInformationPolicyFreeUnits': n if section.get('regex_filters') else 0, 'contextualGroundingPolicyUnits': n if grounded else 0}


def _content_filters(section, found, full):
    strengths = section.get('strengths') or {}
    configured = {c for c, v in strengths.items() if c != 'grounding' and v not in (None, 'NONE')} | \
        {c for c in section.get('classifier_categories', []) if strengths.get(c) != 'NONE'}
    if section.get('detect_injection') and 'prompt_attack' not in configured:
        configured.add('prompt_attack')
    threshold = section.get('classifier_threshold', .5)

    def level(category):
        if category == 'prompt_attack':  # a deterministic pattern match: certain, whatever the configured strength
            return strengths.get(category) if strengths.get(category) in ('LOW', 'MEDIUM', 'HIGH') else 'HIGH', 'HIGH'
        if strengths.get(category) in ('LOW', 'MEDIUM', 'HIGH'):
            return strengths[category], _bucket(CONFIDENCE_OF_THRESHOLD, guardrails.CLASSIFIER_CONFIDENCE[strengths[category]])
        return _bucket(STRENGTH_OF_THRESHOLD, threshold), _bucket(CONFIDENCE_OF_THRESHOLD, threshold)

    out, unmapped = [], []
    detected = {f['match'] for f in found if f['code'] in ('CONTENT_FILTER', 'PROMPT_ATTACK')}
    for category in sorted(detected):
        if category not in FILTER_TYPES:
            unmapped.append(f'content filter {category} has no Amazon Bedrock filter type')
            continue
        strength, confidence = level(category)
        out.append({'type': FILTER_TYPES[category], 'confidence': confidence, 'filterStrength': strength, 'action': 'BLOCKED', 'detected': True})
    if full:
        for category in sorted(configured - detected):
            if category in FILTER_TYPES:
                out.append({'type': FILTER_TYPES[category], 'confidence': 'NONE', 'filterStrength': level(category)[0], 'action': 'NONE', 'detected': False})
    return out, unmapped


def build_assessment(findings, section, texts, sources=(), full=False, latency_ms=0, total_chars=None):
    """One Bedrock GuardrailAssessment for the merged findings of the guarded `texts`. Returns (assessment, unmapped notes)."""
    topics = [{'name': f['match'], 'type': 'DENY', 'action': 'BLOCKED', 'detected': True} for f in findings if f['code'] == 'DENIED_TOPIC']
    topics = [t for n, t in enumerate(topics) if t['name'] not in {x['name'] for x in topics[:n]}]
    if full:
        topics += [{'name': t, 'type': 'DENY', 'action': 'NONE', 'detected': False} for t in section.get('blocked_topics', []) if t not in {x['name'] for x in topics}]
    words = [{'match': f['match'], 'action': 'BLOCKED', 'detected': True} for f in findings if f['code'] == 'BLOCKED_WORD']
    if full:
        words += [{'match': w, 'action': 'NONE', 'detected': False} for w in section.get('word_filters', []) if w not in {x['match'] for x in words}]
    filters, unmapped = _content_filters(section, findings, full)
    pii, regexes = [], []
    for f in findings:
        if f['code'] in ('PII_BLOCKED', 'PII_ANONYMIZED'):
            pattern, check, label = PII[f['match']]
            action = 'BLOCKED' if f['code'] == 'PII_BLOCKED' else 'ANONYMIZED'
            for value in _hits(pattern, check, texts) or [label]:
                pii.append({'match': value, 'type': PII_TYPES[f['match']], 'action': action, 'detected': True})
        elif f['code'] == 'REGEX_BLOCKED':
            spec = next((r for r in section.get('regex_filters', []) if r['name'] == f['match']), None)
            hit = _hits(spec['pattern'], None, texts) if spec else []
            regexes.append({'name': f['match'], 'match': hit[0] if hit else '', 'regex': spec['pattern'] if spec else '', 'action': 'BLOCKED', 'detected': True})
        elif f['code'] == 'REGEX_ANONYMIZED':
            for spec in section.get('regex_filters', []):
                hit = _hits(spec['pattern'], None, texts) if spec.get('action', 'block') == 'mask' else []
                if hit:
                    regexes.append({'name': spec['name'], 'match': hit[0], 'regex': spec['pattern'], 'action': 'ANONYMIZED', 'detected': True})
    if full:
        listed = {(p['type']) for p in pii}
        pii += [{'match': PII[n][2], 'type': PII_TYPES[n], 'action': 'NONE', 'detected': False} for n in (section.get('pii_entities') or {}) if PII_TYPES[n] not in listed]
        named = {r['name'] for r in regexes}
        regexes += [{'name': r['name'], 'match': '', 'regex': r['pattern'], 'action': 'NONE', 'detected': False} for r in section.get('regex_filters', []) if r['name'] not in named]
    grounding = []
    wanted = (section.get('strengths') or {}).get('grounding')
    threshold = guardrails.GROUNDING_SCORE.get(wanted) if wanted in guardrails.GROUNDING_SCORE else section.get('grounding_threshold')
    hit = any(f['code'] == 'GROUNDING' for f in findings)
    if threshold and sources and (hit or full):
        score = min(grounding_score(t, list(sources)) for t in texts)
        grounding.append({'type': 'GROUNDING', 'threshold': threshold, 'score': score, 'action': 'BLOCKED' if hit else 'NONE', 'detected': hit})
    elif hit:
        grounding.append({'type': 'GROUNDING', 'threshold': threshold or 0, 'score': 0.0, 'action': 'BLOCKED', 'detected': True})
    for f in findings:
        if f['code'] == 'MAX_CHARS':
            unmapped.append('content exceeded the guardrail max_chars limit, which Amazon Bedrock has no policy for')
        elif f['code'] == 'OTHER':
            unmapped.append('unclassified Nuvora finding: ' + str(f['match'])[:100])
    assessment = {}
    if topics:
        assessment['topicPolicy'] = {'topics': topics}
    if filters:
        assessment['contentPolicy'] = {'filters': filters}
    if words:
        assessment['wordPolicy'] = {'customWords': words, 'managedWordLists': []}
    if pii or regexes:
        assessment['sensitiveInformationPolicy'] = {'piiEntities': pii, 'regexes': regexes}
    if grounding:
        assessment['contextualGroundingPolicy'] = {'filters': grounding}
    chars = sum(len(t) for t in texts)
    assessment['invocationMetrics'] = {'guardrailProcessingLatency': int(latency_ms), 'usage': _full_usage(section, chars),
                                       'guardrailCoverage': {'textCharacters': {'guarded': chars, 'total': total_chars if total_chars is not None else chars}}}
    assessment['nuvora'] = {'findings': findings}
    return assessment, unmapped


def _full_usage(section, chars):
    return {**_units(section, chars), 'contentPolicyImageUnits': 0, 'automatedReasoningPolicyUnits': 0, 'automatedReasoningPolicies': 0}


def _reason(action, findings, unmapped):
    if action == 'NONE':
        return None
    blocked = any(f['action'] == 'BLOCKED' for f in findings)
    text = 'Guardrail blocked.' if blocked else 'Guardrail anonymized sensitive information.'
    if unmapped:
        text += ' Not expressible as a Bedrock assessment entry: ' + '; '.join(sorted(set(unmapped))) + '.'
    return text


# ---- ApplyGuardrail ---------------------------------------------------------------------

def _content(blocks):
    """(guarded texts, grounding sources, total characters). Qualifiers are honoured or refused."""
    if not isinstance(blocks, list) or not blocks:
        raise errors.validation('content must be a non-empty list')
    guarded, sources, total = [], [], 0
    for n, block in enumerate(blocks):
        if not isinstance(block, dict) or set(block) != {'text'}:
            raise errors.validation(f'content[{n}]: only text blocks are supported (image is not)')
        spec = block['text']
        if not isinstance(spec, dict) or not isinstance(spec.get('text'), str) or set(spec) - {'text', 'qualifiers'}:
            raise errors.validation(f'content[{n}].text must be {{"text": ..., "qualifiers": [...]}}')
        qualifiers = spec.get('qualifiers') or []
        if not isinstance(qualifiers, list) or len(set(qualifiers)) != len(qualifiers):
            raise errors.validation(f'content[{n}].text.qualifiers must be a list without repeats')
        if 'query' in qualifiers:
            raise errors.validation(f'content[{n}]: the query qualifier is not supported (Nuvora has no contextual relevance check)')
        if set(qualifiers) - {'grounding_source', 'guard_content'}:
            raise errors.validation(f'content[{n}]: unknown qualifier')
        if set(qualifiers) == {'grounding_source', 'guard_content'}:
            raise errors.validation(f'content[{n}]: grounding_source and guard_content cannot be combined')
        total += len(spec['text'])
        (sources if qualifiers == ['grounding_source'] else guarded).append(spec['text'])
    if not guarded:
        raise errors.validation('content needs at least one text block to guard (guard_content or unqualified)')
    return guarded, sources, total


def apply_guardrail(req):
    require(req.principal, 'developer', 'admin')
    body = req.json()
    unknown = sorted(set(body) - {'source', 'content', 'outputScope'})
    if unknown:
        raise errors.validation('request: unsupported field ' + ', '.join(unknown))
    source = body.get('source')
    if source not in guardrails.SOURCES:
        raise errors.validation('source must be INPUT or OUTPUT')
    scope = body.get('outputScope', 'INTERVENTIONS')
    if scope not in ('INTERVENTIONS', 'FULL'):
        raise errors.validation('outputScope must be INTERVENTIONS or FULL')
    ident, version = parse_identifier(req.params['guardrailIdentifier']), parse_version(req.params['guardrailVersion'])
    texts, sources, total = _content(body.get('content'))
    if sources and source != 'OUTPUT':
        raise errors.validation('grounding_source content applies to OUTPUT only')
    number, item = _resolve(req, ident, version)
    started = time.monotonic()
    result = req.app.apply_guardrail(req.principal, ident, number, source, texts, sources or None)
    findings = [f for a in result['assessments'] for f in a['findings']]
    section = item.get('input' if source == 'INPUT' else 'output') or {}
    assessment, unmapped = build_assessment(findings, section, texts, sources, scope == 'FULL', (time.monotonic() - started) * 1000, total)
    action = result['action']
    payload = {'action': action, 'outputs': result['outputs'], 'assessments': [assessment],
               'usage': assessment['invocationMetrics']['usage'], 'guardrailCoverage': assessment['invocationMetrics']['guardrailCoverage']}
    reason = _reason(action, findings, unmapped)
    if reason:
        payload['actionReason'] = reason
    return Response(payload, headers={'X-Nuvora-Guardrail-Units': UNITS_LABEL})


# ---- the guardrail carried by Converse / InvokeModel ------------------------------------

class Use:
    """A request's guardrail: resolved once so refusals can be told apart and traced."""

    def __init__(self, req, ident, version, trace, async_mode=False):
        self.req, self.trace, self.async_mode = req, trace, async_mode
        self.number, self.item = _resolve(req, ident, version)
        self.id = ident
        self.resolved = req.app.guardrail(req.principal, {'id': ident, 'version': self.number})
        self.messages = (self.resolved['input']['_message'], self.resolved['output']['_message'])

    @property
    def ref(self):
        return {'id': self.id, 'version': self.number}

    @property
    def tracing(self):
        return self.trace != 'disabled'

    def refusal_text(self, exc):
        """The text a guardrail refusal is reported with, or None when `exc` is not one."""
        if getattr(exc, 'status', 0) != 422:
            return None
        message = str(exc)
        if message in self.messages:
            return message
        if 'refused by guardrail' in message:
            return self.messages[1]
        return None

    def trace_block(self, texts):
        """GuardrailTraceAssessment for a refusal. The input side is re-evaluated from the request text (so a
        classifier is asked again); the output side cannot be, because the blocked model output is not kept."""
        full = self.trace == 'enabled_full'
        started = time.monotonic()
        findings, input_hit = [], False
        policy = self.resolved['input']
        for text in texts:
            verdict = self.req.app.check(self.req.principal, text, policy)
            found = guardrails.findings(verdict, text)
            findings += [f for f in found if f['action'] == 'BLOCKED']
            input_hit = input_hit or not verdict['allowed']
        if input_hit:
            assessment, unmapped = build_assessment(findings, self.item.get('input') or {}, texts, (), full, (time.monotonic() - started) * 1000)
            reason = _reason('GUARDRAIL_INTERVENED', findings, unmapped)
            return {'inputAssessment': {self.id: assessment}, 'actionReason': reason}
        return {'outputAssessments': {self.id: []},
                'actionReason': 'Guardrail blocked the model output. Nuvora does not keep blocked output, so there is no per-policy assessment or modelOutput.'}


def config_from_converse(req, config, streaming):
    """A Use from Converse's `guardrailConfig`, or None when absent/empty."""
    if config in (None, {}):
        return None
    allowed = ('guardrailIdentifier', 'guardrailVersion', 'trace') + (('streamProcessingMode',) if streaming else ())
    if not isinstance(config, dict) or set(config) - set(allowed):
        extra = sorted(set(config) - set(allowed)) if isinstance(config, dict) else ['guardrailConfig']
        raise errors.validation('guardrailConfig: unsupported field ' + ', '.join(extra))
    trace = config.get('trace', 'disabled')
    if trace not in TRACE_VALUES:
        raise errors.validation('guardrailConfig.trace must be enabled, disabled or enabled_full')
    mode = config.get('streamProcessingMode', 'sync')
    if mode not in ('sync', 'async'):
        raise errors.validation('guardrailConfig.streamProcessingMode must be sync or async')
    return Use(req, parse_identifier(config.get('guardrailIdentifier')), parse_version(config.get('guardrailVersion')), trace, mode == 'async')


def config_from_headers(req):
    """A Use from the InvokeModel guardrail headers, or None. A trace header without a guardrail is refused."""
    h = req.handler.headers
    ident, version, trace = h.get('X-Amzn-Bedrock-GuardrailIdentifier'), h.get('X-Amzn-Bedrock-GuardrailVersion'), h.get('X-Amzn-Bedrock-Trace')
    if trace is not None and trace.lower() not in TRACE_VALUES:
        raise errors.validation('The X-Amzn-Bedrock-Trace header must be ENABLED, DISABLED or ENABLED_FULL')
    if not ident and not version:
        if trace and trace.lower() != 'disabled':
            raise errors.validation('The X-Amzn-Bedrock-Trace header is only supported together with a guardrail')
        return None
    if not (ident and version):
        raise errors.validation('X-Amzn-Bedrock-GuardrailIdentifier and X-Amzn-Bedrock-GuardrailVersion must be sent together')
    return Use(req, parse_identifier(ident), parse_version(version), (trace or 'disabled').lower())


def chat_texts(chat):
    """Every string the input guardrail looks at in an internal chat body: message text and tool-call arguments."""
    out = []
    for m in chat.get('messages', []):
        content = m.get('content')
        if isinstance(content, str):
            out.append(content)
        elif isinstance(content, list):
            out += [p['text'] for p in content if p.get('type') == 'text']
        out += [c['function']['arguments'] for c in m.get('tool_calls', [])]
    return [t for t in out if t]
