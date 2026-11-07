import json
import tempfile
import unittest
from pathlib import Path
from multiwan.core import load_config
from multiwan.deployment import render_netplan, config_diff, plan

ROOT=Path(__file__).resolve().parents[1]
class DeploymentTests(unittest.TestCase):
    def setUp(self): self.c=load_config(ROOT/'config/config.example.json')
    def test_netplan_has_all_six_interfaces(self):
        y=render_netplan(self.c)
        for i in range(6): self.assertIn(f'    eth{i}:',y)
        self.assertNotIn('      gateway4:',y)
        self.assertIn('        - to: 192.168.100.0/24',y)
        for table in range(101,106): self.assertIn(f'          table: {table}',y)
    def test_diff_detects_changes(self):
        pending=json.loads(json.dumps(self.c));pending['wans'][0]['gateway']='198.51.100.6'
        self.assertIn('198.51.100.6',config_diff(self.c,pending))
    def test_lan_change_flagged(self):
        pending=json.loads(json.dumps(self.c))
        pending['lan']['interface']='eth7'
        r=plan(self.c,pending)
        self.assertTrue(r['lan_changed'])
        self.assertTrue(r['lan_protected'])
        self.assertTrue(any('禁止' in x for x in r['warnings']))
    def test_plan_never_mutates(self):
        before=json.dumps(self.c,sort_keys=True)
        r=plan(self.c,self.c)
        self.assertFalse(r['changed'])
        self.assertIn('nexthop',r['ecmp_command'])
        self.assertIn('127.0.0.1',before)
        self.assertEqual(before,json.dumps(self.c,sort_keys=True))
    def test_plan_does_not_claim_dynamic_ip(self):
        r=plan(self.c,self.c)
        self.assertTrue(any('尚未接入' in x for x in r['warnings']))
if __name__=='__main__':unittest.main()
