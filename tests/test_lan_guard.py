import unittest
from pathlib import Path
from multiwan.core import load_config, check_lan_guard

ROOT=Path(__file__).resolve().parents[1]
class LanGuardTests(unittest.TestCase):
    def setUp(self):
        self.config=load_config(ROOT/'config/config.example.json')
        self.addr='[{"ifname":"eth0","addr_info":[{"family":"inet","local":"192.168.100.1","prefixlen":24}]}]'
        self.routes='[{"dst":"192.168.100.0/24","dev":"eth0","protocol":"kernel","scope":"link"}]'
    def test_healthy_lan(self):
        self.assertTrue(check_lan_guard(self.config,address_output=self.addr,route_output=self.routes))
    def test_bad_route_refused(self):
        with self.assertRaisesRegex(RuntimeError,'LAN connected route'):
            check_lan_guard(self.config,address_output=self.addr,route_output='[{"dst":"192.168.100.0/24","dev":"eth7"}]')
    def test_bad_address_refused(self):
        with self.assertRaisesRegex(RuntimeError,'LAN address missing'):
            check_lan_guard(self.config,address_output='[]',route_output=self.routes)
if __name__=='__main__':unittest.main()
