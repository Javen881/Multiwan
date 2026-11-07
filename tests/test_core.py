import unittest
from pathlib import Path
from multiwan.core import load_config, current_state, route_command, update_healthy, nft_script
ROOT=Path(__file__).resolve().parents[1]
class CoreTests(unittest.TestCase):
    def setUp(self):
        self.c=load_config(ROOT/'config/config.example.json');self.s=current_state(self.c)
    def test_config(self):
        self.assertEqual(len(self.c['wans']),5)
        self.assertEqual(sum(len(x['addresses']) for x in self.c['wans']),20)
    def test_route(self):
        cmd=route_command(self.c,{'WAN1','WAN5'})
        self.assertEqual(cmd.count('nexthop'),2)
    def test_failover(self):
        for _ in range(3):update_healthy(self.c,self.s,{'WAN1':False,**{f'WAN{i}':True for i in range(2,6)}})
        self.assertFalse(self.s['wans']['WAN1']['healthy'])
        for _ in range(5):update_healthy(self.c,self.s,{f'WAN{i}':True for i in range(1,6)})
        self.assertTrue(self.s['wans']['WAN1']['healthy'])
    def test_nft(self):
        rules=nft_script(self.c,self.s)
        self.assertEqual(rules.count(' snat to '),5)
if __name__=='__main__':unittest.main()

class DecisionTests(unittest.TestCase):
    def test_local_ip_switch(self):
        from multiwan.decision import DecisionEngine
        d=DecisionEngine({'WAN1':['.2','.3','.4','.5']})
        self.assertEqual(d.flag_ip_suspect('WAN1','.2',100),'.3')
        self.assertFalse(d.assess('WAN1',100)['wan_paused'])
    def test_group_needs_independent_coverage(self):
        from multiwan.decision import DecisionEngine
        d=DecisionEngine({'WAN1':['.2','.3','.4','.5']},min_samples=4,bad_windows=3)
        for ip in ['.2','.3','.4','.5']:
            for k in range(4):d.observe(ip,'target'+str(k%2),False,100+k)
        self.assertFalse(d.assess('WAN1',104)['wan_paused'])
        self.assertFalse(d.assess('WAN1',105)['wan_paused'])
        self.assertTrue(d.assess('WAN1',106)['wan_paused'])
