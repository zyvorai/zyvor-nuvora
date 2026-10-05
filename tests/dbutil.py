# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Pick the test database: SQLite by default, PostgreSQL when NUVORA_TEST_DATABASE_URL is set."""
import os

from nuvora.store import Store

TABLES = ('objects','users','tokens','audit','usage','cache','idempotency','login_failures','workers','schema_version')


def make_store(path):
    url = os.getenv('NUVORA_TEST_DATABASE_URL')
    if not url:
        return Store(path)
    import psycopg
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute('DROP TABLE IF EXISTS '+','.join(TABLES))
    return Store(path, url)
