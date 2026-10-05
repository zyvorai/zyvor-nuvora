# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Minimal MCP client over Streamable HTTP (JSON-RPC 2.0): initialize, tools/list, tools/call."""
import json
import os
import re
import urllib.error
import urllib.request

from . import __version__
from .providers import NoRedirect
from .security import Fault, validate_url

PROTOCOL = '2025-06-18'
LIMIT = 1024 * 1024


def tool_name(server_id, tool):
    """An OpenAI-compatible function name (<=64 chars of [A-Za-z0-9_-])."""
    return ('mcp_' + server_id[:8] + '_' + re.sub(r'[^A-Za-z0-9_-]', '_', tool))[:64]


class MCPClient:
    def __init__(self, url, key_env=None, allowlist=()):
        validate_url(url, allowlist)
        self.url = url
        self.key_env = key_env
        self.session = None
        self.ids = 0

    def _headers(self):
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': PROTOCOL}
        if self.key_env:
            secret = os.getenv(self.key_env)
            if not secret:
                raise Fault('MCP server credential is not configured', 503)
            headers['Authorization'] = 'Bearer ' + secret
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        return headers

    def _post(self, method, params=None, notify=False):
        payload = {'jsonrpc': '2.0', 'method': method, **({'params': params} if params is not None else {})}
        if not notify:
            self.ids += 1
            payload['id'] = self.ids
        request = urllib.request.Request(self.url, json.dumps(payload).encode(), self._headers(), method='POST')
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
                self.session = response.headers.get('Mcp-Session-Id') or self.session
                raw = response.read(LIMIT + 1)
                kind = response.headers.get('Content-Type', '')
        except urllib.error.HTTPError as exc:
            exc.close()
            raise Fault(f'MCP server returned HTTP {exc.code}', 502) from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise Fault('MCP server request failed; check operator configuration', 502) from exc
        if notify:
            return None
        if len(raw) > LIMIT:
            raise Fault('MCP response exceeds 1 MiB', 502)
        messages = []
        try:
            if 'text/event-stream' in kind:
                messages = [json.loads(line[5:]) for line in raw.decode('utf-8', 'replace').splitlines() if line.startswith('data:') and line[5:].strip()]
            else:
                body = json.loads(raw)
                messages = body if isinstance(body, list) else [body]
        except ValueError as exc:
            raise Fault('MCP server returned malformed JSON', 502) from exc
        reply = next((m for m in messages if isinstance(m, dict) and m.get('id') == payload['id']), None)
        if reply is None:
            raise Fault('MCP server sent no reply', 502)
        if 'error' in reply:
            raise Fault('MCP error: ' + str(reply['error'].get('message', 'unknown'))[:200], 502)
        return reply.get('result') or {}

    def initialize(self):
        if self.session is None and not self.ids:
            self._post('initialize', {'protocolVersion': PROTOCOL, 'capabilities': {}, 'clientInfo': {'name': 'nuvora', 'version': __version__}})
            self._post('notifications/initialized', notify=True)
        return self

    def list_tools(self):
        self.initialize()
        tools, cursor = [], None
        for _ in range(5):
            result = self._post('tools/list', {'cursor': cursor} if cursor else {})
            tools.extend(t for t in result.get('tools', []) if isinstance(t, dict) and isinstance(t.get('name'), str))
            cursor = result.get('nextCursor')
            if not cursor:
                break
        return [{'name': t['name'][:128], 'description': str(t.get('description', ''))[:1000],
                 'inputSchema': t.get('inputSchema') if isinstance(t.get('inputSchema'), dict) else {'type': 'object', 'properties': {}}} for t in tools[:100]]

    def call(self, tool, arguments):
        self.initialize()
        result = self._post('tools/call', {'name': tool, 'arguments': arguments})
        text = '\n'.join(c.get('text', '') for c in result.get('content', []) if isinstance(c, dict) and c.get('type') == 'text')
        out = {'content': text[:65536], 'is_error': bool(result.get('isError'))}
        if isinstance(result.get('structuredContent'), dict):
            out['structured'] = result['structuredContent']
        return out
