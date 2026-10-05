# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import json
import os
import unittest
from unittest import mock

from test_evals_retrieval import StubModels
from nuvora import datasets
from nuvora.security import Fault

POLICY = {'redact_pii': True, 'detect_injection': True, 'blocked_topics': [], 'max_chars': 100000}


def chat_lines(n, answer='Use the approved runbook.'):
    return '\n'.join(json.dumps({'messages': [{'role': 'user', 'content': f'Question {i}?'}, {'role': 'assistant', 'content': answer}]}) for i in range(n))


def prompt_lines(n):
    return '\n'.join(json.dumps({'prompt': f'Explain topic {i}'}) for i in range(n))


class DatasetValidationTests(unittest.TestCase):
    def test_formats_and_stats(self):
        stats, content = datasets.validate(chat_lines(12)+'\n\n', POLICY)
        self.assertEqual((stats['format'], stats['records']), ('chat', 12))
        self.assertEqual(len(content.splitlines()), 12)
        stats, _ = datasets.validate('\n'.join(json.dumps({'prompt': f'p{i}', 'completion': 'c'}) for i in range(10)), POLICY)
        self.assertEqual(stats['format'], 'completion')
        self.assertEqual(datasets.validate(prompt_lines(10), POLICY)[0]['format'], 'prompts')

    def test_errors_name_lines(self):
        bad = chat_lines(10)+'\nnot json\n'+json.dumps({'messages': [{'role': 'user', 'content': 'q'}]})+'\n'+json.dumps({'prompt': 'x'})
        with self.assertRaises(Fault) as ctx:
            datasets.validate(bad, POLICY)
        message = str(ctx.exception)
        self.assertIn('3 invalid record(s)', message)
        self.assertIn('line 11: not valid JSON', message)
        self.assertIn('line 12: messages need', message)
        self.assertIn('line 13: prompts record in a chat dataset', message)
        with self.assertRaisesRegex(Fault, 'at least 10'):
            datasets.validate(chat_lines(3), POLICY)

    def test_pii_is_redacted_and_counted(self):
        stats, content = datasets.validate(chat_lines(10, 'Mail ops@example.com'), POLICY)
        self.assertEqual(stats['pii_redacted_records'], 10)
        self.assertNotIn('ops@example.com', content)


class TrainingTests(StubModels):
    def setUp(self):
        super().setUp()
        self.remote = {'status': 'running', 'progress': 0.4}
        self.submitted = []

        def submit(handler, body):
            self.submitted.append(body)
            return 200, {'id': 't1', 'status': 'queued'}
        self.trainer, _ = self.stub({('POST', '/v1/training/jobs'): submit, ('GET', '/v1/training/jobs/t1'): lambda h, b: (200, self.remote)})
        self.env = mock.patch.dict(os.environ, {'NUVORA_TRAINER_URL': self.trainer})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.base = self.openai_model(lambda m: 'base answer', 'Base')

    def dataset(self, text, **extra):
        return self.json('/api/datasets', {'name': 'Support', 'content': text, **extra}, expect=200 if extra.get('dry_run') else 201)

    def recipe(self, dataset_id, method='lora', **extra):
        return self.json('/api/recipes', {'name': 'Support tune', 'model': self.base, 'method': method, 'dataset_id': dataset_id, 'rank': 8, 'epochs': 2, **extra}, expect=201)

    def run_recipe(self, rid):
        job = self.json(f'/api/recipes/{rid}/run', {}, expect=202)
        self.app.process_job(self.p, job['id'])
        return self.app.get(self.p, 'jobs', job['id'])

    def test_dataset_api(self):
        dry = self.dataset(chat_lines(10), dry_run=True)
        self.assertEqual((dry['records'], dry['stored']), (10, False))
        self.assertEqual(self.json('/api/datasets', expect=200)['items'], [])
        stored = self.dataset(chat_lines(10))
        listed = self.json('/api/datasets', expect=200)['items']
        self.assertEqual([d['id'] for d in listed], [stored['id']])
        self.assertNotIn('content', listed[0])
        self.assertNotIn('content', self.json('/api/datasets/'+stored['id'], expect=200))
        self.json('/api/datasets', {'name': 'x', 'content': chat_lines(10)}, token=self.viewer, expect=403)
        self.json('/api/datasets', {'name': 'x', 'content': 'nope'}, expect=422)

    def test_recipe_validation(self):
        prompts = self.dataset(prompt_lines(10))['id']
        self.json('/api/recipes', {'name': 'r', 'model': self.base, 'method': 'lora', 'dataset_id': prompts}, expect=400)
        self.json('/api/recipes', {'name': 'r', 'model': self.base, 'method': 'distillation', 'dataset_id': prompts}, expect=400)
        self.json('/api/recipes', {'name': 'r', 'model': self.base, 'method': 'lora', 'rank': 999}, expect=400)
        rid = self.recipe(self.dataset(chat_lines(10))['id'])['id']
        self.assertEqual(self.json('/api/recipes/'+rid, expect=200)['status'], 'ready to train')
        export = self.json('/api/recipes', {'name': 'e', 'model': self.base, 'method': 'quantization'}, expect=201)
        self.json(f"/api/recipes/{export['id']}/run", {}, expect=400)
        self.json(f'/api/recipes/{rid}/run', {}, token=self.dev, expect=403)
        with mock.patch.dict(os.environ, {'NUVORA_TRAINER_URL': ''}):
            self.json(f'/api/recipes/{rid}/run', {}, expect=503)

    def test_training_submits_polls_and_registers_the_model(self):
        ds = self.dataset(chat_lines(10))
        rid = self.recipe(ds['id'])['id']
        job = self.run_recipe(rid)
        self.assertEqual(job['status'], 'waiting_external')
        sent = self.submitted[0]
        self.assertEqual((sent['base_model'], sent['method'], sent['hyperparameters']), ('m', 'lora', {'rank': 8, 'epochs': 2}))
        self.assertEqual((sent['dataset']['format'], sent['dataset']['records'], sent['dataset']['digest']), ('chat', 10, ds['digest']))
        self.assertEqual(self.app.get(self.p, 'recipes', rid)['status'], 'training (trainer job t1)')
        self.app.poll_training()
        waiting = self.app.get(self.p, 'jobs', job['id'])
        self.assertEqual((waiting['status'], waiting['checkpoint']['training']['progress']), ('waiting_external', 0.4))
        self.remote = {'status': 'succeeded', 'result': {'model': 'm-support-ft', 'base_url': self.trainer+'/v1', 'metrics': {'loss': 0.21}}}
        self.app.poll_training()
        self.assertEqual(self.app.get(self.p, 'jobs', job['id'])['status'], 'queued')
        self.app.process_job(self.p, job['id'])
        done = self.app.get(self.p, 'jobs', job['id'])
        self.assertEqual(done['status'], 'completed', done.get('error'))
        model = self.app.get(self.p, 'models', done['result']['model'])
        self.assertEqual((model['upstream_model'], model['name']), ('m-support-ft', 'Support tune · tuned'))
        self.assertEqual(done['result']['metrics'], {'loss': 0.21})
        recipe = self.app.get(self.p, 'recipes', rid)
        self.assertEqual((recipe['status'], recipe['trained_model']), ('trained → Support tune · tuned', model['id']))
        self.json('/api/datasets/'+ds['id'], method='DELETE', expect=409)

    def test_failed_training_marks_the_recipe(self):
        rid = self.recipe(self.dataset(chat_lines(10))['id'])['id']
        job = self.run_recipe(rid)
        self.remote = {'status': 'failed', 'error': 'CUDA out of memory'}
        self.app.poll_training()
        failed = self.app.get(self.p, 'jobs', job['id'])
        self.assertEqual(failed['status'], 'failed')
        self.assertIn('CUDA out of memory', failed['error'])
        self.assertEqual(self.app.get(self.p, 'recipes', rid)['status'], 'training failed')

    def test_distillation_uses_the_teacher(self):
        teacher = self.openai_model(lambda m: 'Teacher says: '+m[-1]['content'], 'Teacher')
        rid = self.recipe(self.dataset(prompt_lines(10))['id'], 'distillation', teacher_model=teacher)['id']
        job = self.run_recipe(rid)
        self.assertEqual(job['status'], 'waiting_external', job.get('error'))
        sent = self.submitted[0]['dataset']
        self.assertEqual((sent['format'], sent['records']), ('chat', 10))
        first = json.loads(sent['content'].splitlines()[0])
        self.assertEqual(first['messages'][-1], {'role': 'assistant', 'content': 'Teacher says: Explain topic 0'})
        self.assertEqual(job['trace'][0], {'type': 'distillation', 'teacher': teacher, 'generated': 10, 'failed': 0})
        self.assertEqual(len(self.json('/api/datasets', expect=200)['items']), 2)
        self.json('/api/models/'+teacher, method='DELETE', expect=409)


if __name__ == '__main__':
    unittest.main()
