# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Database adapters. SQLite (stdlib) is the default; PostgreSQL needs the postgres extra.

Callers write portable SQL with `?` placeholders and explicit column lists. The adapter
translates placeholders, supplies dialect fragments and makes rows readable by name or index."""
import re
import sqlite3
import threading
import zlib

SCHEMA_VERSION = 5

TABLES = '''
CREATE TABLE IF NOT EXISTS objects (
  tenant TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL,
  data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
  created REAL NOT NULL, updated REAL NOT NULL,
  PRIMARY KEY(tenant,kind,id));
CREATE TABLE IF NOT EXISTS users (
  tenant TEXT NOT NULL, username TEXT NOT NULL, password TEXT NOT NULL,
  role TEXT NOT NULL, identity TEXT NOT NULL DEFAULT '', PRIMARY KEY(tenant,username));
CREATE TABLE IF NOT EXISTS tokens (
  digest TEXT PRIMARY KEY, tenant TEXT NOT NULL, username TEXT NOT NULL,
  role TEXT NOT NULL, expires REAL NOT NULL, id TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'session', label TEXT NOT NULL DEFAULT '', created REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit (
  seq SERIAL_KEY, tenant TEXT NOT NULL,
  event TEXT NOT NULL, previous TEXT NOT NULL, digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS usage (
  id TEXT PRIMARY KEY, tenant TEXT NOT NULL, model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
  cost REAL NOT NULL, latency_ms REAL NOT NULL, cached INTEGER NOT NULL,
  created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS cache (
  tenant TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
  expires REAL NOT NULL, PRIMARY KEY(tenant,key));
CREATE TABLE IF NOT EXISTS idempotency (
  tenant TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL,
  value TEXT NOT NULL, PRIMARY KEY(tenant,key));
CREATE TABLE IF NOT EXISTS login_failures (
  tenant TEXT NOT NULL, username TEXT NOT NULL, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS login_failures_key ON login_failures (tenant,username,at);
CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS artifacts (
  tenant TEXT NOT NULL, id TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL,
  data TEXT NOT NULL, owner TEXT NOT NULL, source TEXT NOT NULL DEFAULT '',
  created REAL NOT NULL, expires REAL NOT NULL, PRIMARY KEY(tenant,id));
CREATE TABLE IF NOT EXISTS aws_credentials (
  access_key_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, username TEXT NOT NULL,
  role TEXT NOT NULL, secret TEXT NOT NULL, expires REAL NOT NULL, created REAL NOT NULL,
  label TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
'''

# Columns added after 0.2, applied idempotently to new and upgraded databases.
COLUMNS = [
    ('usage', 'cached_tokens', 'INTEGER NOT NULL DEFAULT 0'),
    ('usage', 'saved', 'REAL NOT NULL DEFAULT 0'),
    ('users', 'groups', "TEXT NOT NULL DEFAULT ''"),
]


class Row(dict):
    """A dict row that also answers positional lookups like sqlite3.Row."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class Database:
    dialect = ''
    IntegrityError = sqlite3.IntegrityError

    def __init__(self):
        self.lock = threading.RLock()
        self.depth = 0

    def statements(self, script):
        return [s.strip() for s in script.split(';') if s.strip()]

    def begin(self):
        raise NotImplementedError

    def lock_key(self, name):
        """Serialise writers on a named key for the rest of the current transaction."""

    def day(self, column):
        raise NotImplementedError

    def for_update(self):
        return ''

    def version(self):
        row = self.execute('SELECT MAX(version) FROM schema_version').fetchone()
        return row[0] if row and row[0] is not None else 0

    def migrate(self):
        for statement in self.statements(self.ddl(TABLES)):
            self.execute(statement)
        self.legacy()
        for table, column, ddl in COLUMNS:
            self.add_column(table, column, self.ddl(' '+ddl+' ').strip())
        current = self.version()
        if current > SCHEMA_VERSION:
            raise RuntimeError(f'Database schema {current} is newer than this Nuvora ({SCHEMA_VERSION}); upgrade Nuvora')
        if current < SCHEMA_VERSION:
            self.execute('DELETE FROM schema_version')
            self.execute('INSERT INTO schema_version (version) VALUES (?)', (SCHEMA_VERSION,))

    def legacy(self):
        """Bring pre-versioned (0.1) databases up to the current shape."""

    def add_column(self, table, column, ddl):
        raise NotImplementedError


class SqliteDB(Database):
    dialect = 'sqlite'

    def __init__(self, path):
        super().__init__()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        for pragma in ('journal_mode=WAL', 'foreign_keys=ON', 'busy_timeout=5000'):
            self.conn.execute('PRAGMA '+pragma)

    def ddl(self, script):
        return script.replace('SERIAL_KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT')

    def execute(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params)

    def begin(self):
        self.conn.execute('BEGIN IMMEDIATE')

    def commit(self):
        self.conn.execute('COMMIT')

    def rollback(self):
        self.conn.execute('ROLLBACK')

    def day(self, column):
        return f"date({column},'unixepoch')"

    def legacy(self):
        columns = {r['name'] for r in self.conn.execute('PRAGMA table_info(tokens)')}
        for name, ddl in (('id', "TEXT NOT NULL DEFAULT ''"), ('kind', "TEXT NOT NULL DEFAULT 'session'"),
                          ('label', "TEXT NOT NULL DEFAULT ''"), ('created', 'REAL NOT NULL DEFAULT 0')):
            if name not in columns:
                self.conn.execute(f'ALTER TABLE tokens ADD COLUMN {name} {ddl}')
        if 'identity' not in {r['name'] for r in self.conn.execute('PRAGMA table_info(users)')}:
            self.conn.execute("ALTER TABLE users ADD COLUMN identity TEXT NOT NULL DEFAULT ''")

    def add_column(self, table, column, ddl):
        if column not in {r['name'] for r in self.conn.execute(f'PRAGMA table_info({table})')}:
            self.conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')

    def close(self):
        self.conn.close()


class PostgresDB(Database):
    dialect = 'postgres'

    def __init__(self, url):
        super().__init__()
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("PostgreSQL needs the postgres extra: pip install 'zyvor-nuvora[postgres]'") from exc
        self.psycopg = psycopg
        self.url = url
        self.IntegrityError = psycopg.errors.IntegrityError
        self.conn = self.connect()

    def connect(self):
        def factory(cursor):
            names = [c.name for c in cursor.description or []]
            return lambda values: Row(zip(names, values))
        return self.psycopg.connect(self.url, autocommit=True, row_factory=factory, connect_timeout=10)

    def ddl(self, script):
        return script.replace('SERIAL_KEY', 'BIGSERIAL PRIMARY KEY').replace(' REAL ', ' DOUBLE PRECISION ')

    @staticmethod
    def translate(sql):
        return re.sub(r'\?', '%s', sql.replace('%', '%%'))

    def execute(self, sql, params=()):
        with self.lock:
            try:
                return self.conn.execute(self.translate(sql), tuple(params))
            except self.psycopg.OperationalError:
                # Reconnect once when idle; never inside a transaction, whose earlier writes are gone.
                if self.depth or not self.conn.closed and not self.conn.broken:
                    raise
                self.conn = self.connect()
                return self.conn.execute(self.translate(sql), tuple(params))

    def begin(self):
        self.execute('BEGIN')

    def commit(self):
        self.execute('COMMIT')

    def rollback(self):
        self.execute('ROLLBACK')

    def lock_key(self, name):
        self.execute('SELECT pg_advisory_xact_lock(?)', (zlib.crc32(name.encode()) - 2**31,))

    def day(self, column):
        return f"to_char(to_timestamp({column}) AT TIME ZONE 'UTC','YYYY-MM-DD')"

    def for_update(self):
        return ' FOR UPDATE SKIP LOCKED'

    def add_column(self, table, column, ddl):
        self.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}')

    def migrate(self):
        with self.lock:
            # Replicas may start together; one migrates at a time.
            self.begin()
            try:
                self.execute('SELECT pg_advisory_xact_lock(?)', (zlib.crc32(b'nuvora-migrate') - 2**31,))
                super().migrate()
            except BaseException:
                self.rollback()
                raise
            self.commit()

    def close(self):
        self.conn.close()


def connect(path=None, url=None):
    url = url or ''
    if url.startswith(('postgres://', 'postgresql://')):
        return PostgresDB(url)
    if url:
        raise ValueError('NUVORA_DATABASE_URL must start with postgresql://')
    return SqliteDB(path)
