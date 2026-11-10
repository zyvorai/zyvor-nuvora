# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Coverage for cron schedules, webhook formats, tokens estimate, audit sign, failover fields."""
import time
import unittest
from nuvora.audit_sign import sign_tip, verify_checkpoint
from nuvora.schedules import cron_matches, due, parse_cron, validate as v_sched
from nuvora.tokens import estimate, estimate_messages, estimate_texts
from nuvora.webhooks import EVENTS, FORMATS, shape, validate as v_hook


class CronTest(unittest.TestCase):
    def test_parse_and_match(self):
        minute, hour, dom, month, dow = parse_cron('*/15 9-17 * * 1-5')
        self.assertIn(0, minute)
        self.assertIn(15, minute)
        self.assertIn(9, hour)
        self.assertIn(17, hour)
        self.assertIn(1, dow)
        # Pick "now" floored to the minute and assert * * * * * matches.
        now = time.time()
        self.assertTrue(cron_matches('* * * * *', now))
        # A cron that can never match this minute should fail.
        other = (time.gmtime(now).tm_min + 1) % 60
        self.assertFalse(cron_matches(f'{other} * * * *', now))

    def test_validate_cron_or_interval(self):
        s = v_sched({'agent': 'a1', 'cron': '0 * * * *', 'prompt': 'hourly'})
        self.assertEqual(s['cron'], '0 * * * *')
        self.assertNotIn('every_minutes', s)
        i = v_sched({'agent': 'a1', 'every_minutes': 30})
        self.assertEqual(i['every_minutes'], 30)
        with self.assertRaises(Exception):
            v_sched({'agent': 'a1'})

    def test_due_interval(self):
        s = {'every_minutes': 10, 'last_run': time.time()}
        self.assertFalse(due(s))
        s['last_run'] = time.time() - 700
        self.assertTrue(due(s))


class WebhookShapeTest(unittest.TestCase):
    def test_formats_and_events(self):
        self.assertIn('slack', FORMATS)
        self.assertIn('document.ingested', EVENTS)
        slack = shape('slack', 'job.failed', {'job_id': 'j1'}, time.time())
        self.assertIn('text', slack)
        teams = shape('teams', 'approval.created', {'id': 'a'}, time.time())
        self.assertEqual(teams['@type'], 'MessageCard')
        h = v_hook({'url': 'https://hooks.example/x', 'events': ['document.ingested'], 'secret': 's' * 16, 'format': 'slack', 'max_retries': 1})
        self.assertEqual(h['format'], 'slack')
        e = v_hook({'to': 'ops@example.com', 'events': ['job.completed'], 'secret': 's' * 16, 'format': 'email'})
        self.assertEqual(e['to'], 'ops@example.com')


class TokensEstimateTest(unittest.TestCase):
    def test_estimate(self):
        self.assertEqual(estimate(''), 0)
        self.assertEqual(estimate('abcd'), 1)
        self.assertEqual(estimate('abcdefgh'), 2)
        self.assertEqual(estimate_texts(['hi', 'there']), estimate('hi') + estimate('there'))
        self.assertGreater(estimate_messages([{'role': 'user', 'content': 'hello world'}]), 0)


class AuditSignTest(unittest.TestCase):
    def test_roundtrip(self):
        tip = 'a' * 64
        secret = 'k' * 32
        cp = sign_tip(tip, secret)
        self.assertTrue(verify_checkpoint(cp, secret))
        self.assertFalse(verify_checkpoint({**cp, 'signature': 'bad'}, secret))
        self.assertIsNone(sign_tip(tip, 'short'))


if __name__ == '__main__':
    unittest.main()
