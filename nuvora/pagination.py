# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Opaque cursor tokens (`maxResults`, `nextToken`) with a stable newest-first order."""
import base64
import json
from .security import Fault

MAX_RESULTS=100


def encode(value):
    return base64.urlsafe_b64encode(json.dumps(value,separators=(',',':')).encode()).decode().rstrip('=')


def decode(token):
    try:
        value=json.loads(base64.urlsafe_b64decode(token+'='*(-len(token)%4)))
    except (ValueError,TypeError):
        raise Fault('Invalid nextToken')
    if not isinstance(value,dict):
        raise Fault('Invalid nextToken')
    return value


def limit(max_results):
    """None means "everything" (the unpaginated behaviour that existed before tokens)."""
    if max_results is None:
        return None
    if isinstance(max_results,str) and max_results.isdigit():
        max_results=int(max_results)
    if not isinstance(max_results,int) or isinstance(max_results,bool) or not 1<=max_results<=MAX_RESULTS:
        raise Fault(f'maxResults must be an integer from 1 to {MAX_RESULTS}')
    return max_results


def page(items,max_results=None,token=None):
    """Keyset pagination over items sorted by (created, id) descending; returns (items, nextToken|None).

    The cursor holds the last returned (created, id), so inserts and deletes between calls never repeat or skip an item."""
    size=limit(max_results)
    ordered=sorted(items,key=lambda x:(x.get('created',0),x['id']),reverse=True)
    if token:
        cursor=decode(token)
        try:
            after=(float(cursor['c']),str(cursor['i']))
        except (KeyError,TypeError,ValueError):
            raise Fault('Invalid nextToken')
        ordered=[x for x in ordered if (x.get('created',0),x['id'])<after]
        if size is None:
            size=MAX_RESULTS
    if size is None or len(ordered)<=size:
        return ordered,None
    chosen=ordered[:size]
    return chosen,encode({'c':chosen[-1].get('created',0),'i':chosen[-1]['id']})
