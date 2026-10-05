# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Training dataset validation for JSONL in chat, completion or prompts-only format."""
import json

from .security import Fault, guard

FORMATS = ('chat', 'completion', 'prompts')
MAX_RECORDS = 100000
MIN_RECORDS = 10
MAX_BYTES = 20*1024*1024
ROLES = ('system', 'user', 'assistant')


def record_format(item):
    if isinstance(item, dict) and isinstance(item.get('messages'), list):
        return 'chat'
    if isinstance(item, dict) and isinstance(item.get('prompt'), str) and 'completion' in item:
        return 'completion'
    if isinstance(item, dict) and isinstance(item.get('prompt'), str):
        return 'prompts'
    return None


def check(item, fmt):
    if fmt == 'chat':
        msgs = item['messages']
        if not 2 <= len(msgs) <= 100 or any(not isinstance(m, dict) or m.get('role') not in ROLES or not isinstance(m.get('content'), str) or not m['content'].strip() for m in msgs):
            return 'messages need 2–100 entries with a system, user or assistant role and non-empty text'
        if not any(m['role'] == 'user' for m in msgs) or msgs[-1]['role'] != 'assistant':
            return 'a chat example needs a user turn and must end with the assistant answer'
    elif fmt == 'completion':
        if not item['prompt'].strip() or not isinstance(item['completion'], str) or not item['completion'].strip():
            return 'prompt and completion must be non-empty strings'
    elif not item['prompt'].strip():
        return 'prompt must be a non-empty string'
    return None


def validate(text, policy):
    """Return (stats, cleaned_jsonl). Raises Fault 422 listing the first problems."""
    if not isinstance(text, str) or not text.strip():
        raise Fault('The dataset is empty', 422)
    if len(text.encode()) > MAX_BYTES:
        raise Fault('Datasets are limited to 20 MiB', 413)
    fmt, errors, out, redacted, chars = None, [], [], 0, 0
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if len(out) >= MAX_RECORDS:
            raise Fault(f'Datasets are limited to {MAX_RECORDS} records', 413)
        try:
            item = json.loads(line)
        except ValueError:
            errors.append(f'line {number}: not valid JSON')
            continue
        kind = record_format(item)
        if kind is None:
            errors.append(f'line {number}: expected {{"messages": [...]}}, {{"prompt", "completion"}} or {{"prompt"}}')
            continue
        fmt = fmt or kind
        if kind != fmt:
            errors.append(f'line {number}: {kind} record in a {fmt} dataset')
            continue
        problem = check(item, fmt)
        if problem:
            errors.append(f'line {number}: {problem}')
            continue
        verdict = guard(json.dumps(item, ensure_ascii=False), {**policy, 'max_chars': 10**9})
        if not verdict['allowed']:
            errors.append(f'line {number}: refused by guardrail ('+'; '.join(verdict['reasons'])[:200]+')')
            continue
        redacted += bool(verdict.get('pii_redacted'))
        cleaned = verdict['text']
        chars += len(cleaned)
        out.append(cleaned)
        if len(errors) >= 20:
            break
    if errors:
        raise Fault(f'{len(errors)} invalid record(s): '+'; '.join(errors[:5]), 422)
    if len(out) < MIN_RECORDS:
        raise Fault(f'A dataset needs at least {MIN_RECORDS} records (found {len(out)})', 422)
    return {'format': fmt, 'records': len(out), 'estimated_tokens': chars//4, 'pii_redacted_records': redacted}, '\n'.join(out)+'\n'


def prompts(content, fmt):
    """Chat message lists to send a distillation teacher (the answer, if any, is dropped)."""
    out = []
    for line in content.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if fmt == 'chat':
            msgs = item['messages']
            out.append(msgs[:-1] if msgs[-1]['role'] == 'assistant' else msgs)
        else:
            out.append([{'role': 'user', 'content': item['prompt']}])
    return out
