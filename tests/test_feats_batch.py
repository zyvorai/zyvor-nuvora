# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Unit coverage for the schedules/webhooks/bundles feature batch and helpers."""
import time
import unittest
from nuvora.activity import touch, last_seen
from nuvora.bundles import export, import_bundle
from nuvora.citations import overlap_score
from nuvora.freshness import prefer_fresh, score
from nuvora.retries import with_retries
from nuvora.schedules import due, validate as v_sched
from nuvora.security import Fault
from nuvora.store import Store
from nuvora.webhooks import sign, validate as v_hook
from nuvora.websearch import search


class HelpersTest(unittest.TestCase):
    def test_citation_overlap(self):
        self.assertGreater(overlap_score('Keep isolates agents in microVMs', ['Keep isolates agents in microVMs on your hosts.']), 0.5)
        self.assertEqual(overlap_score('', ['anything']), 0.0)

    def test_freshness(self):
        now = time.time()
        fresh = {'last_seen': now}
        stale = {'last_seen': now - 200 * 86400}
        self.assertGreater(score(fresh, now), score(stale, now))
        ordered = prefer_fresh([stale | {'name': 'old'}, fresh | {'name': 'new'}], now)
        self.assertEqual(ordered[0]['name'], 'new')

    def test_retries_transient(self):
        calls = {'n': 0}

        def flaky():
            calls['n'] += 1
            if calls['n'] < 3:
                raise Fault('temporarily unavailable', 503)
            return 'ok'

        self.assertEqual(with_retries(flaky, max_retries=3, base_delay=0.01), 'ok')
        self.assertEqual(calls['n'], 3)

    def test_retries_non_transient(self):
        with self.assertRaises(Fault):
            with_retries(lambda: (_ for _ in ()).throw(Fault('bad request', 400)), max_retries=2, base_delay=0.01)

    def test_websearch_unset(self):
        out = search('zyvor')
        self.assertEqual(out['results'], [])
        self.assertIn('not configured', out['note'])


class StoreBackedTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')

    def test_activity(self):
        p = {'tenant': 'default', 'username': 'alice'}
        touch(self.store, p)
        touch(self.store, p)
        self.assertIsNotNone(last_seen(self.store, 'default', 'alice'))
        item = self.store.get('default', 'activity', 'default:alice')
        self.assertEqual(item['count'], 2)

    def test_bundles_roundtrip(self):
        self.store.put('default', 'agents', {'name': 'Investigator', 'model': 'm1', 'tools': [], 'max_steps': 3})
        self.store.put('default', 'prompts', {'name': 'Brief', 'template': 'Say {{x}}', 'variables': ['x']})
        bundle = export(self.store, 'default', ['agents', 'prompts'])
        self.assertEqual(bundle['version'], 1)
        self.assertEqual(len(bundle['kinds']['agents']), 1)
        dry = import_bundle(self.store, 'default', bundle, dry_run=True)
        self.assertTrue(dry['dry_run'])
        self.assertEqual(len(dry['created']), 2)

    def test_schedule_and_webhook_validate(self):
        s = v_sched({'agent': 'a1', 'every_minutes': 15, 'prompt': 'check'})
        self.assertTrue(due(s, time.time() + 1000))
        h = v_hook({'url': 'https://hooks.example/x', 'events': ['job.completed'], 'secret': 's' * 16})
        sig, body = sign(h['secret'], {'event': 'job.completed'})
        self.assertTrue(sig)
        self.assertIn(b'job.completed', body)


if __name__ == '__main__':
    unittest.main()
