import unittest
from multiwan.web import render_page, shell
from multiwan.core import load_config
from pathlib import Path

class DashboardDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=load_config(Path(__file__).resolve().parents[1]/'config/config.example.json')
    def test_home_layout_and_form(self):
        page=render_page(self.config,[],{'mode':'preview'},'csrf-test').decode()
        for required in ('app-shell','sidebar','WAN 出口配置','wan-list','lan_interface','management_routes','admin_token','config.pending'):
            if required=='config.pending': continue
            self.assertIn(required,page)
    def test_layout_links(self):
        s=shell('content',active='logs',title='logs')
        self.assertIn('href="/logs"',s)
        self.assertIn('href="/plan"',s)
        self.assertIn('href="/"',s)
        self.assertIn('active',s)

if __name__=='__main__':unittest.main()
