import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from multiwan.core import load_config
from multiwan.telemetry import connect,log_sample
from multiwan.ip_probe import route_uses_interface,scan
from multiwan.ip_policy import propose_pools,render_snat_pools

ROOT=Path(__file__).resolve().parents[1]

class IPProbePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.tmp.name)/'test.sqlite3')
        self.c=load_config(ROOT/'config/config.example.json')
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def test_mismatch_route_never_counts_as_failure(self):
        cfg={**self.c, 'wans':self.c['wans'][:1]}
        results=scan(cfg,self.db,targets=[('1.1.1.1',443)],route_checker=lambda *a:False)
        self.assertTrue(all(x['outcome']=='unknown' for x in results))
        p=propose_pools(self.db,cfg)
        self.assertEqual(p[0]['ips'],cfg['wans'][0]['addresses'])
    def test_route_check_uses_real_interface(self):
        def runner(*args, **kwargs):return Mock(returncode=0,stdout=json.dumps([{'dev':'eth2','src':'198.51.100.2'}]))
        self.assertFalse(route_uses_interface('198.51.100.2','1.1.1.1','eth1',runner))
    def test_confirmed_bad_ip_uses_same_group_good_ip(self):
        cfg={**self.c,'wans':self.c['wans'][:1]}
        wan=cfg['wans'][0]
        for ip in wan['addresses'][:2]:
            for k in range(12):
                log_sample(self.db,wan=wan['name'],source_ip=ip,target=f'{k%2}.example:443',kind='ip',
                           outcome='timeout' if ip==wan['addresses'][0] else 'success',at=1000+k)
        proposals=propose_pools(self.db,cfg,now=1020,window=60)
        self.assertNotIn(wan['addresses'][0],proposals[0]['ips'])
        self.assertIn(wan['addresses'][1],proposals[0]['ips'])
        self.assertIn('numgen random mod 3',render_snat_pools(cfg,proposals))
    def test_no_corroboration_retains_all(self):
        cfg={**self.c,'wans':self.c['wans'][:1]}
        wan=cfg['wans'][0]
        for k in range(12):
            log_sample(self.db,wan=wan['name'],source_ip=wan['addresses'][0],
                       target=f'{k%2}.example:443',kind='ip',outcome='timeout',at=1000+k)
        p=propose_pools(self.db,cfg,now=1020,window=60)
        self.assertEqual(p[0]['ips'],wan['addresses'])
    def test_dynamic_one_ip(self):
        cfg={**self.c,'wans':[dict(self.c['wans'][0],addresses=['198.51.100.2'])]}
        p=propose_pools(self.db,cfg)
        self.assertIn('snat to 198.51.100.2',render_snat_pools(cfg,p))
    def test_no_live_syscalls(self):
        cfg={**self.c,'wans':self.c['wans'][:1]}
        p=propose_pools(self.db,cfg)
        self.assertEqual(p[0]['status'],'advisory')

if __name__=='__main__':unittest.main()
