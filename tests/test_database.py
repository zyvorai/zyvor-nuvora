# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from dbutil import make_store
from nuvora import db
from nuvora.platform import Platform
from nuvora.security import Auth, Fault
from nuvora.store import Store


class AdapterTest(unittest.TestCase):
    def test_rows_and_placeholders(self):
        row = db.Row(a=1, b='x')
        self.assertEqual((row[0], row['b'], dict(row)), (1, 'x', {'a': 1, 'b': 'x'}))
        self.assertEqual(db.PostgresDB.translate("SELECT * FROM t WHERE a=? AND b LIKE '5%'"), "SELECT * FROM t WHERE a=%s AND b LIKE '5%%'")
        with self.assertRaises(ValueError):
            db.connect('x.db', 'mysql://nope')

    def test_legacy_sqlite_database_is_upgraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/'old.db')
            conn = sqlite3.connect(path)
            conn.executescript('''
              CREATE TABLE users (tenant TEXT NOT NULL, username TEXT NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL, PRIMARY KEY(tenant,username));
              CREATE TABLE tokens (digest TEXT PRIMARY KEY, tenant TEXT NOT NULL, username TEXT NOT NULL, role TEXT NOT NULL, expires REAL NOT NULL);
              INSERT INTO users VALUES ('default','admin','x:y','admin');''')
            conn.commit()
            conn.close()
            store = Store(path)
            columns = {r['name'] for r in store.db.execute('PRAGMA table_info(users)')}
            self.assertIn('identity', columns)
            self.assertEqual(store.db.version(), db.SCHEMA_VERSION)
            self.assertEqual(store.db.execute('SELECT role FROM users').fetchone()[0], 'admin')
            store.db.execute('UPDATE schema_version SET version=?', (db.SCHEMA_VERSION+1,))
            store.close()
            with self.assertRaises(RuntimeError):
                Store(path)


class ReplicaTest(unittest.TestCase):
    """Two stores on one database stand in for two replicas."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = str(Path(self.tmp.name)/'shared.db')
        self.a = make_store(path)
        self.b = Store(path, os.getenv('NUVORA_TEST_DATABASE_URL'))
        self.p = {'tenant': 't', 'username': 'owner', 'role': 'admin'}
        Auth(self.a).add_user('t', 'owner', 'Long-password-123', 'admin')

    def tearDown(self):
        self.a.close()
        self.b.close()
        self.tmp.cleanup()

    def test_only_one_replica_claims_a_job(self):
        for _ in range(5):
            job = self.a.put('t', 'jobs', {'name': 'run', 'type': 'batch', 'status': 'queued', 'principal': self.p})
            won = []
            barrier = threading.Barrier(2)

            def claim(store, name):
                barrier.wait()
                if store.claim_job('t', job['id'], name):
                    won.append(name)
            threads = [threading.Thread(target=claim, args=(s, n)) for s, n in ((self.a, 'a'), (self.b, 'b'))]
            [t.start() for t in threads]
            [t.join() for t in threads]
            self.assertEqual(len(won), 1)
            self.assertEqual(self.a.get('t', 'jobs', job['id'])['worker'], won[0])
            self.assertIsNone(self.b.claim_job('t', job['id'], 'late'))

    def test_audit_chain_survives_concurrent_writers(self):
        def write(store, who):
            for i in range(25):
                store.audit('t', who, 'test.event', str(i))
        threads = [threading.Thread(target=write, args=(s, n)) for s, n in ((self.a, 'a'), (self.b, 'b'))]
        [t.start() for t in threads]
        [t.join() for t in threads]
        result = self.a.verify('t')
        self.assertTrue(result['valid'], result)
        self.assertEqual(result['events'], 50)

    def test_login_throttle_is_shared(self):
        one, two = Auth(self.a), Auth(self.b)
        for i in range(10):
            with self.assertRaises(Fault):
                (one if i % 2 else two).login('t', 'owner', 'wrong-password')
        with self.assertRaises(Fault) as ctx:
            one.login('t', 'owner', 'Long-password-123')
        self.assertEqual(ctx.exception.status, 429)

    def test_recovery_spares_live_workers(self):
        app = Platform(self.a, Auth(self.a))
        mine = self.a.put('t', 'jobs', {'name': 'x', 'type': 'batch', 'status': 'running', 'worker': 'live-replica', 'principal': self.p})
        gone = self.a.put('t', 'jobs', {'name': 'y', 'type': 'batch', 'status': 'running', 'worker': 'dead-replica', 'principal': self.p})
        self.b.heartbeat('live-replica', 45)
        app.recover(self.a.heartbeat(app.instance, 45))
        self.assertEqual(self.a.get('t', 'jobs', mine['id'])['status'], 'running')
        self.assertEqual(self.a.get('t', 'jobs', gone['id'])['status'], 'interrupted')
