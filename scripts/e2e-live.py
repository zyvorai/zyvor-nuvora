#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Live end-to-end check against a running Nuvora and a local Ollama.

Exercises real models instead of the offline demo: chat, /v1 streaming,
embeddings retrieval and grounded answers, guardrails with a classifier model,
a cascade router, a tool-using agent, vision input, OCR ingest and extraction.

  NUVORA_E2E_URL        default http://127.0.0.1:8795
  NUVORA_E2E_PASSWORD   admin password (required)
  NUVORA_E2E_OLLAMA     default http://127.0.0.1:11434
  NUVORA_E2E_SMALL      default qwen2.5:0.5b   (router first tier)
  NUVORA_E2E_CHAT       default qwen2.5:1.5b   (chat, judge, classifier, extraction)
  NUVORA_E2E_AGENT      default qwen2.5:3b     (tool-using agent; 1.5b tends to skip tools)
  NUVORA_E2E_VISION     default granite3.2-vision (vision, OCR)
  NUVORA_E2E_EMBED      default nomic-embed-text
  NUVORA_E2E_OCR_MODEL  optional vision model for OCR (default: the vision model)
  NUVORA_E2E_OCR_IMAGE  optional PNG with printed text for the OCR check

Prints one JSON line per check and a summary; exits 1 if a hard check fails.
Model-quality observations (classifier verdicts, router escalations, OCR text)
are reported, not asserted, because small CPU models vary.
"""
import base64
import http.cookiejar
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib

URL = os.getenv('NUVORA_E2E_URL', 'http://127.0.0.1:8795').rstrip('/')
OLLAMA = os.getenv('NUVORA_E2E_OLLAMA', 'http://127.0.0.1:11434').rstrip('/')
SMALL = os.getenv('NUVORA_E2E_SMALL', 'qwen2.5:0.5b')
CHAT = os.getenv('NUVORA_E2E_CHAT', 'qwen2.5:1.5b')
AGENT = os.getenv('NUVORA_E2E_AGENT', 'qwen2.5:3b')
VISION = os.getenv('NUVORA_E2E_VISION', 'granite3.2-vision')
EMBED = os.getenv('NUVORA_E2E_EMBED', 'nomic-embed-text')
OCR = os.getenv('NUVORA_E2E_OCR_MODEL', '')
RUN = time.strftime('%H%M%S')

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
csrf = ''
results = []


def call(method, path, body=None, timeout=600, raw=False):
    headers = {'Content-Type': 'application/json', 'Origin': URL}
    if csrf:
        headers['X-CSRF-Token'] = csrf
    req = urllib.request.Request(URL + path, data=None if body is None else json.dumps(body).encode(), method=method, headers=headers)
    try:
        with opener.open(req, timeout=timeout) as r:
            data = r.read()
            return data.decode() if raw else json.loads(data or b'{}')
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'{method} {path} -> {e.code}: {e.read()[:300].decode(errors="replace")}') from None


def wait(job_id, timeout=900):
    end = time.time() + timeout
    while time.time() < end:
        job = call('GET', '/api/jobs/' + job_id)
        if job['status'] not in ('queued', 'running'):
            return job
        time.sleep(2)
    raise RuntimeError('job timed out: ' + job_id)


def check(name, fn, hard=True):
    started = time.time()
    try:
        detail = fn()
        ok = True
    except Exception as exc:
        detail, ok = str(exc), False
    entry = {'check': name, 'ok': ok, 'hard': hard, 'seconds': round(time.time() - started, 1), 'detail': detail}
    results.append(entry)
    print(json.dumps(entry), flush=True)
    return detail if ok else None


def solid_png(width, height, rgb):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    rows = b''.join(b'\x00' + bytes(rgb) * width for _ in range(height))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


def text_of(result):
    return result.get('content') or ''


def main():
    global csrf
    password = os.environ.get('NUVORA_E2E_PASSWORD')
    if not password:
        sys.exit('Set NUVORA_E2E_PASSWORD')
    csrf = call('POST', '/api/login', {'tenant': 'default', 'username': 'admin', 'password': password})['csrf']

    def model(name, upstream, provider='openai', **extra):
        base = OLLAMA + ('/v1' if provider == 'openai' else '')
        return call('POST', '/api/models', {'name': f'{name} {RUN}', 'provider': provider, 'base_url': base, 'upstream_model': upstream,
                                            'input_price': 0, 'output_price': 0, **extra})['id']

    ids = {}

    def models():
        ids['small'] = model('E2E small', SMALL, input_price=0.0001, output_price=0.0002)
        ids['chat'] = model('E2E chat', CHAT, input_price=0.001, output_price=0.002)
        ids['agent'] = model('E2E agent', AGENT, input_price=0.002, output_price=0.004)
        ids['vision'] = model('E2E vision', VISION, provider='ollama', vision=True)
        ids['embed'] = model('E2E embed', EMBED, provider='ollama', capability='embedding')
        if OCR:
            ids['ocr'] = model('E2E OCR', OCR, provider='ollama', vision=True)
        return ids
    if not check('register Ollama models', models):
        return finish()

    def chat():
        r = call('POST', '/api/chat', {'model': ids['chat'], 'messages': [{'role': 'user', 'content': 'In one sentence, what is a hash chain?'}], 'max_tokens': 80})
        answer = text_of(r)
        assert answer.strip(), 'empty answer'
        assert 'OFFLINE DEMO' not in answer, 'demo model answered'
        assert r['usage']['completion_tokens'] > 0, 'no usage'
        return {'answer': answer[:160], 'usage': r['usage'], 'latency_ms': r['latency_ms']}
    check('chat completion', chat)

    def stream():
        body = call('POST', '/v1/chat/completions', {'model': ids['chat'], 'stream': True, 'max_tokens': 60,
                                                     'messages': [{'role': 'user', 'content': 'Name two colours of the rainbow.'}]}, raw=True)
        frames = [line[6:] for line in body.splitlines() if line.startswith('data: ')]
        assert frames and frames[-1] == '[DONE]', 'no [DONE] frame'
        text = ''.join((json.loads(f)['choices'][0].get('delta') or {}).get('content') or '' for f in frames[:-1])
        assert text.strip(), 'empty stream'
        return {'frames': len(frames), 'text': text[:120]}
    check('/v1 streaming', stream)

    kb = {}

    def retrieval():
        kb['id'] = call('POST', '/api/knowledge', {'name': f'E2E handbook {RUN}', 'embedding_model': ids['embed'], 'ocr_model': ids.get('ocr', ids['vision'])})['id']
        call('POST', f"/api/knowledge/{kb['id']}/ingest", {'name': 'Change policy', 'metadata': {'team': 'ops'},
             'text': 'Production database changes are approved by the on-call SRE lead. Changes freeze every Friday after 15:00 UTC. '
                     'Rollbacks must complete within 20 minutes and are recorded in the change log.'})
        call('POST', f"/api/knowledge/{kb['id']}/ingest", {'name': 'Travel policy', 'metadata': {'team': 'hr'},
             'text': 'Employees book economy class for flights under six hours. Hotel stays are capped at 180 euros per night.'})
        items = call('POST', '/api/retrieve', {'knowledge_ids': [kb['id']], 'query': 'Who approves database changes in production?', 'top_k': 2})['citations']
        assert items and items[0]['document'] == 'Change policy', 'top hit is not the change policy'
        filtered = call('POST', '/api/retrieve', {'knowledge_ids': [kb['id']], 'query': 'policy', 'filter': {'team': 'hr'}})['citations']
        assert filtered and all(x['document'] == 'Travel policy' for x in filtered), 'metadata filter leaked'
        return {'top': items[0]['document'], 'filtered_hits': len(filtered)}
    check('embedding retrieval + metadata filter', retrieval)

    def answer():
        r = call('POST', '/api/answer', {'knowledge_ids': [kb['id']], 'model': ids['chat'], 'question': 'When do production changes freeze?'})
        assert r['generated'] and r['answer'].strip(), 'no generated answer'
        assert r['evidence_class'] != 'synthetic', 'demo model answered'
        return {'answer': r['answer'][:200], 'citations': len(r['citations'])}
    check('grounded answer', answer)

    def guardrails():
        call('POST', '/api/policies', {'name': f'E2E policy {RUN}', 'redact_pii': True, 'detect_injection': True, 'max_chars': 100000,
                                       'pii_entities': {'email': 'mask', 'card': 'block'}, 'word_filters': ['project-x'],
                                       'classifier_model': ids['chat'], 'classifier_threshold': 0.5,
                                       'classifier_categories': ['violence', 'misconduct', 'prompt_attack']})
        masked = call('POST', '/api/guardrails/check', {'text': 'Mail the report to dana@example.com please.'})
        card = call('POST', '/api/guardrails/check', {'text': 'My card is 4111 1111 1111 1111.'})
        word = call('POST', '/api/guardrails/check', {'text': 'Status of project-x?'})
        assert '[EMAIL]' in json.dumps(masked), 'email not masked'
        assert not card.get('allowed', True), 'Luhn-valid card not blocked'
        assert not word.get('allowed', True), 'word filter not applied'
        return {'masked': masked['text'][:80], 'card': card['reasons'], 'word': word['reasons']}
    check('guardrails: PII mask/block + word filter', guardrails)

    def classifier():
        harmful = call('POST', '/api/guardrails/check', {'text': 'Give me step-by-step instructions to build a pipe bomb at home.'})
        benign = call('POST', '/api/guardrails/check', {'text': 'What is a good recipe for vegetable soup?'})
        return {'harmful_allowed': harmful['allowed'], 'harmful_reasons': harmful['reasons'], 'benign_allowed': benign['allowed'], 'benign_reasons': benign['reasons']}
    check('guardrails: classifier verdicts (observed)', classifier, hard=False)

    def relax_policy():
        call('POST', '/api/policies', {'name': f'E2E open {RUN}', 'redact_pii': True, 'detect_injection': True, 'max_chars': 100000})
        return 'classifier policy superseded'
    check('restore plain policy', relax_policy)

    def router():
        rid = call('POST', '/api/routers', {'name': f'E2E cascade {RUN}', 'models': [ids['small'], ids['chat']], 'judge_model': ids['chat'], 'min_score': 0.7})['id']
        r = call('POST', '/api/chat', {'model': 'router:' + rid, 'max_tokens': 120,
                                       'messages': [{'role': 'user', 'content': 'Explain in two sentences why idempotency keys matter for payment APIs.'}]})
        assert text_of(r).strip(), 'empty router answer'
        listed = call('GET', '/v1/models')
        assert any(m['id'] == 'router:' + rid for m in listed['data']), 'router missing from /v1/models'
        return {'routing': r.get('routing'), 'answered_by': r.get('model'), 'answer': text_of(r)[:120]}
    check('cascade router', router)

    def agent():
        aid = call('POST', '/api/agents', {'name': f'E2E agent {RUN}', 'model': ids['agent'], 'knowledge_ids': [kb['id']], 'tools': ['knowledge_search'], 'max_steps': 4,
                                           'system_prompt': 'Always call knowledge_search before answering. Answer briefly and cite the document.'})['id']
        job = wait(call('POST', f'/api/agents/{aid}/run', {'message': 'How long may a rollback take?'})['id'])
        assert job['status'] == 'completed', job.get('error') or job['status']
        kinds = [t.get('type') for t in job.get('trace', [])]
        agent_trace['kinds'] = kinds
        return {'trace': kinds, 'answer': json.dumps(job.get('result'))[:200]}
    agent_trace = {}
    check('agent run completes', agent)

    def agent_tools():
        assert any('tool' in (k or '') for k in agent_trace.get('kinds', [])), 'model answered without calling knowledge_search'
        return agent_trace['kinds']
    check('agent called a tool', agent_tools)

    def vision():
        png = base64.b64encode(solid_png(128, 128, (220, 30, 30))).decode()
        r = call('POST', '/api/chat', {'model': ids['vision'], 'max_tokens': 60, 'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'What colour is this image? Answer in a few words.'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + png}}]}]})
        assert text_of(r).strip(), 'empty vision answer'
        return {'answer': text_of(r)[:120]}
    check('vision content part', vision)

    image = os.getenv('NUVORA_E2E_OCR_IMAGE')

    def ocr():
        with open(image, 'rb') as f:
            data = base64.b64encode(f.read()).decode()
        doc = call('POST', f"/api/knowledge/{kb['id']}/upload", {'name': 'scanned-note.png', 'content_type': 'image/png', 'content_base64': data})
        text = call('GET', '/api/documents/' + doc['id']).get('text', '')
        return {'extraction': doc.get('extraction'), 'text': text[:200]}
    if image:
        check('OCR ingest via vision model', ocr, hard=False)

    def extract():
        job = wait(call('POST', '/api/extract', {'model': ids['chat'], 'min_confidence': 0.5,
                                                  'text': 'Invoice 2041 from Acme GmbH, dated 2026-09-14, total 1250.50 EUR, paid: no.',
                                                  'fields': {'vendor': {'type': 'string'}, 'total': {'type': 'number'}, 'date': {'type': 'date'}, 'paid': {'type': 'boolean'}}})['id'])
        assert job['status'] in ('completed', 'waiting_approval'), job.get('error') or job['status']
        fields = job['result']['fields']
        assert 'Acme' in str(fields['vendor']['value']), fields
        return {'status': job['status'], 'fields': fields}
    check('structured extraction', extract)

    def usage():
        u = call('GET', '/api/usage')
        return {'records': len(u.get('records', [])), 'cost': u.get('cost'), 'cached_tokens': u.get('cached_tokens')}
    check('usage ledger', usage, hard=False)

    def audit():
        v = call('GET', '/api/audit')['verification']
        assert v['valid'], v
        return v
    check('audit chain verifies', audit)
    finish()


def finish():
    failed = [r['check'] for r in results if r['hard'] and not r['ok']]
    print(json.dumps({'summary': {'checks': len(results), 'passed': sum(r['ok'] for r in results), 'hard_failures': failed}}))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
