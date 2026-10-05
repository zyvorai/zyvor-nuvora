# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""OpenTelemetry trace export over OTLP/HTTP JSON. Spans carry ids, types, models, tools and
costs, never prompt or answer text. Set NUVORA_OTEL_ENDPOINT, e.g. http://collector:4318/v1/traces."""
import hashlib
import json
import logging
import os
import threading
import urllib.request

from . import __version__

log = logging.getLogger('nuvora.telemetry')


def _attr(key, value):
    if isinstance(value, bool):
        return {'key': key, 'value': {'boolValue': value}}
    if isinstance(value, int):
        return {'key': key, 'value': {'intValue': str(value)}}
    if isinstance(value, float):
        return {'key': key, 'value': {'doubleValue': value}}
    return {'key': key, 'value': {'stringValue': str(value)[:256]}}


def _nanos(t):
    return str(int(t * 1e9))


def spans(job, tenant):
    """Root span for the run plus one child per timed trace entry."""
    trace_id = hashlib.sha256(f"{tenant}:{job['id']}".encode()).hexdigest()[:32]
    root_id = trace_id[:16]
    start = job.get('started') or job.get('created') or 0
    end = job.get('finished') or job.get('updated') or start
    failed = job.get('status') in ('failed', 'interrupted', 'rejected')
    out = [{'traceId': trace_id, 'spanId': root_id, 'name': f"{job.get('type', 'job')} run", 'kind': 1,
            'startTimeUnixNano': _nanos(start), 'endTimeUnixNano': _nanos(max(end, start)),
            'attributes': [_attr('nuvora.tenant', tenant), _attr('nuvora.job.id', job['id']), _attr('nuvora.job.type', job.get('type', '')),
                           _attr('nuvora.job.status', job.get('status', ''))],
            'status': {'code': 2 if failed else 1}}]
    for i, entry in enumerate(job.get('trace', [])):
        if 'start' not in entry:
            continue
        name = entry.get('tool') or entry.get('model') or entry.get('type', 'step')
        attrs = [_attr('nuvora.step', entry.get('step', i)), _attr('nuvora.step.type', entry.get('type', ''))]
        for key in ('model', 'tool', 'cost', 'evidence_class', 'status'):
            if key in entry:
                attrs.append(_attr('nuvora.' + key, entry[key]))
        out.append({'traceId': trace_id, 'spanId': hashlib.sha256(f'{trace_id}:{i}'.encode()).hexdigest()[:16], 'parentSpanId': root_id,
                    'name': f"{entry.get('type', 'step')} {name}", 'kind': 1,
                    'startTimeUnixNano': _nanos(entry['start']), 'endTimeUnixNano': _nanos(entry.get('end', entry['start'])),
                    'attributes': attrs, 'status': {'code': 2 if entry.get('error') else 1}})
    return out


def payload(job, tenant):
    return {'resourceSpans': [{'resource': {'attributes': [_attr('service.name', 'nuvora'), _attr('service.version', __version__)]},
                               'scopeSpans': [{'scope': {'name': 'nuvora', 'version': __version__}, 'spans': spans(job, tenant)}]}]}


def export(job, tenant, endpoint=None, wait=False):
    endpoint = endpoint or os.getenv('NUVORA_OTEL_ENDPOINT', '')
    if not endpoint:
        return None
    body = json.dumps(payload(job, tenant)).encode()

    def send():
        try:
            request = urllib.request.Request(endpoint, body, {'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=5) as response:
                response.read(65536)
        except Exception as exc:  # telemetry must never break a run
            log.warning('OTLP export failed: %s', exc.__class__.__name__)

    thread = threading.Thread(target=send, daemon=True)
    thread.start()
    if wait:
        thread.join(6)
    return thread
