# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Zyvor platform integrations, configured by the operator through the environment.

Netra (network evidence) is read-only. Zyntra handoffs leave the decision to Zyntra's own
approval flow. Keep runs code in FluxVM sandboxes and is only reachable through a Nuvora
approval of the exact code. Every host must be on NUVORA_PROVIDER_HOSTS."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .providers import NoRedirect
from .security import Fault, guard, validate_url

SYSTEMS = {
    'netra': {'label': 'Netra', 'role': 'Network evidence: incidents, flows, drop explanations (read-only)', 'health': '/api/v1/status'},
    'zyntra': {'label': 'Zyntra', 'role': 'Ontology decisions: workflow handoffs approved inside Zyntra', 'health': '/api/v1/proposals?limit=1'},
    'keep': {'label': 'Keep', 'role': 'FluxVM sandboxes for agent code execution (always approved first)', 'health': '/v1/sandboxes'},
    'trainer': {'label': 'Trainer', 'role': 'Fine-tuning and distillation jobs (for example Gryvia); finished models join the catalog', 'health': '/v1/training/jobs?limit=1'},
}

MODEL_PRESETS = [
    {'id': 'fabric', 'label': 'Zyvor Fabric AI gateway', 'provider': 'openai', 'base_url': 'https://fabric.example.com/api/ai/openai/ENDPOINT/v1',
     'key_env': 'NUVORA_SECRET_FABRIC_KEY', 'hint': 'Use the endpoint slug from Fabric; keys start with fvai_.'},
    {'id': 'gryvia', 'label': 'Gryvia GPU serving', 'provider': 'openai', 'base_url': 'https://gryvia.example.com/v1',
     'key_env': 'NUVORA_SECRET_GRYVIA_KEY', 'hint': 'A Gryvia tenant key; serves /v1/chat/completions and /v1/embeddings.'},
    {'id': 'vllm', 'label': 'vLLM or any OpenAI-compatible server', 'provider': 'openai', 'base_url': 'http://127.0.0.1:8000/v1', 'key_env': '', 'hint': ''},
    {'id': 'ollama', 'label': 'Ollama', 'provider': 'ollama', 'base_url': 'http://127.0.0.1:11434', 'key_env': '', 'hint': 'Pull models with ollama pull first.'},
]

TOOLS = {
    'netra_status': {'description': 'Netra collector and sensor health', 'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
    'netra_incidents': {'description': 'Recent Netra network incidents', 'parameters': {'type': 'object', 'properties': {
        'status': {'type': 'string', 'enum': ['open', 'resolved', 'all']}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50}}, 'additionalProperties': False}},
    'netra_flow_summary': {'description': 'Top talkers and protocols for a time window', 'parameters': {'type': 'object', 'properties': {
        'window': {'type': 'string', 'enum': ['15m', '1h', '24h']}}, 'additionalProperties': False}},
    'netra_drop_explain': {'description': 'Explain why traffic between two endpoints was dropped', 'parameters': {'type': 'object', 'properties': {
        'src': {'type': 'string'}, 'dst': {'type': 'string'}, 'port': {'type': 'integer', 'minimum': 1, 'maximum': 65535}}, 'required': ['src', 'dst'], 'additionalProperties': False}},
    'run_code': {'description': 'Run a short program in an isolated Keep sandbox; a human approves the exact code first', 'parameters': {'type': 'object', 'properties': {
        'language': {'type': 'string', 'enum': ['python', 'bash']}, 'code': {'type': 'string'}}, 'required': ['language', 'code'], 'additionalProperties': False}},
}
TOOL_SYSTEM = {name: name.split('_')[0] if name.startswith('netra_') else 'keep' for name in TOOLS}
NETRA_PATHS = {'netra_status': '/api/v1/status', 'netra_incidents': '/api/v1/incidents', 'netra_flow_summary': '/api/v1/flows/summary', 'netra_drop_explain': '/api/v1/drops/explain'}
LIMIT = 1024*1024
CODE_LIMIT = 20000


class Integrations:
    def __init__(self, hosts, env=None):
        self.hosts = hosts
        self.env = os.environ if env is None else env

    def url(self, system):
        return self.env.get('NUVORA_'+system.upper()+'_URL', '').rstrip('/')

    def configured(self, system):
        return bool(self.url(system))

    def available_tools(self):
        return [name for name, system in TOOL_SYSTEM.items() if self.configured(system)]

    def status(self):
        out = []
        for name, meta in SYSTEMS.items():
            url = self.url(name)
            out.append({'id': name, 'label': meta['label'], 'role': meta['role'], 'configured': bool(url),
                        'host': urllib.parse.urlsplit(url).hostname if url else None,
                        'credential': 'NUVORA_SECRET_'+name.upper()+'_TOKEN', 'credential_set': bool(self.env.get('NUVORA_SECRET_'+name.upper()+'_TOKEN'))})
        return out

    def request(self, system, method, path, body=None, query=None):
        base = self.url(system)
        if not base:
            raise Fault(SYSTEMS[system]['label']+' is not configured; set NUVORA_'+system.upper()+'_URL', 503)
        url = base+path
        if query:
            url += ('&' if '?' in url else '?')+urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        validate_url(url, self.hosts)
        headers = {'Accept': 'application/json'}
        token = self.env.get('NUVORA_SECRET_'+system.upper()+'_TOKEN')
        if token:
            headers['Authorization'] = 'Bearer '+token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(url, data, headers, method=method)
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as response:
                raw = response.read(LIMIT+1)
        except Fault:
            raise
        except urllib.error.HTTPError as exc:
            exc.close()
            raise Fault(SYSTEMS[system]['label']+' returned HTTP '+str(exc.code), 502) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # A write may have committed before the failure; never retry automatically.
            raise Fault(SYSTEMS[system]['label']+' is unreachable', 502) from exc
        if len(raw) > LIMIT:
            raise Fault(SYSTEMS[system]['label']+' response exceeds 1 MiB', 502)
        try:
            return json.loads(raw) if raw else {}
        except ValueError as exc:
            raise Fault(SYSTEMS[system]['label']+' returned invalid JSON', 502) from exc

    def check(self, system):
        if system not in SYSTEMS:
            raise Fault('Unknown integration', 404)
        self.request(system, 'GET', SYSTEMS[system]['health'])
        return {'id': system, 'ok': True}

    @staticmethod
    def screened(value, policy):
        """Integration output reaches models; apply the tenant guardrail like any tool result."""
        verdict = guard(json.dumps(value), policy)
        if not verdict['allowed']:
            raise Fault('Integration output violates the active guardrail', 422)
        return json.loads(verdict['text'])

    def netra(self, tool, args, policy):
        query = {k: v for k, v in args.items()}
        if tool == 'netra_incidents':
            query.setdefault('limit', 20)
        return self.screened(self.request('netra', 'GET', NETRA_PATHS[tool], query=query or None), policy)

    @staticmethod
    def check_code(args):
        if args.get('language') not in ('python', 'bash') or not isinstance(args.get('code'), str) or not 1 <= len(args['code']) <= CODE_LIMIT:
            raise Fault('run_code needs language python or bash and 1–20000 characters of code')
        return args

    def run_code(self, language, code, policy):
        """Create a sandbox, write the program, run it with a deadline and always delete the sandbox."""
        image = self.env.get('NUVORA_KEEP_IMAGE', 'python:3.12-slim')
        box = self.request('keep', 'POST', '/v1/sandboxes', {'image': image, 'timeout_seconds': 120, 'network': 'none', 'labels': {'origin': 'nuvora'}})
        sid = box.get('id')
        if not isinstance(sid, str) or not sid:
            raise Fault('Keep returned no sandbox id', 502)
        path = '/work/main.py' if language == 'python' else '/work/main.sh'
        try:
            self.request('keep', 'POST', f'/v1/sandboxes/{urllib.parse.quote(sid)}/fs/write', {'path': path, 'content': code})
            result = self.request('keep', 'POST', f'/v1/sandboxes/{urllib.parse.quote(sid)}/process',
                                  {'cmd': ['python3' if language == 'python' else 'sh', path], 'timeout_seconds': 60})
        finally:
            try:
                self.request('keep', 'DELETE', f'/v1/sandboxes/{urllib.parse.quote(sid)}')
            except Fault:
                pass
        out = {'sandbox': sid, 'exit_code': result.get('exit_code'), 'stdout': str(result.get('stdout', ''))[:20000], 'stderr': str(result.get('stderr', ''))[:5000]}
        return self.screened(out, policy)

    def handoff(self, step, inputs):
        body = {'action': step['action'], 'inputs': inputs}
        if step.get('scenario'):
            body['scenario'] = step['scenario']
        proposal = self.request('zyntra', 'POST', '/api/v1/proposals', body)
        if not isinstance(proposal.get('id'), (str, int)):
            raise Fault('Zyntra returned no proposal id', 502)
        return {'id': str(proposal['id']), 'status': proposal.get('status', 'pending')}

    def proposal(self, pid):
        return self.request('zyntra', 'GET', '/api/v1/proposals/'+urllib.parse.quote(pid))

    def submit_training(self, body):
        job = self.request('trainer', 'POST', '/v1/training/jobs', body)
        if not isinstance(job.get('id'), (str, int)):
            raise Fault('Trainer returned no job id', 502)
        return str(job['id'])

    def training_job(self, tid):
        return self.request('trainer', 'GET', '/v1/training/jobs/'+urllib.parse.quote(tid))


def discover(model, hosts, env=None):
    """List upstream model identifiers from an OpenAI-compatible or Ollama endpoint."""
    env = os.environ if env is None else env
    base = model.get('base_url', '').rstrip('/')
    provider = model.get('provider')
    if provider not in ('openai', 'ollama'):
        raise Fault('Discovery supports openai-compatible and ollama providers')
    url = base+('/api/tags' if provider == 'ollama' else '/models')
    validate_url(url, hosts)
    headers = {'Accept': 'application/json'}
    if model.get('key_env'):
        if not model['key_env'].startswith('NUVORA_SECRET_'):
            raise Fault('Secrets must use a NUVORA_SECRET_ environment reference')
        key = env.get(model['key_env'])
        if not key:
            raise Fault('Provider credential is not configured', 503)
        headers['Authorization'] = 'Bearer '+key
    try:
        with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url, headers=headers), timeout=15) as r:
            raw = json.loads(r.read(LIMIT))
    except Fault:
        raise
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        raise Fault('Model discovery failed; check the base URL and credential', 502) from exc
    items = raw.get('models', []) if provider == 'ollama' else raw.get('data', [])
    found = []
    for item in items if isinstance(items, list) else []:
        name = item.get('name') or item.get('model') if provider == 'ollama' else item.get('id')
        if isinstance(name, str):
            embed = any(k in name.lower() for k in ('embed', 'bge', 'e5-', 'minilm', 'nomic'))
            found.append({'id': name, 'capability': 'embedding' if embed else 'chat', 'owned_by': item.get('owned_by')})
    return {'models': found[:500]}
