# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Guardrail resources: validation of the INPUT/OUTPUT sections, strengths, and compilation to a guard() policy.

A section is the same shape as a tenant policy's guard fields (see security.validate_policy) plus
`strengths`, a per-filter level that is mapped onto the existing thresholds:

    level   classifier confidence needed to flag   grounding score required
    HIGH    0.3 (flags the most)                   0.8
    MEDIUM  0.5                                    0.6
    LOW     0.8 (flags the least)                  0.4
    NONE    filter off                             filter off

Content filters are the classifier categories (hate, violence, sexual, self_harm, misconduct,
prompt_attack). `prompt_attack` also switches the deterministic instruction-override detector
(input only); the other categories need a `classifier_model`. `grounding` sets the contextual
grounding threshold. Nothing here is a formal guarantee: the engine is deterministic rules plus an
optional model-based classifier.
"""
import re

from .security import CLASSIFIER_CATEGORIES, Fault, validate_policy

STRENGTHS = ('NONE', 'LOW', 'MEDIUM', 'HIGH')
CLASSIFIER_CONFIDENCE = {'HIGH': .3, 'MEDIUM': .5, 'LOW': .8}
GROUNDING_SCORE = {'HIGH': .8, 'MEDIUM': .6, 'LOW': .4}
SECTION_KEYS = {'blocked_topics', 'word_filters', 'regex_filters', 'pii_entities', 'detect_injection', 'max_chars', 'grounding_threshold',
                'classifier_model', 'classifier_categories', 'classifier_threshold', 'strengths'}
DEFAULT_INPUT_MESSAGE = 'Sorry, the model cannot answer this question.'
DEFAULT_OUTPUT_MESSAGE = 'Sorry, the model cannot answer this question.'
SOURCES = ('INPUT', 'OUTPUT')


def validate_section(section, direction):
    """Validate one section; returns it normalised. Classifier model existence is checked by the caller."""
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise Fault(direction + ' policy must be an object')
    unknown = set(section) - SECTION_KEYS
    if unknown:
        raise Fault('Unknown ' + direction + ' policy fields: ' + ', '.join(sorted(unknown)))
    topics = section.get('blocked_topics', [])
    if not isinstance(topics, list) or len(topics) > 100 or any(not isinstance(x, str) or not 1 <= len(x) <= 100 for x in topics):
        raise Fault('blocked_topics must be up to 100 strings of 1–100 characters')
    if not isinstance(section.get('detect_injection', False), bool):
        raise Fault('detect_injection must be true or false')
    mc = section.get('max_chars')
    if mc is not None and (not isinstance(mc, int) or isinstance(mc, bool) or not 100 <= mc <= 500000):
        raise Fault('max_chars must be an integer between 100 and 500000')
    validate_policy(section)
    strengths = section.get('strengths', {})
    allowed = set(CLASSIFIER_CATEGORIES) | {'grounding'}
    if not isinstance(strengths, dict) or set(strengths) - allowed or any(v not in STRENGTHS for v in strengths.values()):
        raise Fault('strengths maps ' + ', '.join(sorted(allowed)) + ' to ' + ', '.join(STRENGTHS))
    active = {k for k, v in strengths.items() if v != 'NONE'}
    if direction == 'OUTPUT' and ('prompt_attack' in active or section.get('detect_injection')):
        raise Fault('Prompt-attack detection applies to input only')
    if 'grounding' in active and section.get('grounding_threshold') is not None:
        raise Fault('Set either strengths.grounding or grounding_threshold, not both')
    needs_model = (active & set(CLASSIFIER_CATEGORIES)) - {'prompt_attack'} or section.get('classifier_categories')
    if needs_model and not section.get('classifier_model'):
        raise Fault('Content filters need a classifier_model')
    if section.get('classifier_model') and not (active & set(CLASSIFIER_CATEGORIES) or section.get('classifier_categories')):
        raise Fault('Choose at least one content filter for the classifier model')
    if set(section.get('classifier_categories', [])) & {c for c, v in strengths.items() if v == 'NONE'}:
        raise Fault('A category cannot be both listed and strength NONE')
    return section


def compile_section(section, source, message, tag):
    """Turn a stored section into the policy dict that security.guard() and Platform.check() understand."""
    strengths = section.get('strengths', {})
    categories = [c for c in CLASSIFIER_CATEGORIES if (strengths.get(c) not in (None, 'NONE')) or (c in section.get('classifier_categories', []) and strengths.get(c) != 'NONE')]
    policy = {
        'blocked_topics': section.get('blocked_topics', []),
        'word_filters': section.get('word_filters', []),
        'regex_filters': section.get('regex_filters', []),
        # An absent pii_entities would fall back to the tenant-wide legacy redaction; a guardrail only does what it states.
        'pii_entities': section.get('pii_entities') or {},
        'max_chars': section.get('max_chars', 100000),
        'detect_injection': bool(section.get('detect_injection', False)) or strengths.get('prompt_attack') not in (None, 'NONE') and source == 'INPUT',
        '_message': message, '_guardrail': tag,
    }
    if section.get('classifier_model') and categories:
        policy['classifier_model'] = section['classifier_model']
        policy['classifier_categories'] = categories
        policy['classifier_threshold'] = section.get('classifier_threshold', .5)
        policy['classifier_thresholds'] = {c: CLASSIFIER_CONFIDENCE[strengths[c]] for c in categories if strengths.get(c) in CLASSIFIER_CONFIDENCE}
    if strengths.get('grounding') in GROUNDING_SCORE:
        policy['grounding_threshold'] = GROUNDING_SCORE[strengths['grounding']]
    elif section.get('grounding_threshold'):
        policy['grounding_threshold'] = section['grounding_threshold']
    return policy


def parse_version(value):
    """DRAFT or a positive whole number (int or digit string)."""
    if value is None or value == 'DRAFT':
        return 'DRAFT'
    if isinstance(value, bool) or not (isinstance(value, int) or (isinstance(value, str) and re.fullmatch(r'[0-9]{1,9}', value))) or int(value) < 1:
        raise Fault('version must be DRAFT or a version number')
    return int(value)


def findings(verdict, original):
    """Group a guard()/check() verdict's reasons into policy findings with reason codes."""
    out = []
    for reason in verdict['reasons']:
        head, _, detail = reason.partition(': ')
        if head == 'Denied topic':
            out.append({'policy': 'topic_policy', 'code': 'DENIED_TOPIC', 'action': 'BLOCKED', 'match': detail})
        elif head == 'Blocked word':
            out.append({'policy': 'word_policy', 'code': 'BLOCKED_WORD', 'action': 'BLOCKED', 'match': detail})
        elif head == 'Matched filter':
            out.append({'policy': 'regex_policy', 'code': 'REGEX_BLOCKED', 'action': 'BLOCKED', 'match': detail})
        elif head == 'Sensitive information':
            out.append({'policy': 'sensitive_information_policy', 'code': 'PII_BLOCKED', 'action': 'BLOCKED', 'match': detail})
        elif head == 'Classifier':
            out.append({'policy': 'content_policy', 'code': 'CONTENT_FILTER', 'action': 'BLOCKED', 'match': detail})
        elif head.startswith('Instruction override'):
            out.append({'policy': 'content_policy', 'code': 'PROMPT_ATTACK', 'action': 'BLOCKED', 'match': 'prompt_attack'})
        elif head.startswith('Answer not grounded'):
            out.append({'policy': 'contextual_grounding_policy', 'code': 'GROUNDING', 'action': 'BLOCKED', 'match': 'grounding'})
        elif head.startswith('Content size'):
            out.append({'policy': 'size_policy', 'code': 'MAX_CHARS', 'action': 'BLOCKED', 'match': 'max_chars'})
        else:
            out.append({'policy': 'other', 'code': 'OTHER', 'action': 'BLOCKED', 'match': reason})
    blocked = {f['match'] for f in out if f['code'] == 'PII_BLOCKED'}
    for name in verdict.get('pii_found', []):
        if name not in blocked:
            out.append({'policy': 'sensitive_information_policy', 'code': 'PII_ANONYMIZED', 'action': 'ANONYMIZED', 'match': name})
    if verdict['text'] != original and not any(f['action'] == 'ANONYMIZED' for f in out):
        out.append({'policy': 'regex_policy', 'code': 'REGEX_ANONYMIZED', 'action': 'ANONYMIZED', 'match': ''})
    return out
