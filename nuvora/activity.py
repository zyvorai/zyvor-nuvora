# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Lightweight last-seen tracking for principals. Stored as a special object."""
import time

KIND = 'activity'

def touch(store, principal):
    """Record last activity for the principal. Idempotent, cheap."""
    tenant = principal['tenant']
    username = principal.get('username') or 'unknown'
    key = f'{tenant}:{username}'
    now = time.time()
    try:
        existing = store.get(tenant, KIND, key)
        existing['last_seen'] = now
        existing['count'] = existing.get('count', 0) + 1
        store.put(tenant, KIND, existing, key, expected=existing.get('revision'))
    except KeyError:
        store.put(tenant, KIND, {'username': username, 'last_seen': now, 'count': 1}, key)

def last_seen(store, tenant, username):
    try:
        return store.get(tenant, KIND, f'{tenant}:{username}').get('last_seen')
    except KeyError:
        return None
