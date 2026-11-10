# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Outbound webhooks for platform events. HMAC-SHA256 signed, with optional Slack/Teams shapes."""
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from .security import Fault

EVENTS = (
    'job.completed', 'job.failed',
    'approval.created', 'approval.decided',
    'document.ingested', 'connector.synced', 'guardrail.blocked',
)
FORMATS = ('generic', 'slack', 'teams', 'email')


def validate(spec):
    if not isinstance(spec, dict):
        raise Fault('Webhook must be an object')
    fmt = spec.get('format', 'generic')
    if fmt not in FORMATS:
        raise Fault(f'format must be one of {FORMATS}')
    events = spec.get('events', [])
    if not isinstance(events, list) or not events or any(e not in EVENTS for e in events):
        raise Fault(f'events must be non-empty list of {EVENTS}')
    secret = spec.get('secret', '')
    if not isinstance(secret, str) or len(secret) < 16:
        raise Fault('secret must be ≥16 chars (for HMAC)')
    retries = spec.get('max_retries', 2)
    if not isinstance(retries, int) or not 0 <= retries <= 5:
        raise Fault('max_retries must be 0–5')
    out = {'events': list(events), 'secret': secret, 'enabled': bool(spec.get('enabled', True)),
           'format': fmt, 'max_retries': retries}
    if fmt == 'email':
        to = spec.get('to') or spec.get('url', '')
        if isinstance(to, str) and to.startswith('mailto:'):
            to = to[7:]
        if not isinstance(to, str) or '@' not in to or len(to) > 200:
            raise Fault('email webhooks need a to address')
        out['to'] = to
        out['url'] = 'mailto:' + to
    else:
        url = spec.get('url', '')
        if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
            raise Fault('url must be http(s)')
        out['url'] = url
    for key in ('last_status', 'last_delivery', 'failures'):
        if key in spec:
            out[key] = spec[key]
    return out


def sign(secret, payload):
    body = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(), body


def shape(fmt, event, data, at):
    """Build the outbound JSON object for a format."""
    generic = {'event': event, 'at': at, 'data': data}
    if fmt == 'generic':
        return generic
    text = f"Nuvora {event}: {json.dumps(data, sort_keys=True)[:500]}"
    if fmt == 'slack':
        return {'text': text, 'nuvora': generic}
    if fmt == 'teams':
        return {'@type': 'MessageCard', '@context': 'https://schema.org/extensions', 'summary': event,
                'themeColor': '0078D7' if 'failed' not in event and 'blocked' not in event else 'D13438',
                'title': 'Nuvora · ' + event, 'text': text, 'nuvora': generic}
    return generic


def deliver(webhook, event, data, timeout=10):
    """POST (or email) with retries. Returns status code or 'email' or None."""
    if not webhook.get('enabled') or event not in webhook.get('events', []):
        return None
    at = time.time()
    payload = shape(webhook.get('format', 'generic'), event, data, at)
    if webhook.get('format') == 'email':
        from . import notify_email
        ok = notify_email.send(webhook.get('to'), f'Nuvora {event}', json.dumps(payload, indent=2))
        return 'email' if ok else None
    sig, body = sign(webhook['secret'], payload)
    attempts = 1 + max(0, int(webhook.get('max_retries', 2) or 0))
    for attempt in range(attempts):
        req = urllib.request.Request(
            webhook['url'], data=body, method='POST',
            headers={'Content-Type': 'application/json', 'X-Nuvora-Signature': 'sha256=' + sig,
                     'User-Agent': 'NuvoraWebhook/0.4', 'X-Nuvora-Event': event})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status
        except Exception:
            if attempt + 1 < attempts:
                time.sleep(min(0.5 * (2 ** attempt), 4.0))
    return None
