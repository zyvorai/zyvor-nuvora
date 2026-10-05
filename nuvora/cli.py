# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Small API client using a bearer token supplied through environment."""
import argparse
import json
import os
import sys
import urllib.request
from .security import validate_url


def main():
    parser=argparse.ArgumentParser(description='nuvoractl API client')
    parser.add_argument('--url',default=os.getenv('NUVORA_URL','http://127.0.0.1:8789'))
    parser.add_argument('method',choices=['GET','POST','DELETE'])
    parser.add_argument('path')
    parser.add_argument('--file',help='JSON request file; - reads stdin')
    args=parser.parse_args()
    from urllib.parse import urlsplit
    validate_url(args.url,{urlsplit(args.url).hostname})
    token=os.getenv('NUVORA_TOKEN')
    if not token:
        parser.error('Set NUVORA_TOKEN; tokens are never command-line arguments')
    if not args.path.startswith('/') or '://' in args.path:
        parser.error('Use an absolute API path')
    data=None
    if args.file:
        with open(args.file) if args.file!='-' else sys.stdin as file:
            data=json.load(file)
    request=urllib.request.Request(args.url.rstrip('/')+args.path,json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method=args.method)
    try:
        with urllib.request.urlopen(request,timeout=60) as response:
            print(json.dumps(json.load(response),indent=2))
    except urllib.error.HTTPError as exc:
        print(exc.read().decode(),file=sys.stderr)
        sys.exit(1)

if __name__=='__main__':
    main()
