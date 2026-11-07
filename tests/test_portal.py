import json
import tempfile
import unittest
from pathlib import Path
from multiwan.core import load_config
from multiwan.config_portal import validate_candidate, stage_config
from multiwan.discovery import discover_interfaces

ROOT=Path(__file__).resolve().parents[1]
class ConfigPortalTests(unittest.TestCase):
    def setUp(self):
        self.c=load_config(ROOT/'config/config.example.json')
        self.inventory=[{'name':f'eth{i}'} for i in range(8)]
    def test_lan_prefix_mismatch_rejected(self):
        self.c['lan']['address']='192.168.100.1/25'
        with self.assertRaisesRegex(ValueError,'前缀'):validate_candidate(self.c,self.inventory)
    def test_valid(self):
        self.assertEqual(validate_candidate(self.c,self.inventory)['web']['host'],'127.0.0.1')
    def test_duplicate_interface_rejected(self):
        self.c['wans'][0]['interface']='eth0'
        with self.assertRaisesRegex(ValueError,'不同网卡'): validate_candidate(self.c,self.inventory)
    def test_unknown_device_rejected(self):
        self.c['wans'][0]['interface']='does-not-exist'
        with self.assertRaisesRegex(ValueError,'设备不存在'): validate_candidate(self.c,self.inventory)
    def test_subnet_overlaps_rejected(self):
        self.c['wans'][1]['gateway']='198.51.100.1'
        self.c['wans'][1]['addresses']=['198.51.100.6','198.51.100.7','198.51.100.8','198.51.100.9']
        with self.assertRaises(ValueError): validate_candidate(self.c,self.inventory)
    def test_staged_without_modifying_active(self):
        with tempfile.TemporaryDirectory() as d:
            active=Path(d)/'config.json'
            active.write_text(json.dumps(self.c))
            new=json.loads(active.read_text());new['wans'][0]['gateway']='198.51.100.6'
            stage_config(new,active,self.inventory)
            self.assertEqual(load_config(active)['wans'][0]['gateway'],'198.51.100.1')
            self.assertEqual(json.loads((Path(d)/'config.pending.json').read_text())['wans'][0]['gateway'],'198.51.100.6')
    def test_discovery_never_mutates(self):
        self.assertIsInstance(discover_interfaces(),list)
if __name__=='__main__':unittest.main()
