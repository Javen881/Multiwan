import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from multiwan.control_daemon import dispatch, safe_status
from multiwan.actuator import file_write

class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)
    def test_unknown_action_rejected(self):
        with self.assertRaises(ValueError):dispatch({'action':'shell','command':'id'},state=self.state)
    def test_status_hides_secrets(self):
        file_write(self.state/'transaction.json',{'state':'pending','token':'sensitive','previous':{'nat':'secret'},'candidate':{'other':'sensitive'}})
        report=dispatch({'action':'status'},state=self.state)
        self.assertNotIn('token',report['transaction'])
        self.assertNotIn('previous',report['transaction'])
        self.assertNotIn('candidate',report['transaction'])
    def test_apply_requires_staged_config(self):
        active=self.state/'config.json'
        active.write_text('{}')
        with self.assertRaisesRegex(ValueError,'No validated pending'):
            dispatch({'action':'apply'},active=active,state=self.state)
    def test_confirm_requires_token(self):
        with self.assertRaises(ValueError):dispatch({'action':'confirm','token':'x'*129},state=self.state)
    def test_rollback_pass_through(self):
        self.assertEqual(dispatch({'action':'rollback'},state=self.state)['result'],'no pending change')

if __name__=='__main__': unittest.main()
