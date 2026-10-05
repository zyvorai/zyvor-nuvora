#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Copy a Nuvora SQLite database into an empty PostgreSQL database.

  NUVORA_DATABASE_URL=postgresql://user:pass@host/nuvora \\
    python3 scripts/migrate-sqlite-to-postgres.py /data/nuvora.db

Stop Nuvora first. The copy runs in one transaction, keeps audit sequence numbers and
verifies every tenant's audit hash chain before committing. Needs the postgres extra."""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nuvora.db import SqliteDB  # noqa: E402
from nuvora.store import Store  # noqa: E402

TABLES = {
    'objects': ('tenant', 'kind', 'id', 'data', 'revision', 'created', 'updated'),
    'users': ('tenant', 'username', 'password', 'role', 'identity', 'groups'),
    'tokens': ('digest', 'tenant', 'username', 'role', 'expires', 'id', 'kind', 'label', 'created'),
    'audit': ('seq', 'tenant', 'event', 'previous', 'digest'),
    'usage': ('id', 'tenant', 'model', 'input_tokens', 'output_tokens', 'cost', 'latency_ms', 'cached', 'created', 'cached_tokens', 'saved'),
    'idempotency': ('tenant', 'key', 'fingerprint', 'value'),
    'artifacts': ('tenant', 'id', 'mime', 'size', 'data', 'owner', 'source', 'created', 'expires'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('sqlite', help='path to the SQLite database (nuvora.db)')
    parser.add_argument('--url', default=os.getenv('NUVORA_DATABASE_URL', ''), help='PostgreSQL URL (default: $NUVORA_DATABASE_URL)')
    parser.add_argument('--dry-run', action='store_true', help='count rows without writing')
    args = parser.parse_args()
    if not Path(args.sqlite).is_file():
        parser.error('SQLite database not found: '+args.sqlite)
    if not args.url.startswith(('postgres://', 'postgresql://')):
        parser.error('Pass --url or set NUVORA_DATABASE_URL to a postgresql:// URL')

    source = Store(args.sqlite)
    if not isinstance(source.db, SqliteDB):
        parser.error('Source must be SQLite')
    rows = {t: source.db.execute(f'SELECT {",".join(c)} FROM {t}').fetchall() for t, c in TABLES.items()}
    for table, items in rows.items():
        print(f'{table:12} {len(items):>8} rows')
    if args.dry_run:
        return

    target = Store(None, args.url)
    if target.db.execute('SELECT COUNT(*) FROM users').fetchone()[0] or target.db.execute('SELECT COUNT(*) FROM objects').fetchone()[0]:
        sys.exit('Target database already holds Nuvora data; refusing to merge. Use an empty database.')
    tenants = {r['tenant'] for r in rows['audit']}
    with target.transaction():
        for table, columns in TABLES.items():
            marks = ','.join('?'*len(columns))
            for row in rows[table]:
                target.db.execute(f'INSERT INTO {table} ({",".join(columns)}) VALUES ({marks})', tuple(row))
        target.db.execute("SELECT setval(pg_get_serial_sequence('audit','seq'), GREATEST((SELECT COALESCE(MAX(seq),0) FROM audit),1))")
        for tenant in sorted(tenants):
            before, after = source.verify(tenant), target.verify(tenant)
            if after != before:
                raise SystemExit(f'Audit chain for tenant {tenant} changed during copy ({before} -> {after}); rolled back')
            print(f'audit chain  {tenant}: {after["events"]} events, valid={after["valid"]}')
    print('Copied. Set NUVORA_DATABASE_URL (Helm: database.urlSecret) and start Nuvora.')


if __name__ == '__main__':
    main()
