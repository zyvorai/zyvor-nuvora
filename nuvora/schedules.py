# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Scheduled agent runs. Interval (minutes) or a 5-field cron expression."""
import time
from .security import Fault

CRON_RE = __import__('re').compile(r'^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$')


def _parse_field(field, minimum, maximum):
    """Expand a cron field into a sorted set of integers. Supports *, */n, a-b, a,b and a-b/n."""
    values = set()
    for part in field.split(','):
        part = part.strip()
        if not part:
            raise Fault('empty cron field')
        step = 1
        if '/' in part:
            base, step_s = part.split('/', 1)
            if not step_s.isdigit() or int(step_s) < 1:
                raise Fault('invalid cron step')
            step = int(step_s)
            part = base or '*'
        if part == '*':
            start, end = minimum, maximum
        elif '-' in part:
            a, b = part.split('-', 1)
            if not a.isdigit() or not b.isdigit():
                raise Fault('invalid cron range')
            start, end = int(a), int(b)
        elif part.isdigit():
            start = end = int(part)
        else:
            raise Fault('invalid cron field')
        if not minimum <= start <= end <= maximum:
            raise Fault(f'cron values must be {minimum}–{maximum}')
        values.update(range(start, end + 1, step))
    return frozenset(values)


def parse_cron(expr):
    """Return (minute, hour, dom, month, dow) sets for a 5-field cron expression."""
    if not isinstance(expr, str):
        raise Fault('cron must be a string')
    match = CRON_RE.match(expr.strip())
    if not match:
        raise Fault('cron must have 5 fields: minute hour day-of-month month day-of-week')
    minute, hour, dom, month, dow = match.groups()
    return (
        _parse_field(minute, 0, 59),
        _parse_field(hour, 0, 23),
        _parse_field(dom, 1, 31),
        _parse_field(month, 1, 12),
        _parse_field(dow, 0, 6),  # 0 = Sunday
    )


def cron_matches(expr, when=None):
    when = time.gmtime(when if when is not None else time.time())
    minute, hour, dom, month, dow = parse_cron(expr)
    # Python tm_wday: Monday=0 … Sunday=6 → cron Sunday=0
    cron_dow = (when.tm_wday + 1) % 7
    return (when.tm_min in minute and when.tm_hour in hour and when.tm_mday in dom
            and when.tm_mon in month and cron_dow in dow)


def validate(spec):
    if not isinstance(spec, dict):
        raise Fault('Schedule must be an object')
    agent = spec.get('agent')
    if not isinstance(agent, str) or not agent:
        raise Fault('agent id required')
    prompt = spec.get('prompt', '')
    if not isinstance(prompt, str) or len(prompt) > 8000:
        raise Fault('prompt must be a string ≤8000 chars')
    cron = spec.get('cron')
    minutes = spec.get('every_minutes')
    out = {'agent': agent, 'prompt': prompt or 'Run the scheduled check.', 'enabled': bool(spec.get('enabled', True))}
    if cron is not None and cron != '':
        parse_cron(cron)  # validate
        out['cron'] = cron.strip()
        out.pop('every_minutes', None)
    elif minutes is not None:
        if not isinstance(minutes, (int, float)) or not 1 <= minutes <= 10080:
            raise Fault('every_minutes must be 1–10080')
        out['every_minutes'] = int(minutes)
        out.pop('cron', None)
    else:
        raise Fault('Provide every_minutes or cron')
    if 'last_run' in spec and isinstance(spec.get('last_run'), (int, float)):
        out['last_run'] = float(spec['last_run'])
    return out


def due(schedule, now=None):
    now = now if now is not None else time.time()
    last = schedule.get('last_run') or 0
    if schedule.get('cron'):
        # Fire at most once per matching minute, and not in the same minute as last_run.
        if int(now) // 60 == int(last) // 60:
            return False
        return cron_matches(schedule['cron'], now)
    return now - last >= schedule['every_minutes'] * 60
