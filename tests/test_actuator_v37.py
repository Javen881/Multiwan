import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from multiwan.core import load_config
from multiwan.actuator import (protected_config,public_addresses_are_real,verified_pool,
                               render_owned_nat,file_write,confirm,rollback,snapshot)
from multiwan.scheduler import propose,apply_recommendation
from multiwan.telemetry import connect,log_sample
ROOT=Path(__file__).resolve().parents[1]

class GuardTests(unittest.TestCase):
    def setUp(self):
        self.c=load_config(ROOT/'config/config.example.json')
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_lan_change_forbidden(self):
        b=copy.deepcopy(self.c);b['lan']['interface']='eth7'
        with self.assertRaises(ValueError): protected_config(self.c,b)
    def test_management_change_forbidden(self):
        b=copy.deepcopy(self.c);b['management']['routes']=[{'destination':'10.3.0.0/16','via':'192.168.100.2'}]
        with self.assertRaises(ValueError): protected_config(self.c,b)
    def test_dynamic_wan_count(self):
        b=copy.deepcopy(self.c);b['wans']=b['wans'][:3]
        self.assertEqual(len(protected_config(self.c,b)['wans']),3)
    def test_reject_documentary_ip_for_live(self):
        with self.assertRaises(ValueError):public_addresses_are_real(self.c)
    def test_empty_pool_refused(self):
        pools={w['name']:w['addresses'] for w in self.c['wans']}
        pools['WAN1']=[]
        with self.assertRaises(ValueError):verified_pool(self.c,pools)
    def test_snat_dynamic_four_ips(self):
        pools={w['name']:w['addresses'] for w in self.c['wans']}
        self.assertIn('numgen random mod 4',render_owned_nat(self.c,pools))
    def test_confirm_does_not_execute_host_network(self):
        file_write(self.path/'transaction.json',{'state':'pending','token':'this-is-secret','deadline':int(time.time())+300,'previous':{'nat':None,'route':'default via 1.1.1.1 dev eth1'}})
        self.assertEqual(confirm(self.path,'this-is-secret'),'confirmed')
        self.assertEqual(rollback(self.path),'no pending change')
    def test_rollback_triggers_snapshot_restore(self):
        file_write(self.path/'transaction.json',{'state':'pending','token':'t','deadline':int(time.time())+300,'previous':{'nat':None,'route':'default via 1.1.1.1 dev eth1'}})
        with patch('multiwan.actuator.restore_snapshot') as fn:
            self.assertEqual(rollback(self.path),'rolled back')
            fn.assert_called_once()

class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.c=load_config(ROOT/'config/config.example.json');self.c['wans']=self.c['wans'][:1]
        self.tmp=tempfile.TemporaryDirectory();self.db=connect(Path(self.tmp.name)/'telemetry.sqlite3')
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def insert(self,ip,failed,now=3000):
        for window in range(3):
            for j in range(4):
                at=now-window*60-15-j*5
                log_sample(self.db,wan='WAN1',source_ip=ip,kind='ip',target=f'{j%2}.example:443',outcome='timeout' if failed else 'success',at=at)
    def test_needs_three_windows(self):
        ips=self.c['wans'][0]['addresses']
        for j in range(12):log_sample(self.db,wan='WAN1',source_ip=ips[0],kind='ip',target=f'{j%2}.example:443',outcome='timeout',at=2998)
        self.insert(ips[1],False)
        self.assertIn(ips[0],propose(self.db,self.c,now=3000)['pools']['WAN1'])
    def test_switch_same_wan_after_corroboration(self):
        ips=self.c['wans'][0]['addresses'];self.insert(ips[0],True);self.insert(ips[1],False)
        p=propose(self.db,self.c,now=3000)
        self.assertNotIn(ips[0],p['pools']['WAN1'])
        self.assertIn(ips[1],p['pools']['WAN1'])
        r=apply_recommendation(self.c,p,self.tmp.name,execute=False)
        self.assertEqual(r['nat'],'proposed')
    def test_same_proposal_does_not_duplicate_audit(self):
        ips=self.c['wans'][0]['addresses'];self.insert(ips[0],True);self.insert(ips[1],False)
        p=propose(self.db,self.c,now=3000)
        first=apply_recommendation(self.c,p,self.tmp.name,execute=False)
        second=apply_recommendation(self.c,p,self.tmp.name,execute=False)
        self.assertEqual(first['nat'],'proposed')
        self.assertEqual(second['nat'],'unchanged')

    def test_all_bad_does_not_remove_final_wan(self):
        ips=self.c['wans'][0]['addresses']
        for ip in ips:self.insert(ip,True)
        p=propose(self.db,self.c,now=3000)
        self.assertEqual(p['pools']['WAN1'],ips)
        self.assertTrue(p['wan_healthy']['WAN1'])
        self.assertTrue(p['evidence']['WAN1']['all_bad_guard'])

if __name__=='__main__':unittest.main()
