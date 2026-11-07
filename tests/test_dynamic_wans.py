import copy
import json
import tempfile
import unittest
from pathlib import Path
from multiwan.config_portal import validate_candidate, build_candidate_from_form, stage_config
from multiwan.core import load_config, route_command, current_state, check_lan_guard
from multiwan.deployment import plan
from multiwan.web import render_page

ROOT=Path(__file__).resolve().parents[1]

class DynamicWANTests(unittest.TestCase):
    def setUp(self):
        self.c=load_config(ROOT/'config/config.example.json')
        self.inventory=[{'name':f'eth{i}','mac':f'02:00:00:00:00:{i:02x}', 'link_up':True,'speed_mbps':1000,'addresses':[],'gateways':[]} for i in range(8)]

    def test_single_wan_variable_ips(self):
        c=copy.deepcopy(self.c)
        c['wans']=c['wans'][:1]
        c['wans'][0]['addresses']=c['wans'][0]['addresses'][:2]
        c['wans'][0]['weight']=3
        validated=validate_candidate(c,self.inventory)
        self.assertEqual(len(validated['wans']),1)
        self.assertEqual(route_command(validated,{'WAN1'})[-2:],['weight','3'])
        self.assertIn('eth1',plan(validated,validated)['ecmp_command'])

    def test_seven_wans(self):
        c=copy.deepcopy(self.c)
        c['wans'].append({'name':'WAN6','interface':'eth6','gateway':'198.51.106.1','prefix':24,'addresses':['198.51.106.2']})
        c['wans'].append({'name':'WAN7','interface':'eth7','gateway':'198.51.107.1','prefix':24,'addresses':['198.51.107.2']})
        self.assertEqual(len(validate_candidate(c,self.inventory)['wans']),7)
        self.assertIn('table: 107',plan(c,c)['netplan'])

    def test_management_route_validated_and_rendered(self):
        c=copy.deepcopy(self.c)
        c['management']={'routes':[{'destination':'10.20.0.0/16','via':'192.168.100.254'}]}
        out=plan(c,c)
        self.assertIn('10.20.0.0/16',out['netplan'])
        wrong=copy.deepcopy(c);wrong['management']['routes'][0]['via']='192.168.200.1'
        with self.assertRaises(ValueError):validate_candidate(wrong)

    def test_management_route_checked_live(self):
        c=copy.deepcopy(self.c)
        c['management']={'routes':[{'destination':'10.20.0.0/16','via':'192.168.100.254'}]}
        addr='[{"addr_info":[{"local":"192.168.100.1","prefixlen":24}]}]'
        route='[{"dst":"192.168.100.0/24","dev":"eth0"}]'
        with self.assertRaisesRegex(RuntimeError,'management route'):
            check_lan_guard(c,address_output=addr,route_output=route)
        route='[{"dst":"192.168.100.0/24","dev":"eth0"},{"dst":"10.20.0.0/16","dev":"eth0","gateway":"192.168.100.254"}]'
        self.assertTrue(check_lan_guard(c,address_output=addr,route_output=route))

    def test_remove_wans_form(self):
        c=copy.deepcopy(self.c)
        form={'lan_interface':'eth0','lan_address':'192.168.100.1/24','lan_subnet':'192.168.100.0/24','wan_count':'1',
              'wan1_name':'WAN1','wan1_interface':'eth1','wan1_gateway':'198.51.100.1','wan1_prefix':'24','wan1_weight':'2','wan1_ips':'198.51.100.2,198.51.100.3',
              'management_routes':'10.20.0.0/16 192.168.100.254'}
        new=validate_candidate(build_candidate_from_form(c,form),self.inventory)
        self.assertEqual(len(new['wans']),1)
        self.assertEqual(len(new['wans'][0]['addresses']),2)
        self.assertEqual(len(new['management']['routes']),1)

    def test_dashboard_contains_dynamic_controls(self):
        h=render_page(self.c,self.inventory,{},'example').decode()
        self.assertIn('wan_count',h)
        self.assertIn('id="add-wan"',h)
        self.assertIn('management_routes',h)
        self.assertIn('198.51.105.2',h)

    def test_web_forced_loopback(self):
        c=copy.deepcopy(self.c)
        c['web']['host']='0.0.0.0'
        self.assertEqual(validate_candidate(c)['web']['host'],'127.0.0.1')

if __name__=='__main__': unittest.main()
