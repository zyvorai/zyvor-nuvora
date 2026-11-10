# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Export/import of configuration bundles."""
from .security import Fault

EXPORTABLE = ('agents', 'prompts', 'policies', 'workflows', 'guardrails', 'routers', 'schedules', 'mcp_servers', 'connectors')
STRIP = {'id', 'revision', 'created', 'updated', 'catalog', 'available', 'last_run', 'secret', 'key_env'}


def export(store, tenant, kinds=None):
    kinds = kinds or EXPORTABLE
    out = {'version': 1, 'kinds': {}}
    for kind in kinds:
        if kind not in EXPORTABLE:
            continue
        items = store.list(tenant, kind)
        cleaned = []
        for item in items:
            row = {k: v for k, v in item.items() if k not in STRIP}
            if kind == 'schedules' and 'cron' not in row and 'every_minutes' not in row:
                continue
            cleaned.append(row)
        out['kinds'][kind] = cleaned
    return out


def import_bundle(store, tenant, bundle, dry_run=False):
    if not isinstance(bundle, dict) or bundle.get('version') != 1:
        raise Fault('bundle version 1 required')
    created = []
    for kind, items in (bundle.get('kinds') or {}).items():
        if kind not in EXPORTABLE or not isinstance(items, list):
            continue
        for spec in items:
            if dry_run:
                created.append({'kind': kind, 'name': spec.get('name', '?')})
                continue
            obj = store.put(tenant, kind, spec)
            created.append({'kind': kind, 'id': obj['id'], 'name': spec.get('name')})
    return {'created': created, 'dry_run': dry_run}
