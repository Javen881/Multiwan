import tempfile
import unittest
from pathlib import Path
from multiwan.telemetry import connect, log_sample, log_decision, get_dashboard, evaluate_wan

class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.tmp.name)/'telemetry.sqlite3')
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def test_no_samples_is_not_failure(self):
        r=evaluate_wan(self.db,'WAN1',at=1000)
        self.assertFalse(r['sufficient']);self.assertEqual(r['recommendation'],'observe')
    def test_simulated_excluded_from_failure_rate(self):
        for i in range(30):
            log_sample(self.db,wan='WAN1',target='a',outcome='timeout',origin='simulated',at=1000+i)
        self.assertEqual(get_dashboard(self.db,now=1030)['metrics'],[])
        self.assertEqual(evaluate_wan(self.db,'WAN1',at=1030)['recommendation'],'observe')
    def test_multitarget_gated_advisory(self):
        for i in range(12):
            log_sample(self.db,wan='WAN1',target=('a' if i%2 else 'b'),outcome='timeout',at=990+i)
        r=evaluate_wan(self.db,'WAN1',at=1002)
        self.assertEqual(r['recommendation'],'investigate')
        self.assertEqual(r['failures'],12)
    def test_refused_not_counted_as_failure(self):
        log_sample(self.db,wan='WAN1',target='a',outcome='refused',at=1000)
        self.assertEqual(evaluate_wan(self.db,'WAN1',at=1000)['samples'],0)
    def test_decision_evidence_retained(self):
        log_decision(self.db,scope='ip',subject='test.2',action='prefer_next_ip',reason='probe',evidence={'samples':18},at=1000)
        self.assertIn('"samples": 18',get_dashboard(self.db,now=1000)['decisions'][0]['evidence'])
if __name__=='__main__':unittest.main()
