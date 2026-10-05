# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Persistence on SQLite or PostgreSQL. Tenant is mandatory on every object lookup."""
import hashlib
import json
import secrets
import time
from contextlib import contextmanager

from .db import connect


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


class Store:
    def __init__(self, path, url=None):
        self.db = connect(path, url)
        self.lock = self.db.lock
        try:
            self.db.migrate()
        except BaseException:
            self.db.close()
            raise

    @contextmanager
    def transaction(self):
        """Reentrant: nested blocks join the outermost transaction."""
        with self.lock:
            if self.db.depth:
                self.db.depth += 1
                try:
                    yield
                finally:
                    self.db.depth -= 1
                return
            self.db.begin()
            self.db.depth = 1
            try:
                yield
            except BaseException:
                self.db.depth = 0
                self.db.rollback()
                raise
            self.db.depth = 0
            self.db.commit()

    def close(self):
        self.db.close()

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
                self.db.execute('INSERT INTO objects (tenant,kind,id,data,revision,created,updated) VALUES (?,?,?,?,?,?,?)', (tenant,kind,id,canonical(clean),1,now,now))
        return self.get(tenant,kind,id)

    def delete(self, tenant, kind, id):
        with self.lock:
            if not self.db.execute('DELETE FROM objects WHERE tenant=? AND kind=? AND id=?',(tenant,kind,id)).rowcount:
                raise KeyError('Object not found')

    def audit(self, tenant, actor, action, target, detail=None):
        with self.transaction():
            self.db.lock_key('audit:'+tenant)
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

    def claim_job(self, tenant, id, worker):
        """Atomically move a queued job to running for this worker; None if another worker has it."""
        with self.transaction():
            row = self.db.execute("SELECT data FROM objects WHERE tenant=? AND kind='jobs' AND id=?"+self.db.for_update(), (tenant,id)).fetchone()
            if row is None:
                return None
            job = json.loads(row['data'])
            if job.get('status') != 'queued':
                return None
            job.update(status='running', worker=worker)
            self.db.execute("UPDATE objects SET data=?,revision=revision+1,updated=? WHERE tenant=? AND kind='jobs' AND id=?", (canonical(job),time.time(),tenant,id))
        return self.get(tenant,'jobs',id)

    def queued_jobs(self):
        with self.lock:
            rows = self.db.execute("SELECT tenant,id,data FROM objects WHERE kind='jobs' AND data LIKE ?", ('%"status":"queued"%',)).fetchall()
        return [(r['tenant'], r['id'], json.loads(r['data'])) for r in rows]

    def heartbeat(self, worker, ttl):
        now = time.time()
        with self.transaction():
            self.db.execute('DELETE FROM workers WHERE id=? OR seen<?', (worker, now-ttl))
            self.db.execute('INSERT INTO workers (id,seen) VALUES (?,?)', (worker, now))
            return {r['id'] for r in self.db.execute('SELECT id FROM workers').fetchall()}
