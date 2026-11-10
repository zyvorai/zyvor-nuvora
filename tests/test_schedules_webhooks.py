# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import unittest
import time
from nuvora.schedules import validate as v_sched, due
from nuvora.webhooks import validate as v_hook, sign

class ScheduleTest(unittest.TestCase):
    def test_validate(self):
        s = v_sched({'agent':'a1','every_minutes':15,'prompt':'check'})
        self.assertEqual(s['every_minutes'],15)
        self.assertTrue(due(s, time.time()+1000))  # never run
        s['last_run']=time.time()
        self.assertFalse(due(s))

    def test_invalid(self):
        with self.assertRaises(Exception):
            v_sched({'agent':'a1','every_minutes':0})

class WebhookTest(unittest.TestCase):
    def test_sign(self):
        secret='x'*20
        sig, body = sign(secret, {'event':'job.completed','data':{'id':'j1'}})
        self.assertTrue(sig)
        self.assertIn(b'job.completed', body)

if __name__=='__main__':
    unittest.main()
