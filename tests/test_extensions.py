import test_platform
from nuvora.security import Fault

# Standalone scenarios share the fixture helper without inheriting all tests.
import unittest
class ExtensionTests(unittest.TestCase):
    setUp=test_platform.PlatformTests.setUp
    tearDown=test_platform.PlatformTests.tearDown
    workflow_job=test_platform.PlatformTests.workflow_job
    def test_approval_action_tamper_refused(self):
        job,a=self.workflow_job()
        a['action']['preview']='Changed after review'
        self.store.put('a','approvals',a,a['id'])
        with self.assertRaises(Fault):self.app.decide(self.approver,a['id'],'approved',a['digest'])
    def test_versions_preserve_prompt_history(self):
        prompt=self.app.list(self.dev,'prompts')[0]
        self.app.create(self.dev,'prompts',{**prompt,'template':'Changed','expected_revision':prompt['revision']},prompt['id'])
        versions=[v for v in self.store.list('a','versions') if v['resource_id']==prompt['id']]
        self.assertEqual(len(versions),2)
        self.assertEqual(versions[1]['snapshot']['template'],prompt['template'])
    def test_edit_requires_revision(self):
        prompt=self.app.list(self.dev,'prompts')[0]
        with self.assertRaises(Fault):self.app.create(self.dev,'prompts',{'name':'bad','template':'stale'},prompt['id'])
    def test_bad_budget(self):
        with self.assertRaises(Fault):self.app.create(self.admin,'policies',{'name':'bad','daily_tokens':-1})
    def test_semantic_dimension_guard(self):
        from nuvora.retrieval import cosine
        with self.assertRaises(ValueError):cosine([1,2],[1,2,3])
    def test_service_tokens_cannot_approve(self):
        issued=self.auth.issue(self.admin,'developer',60)
        principal=self.auth.principal(issued['token'])
        self.assertEqual(principal['role'],'developer')
        with self.assertRaises(Fault):self.auth.issue(self.admin,'approver',60)
        with self.assertRaises(Fault):self.auth.issue(self.admin,'admin',60)
    def test_viewer_cannot_mint_tokens(self):
        with self.assertRaises(Fault):self.auth.issue(self.viewer,'viewer',60)
    def test_token_expiry_bounds(self):
        with self.assertRaises(Fault):self.auth.issue(self.admin,'viewer',1)
    def test_raw_provider_secret_refused(self):
        with self.assertRaises(Fault):self.app.create(self.admin,'models',{'name':'Bad','provider':'demo','upstream_model':'demo','api_key':'do-not-store'})
    def test_unknown_resource_field_refused(self):
        with self.assertRaises(Fault):self.app.create(self.dev,'prompts',{'name':'Bad','template':'hello','hidden_tool':'shell'})
