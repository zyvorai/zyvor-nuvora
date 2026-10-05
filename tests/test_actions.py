import test_platform
import unittest
from unittest.mock import patch
from nuvora.security import Fault
from nuvora import actions

class ActionTests(unittest.TestCase):
    setUp=test_platform.PlatformTests.setUp
    tearDown=test_platform.PlatformTests.tearDown
    def make_action(self,method='GET'):
        return self.app.create(self.admin,'actions',{'name':'Enterprise API','url':'http://127.0.0.1:9000/tool','method':method,'input_schema':{'type':'object','properties':{'amount':{'type':'integer','minimum':0,'maximum':100}},'required':['amount']}})
    def test_action_admin_only(self):
        with self.assertRaises(Fault):self.app.create(self.dev,'actions',{'name':'Bad'})
    def test_action_url_denied(self):
        with self.assertRaises(Fault):self.app.create(self.admin,'actions',{'name':'Bad','url':'https://evil.example','method':'GET','input_schema':{'type':'object'}})
    def test_typed_arguments(self):
        a=self.make_action()
        for invalid in ({'amount':'100'},{'amount':1000},{'amount':True},{'amount':1,'extra':'bad'},{}):
            with self.assertRaises(Fault):actions.validate_arguments(a['input_schema'],invalid)
    def test_schema_no_arbitrary_nested_objects(self):
        with self.assertRaises(Fault):actions.validate_schema({'type':'object','properties':{'command':{'type':'object'}}})
    def test_agent_write_waits_for_approval(self):
        a=self.make_action('POST')
        agent=self.app.create(self.dev,'agents',{'name':'Agent','model':self.model,'tools':['action_'+a['id']],'max_steps':5})
        job=self.app.new_job(self.dev,'agent',agent['id'],{'message':'test'})
        def provider(model,messages,tools,maximum,temp):
            return {'content':'done' if any(m['role']=='tool' for m in messages) else '', 'tool_calls':[] if any(m['role']=='tool' for m in messages) else [{'id':'call1','type':'function','function':{'name':'action_'+a['id'],'arguments':'{"amount":50}'}}],'usage':{},'evidence_class':'scripted test'}
        self.app.providers.chat=provider
        with patch('nuvora.actions.execute',return_value={'accepted':True}) as execute:
            self.app.process_job(self.dev,job['id'])
            self.assertEqual(execute.call_count,0)
            approval=self.app.list(self.dev,'approvals')[0]
            self.app.decide(self.approver,approval['id'],'approved',approval['digest'])
            self.app.process_job(self.dev,job['id'])
            self.assertEqual(execute.call_count,1)
            self.assertEqual(self.app.get(self.dev,'jobs',job['id'])['status'],'completed')
    def test_workflow_write_waits_for_approval(self):
        a=self.make_action('POST')
        workflow=self.app.create(self.dev,'workflows',{'name':'Write','steps':[{'id':'write','type':'action','action_id':a['id'],'arguments':{'amount':50}}]})
        job=self.app.new_job(self.dev,'workflow',workflow['id'],{'text':'input'})
        with patch('nuvora.actions.execute',return_value={'accepted':True}) as execute:
            self.app.process_job(self.dev,job['id']);self.assertEqual(execute.call_count,0)
            approval=self.app.list(self.dev,'approvals')[0]
            self.app.decide(self.approver,approval['id'],'approved',approval['digest'])
            self.app.process_job(self.dev,job['id'])
            self.assertEqual(execute.call_count,1)
            self.assertTrue(self.app.get(self.dev,'jobs',job['id'])['result']['write']['accepted'])
    def test_approved_action_pins_specification(self):
        a=self.make_action('POST')
        workflow=self.app.create(self.dev,'workflows',{'name':'Write','steps':[{'id':'write','type':'action','action_id':a['id'],'arguments':{'amount':50}}]})
        job=self.app.new_job(self.dev,'workflow',workflow['id'],{})
        self.app.process_job(self.dev,job['id'])
        approval=self.app.list(self.dev,'approvals')[0]
        self.app.create(self.admin,'actions',{**a,'url':'http://127.0.0.1:9001/changed','expected_revision':a['revision']},a['id'])
        self.app.decide(self.approver,approval['id'],'approved',approval['digest'])
        with patch('nuvora.actions.execute',return_value={'accepted':True}) as execute:
            self.app.process_job(self.dev,job['id'])
            self.assertEqual(execute.call_args.args[0]['url'],a['url'])
