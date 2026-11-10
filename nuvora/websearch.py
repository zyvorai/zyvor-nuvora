# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Optional allow-listed web search tool for agents. Stub that returns structured empty results unless a backend is configured.

Configure NUVORA_WEBSEARCH_URL to an internal search endpoint that accepts ?q= and returns JSON {results:[{title,url,snippet}]}.
"""
import json
import os
import urllib.parse
import urllib.request
from .security import Fault

def search(query, limit=5):
    url = os.getenv('NUVORA_WEBSEARCH_URL', '').strip()
    if not url:
        return {'results': [], 'note': 'Web search not configured (set NUVORA_WEBSEARCH_URL)'}
    if not url.startswith(('http://', 'https://')):
        raise Fault('Invalid websearch URL')
    full = url + ('&' if '?' in url else '?') + urllib.parse.urlencode({'q': query, 'limit': limit})
    try:
        with urllib.request.urlopen(full, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return {'results': data.get('results', [])[:limit]}
    except Exception as exc:
        raise Fault('Web search failed', 502) from exc
