# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Knowledge connectors: crawl an allow-listed website, read an S3 prefix or a Confluence space.

Each connector yields items {name, url, version, content_type, load()} where version (when the
source offers one) lets sync skip unchanged items without downloading them."""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import quote, urldefrag, urljoin, urlsplit

from . import ingest as parsers
from .providers import NoRedirect
from .security import Fault, validate_url

AGENT = 'NuvoraConnector/0.3'
PAGE_LIMIT = 2*1024*1024
TYPES = ('web', 's3', 'confluence')
SKIP_SUFFIX = re.compile(r'\.(png|jpe?g|gif|webp|svg|ico|css|js|zip|gz|tar|mp[34]|wav|woff2?|ttf|exe|dmg)$', re.I)


def fetch(url, hosts, headers=None, limit=PAGE_LIMIT):
    """(content_type, bytes) for an allow-listed URL; no redirects, size capped."""
    validate_url(url, hosts)
    request = urllib.request.Request(url, headers={'User-Agent': AGENT, **(headers or {})})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            raw = response.read(limit+1)
            if len(raw) > limit:
                raise Fault('Page larger than '+str(limit//(1024*1024))+' MiB', 413)
            return response.headers.get('Content-Type', ''), raw
    except Fault:
        raise
    except urllib.error.HTTPError as exc:
        raise Fault(f'HTTP {exc.code}', 502) from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise Fault('Fetch failed', 502) from exc


def title_of(html):
    match = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
    return re.sub(r'\s+', ' ', match[1]).strip()[:120] if match else ''


def crawl(spec, hosts, skipped):
    """Breadth-first crawl of one host, honouring robots.txt, depth and page limits."""
    start = spec['url']
    origin = urlsplit(start)
    robots = urllib.robotparser.RobotFileParser()
    try:
        _, raw = fetch(f'{origin.scheme}://{origin.netloc}/robots.txt', hosts, limit=512*1024)
        robots.parse(parsers.decode(raw).splitlines())
    except Fault:
        robots.parse([])
    delay = min(float(robots.crawl_delay(AGENT) or 0), 5.0)
    queue, seen, count = [(start, 0)], {start}, 0
    while queue and count < spec.get('max_pages', 25):
        url, depth = queue.pop(0)
        if not robots.can_fetch(AGENT, url):
            skipped.append({'item': url, 'reason': 'disallowed by robots.txt'})
            continue
        try:
            ctype, raw = fetch(url, hosts)
        except Fault as exc:
            skipped.append({'item': url, 'reason': str(exc)})
            continue
        base = ctype.split(';')[0].strip().lower()
        if base not in ('text/html', 'application/xhtml+xml', 'text/plain', 'text/markdown'):
            skipped.append({'item': url, 'reason': 'unsupported content type '+(base or 'unknown')})
            continue
        source = parsers.decode(raw)
        html = base in ('text/html', 'application/xhtml+xml')
        count += 1
        text = parsers.html_text(source) if html else source
        yield {'name': url[:200], 'url': url, 'content_type': 'text/html' if html else base, 'title': title_of(source) if html else '',
               'load': lambda text=text: text}
        if html and depth < spec.get('depth', 1):
            for href in re.findall(r'''href\s*=\s*["']([^"'#\s]+)''', source, re.I):
                link = urldefrag(urljoin(url, href))[0]
                parts = urlsplit(link)
                if parts.scheme == origin.scheme and parts.netloc == origin.netloc and link not in seen and not SKIP_SUFFIX.search(parts.path):
                    seen.add(link)
                    queue.append((link, depth+1))
        if delay:
            time.sleep(delay)


def s3_client(spec):
    try:
        import boto3
    except ImportError as exc:
        raise Fault("S3 connectors need the aws extra: pip install 'zyvor-nuvora[aws]'", 503) from exc
    return boto3.client('s3', region_name=spec.get('region') or None)


def s3(spec, client, skipped):
    """Objects under bucket/prefix whose type Nuvora can extract as text."""
    count = 0
    try:
        pages = client.get_paginator('list_objects_v2').paginate(Bucket=spec['bucket'], Prefix=spec.get('prefix', ''))
        for page in pages:
            for obj in page.get('Contents', []):
                key = obj['Key']
                if key.endswith('/'):
                    continue
                if count >= spec.get('max_pages', 100):
                    return
                try:
                    detected = parsers.kind(key)
                except Fault:
                    skipped.append({'item': key, 'reason': 'unsupported file type'})
                    continue
                if parsers.media(detected) or obj.get('Size', 0) > parsers.MAX_UPLOAD:
                    skipped.append({'item': key, 'reason': 'images, audio and files over 20 MiB need a direct upload'})
                    continue
                count += 1

                def load(key=key):
                    data = client.get_object(Bucket=spec['bucket'], Key=key)['Body'].read(parsers.MAX_UPLOAD+1)
                    return parsers.extract(key, '', data)[0]
                yield {'name': key[-200:], 'url': f"s3://{spec['bucket']}/{key}", 'version': str(obj.get('ETag', '')).strip('"') or None,
                       'content_type': detected, 'load': load}
    except Fault:
        raise
    except Exception as exc:
        raise Fault('S3 listing failed; check bucket, region and credentials', 502) from exc


def confluence(spec, hosts, skipped):
    """Pages of one Confluence space through the REST API, versioned by page version."""
    token = os.getenv(spec['key_env'])
    if not token:
        raise Fault('Confluence credential is not configured', 503)
    auth = 'Basic '+base64.b64encode(f"{spec['username']}:{token}".encode()).decode() if spec.get('username') else 'Bearer '+token
    base = spec['url'].rstrip('/')
    start, count, limit = 0, 0, 25
    while count < spec.get('max_pages', 100):
        url = f"{base}/rest/api/content?spaceKey={quote(spec['space'])}&type=page&expand=body.storage,version&limit={limit}&start={start}"
        _, raw = fetch(url, hosts, {'Authorization': auth, 'Accept': 'application/json'}, 8*1024*1024)
        try:
            data = json.loads(raw)
            results = data['results']
        except (ValueError, KeyError, TypeError) as exc:
            raise Fault('Confluence returned an unexpected response', 502) from exc
        for page in results:
            if count >= spec.get('max_pages', 100):
                return
            try:
                title = str(page['title'])[:200]
                html = page['body']['storage']['value']
                version = str(page['version']['number'])
            except (KeyError, TypeError):
                skipped.append({'item': str(page.get('id', '?')), 'reason': 'page without body or version'})
                continue
            count += 1
            link = (page.get('_links') or {}).get('webui', '')
            yield {'name': title, 'url': base+link if link else base, 'version': version, 'content_type': 'text/html',
                   'load': lambda html=html: parsers.html_text(html)}
        if len(results) < limit or not (data.get('_links') or {}).get('next'):
            return
        start += limit


def items(spec, hosts, skipped, client=None):
    if spec['type'] == 'web':
        return crawl(spec, hosts, skipped)
    if spec['type'] == 's3':
        return s3(spec, client or s3_client(spec), skipped)
    return confluence(spec, hosts, skipped)
