"""SQLite persistence. Tenant is mandatory on every object lookup."""
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


class Store:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS objects (
          tenant TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL,
          data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
          created REAL NOT NULL, updated REAL NOT NULL,
          PRIMARY KEY(tenant,kind,id));
        CREATE TABLE IF NOT EXISTS users (
          tenant TEXT NOT NULL, username TEXT NOT NULL, password TEXT NOT NULL,
          role TEXT NOT NULL, PRIMARY KEY(tenant,username));
        CREATE TABLE IF NOT EXISTS tokens (
          digest TEXT PRIMARY KEY, tenant TEXT NOT NULL, username TEXT NOT NULL,
          role TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS audit (
          seq INTEGER PRIMARY KEY AUTOINCREMENT, tenant TEXT NOT NULL,
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
        ''')
        columns={r['name'] for r in self.db.execute('PRAGMA table_info(tokens)')}
        for name,ddl in (('id',"TEXT NOT NULL DEFAULT ''"),('kind',"TEXT NOT NULL DEFAULT 'session'"),('label',"TEXT NOT NULL DEFAULT ''"),('created',"REAL NOT NULL DEFAULT 0")):
            if name not in columns:
                self.db.execute(f'ALTER TABLE tokens ADD COLUMN {name} {ddl}')

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
            except BaseException:
                self.db.execute('ROLLBACK')
                raise
            else:
                self.db.execute('COMMIT')

    def list(self, tenant, kind):
        with self.lock:
            rows = self.db.execute('SELECT * FROM objects WHERE tenant=? AND kind=? ORDER BY created DESC', (tenant,kind)).fetchall()
        return [self.unpack(r) for r in rows]

    @staticmethod
    def unpack(row):
        return {**json.loads(row['data']), 'id':row['id'], 'revision':row['revision'], 'created':row['created'], 'updated':row['updated']}

    def get(self, tenant, kind, id):
        with self.lock:
            row = self.db.execute('SELECT * FROM objects WHERE tenant=? AND kind=? AND id=?', (tenant,kind,id)).fetchone()
        if row is None:
            raise KeyError('Object not found')
        return self.unpack(row)

    def put(self, tenant, kind, data, id=None, expected=None):
        id = id or secrets.token_hex(10)
        clean = {k:v for k,v in data.items() if k not in ('id','revision','created','updated','tenant')}
        now = time.time()
        with self.lock:
            old = self.db.execute('SELECT revision FROM objects WHERE tenant=? AND kind=? AND id=?', (tenant,kind,id)).fetchone()
            if expected is not None and (old is None or old['revision'] != expected):
                raise ValueError('Revision conflict')
            if old:
                self.db.execute('UPDATE objects SET data=?,revision=revision+1,updated=? WHERE tenant=? AND kind=? AND id=?', (canonical(clean),now,tenant,kind,id))
            else:
                self.db.execute('INSERT INTO objects VALUES (?,?,?,?,?,?,?)', (tenant,kind,id,canonical(clean),1,now,now))
        return self.get(tenant,kind,id)

    def delete(self, tenant, kind, id):
        with self.lock:
            if not self.db.execute('DELETE FROM objects WHERE tenant=? AND kind=? AND id=?',(tenant,kind,id)).rowcount:
                raise KeyError('Object not found')

    def audit(self, tenant, actor, action, target, detail=None):
        with self.lock:
            previous = self.db.execute('SELECT digest FROM audit WHERE tenant=? ORDER BY seq DESC LIMIT 1',(tenant,)).fetchone()
            previous = previous[0] if previous else '0'*64
            event = canonical({'actor':actor,'action':action,'target':target,'detail':detail or {},'time':time.time()})
            digest = hashlib.sha256((previous+event).encode()).hexdigest()
            self.db.execute('INSERT INTO audit (tenant,event,previous,digest) VALUES (?,?,?,?)',(tenant,event,previous,digest))

    def events(self, tenant, actor=None, action=None, since=None, until=None):
        with self.lock:
            rows = self.db.execute('SELECT * FROM audit WHERE tenant=? ORDER BY seq',(tenant,)).fetchall()
        events=[{'seq':r['seq'],**json.loads(r['event']),'previous':r['previous'],'digest':r['digest']} for r in rows]
        return [e for e in events
                if (not actor or e['actor']==actor)
                and (not action or e['action']==action or e['action'].startswith(action+'.'))
                and (since is None or e['time']>=since)
                and (until is None or e['time']<=until)]

    def verify(self, tenant):
        previous = '0'*64
        with self.lock:
            rows = self.db.execute('SELECT * FROM audit WHERE tenant=? ORDER BY seq',(tenant,)).fetchall()
        for row in rows:
            if row['previous'] != previous or hashlib.sha256((previous+row['event']).encode()).hexdigest() != row['digest']:
                return {'valid':False,'failed_seq':row['seq'],'events':len(rows)}
            previous = row['digest']
        return {'valid':True,'events':len(rows),'tip':previous}
