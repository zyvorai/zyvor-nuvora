# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Typed enterprise API tools. External writes always require separate approval."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from .providers import NoRedirect
from .security import Fault, validate_url, guard


def validate_schema(schema):
    if not isinstance(schema,dict) or schema.get('type')!='object':
        raise Fault('Action input schema must be an object')
    props=schema.get('properties',{})
    required=schema.get('required',[])
    if not isinstance(props,dict) or len(props)>30 or not isinstance(required,list) or set(required)-set(props):
        raise Fault('Invalid action schema')
    for name,value in props.items():
        if not isinstance(value,dict) or value.get('type') not in ('string','integer','number','boolean'):
            raise Fault('Action fields support string, integer, number and boolean')
    return {**schema,'additionalProperties':False}


def validate_arguments(schema,args):
    if not isinstance(args,dict) or set(args)-set(schema.get('properties',{})) or set(schema.get('required',[]))-set(args):
        raise Fault('Action arguments do not match the schema')
    for name,value in args.items():
        spec=schema['properties'][name]
        kind=spec['type']
        valid=(kind=='string' and isinstance(value,str) and len(value)<=10000) or (kind=='integer' and type(value)==int) or (kind=='number' and type(value) in (int,float)) or (kind=='boolean' and type(value)==bool)
        if not valid:
            raise Fault('Invalid action field: '+name)
        if 'enum' in spec and value not in spec['enum']:
            raise Fault('Action field not in permitted values: '+name)
        if kind in ('integer','number'):
            import math
            if not math.isfinite(value) or value<spec.get('minimum',float('-inf')) or value>spec.get('maximum',float('inf')):
                raise Fault('Action field outside permitted range: '+name)
    return args


def execute(action,args,hosts,policy):
    validate_arguments(action['input_schema'],args)
    validate_url(action['url'],hosts)
    verdict=guard(json.dumps(args),policy)
    if not verdict['allowed'] or verdict['pii_redacted']:
        raise Fault('Action arguments violate the active guardrail',422)
    headers={'Accept':'application/json'}
    if action.get('key_env'):
        secret=os.getenv(action['key_env'])
        if not secret:
            raise Fault('Action credential is not configured',503)
        headers['Authorization']='Bearer '+secret
    method=action['method']
    url=action['url']
    body=None
    if method=='GET':
        if args:url+=('&' if '?' in url else '?')+urllib.parse.urlencode(args)
    else:
        body=json.dumps(args).encode()
        headers['Content-Type']='application/json'
    req=urllib.request.Request(url,body,headers,method=method)
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=30) as response:
            raw=response.read(1024*1024+1)
            if len(raw)>1024*1024:
                raise Fault('Action response exceeds 1 MiB',502)
            value=json.loads(raw)
    except Fault:
        raise
    except (urllib.error.URLError,ValueError,TimeoutError) as exc:
        # A POST timeout may hide a committed change. Never retry automatically.
        raise Fault('Action request failed; inspect the external system before retrying',502) from exc
    # Do not inject credentials/content unsafe for downstream model processing.
    safe=guard(json.dumps(value),policy)
    if not safe['allowed']:
        raise Fault('Action output violates the active guardrail',422)
    return json.loads(safe['text'])
